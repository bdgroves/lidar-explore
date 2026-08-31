{{ config(materialized='table') }}

-- The estimator decides the sign.
--
-- Two defensible definitions of "mean canopy height" from the same raster land
-- on opposite sides of the inventory value:
--   * mean over DETECTED STEMS  - crown apexes, sits ABOVE a stem-weighted mean
--   * mean over ALL CHM PIXELS  - includes canopy gaps, sits BELOW it
-- Roughly one pixel in ten is a gap, which is where the negative bias comes from.

with comparable as (

    select * from {{ ref('int_stands_comparable') }}
    where is_comparable and inv_mean_height_m is not null

)

select
    'detected stems'                                        as estimator,
    count(*)                                                as n_stands,
    round(avg(det_mean_height_m), 2)                        as mean_height_m,
    round(avg(inv_mean_height_m), 2)                        as inventory_mean_m,
    round(avg(det_height_bias_m), 2)                        as bias_m,
    round(sqrt(avg(power(det_height_bias_m, 2))), 2)        as rmse_m,
    round(corr(det_mean_height_m, inv_mean_height_m), 3)    as correlation
from comparable

union all

select
    'all chm pixels',
    count(*),
    round(avg(chm_pixel_mean_height_m), 2),
    round(avg(inv_mean_height_m), 2),
    round(avg(pixel_height_bias_m), 2),
    round(sqrt(avg(power(pixel_height_bias_m, 2))), 2),
    round(corr(chm_pixel_mean_height_m, inv_mean_height_m), 3)
from comparable
