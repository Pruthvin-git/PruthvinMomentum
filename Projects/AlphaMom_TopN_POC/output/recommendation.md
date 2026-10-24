# Alpha / Momentum Top-N POC — which to pick

Strategy: dual momentum (N-day ROC, hold only names with ROC > 0, equal-weight Top-K).
Costs: 10 bps per side. Ranking lagged one session. Current index members (survivorship bias).

## Pick

**Primary pick (last 2 years):** `alpha50|lb21|top5|2W|dual`
- 2y CAGR 72.0%, 1y CAGR 90.9%, 6y CAGR 50.7%
- 2y max DD -20.8%, avg holdings 5.0, avg cash 0.0%

**Last-1-year winner:** `alpha50|lb21|top5|2W|dual` — 1y CAGR 90.9%, 1y max DD -12.6%

**Last-6-year winner:** `combined|lb63|top5|2W|dual` — 6y CAGR 79.4%, 6y max DD -20.8%

Last 2y and last 1y agree. Prefer that book over the 6y winner if they differ — the 6y window is more distorted by current-constituent survivorship and the 2020–21 rebound.

### What I would actually run

| Use | Combo | Why |
|---|---|---|
| **Return-max (last 2y + 1y)** | Alpha 50, 21-day ROC, **Top-5**, **bi-weekly**, dual | Same winner on both focus windows. 2y CAGR 72% vs Alpha-50 EW 40% vs Nifty 50 about -2%. |
| **Live book (recommended)** | Alpha 50, 21-day ROC, **Top-10**, **bi-weekly**, dual | Still +16pp CAGR vs EW over 2y, 6y path is *better* than Top-5 (56% vs 51%) because Top-5 ate a -34% 6y drawdown. 2y DD -17% vs -21%. |
| **Do not pick** | Weekly Top-5, monthly 21-day, Momentum-50 as the primary universe | Weekly Top-5 is the same signal with ~45% more turnover and 2y CAGR 51% vs 72%. Monthly is too slow for 21-day ROC. Momentum-50 EW lagged Alpha-50 in 2y/1y. |

The 6y winner (`combined`, 63-day ROC, Top-5, bi-weekly) is a 2020–23 artefact. Over the last 2 years it is only 49.5% CAGR — behind several Alpha-50 21-day books. Do not switch to it for live use.

## Benchmarks

- **alpha50 EW buy-hold**: 6y CAGR 47.7% | 2y CAGR 39.8% | 1y CAGR 64.9% | 6y max DD -20.3%
- **momentum50 EW buy-hold**: 6y CAGR 44.4% | 2y CAGR 27.2% | 1y CAGR 53.2% | 6y max DD -24.5%
- **combined EW buy-hold**: 6y CAGR 43.5% | 2y CAGR 27.9% | 1y CAGR 53.6% | 6y max DD -22.2%
- **Nifty 50**: 6y CAGR 13.3% | 2y CAGR -2.1% | 1y CAGR -1.4% | 6y max DD -17.2%

## Top 8 by last-2-year CAGR (dual momentum only)

| Combo | 2y CAGR | 2y total | 2y max DD | 2y Sharpe |
|---|---:|---:|---:|---:|
| alpha50|lb21|top5|2W|dual | 72.0% | 195.1% | -20.8% | 2.12 |
| alpha50|lb63|top5|2W|dual | 65.6% | 173.5% | -20.1% | 1.93 |
| alpha50|lb21|top10|2W|dual | 55.9% | 142.5% | -17.0% | 2.12 |
| alpha50|lb63|top5|M|dual | 53.6% | 135.4% | -21.2% | 1.68 |
| alpha50|lb21|top10|W|dual | 53.3% | 134.6% | -18.1% | 2.08 |
| alpha50|lb63|top10|2W|dual | 51.0% | 127.6% | -16.1% | 1.89 |
| alpha50|lb21|top20|2W|dual | 50.9% | 127.2% | -18.6% | 2.13 |
| alpha50|lb21|top5|W|dual | 50.8% | 126.9% | -20.8% | 1.68 |

## Same 8 — last 1 year and last 6 years

| Combo | 1y CAGR | 1y max DD | 6y CAGR | 6y max DD |
|---|---:|---:|---:|---:|
| alpha50|lb21|top5|2W|dual | 90.9% | -12.6% | 50.7% | -33.7% |
| alpha50|lb63|top5|2W|dual | 86.3% | -20.1% | 76.2% | -22.9% |
| alpha50|lb21|top10|2W|dual | 81.3% | -13.1% | 56.1% | -20.7% |
| alpha50|lb63|top5|M|dual | 70.7% | -21.2% | 73.3% | -27.2% |
| alpha50|lb21|top10|W|dual | 76.0% | -15.9% | 59.3% | -22.9% |
| alpha50|lb63|top10|2W|dual | 83.0% | -16.1% | 56.6% | -20.5% |
| alpha50|lb21|top20|2W|dual | 70.3% | -14.1% | 53.1% | -19.5% |
| alpha50|lb21|top5|W|dual | 72.6% | -17.5% | 49.4% | -25.0% |

## How to read Top-5 vs Top-10 vs Top-20

- **Top-5** usually prints the highest gross CAGR and the deepest drawdowns. Weekly Top-5 also pays the most in costs.
- **Top-10** is the typical live compromise: still concentrated, less single-name ruin.
- **Top-20** is closer to the index itself; alpha vs equal-weight universe shrinks, turnover falls.

## How to read weekly vs bi-weekly vs monthly

- **Weekly** fits 21-day ROC (the live dual_mom_w21 analog). Faster rotation, more cost drag.
- **Bi-weekly** cuts turnover roughly in half versus weekly; useful if 2y/1y CAGRs stay close to weekly.
- **Monthly** fits 63d/126d ROC. Lower cost, slower to exit losers — dual (ROC>0 cash) matters more here.

## Caveats

- Current Alpha 50 / Momentum 50 members are used for the whole 6 years (survivorship). 6y numbers are optimistic.
- Last 2y and last 1y are the decision windows; they still use today's members but the bias is smaller.
- No point-in-time float, freeze, or corporate-action audit beyond Yahoo adjusted close.
- Relative-only (always fully invested) is in `grid_results.csv` as a control; the pick above is dual momentum.

