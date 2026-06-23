from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
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
    stmt = select(Region)
    if level:
        stmt = stmt.where(Region.level == level)
    stmt = stmt.order_by(Region.ags)
    regions = db.execute(stmt).scalars().all()
    return envelope(
        [_region_to_dict(r) for r in regions],
        sources_used=["regionalatlas"],
    )


@router.get("/{ags}")
def get_region(ags: str, db: Session = Depends(get_db)):
    region = db.execute(
        select(Region).where(Region.ags == ags)
    ).scalar_one_or_none()
    if region is None:
        raise HTTPException(status_code=404, detail=f"Region '{ags}' not found")
    return envelope(_region_to_dict(region), sources_used=["regionalatlas"])
