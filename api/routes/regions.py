from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from api.db import get_db
from api.lib.responses import envelope
from api.models import Region

router = APIRouter(prefix="/regions", tags=["regions"])


def _region_to_dict(r: Region) -> dict:
    return {
        "ags": r.ags,
        "name": r.name,
        "level": r.level.value if hasattr(r.level, "value") else r.level,
        "parent_ags": r.parent_ags,
        "population_latest": r.population_latest,
    }


@router.get("")
def list_regions(
    level: str | None = Query(None, pattern="^(state|district|municipality)$"),
    db: Session = Depends(get_db),
):
    # Use raw SQL to include ST_AsGeoJSON(geom) which ORM mapped_column can't serialize
    conditions = []
    params: dict = {}
    if level:
        conditions.append("level = :level")
        params["level"] = level
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    rows = db.execute(
        text(
            f"""
            SELECT ags, name, level, parent_ags, population_latest,
                   ST_AsGeoJSON(geom)::json AS geom
            FROM regions
            {where}
            ORDER BY ags
            """
        ),
        params,
    ).fetchall()
    results = [
        {
            "ags": r[0],
            "name": r[1],
            "level": r[2],
            "parent_ags": r[3],
            "population_latest": r[4],
            "geom": r[5],
        }
        for r in rows
    ]
    return envelope(results, sources_used=["regionalatlas"])


@router.get("/{ags}/indicators")
def get_region_indicators(ags: str = Path(..., examples=["11000"]), db: Session = Depends(get_db)):
    """Return all indicator time-series for a region."""
    region = db.execute(select(Region).where(Region.ags == ags)).scalar_one_or_none()
    if region is None:
        raise HTTPException(status_code=404, detail=f"Region '{ags}' not found")

    rows = db.execute(
        text(
            """
            SELECT i.name, i.unit, iv.year, iv.value
            FROM indicator_values iv
            JOIN indicators i ON i.id = iv.indicator_id
            WHERE iv.region_id = :ags
            ORDER BY i.name, iv.year
            """
        ),
        {"ags": ags},
    ).fetchall()

    by_indicator: dict[str, list] = {}
    for ind_name, unit, year, value in rows:
        if ind_name not in by_indicator:
            by_indicator[ind_name] = {"name": ind_name, "unit": unit, "values": []}
        by_indicator[ind_name]["values"].append({"year": year, "value": value})

    return envelope(
        list(by_indicator.values()),
        sources_used=["regionalstatistik"],
        extra_meta={"region": _region_to_dict(region)},
    )


@router.get("/{ags}")
def get_region(ags: str = Path(..., examples=["11000"]), db: Session = Depends(get_db)):
    region = db.execute(
        select(Region).where(Region.ags == ags)
    ).scalar_one_or_none()
    if region is None:
        raise HTTPException(status_code=404, detail=f"Region '{ags}' not found")
    return envelope(_region_to_dict(region), sources_used=["regionalatlas"])
