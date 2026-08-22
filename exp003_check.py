"""EXP-003 — run the matcher with and without brand stripping and check the declaration.

Reports exactly the three things the falsification condition names, and nothing else.
"""

from __future__ import annotations

import argparse
import sys

import pandas as pd

from exp002_compare import all_cross_source_pairs, silver_positives
from match_products import candidates, load_products

# The two pairs EXP-002 found: correct, and missed by n-grams. Identified by a substring
# of each side's name so the test does not depend on product keys.
NAMED_PAIRS = (
    ("루트젠 여성 맞춤", "려 루트젠 여성맞춤볼륨"),
    ("바쿠 글로우 캡슐 로션", "온그리디언츠 바쿠글로우 캡슐 로션"),
)
BUDGET = 675


def rank_of(pairs: pd.DataFrame, left: str, right: str) -> int | None:
    """Rank of the named pair in a score-sorted candidate frame, or None if absent."""
    if pairs.empty:
        return None
    names_a, names_b = pairs["name_a"].astype(str), pairs["name_b"].astype(str)
    hit = pairs[
        (names_a.str.contains(left, regex=False) & names_b.str.contains(right, regex=False))
        | (names_a.str.contains(right, regex=False) & names_b.str.contains(left, regex=False))
    ]
    return None if hit.empty else int(hit.index[0])


def conflicts(pairs: pd.DataFrame) -> int:
    if pairs.empty:
        return 0
    grouped = pairs.groupby(["source_a", "key_a", "source_b"]).size()
    return int((grouped > 1).sum())


def run(dsn: str, strip: bool) -> dict:
    frame = load_products(dsn, strip_brand_prefix=strip)
    pairs = candidates(frame)
    all_pairs = all_cross_source_pairs(frame)
    silver = silver_positives(frame, all_pairs)

    # Silver recovery measured against the same candidate output the matcher emits.
    keys = {
        (frame.index[(frame["source"] == r.source_a) & (frame["product_key"] == r.key_a)][0],
         frame.index[(frame["source"] == r.source_b) & (frame["product_key"] == r.key_b)][0])
        for r in pairs.head(BUDGET).itertuples()
    }
    recovered = sum(1 for s in silver if s in keys or (s[1], s[0]) in keys)

    return {
        "pairs": len(pairs),
        "above_090": int((pairs["score"] >= 0.90).sum()) if not pairs.empty else 0,
        "conflicts": conflicts(pairs),
        "silver_total": len(silver),
        "silver_recovered": recovered,
        "ranks": [rank_of(pairs, a, b) for a, b in NAMED_PAIRS],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn", required=True)
    args = parser.parse_args()

    base = run(args.dsn, strip=False)
    strip = run(args.dsn, strip=True)

    print("[측정] baseline vs brand-stripped")
    print(f"{'':<22}{'baseline':>12}{'stripped':>12}")
    for label, key in (
        ("candidate pairs", "pairs"),
        ("score >= 0.90", "above_090"),
        ("one-to-many conflicts", "conflicts"),
        ("silver recovered", "silver_recovered"),
    ):
        print(f"{label:<22}{base[key]:>12}{strip[key]:>12}")
    print(f"{'silver total':<22}{base['silver_total']:>12}{strip['silver_total']:>12}")

    print("\n[측정] rank of the two pairs EXP-002 named (None = not a candidate)")
    for (left, _), b, s in zip(NAMED_PAIRS, base["ranks"], strip["ranks"], strict=True):
        print(f"  {left[:26]:<28} baseline {str(b):>6}   stripped {str(s):>6}")

    print("\n[측정] falsification checks")
    fail1 = any(r is None or r >= BUDGET for r in strip["ranks"])
    fail2 = strip["silver_recovered"] < base["silver_total"]
    growth = (strip["conflicts"] - base["conflicts"]) / max(base["conflicts"], 1)
    fail3 = growth > 0.30
    print(f"  1. a named pair still outside top {BUDGET}: {'MET' if fail1 else 'not met'}")
    print(f"  2. silver recovery below {base['silver_total']}/{base['silver_total']}: "
          f"{'MET' if fail2 else 'not met'}")
    print(f"  3. conflicts up more than 30% ({growth:+.1%}): {'MET' if fail3 else 'not met'}")
    print(f"\n  => {'REFUTED' if (fail1 or fail2 or fail3) else 'SUPPORTED'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
