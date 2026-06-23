"""
Phase 5: Aggregation API — answers all 7 mandatory examiner questions.

Q1  GET /aggregates/accidents?aggregate=earliest_year
Q2  GET /aggregates/accidents?state=SN&year=2023&category=2
Q3  GET /aggregates/accidents?state=NW&aggregate=earliest_year
Q4  GET /aggregates/accidents?state=MV&aggregate=earliest_year
Q5  GET /accidents?state=BE&year=2023&participant=pedestrian  (in accidents.py)
Q6  GET /aggregates/accident-rate?denominator=cars_pkw&year=2023&level=district
Q7  GET /aggregates/accident-rate/top?level=district&year=2024&severity=fatal
            &denominator=population&limit=5&min_population=50000
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from api.db import get_db
from api.lib.geo import STATE_CODE as _STATE_CODE
from api.lib.responses import envelope

router = APIRouter(prefix="/aggregates", tags=["aggregates"])


def _state_prefix(state: str | None) -> str | None:
    if state is None:
        return None
    prefix = _STATE_CODE.get(state.upper())
    if prefix is None:
        raise HTTPException(status_code=422, detail=f"Unknown state code '{state}'. Valid: {', '.join(_STATE_CODE)}")
    return prefix


# ─── /aggregates/accidents ────────────────────────────────────────────────────

@router.get("/accidents")
def aggregate_accidents(
    level: str | None = Query(None, pattern="^(state|district|municipality)$"),
    state: str | None = None,
    year: int | None = None,
    category: int | None = None,
    aggregate: str | None = Query(None, pattern="^(earliest_year|count)$"),
    db: Session = Depends(get_db),
):
    """
    Aggregate accident statistics.

    - aggregate=earliest_year → returns MIN(year) [Q1, Q3, Q4]
    - aggregate=count or omitted → returns COUNT(*) grouped by region+year [Q2]
    """
    state_prefix = _state_prefix(state)
    conditions: list[str] = []
    params: dict = {}

    if state_prefix:
        conditions.append("LEFT(a.region_id, 2) = :state_prefix")
        params["state_prefix"] = state_prefix

    if year is not None:
        conditions.append("a.year = :year")
        params["year"] = year

    if category is not None:
        conditions.append("a.category = :category")
        params["category"] = category

    if level:
        conditions.append("r.level = :level")
        params["level"] = level

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    join = "JOIN regions r ON a.region_id = r.ags" if level else ""

    if aggregate == "earliest_year":
        row = db.execute(
            text(f"SELECT MIN(a.year) FROM accidents a {join} {where}"),
            params,
        ).fetchone()
        earliest = row[0] if row else None
        return envelope(
            {"earliest_year": earliest},
            sources_used=["unfallatlas"],
            extra_meta={"state": state, "aggregate": "earliest_year"},
        )

    # Default: count aggregation, grouped by region and year
    if not level:
        join = ""

    rows = db.execute(
        text(
            f"""
            SELECT a.region_id{', r.name AS region_name' if level else ''}, a.year,
                   COUNT(*) AS accident_count
            FROM accidents a
            {join}
            {where}
            GROUP BY a.region_id{', r.name' if level else ''}, a.year
            ORDER BY a.year, a.region_id
            """
        ),
        params,
    ).fetchall()

    if level:
        results = [
            {"region_id": r[0], "region_name": r[1], "year": r[2], "accident_count": r[3]}
            for r in rows
        ]
    else:
        results = [
            {"region_id": r[0], "year": r[1], "accident_count": r[2]}
            for r in rows
        ]

    total = sum(r[-1] for r in rows) if rows else 0
    return envelope(
        results,
        sources_used=["unfallatlas"],
        extra_meta={
            "total_count": total,
            "state": state,
            "year": year,
            "category": category,
        },
    )


# ─── /aggregates/accident-rate ───────────────────────────────────────────────

@router.get("/accident-rate")
def accident_rate(
    level: str = Query("district", pattern="^(state|district|municipality)$"),
    year: int | None = None,
    denominator: str = Query("population", pattern="^(population|cars_pkw)$"),
    state: str | None = None,
    db: Session = Depends(get_db),
):
    """
    Accident rate per 100k population or per 100k registered cars by region.
    Q6: denominator=cars_pkw
    Uses MAX(indicator year) ≤ requested year as population fallback.
    """
    state_prefix = _state_prefix(state)

    params: dict = {"level": level, "ind_name": denominator}
    state_clause = ""
    if state_prefix:
        state_clause = "AND LEFT(r.ags, 2) = :state_prefix"
        params["state_prefix"] = state_prefix

    year_clause = ""
    if year is not None:
        year_clause = "AND a.year = :acc_year"
        params["acc_year"] = year
        params["max_year"] = year
    else:
        params["max_year"] = 9999  # no upper bound

    rows = db.execute(
        text(
            f"""
            WITH ind_id AS (
                SELECT id FROM indicators WHERE name = :ind_name
            ),
            pop_latest AS (
                SELECT DISTINCT ON (iv.region_id)
                       iv.region_id,
                       iv.year AS indicator_year,
                       iv.value
                FROM indicator_values iv
                JOIN ind_id ON iv.indicator_id = ind_id.id
                WHERE iv.year <= :max_year
                ORDER BY iv.region_id, iv.year DESC
            ),
            acc_counts AS (
                SELECT a.region_id, COUNT(*) AS cnt
                FROM accidents a
                {year_clause}
                GROUP BY a.region_id
            )
            SELECT r.ags, r.name, r.level,
                   COALESCE(ac.cnt, 0) AS accident_count,
                   pl.value AS denominator_value,
                   pl.indicator_year,
                   CASE WHEN pl.value > 0
                        THEN ROUND(COALESCE(ac.cnt, 0) * 100000.0 / pl.value, 2)
                        ELSE NULL
                   END AS rate_per_100k
            FROM regions r
            JOIN pop_latest pl ON pl.region_id = r.ags
            LEFT JOIN acc_counts ac ON ac.region_id = r.ags
            WHERE r.level = :level
              {state_clause}
            ORDER BY rate_per_100k DESC NULLS LAST
            """
        ),
        params,
    ).fetchall()

    # Find the population year used (most common across results)
    pop_years = [r[5] for r in rows if r[5] is not None]
    pop_year_used = max(set(pop_years), key=pop_years.count) if pop_years else None

    results = [
        {
            "ags": r[0],
            "name": r[1],
            "level": r[2],
            "accident_count": r[3],
            "denominator_value": r[4],
            "rate_per_100k": float(r[6]) if r[6] is not None else None,
        }
        for r in rows
    ]

    return envelope(
        results,
        sources_used=["unfallatlas", "regionalstatistik"],
        extra_meta={
            "denominator": denominator,
            "requested_year": year,
            "population_year_used": pop_year_used,
        },
    )


# ─── /aggregates/accident-rate/top ───────────────────────────────────────────

@router.get("/accident-rate/top")
def accident_rate_top(
    level: str = Query("district", pattern="^(state|district)$"),
    year: int | None = None,
    severity: str | None = Query(None, pattern="^(fatal|serious|light)$"),
    denominator: str = Query("population", pattern="^(population|cars_pkw)$"),
    limit: int = Query(5, ge=1, le=50),
    min_population: int = Query(50_000, ge=0),
    db: Session = Depends(get_db),
):
    """
    Top-N regions by accident rate per 100k.
    Q7: level=district&year=2024&severity=fatal&denominator=population&limit=5&min_population=50000
    Uses MIN(population_year) ≤ requested_year fallback; filters ≥ min_population.
    """
    severity_map = {"fatal": 1, "serious": 2, "light": 3}
    category_filter = ""
    params: dict = {
        "level": level,
        "ind_name": denominator,
        "limit": limit,
        "min_pop": min_population,
    }

    if severity and severity in severity_map:
        category_filter = "AND a.category = :category"
        params["category"] = severity_map[severity]

    year_filter = ""
    if year is not None:
        year_filter = "AND a.year = :acc_year"
        params["acc_year"] = year
        params["max_ind_year"] = year
    else:
        params["max_ind_year"] = 9999

    rows = db.execute(
        text(
            f"""
            WITH ind_id AS (
                SELECT id FROM indicators WHERE name = :ind_name
            ),
            pop_latest AS (
                SELECT DISTINCT ON (iv.region_id)
                       iv.region_id,
                       iv.year AS pop_year,
                       iv.value AS population
                FROM indicator_values iv
                JOIN ind_id ON iv.indicator_id = ind_id.id
                WHERE iv.year <= :max_ind_year
                ORDER BY iv.region_id, iv.year DESC
            ),
            fatal_counts AS (
                SELECT a.region_id, COUNT(*) AS cnt
                FROM accidents a
                WHERE 1=1
                  {year_filter}
                  {category_filter}
                GROUP BY a.region_id
            )
            SELECT
                r.ags,
                r.name,
                COALESCE(fc.cnt, 0)    AS accident_count,
                pl.population,
                pl.pop_year,
                CASE WHEN pl.population > 0
                     THEN ROUND(COALESCE(fc.cnt, 0) * 100000.0 / pl.population, 4)
                     ELSE NULL
                END AS rate_per_100k
            FROM regions r
            JOIN pop_latest pl ON pl.region_id = r.ags
            LEFT JOIN fatal_counts fc ON fc.region_id = r.ags
            WHERE r.level = :level
              AND pl.population >= :min_pop
            ORDER BY rate_per_100k DESC NULLS LAST
            LIMIT :limit
            """
        ),
        params,
    ).fetchall()

    pop_years = [r[4] for r in rows if r[4] is not None]
    pop_year_used = max(set(pop_years), key=pop_years.count) if pop_years else None

    results = [
        {
            "rank": i + 1,
            "ags": r[0],
            "name": r[1],
            "accident_count": r[2],
            "population": r[3],
            "rate_per_100k": float(r[5]) if r[5] is not None else None,
        }
        for i, r in enumerate(rows)
    ]

    return envelope(
        results,
        sources_used=["unfallatlas", "regionalstatistik"],
        extra_meta={
            "denominator": denominator,
            "severity": severity,
            "requested_year": year,
            "population_year_used": pop_year_used,
            "min_population_filter": min_population,
        },
    )
