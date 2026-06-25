from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from api.db import get_db
from api.lib.geo import STATE_CODE as _STATE_CODE
from api.lib.responses import envelope

router = APIRouter(prefix="/accidents", tags=["accidents"])

_PARTICIPANT_COL = {
    "pedestrian": "participant_pedestrian",
    "bike": "participant_bike",
    "car": "participant_car",
    "moped": "participant_moped",
    "truck": "participant_truck",
    "other": "participant_other",
}


@router.get("")
def list_accidents(
    state: str | None = None,
    year: int | None = None,
    category: int | None = None,
    participant: str | None = None,
    lat_min: float | None = Query(None, ge=-90, le=90),
    lat_max: float | None = Query(None, ge=-90, le=90),
    lon_min: float | None = Query(None, ge=-180, le=180),
    lon_max: float | None = Query(None, ge=-180, le=180),
    limit: int | None = Query(None, ge=1),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """
    List accidents with optional filters.
    Q5: state=BE&year=2023&participant=pedestrian → pedestrian accidents in Berlin 2023.
    bbox: lat_min, lat_max, lon_min, lon_max → spatial filter to map viewport.
    limit: omit or set to 0 to return all matching rows (no cap).
    """
    conditions = []
    params: dict = {"offset": offset}

    if state:
        state_prefix = _STATE_CODE.get(state.upper())
        if state_prefix is None:
            raise HTTPException(status_code=422, detail=f"Unknown state code '{state}'. Valid: {', '.join(_STATE_CODE)}")
        conditions.append("LEFT(region_id, 2) = :state_prefix")
        params["state_prefix"] = state_prefix

    if year is not None:
        conditions.append("year = :year")
        params["year"] = year

    if category is not None:
        conditions.append("category = :category")
        params["category"] = category

    if participant:
        col = _PARTICIPANT_COL.get(participant.lower())
        if col:
            assert col in _PARTICIPANT_COL.values(), f"unsafe column name: {col}"
            conditions.append(f"{col} = TRUE")

    # Viewport bounding box filter
    if lat_min is not None:
        conditions.append("lat >= :lat_min")
        params["lat_min"] = lat_min
    if lat_max is not None:
        conditions.append("lat <= :lat_max")
        params["lat_max"] = lat_max
    if lon_min is not None:
        conditions.append("lon >= :lon_min")
        params["lon_min"] = lon_min
    if lon_max is not None:
        conditions.append("lon <= :lon_max")
        params["lon_max"] = lon_max

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    # Build LIMIT/OFFSET clause — omit LIMIT when not requested
    if limit is not None:
        params["limit"] = limit
        limit_clause = "LIMIT :limit OFFSET :offset"
    else:
        limit_clause = "OFFSET :offset"

    rows = db.execute(
        text(
            f"""
            SELECT accident_uid, year, month, hour, day_of_week,
                   category, kind, type, light, road_condition,
                   participant_car, participant_bike, participant_moped,
                   participant_truck, participant_pedestrian, participant_other,
                   lat, lon, region_id
            FROM accidents
            {where}
            ORDER BY year, id
            {limit_clause}
            """
        ),
        params,
    ).fetchall()

    results = [
        {
            "accident_uid": r[0],
            "year": r[1],
            "month": r[2],
            "hour": r[3],
            "day_of_week": r[4],
            "category": r[5],
            "kind": r[6],
            "type": r[7],
            "light": r[8],
            "road_condition": r[9],
            "participant_car": r[10],
            "participant_bike": r[11],
            "participant_moped": r[12],
            "participant_truck": r[13],
            "participant_pedestrian": r[14],
            "participant_other": r[15],
            "lat": r[16],
            "lon": r[17],
            "region_id": r[18],
        }
        for r in rows
    ]

    return envelope(
        results,
        sources_used=["unfallatlas"],
        extra_meta={"total_count": len(results), "offset": offset},
    )
