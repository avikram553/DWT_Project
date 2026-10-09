# Nearby Hazards Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "📍 Nearby Hazards" button that fetches the user's GPS location, queries a new `/zones/nearby-hazards` endpoint, and renders up to 5 pulsing red markers on the Leaflet map for accident hotspots within 500 m.

**Architecture:** New dedicated FastAPI route in `api/routes/zones.py` runs a single KNN + ST_DWithin(500) PostGIS query — no post-filtering in Python. Frontend wires geolocation → fetch → Leaflet `L.divIcon` markers in a new `layers.hazards` layer group. Clicking a marker opens the existing insight panel via `openInsightPanel()`.

**Tech Stack:** FastAPI + SQLAlchemy (text queries), PostGIS (`<->` KNN, `ST_DWithin`), Leaflet `L.divIcon`, CSS `@keyframes`, vanilla JS (`navigator.geolocation`)

## Global Constraints

- AGS codes are always TEXT — never cast to integer
- Germany bounding-box validation on every lat/lon param: `lat ge=47.27 le=55.06`, `lon ge=5.87 le=15.04` — return 422 on violation (FastAPI Query)
- All SQL params bound via SQLAlchemy `:name` placeholders — never interpolate user input into SQL strings
- No new libraries — Leaflet and existing vendor scripts only
- Match existing code style: `_row_to_dict()` pattern, `envelope()` wrapper, `apiFetch()` helper

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `api/routes/zones.py` | Modify | Add `_NEARBY_HAZARDS_SQL` constant + `nearby_hazards()` route |
| `tests/test_api_integration.py` | Modify | Add `TestNearbyHazards` class |
| `frontend/style.css` | Modify | Add `.hazard-marker` + `@keyframes hotspotPulse` + `.hazard-toast` + `.lp-hazard-btn` |
| `frontend/index.html` | Modify | Add "📍 Nearby Hazards" button row in left panel |
| `frontend/app.js` | Modify | Add `layers.hazards`, `cellCentroid()`, `showToast()`, `loadNearbyHazards()`, `showInsightHazard()`, `wireNearbyHazards()` |

---

### Task 1: Backend endpoint + tests

**Files:**
- Modify: `api/routes/zones.py`
- Modify: `tests/test_api_integration.py`

**Interfaces:**
- Produces: `GET /zones/nearby-hazards?lat=<float>&lon=<float>` → `{"results": [...], "metadata": {...}}`
- Each result item: `{"kind": "hotspot", "accident_count": int, "year_from": int, "year_to": int, "region_id": str, "region_name": str, "cell_geom": {...GeoJSON Polygon...}, "distance_m": float}`

- [ ] **Step 1: Write the failing tests**

Append this class to `tests/test_api_integration.py` after the existing `TestZonesEndpoints` class:

```python
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
        """All returned zones are within 500 m."""
        resp = api_client.get(
            f"/zones/nearby-hazards?lat={self.LAT}&lon={self.LON}"
        )
        for zone in resp.json()["results"]:
            assert zone["distance_m"] <= 500.0

    def test_nearby_hazards_lat_out_of_bounds(self, api_client):
        """lat outside Germany → 422."""
        resp = api_client.get("/zones/nearby-hazards?lat=0&lon=13.40")
        assert resp.status_code == 422

    def test_nearby_hazards_lon_out_of_bounds(self, api_client):
        """lon outside Germany → 422."""
        resp = api_client.get("/zones/nearby-hazards?lat=52.52&lon=0")
        assert resp.status_code == 422
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /Users/adityavikram/Desktop/DevRepo/DWT_Project
source .venv/bin/activate
pytest tests/test_api_integration.py::TestNearbyHazards -v 2>&1 | head -30
```

Expected: `ERRORS` or `FAILED` — route does not exist yet, 404s or attribute errors.

- [ ] **Step 3: Add SQL constant to `api/routes/zones.py`**

Add this block after the `_YOUR_ZONE_SQL` definition (after line 69, before `_row_to_dict`):

```python
_NEARBY_HAZARDS_SQL = text("""
    SELECT az.kind,
           az.accident_count,
           az.year_from,
           az.year_to,
           az.region_id,
           r.name AS region_name,
           ST_AsGeoJSON(az.cell_geom)::json AS cell_geom,
           ST_Distance(
               az.cell_geom_proj,
               ST_Transform(ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), 25832)
           ) AS distance_m
    FROM accident_zones az
    LEFT JOIN regions r ON r.ags = az.region_id
    WHERE az.kind = 'hotspot'
      AND ST_DWithin(
          az.cell_geom_proj,
          ST_Transform(ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), 25832),
          500
      )
    ORDER BY az.cell_geom_proj
          <-> ST_Transform(ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), 25832)
    LIMIT 5
""")
```

- [ ] **Step 4: Add the route function to `api/routes/zones.py`**

Append at the end of the file:

```python
@router.get("/nearby-hazards")
def nearby_hazards(
    lat: float = Query(..., ge=47.27, le=55.06),
    lon: float = Query(..., ge=5.87, le=15.04),
    db: Session = Depends(get_db),
):
    rows = db.execute(
        _NEARBY_HAZARDS_SQL, {"lat": lat, "lon": lon}
    ).fetchall()

    return envelope(
        [_row_to_dict(r) for r in rows],
        sources_used=["unfallatlas"],
        extra_meta={"lat": lat, "lon": lon, "radius_m": 500},
    )
```

- [ ] **Step 5: Run tests to confirm they pass**

```bash
pytest tests/test_api_integration.py::TestNearbyHazards -v
```

Expected (when zone ETL has been run):
```
PASSED tests/test_api_integration.py::TestNearbyHazards::test_nearby_hazards_returns_200
PASSED tests/test_api_integration.py::TestNearbyHazards::test_nearby_hazards_result_count
PASSED tests/test_api_integration.py::TestNearbyHazards::test_nearby_hazards_all_hotspots
PASSED tests/test_api_integration.py::TestNearbyHazards::test_nearby_hazards_within_radius
PASSED tests/test_api_integration.py::TestNearbyHazards::test_nearby_hazards_lat_out_of_bounds
PASSED tests/test_api_integration.py::TestNearbyHazards::test_nearby_hazards_lon_out_of_bounds
```

If zone ETL not run: zone-dependent tests SKIP, bounds tests PASS.

- [ ] **Step 6: Commit**

```bash
git add api/routes/zones.py tests/test_api_integration.py
git commit -m "feat: add GET /zones/nearby-hazards endpoint (KNN + 500m radius)"
```

---

### Task 2: CSS — pulse animation, marker, toast, button

**Files:**
- Modify: `frontend/style.css` (append after line 430, the current last line)

**Interfaces:**
- Produces: `.hazard-marker` (used by `L.divIcon` html in Task 4), `.lp-hazard-btn` (used by HTML in Task 3), `.hazard-toast` + `.hazard-toast--visible` (used by `showToast()` in Task 4)

- [ ] **Step 1: Append styles to `frontend/style.css`**

Add to the **end** of `frontend/style.css`:

```css
/* ── Nearby Hazards ── */
@keyframes hotspotPulse {
  0%   { box-shadow: 0 0 0 0 rgba(239,68,68,0.8); }
  70%  { box-shadow: 0 0 0 14px rgba(239,68,68,0); }
  100% { box-shadow: 0 0 0 0 rgba(239,68,68,0); }
}

.hazard-marker {
  width: 20px; height: 20px; border-radius: 50%;
  background: var(--accent-red);
  border: 2px solid rgba(255,255,255,0.3);
  animation: hotspotPulse 1.5s ease-in-out infinite;
  cursor: pointer;
}

.lp-hazard-btn {
  width: 100%; padding: 8px 10px; border-radius: 8px;
  background: rgba(239,68,68,0.12);
  border: 1px solid rgba(239,68,68,0.35);
  color: var(--accent-red); font-size: 12px; font-weight: 600;
  cursor: pointer; text-align: center;
  transition: background 150ms, border-color 150ms;
}
.lp-hazard-btn:hover { background: rgba(239,68,68,0.22); border-color: var(--accent-red); }
.lp-hazard-btn:disabled { opacity: 0.5; pointer-events: none; }

.hazard-toast {
  position: fixed; bottom: 90px; left: 50%; transform: translateX(-50%);
  background: rgba(17,24,39,0.95);
  border: 1px solid var(--border-default);
  border-radius: 8px; padding: 10px 16px;
  font-size: 13px; color: var(--text-primary);
  z-index: 2000; opacity: 0;
  transition: opacity 250ms; pointer-events: none;
  white-space: nowrap;
}
.hazard-toast--visible { opacity: 1; }
```

- [ ] **Step 2: Commit**

```bash
git add frontend/style.css
git commit -m "feat: add hazard marker pulse animation, button, and toast styles"
```

---

### Task 3: HTML — Nearby Hazards button

**Files:**
- Modify: `frontend/index.html`

**Interfaces:**
- Produces: `<button id="btn-nearby-hazards" class="lp-hazard-btn">` — event listener attached by `wireNearbyHazards()` in Task 4

- [ ] **Step 1: Add button row to left panel**

In `frontend/index.html`, find this block (around line 100):

```html
  <div class="lp-divider"></div>

  <!-- Queries -->
  <div id="lp-queries">
```

Replace it with:

```html
  <div class="lp-divider"></div>

  <!-- Nearby Hazards -->
  <div class="lp-row">
    <button id="btn-nearby-hazards" class="lp-hazard-btn">📍 Nearby Hazards</button>
  </div>

  <div class="lp-divider"></div>

  <!-- Queries -->
  <div id="lp-queries">
```

- [ ] **Step 2: Visual check**

Open `frontend/index.html` in a browser. The left panel should show a red-tinted "📍 Nearby Hazards" button between the city jump dropdown and the query cards. Button click does nothing yet (JS not wired).

- [ ] **Step 3: Commit**

```bash
git add frontend/index.html
git commit -m "feat: add Nearby Hazards button to left panel"
```

---

### Task 4: JS — geolocation, markers, insight panel

**Files:**
- Modify: `frontend/app.js`

**Interfaces:**
- Consumes:
  - `layers` object (defined ~line 89): extend with `hazards: L.layerGroup().addTo(map)`
  - `apiFetch(path: string): Promise<{results: any[], metadata: object}>` (~line 99)
  - `openInsightPanel(html: string): void` (~line 637)
  - `GET /zones/nearby-hazards?lat=&lon=` from Task 1
  - CSS classes `.hazard-marker`, `.hazard-toast`, `.hazard-toast--visible`, `.lp-hazard-btn` from Task 2
  - `#btn-nearby-hazards` DOM element from Task 3
- Produces: `wireNearbyHazards()` — called during init

- [ ] **Step 1: Add `hazards` to the `layers` object**

In `frontend/app.js`, find the `layers` object (around line 89):

```javascript
const layers = {
  choropleth:     L.layerGroup().addTo(map),
  municipalities: L.layerGroup(),
  stateBoundary:  L.layerGroup().addTo(map),
  accidents:      L.layerGroup().addTo(map),
};
```

Change it to:

```javascript
const layers = {
  choropleth:     L.layerGroup().addTo(map),
  municipalities: L.layerGroup(),
  stateBoundary:  L.layerGroup().addTo(map),
  accidents:      L.layerGroup().addTo(map),
  hazards:        L.layerGroup().addTo(map),
};
```

- [ ] **Step 2: Add the nearby hazards functions**

Append the following block to `frontend/app.js`, just **before** the `// ── Init ──` comment (around line 731):

```javascript
// ── Nearby Hazards ─────────────────────────────────────────────────────────
function cellCentroid(cellGeom) {
  const ring = cellGeom.coordinates[0];
  const lon = ring.reduce((s, p) => s + p[0], 0) / ring.length;
  const lat = ring.reduce((s, p) => s + p[1], 0) / ring.length;
  return [lat, lon];
}

function showToast(msg) {
  let el = document.getElementById('hazard-toast');
  if (!el) {
    el = document.createElement('div');
    el.id = 'hazard-toast';
    el.className = 'hazard-toast';
    document.body.appendChild(el);
  }
  el.textContent = msg;
  el.classList.add('hazard-toast--visible');
  setTimeout(() => el.classList.remove('hazard-toast--visible'), 3000);
}

function showInsightHazard(zone) {
  openInsightPanel(`
    <div class="insight-title">⚠️ Accident Hotspot</div>
    <div class="insight-subtitle">${zone.region_name || 'Unknown area'}</div>
    <div class="insight-stat">
      <span>Accidents (2022–2024)</span>
      <span class="insight-stat-val">${zone.accident_count}</span>
    </div>
    <div class="insight-stat">
      <span>Distance from you</span>
      <span class="insight-stat-val">${zone.distance_m} m</span>
    </div>
    <div style="margin-top:16px;font-size:12px;color:#EF4444">
      Be careful in this area.
    </div>
  `);
}

async function loadNearbyHazards() {
  const btn = document.getElementById('btn-nearby-hazards');
  btn.textContent = 'Loading…';
  btn.disabled = true;
  layers.hazards.clearLayers();

  if (!navigator.geolocation) {
    showToast('Geolocation not supported by your browser.');
    btn.textContent = '📍 Nearby Hazards';
    btn.disabled = false;
    return;
  }

  navigator.geolocation.getCurrentPosition(
    async (pos) => {
      const lat = pos.coords.latitude;
      const lon = pos.coords.longitude;
      try {
        const res = await apiFetch(`/zones/nearby-hazards?lat=${lat}&lon=${lon}`);
        const zones = res.results || [];
        if (zones.length === 0) {
          showToast('No accident hotspots within 500 m of your location.');
        } else {
          map.flyTo([lat, lon], 15, { duration: 1.2 });
          for (const zone of zones) {
            const [clat, clon] = cellCentroid(zone.cell_geom);
            const marker = L.marker([clat, clon], {
              icon: L.divIcon({
                className: '',
                html: '<div class="hazard-marker"></div>',
                iconSize: [20, 20],
                iconAnchor: [10, 10],
              }),
            });
            marker.on('click', () => showInsightHazard(zone));
            marker.addTo(layers.hazards);
          }
        }
      } catch {
        showToast('Could not load nearby hazards.');
      }
      btn.textContent = '📍 Nearby Hazards';
      btn.disabled = false;
    },
    () => {
      showToast('Location access denied — allow location in your browser.');
      btn.textContent = '📍 Nearby Hazards';
      btn.disabled = false;
    }
  );
}

function wireNearbyHazards() {
  document.getElementById('btn-nearby-hazards')
    .addEventListener('click', loadNearbyHazards);
}
```

- [ ] **Step 3: Call `wireNearbyHazards()` in the init block**

In `frontend/app.js`, find the init section at the bottom where `wirePanelA()` and `wireLeftPanel()` are called. Add `wireNearbyHazards()` immediately after `wireLeftPanel()`:

```javascript
wirePanelA();
wireLeftPanel();
wireNearbyHazards();
```

- [ ] **Step 4: Manual verification**

Start the API:
```bash
cd /Users/adityavikram/Desktop/DevRepo/DWT_Project
source .venv/bin/activate
uvicorn api.main:app --reload
```

Open `frontend/index.html` via a local static server (e.g. `python -m http.server 3000` in the `frontend/` dir). Check:

1. "📍 Nearby Hazards" button visible in left panel with red tint
2. Button click → browser shows geolocation permission prompt
3. On grant (location must be in Germany): map flies to location, up to 5 pulsing red markers appear
4. Marker click → insight panel opens with "⚠️ Accident Hotspot", accident count, distance, "Be careful in this area."
5. Button re-click → old markers clear, new fetch starts
6. Deny geolocation → toast: "Location access denied — allow location in your browser."
7. Location outside Germany → toast: "Could not load nearby hazards." (API returns 422, caught by catch block)

- [ ] **Step 5: Commit**

```bash
git add frontend/app.js
git commit -m "feat: wire Nearby Hazards geolocation, pulsing markers, and insight panel"
```
