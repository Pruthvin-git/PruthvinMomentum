#!/usr/bin/env python3
"""1W/1M/1Y/3Y/5Y from backtest_core on the live Nasdaq-100 Top-5 monthly book."""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = Path(__file__).resolve().parent
POC = ROOT.parent / "AlphaMom_TopN_POC"
sys.path.insert(0, str(POC))
sys.path.insert(0, str(ROOT))

from backtest_core import period_returns, roc_score, simulate_top_k  # noqa: E402
from fetch_nasdaq100 import CSV, us_yf  # noqa: E402
from run_topn_grid import COST_PS, close_matrix, download_closes  # noqa: E402

STRATEGY = "ndx|roc126|top5|M|dual"
TEST_START = pd.Timestamp("2021-01-01")
WARM_START = pd.Timestamp("2019-01-01")
BENCH = "QQQ"
ET = ZoneInfo("America/New_York")


def load_yf_symbols() -> list[str]:
    df = pd.read_csv(CSV)
    col = "yf" if "yf" in df.columns else "Symbol"
    if col == "yf":
        return df["yf"].astype(str).tolist()
    return [us_yf(s) for s in df[col].astype(str)]


def main() -> int:
    end = datetime.now(ET).date()
    test_end = pd.Timestamp(end)
    symbols = load_yf_symbols()
    ohlcv = download_closes(symbols + [BENCH], WARM_START.strftime("%Y-%m-%d"), test_end.strftime("%Y-%m-%d"))
    full_close = close_matrix(ohlcv, symbols)
    if full_close.empty:
        print("no price data", file=sys.stderr)
        return 1
    full_close = full_close.loc[full_close.index >= WARM_START]
    test_close = full_close.loc[full_close.index >= TEST_START]
    score = roc_score(full_close, 126).reindex(test_close.index)
    eq = simulate_top_k(test_close, score, k=5, freq="M", cost_per_side=COST_PS, min_score=0.0)["equity"]
    body = {
        "strategy": STRATEGY,
        "asOf": str(test_close.index[-1].date()),
        "windowStart": TEST_START.strftime("%Y-%m-%d"),
        "returns": period_returns(eq),
    }
    print(json.dumps(body, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
