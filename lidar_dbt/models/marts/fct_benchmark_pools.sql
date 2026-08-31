{{ config(materialized='table') }}

-- Benchmark base rates, by candidate pool.
--
-- This model exists to make a specific mistake impossible to repeat. Scoring
-- harvest predictions against the foresters' cutting plan once reported 1.37x
-- lift, computed against ALL stands rather than the pool actually chosen from.
-- That credits the ranking for exclusions the development class had already
-- made.
--
-- Reporting every pool side by side makes the saturation visible: by the time
-- stands are filtered to eligible, essentially all are already proposed for
-- cutting, so precision near 100% is close to unavoidable and the maximum
-- achievable lift is roughly 1.0x.

with stands as (

    select * from {{ ref('int_stands_comparable') }}

),

pools as (

    select 1 as pool_order,
           'all stands >= ' || {{ var('min_stand_ha') }} || ' ha'  as pool,
           count(*)                                                as n_stands,
           sum(iff(cutting_proposed, 1, 0))                        as n_proposed
    from stands
    where area_ha >= {{ var('min_stand_ha') }}

    union all

    select 2,
           'development class ' || '{{ var("mature_class") }}',
           count(*), sum(iff(cutting_proposed, 1, 0))
    from stands
    where development_class = '{{ var("mature_class") }}'

    union all

    select 3,
           'eligible after all gates',
           count(*), sum(iff(cutting_proposed, 1, 0))
    from stands
    where harvest_eligible

)

select
    pool,
    n_stands,
    n_proposed,
    round(100.0 * n_proposed / nullif(n_stands, 0), 1)      as base_rate_pct,

    -- The ceiling on lift, given this base rate. When it approaches 1.00 the
    -- benchmark cannot demonstrate skill no matter how good the model is.
    round(1.0 / nullif(1.0 * n_proposed / nullif(n_stands, 0), 0), 3)
                                                            as max_possible_lift,
    case
        when 1.0 * n_proposed / nullif(n_stands, 0) > 0.95
            then 'SATURATED - benchmark cannot show skill'
        when 1.0 * n_proposed / nullif(n_stands, 0) > 0.85
            then 'near-saturated - interpret lift cautiously'
        else 'usable as a benchmark'
    end                                                     as verdict

from pools
order by pool_order
