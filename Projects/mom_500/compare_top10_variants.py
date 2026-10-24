#!/usr/bin/env python3
"""Compare Nifty 500 Top-10 monthly momentum variants vs the live 63d ROC book.

Same engine as the 20y grid: equal-weight Top-10, monthly rebalance, 10 bps/side,
score lagged one session. Current members only (survivorship).
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
POC = ROOT.parent / "AlphaMom_TopN_POC"
sys.path.insert(0, str(POC))
sys.path.insert(0, str(ROOT))

from backtest_core import rebalance_mask, simulate_top_k, window_metrics  # noqa: E402
from run_nifty500_mom_backtest import merge_cache_download  # noqa: E402
from run_topn_grid import BENCH, COST_PS, close_matrix  # noqa: E402
from universe import load_symbols  # noqa: E402

OUT = ROOT / "output"
IST = ZoneInfo("Asia/Kolkata")
K = 10
FREQ = "M"


def roc(close: pd.DataFrame, n: int) -> pd.DataFrame:
    return close.pct_change(n).shift(1)


def skip_recent(close: pd.DataFrame, long: int, skip: int) -> pd.DataFrame:
    """Return from t-long to t-skip, lagged one more session."""
    return (close.shift(skip) / close.shift(long) - 1.0).shift(1)


def sma_gate(score: pd.DataFrame, close: pd.DataFrame, window: int) -> pd.DataFrame:
    sma = close.rolling(window, min_periods=window).mean()
    above = close.shift(1) > sma.shift(1)
    return score.where(above)


def index_gate(score: pd.DataFrame, nifty: pd.Series, window: int) -> pd.DataFrame:
    sma = nifty.rolling(window, min_periods=window).mean()
    bull = (nifty.shift(1) > sma.shift(1)).reindex(score.index)
    out = score.copy()
    out.loc[~bull.fillna(False)] = np.nan
    return out


def vol_adj(close: pd.DataFrame, n: int, vol_n: int) -> pd.DataFrame:
    r = close.pct_change(n)
    vol = close.pct_change().rolling(vol_n, min_periods=vol_n).std()
    return (r / vol.replace(0, np.nan)).shift(1)


def residual_mom(close: pd.DataFrame, nifty: pd.Series, n: int, beta_n: int) -> pd.DataFrame:
    sr = close.pct_change()
    nr = nifty.pct_change().reindex(close.index)
    sn = sr.mul(nr, axis=0)
    mean_s = sr.rolling(beta_n, min_periods=beta_n).mean()
    mean_n = nr.rolling(beta_n, min_periods=beta_n).mean()
    mean_sn = sn.rolling(beta_n, min_periods=beta_n).mean()
    var_n = nr.rolling(beta_n, min_periods=beta_n).var()
    beta = (mean_sn.sub(mean_s.mul(mean_n, axis=0), axis=0)).div(var_n.replace(0, np.nan), axis=0)
    resid = close.pct_change(n).sub(beta.mul(nifty.pct_change(n), axis=0), axis=0)
    return resid.shift(1)


def zsum(a: pd.DataFrame, b: pd.DataFrame) -> pd.DataFrame:
    def z(df: pd.DataFrame) -> pd.DataFrame:
        mu = df.mean(axis=1)
        sd = df.std(axis=1).replace(0, np.nan)
        return df.sub(mu, axis=0).div(sd, axis=0)

    return z(a) + z(b)


def positive_only(score: pd.DataFrame, raw: pd.DataFrame) -> pd.DataFrame:
    """Keep a ranking score only where the raw momentum is positive."""
    return score.where(raw > 0)


def month_end_mask(index: pd.DatetimeIndex) -> np.ndarray:
    s = pd.Series(index, index=index)
    period = s.dt.to_period("M")
    mask = period != period.shift(-1)
    mask = mask.fillna(True)
    mask.iloc[0] = True
    return mask.to_numpy(dtype=bool)


def simulate_buffered(
    close: pd.DataFrame,
    score: pd.DataFrame,
    k: int = 10,
    buffer: int = 20,
    cost_per_side: float = 0.001,
    min_score: float | None = 0.0,
    month_end: bool = False,
) -> dict:
    """Top-K with a hold buffer: keep a name until it falls out of the top `buffer`."""
    aligned = close.copy()
    sc = score.reindex_like(aligned)
    px = aligned.to_numpy(dtype=float)
    sc_v = sc.to_numpy(dtype=float)
    valid = np.isfinite(px) & (px > 0)
    n, m = px.shape
    rets = np.zeros((n, m), dtype=float)
    prev = px[:-1]
    cur = px[1:]
    ok = np.isfinite(prev) & np.isfinite(cur) & (prev > 0)
    rets[1:] = np.where(ok, cur / prev - 1.0, 0.0)
    reb = month_end_mask(aligned.index) if month_end else rebalance_mask(aligned.index, "M")

    weights = np.zeros(m, dtype=float)
    equity = np.ones(n, dtype=float)
    turnover_traded = 0.0
    held = np.zeros(m, dtype=bool)

    for i in range(n):
        if reb[i]:
            row = sc_v[i]
            eligible = valid[i] & np.isfinite(row)
            if min_score is not None:
                eligible = eligible & (row > min_score)
            idx = np.where(eligible)[0]
            target = np.zeros(m, dtype=float)
            if idx.size:
                order = idx[np.argsort(-row[idx])]
                rank = {int(j): r for r, j in enumerate(order)}
                keep = [int(j) for j in np.where(held)[0] if int(j) in rank and rank[int(j)] < buffer]
                chosen = list(keep)
                for j in order:
                    if len(chosen) >= k:
                        break
                    jj = int(j)
                    if jj not in chosen:
                        chosen.append(jj)
                chosen = chosen[:k]
                if chosen:
                    target[chosen] = 1.0 / float(len(chosen))
            base = equity[i - 1] if i else 1.0
            traded = float(np.abs(target - weights).sum())
            equity[i] = base * (1.0 - traded * cost_per_side)
            weights = target
            held = target > 0
            turnover_traded += traded
        elif i:
            equity[i] = equity[i - 1]

        if i:
            port_r = float(np.dot(weights, rets[i]))
            equity[i] *= 1.0 + port_r
            invested = weights * (1.0 + rets[i])
            cash = max(0.0, 1.0 - float(weights.sum()))
            total = float(invested.sum()) + cash
            weights = invested / total if total > 1e-12 else np.zeros(m, dtype=float)

    eq = pd.Series(equity, index=aligned.index, name="equity")
    return {"equity": eq, "turnover": turnover_traded, "avg_cash": 0.0, "avg_holdings": float(k)}


def metrics_block(eq: pd.Series, start: pd.Timestamp, end: pd.Timestamp) -> dict:
    s = eq[(eq.index >= start) & (eq.index <= end)]
    if len(s) < 5:
        return {"cagr": np.nan, "max_dd": np.nan, "sharpe": np.nan, "total": np.nan}
    m = window_metrics(s, s.index[0])
    return {"cagr": m["cagr"], "max_dd": m["max_dd"], "sharpe": m["sharpe"], "total": m["total_return"]}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    end = pd.Timestamp(datetime.now(IST).date())
    test_start = end - pd.DateOffset(years=20)
    warm = test_start - pd.DateOffset(days=400)
    mid = test_start + pd.DateOffset(years=10)
    y5 = end - pd.DateOffset(years=5)

    symbols = load_symbols()
    ohlcv = merge_cache_download(symbols + [BENCH], warm.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
    full = close_matrix(ohlcv, symbols)
    full = full.loc[full.index >= warm]
    test = full.loc[full.index >= test_start]
    nifty = close_matrix(ohlcv, [BENCH]).iloc[:, 0].reindex(full.index).ffill()
    print(f"names={test.shape[1]} {test.index.min().date()}..{test.index.max().date()}", flush=True)

    roc63 = roc(full, 63).reindex(test.index)
    roc126 = roc(full, 126).reindex(test.index)
    roc252 = roc(full, 252).reindex(test.index)
    m12_1 = skip_recent(full, 252, 21).reindex(test.index)
    m6_1 = skip_recent(full, 126, 21).reindex(test.index)
    blend = positive_only(zsum(roc(full, 63), roc(full, 126)).reindex(test.index), roc63)

    variants: list[tuple[str, pd.DataFrame, float | None]] = [
        ("roc63_dual", roc63, 0.0),
        ("roc126_dual", roc126, 0.0),
        ("roc252_dual", roc252, 0.0),
        ("mom12_1_dual", m12_1, 0.0),
        ("mom6_1_dual", m6_1, 0.0),
        ("roc63_sma200", sma_gate(roc63, full, 200).reindex(test.index), 0.0),
        ("roc63_nifty200", index_gate(roc63, nifty, 200).reindex(test.index), 0.0),
        ("mom12_1_sma200", sma_gate(m12_1, full, 200).reindex(test.index), 0.0),
        ("roc63_sma200_nifty200", index_gate(sma_gate(roc63, full, 200), nifty, 200).reindex(test.index), 0.0),
        ("voladj63_dual", vol_adj(full, 63, 63).reindex(test.index), 0.0),
        ("resid63_dual", residual_mom(full, nifty, 63, 126).reindex(test.index), 0.0),
        ("blend63_126_pos", blend, None),
        ("roc42_dual", roc(full, 42).reindex(test.index), 0.0),
        ("roc84_dual", roc(full, 84).reindex(test.index), 0.0),
        ("roc63_sma50", sma_gate(roc63, full, 50).reindex(test.index), 0.0),
        ("roc63_nifty100", index_gate(roc63, nifty, 100).reindex(test.index), 0.0),
        ("roc63_min10", roc63, 0.10),
    ]

    rows = []
    for name, score, min_score in variants:
        print(f"sim {name}", flush=True)
        res = simulate_top_k(test, score, k=K, freq=FREQ, cost_per_side=COST_PS, min_score=min_score)
        eq = res["equity"]
        full_m = metrics_block(eq, test_start, end)
        h1 = metrics_block(eq, test_start, mid)
        h2 = metrics_block(eq, mid, end)
        last5 = metrics_block(eq, y5, end)
        calmar = full_m["cagr"] / abs(full_m["max_dd"]) if full_m["max_dd"] and full_m["max_dd"] < 0 else np.nan
        rows.append(
            {
                "variant": name,
                "cagr": full_m["cagr"],
                "max_dd": full_m["max_dd"],
                "sharpe": full_m["sharpe"],
                "calmar": calmar,
                "h1_cagr": h1["cagr"],
                "h1_dd": h1["max_dd"],
                "h2_cagr": h2["cagr"],
                "h2_dd": h2["max_dd"],
                "y5_cagr": last5["cagr"],
                "y5_dd": last5["max_dd"],
                "avg_cash": res["avg_cash"],
                "avg_holdings": res["avg_holdings"],
                "turnover": res["turnover"],
            }
        )

    extra = [
        ("roc63_buf15", roc63, 15, False),
        ("roc63_buf20", roc63, 20, False),
        ("roc63_buf30", roc63, 30, False),
        ("roc63_month_end", roc63, 10, True),
        ("roc63_buf20_me", roc63, 20, True),
    ]
    for name, score, buffer, month_end in extra:
        print(f"sim {name}", flush=True)
        res = simulate_buffered(
            test, score, k=K, buffer=buffer, cost_per_side=COST_PS, min_score=0.0, month_end=month_end
        )
        eq = res["equity"]
        full_m = metrics_block(eq, test_start, end)
        h1 = metrics_block(eq, test_start, mid)
        h2 = metrics_block(eq, mid, end)
        last5 = metrics_block(eq, y5, end)
        calmar = full_m["cagr"] / abs(full_m["max_dd"]) if full_m["max_dd"] and full_m["max_dd"] < 0 else np.nan
        rows.append(
            {
                "variant": name,
                "cagr": full_m["cagr"],
                "max_dd": full_m["max_dd"],
                "sharpe": full_m["sharpe"],
                "calmar": calmar,
                "h1_cagr": h1["cagr"],
                "h1_dd": h1["max_dd"],
                "h2_cagr": h2["cagr"],
                "h2_dd": h2["max_dd"],
                "y5_cagr": last5["cagr"],
                "y5_dd": last5["max_dd"],
                "avg_cash": res["avg_cash"],
                "avg_holdings": res["avg_holdings"],
                "turnover": res["turnover"],
            }
        )

    df = pd.DataFrame(rows).sort_values(["calmar", "cagr"], ascending=False)
    df.to_csv(OUT / "top10_variant_compare.csv", index=False)
    base = df.loc[df["variant"] == "roc63_dual"].iloc[0]
    print("\nBASE roc63_dual", flush=True)
    print(
        f"  cagr={base['cagr']*100:.1f}% dd={base['max_dd']*100:.1f}% "
        f"sharpe={base['sharpe']:.2f} calmar={base['calmar']:.2f} "
        f"h1={base['h1_cagr']*100:.1f}% h2={base['h2_cagr']*100:.1f}% y5={base['y5_cagr']*100:.1f}%",
        flush=True,
    )
    print("\nALL", flush=True)
    show = df.copy()
    for c in ("cagr", "max_dd", "h1_cagr", "h1_dd", "h2_cagr", "h2_dd", "y5_cagr", "y5_dd", "avg_cash"):
        show[c] = (show[c] * 100).round(1)
    show["sharpe"] = show["sharpe"].round(2)
    show["calmar"] = show["calmar"].round(2)
    print(show.to_string(index=False), flush=True)

    robust = df[
        (df["h1_cagr"] >= base["h1_cagr"] - 0.01)
        & (df["h2_cagr"] >= base["h2_cagr"] - 0.01)
        & (df["cagr"] > base["cagr"])
        & (df["max_dd"] >= base["max_dd"] - 0.03)
        & (df["variant"] != "roc63_dual")
    ].sort_values(["cagr", "calmar"], ascending=False)
    print("\nROBUST (beat full CAGR, both halves within 1pp, DD not >3pp worse)", flush=True)
    if robust.empty:
        print("  none", flush=True)
    else:
        print(robust[["variant", "cagr", "max_dd", "sharpe", "calmar", "h1_cagr", "h2_cagr", "y5_cagr"]].to_string(index=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
