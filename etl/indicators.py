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
        "filename": "12411-01-01-4.csv",
        "csv_format": "population_multi",
        "local_only": True,
    },
    # Two files cover the full range: 2016-2019 + 2020-2025
    # local_only=True: requires manual download (GENESIS needs browser session)
    "cars_pkw": {
        "table": "46251-01-03-4",
        "url_params": "operation=abruftabelleDownload&selectionname=46251-01-03-4&regionalmerkmal=KREISE&format=CSV",
        "filename": "46251-01-03-4.csv",
        "csv_format": "long",
        "value_col": 4,
        "local_only": True,
    },
    "cars_pkw_pre2020": {
        "table": "46251-01-02-4",
        "url_params": "operation=abruftabelleDownload&selectionname=46251-01-02-4&regionalmerkmal=KREISE&format=CSV",
        "filename": "46251-01-02-4.csv",
        "csv_format": "long",
        "value_col": 4,
        "indicator_name": "cars_pkw",
        "local_only": True,
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


def _parse_csv_population_multi(content: str) -> pd.DataFrame:
    """
    Parse 12411-01-01-4 multi-year population CSV.
    Row with dates: ;;31.12.2024;31.12.2024;31.12.2024;31.12.2023;...
    Every 3rd column starting at col 2 is Insgesamt (total population) for that year.
    """
    import re
    sep = ";"
    lines = content.splitlines()
    year_cols: list[tuple[int, int]] = []  # (col_index, year)

    for line in lines:
        parts = line.split(sep)
        dates = [(i, re.search(r'(\d{4})', p)) for i, p in enumerate(parts)]
        hits = [(i, int(m.group(1))) for i, m in dates if m and 2000 <= int(m.group(1)) <= 2030]
        if len(hits) >= 3:
            year_cols = [(idx, yr) for j, (idx, yr) in enumerate(hits) if j % 3 == 0]
            break

    if not year_cols:
        raise ValueError("Could not find year columns in population CSV")

    records = []
    for line in lines:
        parts = line.split(sep)
        ags = parts[0].strip().strip('"')
        if not (len(ags) == 5 and ags.isdigit() and 1 <= int(ags[:2]) <= 16):
            continue
        for col_idx, yr in year_cols:
            if col_idx >= len(parts):
                continue
            val = _clean_value(parts[col_idx])
            if val is None:
                continue
            records.append({"region_id": ags, "year": yr, "value": val})

    if not records:
        raise ValueError("No valid district rows in population multi-year CSV")
    return pd.DataFrame(records, columns=["region_id", "year", "value"])


def _parse_csv_flat(content: str, value_col: int = 2) -> pd.DataFrame:
    """
    Parse single-year flat CSV: AGS in col 0, year embedded in header as DD.MM.YYYY.
    Used for population_kreise.csv (12411-01-01-4).
    """
    import re
    sep = ";"
    year = None
    records = []
    for line in content.splitlines():
        parts = line.split(sep)
        # Find year from date header like "31.12.2024"
        if year is None:
            for p in parts:
                m = re.search(r'\b(\d{4})\b', p.strip())
                if m and 2000 <= int(m.group(1)) <= 2030:
                    year = int(m.group(1))
                    break
            continue  # header lines: keep scanning until we hit data
        ags = parts[0].strip().strip('"')
        if not (len(ags) == 5 and ags.isdigit() and 1 <= int(ags[:2]) <= 16):
            continue
        if len(parts) <= value_col:
            continue
        val = _clean_value(parts[value_col])
        if val is None:
            continue
        records.append({"region_id": ags, "year": year, "value": val})
    if not records:
        raise ValueError("No valid district rows in flat CSV")
    return pd.DataFrame(records, columns=["region_id", "year", "value"])


def _parse_csv_long(content: str, value_col: int = 4) -> pd.DataFrame:
    """
    Parse 46251-01-03-4 long-format CSV: one row per Stichtag × district.
    Col 0 = date (DD.MM.YYYY), col 1 = AGS, col {value_col} = indicator value.
    Filters to 5-digit district AGS only; extracts year from date.
    """
    sep = ";"
    records = []
    for line in content.splitlines():
        parts = line.split(sep)
        if len(parts) <= value_col:
            continue
        date_str = parts[0].strip().strip('"')
        ags = parts[1].strip().strip('"').strip()
        # Must be 5-digit district AGS (state prefix 01-16)
        if not (len(ags) == 5 and ags.isdigit() and 1 <= int(ags[:2]) <= 16):
            continue
        # Parse year from "DD.MM.YYYY"
        try:
            year = int(date_str.split(".")[-1])
        except (ValueError, IndexError):
            continue
        val = _clean_value(parts[value_col])
        if val is None:
            continue
        records.append({"region_id": ags, "year": year, "value": val})
    if not records:
        raise ValueError("No valid district rows in long-format CSV")
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
            dest = INDICATOR_DIR / src["filename"]

            if src.get("local_only"):
                if not dest.exists():
                    print(f"[indicators] SKIP {ind_name}: {dest} not found — place file manually")
                    continue
                print(f"[indicators] Using local file {dest.name}")
            else:
                url = f"{_BASE_URL}?{src['url_params']}"
                print(f"[indicators] Downloading {ind_name} from Regionalstatistik...")
                try:
                    download_file(url, dest)
                except Exception as exc:
                    print(f"[indicators] WARNING: Download failed for {ind_name}: {exc}.")
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

            if content.lstrip().startswith(("<!DOCTYPE", "<html", "<!doctype")):
                print(f"[indicators] {dest.name} is HTML (needs manual download), skipping")
                continue

            try:
                fmt = src.get("csv_format", "wide")
                if fmt == "long":
                    long_df = _parse_csv_long(content, value_col=src.get("value_col", 4))
                elif fmt == "flat":
                    long_df = _parse_csv_flat(content, value_col=src.get("value_col", 2))
                elif fmt == "population_multi":
                    long_df = _parse_csv_population_multi(content)
                else:
                    long_df = _parse_csv(content, ind_name)
                db_indicator = src.get("indicator_name", ind_name)
                indicator_id = _get_indicator_id(db, db_indicator)
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
