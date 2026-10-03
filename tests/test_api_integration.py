"""
Integration tests: API endpoints against the live SQL database.

Every test hits the real PostGIS database through FastAPI's TestClient.
Validates response structure, data correctness, filtering, and edge cases
for all 5 route modules: regions, accidents, aggregates, zones, metadata.
"""
import pytest
from datetime import date


# ═══════════════════════════════════════════════════════════════════════════════
# HELPER
# ═══════════════════════════════════════════════════════════════════════════════

def _assert_envelope(body: dict):
    """Assert the standard API envelope structure."""
    assert "results" in body, "Missing 'results' key in response"
    assert "metadata" in body, "Missing 'metadata' key in response"
    meta = body["metadata"]
    assert "sources_used" in meta, "Missing 'sources_used' in metadata"
    assert "licenses" in meta, "Missing 'licenses' in metadata"
    assert "snapshot_date" in meta, "Missing 'snapshot_date' in metadata"
    # Validate snapshot_date is a valid ISO date
    date.fromisoformat(meta["snapshot_date"])


# ═══════════════════════════════════════════════════════════════════════════════
# 1. HEALTH CHECK
# ═══════════════════════════════════════════════════════════════════════════════


class TestHealthEndpoints:
    """Health and metadata endpoints."""

    def test_healthz_ok(self, api_client):
        resp = api_client.get("/healthz")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["db"] == "ok"

    def test_data_quality_endpoint(self, api_client):
        resp = api_client.get("/healthz/data-quality")
        assert resp.status_code == 200
        body = resp.json()
        assert "status" in body


# ═══════════════════════════════════════════════════════════════════════════════
# 2. METADATA ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════


class TestMetadataEndpoints:

    def test_list_sources(self, api_client):
        resp = api_client.get("/metadata/sources")
        assert resp.status_code == 200
        body = resp.json()
        _assert_envelope(body)
        results = body["results"]
        assert len(results) >= 3, "Expected at least 3 data sources"
        names = {s["name"] for s in results}
        assert "unfallatlas" in names
        assert "regionalatlas" in names
        # Each source should have required fields
        for s in results:
            assert "id" in s
            assert "name" in s
            assert "license" in s

    def test_list_import_runs(self, api_client):
        resp = api_client.get("/import-runs")
        assert resp.status_code == 200
        body = resp.json()
        _assert_envelope(body)
        results = body["results"]
        assert len(results) > 0, "Expected at least one import run"
        for run in results:
            assert "id" in run
            assert "status" in run
            assert run["status"] in ("running", "success", "failed")


# ═══════════════════════════════════════════════════════════════════════════════
# 3. REGIONS ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════


class TestRegionsEndpoints:

    def test_list_all_regions(self, api_client):
        resp = api_client.get("/regions")
        assert resp.status_code == 200
        body = resp.json()
        _assert_envelope(body)
        assert len(body["results"]) > 100, "Expected many regions"

    @pytest.mark.parametrize("level,expected_count", [
        ("state", 16),
        ("district", 400),
    ])
    def test_filter_by_level(self, api_client, level, expected_count):
        resp = api_client.get(f"/regions?level={level}")
        assert resp.status_code == 200
        body = resp.json()
        results = body["results"]
        assert len(results) == expected_count, (
            f"Expected {expected_count} {level}s, got {len(results)}"
        )
        # All results should have the correct level
        for r in results:
            assert r["level"] == level

    def test_states_have_geometry(self, api_client):
        """GeoJSON geometry should be included in the response."""
        resp = api_client.get("/regions?level=state")
        body = resp.json()
        results = body["results"]
        geom_count = sum(1 for r in results if r.get("geom") is not None)
        assert geom_count == 16, f"Only {geom_count}/16 states have geometry"

    def test_state_geometry_is_valid_geojson(self, api_client):
        """Each geometry should be a valid GeoJSON object."""
        resp = api_client.get("/regions?level=state")
        body = resp.json()
        for r in body["results"]:
            geom = r.get("geom")
            if geom is not None:
                assert "type" in geom, f"Missing 'type' in geom for {r['ags']}"
                assert geom["type"] in ("Polygon", "MultiPolygon"), (
                    f"Unexpected geom type: {geom['type']}"
                )
                assert "coordinates" in geom
                assert len(geom["coordinates"]) > 0

    def test_get_region_by_ags(self, api_client):
        """GET /regions/01 should return Schleswig-Holstein."""
        resp = api_client.get("/regions/01")
        assert resp.status_code == 200
        body = resp.json()
        _assert_envelope(body)
        result = body["results"]
        assert result["ags"] == "01"
        assert result["name"] == "Schleswig-Holstein"
        assert result["level"] == "state"
        assert result["parent_ags"] is None  # states have no parent

    def test_get_district_by_ags(self, api_client):
        """GET /regions/01001 should return Flensburg."""
        resp = api_client.get("/regions/01001")
        assert resp.status_code == 200
        body = resp.json()
        result = body["results"]
        assert result["ags"] == "01001"
        assert result["name"] == "Flensburg"
        assert result["level"] == "district"
        assert result["parent_ags"] == "01"  # parent is SH

    def test_get_region_not_found(self, api_client):
        """Nonexistent AGS should return 404."""
        resp = api_client.get("/regions/99999")
        assert resp.status_code == 404

    def test_invalid_level_parameter(self, api_client):
        """Invalid level value should return 422."""
        resp = api_client.get("/regions?level=invalid")
        assert resp.status_code == 422

    def test_region_indicators(self, api_client):
        """GET /regions/01001/indicators should return time-series data."""
        resp = api_client.get("/regions/01001/indicators")
        assert resp.status_code == 200
        body = resp.json()
        _assert_envelope(body)
        results = body["results"]
        assert len(results) > 0, "Expected at least one indicator"
        # Should contain indicator names and values
        for ind in results:
            assert "name" in ind
            assert "values" in ind
            assert len(ind["values"]) > 0
            for v in ind["values"]:
                assert "year" in v
                assert "value" in v

    def test_region_indicators_not_found(self, api_client):
        """Indicators for nonexistent region should return 404."""
        resp = api_client.get("/regions/99999/indicators")
        assert resp.status_code == 404

    def test_ags_leading_zeros_preserved(self, api_client):
        """AGS codes with leading zeros must be preserved as TEXT."""
        resp = api_client.get("/regions?level=state")
        body = resp.json()
        ags_list = [r["ags"] for r in body["results"]]
        # AGS "01" should NOT become "1"
        assert "01" in ags_list, "Leading zero stripped from AGS '01'"
        assert "02" in ags_list, "Leading zero stripped from AGS '02'"
        # Check they're strings, not integers
        for ags in ags_list:
            assert isinstance(ags, str), f"AGS {ags} is not a string"


# ═══════════════════════════════════════════════════════════════════════════════
# 4. ACCIDENTS ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════


class TestAccidentsEndpoints:

    def test_list_accidents_basic(self, api_client):
        """Basic accident listing with limit."""
        resp = api_client.get("/accidents?limit=10")
        assert resp.status_code == 200
        body = resp.json()
        _assert_envelope(body)
        results = body["results"]
        assert len(results) == 10
        # Check required fields
        for acc in results:
            assert "accident_uid" in acc
            assert "year" in acc
            assert "lat" in acc
            assert "lon" in acc

    def test_filter_by_year(self, api_client):
        """Filter accidents by year."""
        resp = api_client.get("/accidents?year=2023&limit=5")
        assert resp.status_code == 200
        body = resp.json()
        for acc in body["results"]:
            assert acc["year"] == 2023

    def test_filter_by_state(self, api_client):
        """Filter accidents by state code (Berlin)."""
        resp = api_client.get("/accidents?state=BE&limit=10")
        assert resp.status_code == 200
        body = resp.json()
        results = body["results"]
        assert len(results) > 0, "Expected Berlin accidents"
        for acc in results:
            assert acc["region_id"] is not None
            assert acc["region_id"].startswith("11"), (
                f"Berlin accident has region_id {acc['region_id']}"
            )

    def test_filter_by_category(self, api_client):
        """Filter by accident category (1=fatal)."""
        resp = api_client.get("/accidents?category=1&limit=5")
        assert resp.status_code == 200
        body = resp.json()
        for acc in body["results"]:
            assert acc["category"] == 1

    def test_filter_by_participant_pedestrian(self, api_client):
        """Q5: Pedestrian accidents in Berlin 2023."""
        resp = api_client.get(
            "/accidents?state=BE&year=2023&participant=pedestrian&limit=20"
        )
        assert resp.status_code == 200
        body = resp.json()
        results = body["results"]
        assert len(results) > 0, "Expected pedestrian accidents in Berlin 2023"
        for acc in results:
            assert acc["participant_pedestrian"] is True
            assert acc["year"] == 2023
            assert acc["region_id"].startswith("11")

    def test_filter_by_participant_bike(self, api_client):
        """Filter by bicycle participant."""
        resp = api_client.get("/accidents?participant=bike&limit=5")
        assert resp.status_code == 200
        body = resp.json()
        for acc in body["results"]:
            assert acc["participant_bike"] is True

    def test_bbox_filter(self, api_client):
        """Filter by bounding box (central Berlin area)."""
        resp = api_client.get(
            "/accidents?lat_min=52.4&lat_max=52.6&lon_min=13.3&lon_max=13.5&limit=10"
        )
        assert resp.status_code == 200
        body = resp.json()
        results = body["results"]
        assert len(results) > 0
        for acc in results:
            assert 52.4 <= acc["lat"] <= 52.6
            assert 13.3 <= acc["lon"] <= 13.5

    def test_pagination_offset(self, api_client):
        """Pagination with offset should return different results."""
        resp1 = api_client.get("/accidents?limit=5&offset=0")
        resp2 = api_client.get("/accidents?limit=5&offset=5")
        assert resp1.status_code == 200
        assert resp2.status_code == 200
        uids1 = {a["accident_uid"] for a in resp1.json()["results"]}
        uids2 = {a["accident_uid"] for a in resp2.json()["results"]}
        assert uids1.isdisjoint(uids2), "Offset pages should have different records"

    def test_invalid_state_code(self, api_client):
        """Unknown state code should return 422, not a silent full scan."""
        resp = api_client.get("/accidents?state=XX")
        assert resp.status_code == 422

    def test_combined_filters(self, api_client):
        """Multiple filters combined: state + year + category."""
        resp = api_client.get("/accidents?state=SN&year=2023&category=2&limit=10")
        assert resp.status_code == 200
        body = resp.json()
        for acc in body["results"]:
            assert acc["year"] == 2023
            assert acc["category"] == 2
            assert acc["region_id"].startswith("14")

    def test_metadata_includes_total_count(self, api_client):
        """Metadata should include total_count and offset."""
        resp = api_client.get("/accidents?limit=3")
        assert resp.status_code == 200
        meta = resp.json()["metadata"]
        assert "total_count" in meta
        assert "offset" in meta
        assert isinstance(meta["total_count"], int) and meta["total_count"] >= 0


# ═══════════════════════════════════════════════════════════════════════════════
# 5. AGGREGATES ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════


class TestAggregatesEndpoints:

    def test_q1_earliest_year_national(self, api_client):
        """Q1: What is the earliest year of accident data nationally?"""
        resp = api_client.get("/aggregates/accidents?aggregate=earliest_year")
        assert resp.status_code == 200
        body = resp.json()
        _assert_envelope(body)
        result = body["results"]
        assert "earliest_year" in result
        assert result["earliest_year"] == 2016  # Unfallatlas starts at 2016

    def test_q2_count_by_state_year_category(self, api_client):
        """Q2: Accident count for Saxony (SN) in 2023, category 2 (serious)."""
        resp = api_client.get(
            "/aggregates/accidents?state=SN&year=2023&category=2"
        )
        assert resp.status_code == 200
        body = resp.json()
        _assert_envelope(body)
        results = body["results"]
        assert len(results) > 0
        total = body["metadata"]["total_count"]
        assert total > 0, "Expected some serious injuries in Saxony 2023"
        # All results should be for Saxony (region starts with 14)
        for r in results:
            assert r["region_id"].startswith("14")

    def test_q3_earliest_year_nrw(self, api_client):
        """Q3: Earliest year for Nordrhein-Westfalen (NW)."""
        resp = api_client.get(
            "/aggregates/accidents?state=NW&aggregate=earliest_year"
        )
        assert resp.status_code == 200
        body = resp.json()
        result = body["results"]
        assert result["earliest_year"] is not None
        assert 2016 <= result["earliest_year"] <= 2024

    def test_q4_earliest_year_mv(self, api_client):
        """Q4: Earliest year for Mecklenburg-Vorpommern (MV)."""
        resp = api_client.get(
            "/aggregates/accidents?state=MV&aggregate=earliest_year"
        )
        assert resp.status_code == 200
        body = resp.json()
        result = body["results"]
        assert result["earliest_year"] is not None
        assert 2016 <= result["earliest_year"] <= 2024

    def test_aggregate_count_by_level(self, api_client):
        """Aggregate count grouped by district level."""
        resp = api_client.get(
            "/aggregates/accidents?level=district&year=2023&state=SH"
        )
        assert resp.status_code == 200
        body = resp.json()
        results = body["results"]
        assert len(results) > 0
        # Should include region_name when level is specified
        for r in results:
            assert "region_name" in r
            assert "accident_count" in r
            assert r["accident_count"] > 0

    def test_invalid_state_returns_422(self, api_client):
        """Unknown state code should return 422."""
        resp = api_client.get("/aggregates/accidents?state=XX")
        assert resp.status_code == 422

    def test_invalid_aggregate_returns_422(self, api_client):
        """Invalid aggregate parameter should return 422."""
        resp = api_client.get("/aggregates/accidents?aggregate=bogus")
        assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════════════════════════
# 6. ACCIDENT RATE ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════


class TestAccidentRateEndpoints:

    def test_q6_rate_by_cars_district(self, api_client):
        """Q6: Accident rate per 100k cars by district for 2023."""
        resp = api_client.get(
            "/aggregates/accident-rate?denominator=cars_pkw&year=2023&level=district"
        )
        assert resp.status_code == 200
        body = resp.json()
        _assert_envelope(body)
        results = body["results"]
        assert len(results) > 0
        meta = body["metadata"]
        assert meta["denominator"] == "cars_pkw"
        # Rates should be non-negative
        for r in results:
            assert "rate_per_100k" in r
            assert "ags" in r
            assert "name" in r
            if r["rate_per_100k"] is not None:
                assert r["rate_per_100k"] >= 0

    def test_rate_by_population(self, api_client):
        """Accident rate per 100k population."""
        resp = api_client.get(
            "/aggregates/accident-rate?denominator=population&year=2023&level=district"
        )
        assert resp.status_code == 200
        body = resp.json()
        results = body["results"]
        assert len(results) > 0
        for r in results:
            if r["rate_per_100k"] is not None:
                assert r["rate_per_100k"] >= 0
                # Sanity: rate shouldn't be astronomically high
                assert r["rate_per_100k"] < 100000

    def test_rate_filter_by_state(self, api_client):
        """Filter accident rate by state."""
        resp = api_client.get(
            "/aggregates/accident-rate?state=BY&level=district&year=2023"
        )
        assert resp.status_code == 200
        body = resp.json()
        results = body["results"]
        assert len(results) > 0
        # All should be Bavaria districts (09xxx)
        for r in results:
            assert r["ags"].startswith("09"), (
                f"Non-Bavaria district in BY filter: {r['ags']}"
            )


# ═══════════════════════════════════════════════════════════════════════════════
# 7. ACCIDENT RATE TOP-N ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════


class TestAccidentRateTopEndpoints:

    def test_q7_top5_fatal_by_population(self, api_client):
        """Q7: Top 5 districts by fatal accident rate, population ≥50k."""
        resp = api_client.get(
            "/aggregates/accident-rate/top"
            "?level=district&year=2024&severity=fatal"
            "&denominator=population&limit=5&min_population=50000"
        )
        assert resp.status_code == 200
        body = resp.json()
        _assert_envelope(body)
        results = body["results"]
        assert len(results) <= 5
        # Check ranking
        for i, r in enumerate(results):
            assert r["rank"] == i + 1
            assert "ags" in r
            assert "name" in r
            assert "accident_count" in r
            assert "population" in r
            assert r["population"] >= 50000
            assert "rate_per_100k" in r

    def test_top_rates_descending(self, api_client):
        """Top-N results should be sorted by rate descending."""
        resp = api_client.get(
            "/aggregates/accident-rate/top?level=district&limit=10"
        )
        assert resp.status_code == 200
        results = resp.json()["results"]
        rates = [
            r["rate_per_100k"] for r in results
            if r["rate_per_100k"] is not None
        ]
        assert rates == sorted(rates, reverse=True), "Rates not sorted descending"

    def test_top_with_severity_filter(self, api_client):
        """Top-N with severity=serious should filter correctly."""
        resp = api_client.get(
            "/aggregates/accident-rate/top?severity=serious&limit=3"
        )
        assert resp.status_code == 200
        results = resp.json()["results"]
        assert len(results) <= 3

    def test_top_state_level(self, api_client):
        """Top-N at state level."""
        resp = api_client.get(
            "/aggregates/accident-rate/top?level=state&limit=5"
        )
        assert resp.status_code == 200
        results = resp.json()["results"]
        assert len(results) <= 5


# ═══════════════════════════════════════════════════════════════════════════════
# 8. ZERO-ACCIDENT REGIONS
# ═══════════════════════════════════════════════════════════════════════════════


class TestZeroAccidentRegions:

    def test_zero_accident_municipalities(self, api_client):
        """There should be some municipalities with zero accidents."""
        resp = api_client.get("/aggregates/zero-accident-regions?level=municipality")
        assert resp.status_code == 200
        body = resp.json()
        _assert_envelope(body)
        results = body["results"]
        meta = body["metadata"]
        assert "total_regions" in meta
        # Some municipalities should have zero accidents
        assert len(results) > 0, "Expected some zero-accident municipalities"

    def test_zero_accident_by_state(self, api_client):
        """Filter zero-accident regions by state."""
        resp = api_client.get(
            "/aggregates/zero-accident-regions?level=municipality&state=SN"
        )
        assert resp.status_code == 200
        body = resp.json()
        results = body["results"]
        for r in results:
            assert "ags" in r
            assert "name" in r

    def test_zero_accident_by_year(self, api_client):
        """Filter zero-accident regions by year."""
        resp = api_client.get(
            "/aggregates/zero-accident-regions?level=municipality&year=2023"
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["results"]) >= 0  # could be empty or populated


# ═══════════════════════════════════════════════════════════════════════════════
# 9. ZONES ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════


class TestZonesEndpoints:
    """Tests for /zones/nearest, /zones/around endpoints."""

    # Central Berlin coordinates for testing
    LAT = 52.52
    LON = 13.405

    @pytest.fixture(autouse=True)
    def _check_zones_exist(self, api_client):
        """Skip zone API tests if no zones computed yet."""
        # Quick DB check via the around endpoint
        resp = api_client.get(f"/zones/around?lat={self.LAT}&lon={self.LON}")
        body = resp.json()
        results = body.get("results", {})
        hotspots = results.get("hotspots", [])
        if len(hotspots) == 0:
            pytest.skip("No accident zones computed — zone ETL not yet run")

    def test_nearest_hotspots(self, api_client):
        """GET /zones/nearest should return nearby hotspot zones."""
        resp = api_client.get(
            f"/zones/nearest?lat={self.LAT}&lon={self.LON}&type=hotspot&limit=5"
        )
        assert resp.status_code == 200
        body = resp.json()
        _assert_envelope(body)
        results = body["results"]
        assert len(results) <= 5
        for zone in results:
            assert zone["kind"] == "hotspot"
            assert zone["accident_count"] >= 5
            assert "cell_geom" in zone
            assert "distance_m" in zone
            assert zone["distance_m"] >= 0

    def test_nearest_distances_ascending(self, api_client):
        """Nearest zones should be sorted by distance ascending."""
        resp = api_client.get(
            f"/zones/nearest?lat={self.LAT}&lon={self.LON}&type=hotspot&limit=10"
        )
        assert resp.status_code == 200
        results = resp.json()["results"]
        distances = [z["distance_m"] for z in results]
        assert distances == sorted(distances), "Distances not in ascending order"

    def test_zones_around(self, api_client):
        """GET /zones/around returns hotspots and your_zone."""
        resp = api_client.get(f"/zones/around?lat={self.LAT}&lon={self.LON}")
        assert resp.status_code == 200
        body = resp.json()
        _assert_envelope(body)
        results = body["results"]
        assert "hotspots" in results
        assert "your_zone" in results

    def test_zone_cell_geom_is_geojson(self, api_client):
        """Zone cell_geom should be valid GeoJSON polygon."""
        resp = api_client.get(
            f"/zones/nearest?lat={self.LAT}&lon={self.LON}&type=hotspot&limit=1"
        )
        assert resp.status_code == 200
        results = resp.json()["results"]
        if results:
            geom = results[0]["cell_geom"]
            assert geom["type"] == "Polygon"
            assert "coordinates" in geom
            coords = geom["coordinates"][0]  # exterior ring
            # Polygon ring should have at least 4 points (closed)
            assert len(coords) >= 4
            # First and last point should be the same (closed ring)
            assert coords[0] == coords[-1], "Ring not closed"

    def test_nearest_lat_lon_validation(self, api_client):
        """Lat/lon outside Germany bbox should return 422."""
        resp = api_client.get("/zones/nearest?lat=0&lon=0&type=hotspot")
        assert resp.status_code == 422

    def test_nearest_with_year_filter(self, api_client):
        """Zone nearest with year filter."""
        resp = api_client.get(
            f"/zones/nearest?lat={self.LAT}&lon={self.LON}&type=hotspot&year=2023"
        )
        assert resp.status_code == 200
        body = resp.json()
        for zone in body["results"]:
            assert zone["year_from"] <= 2023 <= zone["year_to"]


# ═══════════════════════════════════════════════════════════════════════════════
# 10. CROSS-CUTTING CONCERNS
# ═══════════════════════════════════════════════════════════════════════════════


class TestCrossCuttingConcerns:
    """Tests for behaviors that span multiple endpoints."""

    def test_all_responses_have_license(self, api_client):
        """Every envelope response must include dl-de/by-2-0 license."""
        endpoints = [
            "/regions?level=state",
            "/regions/01",
            "/accidents?limit=1",
            "/aggregates/accidents?aggregate=earliest_year",
            "/metadata/sources",
        ]
        for ep in endpoints:
            resp = api_client.get(ep)
            assert resp.status_code == 200, f"Failed: {ep}"
            body = resp.json()
            if "metadata" in body and "licenses" in body["metadata"]:
                assert "dl-de/by-2-0" in body["metadata"]["licenses"], (
                    f"Missing license in {ep}"
                )

    def test_cors_headers(self, api_client):
        """CORS headers should be present for allowed origins."""
        resp = api_client.get(
            "/healthz",
            headers={"Origin": "http://localhost:3000"},
        )
        assert resp.status_code == 200
        assert "access-control-allow-origin" in resp.headers

    def test_nonexistent_endpoint_returns_404(self, api_client):
        """Requests to undefined paths should return 404."""
        resp = api_client.get("/nonexistent/path")
        assert resp.status_code in (404, 405)

    def test_accident_uid_uniqueness(self, api_client):
        """Accident UIDs in a response should be unique."""
        resp = api_client.get("/accidents?limit=100")
        assert resp.status_code == 200
        uids = [a["accident_uid"] for a in resp.json()["results"]]
        assert len(uids) == len(set(uids)), "Duplicate accident UIDs in response"

    def test_state_codes_all_valid(self, api_client):
        """All 16 German state codes should resolve correctly."""
        state_codes = [
            "SH", "HH", "NI", "HB", "NW", "HE", "RP", "BW",
            "BY", "SL", "BE", "BB", "MV", "SN", "ST", "TH",
        ]
        for code in state_codes:
            resp = api_client.get(
                f"/aggregates/accidents?state={code}&aggregate=earliest_year"
            )
            assert resp.status_code == 200, f"State code {code} failed"
            result = resp.json()["results"]
            assert result["earliest_year"] is not None, (
                f"No data for state {code}"
            )


class TestNearbyHazards:
    """Tests for GET /zones/nearby-hazards."""

    LAT = 52.52
    LON = 13.405

    @pytest.fixture(autouse=True)
    def _check_zones_exist(self, api_client):
        resp = api_client.get(f"/zones/around?lat={self.LAT}&lon={self.LON}")
        body = resp.json()
        results = body.get("results", {})
        if len(results.get("hotspots", [])) == 0:
            pytest.skip("No accident zones computed — zone ETL not yet run")

    def test_nearby_hazards_returns_200(self, api_client):
        """GET /zones/nearby-hazards returns 200 with envelope."""
        resp = api_client.get(
            f"/zones/nearby-hazards?lat={self.LAT}&lon={self.LON}"
        )
        assert resp.status_code == 200
        body = resp.json()
        _assert_envelope(body)

    def test_nearby_hazards_result_count(self, api_client):
        """Result count is at most 5."""
        resp = api_client.get(
            f"/zones/nearby-hazards?lat={self.LAT}&lon={self.LON}"
        )
        results = resp.json()["results"]
        assert len(results) <= 5

    def test_nearby_hazards_all_hotspots(self, api_client):
        """All returned zones are kind='hotspot'."""
        resp = api_client.get(
            f"/zones/nearby-hazards?lat={self.LAT}&lon={self.LON}"
        )
        for zone in resp.json()["results"]:
            assert zone["kind"] == "hotspot"

    def test_nearby_hazards_within_radius(self, api_client):
        """All returned zones are within 10 km."""
        resp = api_client.get(
            f"/zones/nearby-hazards?lat={self.LAT}&lon={self.LON}"
        )
        for zone in resp.json()["results"]:
            assert zone["distance_m"] <= 10000.0

    def test_nearby_hazards_lat_out_of_bounds(self, api_client):
        """lat outside Germany → 422."""
        resp = api_client.get("/zones/nearby-hazards?lat=0&lon=13.40")
        assert resp.status_code == 422

    def test_nearby_hazards_lon_out_of_bounds(self, api_client):
        """lon outside Germany → 422."""
        resp = api_client.get("/zones/nearby-hazards?lat=52.52&lon=0")
        assert resp.status_code == 422
