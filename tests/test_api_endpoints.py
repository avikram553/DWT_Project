import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch


@pytest.fixture
def client():
    from api.main import app
    return TestClient(app)


def _make_mock_region(ags="01", name="Schleswig-Holstein", level="state", parent=None):
    r = MagicMock()
    r.ags = ags
    r.name = name
    r.level = level
    r.parent_ags = parent
    r.population_latest = 2910875
    return r


def test_list_regions_returns_envelope(client):
    from api.main import app
    from api.db import get_db

    mock_regions = [_make_mock_region()]
    mock_db = MagicMock()
    mock_db.execute.return_value.scalars.return_value.all.return_value = mock_regions

    def override_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        resp = client.get("/regions?level=state")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    body = resp.json()
    assert "results" in body
    assert "metadata" in body
    assert "sources_used" in body["metadata"]


def test_get_region_not_found(client):
    from api.main import app
    from api.db import get_db

    mock_db = MagicMock()
    mock_db.execute.return_value.scalar_one_or_none.return_value = None

    def override_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        resp = client.get("/regions/99999")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 404


def test_list_regions_level_validation(client):
    resp = client.get("/regions?level=invalid")
    assert resp.status_code == 422
