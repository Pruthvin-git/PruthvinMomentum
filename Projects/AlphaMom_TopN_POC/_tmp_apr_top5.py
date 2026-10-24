from pathlib import Path

import pandas as pd

from backtest_core import dual_top_k, is_biweekly_friday, roc_score
from run_topn_grid import CACHE, UNIVERSE_CSV, close_matrix, load_symbols

names_df = pd.read_csv(UNIVERSE_CSV["alpha50"])
names = {str(r["Symbol"]).strip().upper(): r["Company Name"] for _, r in names_df.iterrows()}
symbols = load_symbols(UNIVERSE_CSV["alpha50"])
ohlcv = {}
for s in symbols:
    p = CACHE / f"{s.replace('.', '_')}_1d.csv"
    if p.exists():
        ohlcv[s] = pd.read_csv(p, parse_dates=["Date"], index_col="Date")
close = close_matrix(ohlcv, symbols)
score = roc_score(close, 21)
print("close range", close.index.min().date(), close.index.max().date(), "n", len(close.columns))
window = [d for d in close.index if pd.Timestamp("2026-03-27") <= d <= pd.Timestamp("2026-04-10")]
print("--- daily dual top5 (21d ROC>0) ---")
for ts in window:
    picks = dual_top_k(close.loc[ts], score.loc[ts], 5)
    tag = []
    if int(ts.weekday()) == 4:
        tag.append("FRI")
    if is_biweekly_friday(ts):
        tag.append("2W-REBALANCE")
    print(str(ts.date()), ts.day_name()[:3], " ".join(tag))
    for i, s in enumerate(picks, 1):
        roc = float(score.at[ts, s]) * 100
        px = float(close.at[ts, s])
        sym = s.replace(".NS", "")
        print(f"  {i}. {sym:12} {names.get(sym, ''):40} ROC21 {roc:7.2f}%  close {px:.2f}")

asof = pd.Timestamp("2026-04-01")
if asof not in close.index:
    asof = max(d for d in close.index if d <= pd.Timestamp("2026-04-01"))
print("--- 1Y return top5 as of", asof.date(), "---")
rets = []
for s in close.columns:
    hist = close[s].loc[:asof].dropna()
    if len(hist) < 20:
        continue
    start = hist.index[-1] - pd.Timedelta(days=365)
    h = hist.loc[hist.index >= start]
    if len(h) < 20:
        continue
    r = float(h.iloc[-1] / h.iloc[0] - 1)
    rets.append((r, s, float(h.iloc[-1])))
rets.sort(reverse=True)
for i, (r, s, px) in enumerate(rets[:5], 1):
    sym = s.replace(".NS", "")
    print(f"  {i}. {sym:12} {names.get(sym, ''):40} 1Y {r*100:7.1f}%  close {px:.2f}")
