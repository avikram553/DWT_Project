from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from api.db import get_db
from api.lib.responses import envelope

router = APIRouter(prefix="/accidents", tags=["accidents"])


@router.get("")
def list_accidents(
    state: str | None = None,
    year: int | None = None,
    category: int | None = None,
    participant: str | None = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = 0,
    db: Session = Depends(get_db),
):
    # TODO Phase 3: implement accident listing
    return envelope([], sources_used=["unfallatlas"])
