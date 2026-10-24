#!/usr/bin/env python3
"""1W/1M/1Y/3Y/5Y from backtest_core on the live Nifty 500 Top-10 monthly book."""
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
from run_nifty500_mom_backtest import merge_cache_download  # noqa: E402
from run_topn_grid import COST_PS, close_matrix, load_symbols  # noqa: E402

UNIVERSE_CSV = ROOT / "ind_nifty500list.csv"
STRATEGY = "nifty500|lb63|top10|M|dual"
YEARS = 20
IST = ZoneInfo("Asia/Kolkata")


def main() -> int:
    end = datetime.now(IST).date()
    test_end = pd.Timestamp(end)
    warm_start = test_end - pd.DateOffset(years=YEARS) - pd.DateOffset(days=400)
    symbols = load_symbols(UNIVERSE_CSV)
    ohlcv = merge_cache_download(symbols, warm_start.strftime("%Y-%m-%d"), test_end.strftime("%Y-%m-%d"))
    full_close = close_matrix(ohlcv, symbols)
    if full_close.empty:
        print("no price data", file=sys.stderr)
        return 1
    full_close = full_close.loc[full_close.index >= warm_start]
    test_close = full_close.loc[full_close.index >= test_end - pd.DateOffset(years=YEARS)]
    score = roc_score(full_close, 63).reindex(test_close.index)
    eq = simulate_top_k(test_close, score, k=10, freq="M", cost_per_side=COST_PS, min_score=0.0)["equity"]
    body = {
        "strategy": STRATEGY,
        "asOf": str(test_close.index[-1].date()),
        "returns": period_returns(eq),
    }
    print(json.dumps(body, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
