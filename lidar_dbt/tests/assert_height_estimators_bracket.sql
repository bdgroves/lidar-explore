-- The two height estimators must fall on OPPOSITE sides of the inventory value.
--
-- Detected stems are crown apexes and must sit above a stem-weighted mean;
-- the whole-pixel mean includes canopy gaps and must sit below it. If both
-- land on the same side, either the detection changed or a column got crossed
-- somewhere in the pipeline.
--
-- This is not hypothetical: a QGIS table join once returned values shifted two
-- columns, so det_stems_ha was silently serving chm_mean_h. It rendered a
-- perfectly plausible map.
--
-- Returns rows on failure.

with e as (select * from {{ ref('fct_height_estimators') }})

select
    'estimators do not bracket the inventory' as failure,
    max(case when estimator = 'detected stems' then bias_m end)  as detected_bias,
    max(case when estimator = 'all chm pixels' then bias_m end)  as pixel_bias
from e
having not (
       max(case when estimator = 'detected stems' then bias_m end) > 0
   and max(case when estimator = 'all chm pixels' then bias_m end) < 0
)
