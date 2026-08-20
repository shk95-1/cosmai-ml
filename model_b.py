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


def sufficiency(panel: pd.DataFrame) -> dict[str, object]:
    if panel.empty:
        return {"days": 0, "products": 0, "enough": False, "first_day": None, "last_day": None}
    days = panel["day"].nunique()
    return {
        "days": days,
        "products": panel.groupby(["source", "product_key"]).ngroups,
        "rows": len(panel),
        "first_day": str(panel["day"].min().date()),
        "last_day": str(panel["day"].max().date()),
        "enough": days >= REQUIRED_DAYS,
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

    cutoff = design["day"].max() - pd.Timedelta(days=HOLDOUT_DAYS)
    train, test = design[design["day"] <= cutoff], design[design["day"] > cutoff]
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn", required=True, help="trend-radar Postgres DSN")
    parser.add_argument("--horizon", type=int, default=HORIZON_DAYS)
    parser.add_argument("--check", action="store_true", help="report sufficiency and stop")
    args = parser.parse_args()

    panel = load_panel(args.dsn)
    state = sufficiency(panel)

    print(
        f"panel: {state['days']} day(s) of rank history, "
        f"{state.get('products', 0)} products, {state.get('rows', 0)} product-days"
    )
    if state["first_day"]:
        print(f"range: {state['first_day']} .. {state['last_day']}")

    if not state["enough"]:
        missing = REQUIRED_DAYS - int(state["days"])
        print(
            f"\nINSUFFICIENT DATA. This design needs {REQUIRED_DAYS} days of daily rank "
            f"history: {MOMENTUM_DAYS} for the momentum window, {args.horizon} for the "
            f"label to resolve, {HOLDOUT_DAYS} for a temporal holdout, and one to stand on."
            f"\nHave {state['days']}. Missing {missing} more day(s) of hourly collection."
            "\n\nThis is not a bug and not a modelling choice — trend-radar is forward-only "
            "and has no backfill, so the history has to accrue. The cron has been running "
            "since 2026-08-20; nothing else is required for this to start working."
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
