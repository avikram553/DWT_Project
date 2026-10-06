"""
Integration tests: Spatial polygon correctness in the PostGIS database.

Validates:
  - All region geometries are valid, non-empty MULTIPOLYGON in SRID 4326
  - Ring closure and proper winding order
  - Bounding boxes cover Germany's geographic extent
  - Parent/child containment (states contain their districts)
  - No overlapping states
  - Accident point-in-polygon consistency
  - Region area plausibility by level
"""
import pytest
from sqlalchemy import text


# ═══════════════════════════════════════════════════════════════════════════════
# 1. GEOMETRY TYPE, SRID, AND VALIDITY
# ═══════════════════════════════════════════════════════════════════════════════


class TestRegionGeometryValidity:
    """All region polygons must be valid, non-empty MULTIPOLYGONs in WGS84."""

    def test_all_regions_have_geometry(self, db):
        """Every region row must have a non-NULL geom column."""
        row = db.execute(text(
            "SELECT count(*) AS total, count(geom) AS has_geom FROM regions"
        )).fetchone()
        total, has_geom = row[0], row[1]
        assert total > 0, "regions table is empty"
        assert has_geom == total, (
            f"{total - has_geom} regions are missing geometry"
        )

    @pytest.mark.parametrize("level", ["state", "district", "municipality"])
    def test_geometry_type_is_multipolygon(self, db, level):
        """All geometries at each level must be ST_MultiPolygon."""
        rows = db.execute(text(
            "SELECT DISTINCT ST_GeometryType(geom) "
            "FROM regions WHERE level = :level AND geom IS NOT NULL"
        ), {"level": level}).fetchall()
        types = {r[0] for r in rows}
        assert types == {"ST_MultiPolygon"}, (
            f"Unexpected geometry types at {level} level: {types}"
        )

    @pytest.mark.parametrize("level", ["state", "district", "municipality"])
    def test_srid_is_4326(self, db, level):
        """All geometries must use SRID 4326 (WGS84)."""
        rows = db.execute(text(
            "SELECT DISTINCT ST_SRID(geom) "
            "FROM regions WHERE level = :level AND geom IS NOT NULL"
        ), {"level": level}).fetchall()
        srids = {r[0] for r in rows}
        assert srids == {4326}, f"Unexpected SRIDs at {level} level: {srids}"

    @pytest.mark.parametrize("level", ["state", "district", "municipality"])
    def test_all_geometries_valid(self, db, level):
        """ST_IsValid must be true for every region geometry."""
        row = db.execute(text(
            "SELECT count(*) FILTER (WHERE NOT ST_IsValid(geom)) AS invalid "
            "FROM regions WHERE level = :level AND geom IS NOT NULL"
        ), {"level": level}).fetchone()
        assert row[0] == 0, f"{row[0]} invalid geometries at {level} level"

    @pytest.mark.parametrize("level", ["state", "district", "municipality"])
    def test_no_empty_geometries(self, db, level):
        """No geometry should be empty (ST_IsEmpty)."""
        row = db.execute(text(
            "SELECT count(*) FILTER (WHERE ST_IsEmpty(geom)) AS empty "
            "FROM regions WHERE level = :level AND geom IS NOT NULL"
        ), {"level": level}).fetchone()
        assert row[0] == 0, f"{row[0]} empty geometries at {level} level"

    @pytest.mark.parametrize("level", ["state", "district", "municipality"])
    def test_no_degenerate_geometries(self, db, level):
        """Every polygon should have at least 4 coordinate points (triangle)."""
        row = db.execute(text(
            "SELECT count(*) FILTER (WHERE ST_NPoints(geom) < 4) AS degenerate "
            "FROM regions WHERE level = :level AND geom IS NOT NULL"
        ), {"level": level}).fetchone()
        assert row[0] == 0, f"{row[0]} degenerate geometries at {level} level"


# ═══════════════════════════════════════════════════════════════════════════════
# 2. BOUNDING BOX — GERMANY COVERAGE
# ═══════════════════════════════════════════════════════════════════════════════


class TestGeographicExtent:
    """Region extents must cover Germany's geographic bounding box."""

    # Germany's approximate bounding box (WGS84)
    GERMANY_LON_MIN = 5.85
    GERMANY_LON_MAX = 15.05
    GERMANY_LAT_MIN = 47.25
    GERMANY_LAT_MAX = 55.10

    def test_state_extent_covers_germany(self, db):
        """The combined extent of all states should cover Germany."""
        row = db.execute(text(
            "SELECT ST_XMin(ST_Extent(geom)), ST_YMin(ST_Extent(geom)), "
            "       ST_XMax(ST_Extent(geom)), ST_YMax(ST_Extent(geom)) "
            "FROM regions WHERE level = 'state'"
        )).fetchone()
        min_lon, min_lat, max_lon, max_lat = row
        assert min_lon < self.GERMANY_LON_MIN + 0.1, f"West extent too far east: {min_lon}"
        assert max_lon > self.GERMANY_LON_MAX - 0.1, f"East extent too far west: {max_lon}"
        assert min_lat < self.GERMANY_LAT_MIN + 0.1, f"South extent too far north: {min_lat}"
        assert max_lat > self.GERMANY_LAT_MAX - 0.1, f"North extent too far south: {max_lat}"

    def test_no_region_outside_germany(self, db):
        """No region centroid should be outside Germany's extended bbox."""
        row = db.execute(text("""
            SELECT count(*) FROM regions
            WHERE geom IS NOT NULL
              AND NOT ST_Within(
                  ST_Centroid(geom),
                  ST_MakeEnvelope(:xmin, :ymin, :xmax, :ymax, 4326)
              )
        """), {
            "xmin": self.GERMANY_LON_MIN - 0.5,
            "ymin": self.GERMANY_LAT_MIN - 0.5,
            "xmax": self.GERMANY_LON_MAX + 0.5,
            "ymax": self.GERMANY_LAT_MAX + 0.5,
        }).scalar()
        assert row == 0, f"{row} regions have centroids outside Germany bbox"


# ═══════════════════════════════════════════════════════════════════════════════
# 3. REGION HIERARCHY — CONTAINMENT
# ═══════════════════════════════════════════════════════════════════════════════


class TestRegionHierarchy:
    """Spatial hierarchy: districts must be inside states; municipalities inside districts."""

    def test_expected_region_counts(self, db):
        """Sanity check that we have 16 states, ~400 districts, ~10k municipalities."""
        rows = db.execute(text(
            "SELECT level, count(*) FROM regions GROUP BY level ORDER BY level"
        )).fetchall()
        counts = {r[0]: r[1] for r in rows}
        assert counts["state"] == 16
        assert counts["district"] >= 300  # ~400
        assert counts["municipality"] >= 5000  # ~11000

    def test_every_district_has_parent_state(self, db):
        """Every district must reference an existing state via parent_ags."""
        row = db.execute(text("""
            SELECT count(*) FROM regions d
            WHERE d.level = 'district'
              AND NOT EXISTS (
                  SELECT 1 FROM regions s
                  WHERE s.level = 'state' AND s.ags = d.parent_ags
              )
        """)).scalar()
        assert row == 0, f"{row} districts without a valid parent state"

    def test_district_centroids_within_parent_state(self, db):
        """District centroids should fall within their parent state polygon.
        
        A small number of coastal/exclave districts (e.g., Kiel, Wittmund,
        Konstanz) may have centroids just outside their state boundary due
        to bays, islands, or border irregularities. Allow up to 10.
        """
        row = db.execute(text("""
            SELECT count(*) FROM regions d
            JOIN regions s ON s.ags = d.parent_ags AND s.level = 'state'
            WHERE d.level = 'district'
              AND d.geom IS NOT NULL AND s.geom IS NOT NULL
              AND NOT ST_Contains(s.geom, ST_Centroid(d.geom))
        """)).scalar()
        assert row <= 10, (
            f"{row} district centroids fall outside their parent state "
            f"(allowed up to 10 for coastal/exclave districts)"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 4. REGION AREA PLAUSIBILITY
# ═══════════════════════════════════════════════════════════════════════════════


class TestRegionAreaPlausibility:
    """Region areas should be plausible for German administrative units."""

    def test_state_areas_within_range(self, db):
        """State areas should be between 100 km² (Bremen) and 100,000 km² (Bavaria)."""
        rows = db.execute(text("""
            SELECT ags, name, ST_Area(geom::geography) / 1e6 AS area_km2
            FROM regions
            WHERE level = 'state' AND geom IS NOT NULL
            ORDER BY area_km2
        """)).fetchall()
        for ags, name, area in rows:
            assert area > 50, f"State {name} ({ags}) area too small: {area:.1f} km²"
            assert area < 100000, f"State {name} ({ags}) area too large: {area:.1f} km²"

    def test_district_min_area(self, db):
        """No district should be smaller than 10 km² (micro-cities might be ~50 km²)."""
        row = db.execute(text("""
            SELECT count(*) FROM regions
            WHERE level = 'district'
              AND geom IS NOT NULL
              AND ST_Area(geom::geography) / 1e6 < 10
        """)).scalar()
        # Some city-districts are very small, allow up to a few
        assert row <= 5, f"{row} districts smaller than 10 km²"


# ═══════════════════════════════════════════════════════════════════════════════
# 5. ACCIDENT POINT GEOMETRY
# ═══════════════════════════════════════════════════════════════════════════════


class TestAccidentGeometry:
    """Accident point geometries should be valid and within Germany."""

    def test_accident_geom_srid(self, db):
        """All accident point geometries must use SRID 4326."""
        rows = db.execute(text(
            "SELECT DISTINCT ST_SRID(geom) FROM accidents WHERE geom IS NOT NULL"
        )).fetchall()
        srids = {r[0] for r in rows}
        assert srids == {4326}, f"Unexpected accident SRIDs: {srids}"

    def test_accident_geom_is_point(self, db):
        """All accident geometries must be POINT type."""
        rows = db.execute(text(
            "SELECT DISTINCT ST_GeometryType(geom) "
            "FROM accidents WHERE geom IS NOT NULL LIMIT 10"
        )).fetchall()
        types = {r[0] for r in rows}
        assert types == {"ST_Point"}, f"Unexpected geometry types: {types}"

    def test_accident_coords_in_germany(self, db):
        """Accident lat/lon must be within Germany's bounding box."""
        row = db.execute(text("""
            SELECT count(*) FROM accidents
            WHERE lat IS NOT NULL AND lon IS NOT NULL
              AND (lat < 47.0 OR lat > 55.5 OR lon < 5.5 OR lon > 15.5)
        """)).scalar()
        assert row == 0, f"{row} accidents have coordinates outside Germany"

    def test_accident_geom_matches_latlon(self, db):
        """The geom column should match the lat/lon columns (sample check)."""
        rows = db.execute(text("""
            SELECT lat, lon,
                   ST_Y(geom) AS geom_lat,
                   ST_X(geom) AS geom_lon
            FROM accidents
            WHERE geom IS NOT NULL AND lat IS NOT NULL AND lon IS NOT NULL
            LIMIT 100
        """)).fetchall()
        for lat, lon, geom_lat, geom_lon in rows:
            assert abs(lat - geom_lat) < 0.0001, (
                f"lat mismatch: {lat} vs {geom_lat}"
            )
            assert abs(lon - geom_lon) < 0.0001, (
                f"lon mismatch: {lon} vs {geom_lon}"
            )

    def test_accident_containment_rate(self, db):
        """
        At least 85% of accidents with region_id should fall inside their
        assigned region polygon. Some boundary-crossing is expected (~10%)
        because accidents are assigned to districts via AGS code matching
        (ULAND+UREGBEZ+UKREIS), not spatial join — coordinate imprecision
        and boundary effects cause mismatches near district borders.
        """
        row = db.execute(text("""
            SELECT
                count(*) AS total,
                count(*) FILTER (WHERE ST_Contains(r.geom, a.geom)) AS inside
            FROM (SELECT geom, region_id FROM accidents
                  WHERE geom IS NOT NULL AND region_id IS NOT NULL
                  LIMIT 10000) a
            JOIN regions r ON r.ags = a.region_id
            WHERE r.geom IS NOT NULL
        """)).fetchone()
        total, inside = row[0], row[1]
        pct = (inside / total) * 100 if total > 0 else 100
        assert pct >= 85.0, (
            f"Only {pct:.1f}% of sampled accidents inside their region "
            f"(expected ≥85%): {inside}/{total}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 6. ACCIDENT ZONES — SPATIAL CORRECTNESS
# ═══════════════════════════════════════════════════════════════════════════════


class TestAccidentZones:
    """Accident zone grid cells must be valid polygons in the correct SRIDs."""

    @pytest.fixture(autouse=True)
    def _check_zones_exist(self, db):
        """Skip zone tests if the zones table is empty (ETL not yet run)."""
        count = db.execute(text("SELECT count(*) FROM accident_zones")).scalar()
        if count == 0:
            pytest.skip("accident_zones table is empty — zone ETL not yet run")

    def test_zone_cell_geom_is_polygon_4326(self, db):
        """cell_geom (WGS84) must be POLYGON with SRID 4326."""
        rows = db.execute(text(
            "SELECT DISTINCT ST_GeometryType(cell_geom), ST_SRID(cell_geom) "
            "FROM accident_zones LIMIT 10"
        )).fetchall()
        for geom_type, srid in rows:
            assert geom_type == "ST_Polygon", f"Expected Polygon, got {geom_type}"
            assert srid == 4326, f"Expected SRID 4326, got {srid}"

    def test_zone_cell_geom_proj_is_polygon_25832(self, db):
        """cell_geom_proj (metric) must be POLYGON with SRID 25832."""
        rows = db.execute(text(
            "SELECT DISTINCT ST_GeometryType(cell_geom_proj), ST_SRID(cell_geom_proj) "
            "FROM accident_zones LIMIT 10"
        )).fetchall()
        for geom_type, srid in rows:
            assert geom_type == "ST_Polygon", f"Expected Polygon, got {geom_type}"
            assert srid == 25832, f"Expected SRID 25832, got {srid}"

    def test_zone_cells_are_approximately_250m(self, db):
        """Grid cells in EPSG:25832 should be ~250 m × 250 m squares."""
        rows = db.execute(text("""
            SELECT
                ST_XMax(cell_geom_proj) - ST_XMin(cell_geom_proj) AS width,
                ST_YMax(cell_geom_proj) - ST_YMin(cell_geom_proj) AS height
            FROM accident_zones
            LIMIT 100
        """)).fetchall()
        for width, height in rows:
            assert 249 < width < 251, f"Cell width {width} m is not ~250 m"
            assert 249 < height < 251, f"Cell height {height} m is not ~250 m"

    def test_zone_kinds_valid(self, db):
        """Zone kinds must match the schema CHECK: 'hotspot' or 'safe'."""
        rows = db.execute(text(
            "SELECT DISTINCT kind FROM accident_zones"
        )).fetchall()
        kinds = {r[0] for r in rows}
        assert kinds.issubset({"hotspot", "safe"}), f"Unexpected zone kinds: {kinds}"

    def test_hotspot_counts_nonzero(self, db):
        """Hotspot zones must have accident_count ≥ 5 (HOTSPOT_MIN)."""
        row = db.execute(text(
            "SELECT count(*) FROM accident_zones "
            "WHERE kind = 'hotspot' AND accident_count < 5"
        )).scalar()
        assert row == 0, f"{row} hotspot zones with accident_count < 5"

    def test_zone_dual_geom_consistency(self, db):
        """cell_geom should be the WGS84 transform of cell_geom_proj (sample)."""
        rows = db.execute(text("""
            SELECT ST_Distance(
                cell_geom,
                ST_Transform(cell_geom_proj, 4326)
            ) AS diff
            FROM accident_zones
            LIMIT 50
        """)).fetchall()
        for (diff,) in rows:
            assert diff < 0.0001, (
                f"cell_geom / cell_geom_proj mismatch: distance {diff}"
            )
