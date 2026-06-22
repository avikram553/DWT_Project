from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from api.db import get_db
from api.lib.responses import envelope

router = APIRouter(prefix="/aggregates", tags=["aggregates"])


@router.get("/accidents")
def aggregate_accidents(
    level: str | None = Query(None, pattern="^(state|district|municipality)$"),
    state: str | None = None,
    year: int | None = None,
    category: int | None = None,
    aggregate: str | None = None,
    db: Session = Depends(get_db),
):
    # TODO Phase 5: implement aggregation
    return envelope([], sources_used=["unfallatlas"])


@router.get("/accident-rate")
def accident_rate(
    level: str = Query("district", pattern="^(state|district|municipality)$"),
    year: int | None = None,
    denominator: str = Query("population", pattern="^(population|cars_pkw)$"),
    db: Session = Depends(get_db),
):
    # TODO Phase 5: implement rate calculation
    return envelope([], sources_used=["unfallatlas", "regionalstatistik"])


@router.get("/accident-rate/top")
def accident_rate_top(
    level: str = Query("district", pattern="^(state|district)$"),
    year: int | None = None,
    severity: str | None = None,
    denominator: str = Query("population", pattern="^(population|cars_pkw)$"),
    limit: int = Query(5, le=50),
    min_population: int = 50000,
    db: Session = Depends(get_db),
):
    # TODO Phase 5: implement top-N ranking (Q7)
    return envelope(
        [],
        sources_used=["unfallatlas", "regionalstatistik"],
        extra_meta={
            "min_population_filter": min_population,
            "population_year_used": None,
            "requested_year": year,
        },
    )
