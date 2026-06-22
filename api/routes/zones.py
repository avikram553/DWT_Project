from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from api.db import get_db
from api.lib.responses import envelope

router = APIRouter(prefix="/zones", tags=["zones"])


@router.get("/nearest")
def nearest_zones(
    lat: float = Query(..., ge=47.27, le=55.06),
    lon: float = Query(..., ge=5.87, le=15.04),
    type: str = Query("hotspot", pattern="^(hotspot|safe)$"),
    year: int | None = None,
    limit: int = Query(5, ge=1, le=50),
    db: Session = Depends(get_db),
):
    # TODO Phase 6: KNN query on accident_zones.cell_geom_proj (EPSG:25832)
    return envelope([], sources_used=["unfallatlas"])


@router.get("/around")
def zones_around(
    lat: float = Query(..., ge=47.27, le=55.06),
    lon: float = Query(..., ge=5.87, le=15.04),
    year: int | None = None,
    db: Session = Depends(get_db),
):
    # TODO Phase 6: return hotspots + safe + your_zone in one call
    return envelope(
        {"hotspots": [], "safe_zones": [], "your_zone": None},
        sources_used=["unfallatlas"],
    )
