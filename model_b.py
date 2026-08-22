"""Model B — product ranking movement.

This is a working pipeline, not a placeholder. It reads the `trend-radar` Postgres,
builds the (product, day) panel, and either trains or refuses — and when it refuses it
says exactly how much history is missing and when the collector will have produced it.

It refuses today because collection started 2026-08-20. That is the honest state, and
writing it as a running script rather than a design note means the day the data exists,
nobody has to build anything.

Why this model rather than a keyword one: `Y` comes from `rank_snapshot` and most of `X`
comes from prices, launches and reviews, so the label is not a rearrangement of the
features. See MODELS.md.

Usage:
  uv run model_b.py --dsn postgresql://trend_radar:trend_radar@localhost:5432/trend_radar
  uv run model_b.py --dsn ... --check      # report data sufficiency and stop
"""

from __future__ import annotations

import argparse
import sys

import numpy as np
import pandas as pd

# Days of rank history the design needs before it can be fitted at all.
MOMENTUM_DAYS = 7  # longest lookback feature
HORIZON_DAYS = 7  # how far ahead the label looks
HOLDOUT_DAYS = 7  # temporal holdout, never a random split
REQUIRED_DAYS = MOMENTUM_DAYS + HORIZON_DAYS + HOLDOUT_DAYS + 1

# A product only produces a usable row if it has REQUIRED_DAYS of *consecutive* daily
# observations -- a global count of unique days across all products cannot tell disjoint
# coverage from continuous coverage (two products covering 11 disjoint days each pass a
# global "22 unique days" check and produce zero design rows). And one qualifying product
# is not enough for a train/test split to mean anything: its holdout rows are one
# autocorrelated series, not a market, and the ridge fit sees only that one product's
# price/review/age combination. Five is the smallest count that puts more than a
# single-product story on each side of the split while still being reachable early --
# with 529 products tracked, waiting for dozens to individually clear 22 consecutive days
# would delay training long after the panel is actually usable.
MIN_QUALIFYING_PRODUCTS = 5

PANEL_SQL = """
select
    source,
    product_key,
    (captured_at at time zone 'UTC')::date as day,
    min(rank) as best_rank
from rank_snapshot
group by source, product_key, day
"""

PRICE_SQL = """
select
    source,
    product_key,
    (captured_at at time zone 'UTC')::date as day,
    avg(price)::float as price,
    avg(discount_rate)::float as discount_rate
from price_point
group by source, product_key, day
"""

FIRST_SEEN_SQL = """
select source, product_key, (first_seen_at at time zone 'UTC')::date as first_seen
from product
"""


def load_panel(dsn: str) -> pd.DataFrame:
    """One row per (source, product, day), with price and age joined on."""
    import psycopg

    def query(cursor, sql: str) -> pd.DataFrame:
        # Straight through the cursor rather than pd.read_sql: pandas wants a
        # SQLAlchemy connectable and warns on a raw DBAPI one, and SQLAlchemy is a
        # whole dependency to silence a warning about three SELECTs.
        cursor.execute(sql)
        return pd.DataFrame(cursor.fetchall(), columns=[c.name for c in cursor.description])

    with psycopg.connect(dsn) as connection, connection.cursor() as cursor:
        ranks = query(cursor, PANEL_SQL)
        prices = query(cursor, PRICE_SQL)
        first_seen = query(cursor, FIRST_SEEN_SQL)

    if ranks.empty:
        return ranks

    panel = ranks.merge(prices, on=["source", "product_key", "day"], how="left")
    panel = panel.merge(first_seen, on=["source", "product_key"], how="left")
    panel["day"] = pd.to_datetime(panel["day"])
    panel["first_seen"] = pd.to_datetime(panel["first_seen"])
    return panel.sort_values(["source", "product_key", "day"]).reset_index(drop=True)


def build_design(panel: pd.DataFrame, horizon: int = HORIZON_DAYS) -> pd.DataFrame:
    """Features known on `day`, and the rank change over the next `horizon` days.

    Negative `target_rank_change` means the product climbed. Products are grouped so a
    lag never reaches across a product boundary.
    """
    frame = panel.copy()
    grouped = frame.groupby(["source", "product_key"], sort=False)

    for lag in (1, 3, MOMENTUM_DAYS):
        frame[f"momentum_{lag}d"] = frame["best_rank"] - grouped["best_rank"].shift(lag)
    frame["price_change_1d"] = frame["price"] - grouped["price"].shift(1)
    frame["days_since_first_seen"] = (frame["day"] - frame["first_seen"]).dt.days
    frame["target_rank_change"] = grouped["best_rank"].shift(-horizon) - frame["best_rank"]

    columns = [
        "best_rank",
        "momentum_1d",
        "momentum_3d",
        f"momentum_{MOMENTUM_DAYS}d",
        "price",
        "discount_rate",
        "price_change_1d",
        "days_since_first_seen",
    ]
    return frame[["source", "product_key", "day", *columns, "target_rank_change"]].dropna()


def _longest_run(days: pd.Series) -> int:
    """Longest streak of calendar-consecutive dates in `days` (duplicates ignored)."""
    ordered = pd.Series(pd.to_datetime(days).unique()).sort_values()
    if ordered.empty:
        return 0
    new_streak = ordered.diff().dt.days.fillna(1) != 1
    return int(new_streak.cumsum().value_counts().max())


def sufficiency(panel: pd.DataFrame) -> dict[str, object]:
    if panel.empty:
        return {
            "days": 0, "products": 0, "rows": 0, "first_day": None, "last_day": None,
            "qualifying_products": 0, "best_run": 0, "best_run_product": None,
            "enough": False,
        }
    runs = panel.groupby(["source", "product_key"])["day"].apply(_longest_run)
    best_key = runs.idxmax()
    return {
        "days": panel["day"].nunique(),
        "products": len(runs),
        "rows": len(panel),
        "first_day": str(panel["day"].min().date()),
        "last_day": str(panel["day"].max().date()),
        "qualifying_products": int((runs >= REQUIRED_DAYS).sum()),
        "best_run": int(runs.max()),
        "best_run_product": "/".join(best_key),
        "enough": int((runs >= REQUIRED_DAYS).sum()) >= MIN_QUALIFYING_PRODUCTS,
    }


def _metrics(actual: np.ndarray, predicted: np.ndarray) -> dict[str, float]:
    error = predicted - actual
    return {
        "mae": float(np.mean(np.abs(error))),
        "rmse": float(np.sqrt(np.mean(error**2))),
        "direction": float(np.mean(np.sign(predicted) == np.sign(actual))),
    }


def evaluate(panel: pd.DataFrame, horizon: int = HORIZON_DAYS) -> dict[str, object]:
    design = build_design(panel, horizon=horizon)
    features = [
        c for c in design.columns if c not in ("source", "product_key", "day", "target_rank_change")
    ]

    # Split by day, never at random -- a random split lets the model see days either side
    # of the one it is scored on, which for a series this autocorrelated is indistinguishable
    # from reading the answer.
    #
    # A row on `day` carries a target from `day + horizon`. Cutting the split at `day`
    # alone leaves the last `horizon` days of training rows with targets that land inside
    # the test period -- purge them too, so no training target reaches past the start of
    # the test window (same leakage model_a.py had, and fixed the same way).
    cutoff = design["day"].max() - pd.Timedelta(days=HOLDOUT_DAYS)
    purge_before = cutoff - pd.Timedelta(days=horizon)
    train, test = design[design["day"] <= purge_before], design[design["day"] > cutoff]
    if train.empty or test.empty:
        raise SystemExit("temporal split left one side empty; more days needed")

    x_train = train[features].to_numpy(dtype=float)
    x_test = test[features].to_numpy(dtype=float)
    y_train = train["target_rank_change"].to_numpy(dtype=float)
    y_test = test["target_rank_change"].to_numpy(dtype=float)

    mean, scale = x_train.mean(axis=0), x_train.std(axis=0)
    scale[scale == 0] = 1.0
    x_train_z = np.column_stack([np.ones(len(x_train)), (x_train - mean) / scale])
    x_test_z = np.column_stack([np.ones(len(x_test)), (x_test - mean) / scale])

    penalty = np.ones(x_train_z.shape[1])
    penalty[0] = 0.0
    coefficients = np.linalg.solve(
        x_train_z.T @ x_train_z + np.diag(penalty), x_train_z.T @ y_train
    )

    return {
        "rows_train": len(train),
        "rows_test": len(test),
        "ridge": _metrics(y_test, x_test_z @ coefficients),
        # Persistence: the rank does not move. This is the bar to beat, and for a
        # series this autocorrelated it is a high one.
        "persistence": _metrics(y_test, np.zeros(len(y_test))),
        "coefficients": dict(zip(["intercept", *features], coefficients.round(4), strict=True)),
    }


def _product_panel(product_key: str, days: pd.DatetimeIndex) -> pd.DataFrame:
    return pd.DataFrame({
        "source": "s", "product_key": product_key, "day": days,
        "best_rank": range(10, 10 + len(days)), "price": 100.0, "discount_rate": 0.0,
        "first_seen": days[0],
    })


def _self_check() -> None:
    # The audited bug: two products, 11 disjoint days each. 22 unique days globally
    # clears REQUIRED_DAYS, but neither product has a continuous run long enough to
    # produce even one design row.
    disjoint = pd.concat([
        _product_panel("a", pd.date_range("2026-01-01", periods=11)),
        _product_panel("b", pd.date_range("2026-01-12", periods=11)),
    ], ignore_index=True)

    state = sufficiency(disjoint)
    assert state["days"] == 22
    assert state["qualifying_products"] == 0
    assert not state["enough"], "disjoint per-product coverage must not read as sufficient"
    assert build_design(disjoint).empty, "no product here has a usable continuous window"

    # One product with a real REQUIRED_DAYS run is recognized as qualifying, but a single
    # qualifying product still isn't `enough` -- that is the whole point of
    # MIN_QUALIFYING_PRODUCTS.
    one_continuous = pd.concat(
        [disjoint, _product_panel("c", pd.date_range("2026-01-01", periods=REQUIRED_DAYS))],
        ignore_index=True,
    )
    state = sufficiency(one_continuous)
    assert state["qualifying_products"] == 1
    assert not state["enough"], f"one product must not clear MIN_QUALIFYING_PRODUCTS={MIN_QUALIFYING_PRODUCTS}"

    # evaluate()'s split must purge training rows whose target lands in the test window.
    panel = pd.concat(
        [_product_panel(str(i), pd.date_range("2026-01-01", periods=REQUIRED_DAYS + 10))
         for i in range(MIN_QUALIFYING_PRODUCTS)],
        ignore_index=True,
    )
    design = build_design(panel)
    cutoff = design["day"].max() - pd.Timedelta(days=HOLDOUT_DAYS)
    purge_before = cutoff - pd.Timedelta(days=HORIZON_DAYS)
    train_days = design.loc[design["day"] <= purge_before, "day"]
    test_days = design.loc[design["day"] > cutoff, "day"]
    assert train_days.max() + pd.Timedelta(days=HORIZON_DAYS) <= test_days.min(), (
        "a training row's target must never land inside the test window"
    )
    evaluate(panel)  # must not raise

    print("self-check OK")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn", help="trend-radar Postgres DSN")
    parser.add_argument("--horizon", type=int, default=HORIZON_DAYS)
    parser.add_argument("--check", action="store_true", help="report sufficiency and stop")
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()

    if args.self_check:
        _self_check()
        return 0
    if not args.dsn:
        raise SystemExit("--dsn is required unless --self-check is given")

    panel = load_panel(args.dsn)
    state = sufficiency(panel)

    print(
        f"panel: {state['days']} day(s) of rank history, "
        f"{state.get('products', 0)} products, {state.get('rows', 0)} product-days"
    )
    if state["first_day"]:
        print(f"range: {state['first_day']} .. {state['last_day']}")
        print(
            f"longest continuous run for a single product: {state['best_run']} day(s) "
            f"({state['best_run_product']}); {state['qualifying_products']} product(s) "
            f"reach the {REQUIRED_DAYS}-day bar, need {MIN_QUALIFYING_PRODUCTS}"
        )

    if not state["enough"]:
        print(
            f"\nINSUFFICIENT DATA. This design needs a run of {REQUIRED_DAYS} *consecutive* "
            f"daily observations per product: {MOMENTUM_DAYS} for the momentum window, "
            f"{args.horizon} for the label to resolve, {HOLDOUT_DAYS} for a temporal "
            "holdout, and one to stand on -- and needs at least "
            f"{MIN_QUALIFYING_PRODUCTS} products clearing that bar, or the split is scored "
            "on one product's autocorrelated history rather than a market."
            f"\n{state['qualifying_products']} product(s) currently clear it. The longest "
            f"run anywhere in the panel is {state['best_run']} day(s), on "
            f"{state['best_run_product']}. A global count of {state['days']} unique "
            "day(s) across all products is not the same thing -- products covering "
            "disjoint stretches of days add up to plenty of unique days and zero rows "
            "any product can actually be scored on."
            "\n\nThis is not a bug and not a modelling choice — trend-radar is forward-only "
            "and has no backfill, so the history has to accrue, per product, day by day. "
            "The cron has been running since 2026-08-20; nothing else is required for "
            "this to start working."
        )
        return 1

    if args.check:
        print("\nsufficient. run without --check to fit.")
        return 0

    result = evaluate(panel, horizon=args.horizon)
    print(f"\nrows: {result['rows_train']} train, {result['rows_test']} test")
    print(f"{'model':<12} {'MAE':>8} {'RMSE':>8} {'direction':>10}")
    for name in ("ridge", "persistence"):
        m = result[name]  # type: ignore[index]
        print(f"{name:<12} {m['mae']:>8.4f} {m['rmse']:>8.4f} {m['direction']:>10.2f}")

    ridge, persistence = result["ridge"], result["persistence"]
    if ridge["mae"] >= persistence["mae"]:  # type: ignore[index]
        print(
            "\nVERDICT: ridge does NOT beat persistence. Ranks are strongly autocorrelated; "
            "not beating 'nothing moves' means no signal was found, not that the data is bad."
        )
    else:
        print("\nVERDICT: ridge beats persistence. Check the window for scraper gaps before")
        print("believing it — an outage looks exactly like a quiet market in this data.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
