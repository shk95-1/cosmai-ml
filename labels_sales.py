"""Sales-volume labels from Korea Customs duty-free statistics.

This is the only label axis with real data today. The other three axes named in the
project brief -- academic trend, keyword interest, new-product launch -- depend on
collector output that Cosmai P0-B has not produced yet. See README.md for the specs.

Granularity warning: these files are category-level (`화장품`, `향수`), not
ingredient- or product-level. Sales can therefore only label a whole category. Any
per-ingredient target has to come from a different source or from an allocation
assumption written down as such.

Inputs (from the `project-data` repo, `datasets/`):
  관세청_면세점_품목별_내외국인_매출현황_20250905.xlsx   monthly, per item category
  관세청_면세점_매출액_및_이용객수_20260430.xlsx          monthly totals + visitors

Usage:
  uv run labels_sales.py [DATASETS_DIR] [-o OUT.csv]
  uv run labels_sales.py --self-check
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

DEFAULT_DATASETS = Path(__file__).resolve().parent.parent / "project-data" / "datasets"

CATEGORY_FILE = "관세청_면세점_품목별_내외국인_매출현황_20250905.xlsx"
TOTALS_FILE = "관세청_면세점_매출액_및_이용객수_20260430.xlsx"

# Sheets are read positionally: the files use Korean sheet names that differ between
# releases, but the order (resident, then foreign visitor) has been stable.
SEGMENTS = ("resident", "foreign")

# The category file carries no unit row. Summing all categories for a month reproduces
# the monthly total in `TOTALS_FILE` once converted at roughly 1,100-1,300 KRW/USD,
# which puts the unit at 억원 (0.1 bn KRW). Treated as an assumption, not a fact:
# re-check it against a fresh release before quoting an absolute number. Growth rates,
# which is all the label uses, are unit-free.
CATEGORY_UNIT = "eok_krw_assumed"


def _month_from_excel_serial(col: pd.Series) -> pd.Series:
    """Column 0 of the category file holds Excel serial dates (43466 -> 2019-01-01)."""
    return pd.to_datetime(col.astype(float), unit="D", origin="1899-12-30").dt.to_period("M")


def read_category_monthly(datasets: Path) -> pd.DataFrame:
    """Return tidy monthly sales per item category: month, segment, category, value."""
    book = pd.ExcelFile(datasets / CATEGORY_FILE)
    frames = []
    for segment, sheet in zip(SEGMENTS, book.sheet_names[: len(SEGMENTS)], strict=True):
        raw = book.parse(sheet)
        raw = raw.rename(columns={raw.columns[0]: "month"})
        raw = raw[raw["month"].notna()]
        raw["month"] = _month_from_excel_serial(raw["month"])
        tidy = raw.melt(id_vars="month", var_name="category", value_name="value")
        tidy["segment"] = segment
        frames.append(tidy)
    out = pd.concat(frames, ignore_index=True)
    out["value"] = pd.to_numeric(out["value"], errors="coerce")
    return out.dropna(subset=["value"]).sort_values(["month", "segment", "category"])


def read_totals_monthly(datasets: Path) -> pd.DataFrame:
    """Return monthly duty-free totals: month, segment, sales_musd, visitors_k."""
    book = pd.ExcelFile(datasets / TOTALS_FILE)
    sales = book.parse(book.sheet_names[0])
    visitors = book.parse(book.sheet_names[1])
    frames = []
    for i, segment in enumerate(SEGMENTS, start=1):
        frames.append(
            pd.DataFrame(
                {
                    "month": pd.to_datetime(sales.iloc[:, 0]).dt.to_period("M"),
                    "segment": segment,
                    "sales_musd": pd.to_numeric(sales.iloc[:, i], errors="coerce"),
                    "visitors_k": pd.to_numeric(visitors.iloc[:, i], errors="coerce"),
                }
            )
        )
    return pd.concat(frames, ignore_index=True).dropna(subset=["sales_musd"])


def cosmetics_labels(datasets: Path = DEFAULT_DATASETS, horizon: int = 3) -> pd.DataFrame:
    """Monthly cosmetics sales label table.

    Columns:
      month             calendar month
      sales             화장품 + 향수, both segments summed (unit: see CATEGORY_UNIT)
      per_visitor       sales divided by total visitors, removes travel-volume swings
      yoy               year-over-year growth of `sales`, the realised signal
      target_yoy_fwd    `yoy` shifted back by `horizon` months -- the value a model
                        standing at `month` is asked to predict. NaN at the tail.

    `per_visitor` matters because 2020-2022 duty-free volume collapsed for reasons that
    have nothing to do with beauty demand. A model trained on raw `yoy` will learn the
    pandemic, not the category.
    """
    cats = read_category_monthly(datasets)
    beauty = cats[cats["category"].isin(["화장품", "향수"])]
    sales = beauty.groupby("month", as_index=False)["value"].sum().rename(columns={"value": "sales"})

    visitors = (
        read_totals_monthly(datasets).groupby("month", as_index=False)["visitors_k"].sum()
    )
    out = sales.merge(visitors, on="month", how="left").sort_values("month").reset_index(drop=True)

    out["per_visitor"] = out["sales"] / out["visitors_k"]
    out["yoy"] = out["sales"].pct_change(12)
    out["target_yoy_fwd"] = out["yoy"].shift(-horizon)
    return out


def _self_check(datasets: Path = DEFAULT_DATASETS) -> None:
    assert datasets.is_dir(), f"datasets dir not found: {datasets}"

    cats = read_category_monthly(datasets)
    assert not cats.empty
    assert str(cats["month"].min()) == "2019-01", cats["month"].min()
    assert "화장품" in set(cats["category"]), sorted(set(cats["category"]))[:5]
    assert set(cats["segment"]) == set(SEGMENTS)
    # Foreign-visitor cosmetics sales dwarf resident ones at duty-free; if this flips,
    # the two sheets were read in the wrong order.
    by_seg = cats[cats["category"] == "화장품"].groupby("segment")["value"].sum()
    assert by_seg["foreign"] > by_seg["resident"], by_seg.to_dict()

    labels = cosmetics_labels(datasets)
    assert labels["month"].is_monotonic_increasing
    assert labels["month"].is_unique
    assert labels["sales"].gt(0).all()
    assert labels["yoy"].notna().sum() > 12, "not enough history for year-over-year"
    # The horizon shift must leave exactly `horizon` unknown rows at the tail.
    assert labels["target_yoy_fwd"].tail(3).isna().all()
    assert labels["target_yoy_fwd"].iloc[-4] == labels["yoy"].iloc[-1]

    print(f"self-check OK: {len(labels)} months, {labels['month'].min()}..{labels['month'].max()}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("datasets", nargs="?", type=Path, default=DEFAULT_DATASETS)
    parser.add_argument("-o", "--out", type=Path, help="write the label table as CSV")
    parser.add_argument("--horizon", type=int, default=3, help="forecast horizon in months")
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()

    if args.self_check:
        _self_check(args.datasets)
        return 0

    labels = cosmetics_labels(args.datasets, horizon=args.horizon)
    if args.out:
        labels.to_csv(args.out, index=False)
        print(f"wrote {args.out} ({len(labels)} rows)")
    else:
        print(labels.to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
