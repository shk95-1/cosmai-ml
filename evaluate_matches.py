"""Precision of the product matcher, from a hand-labelled sample.

Written before the labels came back, deliberately. Deciding what to compute after seeing
the answers is how a threshold gets chosen to flatter the matcher, and this file exists
because every number in EXP-001..003 is a count rather than a quality.

WHAT THIS MEASURES
Precision, by score band. Of the pairs the matcher proposed at a given score, how many
are actually the same product.

WHAT IT CANNOT MEASURE
Recall. The sample is drawn from the matcher's own candidate list, so a true pair the
matcher never proposed cannot appear in it and cannot be counted as missed. Recall needs
a different sample -- random within-brand pairs including ones the matcher scored below
threshold -- and that sample does not exist. Any recall number derived from this file
would be measuring the matcher against its own opinion.

THRESHOLD CHOICE
`--suggest-threshold` reports where precision crosses a target, but the precision at that
threshold is optimistic: it was chosen on the same labels it is scored on. Treat it as a
starting point to validate on the next batch, not as a measured operating point.

Usage:
  python evaluate_matches.py labelled.csv
  python evaluate_matches.py labelled.csv --suggest-threshold 0.90
  python evaluate_matches.py --self-check
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

# Bands reported separately. Chosen to match the sampling bands so each has labels in it.
BANDS = [(0.45, 0.60), (0.60, 0.80), (0.80, 1.00), (1.00, 1.20), (1.20, 2.00)]

YES = {"y", "yes", "1", "true", "o", "ㅇ"}
NO = {"n", "no", "0", "false", "x", "ㄴ"}


def read_labels(path: Path) -> pd.DataFrame:
    """The labelled file, with blanks dropped and unrecognised answers reported."""
    frame = pd.read_csv(path)
    if "is_same_product" not in frame or "score" not in frame:
        raise SystemExit("expected columns 'is_same_product' and 'score'")

    # Blank is decided on the original column, not on its string form. pandas renders
    # missing values differently across versions -- "nan" on 2.x, "<NA>" on 3.x -- so a
    # string comparison silently reclassified every empty cell as an unrecognised answer.
    missing = frame["is_same_product"].isna()
    raw = frame["is_same_product"].astype(str).str.strip().str.lower()
    raw = raw.where(~missing, "")
    frame["label"] = raw.map(lambda v: True if v in YES else False if v in NO else None)

    blank = int((raw == "").sum())
    unknown = int(frame["label"].isna().sum()) - blank
    if unknown:
        bad = sorted(set(raw[frame["label"].isna() & (raw != "")]))
        print(f"[경고] 알 수 없는 라벨 {unknown}건, 제외함: {bad[:6]}")

    labelled = frame[frame["label"].notna()].copy()
    labelled["label"] = labelled["label"].astype(bool)
    print(f"[측정] {len(frame)}쌍 중 라벨 {len(labelled)}건, 미기입 {blank}건")
    return labelled


def by_band(labelled: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for low, high in BANDS:
        band = labelled[(labelled["score"] >= low) & (labelled["score"] < high)]
        if band.empty:
            rows.append({"band": f"{low:.2f}-{high:.2f}", "n": 0, "correct": 0,
                         "precision": float("nan")})
            continue
        correct = int(band["label"].sum())
        rows.append(
            {
                "band": f"{low:.2f}-{high:.2f}",
                "n": len(band),
                "correct": correct,
                "precision": correct / len(band),
            }
        )
    return pd.DataFrame(rows)


def cumulative(labelled: pd.DataFrame) -> pd.DataFrame:
    """Precision of everything at or above each band floor -- how an operating point reads."""
    rows = []
    for low, _ in BANDS:
        at_or_above = labelled[labelled["score"] >= low]
        if at_or_above.empty:
            continue
        correct = int(at_or_above["label"].sum())
        rows.append(
            {
                "threshold": f">= {low:.2f}",
                "n": len(at_or_above),
                "correct": correct,
                "precision": correct / len(at_or_above),
            }
        )
    return pd.DataFrame(rows)


def wilson(correct: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval. Normal approximation breaks near 0 and 1, which is exactly
    where a good matcher's top band sits, and small bands here will hold ~15 pairs."""
    if total == 0:
        return (float("nan"), float("nan"))
    p = correct / total
    denom = 1 + z**2 / total
    centre = (p + z**2 / (2 * total)) / denom
    spread = z * ((p * (1 - p) / total + z**2 / (4 * total**2)) ** 0.5) / denom
    return (max(0.0, centre - spread), min(1.0, centre + spread))


def report(labelled: pd.DataFrame, target: float | None) -> str:
    lines = ["", "[측정] 점수 구간별 정밀도", ""]
    lines.append(f"{'구간':<14}{'n':>5}{'정답':>6}{'정밀도':>9}{'95% 구간':>18}")
    for row in by_band(labelled).itertuples():
        if row.n == 0:
            lines.append(f"{row.band:<14}{0:>5}{'':>6}{'라벨 없음':>12}")
            continue
        low, high = wilson(row.correct, row.n)
        lines.append(
            f"{row.band:<14}{row.n:>5}{row.correct:>6}{row.precision:>9.1%}"
            f"{f'{low:.1%} - {high:.1%}':>18}"
        )

    lines += ["", "[측정] 임계값별 누적 정밀도 (실제 운용 형태)", ""]
    lines.append(f"{'임계값':<14}{'n':>5}{'정답':>6}{'정밀도':>9}{'95% 구간':>18}")
    cum = cumulative(labelled)
    for row in cum.itertuples():
        low, high = wilson(row.correct, row.n)
        lines.append(
            f"{row.threshold:<14}{row.n:>5}{row.correct:>6}{row.precision:>9.1%}"
            f"{f'{low:.1%} - {high:.1%}':>18}"
        )

    if target is not None:
        hit = cum[cum["precision"] >= target]
        lines += [""]
        if hit.empty:
            lines.append(
                f"[추론] 어떤 임계값에서도 정밀도 {target:.0%}에 도달하지 못한다. "
                "매처를 고치는 것이 임계값을 올리는 것보다 먼저다."
            )
        else:
            best = hit.iloc[0]
            lines.append(
                f"[추론] {best.threshold} 에서 정밀도 {best.precision:.1%} "
                f"(n={best.n}) — 목표 {target:.0%} 충족."
            )
            lines.append(
                "  다만 이 임계값은 이 라벨로 고른 것이므로 여기서의 정밀도는 낙관적이다. "
                "다음 배치로 검증하기 전까지는 운용값이 아니라 출발점이다."
            )

    lines += [
        "",
        "[측정 아님] 재현율은 계산하지 않았고 계산할 수 없다. 표본이 매처가 제안한 후보에서",
        "뽑혔으므로, 매처가 놓친 참 쌍은 이 파일에 나타날 수 없다. 재현율을 재려면 임계값",
        "아래를 포함한 무작위 브랜드 내 쌍을 따로 라벨링해야 한다.",
    ]
    return "\n".join(lines)


def _self_check() -> None:
    """Synthetic labels only -- checks the arithmetic, not the matcher."""
    frame = pd.DataFrame(
        {
            "score": [1.30, 1.10, 0.95, 0.85, 0.70, 0.65, 0.50, 0.47],
            "is_same_product": ["y", "y", "y", "n", "y", "n", "n", ""],
        }
    )
    path = Path("_selfcheck_labels.csv")
    frame.to_csv(path, index=False)
    try:
        labelled = read_labels(path)
        assert len(labelled) == 7, len(labelled)  # the blank is dropped
        bands = by_band(labelled).set_index("band")
        assert bands.loc["1.20-2.00", "n"] == 1
        assert bands.loc["0.80-1.00", "correct"] == 1  # 0.95 yes, 0.85 no
        assert abs(bands.loc["0.80-1.00", "precision"] - 0.5) < 1e-9
        cum = cumulative(labelled).set_index("threshold")
        assert cum.loc[">= 0.45", "n"] == 7
        assert cum.loc[">= 1.00", "correct"] == 2
        low, high = wilson(2, 2)
        assert 0.0 < low < 1.0 and high == 1.0, (low, high)  # never reports 100% certainty
    finally:
        path.unlink(missing_ok=True)
    print("self-check OK")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("labelled", nargs="?", type=Path, help="the filled-in CSV")
    parser.add_argument("--suggest-threshold", type=float, default=None,
                        help="report the lowest threshold reaching this precision")
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()

    if args.self_check:
        _self_check()
        return 0
    if not args.labelled:
        parser.error("give the labelled CSV, or --self-check")

    labelled = read_labels(args.labelled)
    if labelled.empty:
        raise SystemExit("라벨이 하나도 없다. is_same_product 열에 y/n 을 채워야 한다.")
    print(report(labelled, args.suggest_threshold))
    return 0


if __name__ == "__main__":
    sys.exit(main())
