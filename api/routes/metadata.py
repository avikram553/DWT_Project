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
    # TODO Phase 10: run automated plausibility checks
    return {"status": "not_run", "checks": []}
