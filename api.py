"""
lidar-explore API — serves stand-level LiDAR detection results validated
against the Finnish Forest Centre's national inventory.

Real data, not a demo fixture: 1,840 stands on Sheet L4132D, joined against
observed inventory records from data/stand_validation.csv (see
stand_validate.py). See README.md for the full validation write-up and
methodology.

Run:
    pixi run uvicorn api:app --reload

Docs (Swagger UI): http://127.0.0.1:8000/docs
"""

from pathlib import Path
from typing import Optional

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

DATA_PATH = Path(__file__).parent / "data" / "stand_validation.csv"

app = FastAPI(
    title="lidar-explore API",
    description=(
        "Stand-level LiDAR detection results for Sheet L4132D, Finland, "
        "validated against the Finnish Forest Centre national forest "
        "inventory. Backed by real inventory data (CC BY 4.0), not a "
        "synthetic fixture."
    ),
    version="0.1.0",
)

_df: Optional[pd.DataFrame] = None


def get_data() -> pd.DataFrame:
    global _df
    if _df is None:
        if not DATA_PATH.exists():
            raise HTTPException(
                status_code=503,
                detail=f"Stand data not found at {DATA_PATH}. Run stand_validate.py first.",
            )
        df = pd.read_csv(DATA_PATH)
        df["h_err_detected"] = df["det_mean_h"] - df["meanheight"]
        _df = df
    return _df


class Stand(BaseModel):
    standid: int
    poly_ha: Optional[float] = None
    developmentclass: Optional[str] = None
    maintreespecies: Optional[float] = None
    meanage: Optional[float] = None
    meanheight: Optional[float] = None
    stemcount: Optional[float] = None
    basalarea: Optional[float] = None
    volume: Optional[float] = None
    det_stems: Optional[int] = None
    det_stems_ha: Optional[float] = None
    det_mean_h: Optional[float] = None
    chm_mean_h: Optional[float] = None
    canopy_frac: Optional[float] = None
    coverage_pct: Optional[float] = None
    restricted: Optional[int] = None
    op_cut: Optional[int] = None
    obs_year: Optional[float] = None
    obs_gap: Optional[float] = None
    fresh_inv: Optional[bool] = None
    usable_inv: Optional[bool] = None
    eligible: Optional[bool] = None
    h_err_detected: Optional[float] = None

    class Config:
        extra = "ignore"


class SummaryStats(BaseModel):
    population: str
    stand_count: int
    median_stem_recovery_pct: float
    detected_height_bias_mean_m: float
    detected_height_correlation: float
    whole_pixel_height_bias_mean_m: float
    note: str


@app.get("/", tags=["meta"])
def root():
    return {
        "service": "lidar-explore API",
        "docs": "/docs",
        "endpoints": ["/stands", "/stands/{standid}", "/summary"],
        "source": "github.com/bdgroves/lidar-explore",
        "data_attribution": "Suomen metsakeskus / Finnish Forest Centre, CC BY 4.0",
    }


@app.get("/stands", response_model=list[Stand], tags=["stands"])
def list_stands(
    developmentclass: Optional[str] = Query(None, description="Filter by development class, e.g. '04'"),
    eligible: Optional[bool] = Query(None, description="Filter by cutting eligibility"),
    min_ha: Optional[float] = Query(None, description="Minimum stand area in hectares"),
    limit: int = Query(50, le=500, description="Max rows to return"),
    offset: int = Query(0, ge=0),
):
    df = get_data()

    if developmentclass is not None:
        df = df[df["developmentclass"] == developmentclass]
    if eligible is not None:
        df = df[df["eligible"] == eligible]
    if min_ha is not None:
        df = df[df["poly_ha"] >= min_ha]

    df = df.iloc[offset : offset + limit]
    return df.where(pd.notnull(df), None).to_dict(orient="records")


@app.get("/stands/{standid}", response_model=Stand, tags=["stands"])
def get_stand(standid: int):
    df = get_data()
    row = df[df["standid"] == standid]
    if row.empty:
        raise HTTPException(status_code=404, detail=f"Stand {standid} not found")
    return row.where(pd.notnull(row), None).iloc[0].to_dict()


@app.get("/summary", response_model=SummaryStats, tags=["stats"])
def summary():
    """
    Validation stats computed live from the stand-level CSV, restricted to
    usable, unrestricted stands with valid height comparisons. This is a
    slightly broader population than the hand-curated 1,295-stand set in
    README.md (which also filters to specific development classes) — see
    README.md for the canonical, fully-documented write-up. Numbers here
    will be close but not always identical.
    """
    df = get_data()
    pop = df[(df["usable_inv"] == True) & (df["restricted"] == 0)]
    pop = pop.dropna(subset=["meanheight", "det_mean_h"])

    recovery = (pop["det_stems_ha"] / (pop["stemcount"] / pop["poly_ha"])) * 100
    recovery = recovery.replace([float("inf"), float("-inf")], None).dropna()

    det_bias = pop["det_mean_h"] - pop["meanheight"]
    pixel_bias = pop["chm_mean_h"] - pop["meanheight"]
    correlation = pop[["det_mean_h", "meanheight"]].corr().iloc[0, 1]

    return {
        "population": "usable_inv & unrestricted & valid height pair",
        "stand_count": int(len(pop)),
        "median_stem_recovery_pct": round(float(recovery.median()), 1),
        "detected_height_bias_mean_m": round(float(det_bias.mean()), 2),
        "detected_height_correlation": round(float(correlation), 3),
        "whole_pixel_height_bias_mean_m": round(float(pixel_bias.mean()), 2),
        "note": "See README.md for the canonical 1,295-stand validated write-up.",
    }
