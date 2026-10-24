#!/usr/bin/env python3
"""1W/1M/1Y/3Y/5Y from backtest_core on the live Alpha 50 Top-5 bi-weekly book."""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from backtest_core import period_returns, roc_score, simulate_top_k  # noqa: E402
from run_topn_grid import COST_PS, UNIVERSE_CSV, close_matrix, download_closes, load_symbols  # noqa: E402

STRATEGY = "alpha50|lb21|top5|2W|dual"
YEARS = 20
IST = ZoneInfo("Asia/Kolkata")


def main() -> int:
    end = datetime.now(IST).date()
    test_end = pd.Timestamp(end)
    warm_start = test_end - pd.DateOffset(years=YEARS) - pd.DateOffset(days=400)
    symbols = load_symbols(UNIVERSE_CSV["alpha50"])
    ohlcv = download_closes(symbols, warm_start.strftime("%Y-%m-%d"), test_end.strftime("%Y-%m-%d"))
    full_close = close_matrix(ohlcv, symbols)
    if full_close.empty:
        print("no price data", file=sys.stderr)
        return 1
    full_close = full_close.loc[full_close.index >= warm_start]
    test_close = full_close.loc[full_close.index >= test_end - pd.DateOffset(years=YEARS)]
    score = roc_score(full_close, 21).reindex(test_close.index)
    eq = simulate_top_k(test_close, score, k=5, freq="2W", cost_per_side=COST_PS, min_score=0.0)["equity"]
    body = {
        "strategy": STRATEGY,
        "asOf": str(test_close.index[-1].date()),
        "returns": period_returns(eq),
    }
    print(json.dumps(body, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
