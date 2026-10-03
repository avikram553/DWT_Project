from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session
from api.db import get_db, check_db_connection
from api.lib.responses import envelope

router = APIRouter(tags=["metadata"])


@router.get("/metadata/sources")
def list_sources(db: Session = Depends(get_db)):
    rows = db.execute(
        text("SELECT id, name, url, license, description, last_checked FROM sources ORDER BY id")
    ).mappings().all()
    rows_dicts = [dict(r) for r in rows]
    return envelope(rows_dicts, sources_used=[r["name"] for r in rows_dicts])


@router.get("/import-runs")
def list_import_runs(db: Session = Depends(get_db)):
    rows = db.execute(
        text(
            "SELECT id, source_id, started_at, finished_at, status,"
            " rows_inserted, rows_updated, rows_skipped, source_timestamp"
            " FROM import_runs ORDER BY started_at DESC LIMIT 100"
        )
    ).mappings().all()
    return envelope([dict(r) for r in rows])


@router.get("/healthz")
def healthz():
    db_ok = check_db_connection()
    return {"status": "ok" if db_ok else "degraded", "db": "ok" if db_ok else "error"}


@router.get("/healthz/data-quality")
def data_quality(db: Session = Depends(get_db)):
    checks = []

    def add_count_check(name: str, sql: str, minimum: int = 1):
        count = db.execute(text(sql)).scalar() or 0
        checks.append({
            "name": name,
            "status": "ok" if count >= minimum else "error",
            "count": count,
            "minimum": minimum,
        })

    add_count_check("accidents populated", "SELECT COUNT(*) FROM accidents")
    add_count_check("regions populated", "SELECT COUNT(*) FROM regions")
    add_count_check("indicators populated", "SELECT COUNT(*) FROM indicators")
    add_count_check("indicator_values populated", "SELECT COUNT(*) FROM indicator_values")
    add_count_check("accident_zones populated", "SELECT COUNT(*) FROM accident_zones")

    indicator_years = db.execute(
        text(
            """
            SELECT i.name, MIN(iv.year) AS min_year, MAX(iv.year) AS max_year,
                   COUNT(*) AS rows, COUNT(DISTINCT iv.region_id) AS regions
            FROM indicator_values iv
            JOIN indicators i ON i.id = iv.indicator_id
            WHERE i.name IN ('population', 'cars_pkw')
            GROUP BY i.name
            ORDER BY i.name
            """
        )
    ).mappings().all()

    checks.append({
        "name": "regionalstatistik coverage",
        "status": "ok" if len(indicator_years) == 2 else "error",
        "indicators": [dict(row) for row in indicator_years],
    })

    status = "ok" if all(check["status"] == "ok" for check in checks) else "degraded"
    return {"status": status, "checks": checks}
