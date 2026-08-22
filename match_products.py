"""C2 — cross-source product matching.

The integrated database holds 4,804 products across four sites and no notion that
any two of them are the same thing. Until that is fixed every cross-source model
is really four single-source models wearing a trenchcoat, so this is the first
thing MODELS-CATALOGUE.md says to build.

Approach, in the order the cheapness argues for:

  1. normalise the name -- Korean retail names carry brackets, promo words, volume
     and gift markers that have nothing to do with product identity
  2. block on the normalised brand, so 4,804 products are not compared pairwise
     (11.5M pairs) but within brand groups
  3. score with character n-gram TF-IDF cosine, plus volume agreement

Character n-grams rather than a sentence embedding, and EXP-002 says why. The first
reason given here was cost, and that was wrong -- encoding all 4,804 names took 17.7 s
and 512 MB on an idle GPU. The real reason is that a model trained for semantic textual
similarity answers "are these the same kind of thing", which for 도루코윈 3중날 면도기
and 도루코 PACE7 면도기 is yes and is useless. Identity lives in exactly the tokens STS
training teaches a model to discount: model numbers, blade counts, pack sizes.

WHAT THIS DOES NOT DO
It does not tell you how good it is. There are no ground-truth pairs, so precision
is unmeasured, and a matcher's score distribution says nothing about whether the
matches are right. `--label-sample` writes a stratified sample for a person to
label; until that comes back, treat every number here as a count, not a quality.

Usage:
  python match_products.py --dsn ... --out matches.csv
  python match_products.py --dsn ... --label-sample to-label.csv
"""

from __future__ import annotations

import argparse
import re
import sys
from itertools import combinations

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer

# Score below which a pair is not worth a person's attention. Deliberately low:
# the cost of a missed candidate is a product that never gets linked, the cost of
# a spurious one is a row in a review file.
MIN_SCORE = 0.45

# Bracketed segments are promo scaffolding in Korean retail listings -- [1+1],
# [기획], [단독] -- and never product identity.
_BRACKET = re.compile(r"[\[\(【][^\]\)】]*[\]\)】]")
# Volume/count tokens, pulled out and compared separately rather than matched as text.
_VOLUME = re.compile(r"(\d+(?:\.\d+)?)\s*(ml|mL|ML|g|G|호|매|개|정|캡슐|포)\b")
_PROMO = re.compile(
    r"(기획|한정|단독|증정|사은품|리필|본품|세트|특가|할인|무료배송|택1|\d+\s*\+\s*\d+)"
)
_SPACE = re.compile(r"\s+")

# Product form. Eyeballing the first run, nearly every wrong pair was two products
# from the same line in different forms -- "다이브인 저분자 히알루론산 세럼" matched
# to "... 토너", "레드 블레미쉬 ... 선" to "... 세럼". They share almost every
# character n-gram and differ by one short token, which is exactly what char n-grams
# cannot see. Pulled out and compared separately, like volume.
#
# Order matters: 선크림 must be tested before 크림, 클렌징오일 before 오일.
_FORMS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("sun", ("선크림", "선스틱", "선에센스", "선세럼", "선쿠션", "썬크림", "sun ")),
    ("cleanser", ("클렌징오일", "클렌징폼", "클렌징워터", "클렌저", "클렌징", "폼")),
    ("mask", ("마스크", "팩시트", "시트팩", "팩")),
    ("ampoule", ("앰플",)),
    ("serum", ("세럼", "에센스")),
    ("toner", ("토너", "스킨")),
    ("lotion", ("로션", "에멀전")),
    ("cream", ("크림",)),
    ("tint", ("틴트", "립스틱", "립글로스")),
    ("cushion", ("쿠션",)),
    ("shampoo", ("샴푸", "트리트먼트", "컨디셔너")),
    ("bodywash", ("바디워시", "샤워젤")),
    ("perfume", ("퍼퓸", "오드퍼퓸", "edp", "edt", "향수")),
    ("mist", ("미스트",)),
    ("gel", ("젤",)),
    ("balm", ("밤",)),
    ("oil", ("오일",)),
    ("powder", ("파우더",)),
)


def form_of(name: str) -> str:
    """The product form named in the title, or "" when it names none."""
    if not isinstance(name, str):
        return ""
    lowered = name.lower().replace(" ", "")
    for form, tokens in _FORMS:
        if any(token.replace(" ", "") in lowered for token in tokens):
            return form
    return ""


def normalise(name: str) -> str:
    """Product name with the retail scaffolding removed."""
    if not isinstance(name, str):
        return ""
    text = _BRACKET.sub(" ", name)
    text = _PROMO.sub(" ", text)
    text = _VOLUME.sub(" ", text)
    text = re.sub(r"[^0-9A-Za-z가-힣]+", " ", text)
    return _SPACE.sub(" ", text).strip().lower()


def volume_of(name: str) -> tuple[float, str] | None:
    """The first volume token, as (amount, unit). None when the name carries none."""
    if not isinstance(name, str):
        return None
    found = _VOLUME.search(name)
    if not found:
        return None
    unit = found.group(2).lower()
    return float(found.group(1)), "ml" if unit in ("ml",) else unit


def strip_brand(norm: str, brand: str) -> str:
    """Drop leading tokens that spell the blocked brand.

    Candidates are already blocked on brand, so a brand printed inside the name adds no
    identity the blocking has not used -- it only makes one side longer, which char n-gram
    cosine reads as difference. EXP-002 found two correct pairs missed for exactly that:
    glowpick writes "루트젠 ... 샴푸" where oliveyoung writes "려 루트젠 ... 샴푸".

    Leading only, and only when the tokens actually spell the brand. A brand named
    mid-title is usually doing work there.
    """
    if not brand or not norm:
        return norm
    tokens = norm.split()
    accumulated = ""
    cut = 0
    for position, token in enumerate(tokens):
        accumulated += token
        if accumulated == brand:
            cut = position + 1
            break
        if not brand.startswith(accumulated):
            break
    remainder = " ".join(tokens[cut:])
    # Never strip a name down to nothing: some products are named only for their brand.
    return remainder if remainder else norm


def normalise_brand(brand: object) -> str:
    if not isinstance(brand, str):
        return ""
    return _SPACE.sub("", re.sub(r"[^0-9A-Za-z가-힣]+", "", brand)).lower()


def load_products(dsn: str, strip_brand_prefix: bool = False) -> pd.DataFrame:
    import psycopg

    with psycopg.connect(dsn) as connection, connection.cursor() as cursor:
        cursor.execute("select source, product_key, name, brand, volume from product")
        frame = pd.DataFrame(
            cursor.fetchall(), columns=[c.name for c in cursor.description]
        )

    frame["norm"] = frame["name"].map(normalise)
    frame["brand_norm"] = frame["brand"].map(normalise_brand)
    # Volume from the dedicated column when the site gave one, else parsed from the name.
    frame["vol"] = [
        volume_of(v) or volume_of(n) for v, n in zip(frame["volume"], frame["name"], strict=True)
    ]
    frame["form"] = frame["name"].map(form_of)
    if strip_brand_prefix:
        frame["norm"] = [
            strip_brand(n, b) for n, b in zip(frame["norm"], frame["brand_norm"], strict=True)
        ]
    return frame[frame["norm"].str.len() > 1].reset_index(drop=True)


def _volume_agreement(a: tuple | None, b: tuple | None) -> float:
    """+1 when both sides state the same volume, -1 when they disagree, 0 when unknown.

    Unknown is not disagreement: three of the four sources leave the column empty,
    so treating a missing volume as a mismatch would reject almost every real pair.
    """
    if a is None or b is None:
        return 0.0
    if a[1] != b[1]:
        return 0.0
    return 1.0 if abs(a[0] - b[0]) < 1e-6 else -1.0


def candidates(frame: pd.DataFrame, min_score: float = MIN_SCORE) -> pd.DataFrame:
    """Cross-source pairs that might be the same product, best first."""
    vectoriser = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), min_df=1)
    matrix = vectoriser.fit_transform(frame["norm"])

    rows = []
    # Block on brand. A product's brand is the one field both sides tend to agree on,
    # and blocking on it turns 11.5M pairs into a few thousand.
    for brand, group in frame.groupby("brand_norm"):
        if not brand or len(group) < 2:
            continue
        index = group.index.to_numpy()
        sub = matrix[index]
        similarity = (sub @ sub.T).toarray()

        for i, j in combinations(range(len(index)), 2):
            left, right = frame.iloc[index[i]], frame.iloc[index[j]]
            if left["source"] == right["source"]:
                continue  # same-site duplicates are a different problem
            name_score = float(similarity[i, j])
            volume = _volume_agreement(left["vol"], right["vol"])
            # A stated disagreement about form is close to decisive: 세럼 and 토너
            # from one line are not the same product however alike their names read.
            # Silence on either side is not disagreement -- many titles name no form.
            form_a, form_b = left["form"], right["form"]
            if form_a and form_b:
                form = 1.0 if form_a == form_b else -1.0
            else:
                form = 0.0
            score = name_score + 0.15 * volume + 0.30 * form
            if score < min_score:
                continue
            rows.append(
                {
                    "score": round(score, 4),
                    "name_score": round(name_score, 4),
                    "volume_agreement": volume,
                    "form_agreement": form,
                    "form_a": form_a,
                    "form_b": form_b,
                    "brand": brand,
                    "source_a": left["source"],
                    "key_a": left["product_key"],
                    "name_a": left["name"],
                    "source_b": right["source"],
                    "key_b": right["product_key"],
                    "name_b": right["name"],
                }
            )

    return pd.DataFrame(rows).sort_values("score", ascending=False).reset_index(drop=True)


def diagnostics(frame: pd.DataFrame, pairs: pd.DataFrame) -> str:
    """What can be measured without ground truth. None of it is precision."""
    lines = [
        f"products: {len(frame)}  brands: {frame['brand_norm'].ne('').sum()} "
        f"named / {frame['brand_norm'].nunique()} distinct",
        f"products with a parsed volume: {frame['vol'].notna().sum()}",
        f"products with a recognised form: {frame['form'].ne('').sum()}",
        "",
        "per-source products:",
    ]
    for source, count in frame["source"].value_counts().items():
        lines.append(f"  {source:<12} {count:>6}")

    if pairs.empty:
        lines += ["", "no candidate pairs above the threshold"]
        return "\n".join(lines)

    lines += ["", f"candidate pairs: {len(pairs)}", "", "score distribution:"]
    for low in (0.9, 0.8, 0.7, 0.6, 0.5, 0.45):
        lines.append(f"  >= {low:.2f}  {int((pairs['score'] >= low).sum()):>6}")

    lines += ["", "source pairs matched:"]
    combo = pairs.groupby(["source_a", "source_b"]).size().sort_values(ascending=False)
    for (a, b), count in combo.items():
        lines.append(f"  {a} <-> {b}: {count}")

    # A product matching several products on the same other site is a signal that
    # something is wrong -- variants, or the matcher latching onto a shared prefix.
    conflicts = (
        pairs.groupby(["source_a", "key_a", "source_b"]).size().pipe(lambda s: s[s > 1])
    )
    lines += [
        "",
        f"one-to-many conflicts: {len(conflicts)} "
        f"(a product matched to more than one product on the same other site)",
        "",
        "NOT MEASURED: precision. There are no ground-truth pairs. Every number above",
        "is a count of what the matcher proposed, not evidence that it is right.",
        "Run --label-sample, label the file by hand, and only then quote a number.",
    ]
    return "\n".join(lines)


def label_sample(pairs: pd.DataFrame, size: int = 300, seed: int = 0) -> pd.DataFrame:
    """A stratified sample across the score range, for a person to label.

    Stratified rather than top-N: sampling only high scores measures the matcher
    where it is most confident and says nothing about where the threshold belongs.
    """
    if pairs.empty:
        return pairs
    bands = pd.cut(pairs["score"], bins=[0, 0.5, 0.6, 0.7, 0.8, 0.9, 1.1])
    per_band = max(1, size // bands.nunique())
    picked = (
        pairs.groupby(bands, observed=True, group_keys=False)
        .apply(lambda g: g.sample(min(len(g), per_band), random_state=seed))
        .reset_index(drop=True)
    )
    picked.insert(0, "is_same_product", "")  # the column a human fills in: y / n
    return picked


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn", required=True)
    parser.add_argument("--out", help="write candidate pairs here")
    parser.add_argument("--label-sample", dest="label", help="write a sample to label by hand")
    parser.add_argument("--min-score", type=float, default=MIN_SCORE)
    parser.add_argument(
        "--strip-brand", action="store_true",
        help="drop a leading brand token from the name before scoring (EXP-003)",
    )
    args = parser.parse_args()

    frame = load_products(args.dsn, strip_brand_prefix=args.strip_brand)
    pairs = candidates(frame, min_score=args.min_score)
    print(diagnostics(frame, pairs))

    if args.out:
        pairs.to_csv(args.out, index=False)
        print(f"\nwrote {args.out} ({len(pairs)} pairs)")
    if args.label:
        sample = label_sample(pairs)
        sample.to_csv(args.label, index=False)
        print(f"wrote {args.label} ({len(sample)} pairs to label by hand)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
