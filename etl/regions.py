"""Phase 2 ETL: load German administrative regions from BKG VG250-EW Shapefile."""
from __future__ import annotations

import io
import zipfile
from typing import Any

import shapefile  # pyshp
from pyproj import Transformer
from shapely.geometry import shape as shapely_shape, MultiPolygon
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
    "aktuell/vg250-ew_12-31.utm32s.shape.ebenen.zip"
)
VG250_ZIP = RAW_DATA_DIR / "vg250-ew.shape.zip"

# Subdirectory inside the zip where shapefiles live
_ZIP_SUBDIR = "vg250-ew_12-31.utm32s.shape.ebenen/vg250-ew_ebenen_1231"

LEVEL_FILES = [
    ("VG250_LAN", "state"),
    ("VG250_KRS", "district"),
    ("VG250_GEM", "municipality"),
]

_TRANSFORMER = Transformer.from_crs("EPSG:25832", "EPSG:4326", always_xy=True)


def reproject_coords(x: float, y: float) -> tuple[float, float]:
    """Transform point from EPSG:25832 to EPSG:4326. Returns (lon, lat)."""
    lon, lat = _TRANSFORMER.transform(x, y)
    return lon, lat


def _reproject_geom(geom):
    return transform(_TRANSFORMER.transform, geom)


def extract_ags(props: dict[str, Any], level: str) -> str:
    # Prefer AGS field (already at correct length in Shapefile).
    # Fall back to ARS[:N] for GeoJSON source which uses RS/RS_0.
    ags_direct: str = str(props.get("AGS") or props.get("AGS_0") or "").strip()
    rs: str = str(props.get("ARS") or props.get("RS") or props.get("ARS_0") or props.get("RS_0") or "").strip()
    if level == "state":
        return (ags_direct or rs)[:2]
    if level == "district":
        if ags_direct and len(ags_direct) >= 5:
            return ags_direct[:5]
        return rs[:5]
    # municipality: AGS is exactly 8 chars in Shapefile
    if ags_direct and len(ags_direct) >= 8:
        return ags_direct[:8]
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
    # Read .shp, .dbf, .shx from the zip
    prefix = f"{_ZIP_SUBDIR}/{file_substr}"
    shp_data = io.BytesIO(zf.read(prefix + ".shp"))
    dbf_data = io.BytesIO(zf.read(prefix + ".dbf"))
    shx_data = io.BytesIO(zf.read(prefix + ".shx"))

    sf = shapefile.Reader(shp=shp_data, dbf=dbf_data, shx=shx_data)
    fields = [f[0] for f in sf.fields[1:]]  # skip deletion flag

    inserted = updated = 0
    for shape_rec in sf.iterShapeRecords():
        props = dict(zip(fields, shape_rec.record))

        # Skip non-land areas (GF=4 is the actual land polygon)
        # For states only — districts and municipalities don't have this issue
        gf = props.get("GF")
        if level == "state" and gf != 4:
            continue

        ags = extract_ags(props, level)
        if not ags or len(ags) < 2:
            continue

        if shape_rec.shape.shapeType == 0:
            continue

        name: str = props.get("GEN") or props.get("BEZ") or ""
        if not name:
            continue

        population: int | None = props.get("EWZ")
        parent = parent_ags_for(ags, level)

        # Convert shapefile geometry to shapely, then reproject
        raw_geom = shapely_shape(shape_rec.shape.__geo_interface__)
        geom_4326 = _reproject_geom(raw_geom)
        if geom_4326.geom_type == "Polygon":
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
        # Remove cached zip if it may be corrupt so next run re-downloads
        if VG250_ZIP.exists() and VG250_ZIP.stat().st_size == 0:
            VG250_ZIP.unlink()
        finish_import_run(
            db, run_id,
            status="failed",
            rows_inserted=total_ins,
            rows_updated=total_upd,
            file_hash=file_hash,
            error_message=str(exc),
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
