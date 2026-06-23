"""
Phase 3 ETL: load Unfallatlas accident data (2016-2024) into accidents table.

Handles per-year column variations, surrogate SHA-1 UIDs for 2016/2018/2019,
comma-decimal coordinates, and UTF-8 BOM encoding for 2021/2023/2024 files.
Bulk-loads via batched INSERT ON CONFLICT DO NOTHING (idempotent).
"""
from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from etl.common import (
    RAW_DATA_DIR,
    finish_import_run,
    start_import_run,
)
from etl.mappers.unfallatlas_columns import detect_encoding, normalize_columns

ACCIDENT_DIR = RAW_DATA_DIR / "Accidents"
BATCH_SIZE = 10_000

_INSERT_SQL = text(
    """
    INSERT INTO accidents (
        accident_uid, year, month, hour, day_of_week, category, kind, type,
        light, road_condition,
        participant_car, participant_bike, participant_moped,
        participant_truck, participant_pedestrian, participant_other,
        lat, lon, geom, region_id, import_run_id
    ) VALUES (
        :accident_uid, :year, :month, :hour, :day_of_week, :category, :kind, :type,
        :light, :road_condition,
        :participant_car, :participant_bike, :participant_moped,
        :participant_truck, :participant_pedestrian, :participant_other,
        :lat, :lon,
        CASE WHEN :lon IS NOT NULL AND :lat IS NOT NULL
             THEN ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)
             ELSE NULL END,
        :region_id, :run_id
    )
    ON CONFLICT (accident_uid) DO NOTHING
    """
)


def _build_ags_map(db: Session) -> dict[str, str]:
    """Return {raw_district_ags: canonical_ags} from regions + history tables.

    Includes structural prefix rules for city-state sub-district codes:
      02xxx (Hamburg Stadtteile) → 02000
      11xxx (Berlin Bezirke)     → 11000
    These rules cover all present and future sub-codes without enumeration.
    """
    rows = db.execute(
        text("SELECT ags FROM regions WHERE level = 'district'")
    ).fetchall()
    canonical: dict[str, str] = {r[0]: r[0] for r in rows}
    history = db.execute(
        text("SELECT old_ags, new_ags FROM regions_history")
    ).fetchall()
    for old, new in history:
        if old not in canonical:
            canonical[old] = new

    # Prefix rules for city-state sub-district codes used in Unfallatlas
    _PREFIX_RULES: dict[str, str] = {"02": "02000", "11": "11000"}
    for prefix, target in _PREFIX_RULES.items():
        if target in canonical:
            # Pre-populate all 5-digit codes with this prefix not already mapped
            for i in range(1000):
                code = f"{prefix}{i:03d}"
                if code not in canonical:
                    canonical[code] = target

    return canonical


def _get_csv_name(zf: zipfile.ZipFile) -> str:
    candidates = [n for n in zf.namelist() if n.endswith((".txt", ".csv"))]
    if not candidates:
        raise ValueError(f"No CSV found in {zf.filename}")
    return candidates[0]


def _read_year_csv(zip_path: Path) -> pd.DataFrame:
    """Open zip, detect encoding, normalise column names, return DataFrame."""
    with zipfile.ZipFile(zip_path) as zf:
        csv_name = _get_csv_name(zf)
        with zf.open(csv_name) as f:
            encoding = detect_encoding(f.read(3))
        with zf.open(csv_name) as f:
            df = pd.read_csv(f, encoding=encoding, sep=";", dtype=str, low_memory=False)

    renames = normalize_columns(list(df.columns))
    if renames:
        df = df.rename(columns=renames)
    return df


def _coord_series(series: pd.Series) -> pd.Series:
    """Parse coordinate column (comma decimal → float), returns float64 Series."""
    return (
        series.str.strip()
        .str.replace(",", ".", regex=False)
        .pipe(pd.to_numeric, errors="coerce")
    )


def _flag_series(df: pd.DataFrame, col: str) -> pd.Series:
    """Return boolean Series for participation flag column; None if column absent."""
    if col in df.columns:
        numeric = pd.to_numeric(df[col].str.strip(), errors="coerce")
        return numeric.eq(1).where(numeric.notna())
    return pd.Series([None] * len(df), index=df.index, dtype=object)


def _int_col(df: pd.DataFrame, col: str) -> pd.Series:
    """Return nullable integer Series for column, NaN → None."""
    if col not in df.columns:
        return pd.Series([None] * len(df), index=df.index, dtype=object)
    return pd.to_numeric(df[col].str.strip(), errors="coerce").where(
        pd.notna(df[col].str.strip()), other=None
    )


def _transform(
    df: pd.DataFrame, year: int, ags_map: dict[str, str], run_id: int
) -> tuple[list[dict], int]:
    """
    Vectorised transformation of raw DataFrame into INSERT-ready row dicts.
    Returns (rows, unresolved_count).
    """
    # --- UID ---
    if "UIDENTSTLAE" in df.columns:
        uid = df["UIDENTSTLAE"].str.strip()
    else:
        objectid = df.get("OBJECTID", pd.Series([""] * len(df), index=df.index)).fillna("")
        keys = (
            str(year) + "|"
            + objectid + "|"
            + df["ULAND"].fillna("") + "|"
            + df["UREGBEZ"].fillna("") + "|"
            + df["UKREIS"].fillna("") + "|"
            + df["UGEMEINDE"].fillna("") + "|"
            + df["XGCSWGS84"].fillna("") + "|"
            + df["YGCSWGS84"].fillna("")
        )
        uid = pd.Series(
            ["sha1:" + hashlib.sha1(k.encode()).hexdigest() for k in keys],
            index=df.index,
        )

    # --- District AGS → region_id ---
    district_ags = (
        df["ULAND"].str.strip().str.zfill(2)
        + df["UREGBEZ"].str.strip().str.zfill(1)
        + df["UKREIS"].str.strip().str.zfill(2)
    )
    region_id = district_ags.map(ags_map)  # NaN where not found
    unresolved = int(region_id.isna().sum())

    # --- Coordinates ---
    lon = _coord_series(df["XGCSWGS84"])
    lat = _coord_series(df["YGCSWGS84"])

    # --- Typed columns ---
    road_cond = _int_col(df, "STRZUSTAND")

    out = pd.DataFrame(
        {
            "accident_uid": uid,
            "year": pd.to_numeric(df["UJAHR"].str.strip(), errors="coerce"),
            "month": pd.to_numeric(df["UMONAT"].str.strip(), errors="coerce"),
            "hour": pd.to_numeric(df["USTUNDE"].str.strip(), errors="coerce"),
            "day_of_week": pd.to_numeric(df["UWOCHENTAG"].str.strip(), errors="coerce"),
            "category": pd.to_numeric(df["UKATEGORIE"].str.strip(), errors="coerce"),
            "kind": pd.to_numeric(df["UART"].str.strip(), errors="coerce"),
            "type": pd.to_numeric(df["UTYP1"].str.strip(), errors="coerce"),
            "light": pd.to_numeric(df["ULICHTVERH"].str.strip(), errors="coerce")
            if "ULICHTVERH" in df.columns
            else None,
            "road_condition": road_cond,
            "participant_car": _flag_series(df, "IstPKW"),
            "participant_bike": _flag_series(df, "IstRad"),
            "participant_moped": _flag_series(df, "IstKrad"),
            "participant_truck": _flag_series(df, "IstGkfz"),
            "participant_pedestrian": _flag_series(df, "IstFuss"),
            "participant_other": _flag_series(df, "IstSonstige"),
            "lat": lat,
            "lon": lon,
            "region_id": region_id,
            "run_id": run_id,
        }
    )

    def _py(val):
        """Convert numpy scalar to Python native (None for NaN/NaT)."""
        if val is None:
            return None
        if isinstance(val, float) and np.isnan(val):
            return None
        if hasattr(val, "item"):
            return val.item()
        return val

    rows = [
        {k: _py(v) for k, v in row.items()}
        for row in out.to_dict("records")
    ]
    return rows, unresolved


def _insert_batch(db: Session, batch: list[dict]) -> int:
    """Execute batched INSERT ON CONFLICT DO NOTHING."""
    if not batch:
        return 0
    result = db.execute(_INSERT_SQL, batch)
    db.commit()
    return result.rowcount


def _load_year(
    zip_path: Path, year: int, ags_map: dict[str, str], db: Session, run_id: int
) -> tuple[int, int]:
    """Load one year. Returns (inserted, unresolved)."""
    print(f"[accidents] Reading {zip_path.name}...")
    df = _read_year_csv(zip_path)
    print(f"[accidents] {year}: {len(df)} rows read")

    rows, unresolved = _transform(df, year, ags_map, run_id)

    if unresolved > 0:
        pct = 100.0 * unresolved / len(rows) if rows else 0.0
        print(
            f"[accidents] {year}: {unresolved} rows ({pct:.1f}%) unresolved AGS"
            " (region_id=NULL)"
        )
        if pct > 5.0:
            raise RuntimeError(
                f"[accidents] {year}: {pct:.1f}% unresolved AGS > 5% threshold. "
                "Extend regions_history with missing codes."
            )

    inserted = 0
    for start in range(0, len(rows), BATCH_SIZE):
        batch = rows[start : start + BATCH_SIZE]
        inserted += _insert_batch(db, batch)

    return inserted, unresolved


def run_accidents_etl(
    db: Session,
    years: list[int] | None = None,
    specific_year: int | None = None,
) -> dict:
    """
    Load Unfallatlas accident data.

    Args:
        db: SQLAlchemy session
        years: explicit list of years (default: auto-detect from ACCIDENT_DIR)
        specific_year: shorthand for years=[specific_year]
    """
    if specific_year is not None:
        years = [specific_year]
    if years is None:
        years = sorted(
            int(p.stem.split("Unfallorte")[1].split("_EPSG")[0])
            for p in ACCIDENT_DIR.glob("Unfallorte*_EPSG25832_CSV.zip")
            if "Unfallorte" in p.stem
        )
    if not years:
        print("[accidents] No accident zip files found in rawData/Accidents/ — skipping")
        return {"inserted": 0, "updated": 0}

    ags_map = _build_ags_map(db)
    run_id = start_import_run(db, "unfallatlas", str(ACCIDENT_DIR))

    total_ins = total_unres = 0
    try:
        for year in years:
            zip_path = ACCIDENT_DIR / f"Unfallorte{year}_EPSG25832_CSV.zip"
            if not zip_path.exists():
                print(f"[accidents] {year}: file not found, skipping")
                continue
            ins, unres = _load_year(zip_path, year, ags_map, db, run_id)
            print(f"[accidents] {year}: {ins} inserted")
            total_ins += ins
            total_unres += unres
    except Exception as exc:
        finish_import_run(
            db, run_id,
            status="failed",
            rows_inserted=total_ins,
            rows_updated=0,
            error_message=str(exc),
        )
        raise

    finish_import_run(db, run_id, status="success", rows_inserted=total_ins, rows_updated=0)
    print(f"[accidents] Done: {total_ins} total inserted, {total_unres} unresolved AGS")
    return {"inserted": total_ins, "updated": 0, "unresolved": total_unres}
