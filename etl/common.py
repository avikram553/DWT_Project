"""Shared ETL utilities: download, hash, import_run tracking."""
import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

RAW_DATA_DIR = Path(__file__).parent.parent / "rawData"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def download_file(url: str, dest: Path) -> Path:
    """Download url to dest. Skips download if dest already exists."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        print(f"[skip] {dest.name} already downloaded")
        return dest
    print(f"[download] {url} → {dest.name}")
    with httpx.stream("GET", url, follow_redirects=True, timeout=120) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_bytes(chunk_size=65536):
                f.write(chunk)
    print(f"[done] {dest.stat().st_size // 1024} KB")
    return dest


def start_import_run(db: Session, source_name: str, file_url: str) -> int:
    """Insert an import_run row for source_name, return the new run id."""
    source_id = db.execute(
        text("SELECT id FROM sources WHERE name = :name"),
        {"name": source_name},
    ).scalar_one()
    result = db.execute(
        text(
            "INSERT INTO import_runs (source_id, started_at, status, file_url) "
            "VALUES (:sid, :ts, 'running', :url) RETURNING id"
        ),
        {"sid": source_id, "ts": datetime.now(timezone.utc), "url": file_url},
    )
    run_id = result.scalar_one()
    db.commit()
    return run_id


def finish_import_run(
    db: Session,
    run_id: int,
    *,
    status: str,
    rows_inserted: int,
    rows_updated: int,
    file_hash: str | None = None,
) -> None:
    db.execute(
        text(
            "UPDATE import_runs SET finished_at=:ts, status=:status, "
            "rows_inserted=:ins, rows_updated=:upd, file_hash_sha256=:hash "
            "WHERE id=:id"
        ),
        {
            "ts": datetime.now(timezone.utc),
            "status": status,
            "ins": rows_inserted,
            "upd": rows_updated,
            "hash": file_hash,
            "id": run_id,
        },
    )
    db.commit()
