{{ config(materialized='view') }}

-- Typed, renamed passthrough. No filtering happens here on purpose: every
-- exclusion downstream is an explicit, named decision rather than something
-- quietly applied at the edge of the warehouse.

with source as (

    select * from {{ source('nuuksio', 'stands') }}

),

renamed as (

    select
        standid,
        nullif(devclass, 'NA')                          as development_class,
        species                                          as main_species_code,
        poly_ha                                          as area_ha,
        area_m2_proj,

        -- inventory (Forest Centre, field/ALS derived)
        meanheight                                       as inv_mean_height_m,
        stemcount                                        as inv_stems_per_ha,
        basalarea                                        as inv_basal_area_m2_ha,
        volume                                           as inv_volume_m3_ha,

        -- detection (our CHM local maxima)
        det_stems_ha                                     as det_stems_per_ha,
        det_mean_h                                       as det_mean_height_m,
        chm_mean_h                                       as chm_pixel_mean_height_m,
        canopy_frac                                      as canopy_fraction,

        -- provenance and status
        obs_gap                                          as inv_age_years,
        usable_inv                                       as inv_usable,
        eligible                                         as harvest_eligible,
        op_cut                                           as cutting_proposed,
        restricted                                       as legally_restricted,
        geom

    from source

)

select * from renamed
