{{ config(materialized='table') }}

-- Where the standing volume actually sits.
--
-- inv_volume_m3_ha is per hectare, so total volume must be weighted by stand
-- area. Summing it directly would over-weight small stands.

with stands as (

    select * from {{ ref('int_stands_comparable') }}
    where inv_volume_m3_ha is not null
      and not excl_stale_inventory
      and not excl_unusable_class

)

select
    coalesce(development_class, 'unclassified')             as development_class,
    count(*)                                                as n_stands,
    round(sum(area_ha), 1)                                  as total_ha,
    round(avg(inv_volume_m3_ha), 0)                         as m3_per_ha,
    round(sum(inv_volume_m3_ha * area_ha), 0)               as total_m3,
    round(100.0 * sum(inv_volume_m3_ha * area_ha)
          / sum(sum(inv_volume_m3_ha * area_ha)) over (), 1) as pct_of_total,
    round(avg(inv_basal_area_m2_ha), 1)                     as basal_area_m2_ha

from stands
group by 1
having count(*) >= 5
order by total_m3 desc
