-- Stem recovery must increase from young thinning (02) through advanced
-- thinning (03) to regeneration-mature (04).
--
-- The physical reason is that mature stands have fewer, larger, better-
-- separated crowns, which local-maximum detection can actually resolve. If
-- this ordering breaks, the detector is picking up something other than trees
-- - which is exactly what happened on sparse synthetic data, where noise in a
-- mostly-empty CHM manufactured spurious maxima and RAISED apparent recall.
--
-- Returns rows on failure.

with c as (
    select development_class, recovery_pct
    from {{ ref('fct_detection_by_class') }}
    where development_class in ('02', '03', '04')
),
p as (
    select
        max(case when development_class = '02' then recovery_pct end) as young,
        max(case when development_class = '03' then recovery_pct end) as advanced,
        max(case when development_class = '04' then recovery_pct end) as mature
    from c
)

select 'recovery is not monotonic with maturity' as failure, young, advanced, mature
from p
where young is not null and advanced is not null and mature is not null
  and not (young <= advanced and advanced <= mature)
