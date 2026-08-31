{{ config(materialized='table') }}

-- Detection performance by silvicultural development class.
--
-- The expected pattern is monotonic: recovery rises with maturity, because
-- mature stands have fewer, larger, better-separated crowns. A canopy height
-- model resolves the overstory only.

with comparable as (

    select * from {{ ref('int_stands_comparable') }}
    where is_comparable

)

select
    coalesce(development_class, 'unclassified')            as development_class,
    case coalesce(development_class, 'x')
        when '02' then 'young thinning stand'
        when '03' then 'advanced thinning stand'
        when '04' then 'regeneration-mature'
        when 'T2' then 'advanced seedling'
        when 'Y1' then 'seedling under overstory'
        else           'unclassified / other'
    end                                                    as class_label,

    count(*)                                               as n_stands,
    round(sum(area_ha), 1)                                 as total_ha,

    round(avg(inv_stems_per_ha), 0)                        as inv_stems_per_ha,
    round(avg(det_stems_per_ha), 0)                        as det_stems_per_ha,
    round(100 * median(stem_recovery_ratio), 1)            as recovery_pct,

    round(avg(inv_mean_height_m), 2)                       as inv_height_m,
    round(avg(det_mean_height_m), 2)                       as det_height_m,
    round(avg(det_height_bias_m), 2)                       as det_height_bias_m,
    round(corr(det_mean_height_m, inv_mean_height_m), 3)   as height_corr

from comparable
group by 1, 2
having count(*) >= 5           -- a one-stand class is noise presented as a statistic
order by 1
