# Accident Map — Zoom-Driven Visualization Redesign

**Date:** 2026-06-25  
**Scope:** `frontend/` only — `index.html`, `style.css`, `app.js` (full rewrite), two new vendor bundles  
**Data:** Unfallatlas 2016–2024, Germany

---

## Overview

Redesign the Accident Map to implement a zoom-driven layer switching system that transitions between three visualization modes — Choropleth → Hexagonal Binning → Point Map — based on zoom level. Colors derived from the existing dark-theme palette. Sidebar replaced by three floating panels + bottom-center timeline scrubber.

---

## Decisions

| Decision | Choice | Reason |
|---|---|---|
| Hex binning engine | deck.gl `HexagonLayer` via local vendor file | WebGL 3D extrusion; matches existing vendor pattern; no CSP changes |
| Hex data loading | Viewport-bounded fetch on moveend | Matches existing point-layer pattern; avoids 268k-row upfront load |
| Code structure | Full rewrite of `app.js` | Zoom state machine + deck.gl lifecycle best designed together; sidebar removal makes surgical graft too costly |
| Sidebar | Remove entirely | Clean break; all sidebar features (charts, route analysis, examiner questions) dropped |
| Legacy layers | Municipalities survive as subtle overlay; hotspots and safe zones removed | Municipalities useful at zoom 9+; hotspot concept covered by hex density |
| Clustering | Supercluster (vendored, ~15KB) | Lightweight, no build step, custom styling |

---

## Color Palette

All colors from existing `style.css` tokens (remapped to spec intent):

| Token | Hex | Usage |
|---|---|---|
| `--bg-deep` | `#0B1220` | Panel backgrounds |
| `--bg-dark` | `#111827` | Insight panel bg |
| `--bg-card` | `#1A2332` | Detail card bg |
| `--accent-red` | `#EF4444` | High severity, active filters, pulse ring |
| `--accent-red-deep` | `#7F1D1D` | Fatal severity, max choropleth intensity |
| `--accent-warm` | `#C2410C` | Minor severity, mid-high scale |
| `--accent-brown` | `#8B6914` | Medium scale |
| `--scale-low` | `#2D3748` | Lowest density |
| `--text-primary` | `#F9FAFB` | Headings |
| `--text-secondary` | `#9CA3AF` | Labels, district labels |

Choropleth / hex color scale (7 steps, same for both layers):

```
0          → #2D3748
1–50       → #4A4030
51–200     → #6B5B3E
201–500    → #8B6914
501–1000   → #C2410C
1001–3000  → #EF4444
3000+      → #7F1D1D
```

---

## Zoom-Driven Layer Switching

### Thresholds

| Layer | Zoom Range | Purpose |
|---|---|---|
| Choropleth | 5 – 8 | National/regional overview per district |
| Hexagonal Binning | 8 – 12 | City/area density clusters |
| Point Map | 12 – 18 | Individual accident locations |

### Hysteresis

Switch **up** at exact threshold (e.g. zoom 8.0 → hex). Switch **back down** only after 0.5 zoom drop (zoom 7.5 → choropleth). Prevents threshold flickering. Reference zoom stored in `state.lastSwitchZoom`.

### Crossfade

Outgoing layer wrapper: `opacity 1→0`, 400ms, `cubic-bezier(0.4,0,0.2,1)`.  
Incoming layer wrapper: `opacity 0→1`, 400ms, same easing.  
Implemented via CSS transition class, not JS animation.

### Manual Override

`state.mode !== 'auto'` bypasses zoom logic. `switchLayer(target)` called immediately on Panel A selection.

---

## Architecture

### State

```js
const state = {
  year: 2024,
  participant: '',       // '' | 'car' | 'bike' | 'pedestrian' | 'truck'
  category: '',          // '' | '2' | '1'
  mode: 'auto',          // 'auto' | 'district' | 'hex' | 'point'
  activeLayer: 'choropleth',
  lastSwitchZoom: 6,
}
```

### deck.gl Integration

One `DeckGL` instance overlaid on Leaflet canvas. Viewport synced from `map.getCenter()` / `map.getZoom()` on every Leaflet `move` / `zoom` event. `HexagonLayer` recreated on moveend with new bbox-filtered data. Other deck.gl layers use `setProps` for cheap updates.

### Data Flow

| Layer | Fetch | Trigger |
|---|---|---|
| Choropleth | `/aggregates/accidents?level=district&year=X` + `/regions?level=district` GeoJSON | Year change, init |
| Hex | `/accidents?year=X&lat_min=…&lat_max=…&lon_min=…&lon_max=…` (bbox) | moveend (debounced 500ms) |
| Point | Same bbox endpoint + participant/category params | moveend (debounced 500ms) |
| Municipalities | `/regions?level=municipality` GeoJSON | Once, lazy at zoom ≥ 9 |

---

## Layer 1: Choropleth

- Source: existing `loadChoropleth()` logic, rewritten cleanly
- District borders: `1px solid rgba(255,255,255,0.08)`
- Hover: border → `rgba(255,255,255,0.25)`, `filter: brightness(1.15)`, 150ms
- District labels: Leaflet permanent tooltips, visible zoom ≥ 7, `font-size: 11px`, color `#9CA3AF`
- Legend: fixed-position collapsible div, bottom-right, 7 swatches, `backdrop-filter: blur(8px)`, `background: rgba(11,18,32,0.8)`
- On click: opens Insight Panel with district stats

---

## Layer 2: Hexagonal Binning

### deck.gl HexagonLayer Config

```js
{
  id: 'hex-layer',
  data: accidentPoints,        // [{position: [lon, lat], category}]
  getPosition: d => d.position,
  radius: zoom < 10 ? 500 : 200,
  colorRange: [
    [45,55,72], [74,64,48], [107,91,62],
    [139,105,20], [194,65,12], [239,68,68], [127,29,29]
  ],
  elevationRange: [0, 500],
  elevationScale: 4,
  upperPercentile: 99,
  coverage: 0.9,
  opacity: 0.75,
  pickable: true,
  onHover: showHexTooltip,
  onClick: ({object}) => showInsightPanel('hex', object),
}
```

Radius switches at zoom 10 via `deckLayer.setProps({radius: 200})`.

### Hex Tooltip

`"45 accidents · 3 fatal · [lat, lon]"` — fade-in 150ms, `translateY(4px→0)`.

### Hover Style

deck.gl built-in highlight: `autoHighlight: true, highlightColor: [255,255,255,30]`.

---

## Layer 3: Point Map

### Severity Styling

| Category | Fill | Radius | Stroke |
|---|---|---|---|
| 1 — Fatal | `#7F1D1D` | 10px | 2px `#EF4444` |
| 2 — Serious | `#EF4444` | 7px | 1px `rgba(255,255,255,0.3)` |
| 3 — Minor | `#C2410C` | 5px | 1px `rgba(255,255,255,0.2)` |

All points: `opacity: 0.85`.

### Fatal Pulse Animation

```css
@keyframes fatalPulse {
  0%   { transform: scale(1);   opacity: 0.6; }
  100% { transform: scale(1.5); opacity: 0; }
}
.pulse-ring {
  animation: fatalPulse 2s ease-out infinite;
  border: 2px solid #EF4444;
  border-radius: 50%;
}
```

Sibling `div.pulse-ring` injected into Leaflet marker pane for each fatal point.

### Clustering (zoom 12–14)

Supercluster with `radius: 30`. Cluster rendered as `L.divIcon`: circle with weighted-average color, count badge center. Click cluster → `map.setZoom(zoom + 1)`.

### Point Click

Opens floating Detail Card (Leaflet popup with custom CSS, not Insight Panel).

---

## UI: Floating Panels

### Panel A — Layer Mode (top-left)

```css
position: fixed; top: 16px; left: 16px;
backdrop-filter: blur(12px);
background: rgba(17,24,39,0.85);
border: 1px solid rgba(255,255,255,0.08);
border-radius: 12px;
```

Pill button `⬡` toggles dropdown. Options: `Auto ✓ | District | Hex | Point`. Active option: `#EF4444` indicator dot. Dropdown closes on selection or outside click.

### Panel B — Filters (bottom-left)

```css
position: fixed; bottom: 80px; left: 16px;
```

Row 1: `All | 🚗 Car | 🚲 Bike | 🚶 Foot | 🚛 Truck`  
Row 2: `All Severities | Serious+ | Fatal`

Active pill: `background: #EF4444; box-shadow: 0 0 8px rgba(239,68,68,0.3)`.  
Inactive: `background: transparent; color: #9CA3AF`.  
Border-radius: 20px, padding: 6px 14px.  
Any filter change triggers `reloadActiveLayer()`.

### Panel C — Stats Strip (top-right)

```css
position: fixed; top: 16px; right: 16px;
backdrop-filter: blur(8px);
background: rgba(11,18,32,0.7);
```

Dynamic content by active layer:
- Choropleth/Hex: `268,519 Accidents · 2,458 Fatal` (+ `· ⬡ N Hexagons` in hex mode)
- Point: `N in viewport · M Fatal`

Monospace numbers, 11px sans-serif labels.

### Zoom Mode Badge (bottom-right)

```css
position: fixed; bottom: 32px; right: 16px;
```

Content: `🗺️ District View` / `⬡ Hex View` / `📍 Point View`. Updates on `switchLayer()`.

---

## UI: Timeline Scrubber (bottom-center)

```css
position: fixed; bottom: 16px; left: 50%; transform: translateX(-50%);
width: 480px;
backdrop-filter: blur(8px); background: rgba(11,18,32,0.7);
border-radius: 12px; padding: 10px 16px;
```

SVG sparkline: 9 bars (2016–2024). Bar height proportional to total accidents per year. Stacked fill: fatal=`#7F1D1D`, serious=`#EF4444`, minor=`#C2410C`. Draggable playhead snaps to year on release, updates `state.year` and calls `reloadActiveLayer()`.

Play button `▶` advances years at 1.5s intervals. Current year bold in `#EF4444`.

Sparkline data fetched once on init from `/aggregates/accidents` (no year param → all years).

---

## UI: Insight Panel (right slide-out)

```css
position: fixed; top: 0; right: 0; height: 100%; width: 320px;
background: #111827;
border-left: 1px solid rgba(255,255,255,0.08);
box-shadow: -8px 0 24px rgba(0,0,0,0.4);
transform: translateX(320px);
transition: transform 250ms ease;
```

`.open` class: `transform: translateX(0)`. Closed by `✕` button or Escape key.

Content by click source:

**Choropleth click:**
- District name + total accidents + national rank
- 5-bar mini-sparkline (2016–2024 trend, inline SVG)
- Top 3 accident types as horizontal bar segments

**Hex click:**
- Approximate center address (Nominatim reverse-geocode, memoized in a JS `Map` keyed by `"lat,lon"`)
- Accident count breakdown by severity
- Time-of-day bar chart (Chart.js, 0–23h)
- Dominant participant type

**Point click:** Does not open insight panel — opens Detail Card instead.

---

## UI: Detail Card (point click)

Leaflet `L.popup()` with `className: 'detail-card'` overriding all default Leaflet popup styles.

```css
.detail-card .leaflet-popup-content-wrapper {
  background: #1A2332;
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 12px;
  box-shadow: 0 8px 32px rgba(0,0,0,0.4);
  max-width: 280px;
}
```

Three rows:
- **Header:** severity badge (color-coded pill) + date + time
- **Body:** street/district (from `acc` fields) + accident type + vehicles involved + injury/fatality count — each field rendered only if present in API response; `category` and `participant_*` booleans always available
- **Footer:** weather / road surface / lighting icons — omitted entirely if fields absent from API response

---

## Animations Summary

| Interaction | Spec |
|---|---|
| Layer crossfade | `opacity` 0↔1, 400ms, `cubic-bezier(0.4,0,0.2,1)` |
| District hover | `filter: brightness(1.15)`, border rgba change, 150ms |
| Hex hover | deck.gl `autoHighlight`, tooltip fade 150ms |
| Fatal pulse | CSS `@keyframes`, 2s infinite, ring expands 1×→1.5× |
| Filter toggle | `transform: scale(0.96→1)`, 200ms |
| Insight panel slide | `transform: translateX()`, 250ms ease |
| Tooltip | `opacity 0→1` + `translateY(4px→0)`, 150ms |

---

## Files Changed

| File | Change |
|---|---|
| `frontend/app.js` | Full rewrite (~1000–1200 lines) |
| `frontend/index.html` | Remove sidebar HTML; add 3 panel divs, scrubber, insight panel, detail card anchor; add 2 vendor `<script>` tags |
| `frontend/style.css` | Remove sidebar styles; add panel, scrubber, badge, detail-card, pulse-ring styles |
| `frontend/vendor/deck.gl/deck.gl.min.js` | New — deck.gl v9 standalone bundle (~3.5MB) |
| `frontend/vendor/supercluster/supercluster.min.js` | New — Supercluster v8 (~15KB) |

No backend changes. No CSP changes. No build step.

---

## Out of Scope

- Year Trend chart, Hour Distribution chart, Day×Hour heatgrid
- Route Analysis tool
- Examiner Questions panel
- Hotspot and Safe Zone layers
- Backend hex-aggregation endpoint
- Mobile/touch optimization
