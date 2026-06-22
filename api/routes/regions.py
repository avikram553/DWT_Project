from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from api.db import get_db
from api.lib.responses import envelope

router = APIRouter(prefix="/regions", tags=["regions"])


@router.get("")
def list_regions(
    level: str | None = Query(None, pattern="^(state|district|municipality)$"),
    db: Session = Depends(get_db),
):
    # TODO Phase 2: implement region listing
    return envelope([], sources_used=["regionalatlas"])


@router.get("/{ags}")
def get_region(ags: str, db: Session = Depends(get_db)):
    # TODO Phase 2: implement region detail
    return envelope(None, sources_used=["regionalatlas"])
