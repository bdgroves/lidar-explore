{{ config(materialized='view') }}

-- The comparable set: stands where detection and inventory can honestly be
-- compared against each other. Every exclusion is named and counted so the
-- sample size behind any published number is traceable.
--
-- This model exists because the same statistic was once reported on two
-- different subsets (n=1,295 and n=1,706) in the same repository. Defining
-- the population once, in one place, prevents that.

with stands as (

    select * from {{ ref('stg_stands') }}

),

flagged as (

    select
        *,
        -- Reasons a stand cannot support a detection-vs-inventory comparison.
        geom is null                                       as excl_bad_geometry,
        development_class in ('A0', 'T1')                  as excl_unusable_class,
        coalesce(inv_age_years, 999)
            > {{ var('max_obs_gap_years') }}               as excl_stale_inventory,
        area_ha < {{ var('min_stand_ha') }}                as excl_too_small,
        coalesce(inv_stems_per_ha, 0) <= 0                 as excl_no_inventory

    from stands

)

select
    *,
    not (excl_bad_geometry
         or excl_unusable_class
         or excl_stale_inventory
         or excl_too_small
         or excl_no_inventory)                             as is_comparable,

    -- Headline ratios, defined once so every mart agrees on them.
    det_stems_per_ha / nullif(inv_stems_per_ha, 0)         as stem_recovery_ratio,
    det_mean_height_m - inv_mean_height_m                  as det_height_bias_m,
    chm_pixel_mean_height_m - inv_mean_height_m            as pixel_height_bias_m

from flagged
