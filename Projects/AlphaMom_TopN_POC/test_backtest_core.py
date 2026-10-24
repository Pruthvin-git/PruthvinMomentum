"""Synthetic checks for ranking, rebalance cadence, and no same-bar lookahead."""
from __future__ import annotations

import numpy as np
import pandas as pd

from backtest_core import is_biweekly_friday, rebalance_mask, roc_score, simulate_top_k, window_metrics, wfri_even


def test_weekly_mask_fires_on_week_starts():
    idx = pd.bdate_range("2024-01-01", periods=20)
    mask = rebalance_mask(idx, "W")
    assert mask[0]
    assert mask.sum() >= 3


def test_score_is_lagged():
    idx = pd.bdate_range("2024-01-01", periods=30)
    close = pd.DataFrame({"A": np.linspace(100, 130, 30)}, index=idx)
    sc = roc_score(close, 5)
    # ROC at bar i uses close[i-1]/close[i-6]-1, never close[i]
    i = 10
    expected = close.iloc[i - 1, 0] / close.iloc[i - 1 - 5, 0] - 1.0
    assert abs(float(sc.iloc[i, 0]) - expected) < 1e-12


def test_dual_mom_skips_negative_roc():
    idx = pd.bdate_range("2024-01-01", periods=40)
    a = np.linspace(100, 200, 40)
    b = np.linspace(200, 100, 40)
    close = pd.DataFrame({"UP": a, "DOWN": b}, index=idx)
    sc = roc_score(close, 5)
    out = simulate_top_k(close, sc, k=2, freq="W", cost_per_side=0.0, min_score=0.0)
    # With a crashing name, dual mom should not stay fully in both names
    assert out["avg_holdings"] < 1.9
    assert out["equity"].iloc[-1] > 1.0


def test_window_metrics_positive_trend():
    idx = pd.bdate_range("2020-01-01", periods=252)
    eq = pd.Series(np.linspace(1.0, 1.2, 252), index=idx)
    m = window_metrics(eq)
    assert m["total_return"] > 0.19
    assert m["cagr"] > 0.15
    assert m["max_dd"] == 0.0


def test_biweekly_friday_even_wfri_only():
    # 2026-08-28 is Friday; 2026-08-21 is the previous Friday
    assert is_biweekly_friday(pd.Timestamp("2026-08-28")) or is_biweekly_friday(pd.Timestamp("2026-08-21"))
    assert is_biweekly_friday(pd.Timestamp("2026-08-28")) != is_biweekly_friday(pd.Timestamp("2026-08-21"))
    assert not is_biweekly_friday(pd.Timestamp("2026-08-27"))  # Thursday
    assert wfri_even(pd.Timestamp("2026-08-28")) == is_biweekly_friday(pd.Timestamp("2026-08-28"))


if __name__ == "__main__":
    test_weekly_mask_fires_on_week_starts()
    test_score_is_lagged()
    test_dual_mom_skips_negative_roc()
    test_window_metrics_positive_trend()
    test_biweekly_friday_even_wfri_only()
    print("ok")
