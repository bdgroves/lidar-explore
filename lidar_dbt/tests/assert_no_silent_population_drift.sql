-- The comparable population must stay within a sane band.
--
-- If a filter change quietly halves the sample, every published statistic
-- moves and nothing errors. This is the guard against the n=1,295 versus
-- n=1,706 discrepancy that once put two different medians for the same
-- measurement into the same repository.
--
-- Returns rows on failure.

with counts as (
    select
        count(*)                                as total_stands,
        sum(iff(is_comparable, 1, 0))           as comparable_stands
    from {{ ref('int_stands_comparable') }}
)

select
    'comparable population outside expected band' as failure,
    total_stands,
    comparable_stands,
    round(100.0 * comparable_stands / nullif(total_stands, 0), 1) as pct
from counts
where comparable_stands < 800 or comparable_stands > 1700
