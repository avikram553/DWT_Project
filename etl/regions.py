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

LEVEL_FILES = [
    ("VG250_LAN", "state"),
    ("VG250_KRS", "district"),
    ("VG250_GEM", "municipality"),
]

_TRANSFORMER = Transformer.from_crs("EPSG:25832", "EPSG:4326", always_xy=True)


def reproject_coords(x: float, y: float) -> tuple[float, float]:
    lon, lat = _TRANSFORMER.transform(x, y)
    return lon, lat


def _reproject_geom(geom):
    return transform(_TRANSFORMER.transform, geom)


def extract_ags(props: dict[str, Any], level: str) -> str:
    rs: str = str(props.get("RS") or props.get("RS_0") or "")
    if level == "state":
        return rs[:2]
    if level == "district":
        return rs[:5]
    return rs[:8]


def parent_ags_for(ags: str, level: str) -> str | None:
    if level == "state":
        return None
    if level == "district":
        return ags[:2]
    return ags[:5]


def _load_level(
    zf: zipfile.ZipFile,
    file_substr: str,
    level: str,
    db: Session,
    run_id: int,
) -> tuple[int, int]:
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

        raw_geom = from_geojson(json.dumps(feat["geometry"]))
        geom_4326 = _reproject_geom(raw_geom)
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
