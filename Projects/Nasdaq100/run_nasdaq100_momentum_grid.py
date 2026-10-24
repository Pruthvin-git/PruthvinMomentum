#!/usr/bin/env python3
"""Momentum grid on Nasdaq-100: Top-5/10/20, bi-weekly vs monthly.

Same engine as AlphaMom / Microcap: lagged ROC, equal-weight Top-K, 10 bps/side.
Universe is the current NDX list (survivorship bias).
"""
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
from run_topn_grid import COST_PS, close_matrix, download_closes, pick_best  # noqa: E402

from fetch_nasdaq100 import CSV, fetch_rows, us_yf  # noqa: E402

OUT = ROOT / "output"
ET = ZoneInfo("America/New_York")
TEST_START = pd.Timestamp("2021-01-01")
WARM_START = pd.Timestamp("2019-01-01")
KS = (5, 10, 20)
FREQS = ("2W", "M")
FILTERS = (("dual", 0.0), ("relative", None))
BENCH = "QQQ"


def skip_month_score(close: pd.DataFrame, long_lb: int = 252, skip: int = 21) -> pd.DataFrame:
    return (close.shift(skip) / close.shift(long_lb) - 1.0).shift(1)


def vol_adj_score(close: pd.DataFrame, lookback: int = 63, vol_win: int = 63) -> pd.DataFrame:
    roc = close.pct_change(lookback)
    vol = close.pct_change().rolling(vol_win).std()
    return (roc / vol.replace(0.0, np.nan)).shift(1)


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
        rows.append({"year": year, "return": end / start - 1.0, "max_dd": dd, "sessions": int(len(cur))})
    return rows


def equity_curve_points(eq: pd.Series, step: int = 10) -> list[dict]:
    s = eq.dropna()
    if s.empty:
        return []
    idx = list(range(0, len(s), step))
    if idx[-1] != len(s) - 1:
        idx.append(len(s) - 1)
    return [{"date": s.index[i].strftime("%Y-%m-%d"), "equity": float(s.iloc[i])} for i in idx]


def ensure_universe() -> pd.DataFrame:
    rows, meta = fetch_rows()
    out = []
    seen: set[str] = set()
    for r in rows:
        raw = str(r.get("symbol") or "").strip().upper()
        if not raw or raw in seen:
            continue
        seen.add(raw)
        out.append(
            {
                "Company Name": str(r.get("companyName") or "").strip(),
                "Symbol": raw,
                "yf": us_yf(raw),
                "lastSalePrice": r.get("lastSalePrice"),
                "marketCap": r.get("marketCap"),
            }
        )
    df = pd.DataFrame(out).sort_values("Symbol")
    df.to_csv(CSV, index=False)
    print(f"universe n={len(df)} asof={meta.get('asof')}", flush=True)
    return df


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    end = datetime.now(ET).date()
    test_end = pd.Timestamp(end)
    uni = ensure_universe()
    symbols = uni["yf"].tolist()
    all_syms = symbols + [BENCH]
    print(f"window={TEST_START.date()}..{test_end.date()}", flush=True)

    ohlcv = download_closes(all_syms, WARM_START.strftime("%Y-%m-%d"), test_end.strftime("%Y-%m-%d"))
    full_close = close_matrix(ohlcv, [s for s in symbols if s in ohlcv])
    bench_close = close_matrix(ohlcv, [BENCH] if BENCH in ohlcv else [])
    missing = [s for s in symbols if s not in full_close.columns]
    if missing:
        print(f"missing prices n={len(missing)} {missing[:12]}", flush=True)
    if full_close.empty:
        print("no price data", flush=True)
        return 1

    full_close = full_close.loc[full_close.index >= WARM_START]
    test_close = full_close.loc[full_close.index >= TEST_START]
    years_span = (test_close.index[-1] - test_close.index[0]).days / 365.25
    print(
        f"data {test_close.index.min().date()}..{test_close.index.max().date()} "
        f"names={test_close.shape[1]} years={years_span:.2f}",
        flush=True,
    )

    score_specs = [
        ("roc21", roc_score(full_close, 21)),
        ("roc63", roc_score(full_close, 63)),
        ("roc126", roc_score(full_close, 126)),
        ("roc252", roc_score(full_close, 252)),
        ("skip12_1", skip_month_score(full_close)),
        ("voladj63", vol_adj_score(full_close, 63, 63)),
    ]

    last_years = list(range(TEST_START.year, test_end.year + 1))
    rows = []
    equity_keep: dict[str, pd.Series] = {}

    for score_name, raw_score in score_specs:
        score = raw_score.reindex(test_close.index)
        for k in KS:
            for freq in FREQS:
                for filt_name, min_score in FILTERS:
                    label = f"ndx|{score_name}|top{k}|{freq}|{filt_name}"
                    res = simulate_top_k(
                        test_close, score, k=k, freq=freq, cost_per_side=COST_PS, min_score=min_score
                    )
                    eq = res["equity"]
                    m = window_metrics(eq, TEST_START)
                    yearly = calendar_year_returns(eq, last_years)
                    turnover_pa = float(res["turnover"]) / years_span if years_span > 0 else np.nan
                    row = {
                        "label": label,
                        "score": score_name,
                        "k": k,
                        "freq": freq,
                        "filter": filt_name,
                        "cagr": m["cagr"],
                        "total_return": m["total_return"],
                        "max_dd": m["max_dd"],
                        "sharpe": m["sharpe"],
                        "turnover": res["turnover"],
                        "turnover_pa": turnover_pa,
                        "rebalances": res["rebalances"],
                        "avg_cash": res["avg_cash"],
                        "avg_holdings": res["avg_holdings"],
                        "yearly": yearly,
                    }
                    rows.append(row)
                    equity_keep[label] = eq
                    print(
                        f"{label:40s} CAGR={m['cagr']*100:6.1f}%  DD={m['max_dd']*100:6.1f}%  "
                        f"Sharpe={m['sharpe']:.2f}  turn/yr={turnover_pa:.1f}",
                        flush=True,
                    )

    grid = pd.DataFrame([{k: v for k, v in r.items() if k != "yearly"} for r in rows])
    grid.to_csv(OUT / "nasdaq100_momentum_grid.csv", index=False)

    dual = grid[grid["filter"] == "dual"].copy()
    best_cagr = dual.sort_values("cagr", ascending=False).iloc[0]
    best_bal = pick_best(dual, "cagr", "max_dd")
    q75 = float(dual["cagr"].quantile(0.75))
    low_churn = dual[(dual["cagr"] >= q75)].sort_values(["turnover_pa", "cagr"], ascending=[True, False])
    best_low_churn = low_churn.iloc[0] if not low_churn.empty else best_cagr

    ew = buy_and_hold_ew(test_close)
    ew_m = window_metrics(ew, TEST_START)
    ew_row = {
        "label": "NDX equal-weight BH",
        "cagr": ew_m["cagr"],
        "total_return": ew_m["total_return"],
        "max_dd": ew_m["max_dd"],
        "sharpe": ew_m["sharpe"],
        "yearly": calendar_year_returns(ew, last_years),
        "equity": equity_curve_points(ew),
    }

    bench_row = None
    if not bench_close.empty:
        q = bench_close.iloc[:, 0].dropna()
        q = q.loc[q.index >= TEST_START]
        q_eq = q / float(q.iloc[0])
        bm = window_metrics(q_eq, TEST_START)
        bench_row = {
            "label": "QQQ",
            "cagr": bm["cagr"],
            "total_return": bm["total_return"],
            "max_dd": bm["max_dd"],
            "sharpe": bm["sharpe"],
            "yearly": calendar_year_returns(q_eq, last_years),
            "equity": equity_curve_points(q_eq),
        }

    def pack(series_or_row) -> dict:
        d = series_or_row.to_dict() if isinstance(series_or_row, pd.Series) else dict(series_or_row)
        lab = d["label"]
        yearly = next(r["yearly"] for r in rows if r["label"] == lab)
        d["yearly"] = yearly
        d["equity"] = equity_curve_points(equity_keep[lab])
        return d

    top10 = dual.sort_values("cagr", ascending=False).head(10)
    all_ranked = dual.sort_values("cagr", ascending=False)

    summary = {
        "asof": test_end.strftime("%Y-%m-%d"),
        "universe": str(CSV),
        "symbols_requested": len(symbols),
        "symbols_with_data": int(test_close.shape[1]),
        "missing": missing,
        "window_start": TEST_START.strftime("%Y-%m-%d"),
        "window_end": test_close.index.max().strftime("%Y-%m-%d"),
        "cost_per_side": COST_PS,
        "best_cagr": pack(best_cagr),
        "best_balanced": pack(best_bal),
        "best_low_churn": pack(best_low_churn),
        "ew_universe": ew_row,
        "qqq": bench_row,
        "top10_dual": [pack(r) for _, r in top10.iterrows()],
        "all_dual": [pack(r) for _, r in all_ranked.iterrows()],
        "caveat": (
            "Current Nasdaq-100 members only (survivorship bias). "
            "Yahoo adjusted close. Costs 10 bps/side. 2026 is year-to-date. "
            "Source: api.nasdaq.com/api/quote/list-type/nasdaq100 "
            "(same feed as nasdaq.com/market-activity/quotes/nasdaq-ndx-index)."
        ),
    }
    (OUT / "nasdaq100_momentum_summary.json").write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8"
    )

    print("\n=== BEST CAGR (2W/M dual) ===")
    print(best_cagr[["label", "cagr", "max_dd", "sharpe", "turnover_pa"]].to_string())
    print("\n=== BEST LOW-CHURN (top CAGR quartile, lowest turnover) ===")
    print(best_low_churn[["label", "cagr", "max_dd", "sharpe", "turnover_pa"]].to_string())
    print("\n=== TOP 10 DUAL ===")
    print(top10[["label", "cagr", "max_dd", "sharpe", "turnover_pa", "freq"]].to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
