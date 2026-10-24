"""Lookahead-safe equal-weight Top-K dual-momentum simulator."""
from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS = 252

# Calendar-day total-return windows from the last equity point (matches period_returns.py in each book).
PERIOD_WINDOWS = (
    ("1W", 7),
    ("1M", 30),
    ("3M", 91),
    ("6M", 182),
    ("1Y", 365),
    ("3Y", 1095),
    ("5Y", 1825),
)


def rebalance_mask(index: pd.DatetimeIndex, freq: str) -> np.ndarray:
    """True on the first session of each weekly / biweekly / monthly period."""
    s = pd.Series(index, index=index)
    if freq == "W":
        period = s.dt.to_period("W-FRI")
        mask = period != period.shift(1)
    elif freq == "2W":
        period = s.dt.to_period("W-FRI")
        week_start = period != period.shift(1)
        ordinal = period.map(lambda p: int(p.ordinal))
        mask = week_start & (ordinal % 2 == 0)
    elif freq == "M":
        period = s.dt.to_period("M")
        mask = period != period.shift(1)
    else:
        raise ValueError(f"unsupported freq {freq}")
    mask = mask.fillna(True)
    mask.iloc[0] = True
    return mask.to_numpy(dtype=bool)


def wfri_even(ts) -> bool:
    """True on even W-FRI weeks — same fortnight clock as freq='2W' in the grid."""
    return int(pd.Timestamp(ts).to_period("W-FRI").ordinal) % 2 == 0


def is_biweekly_friday(d) -> bool:
    ts = pd.Timestamp(d)
    return int(ts.weekday()) == 4 and wfri_even(ts)


def dual_top_k(close_row: pd.Series, score_row: pd.Series, k: int, min_score: float = 0.0) -> list[str]:
    ranked: list[tuple[float, str]] = []
    for s in score_row.index:
        v = score_row[s]
        px = close_row.get(s) if hasattr(close_row, "get") else close_row[s]
        if pd.notna(v) and float(v) > min_score and pd.notna(px) and float(px) > 0:
            ranked.append((float(v), str(s)))
    ranked.sort(reverse=True)
    return [s for _, s in ranked[:k]]


def roc_score(close: pd.DataFrame, lookback: int) -> pd.DataFrame:
    """N-day ROC lagged one session so ranking never uses the fill bar's close."""
    return close.pct_change(lookback).shift(1)


def simulate_top_k(
    close: pd.DataFrame,
    score: pd.DataFrame,
    k: int,
    freq: str,
    cost_per_side: float = 0.001,
    min_score: float | None = 0.0,
) -> dict:
    """
    Equal-weight Top-K.

    Timeline: score is already lagged. On a rebalance bar we set target weights,
    pay cost on traded notional, then those weights earn that bar's close-to-close
    return (decision after T-1 close, fill near T open / T close-to-close).

    If min_score is 0.0 (dual momentum), names with ROC <= 0 are skipped and leftover
    weight stays cash. If min_score is None, always hold K names (relative momentum).
    """
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
    reb = rebalance_mask(aligned.index, freq)

    weights = np.zeros(m, dtype=float)
    equity = np.ones(n, dtype=float)
    turnover_traded = 0.0
    n_rebals = 0
    cash_frac = np.ones(n, dtype=float)
    hold_count = np.zeros(n, dtype=float)

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
                take = order[: min(k, order.size)]
                target[take] = 1.0 / float(take.size)
            base = equity[i - 1] if i else 1.0
            traded = float(np.abs(target - weights).sum())
            equity[i] = base * (1.0 - traded * cost_per_side)
            weights = target
            turnover_traded += traded
            n_rebals += 1
        elif i:
            equity[i] = equity[i - 1]

        if i:
            port_r = float(np.dot(weights, rets[i]))
            equity[i] *= 1.0 + port_r
            invested = weights * (1.0 + rets[i])
            cash = max(0.0, 1.0 - float(weights.sum()))
            total = float(invested.sum()) + cash
            if total > 1e-12:
                weights = invested / total
            else:
                weights = np.zeros(m, dtype=float)

        cash_frac[i] = max(0.0, 1.0 - float(np.clip(weights.sum(), 0.0, 1.0)))
        hold_count[i] = float(np.count_nonzero(weights > 1e-8))

    eq = pd.Series(equity, index=aligned.index, name="equity")
    return {
        "equity": eq,
        "turnover": turnover_traded,
        "rebalances": n_rebals,
        "avg_cash": float(np.mean(cash_frac)),
        "avg_holdings": float(np.mean(hold_count)),
    }


def buy_and_hold_ew(close: pd.DataFrame) -> pd.Series:
    """Equal-weight buy-and-hold of names that have a valid first price."""
    px = close.to_numpy(dtype=float)
    n, m = px.shape
    live = np.zeros(m, dtype=bool)
    for j in range(m):
        ok = np.where(np.isfinite(px[:, j]) & (px[:, j] > 0))[0]
        live[j] = ok.size > 0
    rets = np.zeros((n, m))
    prev = px[:-1]
    cur = px[1:]
    ok = np.isfinite(prev) & np.isfinite(cur) & (prev > 0)
    rets[1:] = np.where(ok, cur / prev - 1.0, 0.0)
    equity = np.ones(n)
    w = np.zeros(m)
    if live.any():
        w[live] = 1.0 / live.sum()
    for i in range(1, n):
        r = float(np.dot(w, rets[i]))
        equity[i] = equity[i - 1] * (1.0 + r)
        invested = w * (1.0 + rets[i])
        total = float(invested.sum())
        if total > 1e-12:
            w = invested / total
    return pd.Series(equity, index=close.index, name="ew_bh")


CHART_WINDOWS = (("1Y", 365), ("3Y", 1095), ("5Y", 1825))


def chart_rebased(eq: pd.Series, days: int, step: int = 5, min_coverage: float = 0.7) -> list[dict[str, float | str]]:
    """Daily equity rebased to 100 at the calendar window start (for hub charts)."""
    s = eq.dropna().sort_index()
    if len(s) < 2:
        return []
    last_ts = pd.Timestamp(s.index[-1])
    target = last_ts - pd.Timedelta(days=days)
    prior = s.loc[s.index <= target]
    if prior.empty:
        start_ts = pd.Timestamp(s.index[0])
        base = float(s.iloc[0])
    else:
        start_ts = pd.Timestamp(prior.index[-1])
        base = float(prior.iloc[-1])
    if base <= 0 or (last_ts - start_ts).days < days * min_coverage:
        return []
    window = s.loc[s.index >= start_ts]
    if window.empty:
        return []
    out: list[dict[str, float | str]] = []
    for i in range(0, len(window), step):
        ts = pd.Timestamp(window.index[i])
        out.append({"d": ts.strftime("%Y-%m-%d"), "v": round(float(window.iloc[i]) / base * 100.0, 4)})
    if (len(window) - 1) % step != 0:
        ts = pd.Timestamp(window.index[-1])
        out.append({"d": ts.strftime("%Y-%m-%d"), "v": round(float(window.iloc[-1]) / base * 100.0, 4)})
    return out


def period_returns(eq: pd.Series, min_coverage: float = 0.7) -> dict[str, float | None]:
    """Total return over 1W/1M/1Y/3Y/5Y calendar windows from a daily equity curve."""
    s = eq.dropna().sort_index()
    if len(s) < 2:
        return {key: None for key, _ in PERIOD_WINDOWS}
    last_ts = pd.Timestamp(s.index[-1])
    last_v = float(s.iloc[-1])
    first_ts = pd.Timestamp(s.index[0])
    span_days = (last_ts - first_ts).days
    out: dict[str, float | None] = {}
    for key, days in PERIOD_WINDOWS:
        target = last_ts - pd.Timedelta(days=days)
        if first_ts > target + pd.Timedelta(days=2) and span_days < days * 0.85:
            out[key] = None
            continue
        prior = s.loc[s.index <= target]
        if prior.empty:
            pick_ts = first_ts
            pick_v = float(s.iloc[0])
        else:
            pick_ts = pd.Timestamp(prior.index[-1])
            pick_v = float(prior.iloc[-1])
        if pick_v <= 0 or (last_ts - pick_ts).days < days * min_coverage:
            out[key] = None
        else:
            out[key] = last_v / pick_v - 1.0
    return out


def window_metrics(eq: pd.Series, start: pd.Timestamp | None = None) -> dict:
    s = eq.dropna()
    if start is not None:
        s = s[s.index >= start]
    if len(s) < 5 or float(s.iloc[0]) <= 0:
        return {
            "total_return": np.nan,
            "cagr": np.nan,
            "max_dd": np.nan,
            "sharpe": np.nan,
        }
    total = float(s.iloc[-1] / s.iloc[0] - 1.0)
    years = (s.index[-1] - s.index[0]).days / 365.25
    cagr = float((s.iloc[-1] / s.iloc[0]) ** (1.0 / years) - 1.0) if years > 0 else np.nan
    peak = s.cummax()
    dd = float((s / peak - 1.0).min())
    daily = s.pct_change().dropna()
    sharpe = float(np.sqrt(TRADING_DAYS) * daily.mean() / daily.std()) if float(daily.std() or 0) > 0 else np.nan
    return {"total_return": total, "cagr": cagr, "max_dd": dd, "sharpe": sharpe}
