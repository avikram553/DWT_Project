# Nearby Hazards Feature — Design Spec

**Date:** 2026-06-25  
**Status:** Approved

---

## Summary

User clicks a "📍 Nearby Hazards" button. The browser requests GPS location, sends it to a new dedicated backend endpoint, and displays the top 5 accident hotspots within 5 km as pulsing red markers on the Leaflet map. Clicking a marker opens the existing insight panel with hazard details.

---

## 1. Backend

### New endpoint

```
GET /zones/nearby-hazards?lat=<float>&lon=<float>
```

**Location:** `api/routes/zones.py` (new route alongside existing zone routes)

**Fixed parameters (not exposed to caller):**
- `kind = 'hotspot'`
- `limit = 5`
- `radius = 500` m

**SQL strategy:**
- KNN operator `<->` on `cell_geom_proj` (EPSG:25832) for ordering by distance
- `ST_DWithin(az.cell_geom_proj, user_point_proj, 500)` as the radius cutoff
- Both conditions in one query — no post-filter in Python

**Validation:**
- `lat`: `ge=47.27, le=55.06` (Germany bounding box)
- `lon`: `ge=5.87, le=15.04`
- Returns 422 if out of bounds (FastAPI Query validation, same as existing routes)

**Response shape:** Same envelope format as `/zones/nearest`:
```json
{
  "results": [
    {
      "kind": "hotspot",
      "accident_count": 12,
      "year_from": 2022,
      "year_to": 2024,
      "region_id": "11000",
      "region_name": "Berlin",
      "cell_geom": { "type": "Polygon", "coordinates": [...] },
      "distance_m": 312.4
    }
  ],
  "metadata": { ... }
}
```

**Empty result:** Returns 200 with `results: []` when no hotspots exist within 5 km.

---

## 2. Frontend

### Button

- Label: `📍 Nearby Hazards`
- Location: left panel, below existing filter pills
- States: default → "Loading…" (while geolocation + fetch in flight) → back to default on completion

### Geolocation flow

1. `navigator.geolocation.getCurrentPosition()` called on button click
2. On success: call `GET /zones/nearby-hazards?lat=&lon=`
3. Map flies to user location at zoom 12 after results load
4. Hotspot markers rendered from response

### Markers

- **Layer group:** `layers.hazards` (new, same pattern as `layers.choropleth`, `layers.accidents`)
- **Type:** `L.divIcon` wrapper div containing a styled element
- **Style:** Red filled circle, ~20px diameter
- **Animation:** CSS keyframe `hotspot-pulse` — `box-shadow` and `opacity` glow-in → glow-out, 1.5s loop
- **Centroid:** Computed from `cell_geom` polygon coordinates (avg of exterior ring points)
- Re-clicking the button clears `layers.hazards` and re-fetches

### Interaction

- Marker click → calls `showInsightHazard(zone)` (new function)
- `showInsightHazard` calls existing `openInsightPanel(html)` with:
  - Title: `⚠️ Accident Hotspot`
  - Subtitle: region name
  - Stats: accident count (2022–2024), distance from user
  - Footer message: `"Be careful in this area."`

---

## 3. Error Handling

| Scenario | User-facing message | Behaviour |
|---|---|---|
| Geolocation denied | "Location access denied — allow location in your browser." | No API call |
| lat/lon outside Germany | "Your location is outside Germany." | 422 caught, toast shown |
| 0 results | "No accident hotspots within 500 m of your location." | `layers.hazards` stays empty |
| Network / API error | "Could not load nearby hazards." | Toast shown |

**Toast:** Small overlay div, auto-dismisses after 3 s. No new library.

---

## 4. Testing

### Backend (`tests/test_api_integration.py`)

- `GET /zones/nearby-hazards?lat=52.52&lon=13.40` → 200, `results` length ≤ 5, all `kind == 'hotspot'`, all `distance_m ≤ 500`
- `GET /zones/nearby-hazards?lat=0&lon=0` → 422
- Skip fixture: same pattern as existing zone tests — skip if `accident_zones` table empty

### Frontend

Manual verification:
- Button click → browser geolocation prompt appears
- On grant → markers appear on map with pulse animation
- Marker click → insight panel opens with correct accident count and region name
- Button re-click → markers clear and reload
- Deny geolocation → toast appears, no crash

---

## 5. Files Changed

| File | Change |
|---|---|
| `api/routes/zones.py` | Add `GET /zones/nearby-hazards` route |
| `frontend/app.js` | Add button handler, `loadNearbyHazards()`, `showInsightHazard()`, pulse marker render |
| `frontend/style.css` | Add `.hotspot-pulse` CSS keyframe animation |
| `frontend/index.html` | Add "📍 Nearby Hazards" button to left panel |
| `tests/test_api_integration.py` | Add `TestNearbyHazards` test class |

No schema changes. No ETL changes.
