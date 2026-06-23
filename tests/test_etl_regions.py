import json
import pytest


def test_extract_ags_state():
    from etl.regions import extract_ags
    props = {"RS": "010000000000"}
    assert extract_ags(props, "state") == "01"


def test_extract_ags_district():
    from etl.regions import extract_ags
    props = {"RS": "010010000000"}
    assert extract_ags(props, "district") == "01001"


def test_extract_ags_municipality():
    from etl.regions import extract_ags
    props = {"RS": "010010000000"}
    assert extract_ags(props, "municipality") == "01001000"


def test_extract_ags_strips_leading_zeros_preserved():
    from etl.regions import extract_ags
    props = {"RS": "140000000000"}
    result = extract_ags(props, "state")
    assert result == "14"
    assert isinstance(result, str)


def test_reproject_point():
    from etl.regions import reproject_coords
    lon, lat = reproject_coords(537000, 6090000)
    assert 9.0 < lon < 10.0
    assert 54.5 < lat < 55.1


def test_parent_ags_state():
    from etl.regions import parent_ags_for
    assert parent_ags_for("01", "state") is None


def test_parent_ags_district():
    from etl.regions import parent_ags_for
    assert parent_ags_for("01001", "district") == "01"


def test_parent_ags_municipality():
    from etl.regions import parent_ags_for
    assert parent_ags_for("01001000", "municipality") == "01001"
