from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from api.db import get_db
from api.lib.responses import envelope

router = APIRouter(prefix="/zones", tags=["zones"])

# Germany bounding box validation applied via Query ge/le constraints on lat/lon.
# KNN operator <-> uses cell_geom_proj (EPSG:25832, metric) — distances are metres.

_NEAREST_SQL = """
    SELECT az.kind,
           az.accident_count,
           az.year_from,
           az.year_to,
           az.region_id,
           r.name AS region_name,
           ST_AsGeoJSON(az.cell_geom)::json AS cell_geom,
           ST_Distance(
               az.cell_geom_proj,
               ST_Transform(ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), 25832)
           ) AS distance_m
    FROM accident_zones az
    LEFT JOIN regions r ON r.ags = az.region_id
    WHERE az.kind = :kind
      {year_filter}
    ORDER BY az.cell_geom_proj
          <-> ST_Transform(ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), 25832)
    LIMIT :limit
"""

_AROUND_SQL = """
    SELECT az.kind,
           az.accident_count,
           az.year_from,
           az.year_to,
           az.region_id,
           r.name AS region_name,
           ST_AsGeoJSON(az.cell_geom)::json AS cell_geom,
           ST_Distance(
               az.cell_geom_proj,
               ST_Transform(ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), 25832)
           ) AS distance_m
    FROM accident_zones az
    LEFT JOIN regions r ON r.ags = az.region_id
    {year_filter}
    ORDER BY az.cell_geom_proj
          <-> ST_Transform(ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), 25832)
    LIMIT 50
"""

_YOUR_ZONE_SQL = text("""
    SELECT az.kind,
           az.accident_count,
           az.year_from,
           az.year_to,
           az.region_id,
           r.name AS region_name,
           ST_AsGeoJSON(az.cell_geom)::json AS cell_geom
    FROM accident_zones az
    LEFT JOIN regions r ON r.ags = az.region_id
    WHERE ST_Contains(
        az.cell_geom_proj,
        ST_Transform(ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), 25832)
    )
    LIMIT 1
""")


def _row_to_dict(r) -> dict:
    return {
        "kind": r[0],
        "accident_count": r[1],
        "year_from": r[2],
        "year_to": r[3],
        "region_id": r[4],
        "region_name": r[5],
        "cell_geom": r[6],
        "distance_m": round(float(r[7]), 1),
    }


@router.get("/nearest")
def nearest_zones(
    lat: float = Query(..., ge=47.27, le=55.06),
    lon: float = Query(..., ge=5.87, le=15.04),
    type: str = Query("hotspot", pattern="^(hotspot|safe)$"),
    year: int | None = None,
    limit: int = Query(5, ge=1, le=50),
    db: Session = Depends(get_db),
):
    params: dict = {"lat": lat, "lon": lon, "kind": type, "limit": limit}
    year_filter = ""
    if year is not None:
        year_filter = "AND az.year_from <= :year AND az.year_to >= :year"
        params["year"] = year

    rows = db.execute(
        text(_NEAREST_SQL.format(year_filter=year_filter)), params
    ).fetchall()

    return envelope(
        [_row_to_dict(r) for r in rows],
        sources_used=["unfallatlas"],
        extra_meta={"type": type, "lat": lat, "lon": lon},
    )


@router.get("/around")
def zones_around(
    lat: float = Query(..., ge=47.27, le=55.06),
    lon: float = Query(..., ge=5.87, le=15.04),
    year: int | None = None,
    db: Session = Depends(get_db),
):
    params: dict = {"lat": lat, "lon": lon}
    year_filter = ""
    if year is not None:
        year_filter = "WHERE az.year_from <= :year AND az.year_to >= :year"
        params["year"] = year

    rows = db.execute(
        text(_AROUND_SQL.format(year_filter=year_filter)), params
    ).fetchall()

    hotspots = [_row_to_dict(r) for r in rows if r[0] == "hotspot"]
    safe_zones = [_row_to_dict(r) for r in rows if r[0] == "safe"]

    your_zone_row = db.execute(_YOUR_ZONE_SQL, {"lat": lat, "lon": lon}).fetchone()
    your_zone = None
    if your_zone_row:
        your_zone = {
            "kind": your_zone_row[0],
            "accident_count": your_zone_row[1],
            "year_from": your_zone_row[2],
            "year_to": your_zone_row[3],
            "region_id": your_zone_row[4],
            "region_name": your_zone_row[5],
            "cell_geom": your_zone_row[6],
        }

    return envelope(
        {"hotspots": hotspots, "safe_zones": safe_zones, "your_zone": your_zone},
        sources_used=["unfallatlas"],
        extra_meta={"lat": lat, "lon": lon},
    )
