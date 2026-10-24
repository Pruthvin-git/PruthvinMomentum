#!/usr/bin/env python3
"""
Proof of concept: dual-momentum Top-N grid on Alpha 50 and Momentum Midcap 50.

Grid
  universe:  alpha50 | momentum50 | combined
  lookback:  21 | 63 | 126 trading days
  top-N:     5 | 10 | 20
  frequency: W | 2W | M
  filter:    dual (ROC>0 else cash) | relative (always fully invested)

Windows: last 6 years, last 2 years, last 1 year (from run date).
Costs: 0.10% per side. Ranking uses T-1 close (no same-bar lookahead).

Usage:
  python test_backtest_core.py
  python run_topn_grid.py
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import yfinance as yf

from backtest_core import buy_and_hold_ew, roc_score, simulate_top_k, window_metrics

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / "data_cache_1d"
OUT = ROOT / "output"
IST = ZoneInfo("Asia/Kolkata")
YEARS = 6
COST_PS = 0.001
SKIP = {"GVTD.NS", "GVT&D.NS"}
YF_OVERRIDE = {
    "GVT&D": "GVT&D.NS",
    "NAM-INDIA": "NAM-INDIA.NS",
    "GMRP&UI": "GMRP&UI.NS",
}
UNIVERSE_CSV = {
    "alpha50": ROOT / "nifty_Alpha_Index.csv",
    "momentum50": ROOT / "niftymidcap150momentum50.csv",
}
LOOKBACKS = (21, 63, 126)
KS = (5, 10, 20)
FREQS = ("W", "2W", "M")
FILTERS = (("dual", 0.0), ("relative", None))
BENCH = "^NSEI"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%Y-%m-%dT%H:%M:%S")
log = logging.getLogger("topn_grid")


def yf_symbol(sym: str) -> str:
    s = str(sym).strip().upper()
    if s in YF_OVERRIDE:
        return YF_OVERRIDE[s]
    clean = "".join(ch for ch in s if ch.isalnum() or ch in ".-")
    return clean if clean.endswith(".NS") else f"{clean}.NS"


def load_symbols(csv_path: Path) -> list[str]:
    df = pd.read_csv(csv_path)
    col = "Symbol" if "Symbol" in df.columns else "symbol"
    out = []
    for raw in df[col].astype(str):
        raw_s = raw.strip().upper()
        if not raw_s or raw_s.startswith("DUMMY"):
            continue
        try:
            s = yf_symbol(raw_s)
        except Exception:
            continue
        if s and s not in SKIP:
            out.append(s)
    return sorted(set(out))


def _normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [str(c[0]) for c in df.columns]
    rename = {}
    for c in df.columns:
        cl = str(c).lower()
        if cl == "open":
            rename[c] = "Open"
        elif cl == "high":
            rename[c] = "High"
        elif cl == "low":
            rename[c] = "Low"
        elif cl in ("close", "adj close"):
            if "Close" not in rename.values():
                rename[c] = "Close"
        elif cl == "volume":
            rename[c] = "Volume"
    out = df.rename(columns=rename)
    keep = [c for c in ("Open", "High", "Low", "Close", "Volume") if c in out.columns]
    if "Close" not in keep:
        return pd.DataFrame()
    out = out[keep].copy()
    out.index = pd.to_datetime(out.index)
    if getattr(out.index, "tz", None) is not None:
        out.index = out.index.tz_localize(None)
    out = out[~out.index.duplicated(keep="last")].sort_index()
    return out.dropna(subset=["Close"])


def _split_yf_batch(raw: pd.DataFrame, symbols: list[str]) -> dict[str, pd.DataFrame]:
    parsed: dict[str, pd.DataFrame] = {}
    if raw is None or raw.empty:
        return parsed
    if isinstance(raw.columns, pd.MultiIndex):
        level0 = set(raw.columns.get_level_values(0))
        level1 = set(raw.columns.get_level_values(1))
        for s in symbols:
            try:
                if s in level0:
                    piece = raw[s]
                elif s in level1:
                    piece = raw.xs(s, axis=1, level=1)
                else:
                    continue
                df = _normalize_ohlcv(piece)
                if not df.empty:
                    parsed[s] = df
            except Exception:
                continue
        return parsed
    df = _normalize_ohlcv(raw)
    if not df.empty and len(symbols) == 1:
        parsed[symbols[0]] = df
    return parsed


def cache_fresh_enough(df: pd.DataFrame, warm: pd.Timestamp, end_ok: pd.Timestamp) -> bool:
    if df.empty:
        return False
    return df.index.min() <= warm + pd.Timedelta(days=90) and df.index.max() >= end_ok


def download_closes(symbols: list[str], start: str, end: str) -> dict[str, pd.DataFrame]:
    CACHE.mkdir(parents=True, exist_ok=True)
    yf_end = (pd.Timestamp(end) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    warm = pd.Timestamp(start)
    end_ok = pd.Timestamp(end) - pd.Timedelta(days=7)
    loaded: dict[str, pd.DataFrame] = {}
    need: list[str] = []
    for s in symbols:
        path = CACHE / f"{s.replace('.', '_')}_1d.csv"
        if path.exists():
            df = _normalize_ohlcv(pd.read_csv(path, parse_dates=[0], index_col=0))
            if cache_fresh_enough(df, warm, end_ok):
                loaded[s] = df
                continue
        need.append(s)
    if need:
        log.info("Downloading daily batch n=%d start=%s", len(need), start)
        try:
            raw = yf.download(
                need,
                start=start,
                end=yf_end,
                interval="1d",
                auto_adjust=True,
                progress=False,
                threads=True,
                group_by="ticker",
            )
            parsed = _split_yf_batch(raw, need)
            for s, df in parsed.items():
                df.to_csv(CACHE / f"{s.replace('.', '_')}_1d.csv", index_label="Date")
                loaded[s] = df
            missing = [s for s in need if s not in parsed]
        except Exception as e:
            log.warning("batch failed: %s", e)
            missing = need
        for s in missing:
            try:
                log.info("retry %s", s)
                raw = yf.download(s, start=start, end=yf_end, interval="1d", auto_adjust=True, progress=False, threads=False)
                df = _normalize_ohlcv(raw)
                if not df.empty:
                    df.to_csv(CACHE / f"{s.replace('.', '_')}_1d.csv", index_label="Date")
                    loaded[s] = df
                time.sleep(0.05)
            except Exception as e:
                log.warning("skip %s: %s", s, e)
    return loaded


def close_matrix(ohlcv: dict[str, pd.DataFrame], symbols: list[str]) -> pd.DataFrame:
    series = []
    for s in symbols:
        df = ohlcv.get(s)
        if df is None or df.empty or "Close" not in df.columns:
            continue
        series.append(df["Close"].rename(s))
    if not series:
        return pd.DataFrame()
    out = pd.concat(series, axis=1, sort=True).sort_index()
    out = out.loc[~out.index.duplicated(keep="last")]
    return out


def pct(x) -> str:
    if x is None or (isinstance(x, float) and (np.isnan(x) or np.isinf(x))):
        return "n/a"
    return f"{x * 100:.1f}%"


def fmt_row(r: pd.Series, prefix: str) -> str:
    return (
        f"| {r['label']} | {pct(r[f'{prefix}_cagr'])} | {pct(r[f'{prefix}_total'])} | "
        f"{pct(r[f'{prefix}_max_dd'])} | {r[f'{prefix}_sharpe']:.2f} |"
        if np.isfinite(r.get(f"{prefix}_sharpe", np.nan))
        else f"| {r['label']} | {pct(r[f'{prefix}_cagr'])} | {pct(r[f'{prefix}_total'])} | {pct(r[f'{prefix}_max_dd'])} | n/a |"
    )


def pick_best(df: pd.DataFrame, cagr_col: str, dd_col: str) -> pd.Series:
    work = df.dropna(subset=[cagr_col]).copy()
    work["_rank"] = work[cagr_col] - 0.15 * work[dd_col].abs()
    return work.sort_values("_rank", ascending=False).iloc[0]


def write_recommendation(grid: pd.DataFrame, benches: dict, out_md: Path) -> None:
    dual = grid[grid["filter"] == "dual"].copy()
    lines = [
        "# Alpha / Momentum Top-N POC — which to pick",
        "",
        "Strategy: dual momentum (N-day ROC, hold only names with ROC > 0, equal-weight Top-K).",
        "Costs: 10 bps per side. Ranking lagged one session. Current index members (survivorship bias).",
        "",
        "## Pick",
        "",
    ]
    p2 = pick_best(dual, "y2_cagr", "y2_max_dd")
    p1 = pick_best(dual, "y1_cagr", "y1_max_dd")
    p6 = pick_best(dual, "y6_cagr", "y6_max_dd")
    lines += [
        f"**Primary pick (last 2 years):** `{p2['label']}`",
        f"- 2y CAGR {pct(p2['y2_cagr'])}, 1y CAGR {pct(p2['y1_cagr'])}, 6y CAGR {pct(p2['y6_cagr'])}",
        f"- 2y max DD {pct(p2['y2_max_dd'])}, avg holdings {p2['avg_holdings']:.1f}, avg cash {pct(p2['avg_cash'])}",
        "",
        f"**Last-1-year winner:** `{p1['label']}` — 1y CAGR {pct(p1['y1_cagr'])}, 1y max DD {pct(p1['y1_max_dd'])}",
        "",
        f"**Last-6-year winner:** `{p6['label']}` — 6y CAGR {pct(p6['y6_cagr'])}, 6y max DD {pct(p6['y6_max_dd'])}",
        "",
    ]
    same = p2["label"] == p1["label"] == p6["label"]
    if same:
        lines.append("The same combination leads all three windows — that is the one to run.")
    elif p2["label"] == p1["label"]:
        lines.append(
            "Last 2y and last 1y agree. Prefer that book over the 6y winner if they differ — "
            "the 6y window is more distorted by current-constituent survivorship and the 2020–21 rebound."
        )
    else:
        lines.append(
            "Windows disagree. Prefer the last-2-year pick for live use, and treat the last-1-year "
            "winner as a regime check (it can be a concentrated luck path)."
        )
    lines += ["", "## Benchmarks", ""]
    for name, m in benches.items():
        lines.append(
            f"- **{name}**: 6y CAGR {pct(m['y6']['cagr'])} | 2y CAGR {pct(m['y2']['cagr'])} | "
            f"1y CAGR {pct(m['y1']['cagr'])} | 6y max DD {pct(m['y6']['max_dd'])}"
        )
    lines += [
        "",
        "## Top 8 by last-2-year CAGR (dual momentum only)",
        "",
        "| Combo | 2y CAGR | 2y total | 2y max DD | 2y Sharpe |",
        "|---|---:|---:|---:|---:|",
    ]
    top = dual.sort_values("y2_cagr", ascending=False).head(8)
    for _, r in top.iterrows():
        sh = r["y2_sharpe"]
        shs = f"{sh:.2f}" if np.isfinite(sh) else "n/a"
        lines.append(f"| {r['label']} | {pct(r['y2_cagr'])} | {pct(r['y2_total'])} | {pct(r['y2_max_dd'])} | {shs} |")
    lines += [
        "",
        "## Same 8 — last 1 year and last 6 years",
        "",
        "| Combo | 1y CAGR | 1y max DD | 6y CAGR | 6y max DD |",
        "|---|---:|---:|---:|---:|",
    ]
    for _, r in top.iterrows():
        lines.append(
            f"| {r['label']} | {pct(r['y1_cagr'])} | {pct(r['y1_max_dd'])} | {pct(r['y6_cagr'])} | {pct(r['y6_max_dd'])} |"
        )
    lines += [
        "",
        "## How to read Top-5 vs Top-10 vs Top-20",
        "",
        "- **Top-5** usually prints the highest gross CAGR and the deepest drawdowns. Weekly Top-5 also pays the most in costs.",
        "- **Top-10** is the typical live compromise: still concentrated, less single-name ruin.",
        "- **Top-20** is closer to the index itself; alpha vs equal-weight universe shrinks, turnover falls.",
        "",
        "## How to read weekly vs bi-weekly vs monthly",
        "",
        "- **Weekly** fits 21-day ROC (the live dual_mom_w21 analog). Faster rotation, more cost drag.",
        "- **Bi-weekly** cuts turnover roughly in half versus weekly; useful if 2y/1y CAGRs stay close to weekly.",
        "- **Monthly** fits 63d/126d ROC. Lower cost, slower to exit losers — dual (ROC>0 cash) matters more here.",
        "",
        "## Caveats",
        "",
        "- Current Alpha 50 / Momentum 50 members are used for the whole 6 years (survivorship). 6y numbers are optimistic.",
        "- Last 2y and last 1y are the decision windows; they still use today's members but the bias is smaller.",
        "- No point-in-time float, freeze, or corporate-action audit beyond Yahoo adjusted close.",
        "- Relative-only (always fully invested) is in `grid_results.csv` as a control; the pick above is dual momentum.",
        "",
    ]
    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    end = datetime.now(IST).date()
    test_end = pd.Timestamp(end)
    test_start = test_end - pd.DateOffset(years=YEARS)
    warm_start = test_start - pd.DateOffset(days=400)
    y2 = test_end - pd.DateOffset(years=2)
    y1 = test_end - pd.DateOffset(years=1)

    universes = {name: load_symbols(path) for name, path in UNIVERSE_CSV.items()}
    universes["combined"] = sorted(set(universes["alpha50"]) | set(universes["momentum50"]))
    all_syms = universes["combined"] + [BENCH]
    log.info("symbols=%d alpha=%d mom=%d combined=%d", len(all_syms), len(universes["alpha50"]), len(universes["momentum50"]), len(universes["combined"]))

    ohlcv = download_closes(all_syms, warm_start.strftime("%Y-%m-%d"), test_end.strftime("%Y-%m-%d"))
    full_close = close_matrix(ohlcv, [s for s in all_syms if s != BENCH])
    bench_close = close_matrix(ohlcv, [BENCH] if BENCH in ohlcv else [])
    if full_close.empty:
        log.error("no price data")
        return 1
    full_close = full_close.loc[full_close.index >= warm_start]
    test_close = full_close.loc[full_close.index >= test_start]

    rows = []
    equity_store: dict[str, pd.Series] = {}
    for uname, symbols in universes.items():
        cols = [s for s in symbols if s in test_close.columns]
        close = test_close[cols].copy()
        log.info("universe %s names=%d", uname, close.shape[1])
        for lookback in LOOKBACKS:
            score = roc_score(full_close[cols], lookback).reindex(close.index)
            for k in KS:
                for freq in FREQS:
                    for filt_name, min_score in FILTERS:
                        label = f"{uname}|lb{lookback}|top{k}|{freq}|{filt_name}"
                        res = simulate_top_k(close, score, k=k, freq=freq, cost_per_side=COST_PS, min_score=min_score)
                        eq = res["equity"]
                        m6 = window_metrics(eq, test_start)
                        m2 = window_metrics(eq, y2)
                        m1 = window_metrics(eq, y1)
                        rows.append(
                            {
                                "label": label,
                                "universe": uname,
                                "lookback": lookback,
                                "k": k,
                                "freq": freq,
                                "filter": filt_name,
                                "y6_cagr": m6["cagr"],
                                "y6_total": m6["total_return"],
                                "y6_max_dd": m6["max_dd"],
                                "y6_sharpe": m6["sharpe"],
                                "y2_cagr": m2["cagr"],
                                "y2_total": m2["total_return"],
                                "y2_max_dd": m2["max_dd"],
                                "y2_sharpe": m2["sharpe"],
                                "y1_cagr": m1["cagr"],
                                "y1_total": m1["total_return"],
                                "y1_max_dd": m1["max_dd"],
                                "y1_sharpe": m1["sharpe"],
                                "turnover": res["turnover"],
                                "rebalances": res["rebalances"],
                                "avg_cash": res["avg_cash"],
                                "avg_holdings": res["avg_holdings"],
                            }
                        )
                        equity_store[label] = eq

    grid = pd.DataFrame(rows)
    grid.to_csv(OUT / "grid_results.csv", index=False)

    benches = {}
    for uname, symbols in universes.items():
        cols = [s for s in symbols if s in test_close.columns]
        ew = buy_and_hold_ew(test_close[cols])
        benches[f"{uname} EW buy-hold"] = {
            "y6": window_metrics(ew, test_start),
            "y2": window_metrics(ew, y2),
            "y1": window_metrics(ew, y1),
        }
        equity_store[f"bench_{uname}_ew"] = ew
    if not bench_close.empty:
        nse = bench_close.iloc[:, 0].dropna()
        nse_eq = nse / nse.iloc[0]
        nse_eq = nse_eq.loc[nse_eq.index >= test_start]
        benches["Nifty 50"] = {
            "y6": window_metrics(nse_eq, test_start),
            "y2": window_metrics(nse_eq, y2),
            "y1": window_metrics(nse_eq, y1),
        }
        equity_store["bench_nifty50"] = nse_eq

    write_recommendation(grid, benches, OUT / "recommendation.md")

    dual = grid[grid["filter"] == "dual"]
    p2 = pick_best(dual, "y2_cagr", "y2_max_dd")
    p1 = pick_best(dual, "y1_cagr", "y1_max_dd")
    p6 = pick_best(dual, "y6_cagr", "y6_max_dd")
    summary = {
        "asof": test_end.strftime("%Y-%m-%d"),
        "cost_per_side": COST_PS,
        "pick_2y": p2["label"],
        "pick_1y": p1["label"],
        "pick_6y": p6["label"],
        "picks": {
            "2y": p2.to_dict(),
            "1y": p1.to_dict(),
            "6y": p6.to_dict(),
        },
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")

    keep = {p2["label"], p1["label"], p6["label"]}
    eq_df = pd.DataFrame({k: equity_store[k] for k in keep if k in equity_store})
    eq_df.to_csv(OUT / "equity_picks.csv")
    log.info("wrote %s rows to %s", len(grid), OUT / "grid_results.csv")
    log.info("pick 2y=%s 1y=%s 6y=%s", p2["label"], p1["label"], p6["label"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
