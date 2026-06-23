"""
Per-year column name normalisation for Unfallatlas CSV files.

Actual observed column variations (verified against rawData):
- 2016: ULICHTVERH, no STRZUSTAND, no uid, has IstSonstig/IstGkfz, FID+OBJECTID id cols
- 2017: LICHT, STRZUSTAND, UIDENTSTLA (truncated uid), IstSonstig, no IstGkfz, OBJECTID
- 2018: ULICHTVERH, STRZUSTAND, no uid, IstSonstig/IstGkfz, OBJECTID_1
- 2019: ULICHTVERH, STRZUSTAND (at end), no uid, IstSonstige/IstGkfz, OBJECTID
- 2020: ULICHTVERH, STRZUSTAND, UIDENTSTLAE, IstSonstige/IstGkfz, OBJECTID
- 2021: UTF-8 BOM, OID_ prefix, ULICHTVERH, IstStrassenzustand, UIDENTSTLAE, IstSonstige/IstGkfz
- 2022: ULICHTVERH, IstStrassenzustand, UIDENTSTLAE, IstSonstige/IstGkfz, OBJECTID
- 2023: UTF-8 BOM, OID_ prefix, ULICHTVERH, IstStrassenzustand, UIDENTSTLAE, IstSonstige/IstGkfz, PLST
- 2024: same as 2023
"""


def detect_encoding(first_bytes: bytes) -> str:
    """Return 'utf-8-sig' if UTF-8 BOM present, else 'latin-1'."""
    return "utf-8-sig" if first_bytes[:3] == b"\xef\xbb\xbf" else "latin-1"


def normalize_columns(raw_columns: list[str]) -> dict[str, str]:
    """
    Return {raw_name: canonical_name} rename map based on actual column names.
    Canonical targets match what the ETL expects to read.
    """
    renames: dict[str, str] = {}

    # Strip BOM from first column if present
    for col in raw_columns:
        stripped = col.lstrip("﻿").lstrip("ï»¿")
        if stripped != col:
            renames[col] = stripped

    # Work on potentially-renamed columns
    effective = [renames.get(c, c) for c in raw_columns]

    # ID column → OBJECTID (only if OBJECTID not already present)
    if "OBJECTID" not in effective:
        for id_col in ("OID_", "OBJECTID_1", "FID"):
            if id_col in effective:
                renames[raw_columns[effective.index(id_col)]] = "OBJECTID"
                break

    # Light condition column
    if "LICHT" in effective and "ULICHTVERH" not in effective:
        renames[raw_columns[effective.index("LICHT")]] = "ULICHTVERH"

    # Road condition column
    if "IstStrassenzustand" in effective and "STRZUSTAND" not in effective:
        renames[raw_columns[effective.index("IstStrassenzustand")]] = "STRZUSTAND"

    # Trailing 'e' normalisation for IstSonstig
    if "IstSonstig" in effective and "IstSonstige" not in effective:
        renames[raw_columns[effective.index("IstSonstig")]] = "IstSonstige"

    # 2017: truncated UID column
    if "UIDENTSTLA" in effective and "UIDENTSTLAE" not in effective:
        renames[raw_columns[effective.index("UIDENTSTLA")]] = "UIDENTSTLAE"

    return renames


def has_uid_column(columns: list[str]) -> bool:
    """True if UIDENTSTLAE (or UIDENTSTLA) is present after normalisation."""
    return "UIDENTSTLAE" in columns or "UIDENTSTLA" in columns


def has_road_condition(columns: list[str]) -> bool:
    """True if STRZUSTAND or IstStrassenzustand is present."""
    return "STRZUSTAND" in columns or "IstStrassenzustand" in columns
