#!/usr/bin/env python3
"""1W/1M/1Y/3Y/5Y from backtest_core on the live Microcap Top-10 monthly book."""
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

from backtest_core import period_returns, roc_score, simulate_top_k  # noqa: E402
from run_topn_grid import BENCH, COST_PS, close_matrix, download_closes, load_symbols  # noqa: E402

UNIVERSE_CSV = ROOT / "niftymicrocap250.csv"
STRATEGY = "microcap250|roc252|top10|M|dual"
TEST_START = pd.Timestamp("2021-01-01")
WARM_START = pd.Timestamp("2019-01-01")
IST = ZoneInfo("Asia/Kolkata")


def main() -> int:
    end = datetime.now(IST).date()
    test_end = pd.Timestamp(end)
    symbols = load_symbols(UNIVERSE_CSV)
    ohlcv = download_closes(symbols + [BENCH], WARM_START.strftime("%Y-%m-%d"), test_end.strftime("%Y-%m-%d"))
    full_close = close_matrix(ohlcv, symbols)
    if full_close.empty:
        print("no price data", file=sys.stderr)
        return 1
    full_close = full_close.loc[full_close.index >= WARM_START]
    test_close = full_close.loc[full_close.index >= TEST_START]
    score = roc_score(full_close, 252).reindex(test_close.index)
    eq = simulate_top_k(test_close, score, k=10, freq="M", cost_per_side=COST_PS, min_score=0.0)["equity"]
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
