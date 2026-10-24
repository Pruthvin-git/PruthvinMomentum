#!/usr/bin/env python3
"""Nifty 500 Top-10 dual-momentum grid (20y+) + rebalance frequency comparison."""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
POC = ROOT.parent / "AlphaMom_TopN_POC"
sys.path.insert(0, str(POC))

from backtest_core import buy_and_hold_ew, roc_score, simulate_top_k, window_metrics  # noqa: E402
from run_topn_grid import (  # noqa: E402
    BENCH,
    COST_PS,
    close_matrix,
    download_closes,
    load_symbols,
    pick_best,
)

UNIVERSE_CSV = ROOT / "ind_nifty500list.csv"
OUT = ROOT / "output"
IST = ZoneInfo("Asia/Kolkata")
YEARS = 20
LOOKBACKS = (21, 63, 126, 252)
KS = (10,)
FREQS = ("W", "2W", "M")
FILTERS = (("dual", 0.0), ("relative", None))


def merge_cache_download(symbols: list[str], start: str, end: str) -> dict:
    """Prefer AlphaMom cache, then BestOfAll cache, then yfinance."""
    import run_topn_grid as rtg

    extra_caches = [
        POC / "data_cache_1d",
        ROOT.parent / "BestOfAll" / "data_cache",
    ]
    orig_cache = rtg.CACHE
    loaded: dict[str, pd.DataFrame] = {}
    warm = pd.Timestamp(start)
    end_ok = pd.Timestamp(end) - pd.Timedelta(days=7)
    need = list(symbols)
    for cache_dir in extra_caches:
        if not cache_dir.exists():
            continue
        still = []
        for s in need:
            path = cache_dir / f"{s.replace('.', '_')}_1d.csv"
            if not path.exists():
                still.append(s)
                continue
            df = rtg._normalize_ohlcv(pd.read_csv(path, parse_dates=[0], index_col=0))
            if rtg.cache_fresh_enough(df, warm, end_ok):
                loaded[s] = df
            else:
                still.append(s)
        need = still
    if need:
        rtg.CACHE = POC / "data_cache_1d"
        rtg.CACHE.mkdir(parents=True, exist_ok=True)
        more = download_closes(need, start, end)
        loaded.update(more)
    rtg.CACHE = orig_cache
    return loaded


def calendar_year_returns(eq: pd.Series, years: list[int]) -> list[dict]:
    rows = []
    for year in years:
        prev = eq[eq.index.year < year]
        cur = eq[eq.index.year == year]
        if cur.empty:
            continue
        start = float(prev.iloc[-1]) if len(prev) else float(cur.iloc[0])
        end = float(cur.iloc[-1])
        if start <= 0:
            continue
        path = pd.concat([pd.Series([start], index=[cur.index[0] - pd.Timedelta(days=1)]), cur])
        dd = float((path / path.cummax() - 1.0).min())
        rows.append({"year": year, "return": end / start - 1.0, "max_dd": dd})
    return rows


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    end = datetime.now(IST).date()
    test_end = pd.Timestamp(end)
    test_start = test_end - pd.DateOffset(years=YEARS)
    warm_start = test_start - pd.DateOffset(days=400)

    symbols = load_symbols(UNIVERSE_CSV)
    all_syms = symbols + [BENCH]
    print(f"universe={len(symbols)} window={test_start.date()}..{test_end.date()}", flush=True)

    ohlcv = merge_cache_download(all_syms, warm_start.strftime("%Y-%m-%d"), test_end.strftime("%Y-%m-%d"))
    full_close = close_matrix(ohlcv, [s for s in all_syms if s != BENCH])
    bench_close = close_matrix(ohlcv, [BENCH] if BENCH in ohlcv else [])
    if full_close.empty:
        print("no price data", flush=True)
        return 1
    full_close = full_close.loc[full_close.index >= warm_start]
    test_close = full_close.loc[full_close.index >= test_start]
    print(
        f"data {test_close.index.min().date()}..{test_close.index.max().date()} "
        f"names={test_close.shape[1]}",
        flush=True,
    )

    rows = []
    for lookback in LOOKBACKS:
        score = roc_score(full_close, lookback).reindex(test_close.index)
        for k in KS:
            for freq in FREQS:
                for filt_name, min_score in FILTERS:
                    label = f"nifty500|lb{lookback}|top{k}|{freq}|{filt_name}"
                    res = simulate_top_k(
                        test_close, score, k=k, freq=freq, cost_per_side=COST_PS, min_score=min_score
                    )
                    eq = res["equity"]
                    m = window_metrics(eq, test_start)
                    rows.append(
                        {
                            "label": label,
                            "lookback": lookback,
                            "k": k,
                            "freq": freq,
                            "filter": filt_name,
                            "cagr": m["cagr"],
                            "total_return": m["total_return"],
                            "max_dd": m["max_dd"],
                            "sharpe": m["sharpe"],
                            "turnover": res["turnover"],
                            "rebalances": res["rebalances"],
                            "avg_cash": res["avg_cash"],
                            "avg_holdings": res["avg_holdings"],
                        }
                    )

    grid = pd.DataFrame(rows)
    grid.to_csv(OUT / "grid_nifty500_top10_20y.csv", index=False)

    dual = grid[grid["filter"] == "dual"].copy()
    best = pick_best(dual, "cagr", "max_dd")
    best_lb = int(best["lookback"])

    # Rebalance comparison at best lookback (dual only)
    reb_cmp = dual[dual["lookback"] == best_lb].sort_values("freq")
    reb_cmp.to_csv(OUT / "rebalance_compare.csv", index=False)

    # Yearly returns for winning combo
    win_label = best["label"]
    lookback = best_lb
    freq = best["freq"]
    score = roc_score(full_close, lookback).reindex(test_close.index)
    win_res = simulate_top_k(
        test_close, score, k=10, freq=freq, cost_per_side=COST_PS, min_score=0.0
    )
    eq = win_res["equity"]
    last5 = list(range(test_end.year - 4, test_end.year + 1))
    yearly = calendar_year_returns(eq, last5)

    ew = buy_and_hold_ew(test_close)
    ew_yearly = calendar_year_returns(ew, last5)
    bench_yearly = []
    if not bench_close.empty:
        nse = bench_close.iloc[:, 0].dropna()
        nse_eq = nse / nse.loc[nse.index >= test_start].iloc[0]
        nse_eq = nse_eq.loc[nse_eq.index >= test_start]
        bench_yearly = calendar_year_returns(nse_eq, last5)

    summary = {
        "asof": test_end.strftime("%Y-%m-%d"),
        "universe": str(UNIVERSE_CSV),
        "symbols_requested": len(symbols),
        "symbols_with_data": int(test_close.shape[1]),
        "years": YEARS,
        "cost_per_side": COST_PS,
        "best_dual": best.to_dict(),
        "rebalance_at_best_lookback": reb_cmp.to_dict(orient="records"),
        "yearly_strategy": yearly,
        "yearly_ew_universe": ew_yearly,
        "yearly_nifty50": bench_yearly,
        "caveat": "Current Nifty 500 members for full history (survivorship bias). Yahoo adjusted close.",
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")

    print("\n=== BEST DUAL TOP-10 (20y window) ===")
    print(best[["label", "cagr", "total_return", "max_dd", "sharpe", "avg_holdings", "avg_cash"]].to_string())
    print("\n=== REBALANCE @ lookback", best_lb, "===")
    print(reb_cmp[["freq", "cagr", "max_dd", "sharpe", "turnover", "rebalances"]].to_string(index=False))
    print("\n=== CALENDAR YEARS (strategy)", win_label, "===")
    for r in yearly:
        print(f"  {r['year']}: {r['return']*100:.1f}%  max_dd {r['max_dd']*100:.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
