"""Model A — category demand three months out.

The only model here with enough history to train today, and it is small enough that
the point is the comparison, not the score. 78 months of duty-free sales, minus the
year-over-year window, the forward shift and the feature lags, leaves 60 usable rows;
a 12-month holdout leaves 48 to fit on.

At that size the question is not "what does the model predict" but "does it beat
predicting nothing". Two baselines are computed for exactly that reason:

  persistence   next quarter's growth equals this month's growth
  zero          growth is zero

A ridge fit that does not beat both is not evidence of a signal, and this script
says so rather than reporting an R² and letting the reader assume.

Ridge is solved in closed form with numpy. scikit-learn would be a heavy new
dependency (and a large aarch64 wheel on the DGX) for `(X'X + kI)^-1 X'y`.

Usage:
  uv run --with pandas --with openpyxl model_a.py [DATASETS_DIR]
  uv run --with pandas --with openpyxl model_a.py --self-check
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from labels_sales import DEFAULT_DATASETS, cosmetics_labels

HOLDOUT_MONTHS = 12
RIDGE_PENALTY = 1.0


def build_design(labels: pd.DataFrame) -> pd.DataFrame:
    """Features known at month t, and the label for t + horizon.

    Every column here is computed from data at or before `month`. `yoy` uses sales at
    t and t-12, which is in the past at t; `target_yoy_fwd` is the future value and is
    the label, never a feature.
    """
    frame = labels.copy()
    frame["yoy_lag1"] = frame["yoy"].shift(1)
    frame["yoy_lag3"] = frame["yoy"].shift(3)
    frame["visitors_yoy"] = frame["visitors_k"].pct_change(12)
    # Month-of-year as sine/cosine rather than eleven dummies: with 48 training rows,
    # eleven columns for seasonality alone would spend most of the sample on it.
    month_no = frame["month"].dt.month
    frame["month_sin"] = np.sin(2 * np.pi * month_no / 12)
    frame["month_cos"] = np.cos(2 * np.pi * month_no / 12)

    columns = [
        "yoy",
        "yoy_lag1",
        "yoy_lag3",
        "visitors_yoy",
        "per_visitor",
        "month_sin",
        "month_cos",
    ]
    design = frame[["month", *columns, "target_yoy_fwd"]].dropna()
    return design.reset_index(drop=True)


def _metrics(actual: np.ndarray, predicted: np.ndarray) -> dict[str, float]:
    error = predicted - actual
    return {
        "mae": float(np.mean(np.abs(error))),
        "rmse": float(np.sqrt(np.mean(error**2))),
        # Whether the sign was right matters more to a decision than the magnitude.
        # Meaningless when every prediction is exactly zero -- sign(0) matches
        # nothing -- so the caller reports n/a for the zero baseline rather than 0.00.
        "direction": float(np.mean(np.sign(predicted) == np.sign(actual))),
    }


def evaluate(
    datasets: Path = DEFAULT_DATASETS,
    horizon: int = 3,
    holdout: int = HOLDOUT_MONTHS,
) -> dict[str, object]:
    design = build_design(cosmetics_labels(datasets, horizon=horizon))
    features = [c for c in design.columns if c not in ("month", "target_yoy_fwd")]

    if len(design) <= holdout + len(features):
        raise SystemExit(
            f"not enough rows to fit: {len(design)} usable, "
            f"{holdout} held out, {len(features)} features"
        )

    # Split by time, never at random. A random split lets the model see months either
    # side of the one it is scored on, which for a series this autocorrelated is
    # indistinguishable from reading the answer.
    train, test = design.iloc[:-holdout], design.iloc[-holdout:]

    x_train = train[features].to_numpy(dtype=float)
    x_test = test[features].to_numpy(dtype=float)
    y_train = train["target_yoy_fwd"].to_numpy(dtype=float)
    y_test = test["target_yoy_fwd"].to_numpy(dtype=float)

    # Standardize on the training set only; using test statistics would leak.
    mean, scale = x_train.mean(axis=0), x_train.std(axis=0)
    scale[scale == 0] = 1.0
    x_train_z = np.column_stack([np.ones(len(x_train)), (x_train - mean) / scale])
    x_test_z = np.column_stack([np.ones(len(x_test)), (x_test - mean) / scale])

    penalty = np.full(x_train_z.shape[1], RIDGE_PENALTY)
    penalty[0] = 0.0  # never penalize the intercept
    coefficients = np.linalg.solve(
        x_train_z.T @ x_train_z + np.diag(penalty), x_train_z.T @ y_train
    )

    return {
        "rows_usable": len(design),
        "rows_train": len(train),
        "rows_test": len(test),
        "test_from": str(test["month"].iloc[0]),
        "test_to": str(test["month"].iloc[-1]),
        "ridge": _metrics(y_test, x_test_z @ coefficients),
        "persistence": _metrics(y_test, test["yoy"].to_numpy(dtype=float)),
        "zero": _metrics(y_test, np.zeros(len(y_test))),
        "coefficients": dict(zip(["intercept", *features], coefficients.round(4), strict=True)),
    }


def report(result: dict[str, object]) -> str:
    lines = [
        f"rows: {result['rows_usable']} usable, {result['rows_train']} train, "
        f"{result['rows_test']} test ({result['test_from']}..{result['test_to']})",
        "",
        f"{'model':<12} {'MAE':>8} {'RMSE':>8} {'direction':>10}",
    ]
    for name in ("ridge", "persistence", "zero"):
        m = result[name]  # type: ignore[index]
        direction = "     n/a" if name == "zero" else f"{m['direction']:>8.2f}"
        lines.append(f"{name:<12} {m['mae']:>8.4f} {m['rmse']:>8.4f} {direction:>10}")

    ridge, persistence, zero = (result[k] for k in ("ridge", "persistence", "zero"))
    beat = ridge["mae"] < persistence["mae"] and ridge["mae"] < zero["mae"]  # type: ignore[index]
    lines += [
        "",
        (
            f"VERDICT: ridge beats both baselines on MAE. On {result['rows_train']} "
            f"training rows and {result['rows_test']} contiguous test months -- which are "
            "autocorrelated, so the effective sample is smaller than it looks -- treat "
            "this as a hypothesis, not a result."
            if beat
            else "VERDICT: ridge does NOT beat both baselines. There is no evidence of a "
            "learnable signal at this sample size. Report the baseline, not the model."
        ),
    ]
    return "\n".join(lines)


def _self_check() -> None:
    design = build_design(cosmetics_labels(DEFAULT_DATASETS))
    assert not design.isna().to_numpy().any(), "design matrix still holds NaN"
    assert design["month"].is_monotonic_increasing
    assert "target_yoy_fwd" in design

    result = evaluate()
    assert result["rows_train"] + result["rows_test"] == result["rows_usable"]
    assert result["rows_test"] == HOLDOUT_MONTHS
    # The split must be temporal: every training month precedes every test month.
    train_end = build_design(cosmetics_labels(DEFAULT_DATASETS)).iloc[-HOLDOUT_MONTHS - 1]["month"]
    assert str(train_end) < result["test_from"]  # type: ignore[operator]
    for name in ("ridge", "persistence", "zero"):
        assert 0.0 <= result[name]["direction"] <= 1.0  # type: ignore[index]
    print(f"self-check OK: {result['rows_usable']} usable rows")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("datasets", nargs="?", type=Path, default=DEFAULT_DATASETS)
    parser.add_argument("--horizon", type=int, default=3)
    parser.add_argument("--holdout", type=int, default=HOLDOUT_MONTHS)
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()

    if args.self_check:
        _self_check()
        return 0

    print(report(evaluate(args.datasets, horizon=args.horizon, holdout=args.holdout)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
