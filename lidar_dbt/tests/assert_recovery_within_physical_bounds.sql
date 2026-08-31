-- Detection cannot plausibly recover more stems than the inventory records,
-- nor a negligible fraction of them.
--
-- Above 100% means the detector is finding things that are not trees - the
-- sparse-CHM noise failure mode. Below 2% means the pipeline is broken rather
-- than merely limited. Observed range on real data is 12-18%.
--
-- Returns rows on failure.

select
    standid,
    development_class,
    round(100 * stem_recovery_ratio, 1) as recovery_pct,
    inv_stems_per_ha,
    det_stems_per_ha
from {{ ref('int_stands_comparable') }}
where is_comparable
  and (stem_recovery_ratio > 1.0 or stem_recovery_ratio < 0.02)
