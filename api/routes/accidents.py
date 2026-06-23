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
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """
    List accidents with optional filters.
    Q5: state=BE&year=2023&participant=pedestrian → pedestrian accidents in Berlin 2023.
    """
    conditions = []
    params: dict = {"limit": limit, "offset": offset}

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

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

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
            LIMIT :limit OFFSET :offset
            """
        ),
        params,
    ).fetchall()

    count_row = db.execute(
        text(f"SELECT COUNT(*) FROM accidents {where}"),
        {k: v for k, v in params.items() if k not in ("limit", "offset")},
    ).scalar()

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
        extra_meta={"total_count": count_row, "limit": limit, "offset": offset},
    )
