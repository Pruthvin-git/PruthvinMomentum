"""Microcap 250 k-5 / k-10 weekly & bi-weekly, calendar years from 2020.

Same engine as Alpha: 21-day ROC dual momentum, equal-weight Top-K,
10 bps per side, ranking lagged one session.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from backtest_core import buy_and_hold_ew, roc_score, simulate_top_k, window_metrics
from run_topn_grid import (
    COST_PS,
    UNIVERSE_CSV,
    close_matrix,
    download_closes,
    load_symbols,
    yf_symbol,
)

ROOT = Path(__file__).resolve().parent
MC_CSV = ROOT.parent / "momenta-dma" / "niftymicrocap250.csv"
OUT = ROOT / "output"


def load_microcap_symbols() -> list[str]:
    df = pd.read_csv(MC_CSV)
    col = "Symbol" if "Symbol" in df.columns else "symbol"
    out: list[str] = []
    for raw in df[col].astype(str):
        s = raw.strip().upper()
        if not s or s.startswith("DUMMY"):
            continue
        out.append(yf_symbol(s))
    return sorted(set(out))


def calendar_rows(eq: pd.Series) -> list[dict]:
    rows = []
    last_year = int(eq.index.max().year)
    for year in range(2020, last_year + 1):
        prev = eq[eq.index.year < year]
        cur = eq[eq.index.year == year]
        if cur.empty:
            continue
        start = float(prev.iloc[-1]) if len(prev) else float(cur.iloc[0])
        end = float(cur.iloc[-1])
        if start <= 0:
            continue
        peak = cur.cummax()
        # drawdown vs peak reached during the year, anchored at year-start equity
        path = pd.concat([pd.Series([start], index=[cur.index[0] - pd.Timedelta(days=1)]), cur])
        dd = float((path / path.cummax() - 1.0).min())
        rows.append(
            {
                "year": year,
                "total": end / start - 1.0,
                "max_dd": dd,
                "sessions": int(len(cur)),
            }
        )
    return rows


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    mc = load_microcap_symbols()
    alpha = load_symbols(UNIVERSE_CSV["alpha50"])
    all_syms = sorted(set(mc) | set(alpha) | {"^NSEI"})
    print(f"microcap={len(mc)} alpha={len(alpha)} download={len(all_syms)}", flush=True)

    ohlcv = download_closes(all_syms, "2019-01-01", pd.Timestamp.today().strftime("%Y-%m-%d"))
    full = close_matrix(ohlcv, [s for s in all_syms if s != "^NSEI"])
    full = full.loc[full.index >= pd.Timestamp("2019-01-01")]
    test = full.loc[full.index >= pd.Timestamp("2020-01-01")]
    print(f"close {test.index.min().date()} to {test.index.max().date()} cols={test.shape[1]}", flush=True)

    combos = [
        ("microcap250", mc, 5, "W"),
        ("microcap250", mc, 5, "2W"),
        ("microcap250", mc, 10, "W"),
        ("microcap250", mc, 10, "2W"),
        ("alpha50", alpha, 5, "W"),
        ("alpha50", alpha, 5, "2W"),
        ("alpha50", alpha, 10, "W"),
        ("alpha50", alpha, 10, "2W"),
    ]

    year_rows = []
    summary_rows = []
    eq_store = {}
    for uname, symbols, k, freq in combos:
        cols = [s for s in symbols if s in test.columns]
        close = test[cols].copy()
        score = roc_score(full[cols], 21).reindex(close.index)
        label = f"{uname}|lb21|top{k}|{freq}|dual"
        print(f"sim {label} names={close.shape[1]}", flush=True)
        res = simulate_top_k(close, score, k=k, freq=freq, cost_per_side=COST_PS, min_score=0.0)
        eq = res["equity"]
        eq_store[label] = eq
        overall = window_metrics(eq, pd.Timestamp("2020-01-01"))
        summary_rows.append(
            {
                "label": label,
                "universe": uname,
                "k": k,
                "freq": freq,
                "names": close.shape[1],
                "cagr": overall["cagr"],
                "total": overall["total_return"],
                "max_dd": overall["max_dd"],
                "sharpe": overall["sharpe"],
                "rebalances": res["rebalances"],
                "avg_holdings": res["avg_holdings"],
                "avg_cash": res["avg_cash"],
            }
        )
        for r in calendar_rows(eq):
            year_rows.append({"label": label, "universe": uname, "k": k, "freq": freq, **r})

    # equal-weight buy-hold of current microcap list
    mc_cols = [s for s in mc if s in test.columns]
    ew = buy_and_hold_ew(test[mc_cols])
    eq_store["microcap250|EW"] = ew
    overall = window_metrics(ew, pd.Timestamp("2020-01-01"))
    summary_rows.append(
        {
            "label": "microcap250|EW",
            "universe": "microcap250",
            "k": 0,
            "freq": "BH",
            "names": len(mc_cols),
            "cagr": overall["cagr"],
            "total": overall["total_return"],
            "max_dd": overall["max_dd"],
            "sharpe": overall["sharpe"],
            "rebalances": 0,
            "avg_holdings": float(len(mc_cols)),
            "avg_cash": 0.0,
        }
    )
    for r in calendar_rows(ew):
        year_rows.append({"label": "microcap250|EW", "universe": "microcap250", "k": 0, "freq": "BH", **r})

    years_df = pd.DataFrame(year_rows)
    sum_df = pd.DataFrame(summary_rows)
    years_df.to_csv(OUT / "microcap250_topk_years.csv", index=False)
    sum_df.to_csv(OUT / "microcap250_topk_summary.csv", index=False)
    pd.DataFrame(eq_store).to_csv(OUT / "microcap250_topk_equity.csv")
    print(sum_df.to_string(index=False), flush=True)
    print("--- years ---", flush=True)
    for label in years_df["label"].unique():
        sub = years_df[years_df["label"] == label]
        bits = [f"{int(r.year)} {r.total*100:.1f}%" for r in sub.itertuples()]
        print(f"{label}: " + " | ".join(bits), flush=True)


if __name__ == "__main__":
    main()
