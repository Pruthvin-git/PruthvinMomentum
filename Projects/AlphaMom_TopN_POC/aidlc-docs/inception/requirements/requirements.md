# Requirements

## Intent Analysis
- **User request**: Separate-directory proof of concept. Historical backtest on Nifty Alpha 50 and Nifty Midcap 150 Momentum 50. Compare Top-5 vs Top-10 vs Top-20, rebalanced weekly vs bi-weekly vs monthly. Report which combination produced superior returns over the last 6 years, with emphasis on the last 2 years and last 1 year.
- **Request type**: New Project (research backtest)
- **Scope estimate**: Single Python package/script plus cached daily prices
- **Complexity estimate**: Simple
- **Requirements depth**: Minimal (grid is specified; ranking method delegated to the strategy we can actually run)

## Assumptions (immediate implementation)
| Topic | Choice |
|---|---|
| Ranking | Dual momentum: N-day ROC, long only names with ROC > 0, then Top-K by ROC (same rule as Hourly_mom `dual_mom_w21_k5`) |
| Lookbacks tested | 21 (live analog), 63 (quarter), 126 (six-month) |
| Relative-only control | Same Top-K without the ROC>0 cash filter |
| Universes | Alpha 50, Momentum Midcap 50, and the unique union |
| Weights | Equal weight among selected names; leftover is cash |
| Execution | Rank with T-1 close (no same-bar lookahead); new weights earn day-T return |
| Costs | 0.10% per side of traded notional |
| Constituents | Current index members (survivorship bias — disclosed) |
| Benchmarks | Equal-weight buy-and-hold of each universe; Nifty 50 (`^NSEI`) |
| Security Baseline | No (local research POC, no auth/datastore) |
| Property-Based Testing | No (deterministic grid; one synthetic unit test) |

## Functional Requirements
- **FR1**: Load Alpha 50 and Momentum Midcap 50 symbol lists from CSV.
- **FR2**: Download or reuse cached adjusted daily closes for ~6.5 years.
- **FR3**: Run the full grid of universe x lookback x Top-N x frequency x dual/relative.
- **FR4**: Report total return, CAGR, max drawdown, Sharpe, turnover, and cash time for 6y / 2y / 1y windows.
- **FR5**: Rank combinations for the 2y and 1y windows and write a pick recommendation.

## Non-Functional Requirements
- **NFR1**: No broker keys or secrets.
- **NFR2**: Prices cached locally so re-runs do not re-download.
- **NFR3**: Lookahead-safe ranking (score lagged one session).

## Out of scope
- Live trading, mailers, Pine Script
- Point-in-time historical index membership
- Intraday execution, shorts, leverage
- Tax-lot / STT exact modelling beyond the 10 bps per-side cost

## Extension Configuration
| Extension | Enabled | Rationale |
|---|---|---|
| Security Baseline | No | Local analysis scripts only |
| Property-Based Testing | No | Deterministic ranking covered by a synthetic unit test |
