# Phase 2 — Regions ETL Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Download German administrative boundaries from BKG VG250 open data, load ~12 k regions (16 states, ~400 districts, ~11 k municipalities) into the `regions` table, and expose them through the `/regions` API endpoints.

**Architecture:** `etl/regions.py` downloads the BKG VG250 GeoJSON zip via httpx, reprojects from EPSG:25832 → EPSG:4326 using pyproj+shapely, then bulk-upserts into `regions` via raw psycopg COPY (wrapped by `etl/common.py` import-run tracking). The FastAPI routes in `api/routes/regions.py` replace their stubs with SQLAlchemy queries.

**Tech Stack:** Python 3.11, psycopg 3, SQLAlchemy 2, httpx, shapely 2, pyproj, FastAPI

## Global Constraints

- `ags` is always `TEXT` — never cast to integer (leading-zero bug: "01001" ≠ 1001)
- Geometry stored as `GEOMETRY(MULTIPOLYGON, 4326)` — all input must be reprojected if not already WGS84
- UPSERT key is `ags` (PK) — re-running ETL must produce identical row counts (idempotent)
- Every import run recorded in `import_runs` table; every `regions` row carries `import_run_id`
- License: dl-de/by-2-0 — `sources` row name is `'regionalatlas'` (seeded in Phase 1)
- DB: `postgresql+psycopg://postgres:postgres@localhost:5432/dwt` (local) or via `DATABASE_URL` env var
- Docker: `docker compose up -d` must be running before any ETL or API test

---

## Data Source

**BKG VG250-EW** (Verwaltungsgebiete 1:250 000 mit Einwohnerzahlen)
- License: dl-de/by-2-0
- Download URL: `https://daten.gdz.bkg.bund.de/produkte/vg/vg250-ew_ebenen_1231/aktuell/vg250-ew_12-31.utm32s.geojson.zip`
- Contents (after unzip):
  - `VG250_LAN.geojson` → 16 states (`level = 'state'`)
  - `VG250_KRS.geojson` → ~400 districts (`level = 'district'`)
  - `VG250_GEM.geojson` → ~11 000 municipalities (`level = 'municipality'`)
- CRS: EPSG:25832 (UTM Zone 32N / ETRS89) → must reproject to EPSG:4326
- Key GeoJSON properties per feature:
  - `RS` — zero-padded Regionalschlüssel string (12 chars); AGS extracted as: state=`rs[:2]`, district=`rs[:5]`, municipality=`rs[:8]`
  - `GEN` — region name (Gebietsname), e.g. `"Schleswig-Holstein"`, `"Flensburg"`, `"Flensburg"`
  - `EWZ` — Einwohnerzahl (population count, integer) — load into `population_latest`

**Fallback:** If the BKG URL changes, the canonical replacement is always at `https://gdz.bkg.bund.de/` under Products → VG250. The filename pattern is `vg250-ew_<date>.utm32s.geojson.zip`.

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `pyproject.toml` | Modify | Add `pyproj>=3.6` dependency |
| `etl/common.py` | Modify | Add `download_file()`, `start_import_run()`, `finish_import_run()` |
| `etl/regions.py` | Create | Full regions ETL: download → parse → reproject → upsert |
| `api/routes/regions.py` | Modify | Replace stubs with real DB queries |
| `tests/test_etl_regions.py` | Create | Unit tests for AGS extraction and geometry parsing |
| `tests/test_api_endpoints.py` | Modify | Add regions endpoint tests |

---

## Task 1: Add pyproj dependency and extend common.py

**Files:**
- Modify: `pyproject.toml`
- Modify: `etl/common.py`

**Interfaces:**
- Produces:
  - `download_file(url: str, dest: Path) -> Path` — downloads to dest, returns path
  - `start_import_run(db: Session, source_name: str, file_url: str) -> int` — inserts import_run row, returns run id
  - `finish_import_run(db: Session, run_id: int, *, status: str, rows_inserted: int, rows_updated: int, file_hash: str | None) -> None`

- [ ] **Step 1: Add pyproj to pyproject.toml**

Edit `pyproject.toml`, add `"pyproj>=3.6"` to the `dependencies` list:

```toml
dependencies = [
    "fastapi>=0.111",
    "uvicorn[standard]>=0.29",
    "sqlalchemy>=2.0",
    "geoalchemy2>=0.14",
    "psycopg[binary]>=3.1",
    "pandas>=2.2",
    "httpx>=0.27",
    "python-dotenv>=1.0",
    "shapely>=2.0",
    "pyproj>=3.6",
]
```

- [ ] **Step 2: Install the new dependency**

```bash
cd /Users/adityavikram/Desktop/DevRepo/DWT_Project
.venv/bin/pip install "pyproj>=3.6"
```

Expected output: `Successfully installed pyproj-<version>`

- [ ] **Step 3: Write tests for common.py helpers**

Create `tests/test_etl_common.py`:

```python
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch


def test_sha256_file(tmp_path):
    from etl.common import sha256_file
    f = tmp_path / "test.txt"
    f.write_bytes(b"hello")
    result = sha256_file(f)
    assert len(result) == 64
    assert result == sha256_file(f)  # deterministic


def test_start_import_run():
    from etl.common import start_import_run
    db = MagicMock()
    # Should query sources by name, insert import_run, return id
    mock_source = MagicMock()
    mock_source.id = 1
    db.execute.return_value.scalar_one.return_value = mock_source.id

    run_id = start_import_run(db, "regionalatlas", "http://example.com/file.zip")
    db.execute.assert_called()
    db.commit.assert_called()
    assert isinstance(run_id, int)


def test_finish_import_run():
    from etl.common import finish_import_run
    db = MagicMock()
    finish_import_run(db, 42, status="success", rows_inserted=100, rows_updated=5, file_hash="abc123")
    db.execute.assert_called()
    db.commit.assert_called()
```

- [ ] **Step 4: Run tests to confirm they fail (common helpers not yet implemented)**

```bash
cd /Users/adityavikram/Desktop/DevRepo/DWT_Project
.venv/bin/python -m pytest tests/test_etl_common.py -v 2>&1 | head -40
```

Expected: `FAILED` with `ImportError` or `AttributeError` — confirms tests are wired correctly.

- [ ] **Step 5: Implement common.py helpers**

Replace `etl/common.py` with:

```python
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
```

- [ ] **Step 6: Run tests — expect pass**

```bash
cd /Users/adityavikram/Desktop/DevRepo/DWT_Project
.venv/bin/python -m pytest tests/test_etl_common.py -v
```

Expected: `3 passed`

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml etl/common.py tests/test_etl_common.py
git commit -m "feat(etl): add download, import_run tracking helpers to common.py"
```

---

## Task 2: Implement etl/regions.py

**Files:**
- Create: `etl/regions.py`
- Create: `tests/test_etl_regions.py`

**Interfaces:**
- Consumes: `download_file`, `start_import_run`, `finish_import_run` from `etl.common`; `Session` from `api.db`
- Produces: `run_regions_etl(db: Session) -> dict` — returns `{"inserted": int, "updated": int}`

- [ ] **Step 1: Write unit tests for AGS extraction and geometry reprojection**

Create `tests/test_etl_regions.py`:

```python
import json
import pytest


def test_extract_ags_state():
    from etl.regions import extract_ags
    props = {"RS": "010000000000"}
    assert extract_ags(props, "state") == "01"


def test_extract_ags_district():
    from etl.regions import extract_ags
    props = {"RS": "010010000000"}
    assert extract_ags(props, "district") == "01001"


def test_extract_ags_municipality():
    from etl.regions import extract_ags
    props = {"RS": "010010000000"}
    assert extract_ags(props, "municipality") == "01001000"


def test_extract_ags_strips_leading_zeros_preserved():
    from etl.regions import extract_ags
    # Saxony state code must stay "14" not 14
    props = {"RS": "140000000000"}
    result = extract_ags(props, "state")
    assert result == "14"
    assert isinstance(result, str)


def test_reproject_point():
    from etl.regions import reproject_coords
    # Flensburg roughly at UTM32N (537000, 6090000)
    lon, lat = reproject_coords(537000, 6090000)
    # Should be ~54.79°N, 9.43°E
    assert 9.0 < lon < 10.0
    assert 54.5 < lat < 55.1


def test_parent_ags_state():
    from etl.regions import parent_ags_for
    assert parent_ags_for("01", "state") is None


def test_parent_ags_district():
    from etl.regions import parent_ags_for
    assert parent_ags_for("01001", "district") == "01"


def test_parent_ags_municipality():
    from etl.regions import parent_ags_for
    assert parent_ags_for("01001000", "municipality") == "01001"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /Users/adityavikram/Desktop/DevRepo/DWT_Project
.venv/bin/python -m pytest tests/test_etl_regions.py -v 2>&1 | head -30
```

Expected: `FAILED` — `ImportError: cannot import name 'extract_ags' from 'etl.regions'`

- [ ] **Step 3: Create etl/regions.py**

```python
"""Phase 2 ETL: load German administrative regions from BKG VG250-EW GeoJSON."""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Any

from pyproj import Transformer
from shapely import from_geojson, to_wkb
from shapely.ops import transform
from sqlalchemy import text
from sqlalchemy.orm import Session

from etl.common import (
    RAW_DATA_DIR,
    download_file,
    finish_import_run,
    sha256_file,
    start_import_run,
)

VG250_URL = (
    "https://daten.gdz.bkg.bund.de/produkte/vg/vg250-ew_ebenen_1231/"
    "aktuell/vg250-ew_12-31.utm32s.geojson.zip"
)
VG250_ZIP = RAW_DATA_DIR / "vg250-ew.geojson.zip"

# GeoJSON files inside the zip → (filename_substr, level)
LEVEL_FILES = [
    ("VG250_LAN", "state"),
    ("VG250_KRS", "district"),
    ("VG250_GEM", "municipality"),
]

_TRANSFORMER = Transformer.from_crs("EPSG:25832", "EPSG:4326", always_xy=True)


def reproject_coords(x: float, y: float) -> tuple[float, float]:
    """Transform a single point from EPSG:25832 to EPSG:4326 (lon, lat)."""
    lon, lat = _TRANSFORMER.transform(x, y)
    return lon, lat


def _reproject_geom(geom):
    """Reproject a shapely geometry from EPSG:25832 to EPSG:4326."""
    return transform(_TRANSFORMER.transform, geom)


def extract_ags(props: dict[str, Any], level: str) -> str:
    """Extract zero-padded AGS string from VG250 feature properties."""
    rs: str = str(props.get("RS") or props.get("RS_0") or "")
    if level == "state":
        return rs[:2]
    if level == "district":
        return rs[:5]
    return rs[:8]  # municipality


def parent_ags_for(ags: str, level: str) -> str | None:
    if level == "state":
        return None
    if level == "district":
        return ags[:2]
    return ags[:5]  # municipality


def _load_level(
    zf: zipfile.ZipFile,
    file_substr: str,
    level: str,
    db: Session,
    run_id: int,
) -> tuple[int, int]:
    """Parse one GeoJSON layer and upsert into regions. Returns (inserted, updated)."""
    geojson_name = next(
        n for n in zf.namelist() if file_substr in n and n.endswith(".geojson")
    )
    with zf.open(geojson_name) as f:
        fc = json.load(f)

    inserted = updated = 0
    for feat in fc["features"]:
        props = feat["properties"]
        ags = extract_ags(props, level)
        if not ags or len(ags) < 2:
            continue

        name: str = props.get("GEN") or props.get("BEZ") or ""
        population: int | None = props.get("EWZ")
        parent = parent_ags_for(ags, level)

        # Reproject geometry 25832 → 4326
        raw_geom = from_geojson(json.dumps(feat["geometry"]))
        geom_4326 = _reproject_geom(raw_geom)
        # Force MultiPolygon (schema requires MULTIPOLYGON)
        if geom_4326.geom_type == "Polygon":
            from shapely.geometry import MultiPolygon
            geom_4326 = MultiPolygon([geom_4326])
        wkb_hex = geom_4326.wkb_hex

        result = db.execute(
            text(
                """
                INSERT INTO regions (ags, name, level, parent_ags, population_latest, geom, import_run_id)
                VALUES (:ags, :name, :level, :parent, :pop, ST_GeomFromWKB(decode(:geom, 'hex'), 4326), :run_id)
                ON CONFLICT (ags) DO UPDATE SET
                    name              = EXCLUDED.name,
                    level             = EXCLUDED.level,
                    parent_ags        = EXCLUDED.parent_ags,
                    population_latest = EXCLUDED.population_latest,
                    geom              = EXCLUDED.geom,
                    import_run_id     = EXCLUDED.import_run_id
                RETURNING (xmax = 0) AS was_inserted
                """
            ),
            {
                "ags": ags,
                "name": name,
                "level": level,
                "parent": parent,
                "pop": population,
                "geom": wkb_hex,
                "run_id": run_id,
            },
        )
        was_inserted = result.scalar_one()
        if was_inserted:
            inserted += 1
        else:
            updated += 1

    db.commit()
    return inserted, updated


def run_regions_etl(db: Session) -> dict:
    """Full regions ETL. Returns {"inserted": int, "updated": int}."""
    path = download_file(VG250_URL, VG250_ZIP)
    file_hash = sha256_file(path)
    run_id = start_import_run(db, "regionalatlas", VG250_URL)

    total_ins = total_upd = 0
    try:
        with zipfile.ZipFile(path) as zf:
            for file_substr, level in LEVEL_FILES:
                print(f"[regions] Loading {level}s from {file_substr}...")
                ins, upd = _load_level(zf, file_substr, level, db, run_id)
                print(f"[regions]   {ins} inserted, {upd} updated")
                total_ins += ins
                total_upd += upd
    except Exception as exc:
        finish_import_run(
            db, run_id,
            status="failed",
            rows_inserted=total_ins,
            rows_updated=total_upd,
            file_hash=file_hash,
        )
        raise

    finish_import_run(
        db, run_id,
        status="success",
        rows_inserted=total_ins,
        rows_updated=total_upd,
        file_hash=file_hash,
    )
    return {"inserted": total_ins, "updated": total_upd}
```

- [ ] **Step 4: Run unit tests — expect pass**

```bash
cd /Users/adityavikram/Desktop/DevRepo/DWT_Project
.venv/bin/python -m pytest tests/test_etl_regions.py -v
```

Expected: `8 passed`

- [ ] **Step 5: Commit**

```bash
git add etl/regions.py tests/test_etl_regions.py
git commit -m "feat(etl): implement regions ETL from BKG VG250 GeoJSON"
```

---

## Task 3: Implement /regions API endpoints

**Files:**
- Modify: `api/routes/regions.py`

**Interfaces:**
- Consumes: `Region` model from `api.models`, `get_db` from `api.db`, `envelope` from `api.lib.responses`
- Produces:
  - `GET /regions?level=state|district|municipality` → `{"results": [...], "metadata": {...}}`
  - `GET /regions/{ags}` → `{"results": {...}, "metadata": {...}}`
  - Each region object: `{"ags": str, "name": str, "level": str, "parent_ags": str|null, "population_latest": int|null}`

- [ ] **Step 1: Write API endpoint tests**

Add to `tests/test_api_endpoints.py` (create if it doesn't exist):

```python
import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch


@pytest.fixture
def client():
    from api.main import app
    return TestClient(app)


def _make_mock_region(ags="01", name="Schleswig-Holstein", level="state", parent=None):
    r = MagicMock()
    r.ags = ags
    r.name = name
    r.level = level
    r.parent_ags = parent
    r.population_latest = 2910875
    return r


def test_list_regions_returns_envelope(client):
    mock_regions = [_make_mock_region()]
    with patch("api.routes.regions.get_db") as mock_get_db:
        mock_db = MagicMock()
        mock_db.execute.return_value.scalars.return_value.all.return_value = mock_regions
        mock_get_db.return_value = iter([mock_db])
        resp = client.get("/regions?level=state")
    assert resp.status_code == 200
    body = resp.json()
    assert "results" in body
    assert "metadata" in body
    assert "sources_used" in body["metadata"]


def test_get_region_not_found(client):
    with patch("api.routes.regions.get_db") as mock_get_db:
        mock_db = MagicMock()
        mock_db.execute.return_value.scalar_one_or_none.return_value = None
        mock_get_db.return_value = iter([mock_db])
        resp = client.get("/regions/99999")
    assert resp.status_code == 404


def test_list_regions_level_validation(client):
    resp = client.get("/regions?level=invalid")
    assert resp.status_code == 422
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /Users/adityavikram/Desktop/DevRepo/DWT_Project
.venv/bin/python -m pytest tests/test_api_endpoints.py -v 2>&1 | head -30
```

Expected: `FAILED` — endpoints return empty stubs

- [ ] **Step 3: Replace stubs in api/routes/regions.py**

```python
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.db import get_db
from api.lib.responses import envelope
from api.models import Region, RegionLevel

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
```

- [ ] **Step 4: Run tests — expect pass**

```bash
cd /Users/adityavikram/Desktop/DevRepo/DWT_Project
.venv/bin/python -m pytest tests/test_api_endpoints.py -v
```

Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add api/routes/regions.py tests/test_api_endpoints.py
git commit -m "feat(api): implement /regions list and detail endpoints"
```

---

## Task 4: End-to-end smoke test

This task runs the actual ETL against a live Docker DB and verifies the success criterion from the plan: `GET /regions?level=state` returns 16 rows.

**Prerequisites:** Docker running with `docker compose up -d`, DB healthy.

- [ ] **Step 1: Start Docker DB**

```bash
cd /Users/adityavikram/Desktop/DevRepo/DWT_Project
docker compose up -d db
docker compose ps
```

Expected: `db` service `healthy` within 30 s.

- [ ] **Step 2: Verify DB schema exists**

```bash
docker compose exec db psql -U postgres -d dwt -c "\dt"
```

Expected: tables listed including `regions`, `import_runs`, `sources`.

If tables are missing, the schema hasn't been applied yet. Re-create the volume:
```bash
docker compose down -v && docker compose up -d db
```
Wait 15 s for init scripts to run, then re-check.

- [ ] **Step 3: Run the regions ETL**

```bash
cd /Users/adityavikram/Desktop/DevRepo/DWT_Project
DATABASE_URL="postgresql+psycopg://postgres:postgres@localhost:5432/dwt" \
  .venv/bin/python -c "
from api.db import SessionLocal
from etl.regions import run_regions_etl
db = SessionLocal()
result = run_regions_etl(db)
print('Done:', result)
db.close()
"
```

Expected output (approximate):
```
[download] https://daten.gdz.bkg.bund.de/... → vg250-ew.geojson.zip
[done] 28000 KB
[regions] Loading states from VG250_LAN...
[regions]   16 inserted, 0 updated
[regions] Loading districts from VG250_KRS...
[regions]   400 inserted, 0 updated
[regions] Loading municipalities from VG250_GEM...
[regions]   10994 inserted, 0 updated
Done: {'inserted': 11410, 'updated': 0}
```

- [ ] **Step 4: Verify success criterion — 16 states via DB**

```bash
docker compose exec db psql -U postgres -d dwt -c \
  "SELECT COUNT(*) FROM regions WHERE level='state';"
```

Expected: `count = 16`

- [ ] **Step 5: Start the API and verify via HTTP**

```bash
cd /Users/adityavikram/Desktop/DevRepo/DWT_Project
DATABASE_URL="postgresql+psycopg://postgres:postgres@localhost:5432/dwt" \
  .venv/bin/uvicorn api.main:app --reload --port 8000 &
sleep 3
curl -s "http://localhost:8000/regions?level=state" | python3 -c \
  "import sys,json; d=json.load(sys.stdin); print(len(d['results']), 'states')"
```

Expected: `16 states`

Kill the server: `kill %1`

- [ ] **Step 6: Verify idempotency — re-run ETL produces same counts**

```bash
DATABASE_URL="postgresql+psycopg://postgres:postgres@localhost:5432/dwt" \
  .venv/bin/python -c "
from api.db import SessionLocal
from etl.regions import run_regions_etl
db = SessionLocal()
result = run_regions_etl(db)
print('Re-run result:', result)
db.close()
"
```

Expected: `{'inserted': 0, 'updated': 11410}` (all rows updated, none inserted on second run — idempotency confirmed)

- [ ] **Step 7: Verify import_run recorded**

```bash
docker compose exec db psql -U postgres -d dwt -c \
  "SELECT id, status, rows_inserted, rows_updated FROM import_runs ORDER BY id DESC LIMIT 3;"
```

Expected: 2 rows with `status = 'success'`, correct counts.

- [ ] **Step 8: Commit**

```bash
git add -p  # review any changes from smoke test fixes
git commit -m "test: verify Phase 2 regions ETL end-to-end (16 states loaded)"
```

---

## Task 5: Wire regions into etl/update.py orchestrator

**Files:**
- Modify: `etl/update.py`

- [ ] **Step 1: Update orchestrator to call regions ETL**

Replace `etl/update.py` with:

```python
"""
Mandatory ETL orchestrator.

Usage:
    python -m etl.update
    python -m etl.update --source regionalatlas
    python -m etl.update --dry-run
"""
import argparse

from api.db import SessionLocal


def main():
    parser = argparse.ArgumentParser(description="DBW ETL update orchestrator")
    parser.add_argument(
        "--source",
        choices=["unfallatlas", "regionalatlas", "regionalstatistik", "gvisys"],
    )
    parser.add_argument("--year", type=int)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.dry_run:
        print("[dry-run] Would run ETL for:", args.source or "all sources")
        return

    db = SessionLocal()
    try:
        if args.source is None or args.source == "regionalatlas":
            from etl.regions import run_regions_etl
            print("[update] Running regions ETL...")
            result = run_regions_etl(db)
            print(f"[update] Regions done: {result}")

        # Phase 3: unfallatlas ETL goes here
        # Phase 4: regionalstatistik ETL goes here
    finally:
        db.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify orchestrator works**

```bash
cd /Users/adityavikram/Desktop/DevRepo/DWT_Project
DATABASE_URL="postgresql+psycopg://postgres:postgres@localhost:5432/dwt" \
  .venv/bin/python -m etl.update --source regionalatlas
```

Expected: same output as Task 4 Step 3 (skip-download path since file cached in `rawData/`).

- [ ] **Step 3: Commit**

```bash
git add etl/update.py
git commit -m "feat(etl): wire regions ETL into update orchestrator"
```

---

## Verification Checklist

Before calling Phase 2 complete, confirm all of the following:

- [ ] `GET /regions?level=state` returns exactly 16 items
- [ ] `GET /regions?level=district` returns ≥ 400 items
- [ ] `GET /regions/01` returns Schleswig-Holstein (name = "Schleswig-Holstein")
- [ ] `GET /regions/14612` returns city of Chemnitz (or similar Saxony district)
- [ ] `GET /regions/99999` returns HTTP 404
- [ ] `GET /regions?level=invalid` returns HTTP 422
- [ ] All responses contain `metadata.sources_used = ["regionalatlas"]`
- [ ] All responses contain `metadata.licenses = ["dl-de/by-2-0"]`
- [ ] Re-running ETL produces `inserted: 0` (idempotency)
- [ ] `import_runs` table has 2 rows with `status = 'success'`
- [ ] `python -m etl.update --dry-run` prints a message and exits without touching DB
- [ ] All unit tests pass: `pytest tests/ -v`
