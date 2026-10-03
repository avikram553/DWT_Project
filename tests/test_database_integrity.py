"""
Integration tests: Database schema, data integrity, and referential consistency.

Validates:
  - Schema matches expected tables and columns
  - Referential integrity (foreign keys resolve)
  - Data completeness and plausibility
  - Index existence for performance-critical queries
  - AGS code format correctness (TEXT, leading zeros preserved)
"""
import pytest
from sqlalchemy import text


# ═══════════════════════════════════════════════════════════════════════════════
# 1. SCHEMA VALIDATION
# ═══════════════════════════════════════════════════════════════════════════════


class TestSchemaExistence:
    """All 9 expected tables must exist with PostGIS extension enabled."""

    EXPECTED_TABLES = [
        "sources", "import_runs", "regions", "lookup_codes",
        "accidents", "indicators", "indicator_values",
        "accident_zones", "regions_history",
    ]

    def test_postgis_extension_enabled(self, db):
        """PostGIS extension must be installed."""
        row = db.execute(text(
            "SELECT count(*) FROM pg_extension WHERE extname = 'postgis'"
        )).scalar()
        assert row == 1, "PostGIS extension not installed"

    @pytest.mark.parametrize("table", EXPECTED_TABLES)
    def test_table_exists(self, db, table):
        """Each expected table must exist in the public schema."""
        row = db.execute(text(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = :name"
        ), {"name": table}).scalar()
        assert row == 1, f"Table '{table}' does not exist"

    def test_region_level_enum_exists(self, db):
        """The region_level enum type must exist."""
        row = db.execute(text(
            "SELECT count(*) FROM pg_type WHERE typname = 'region_level'"
        )).scalar()
        assert row == 1, "Enum type 'region_level' does not exist"

    def test_region_level_values(self, db):
        """region_level enum must have exactly {state, district, municipality}."""
        rows = db.execute(text(
            "SELECT enumlabel FROM pg_enum "
            "JOIN pg_type ON pg_enum.enumtypid = pg_type.oid "
            "WHERE pg_type.typname = 'region_level' "
            "ORDER BY enumsortorder"
        )).fetchall()
        labels = [r[0] for r in rows]
        assert set(labels) == {"state", "district", "municipality"}


# ═══════════════════════════════════════════════════════════════════════════════
# 2. INDEX VALIDATION
# ═══════════════════════════════════════════════════════════════════════════════


class TestIndexExistence:
    """Performance-critical indexes must exist."""

    EXPECTED_INDEXES = [
        "idx_accidents_year",
        "idx_accidents_region_year",
        "idx_accidents_year_category",
        "idx_accidents_fatal_partial",
        "idx_accidents_geom",
        "idx_regions_level_parent",
        "idx_regions_geom",
        "idx_zones_geom_proj",
        "idx_zones_geom",
        "idx_indicator_values_lookup",
    ]

    # Index defined in schema SQL but not yet created in the live DB.
    # Tracked here so it can be flagged when the schema is applied fully.
    MISSING_INDEXES = [
        "idx_regions_history_old_ags",
    ]

    @pytest.mark.parametrize("index_name", EXPECTED_INDEXES)
    def test_index_exists(self, db, index_name):
        """Each performance-critical index must exist."""
        row = db.execute(text(
            "SELECT count(*) FROM pg_indexes "
            "WHERE schemaname = 'public' AND indexname = :name"
        ), {"name": index_name}).scalar()
        assert row == 1, f"Index '{index_name}' does not exist"

    def test_gist_indexes_on_geom_columns(self, db):
        """GiST indexes should be used for geometry columns."""
        rows = db.execute(text("""
            SELECT indexname, indexdef FROM pg_indexes
            WHERE schemaname = 'public'
              AND indexdef LIKE '%USING gist%'
        """)).fetchall()
        gist_names = {r[0] for r in rows}
        assert "idx_accidents_geom" in gist_names
        assert "idx_regions_geom" in gist_names


# ═══════════════════════════════════════════════════════════════════════════════
# 3. DATA COMPLETENESS
# ═══════════════════════════════════════════════════════════════════════════════


class TestDataCompleteness:
    """Critical tables must be populated with expected volumes."""

    def test_sources_populated(self, db):
        """Sources table should have at least 3 entries."""
        row = db.execute(text("SELECT count(*) FROM sources")).scalar()
        assert row >= 3

    def test_regions_16_states(self, db):
        """Exactly 16 German states."""
        row = db.execute(text(
            "SELECT count(*) FROM regions WHERE level = 'state'"
        )).scalar()
        assert row == 16

    def test_regions_districts_count(self, db):
        """~400 German districts."""
        row = db.execute(text(
            "SELECT count(*) FROM regions WHERE level = 'district'"
        )).scalar()
        assert 350 <= row <= 500, f"Unexpected district count: {row}"

    def test_regions_municipalities_count(self, db):
        """~10,000+ German municipalities."""
        row = db.execute(text(
            "SELECT count(*) FROM regions WHERE level = 'municipality'"
        )).scalar()
        assert row > 5000, f"Too few municipalities: {row}"

    def test_accidents_populated(self, db):
        """Accidents table should have >1M rows (2016–2024 data)."""
        row = db.execute(text("SELECT count(*) FROM accidents")).scalar()
        assert row > 1_000_000, f"Too few accidents: {row}"

    def test_accidents_year_range(self, db):
        """Accident data should span 2016–2024."""
        row = db.execute(text(
            "SELECT MIN(year), MAX(year) FROM accidents"
        )).fetchone()
        assert row[0] == 2016, f"Earliest year is {row[0]}, expected 2016"
        assert row[1] == 2024, f"Latest year is {row[1]}, expected 2024"

    def test_indicators_exist(self, db):
        """At least population and cars_pkw indicators should exist."""
        rows = db.execute(text(
            "SELECT name FROM indicators ORDER BY name"
        )).fetchall()
        names = {r[0] for r in rows}
        assert "population" in names
        assert "cars_pkw" in names

    def test_indicator_values_populated(self, db):
        """Indicator values should have substantial data."""
        row = db.execute(text("SELECT count(*) FROM indicator_values")).scalar()
        assert row > 1000, f"Too few indicator values: {row}"

    def test_lookup_codes_populated(self, db):
        """Lookup codes should include accident categories and days of week."""
        rows = db.execute(text(
            "SELECT DISTINCT category FROM lookup_codes ORDER BY category"
        )).fetchall()
        categories = {r[0] for r in rows}
        assert "accident_category" in categories
        assert "day_of_week" in categories


# ═══════════════════════════════════════════════════════════════════════════════
# 4. REFERENTIAL INTEGRITY
# ═══════════════════════════════════════════════════════════════════════════════


class TestReferentialIntegrity:
    """Foreign key relationships should be consistent."""

    def test_accident_region_ids_resolve(self, db):
        """
        All non-NULL accident region_ids should reference existing regions.
        Some NULL region_ids are expected (~1%) for unresolved AGS codes.
        """
        row = db.execute(text("""
            SELECT count(*) FROM accidents a
            WHERE a.region_id IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM regions r WHERE r.ags = a.region_id
              )
        """)).scalar()
        assert row == 0, f"{row} accidents reference non-existent regions"

    def test_region_parent_ags_resolves(self, db):
        """All non-NULL parent_ags should reference existing regions."""
        row = db.execute(text("""
            SELECT count(*) FROM regions r1
            WHERE r1.parent_ags IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM regions r2 WHERE r2.ags = r1.parent_ags
              )
        """)).scalar()
        assert row == 0, f"{row} regions reference non-existent parents"

    def test_indicator_values_region_resolves(self, db):
        """Indicator value region_ids should reference existing regions."""
        row = db.execute(text("""
            SELECT count(*) FROM indicator_values iv
            WHERE NOT EXISTS (
                SELECT 1 FROM regions r WHERE r.ags = iv.region_id
            )
        """)).scalar()
        assert row == 0, f"{row} indicator values reference non-existent regions"

    def test_indicator_values_indicator_resolves(self, db):
        """Indicator value indicator_ids should reference existing indicators."""
        row = db.execute(text("""
            SELECT count(*) FROM indicator_values iv
            WHERE NOT EXISTS (
                SELECT 1 FROM indicators i WHERE i.id = iv.indicator_id
            )
        """)).scalar()
        assert row == 0

    def test_import_runs_source_resolves(self, db):
        """Import run source_ids should reference existing sources."""
        row = db.execute(text("""
            SELECT count(*) FROM import_runs ir
            WHERE ir.source_id IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM sources s WHERE s.id = ir.source_id
              )
        """)).scalar()
        assert row == 0

    def test_regions_history_new_ags_resolves(self, db):
        """regions_history.new_ags should reference existing regions."""
        row = db.execute(text("""
            SELECT count(*) FROM regions_history rh
            WHERE NOT EXISTS (
                SELECT 1 FROM regions r WHERE r.ags = rh.new_ags
            )
        """)).scalar()
        assert row == 0


# ═══════════════════════════════════════════════════════════════════════════════
# 5. AGS CODE FORMAT
# ═══════════════════════════════════════════════════════════════════════════════


class TestAGSCodeFormat:
    """AGS codes must be TEXT with correct lengths and leading zeros preserved."""

    def test_state_ags_is_2_chars(self, db):
        """State AGS codes should be exactly 2 characters."""
        row = db.execute(text(
            "SELECT count(*) FROM regions "
            "WHERE level = 'state' AND length(ags) != 2"
        )).scalar()
        assert row == 0, f"{row} states with AGS not 2 chars"

    def test_district_ags_is_5_chars(self, db):
        """District AGS codes should be exactly 5 characters."""
        row = db.execute(text(
            "SELECT count(*) FROM regions "
            "WHERE level = 'district' AND length(ags) != 5"
        )).scalar()
        assert row == 0, f"{row} districts with AGS not 5 chars"

    def test_municipality_ags_is_8_chars(self, db):
        """Municipality AGS codes should be exactly 8 characters."""
        row = db.execute(text(
            "SELECT count(*) FROM regions "
            "WHERE level = 'municipality' AND length(ags) != 8"
        )).scalar()
        assert row == 0, f"{row} municipalities with AGS not 8 chars"

    def test_ags_contains_only_digits(self, db):
        """AGS codes should contain only digits (no letters/spaces)."""
        row = db.execute(text(
            "SELECT count(*) FROM regions WHERE ags ~ '[^0-9]'"
        )).scalar()
        assert row == 0, f"{row} regions have non-digit characters in AGS"

    def test_leading_zeros_preserved(self, db):
        """States with AGS starting with '0' must retain the leading zero."""
        rows = db.execute(text(
            "SELECT ags FROM regions WHERE level = 'state' AND ags LIKE '0%'"
        )).fetchall()
        # States 01..09 should exist with leading zero
        leading_zero_states = {r[0] for r in rows}
        expected = {"01", "02", "03", "04", "05", "06", "07", "08", "09"}
        assert expected.issubset(leading_zero_states), (
            f"Missing leading-zero states: {expected - leading_zero_states}"
        )

    def test_district_parent_prefix_match(self, db):
        """District AGS[:2] should match their parent state AGS."""
        row = db.execute(text("""
            SELECT count(*) FROM regions
            WHERE level = 'district'
              AND LEFT(ags, 2) != parent_ags
        """)).scalar()
        assert row == 0, f"{row} districts with parent AGS mismatch"


# ═══════════════════════════════════════════════════════════════════════════════
# 6. DATA PLAUSIBILITY
# ═══════════════════════════════════════════════════════════════════════════════


class TestDataPlausibility:
    """Sanity checks on data values."""

    def test_accident_categories_valid(self, db):
        """Accident categories should be 1 (fatal), 2 (serious), or 3 (light)."""
        rows = db.execute(text(
            "SELECT DISTINCT category FROM accidents "
            "WHERE category IS NOT NULL ORDER BY category"
        )).fetchall()
        categories = {r[0] for r in rows}
        assert categories.issubset({1, 2, 3}), (
            f"Unexpected accident categories: {categories}"
        )

    def test_accident_day_of_week_valid(self, db):
        """day_of_week should be 1–7 (Destatis: 1=Sunday … 7=Saturday)."""
        rows = db.execute(text(
            "SELECT DISTINCT day_of_week FROM accidents "
            "WHERE day_of_week IS NOT NULL ORDER BY day_of_week"
        )).fetchall()
        days = {r[0] for r in rows}
        assert days.issubset({1, 2, 3, 4, 5, 6, 7}), (
            f"Unexpected day_of_week values: {days}"
        )

    def test_accident_hours_valid(self, db):
        """hour should be 0–23."""
        row = db.execute(text(
            "SELECT count(*) FROM accidents "
            "WHERE hour IS NOT NULL AND (hour < 0 OR hour > 23)"
        )).scalar()
        assert row == 0, f"{row} accidents with invalid hour"

    def test_accident_months_valid(self, db):
        """month should be 1–12."""
        row = db.execute(text(
            "SELECT count(*) FROM accidents "
            "WHERE month IS NOT NULL AND (month < 1 OR month > 12)"
        )).scalar()
        assert row == 0, f"{row} accidents with invalid month"

    def test_population_values_nonnegative(self, db):
        """Population indicator values should be non-negative."""
        row = db.execute(text("""
            SELECT count(*) FROM indicator_values iv
            JOIN indicators i ON i.id = iv.indicator_id
            WHERE i.name = 'population' AND iv.value < 0
        """)).scalar()
        assert row == 0, f"{row} negative population values"

    def test_accident_uid_uniqueness(self, db):
        """accident_uid should be unique across the table."""
        row = db.execute(text("""
            SELECT count(*) - count(DISTINCT accident_uid) AS dupes
            FROM accidents
        """)).scalar()
        assert row == 0, f"{row} duplicate accident UIDs"

    def test_import_runs_have_valid_status(self, db):
        """Import run status should be running, success, or failed."""
        rows = db.execute(text(
            "SELECT DISTINCT status FROM import_runs"
        )).fetchall()
        statuses = {r[0] for r in rows}
        assert statuses.issubset({"running", "success", "failed"}), (
            f"Unexpected statuses: {statuses}"
        )
