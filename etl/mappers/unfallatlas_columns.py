"""
Per-year column name mapper for Unfallatlas CSV files.

Unfallatlas changed column names across schema generations:
- LICHT (pre-2020) → ULICHTVERH (2020+)
- STRZUSTAND added in 2020
- UIDENTSTLAE added in 2018 (used as accident_uid; synthesised SHA-1 for 2016-2017)
"""

# Columns present in all years
BASE_COLUMNS = [
    "ULAND", "UREGBEZ", "UKREIS", "UGEMEINDE",
    "UJAHR", "UMONAT", "USTUNDE", "UWOCHENTAG",
    "UKATEGORIE", "UART", "UTYP1",
    "ULICHTVERH",  # normalised name (see get_column_map)
    "IstRad", "IstPKW", "IstFuss", "IstKrad", "IstGkfz", "IstSonstige",
    "XGCSWGS84", "YGCSWGS84",
]


def get_column_map(year: int) -> dict[str, str]:
    """Return a rename map {raw_col: canonical_col} for the given year."""
    mapping: dict[str, str] = {}
    if year < 2020:
        # Pre-2020: light condition column is called LICHT
        mapping["LICHT"] = "ULICHTVERH"
    # STRZUSTAND only available from 2020; missing years → None (handled in ETL)
    return mapping


def has_uid_column(year: int) -> bool:
    """UIDENTSTLAE is present from 2018 onwards."""
    return year >= 2018


def has_road_condition(year: int) -> bool:
    """STRZUSTAND is present from 2020 onwards."""
    return year >= 2020
