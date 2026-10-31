-- #48's raw query (research/PREREGISTRATION_EXEC_ANSWER.md). `python research/substrate_reprice.py holdout`
-- fills {legs}, {weeks} and {size} and stops if this query's theta differs from the Python point estimate.
--
-- theta = drag / (bench - gross + drag), the share of the holdout's realised shortfall against BTC
-- that execution accounts for, at {size} dollars a leg. cost_bps is Binance's 5 bps taker fee + the half-spread
-- paid + the frozen impact fit. An unpriced leg takes the mean of the priced legs, counted in `unpriced`.
WITH weeks AS (
    SELECT gross, bench FROM read_csv_auto('{weeks}')
), span AS (
    SELECT COUNT(*) / (365.25 / 7) AS years, SUM(gross) AS g, SUM(bench) AS b FROM weeks
), legs AS (
    SELECT TRY_CAST(cost_bps AS DOUBLE) AS cost
    FROM read_csv_auto('{legs}', all_varchar = true)
    WHERE TRY_CAST(size AS DOUBLE) = {size}
), filled AS (
    SELECT COALESCE(cost, (SELECT AVG(cost) FROM legs)) AS cost, cost IS NULL AS unpriced FROM legs
), cost AS (
    SELECT SUM(-LN(1 - cost / 10000.0)) AS total, COUNT(*) AS n, SUM(unpriced::INT) AS unpriced FROM filled
)
SELECT span.years,
       span.g / span.years AS gross_ann,
       span.b / span.years AS bench_ann,
       cost.total / span.years AS drag_ann,
       (span.b - span.g + cost.total) / span.years AS shortfall_ann,
       CASE WHEN span.g >= span.b THEN 1.0
            ELSE (cost.total / span.years) / ((span.b - span.g + cost.total) / span.years) END AS theta,
       cost.n AS legs,
       cost.unpriced
FROM span, cost;
