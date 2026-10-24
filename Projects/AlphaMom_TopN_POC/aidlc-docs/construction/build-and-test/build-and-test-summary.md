# Build and Test

## Unit tests
```
python test_backtest_core.py
```
Expected: `ok` (rebalance mask, lagged ROC, dual-mom skip of negative ROC, window metrics).

## Grid backtest
```
python run_topn_grid.py
```
Writes `output/grid_results.csv`, `output/recommendation.md`, `output/summary.json`, `output/equity_picks.csv`.
Needs network only for Yahoo symbols not already in `data_cache_1d/`.

## Run log (2026-08-29)
- Unit tests: pass
- Grid: 162 rows (3 universes x 3 lookbacks x 3 K x 3 freqs x 2 filters)
- 2y and 1y pick: `alpha50|lb21|top5|2W|dual`
- 6y pick: `combined|lb63|top5|2W|dual`
