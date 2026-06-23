"""
Phase 4 ETL: load population and PKW indicator values from Regionalstatistik.

Downloads district-level CSV tables from GENESIS-Online:
  - 12411-01-01-4: Bevölkerung (population per district per year)
  - 46251-01-01-4: PKW-Bestand (registered passenger cars per district per year)

CSV format (GENESIS-Online wide format):
  Several metadata header lines → detected by scanning for the row that starts
  with a plausible AGS-like code. Then wide format: cols are years, rows are districts.
  Values use "." as thousands separator (e.g. "89.504" = 89504) and "." or "-" for missing.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from etl.common import (
    RAW_DATA_DIR,
    download_file,
    finish_import_run,
    sha256_file,
    start_import_run,
)

INDICATOR_DIR = RAW_DATA_DIR / "Indicators"

_BASE_URL = "https://www.regionalstatistik.de/genesis/online/data"

INDICATOR_SOURCES = {
    "population": {
        "table": "12411-01-01-4",
        "url_params": "operation=abruftabelleDownload&selectionname=12411-01-01-4&regionalmerkmal=KREISE&format=CSV",
        "filename": "population_kreise.csv",
    },
    "cars_pkw": {
        "table": "46251-01-01-4",
        "url_params": "operation=abruftabelleDownload&selectionname=46251-01-01-4&regionalmerkmal=KREISE&format=CSV",
        "filename": "cars_pkw_kreise.csv",
    },
}


def _clean_value(val: str) -> int | None:
    """Parse GENESIS numeric value: strip thousands dots, handle missing markers."""
    if not val or val.strip() in (".", "-", "/", "x", "X", ""):
        return None
    # Remove thousands separator (period in German locale) and whitespace
    cleaned = val.strip().replace(".", "").replace("\xa0", "")
    try:
        return int(cleaned)
    except ValueError:
        return None


def _find_data_start(lines: list[str], sep: str) -> int:
    """
    Scan lines to find the index of the first data row (district AGS in first field).
    Skips metadata header block.
    District AGS codes are exactly 5 digits with state prefix 01-16.
    """
    for i, line in enumerate(lines):
        parts = line.strip().strip('"').split(sep)
        first = parts[0].strip().strip('"').strip()
        # District AGS: exactly 5 digits, state prefix 01–16, row must have
        # at least 3 fields (AGS + name + ≥1 year value) to exclude metadata lines
        if (
            len(first) == 5
            and first.isdigit()
            and 1 <= int(first[:2]) <= 16
            and len(parts) >= 3
        ):
            return i
    raise ValueError("Could not locate district AGS data row in Regionalstatistik CSV")


def _parse_csv(content: str, indicator_name: str) -> pd.DataFrame:
    """
    Parse a GENESIS-Online wide-format CSV into a long DataFrame with columns:
    [region_id, year, value].
    """
    # Try common separators; GENESIS uses ";" in most exports
    for sep in (";", ",", "\t"):
        if sep in content[:500]:
            break
    else:
        raise ValueError("Could not detect CSV separator in first 500 chars of Regionalstatistik file")

    lines = content.splitlines()
    data_start = _find_data_start(lines, sep)

    # The header row is just above the first data row
    header_row = data_start - 1
    if header_row < 0:
        raise ValueError("No header row found before data in Regionalstatistik CSV")

    header_line = lines[header_row]
    header_parts = [p.strip().strip('"') for p in header_line.split(sep)]

    data_lines = []
    for line in lines[data_start:]:
        stripped = line.strip()
        if not stripped:
            continue
        # Stop at footer separator lines
        if stripped.startswith("__") or stripped.startswith("Fußnote") or stripped.startswith("©"):
            break
        parts = [p.strip().strip('"') for p in stripped.split(sep)]
        if parts and parts[0].isdigit():
            data_lines.append(parts)

    if not data_lines:
        raise ValueError("No data rows found in Regionalstatistik CSV")

    n_cols = len(header_parts)
    # Pad short rows with empty strings; truncate rows longer than header
    data_lines = [
        (row + [""] * n_cols)[:n_cols] for row in data_lines
    ]
    df = pd.DataFrame(data_lines, columns=header_parts)

    # First column is AGS/Kreiskennziffer, second is name, rest are year columns
    ags_col = df.columns[0]
    year_cols = [c for c in df.columns[2:] if c.strip().isdigit()]

    # Pivot wide → long
    records = []
    for _, row in df.iterrows():
        ags = str(row[ags_col]).strip().zfill(5)  # District AGS is 5 chars
        for yr_col in year_cols:
            val = _clean_value(str(row.get(yr_col, "")))
            if val is not None:
                records.append({"region_id": ags, "year": int(yr_col), "value": val})

    return pd.DataFrame(records, columns=["region_id", "year", "value"])


def _get_indicator_id(db: Session, name: str) -> int:
    row = db.execute(
        text("SELECT id FROM indicators WHERE name = :name"), {"name": name}
    ).fetchone()
    if row is None:
        raise RuntimeError(f"Indicator '{name}' not found in indicators table")
    return row[0]


def _upsert_values(
    db: Session,
    long_df: pd.DataFrame,
    indicator_id: int,
    run_id: int,
    valid_ags: set[str],
) -> tuple[int, int]:
    """UPSERT rows into indicator_values. Returns (inserted, skipped)."""
    upsert_sql = text(
        """
        INSERT INTO indicator_values (indicator_id, region_id, year, value, import_run_id)
        VALUES (:ind_id, :region_id, :year, :value, :run_id)
        ON CONFLICT (indicator_id, region_id, year) DO UPDATE SET
            value = EXCLUDED.value,
            import_run_id = EXCLUDED.import_run_id
        """
    )
    inserted = skipped = 0
    batch: list[dict] = []
    BATCH = 2000

    for _, row in long_df.iterrows():
        ags = row["region_id"]
        if ags not in valid_ags:
            skipped += 1
            continue
        batch.append(
            {
                "ind_id": indicator_id,
                "region_id": ags,
                "year": int(row["year"]),
                "value": int(row["value"]),
                "run_id": run_id,
            }
        )
        if len(batch) >= BATCH:
            db.execute(upsert_sql, batch)
            db.commit()
            inserted += len(batch)
            batch = []

    if batch:
        db.execute(upsert_sql, batch)
        db.commit()
        inserted += len(batch)

    return inserted, skipped


def run_indicators_etl(db: Session) -> dict:
    """Download and load population + PKW indicator values from Regionalstatistik."""
    INDICATOR_DIR.mkdir(parents=True, exist_ok=True)

    # Pre-load all known district AGS from regions table
    valid_ags: set[str] = {
        r[0]
        for r in db.execute(text("SELECT ags FROM regions WHERE level = 'district'")).fetchall()
    }
    if not valid_ags:
        raise RuntimeError(
            "[indicators] No district regions found — run regions ETL first"
        )

    run_id = start_import_run(db, "regionalstatistik", _BASE_URL)
    total_ins = total_skip = 0

    try:
        for ind_name, src in INDICATOR_SOURCES.items():
            url = f"{_BASE_URL}?{src['url_params']}"
            dest = INDICATOR_DIR / src["filename"]

            print(f"[indicators] Downloading {ind_name} from Regionalstatistik...")
            try:
                download_file(url, dest)
            except Exception as exc:
                print(
                    f"[indicators] WARNING: Download failed for {ind_name}: {exc}. "
                    "Place a pre-downloaded CSV at '{dest}' to proceed."
                )
                if not dest.exists():
                    continue

            file_hash = sha256_file(dest)
            print(f"[indicators] Parsing {dest.name} (sha256={file_hash[:8]}…)")

            # Try common encodings
            content: str | None = None
            for enc in ("utf-8-sig", "latin-1", "cp1252"):
                try:
                    content = dest.read_text(encoding=enc)
                    break
                except UnicodeDecodeError:
                    continue
            if content is None:
                print(f"[indicators] Could not decode {dest.name}, skipping")
                continue

            try:
                long_df = _parse_csv(content, ind_name)
                indicator_id = _get_indicator_id(db, ind_name)
            except Exception as exc:
                print(f"[indicators] Error for {ind_name}: {exc}, skipping")
                continue

            ins, skip = _upsert_values(db, long_df, indicator_id, run_id, valid_ags)
            print(f"[indicators] {ind_name}: {ins} upserted, {skip} skipped (no matching AGS)")
            total_ins += ins
            total_skip += skip

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
    print(f"[indicators] Done: {total_ins} rows upserted")
    return {"inserted": total_ins, "skipped": total_skip}
