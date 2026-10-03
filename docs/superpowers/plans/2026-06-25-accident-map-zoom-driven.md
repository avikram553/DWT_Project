# Accident Map — Zoom-Driven Visualization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the Unfallatlas frontend to a zoom-driven three-layer system (Choropleth → Hex Binning → Point Map), replacing the sidebar with floating panels.

**Architecture:** Full rewrite of `app.js` around a zoom state machine. deck.gl `Deck` + `HexagonLayer` renders hex binning via a canvas overlay synced to Leaflet. Supercluster handles point clustering at zoom 12–14. Three fixed-position floating panels replace the sidebar. State machine drives layer transitions with 0.5-zoom hysteresis and 400ms crossfade.

**Tech Stack:** Leaflet 1.x (existing), deck.gl v9 standalone (new vendor), Supercluster v8 (new vendor), vanilla JS, FastAPI backend (unchanged)

## Global Constraints

- No npm, no build step — vendor files in `frontend/vendor/`, loaded via `<script>`
- CSP in `index.html` `<meta>` tag unchanged — no external CDN at runtime
- All hex color values from spec palette only
- No backend changes — all data from existing `/accidents`, `/aggregates/accidents`, `/regions` endpoints
- AGS codes always TEXT (never cast to integer)
- Single `app.js` file — no module splitting
- deck.gl zoom = Leaflet zoom − 1 (256px vs 512px tile convention)
- Sidebar and all sidebar features removed: year trend chart, hour chart, heatgrid, route analysis, examiner questions
- Hotspot and safe zone layers removed entirely

---

### Task 1: Vendor Assets

**Files:**
- Create: `frontend/vendor/deck.gl/deck.gl.min.js`
- Create: `frontend/vendor/supercluster/supercluster.min.js`

**Interfaces:**
- Produces: `deck.Deck`, `deck.HexagonLayer` globals (from deck.gl bundle); `Supercluster` global (from supercluster bundle)

- [ ] **Step 1: Download deck.gl standalone bundle**

```bash
mkdir -p frontend/vendor/deck.gl
curl -L "https://unpkg.com/deck.gl@9.0.36/dist.min.js" -o frontend/vendor/deck.gl/deck.gl.min.js
wc -c frontend/vendor/deck.gl/deck.gl.min.js
```

Expected: file exists, ~3–4MB. If 404, try `https://unpkg.com/deck.gl@8.9.35/dist.min.js`.

- [ ] **Step 2: Download Supercluster bundle**

```bash
mkdir -p frontend/vendor/supercluster
curl -L "https://unpkg.com/supercluster@8.0.1/dist/supercluster.min.js" -o frontend/vendor/supercluster/supercluster.min.js
wc -c frontend/vendor/supercluster/supercluster.min.js
```

Expected: file exists, ~15KB.

- [ ] **Step 3: Commit**

```bash
git add frontend/vendor/deck.gl/deck.gl.min.js frontend/vendor/supercluster/supercluster.min.js
git commit -m "feat: add deck.gl v9 and supercluster v8 vendor bundles"
```

---

### Task 2: HTML Restructure

**Files:**
- Modify: `frontend/index.html` (full replacement)

**Interfaces:**
- Produces: DOM structure consumed by all subsequent tasks
- Element IDs referenced by `app.js`: `#map`, `#panel-a`, `#panel-a-btn`, `#panel-a-dropdown`, `#panel-b`, `#filter-participant`, `#filter-severity`, `#panel-c`, `#stat-total`, `#stat-fatal`, `#stat-dynamic`, `#stat-dynamic-val`, `#stat-dynamic-lbl`, `#zoom-badge`, `#scrubber`, `#scrubber-svg`, `#scrubber-track`, `#scrubber-playhead`, `#scrubber-play`, `#insight-panel`, `#insight-close`, `#insight-content`, `#api-status`

- [ ] **Step 1: Replace index.html entirely**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta http-equiv="Content-Security-Policy" content="default-src 'self' 'unsafe-eval' 'unsafe-inline' https://fonts.googleapis.com https://fonts.gstatic.com https://*.basemaps.cartocdn.com https://nominatim.openstreetmap.org http://localhost:8000 data: blob:;">
  <title>Unfallatlas Deutschland</title>
  <link rel="stylesheet" href="vendor/leaflet/leaflet.css">
  <link rel="stylesheet" href="style.css">
</head>
<body>

<!-- MAP -->
<div id="map"></div>

<!-- PANEL A: Layer Mode (top-left) -->
<div id="panel-a" class="float-panel panel-a">
  <button id="panel-a-btn" class="panel-a-btn" aria-label="Layer mode">⬡</button>
  <div id="panel-a-dropdown" class="panel-a-dropdown hidden">
    <button class="mode-option mode-option--active" data-mode="auto">Auto <span class="mode-dot"></span></button>
    <button class="mode-option" data-mode="district">🗺️ District</button>
    <button class="mode-option" data-mode="hex">⬡ Hex</button>
    <button class="mode-option" data-mode="point">📍 Point</button>
  </div>
</div>

<!-- PANEL B: Filters (bottom-left) -->
<div id="panel-b" class="float-panel panel-b">
  <div id="filter-participant" class="filter-row">
    <button class="filter-pill filter-pill--active" data-participant="">All</button>
    <button class="filter-pill" data-participant="car">🚗 Car</button>
    <button class="filter-pill" data-participant="bike">🚲 Bike</button>
    <button class="filter-pill" data-participant="pedestrian">🚶 Foot</button>
    <button class="filter-pill" data-participant="truck">🚛 Truck</button>
  </div>
  <div id="filter-severity" class="filter-row">
    <button class="filter-pill filter-pill--active" data-category="">All Severities</button>
    <button class="filter-pill" data-category="2">Serious+</button>
    <button class="filter-pill" data-category="1">Fatal</button>
  </div>
</div>

<!-- PANEL C: Stats strip (top-right) -->
<div id="panel-c" class="float-panel panel-c">
  <span id="stat-total"><span class="stat-num">—</span> <span class="stat-lbl">Accidents</span></span>
  <span class="stat-sep">·</span>
  <span id="stat-fatal"><span class="stat-num">—</span> <span class="stat-lbl">Fatal</span></span>
  <span id="stat-dynamic" class="hidden">
    <span class="stat-sep">·</span>
    <span id="stat-dynamic-val" class="stat-num">—</span>
    <span id="stat-dynamic-lbl" class="stat-lbl">—</span>
  </span>
</div>

<!-- Zoom Mode Badge (bottom-right, above attribution) -->
<div id="zoom-badge" class="zoom-badge">🗺️ District View</div>

<!-- TIMELINE SCRUBBER (bottom-center) -->
<div id="scrubber" class="scrubber">
  <button id="scrubber-play" class="scrubber-play" aria-label="Play">▶</button>
  <div class="scrubber-inner">
    <svg id="scrubber-svg" class="scrubber-sparkline" viewBox="0 0 270 40" preserveAspectRatio="none"></svg>
    <div id="scrubber-track" class="scrubber-track">
      <div id="scrubber-playhead" class="scrubber-playhead"></div>
    </div>
    <div class="scrubber-labels">
      <span>2016</span><span></span><span></span><span></span><span></span>
      <span></span><span></span><span></span><span>2024</span>
    </div>
  </div>
</div>

<!-- INSIGHT PANEL (right slide-out) -->
<div id="insight-panel" class="insight-panel">
  <button id="insight-close" class="insight-close" aria-label="Close">✕</button>
  <div id="insight-content" class="insight-content"></div>
</div>

<!-- API status -->
<div class="api-status-wrap">
  <span id="api-status" class="api-status">● Connecting…</span>
</div>

<script src="vendor/leaflet/leaflet.js"></script>
<script src="vendor/deck.gl/deck.gl.min.js"></script>
<script src="vendor/supercluster/supercluster.min.js"></script>
<script src="app.js"></script>
</body>
</html>
```

- [ ] **Step 2: Verify structure loads**

Open `frontend/index.html` in browser (API running). Map container should be present in DOM. Console: no 404s for vendor files. Panels not yet styled — that's Task 3.

- [ ] **Step 3: Commit**

```bash
git add frontend/index.html
git commit -m "feat: restructure HTML — remove sidebar, add floating panel scaffolding"
```

---

### Task 3: CSS Overhaul

**Files:**
- Modify: `frontend/style.css` (full replacement)

**Interfaces:**
- Produces: all visual styles consumed by `app.js` DOM operations
- Key class names `app.js` adds/removes: `.hidden`, `.open` (insight panel), `.filter-pill--active`, `.mode-option--active`, `.hex-active` (deck canvas), `.pulse-ring`, `.legend-hidden`

- [ ] **Step 1: Replace style.css entirely**

```css
/* ── Tokens ── */
:root {
  --bg-deep:        #0B1220;
  --bg-dark:        #111827;
  --bg-card:        #1A2332;
  --bg-elevated:    #243447;
  --border-subtle:  rgba(255,255,255,0.06);
  --border-default: rgba(255,255,255,0.10);
  --text-primary:   #F9FAFB;
  --text-secondary: #9CA3AF;
  --text-muted:     #6B7280;
  --accent-red:     #EF4444;
  --accent-warm:    #C2410C;
  --accent-red-deep:#7F1D1D;
  --accent-brown:   #8B6914;
}

/* ── Reset ── */
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body { background: var(--bg-deep); color: var(--text-primary); font-family: system-ui, sans-serif; overflow: hidden; }

/* ── Map ── */
#map { position: fixed; inset: 0; z-index: 0; }

/* ── deck.gl canvas ── */
#deck-canvas {
  position: absolute; top: 0; left: 0; width: 100%; height: 100%;
  pointer-events: none; z-index: 400;
  transition: opacity 400ms cubic-bezier(0.4,0,0.2,1);
}
#deck-canvas.hex-active { pointer-events: auto; }

/* ── Floating panel base ── */
.float-panel {
  position: fixed;
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  background: rgba(17,24,39,0.85);
  border: 1px solid var(--border-default);
  border-radius: 12px;
  z-index: 1000;
  color: var(--text-primary);
}

/* ── Panel A: Layer Mode ── */
.panel-a { top: 16px; left: 16px; padding: 6px; }
.panel-a-btn {
  background: none; border: none; color: var(--text-primary);
  font-size: 20px; cursor: pointer; padding: 4px 8px; border-radius: 8px;
  transition: background 150ms;
}
.panel-a-btn:hover { background: var(--bg-elevated); }
.panel-a-dropdown {
  position: absolute; top: calc(100% + 6px); left: 0;
  background: rgba(17,24,39,0.95);
  border: 1px solid var(--border-default);
  border-radius: 10px; overflow: hidden; min-width: 140px;
}
.panel-a-dropdown.hidden { display: none; }
.mode-option {
  display: flex; align-items: center; justify-content: space-between;
  width: 100%; padding: 8px 14px; background: none; border: none;
  color: var(--text-secondary); font-size: 13px; cursor: pointer; text-align: left;
  transition: background 150ms, color 150ms;
}
.mode-option:hover { background: var(--bg-elevated); color: var(--text-primary); }
.mode-option--active { color: var(--text-primary); }
.mode-dot {
  width: 6px; height: 6px; border-radius: 50%;
  background: var(--accent-red); display: inline-block;
}

/* ── Panel B: Filters ── */
.panel-b { bottom: 80px; left: 16px; padding: 10px 12px; display: flex; flex-direction: column; gap: 8px; }
.filter-row { display: flex; gap: 6px; flex-wrap: wrap; }
.filter-pill {
  padding: 6px 14px; border-radius: 20px; border: 1px solid var(--border-default);
  background: transparent; color: var(--text-secondary); font-size: 13px; cursor: pointer;
  transition: transform 200ms, background 150ms, color 150ms, box-shadow 150ms;
}
.filter-pill:active { transform: scale(0.96); }
.filter-pill--active {
  background: var(--accent-red); color: #fff; border-color: var(--accent-red);
  box-shadow: 0 0 8px rgba(239,68,68,0.3);
}

/* ── Panel C: Stats ── */
.panel-c {
  top: 16px; right: 16px; padding: 8px 14px;
  display: flex; align-items: center; gap: 8px;
  backdrop-filter: blur(8px);
  background: rgba(11,18,32,0.7);
}
.stat-num { font-family: monospace; font-size: 14px; color: var(--text-primary); }
.stat-lbl { font-size: 11px; color: var(--text-secondary); }
.stat-sep { color: var(--text-muted); font-size: 12px; }

/* ── Zoom Badge ── */
.zoom-badge {
  position: fixed; bottom: 32px; right: 16px; z-index: 1000;
  backdrop-filter: blur(8px);
  background: rgba(11,18,32,0.7);
  border: 1px solid var(--border-default);
  border-radius: 20px; padding: 5px 12px;
  font-size: 12px; color: var(--text-secondary);
}

/* ── Timeline Scrubber ── */
.scrubber {
  position: fixed; bottom: 16px; left: 50%; transform: translateX(-50%);
  width: 480px; z-index: 1000;
  backdrop-filter: blur(8px);
  background: rgba(11,18,32,0.7);
  border: 1px solid var(--border-default);
  border-radius: 12px; padding: 10px 16px;
  display: flex; align-items: center; gap: 10px;
}
.scrubber-play {
  background: none; border: 1px solid var(--border-default);
  color: var(--text-primary); border-radius: 6px; padding: 4px 8px;
  font-size: 14px; cursor: pointer; flex-shrink: 0;
  transition: background 150ms;
}
.scrubber-play:hover { background: var(--bg-elevated); }
.scrubber-inner { flex: 1; display: flex; flex-direction: column; gap: 4px; }
.scrubber-sparkline { width: 100%; height: 40px; display: block; }
.scrubber-track {
  position: relative; height: 4px; background: var(--bg-elevated);
  border-radius: 2px; cursor: pointer;
}
.scrubber-playhead {
  position: absolute; top: 50%; transform: translate(-50%, -50%);
  width: 12px; height: 12px; border-radius: 50%;
  background: var(--accent-red); cursor: grab;
  transition: left 150ms;
}
.scrubber-labels {
  display: flex; justify-content: space-between;
  font-size: 10px; color: var(--text-muted);
}
.scrubber-labels .active { color: var(--accent-red); font-weight: 700; }

/* ── Insight Panel ── */
.insight-panel {
  position: fixed; top: 0; right: 0; height: 100%; width: 320px;
  background: var(--bg-dark); z-index: 1100;
  border-left: 1px solid var(--border-subtle);
  box-shadow: -8px 0 24px rgba(0,0,0,0.4);
  transform: translateX(320px);
  transition: transform 250ms ease;
  overflow-y: auto;
}
.insight-panel.open { transform: translateX(0); }
.insight-close {
  position: absolute; top: 12px; right: 12px;
  background: none; border: none; color: var(--text-secondary);
  font-size: 18px; cursor: pointer; padding: 4px;
}
.insight-content { padding: 48px 20px 20px; }
.insight-title { font-size: 16px; font-weight: 600; margin-bottom: 4px; color: var(--text-primary); }
.insight-subtitle { font-size: 12px; color: var(--text-secondary); margin-bottom: 16px; }
.insight-stat {
  display: flex; justify-content: space-between;
  padding: 8px 0; border-bottom: 1px solid var(--border-subtle); font-size: 13px;
  color: var(--text-secondary);
}
.insight-stat-val { font-family: monospace; color: var(--text-primary); }

/* ── Detail Card (Leaflet popup override) ── */
.detail-card .leaflet-popup-content-wrapper {
  background: var(--bg-card);
  border: 1px solid var(--border-default);
  border-radius: 12px;
  box-shadow: 0 8px 32px rgba(0,0,0,0.4);
  max-width: 280px; padding: 0; color: var(--text-primary);
}
.detail-card .leaflet-popup-tip-container { display: none; }
.detail-card .leaflet-popup-content { margin: 0; }
.card-header {
  padding: 10px 14px; border-bottom: 1px solid var(--border-subtle);
  display: flex; justify-content: space-between; align-items: center;
}
.card-severity { padding: 3px 8px; border-radius: 10px; font-size: 11px; font-weight: 600; }
.card-severity--fatal   { background: var(--accent-red-deep); color: #fff; }
.card-severity--serious { background: var(--accent-red); color: #fff; }
.card-severity--minor   { background: var(--accent-warm); color: #fff; }
.card-datetime { font-size: 12px; color: var(--text-secondary); }
.card-body { padding: 10px 14px; font-size: 13px; line-height: 1.6; }
.card-footer { padding: 8px 14px; border-top: 1px solid var(--border-subtle); font-size: 12px; color: var(--text-muted); }

/* ── Fatal Pulse Ring ── */
@keyframes fatalPulse {
  0%   { transform: scale(1);   opacity: 0.6; }
  100% { transform: scale(1.5); opacity: 0; }
}
.pulse-ring {
  position: absolute; border-radius: 50%;
  border: 2px solid var(--accent-red);
  animation: fatalPulse 2s ease-out infinite;
  pointer-events: none;
}

/* ── Choropleth Legend ── */
.choropleth-legend {
  position: fixed; bottom: 80px; right: 16px; z-index: 1000;
  backdrop-filter: blur(8px);
  background: rgba(11,18,32,0.8);
  border: 1px solid var(--border-default);
  border-radius: 10px; padding: 10px 12px;
  display: flex; flex-direction: column; gap: 4px;
}
.legend-row { display: flex; align-items: center; gap: 8px; font-size: 11px; color: var(--text-secondary); }
.legend-swatch { width: 12px; height: 12px; border-radius: 2px; flex-shrink: 0; }
.legend-hidden { display: none !important; }

/* ── District label (permanent Leaflet tooltip) ── */
.district-label {
  background: none; border: none; box-shadow: none;
  font-size: 11px; color: #9CA3AF; pointer-events: none;
  white-space: nowrap;
}
.district-label::before { display: none; }

/* ── Cluster markers ── */
.cluster-marker {
  border-radius: 50%; display: flex; align-items: center; justify-content: center;
  color: #fff; font-size: 11px; font-weight: 700;
  border: 2px solid rgba(255,255,255,0.3); cursor: pointer;
}

/* ── API status ── */
.api-status-wrap { position: fixed; top: 16px; left: 50%; transform: translateX(-50%); z-index: 1000; }
.api-status { font-size: 11px; color: var(--text-muted); background: rgba(11,18,32,0.7); padding: 3px 10px; border-radius: 10px; }
.api-status.live  { color: #10B981; }
.api-status.error { color: var(--accent-red); }

/* ── Utility ── */
.hidden { display: none !important; }
```

- [ ] **Step 2: Verify visually**

Open browser. Map fills full viewport. All panels positioned correctly: Panel A top-left, Panel B bottom-left, Panel C top-right, badge bottom-right, scrubber bottom-center. No sidebar. No JS errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/style.css
git commit -m "feat: replace sidebar CSS with floating panel, scrubber, insight panel, pulse styles"
```

---

### Task 4: app.js — State, Map, deck.gl Overlay, Zoom State Machine

**Files:**
- Modify: `frontend/app.js` (full rewrite — this task writes the skeleton; Tasks 5–11 add functions to it)

**Interfaces:**
- Produces: `state`, `map`, `deckInstance`, `layers`, `SCALE`, `SCALE_RGB`, `scaleColor(count)`, `apiFetch(path)`, `switchLayer(name)`, `reloadActiveLayer()`, `updateZoomBadge(layer)`, `updateDynamicStat(val, lbl)`
- Consumed by: Tasks 5–12

- [ ] **Step 1: Write app.js skeleton**

Replace all of `frontend/app.js` with:

```js
// Unfallkarte Deutschland — Zoom-Driven Visualization
'use strict';

// ── State ──────────────────────────────────────────────────────────────────
const state = {
  year: 2024,
  participant: '',      // '' | 'car' | 'bike' | 'pedestrian' | 'truck'
  category: '',         // '' | '2' | '1'
  mode: 'auto',         // 'auto' | 'district' | 'hex' | 'point'
  activeLayer: 'choropleth',
  lastSwitchZoom: 6,
  playInterval: null,
  yearData: {},         // year → {total, fatal, serious, minor}
};

// ── Color scale ────────────────────────────────────────────────────────────
const SCALE = [
  { max: 0,        color: '#2D3748' },
  { max: 50,       color: '#4A4030' },
  { max: 200,      color: '#6B5B3E' },
  { max: 500,      color: '#8B6914' },
  { max: 1000,     color: '#C2410C' },
  { max: 3000,     color: '#EF4444' },
  { max: Infinity, color: '#7F1D1D' },
];

// RGB arrays for deck.gl colorRange (same 7 steps as SCALE)
const SCALE_RGB = [
  [45,55,72],[74,64,48],[107,91,62],
  [139,105,20],[194,65,12],[239,68,68],[127,29,29],
];

function scaleColor(count) {
  for (const s of SCALE) if (count <= s.max) return s.color;
  return '#7F1D1D';
}

// ── Map ────────────────────────────────────────────────────────────────────
const map = L.map('map', { zoom: 6, center: [51.2, 10.5], zoomControl: false });
L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
  attribution: '© OpenStreetMap contributors © CARTO',
  subdomains: 'abcd', maxZoom: 19,
}).addTo(map);
L.control.zoom({ position: 'topright' }).addTo(map);

// ── deck.gl canvas overlay ─────────────────────────────────────────────────
const deckCanvas = document.createElement('canvas');
deckCanvas.id = 'deck-canvas';
document.getElementById('map').appendChild(deckCanvas);

function getDeckViewState() {
  const c = map.getCenter();
  // deck.gl uses 512px tile convention; Leaflet uses 256px → subtract 1 zoom level
  return { longitude: c.lng, latitude: c.lat, zoom: map.getZoom() - 1, pitch: 30, bearing: 0 };
}

const deckInstance = new deck.Deck({
  canvas: deckCanvas,
  width: '100%',
  height: '100%',
  initialViewState: getDeckViewState(),
  controller: false,
  layers: [],
  getTooltip: ({ object }) => {
    if (!object) return null;
    const points = object.points || [];
    const count  = points.length;
    const fatal  = points.filter(p => p.source && p.source.category === 1).length;
    return {
      html: `<div style="background:#1A2332;border:1px solid rgba(255,255,255,0.1);border-radius:8px;padding:8px 12px;font-size:12px;color:#F9FAFB">${count.toLocaleString('en-US')} accidents · ${fatal} fatal</div>`,
      style: { padding: '0', background: 'none', border: 'none' },
    };
  },
});

map.on('move', () => deckInstance.setProps({ viewState: getDeckViewState() }));

// ── Leaflet layer groups ───────────────────────────────────────────────────
const layers = {
  choropleth:     L.layerGroup().addTo(map),
  municipalities: L.layerGroup(),
  accidents:      L.layerGroup().addTo(map),
};

// ── API helper ─────────────────────────────────────────────────────────────
async function apiFetch(path) {
  const res = await fetch(`http://localhost:8000${path}`);
  if (!res.ok) throw new Error(`${res.status} ${path}`);
  return res.json();
}

// ── Zoom state machine ─────────────────────────────────────────────────────
const ZOOM_HEX   = 8;
const ZOOM_POINT = 12;
const HYSTERESIS = 0.5;

function targetLayerForZoom(z) {
  if (z >= ZOOM_POINT) return 'point';
  if (z >= ZOOM_HEX)   return 'hex';
  return 'choropleth';
}

function syncLegendVisibility() {
  const el = document.getElementById('choropleth-legend');
  if (el) el.classList.toggle('legend-hidden', state.activeLayer !== 'choropleth');
}

function switchLayer(name) {
  if (state.activeLayer === name) return;

  if (state.activeLayer === 'hex') {
    deckCanvas.style.opacity = '0';
    deckCanvas.classList.remove('hex-active');
    deckInstance.setProps({ layers: [] });
  }
  if (state.activeLayer === 'point') {
    layers.accidents.clearLayers();
  }

  state.activeLayer = name;
  updateZoomBadge(name);
  syncLegendVisibility();

  if (name === 'hex') {
    deckCanvas.style.opacity = '1';
    deckCanvas.classList.add('hex-active');
    loadHex();
  } else if (name === 'point') {
    loadPoints();
  }
  // choropleth: already loaded, nothing to do
}

function onZoomEnd() {
  maybeLoadMunicipalities();
  if (state.mode !== 'auto') return;

  const z = map.getZoom();
  const target = targetLayerForZoom(z);

  if (target === state.activeLayer) {
    // Same layer — reload choropleth so district labels appear/disappear at zoom 7
    if (state.activeLayer === 'choropleth') loadChoropleth();
    return;
  }

  // Hysteresis: switching to a lower-density layer requires 0.5 zoom drop
  const movingToLower = (state.activeLayer === 'point' && target !== 'point') ||
                        (state.activeLayer === 'hex'   && target === 'choropleth');
  if (movingToLower && Math.abs(z - state.lastSwitchZoom) < HYSTERESIS) return;

  state.lastSwitchZoom = z;
  switchLayer(target);
}

map.on('zoomend', onZoomEnd);

function updateZoomBadge(layer) {
  const el = document.getElementById('zoom-badge');
  if (!el) return;
  el.textContent = layer === 'hex' ? '⬡ Hex View'
                 : layer === 'point' ? '📍 Point View'
                 : '🗺️ District View';
}

function updateDynamicStat(val, lbl) {
  document.getElementById('stat-dynamic').classList.remove('hidden');
  document.getElementById('stat-dynamic-val').textContent = val;
  document.getElementById('stat-dynamic-lbl').textContent = lbl;
}

// ── Reload active layer on filter / year change ───────────────────────────
function reloadActiveLayer() {
  if (state.activeLayer === 'choropleth') loadChoropleth();
  else if (state.activeLayer === 'hex')   loadHex();
  else                                     loadPoints();
  updateKPIs();
}

// ── moveend: reload hex/point for new viewport ─────────────────────────────
let moveendTimer = null;
map.on('moveend', () => {
  clearTimeout(moveendTimer);
  moveendTimer = setTimeout(() => {
    if (state.activeLayer === 'hex')   loadHex();
    if (state.activeLayer === 'point') loadPoints();
  }, 500);
});

// ── API status ─────────────────────────────────────────────────────────────
async function checkApiStatus() {
  const el = document.getElementById('api-status');
  try {
    await apiFetch('/metadata/sources');
    el.textContent = '● Live'; el.className = 'api-status live';
  } catch {
    el.textContent = '● Offline'; el.className = 'api-status error';
  }
}

// ── Stubs filled by Tasks 5–11 ─────────────────────────────────────────────
function loadChoropleth()              { /* Task 5 */ }
function loadMunicipalities()          { /* Task 6 */ }
function maybeLoadMunicipalities()     { /* Task 6 */ }
function loadHex()                     { /* Task 7 */ }
function loadPoints()                  { /* Task 8 */ }
function wirePanelA()                  { /* Task 9 */ }
function wirePanelB()                  { /* Task 9 */ }
async function updateKPIs()            { /* Task 9 */ }
async function loadAllYearData()       { /* Task 10 */ }
function wireScrubber()                { /* Task 10 */ }
function showInsightDistrict()         { /* Task 11 */ }
function showInsightHex()              { /* Task 11 */ }

// ── Init ───────────────────────────────────────────────────────────────────
async function init() {
  await checkApiStatus();
  wirePanelA();
  wirePanelB();
  wireScrubber();
  await Promise.all([loadChoropleth(), updateKPIs(), loadAllYearData()]);
}

document.addEventListener('DOMContentLoaded', () => init().catch(console.error));
```

- [ ] **Step 2: Verify map loads**

Open browser. Dark basemap renders. `deck.Deck` and `Supercluster` present in console (`typeof deck.Deck === 'function'`, `typeof Supercluster === 'function'`). No JS errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/app.js
git commit -m "feat: app.js skeleton — state, map init, deck.gl canvas overlay, zoom state machine"
```

---

### Task 5: Choropleth Layer

**Files:**
- Modify: `frontend/app.js` — replace `loadChoropleth` stub, add `renderLegend`, `syncLegendVisibility`

**Interfaces:**
- Consumes: `state.year`, `state.category`, `state.participant`, `apiFetch`, `scaleColor`, `layers.choropleth`, `map.getZoom()`
- Produces: `loadChoropleth()` — async; `renderLegend()` — renders fixed legend div; calls `showInsightDistrict` on click (stub from Task 4, implemented Task 11)

- [ ] **Step 1: Replace `loadChoropleth` stub**

Find and replace the stub line `function loadChoropleth() { /* Task 5 */ }` with:

```js
async function loadChoropleth() {
  layers.choropleth.clearLayers();

  let countUrl = `/aggregates/accidents?level=district&year=${state.year}`;
  if (state.category)    countUrl += `&category=${state.category}`;
  if (state.participant) countUrl += `&participant=${state.participant}`;

  const [countRes, geoRes] = await Promise.all([
    apiFetch(countUrl),
    apiFetch('/regions?level=district'),
  ]);

  const lookup = {};
  for (const r of countRes.results) {
    lookup[String(r.region_id)] = (lookup[String(r.region_id)] || 0) + r.accident_count;
  }

  const features = geoRes.results.map(r => ({
    type: 'Feature',
    properties: { ags: String(r.ags), name: r.name },
    geometry: r.geom,
  }));

  const showLabels = map.getZoom() >= 7;

  L.geoJSON(features, {
    style: feature => ({
      fillColor: scaleColor(lookup[feature.properties.ags] || 0),
      fillOpacity: 0.75,
      color: 'rgba(255,255,255,0.08)',
      weight: 1,
    }),
    onEachFeature: (feature, lyr) => {
      const count = lookup[feature.properties.ags] || 0;
      lyr.bindTooltip(
        `<strong>${feature.properties.name}</strong><br>${count.toLocaleString('en-US')} accidents`,
        { sticky: true }
      );
      if (showLabels) {
        lyr.bindTooltip(feature.properties.name, {
          permanent: true, className: 'district-label', direction: 'center',
        });
      }
      lyr.on('mouseover', () => lyr.setStyle({ color: 'rgba(255,255,255,0.25)', weight: 1.5 }));
      lyr.on('mouseout',  () => lyr.setStyle({ color: 'rgba(255,255,255,0.08)', weight: 1 }));
      lyr.on('click', () => showInsightDistrict(feature.properties.ags, feature.properties.name, count));
    },
  }).addTo(layers.choropleth);

  renderLegend();
}

function renderLegend() {
  let el = document.getElementById('choropleth-legend');
  if (!el) {
    el = document.createElement('div');
    el.id = 'choropleth-legend';
    el.className = 'choropleth-legend';
    document.body.appendChild(el);
  }
  el.innerHTML = [
    ['#2D3748','0'], ['#4A4030','1–50'], ['#6B5B3E','51–200'],
    ['#8B6914','201–500'], ['#C2410C','501–1k'], ['#EF4444','1k–3k'], ['#7F1D1D','3k+'],
  ].map(([color, label]) =>
    `<div class="legend-row"><div class="legend-swatch" style="background:${color}"></div><span>${label}</span></div>`
  ).join('');
  syncLegendVisibility();
}
```

Also replace the stub `function syncLegendVisibility() { ... }` — the real version is already in the skeleton from Task 4. If it's a stub, replace it with the actual body:

```js
function syncLegendVisibility() {
  const el = document.getElementById('choropleth-legend');
  if (el) el.classList.toggle('legend-hidden', state.activeLayer !== 'choropleth');
}
```

- [ ] **Step 2: Verify choropleth**

Open browser at zoom 6. Germany covered with colored districts on dark basemap. Hover shows tooltip. Legend visible bottom-right. Zoom to 7 — district names appear. Zoom out — names gone.

- [ ] **Step 3: Commit**

```bash
git add frontend/app.js
git commit -m "feat: choropleth layer — 7-step palette, legend, hover highlight, district labels zoom≥7"
```

---

### Task 6: Municipalities Overlay

**Files:**
- Modify: `frontend/app.js` — replace `loadMunicipalities` and `maybeLoadMunicipalities` stubs

**Interfaces:**
- Consumes: `layers.municipalities`, `map.getZoom()`, `apiFetch`
- Produces: `loadMunicipalities()` — fetches once, lazy; `maybeLoadMunicipalities()` — adds/removes layer at zoom threshold

- [ ] **Step 1: Replace municipality stubs**

Replace both stub lines with:

```js
let municipalitiesLoaded = false;

async function loadMunicipalities() {
  if (municipalitiesLoaded) return;
  municipalitiesLoaded = true;
  try {
    const res = await apiFetch('/regions?level=municipality');
    L.geoJSON(
      res.results.map(r => ({ type: 'Feature', properties: {}, geometry: r.geom })),
      { style: { fillOpacity: 0, color: 'rgba(255,255,255,0.05)', weight: 0.5 }, interactive: false }
    ).addTo(layers.municipalities);
  } catch {
    municipalitiesLoaded = false; // allow retry
  }
}

function maybeLoadMunicipalities() {
  if (map.getZoom() >= 9) {
    if (!map.hasLayer(layers.municipalities)) map.addLayer(layers.municipalities);
    loadMunicipalities();
  } else {
    if (map.hasLayer(layers.municipalities)) map.removeLayer(layers.municipalities);
  }
}
```

- [ ] **Step 2: Verify**

Zoom to 9+. Faint municipality boundaries appear as subtle outlines. Zoom out — boundaries disappear.

- [ ] **Step 3: Commit**

```bash
git add frontend/app.js
git commit -m "feat: municipalities overlay — loads once at zoom≥9, rgba(255,255,255,0.05) outlines"
```

---

### Task 7: Hex Binning Layer

**Files:**
- Modify: `frontend/app.js` — replace `loadHex` stub, add `buildHexLayer(data)`, `showInsightHex` stub update

**Interfaces:**
- Consumes: `deckInstance`, `state.year/participant/category`, `map.getBounds()`, `map.getZoom()`, `SCALE_RGB`
- Produces: `buildHexLayer(data)` returns a `deck.HexagonLayer`; `loadHex()` fetches bbox accidents and calls `deckInstance.setProps`

- [ ] **Step 1: Replace `loadHex` stub**

```js
function buildHexLayer(data) {
  return new deck.HexagonLayer({
    id: 'hex-layer',
    data,
    getPosition: d => d.position,
    radius: map.getZoom() < 10 ? 500 : 200,
    colorRange: SCALE_RGB,
    elevationRange: [0, 500],
    elevationScale: 4,
    upperPercentile: 99,
    coverage: 0.9,
    opacity: 0.75,
    pickable: true,
    extruded: true,
    autoHighlight: true,
    highlightColor: [255, 255, 255, 30],
    onClick: ({ object }) => { if (object) showInsightHex(object); },
  });
}

async function loadHex() {
  const b = map.getBounds();
  let url = `/accidents?year=${state.year}&lat_min=${b.getSouth()}&lat_max=${b.getNorth()}&lon_min=${b.getWest()}&lon_max=${b.getEast()}`;
  if (state.category)    url += `&category=${state.category}`;
  if (state.participant) url += `&participant=${state.participant}`;

  let res;
  try { res = await apiFetch(url); } catch { return; }

  const data = res.results.map(a => ({ position: [a.lon, a.lat], category: a.category }));
  deckInstance.setProps({ layers: [buildHexLayer(data)] });
  updateDynamicStat(`⬡ ${data.length.toLocaleString('en-US')}`, 'in viewport');
}
```

- [ ] **Step 2: Verify hex layer**

Zoom to 9–11 over Germany. 3D hexagonal columns appear colored by density. Tooltip on hover shows accident count. At zoom 10 the hex radius shrinks from 500m to 200m — columns become denser. WebGL errors in console indicate deck.gl version mismatch.

- [ ] **Step 3: Commit**

```bash
git add frontend/app.js
git commit -m "feat: deck.gl HexagonLayer — bbox fetch, 3D extrusion, radius switches at zoom 10"
```

---

### Task 8: Point Map Layer

**Files:**
- Modify: `frontend/app.js` — replace `loadPoints` stub, add `buildHexLayer` (done), `renderSinglePoint(acc)`, `makePulseRing(latlng)`, `clusterColor(points)`, `showDetailCard(acc, latlng)`

**Interfaces:**
- Consumes: `layers.accidents`, `Supercluster` global, `state.year/participant/category`, `map.getBounds()`, `map.getZoom()`
- Produces: `loadPoints()`, `renderSinglePoint(acc)` returns Leaflet marker, `showDetailCard(acc, latlng)` opens popup

- [ ] **Step 1: Replace `loadPoints` stub and add helpers**

```js
const SEV_STYLE = {
  1: { radius: 10, fillColor: '#7F1D1D', color: '#EF4444',              weight: 2 },
  2: { radius: 7,  fillColor: '#EF4444', color: 'rgba(255,255,255,0.3)', weight: 1 },
  3: { radius: 5,  fillColor: '#C2410C', color: 'rgba(255,255,255,0.2)', weight: 1 },
};

function makePulseRing(latlng) {
  return L.marker(latlng, {
    icon: L.divIcon({
      className: '',
      html: '<div class="pulse-ring" style="width:20px;height:20px;margin:-10px 0 0 -10px"></div>',
      iconSize: [0, 0],
    }),
    interactive: false,
  });
}

function clusterColor(leaves) {
  const cats = leaves.map(l => l.properties.category);
  if (cats.includes(1)) return '#7F1D1D';
  if (cats.includes(2)) return '#EF4444';
  return '#C2410C';
}

function renderSinglePoint(acc) {
  const sev = SEV_STYLE[acc.category] || SEV_STYLE[3];
  const marker = L.circleMarker([acc.lat, acc.lon], { ...sev, fillOpacity: 0.85 });
  marker.on('click', () => showDetailCard(acc, [acc.lat, acc.lon]));
  return marker;
}

async function loadPoints() {
  layers.accidents.clearLayers();
  const b = map.getBounds();
  let url = `/accidents?year=${state.year}&lat_min=${b.getSouth()}&lat_max=${b.getNorth()}&lon_min=${b.getWest()}&lon_max=${b.getEast()}`;
  if (state.category)    url += `&category=${state.category}`;
  if (state.participant) url += `&participant=${state.participant}`;

  let res;
  try { res = await apiFetch(url); } catch { return; }
  const accidents = res.results;

  const z = map.getZoom();
  const useCluster = z < 14;

  if (useCluster) {
    const sc = new Supercluster({ radius: 30, maxZoom: 16 });
    sc.load(accidents.map(a => ({
      type: 'Feature',
      properties: { category: a.category, acc: a },
      geometry: { type: 'Point', coordinates: [a.lon, a.lat] },
    })));
    const bounds = [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()];
    for (const c of sc.getClusters(bounds, Math.floor(z))) {
      const [lon, lat] = c.geometry.coordinates;
      if (c.properties.cluster) {
        const count  = c.properties.point_count;
        const leaves = sc.getLeaves(c.properties.cluster_id, Infinity);
        const color  = clusterColor(leaves);
        const size   = Math.min(40 + count * 0.5, 60);
        L.marker([lat, lon], {
          icon: L.divIcon({
            className: '',
            html: `<div class="cluster-marker" style="width:${size}px;height:${size}px;background:${color}">${count}</div>`,
            iconSize: [size, size], iconAnchor: [size/2, size/2],
          }),
        }).on('click', () => map.setZoom(map.getZoom() + 1)).addTo(layers.accidents);
      } else {
        const acc = c.properties.acc;
        renderSinglePoint(acc).addTo(layers.accidents);
        if (acc.category === 1) makePulseRing([acc.lat, acc.lon]).addTo(layers.accidents);
      }
    }
  } else {
    for (const acc of accidents) {
      renderSinglePoint(acc).addTo(layers.accidents);
      if (acc.category === 1) makePulseRing([acc.lat, acc.lon]).addTo(layers.accidents);
    }
  }

  updateDynamicStat(accidents.length.toLocaleString('en-US'), 'in viewport');
}

function showDetailCard(acc, latlng) {
  const sevLabel = acc.category === 1 ? 'Fatal' : acc.category === 2 ? 'Serious' : 'Minor';
  const sevClass = acc.category === 1 ? 'fatal' : acc.category === 2 ? 'serious' : 'minor';

  const parts = [];
  if (acc.participant_car)        parts.push('Car');
  if (acc.participant_bike)       parts.push('Bike');
  if (acc.participant_pedestrian) parts.push('Pedestrian');
  if (acc.participant_truck)      parts.push('Truck');
  if (acc.participant_moped)      parts.push('Moped');

  const year = acc.year || '—';

  L.popup({ className: 'detail-card', closeButton: true, maxWidth: 280 })
    .setLatLng(latlng)
    .setContent(`
      <div class="card-header">
        <span class="card-severity card-severity--${sevClass}">${sevLabel}</span>
        <span class="card-datetime">${year}</span>
      </div>
      <div class="card-body">
        ${acc.region_name ? `<div>${acc.region_name}</div>` : ''}
        ${parts.length ? `<div style="color:#9CA3AF;font-size:12px">${parts.join(', ')}</div>` : ''}
      </div>
    `)
    .openOn(map);
}
```

- [ ] **Step 2: Verify point layer**

Zoom to 12+. Circle markers appear: crimson for fatal (10px), red for serious (7px), orange for minor (5px). Fatal points have expanding pulse ring. Zoom 12–14: clusters appear as colored circles with count. Click cluster → zoom in. Click point → detail card popup.

- [ ] **Step 3: Commit**

```bash
git add frontend/app.js
git commit -m "feat: point map — severity circles, Supercluster clustering, fatal pulse, detail card"
```

---

### Task 9: Floating Panels + Stats

**Files:**
- Modify: `frontend/app.js` — replace `wirePanelA`, `wirePanelB`, `updateKPIs` stubs

**Interfaces:**
- Consumes: DOM from Task 2, `state`, `switchLayer`, `targetLayerForZoom`, `reloadActiveLayer`, `apiFetch`
- Produces: `wirePanelA()`, `wirePanelB()`, `updateKPIs()`

- [ ] **Step 1: Replace `wirePanelA` stub**

```js
function wirePanelA() {
  const btn      = document.getElementById('panel-a-btn');
  const dropdown = document.getElementById('panel-a-dropdown');

  btn.addEventListener('click', e => {
    e.stopPropagation();
    dropdown.classList.toggle('hidden');
  });
  document.addEventListener('click', () => dropdown.classList.add('hidden'));

  dropdown.querySelectorAll('.mode-option').forEach(opt => {
    opt.addEventListener('click', () => {
      state.mode = opt.dataset.mode;
      dropdown.querySelectorAll('.mode-option').forEach(o => o.classList.remove('mode-option--active'));
      opt.classList.add('mode-option--active');
      dropdown.classList.add('hidden');

      if (state.mode === 'auto') {
        switchLayer(targetLayerForZoom(map.getZoom()));
      } else {
        const nameMap = { district: 'choropleth', hex: 'hex', point: 'point' };
        switchLayer(nameMap[state.mode]);
      }
    });
  });
}
```

- [ ] **Step 2: Replace `wirePanelB` stub**

```js
function wirePanelB() {
  document.getElementById('filter-participant').addEventListener('click', e => {
    const btn = e.target.closest('.filter-pill');
    if (!btn) return;
    document.querySelectorAll('#filter-participant .filter-pill').forEach(b => b.classList.remove('filter-pill--active'));
    btn.classList.add('filter-pill--active');
    state.participant = btn.dataset.participant;
    reloadActiveLayer();
  });

  document.getElementById('filter-severity').addEventListener('click', e => {
    const btn = e.target.closest('.filter-pill');
    if (!btn) return;
    document.querySelectorAll('#filter-severity .filter-pill').forEach(b => b.classList.remove('filter-pill--active'));
    btn.classList.add('filter-pill--active');
    state.category = btn.dataset.category;
    reloadActiveLayer();
  });
}
```

- [ ] **Step 3: Replace `updateKPIs` stub**

```js
async function updateKPIs() {
  let url = `/aggregates/accidents?year=${state.year}`;
  if (state.category)    url += `&category=${state.category}`;
  if (state.participant) url += `&participant=${state.participant}`;

  try {
    const [res, fatalRes] = await Promise.all([
      apiFetch(url),
      apiFetch(`/aggregates/accidents?year=${state.year}&category=1`),
    ]);
    const total = res.metadata?.total_count
      ?? res.results.reduce((s, r) => s + r.accident_count, 0);
    const fatal = fatalRes.metadata?.total_count
      ?? fatalRes.results.reduce((s, r) => s + r.accident_count, 0);
    document.querySelector('#stat-total .stat-num').textContent = total.toLocaleString('en-US');
    document.querySelector('#stat-fatal .stat-num').textContent = fatal.toLocaleString('en-US');
  } catch { /* keep dashes */ }
}
```

- [ ] **Step 4: Verify panels**

Panel A dropdown opens/closes. Selecting "Hex" at zoom 6 forces hex layer. Selecting "Auto" resumes zoom-driven switching. Filter pills toggle active state and reload map. Stats strip shows live accident/fatal counts.

- [ ] **Step 5: Commit**

```bash
git add frontend/app.js
git commit -m "feat: Panel A mode selector, Panel B filters, Panel C stats strip"
```

---

### Task 10: Timeline Scrubber

**Files:**
- Modify: `frontend/app.js` — replace `loadAllYearData` and `wireScrubber` stubs, add `renderScrubberSparkline()`, `updateScrubberPlayhead()`

**Interfaces:**
- Consumes: `apiFetch('/aggregates/accidents')` (no year = all years), `state.yearData`, DOM `#scrubber-svg`, `#scrubber-track`, `#scrubber-playhead`, `#scrubber-play`
- Produces: `loadAllYearData()` populates `state.yearData` and renders sparkline; `wireScrubber()` wires drag + play

- [ ] **Step 1: Replace `loadAllYearData` stub**

```js
const YEARS = [2016,2017,2018,2019,2020,2021,2022,2023,2024];

async function loadAllYearData() {
  try {
    const [allRes, fatalRes, seriousRes] = await Promise.all([
      apiFetch('/aggregates/accidents'),
      apiFetch('/aggregates/accidents?category=1'),
      apiFetch('/aggregates/accidents?category=2'),
    ]);

    const total = {}, fatal = {}, serious = {};
    for (const r of allRes.results)     total[r.year]   = (total[r.year]   || 0) + r.accident_count;
    for (const r of fatalRes.results)   fatal[r.year]   = (fatal[r.year]   || 0) + r.accident_count;
    for (const r of seriousRes.results) serious[r.year] = (serious[r.year] || 0) + r.accident_count;

    for (const y of YEARS) {
      state.yearData[y] = {
        total:   total[y]   || 0,
        fatal:   fatal[y]   || 0,
        serious: serious[y] || 0,
        minor:   (total[y] || 0) - (fatal[y] || 0) - (serious[y] || 0),
      };
    }
    renderScrubberSparkline();
    updateScrubberPlayhead();
  } catch { /* sparkline stays empty */ }
}

function renderScrubberSparkline() {
  const svg = document.getElementById('scrubber-svg');
  if (!svg) return;
  const maxTotal = Math.max(...YEARS.map(y => state.yearData[y]?.total || 0), 1);
  const W = 270, H = 40;
  const colW = W / YEARS.length;
  const barW = colW - 2;

  svg.innerHTML = YEARS.map((y, i) => {
    const d = state.yearData[y] || {};
    const x = i * colW + 1;
    const fH = ((d.fatal   || 0) / maxTotal) * H;
    const sH = ((d.serious || 0) / maxTotal) * H;
    const mH = ((d.minor   || 0) / maxTotal) * H;
    let yPos = H;
    const rects = [];
    if (mH > 0) { yPos -= mH; rects.push(`<rect x="${x}" y="${yPos}" width="${barW}" height="${mH}" fill="#C2410C"/>`); }
    if (sH > 0) { yPos -= sH; rects.push(`<rect x="${x}" y="${yPos}" width="${barW}" height="${sH}" fill="#EF4444"/>`); }
    if (fH > 0) { yPos -= fH; rects.push(`<rect x="${x}" y="${yPos}" width="${barW}" height="${fH}" fill="#7F1D1D"/>`); }
    return rects.join('');
  }).join('');
}

function updateScrubberPlayhead() {
  const idx = YEARS.indexOf(state.year);
  const pct = idx / (YEARS.length - 1);
  const ph = document.getElementById('scrubber-playhead');
  if (ph) ph.style.left = `${pct * 100}%`;

  document.querySelectorAll('.scrubber-labels span').forEach((s, i) => {
    s.classList.toggle('active', i === idx);
  });
}
```

- [ ] **Step 2: Replace `wireScrubber` stub**

```js
function wireScrubber() {
  const track   = document.getElementById('scrubber-track');
  const playBtn = document.getElementById('scrubber-play');

  function yearFromClientX(clientX) {
    const rect = track.getBoundingClientRect();
    const pct  = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
    return YEARS[Math.round(pct * (YEARS.length - 1))];
  }

  function setYear(y) {
    if (y === state.year) return;
    state.year = y;
    updateScrubberPlayhead();
    reloadActiveLayer();
    updateKPIs();
  }

  let dragging = false;
  document.getElementById('scrubber-playhead').addEventListener('mousedown', () => { dragging = true; });
  document.addEventListener('mousemove', e => { if (dragging) setYear(yearFromClientX(e.clientX)); });
  document.addEventListener('mouseup',   () => { dragging = false; });
  track.addEventListener('click', e => setYear(yearFromClientX(e.clientX)));

  playBtn.addEventListener('click', () => {
    if (state.playInterval) {
      clearInterval(state.playInterval);
      state.playInterval = null;
      playBtn.textContent = '▶';
      return;
    }
    playBtn.textContent = '⏸';
    state.playInterval = setInterval(() => {
      setYear(YEARS[(YEARS.indexOf(state.year) + 1) % YEARS.length]);
    }, 1500);
  });
}
```

- [ ] **Step 3: Verify scrubber**

Stacked sparkline bars visible (minor=orange, serious=red, fatal=crimson). Playhead at 2024 position. Drag playhead to 2016 → choropleth updates. Click ▶ → years cycle. Click ⏸ → stops.

- [ ] **Step 4: Commit**

```bash
git add frontend/app.js
git commit -m "feat: timeline scrubber — stacked sparkline, draggable playhead, play/pause"
```

---

### Task 11: Insight Panel

**Files:**
- Modify: `frontend/app.js` — replace `showInsightDistrict` and `showInsightHex` stubs, add `openInsightPanel(html)`, `closeInsightPanel()`, `reverseGeocode(lat, lng)`

**Interfaces:**
- Consumes: `#insight-panel`, `#insight-content`, `#insight-close`, `YEARS`, `state.year`, `apiFetch`, Nominatim (`https://nominatim.openstreetmap.org`)
- Produces: `openInsightPanel(html)`, `closeInsightPanel()`, `showInsightDistrict(ags, name, count)`, `showInsightHex(object)`

- [ ] **Step 1: Add panel open/close (before stub lines)**

```js
function openInsightPanel(html) {
  document.getElementById('insight-content').innerHTML = html;
  document.getElementById('insight-panel').classList.add('open');
}

function closeInsightPanel() {
  document.getElementById('insight-panel').classList.remove('open');
}

document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('insight-close').addEventListener('click', closeInsightPanel);
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closeInsightPanel(); });
});
```

- [ ] **Step 2: Replace `showInsightDistrict` stub**

```js
async function showInsightDistrict(ags, name, count) {
  let trend = YEARS.map(() => 0);
  try {
    const res = await apiFetch(`/aggregates/accidents?level=district&ags=${ags}`);
    const byYear = {};
    for (const r of res.results) byYear[r.year] = (byYear[r.year] || 0) + r.accident_count;
    trend = YEARS.map(y => byYear[y] || 0);
  } catch { /* show zeros */ }

  const maxT = Math.max(...trend, 1);
  const colW = 14;
  const sparkBars = trend.map((v, i) => {
    const h = (v / maxT) * 30;
    const fill = (v === Math.max(...trend)) ? '#EF4444' : '#8B6914';
    return `<rect x="${i * colW}" y="${30 - h}" width="${colW - 2}" height="${h}" fill="${fill}"/>`;
  }).join('');

  openInsightPanel(`
    <div class="insight-title">${name}</div>
    <div class="insight-subtitle">District · ${state.year}</div>
    <div class="insight-stat">
      <span>Total accidents</span>
      <span class="insight-stat-val">${count.toLocaleString('en-US')}</span>
    </div>
    <div style="margin-top:16px">
      <div style="font-size:11px;color:#6B7280;margin-bottom:6px">Trend 2016–2024</div>
      <svg viewBox="0 0 ${YEARS.length * colW} 32" style="width:100%;height:40px">
        ${sparkBars}
      </svg>
      <div style="display:flex;justify-content:space-between;font-size:10px;color:#6B7280;margin-top:2px">
        <span>2016</span><span>2024</span>
      </div>
    </div>
  `);
}
```

- [ ] **Step 3: Replace `showInsightHex` stub and add geocoder**

```js
const geoCache = new Map();

async function reverseGeocode(lat, lng) {
  const key = `${lat.toFixed(3)},${lng.toFixed(3)}`;
  if (geoCache.has(key)) return geoCache.get(key);
  try {
    const res  = await fetch(`https://nominatim.openstreetmap.org/reverse?lat=${lat}&lon=${lng}&format=json`);
    const data = await res.json();
    const addr = data.address?.road || data.display_name || `${lat.toFixed(3)}, ${lng.toFixed(3)}`;
    geoCache.set(key, addr);
    return addr;
  } catch {
    return `${lat.toFixed(3)}, ${lng.toFixed(3)}`;
  }
}

async function showInsightHex(object) {
  const points  = object.points || [];
  const count   = points.length;
  const fatal   = points.filter(p => p.source?.category === 1).length;
  const serious = points.filter(p => p.source?.category === 2).length;
  const minor   = count - fatal - serious;
  const lat = object.position?.[1] ?? 0;
  const lng = object.position?.[0] ?? 0;
  const addr = await reverseGeocode(lat, lng);

  openInsightPanel(`
    <div class="insight-title">Hex Cell</div>
    <div class="insight-subtitle">${addr}</div>
    <div class="insight-stat">
      <span>Total accidents</span><span class="insight-stat-val">${count}</span>
    </div>
    <div class="insight-stat">
      <span>Fatal</span>
      <span class="insight-stat-val" style="color:#7F1D1D">${fatal}</span>
    </div>
    <div class="insight-stat">
      <span>Serious</span>
      <span class="insight-stat-val" style="color:#EF4444">${serious}</span>
    </div>
    <div class="insight-stat">
      <span>Minor</span>
      <span class="insight-stat-val" style="color:#C2410C">${minor}</span>
    </div>
  `);
}
```

- [ ] **Step 4: Verify insight panel**

Click a district in choropleth → panel slides in from right with district name, count, trend sparkline. Click hex cell → panel shows breakdown + reverse-geocoded address. Press Escape or ✕ → panel slides out.

- [ ] **Step 5: Commit**

```bash
git add frontend/app.js
git commit -m "feat: insight panel — district trend, hex breakdown, Nominatim reverse-geocode"
```

---

### Task 12: Smoke Test + Final Commit

**Files:**
- None (verification only)

- [ ] **Step 1: Full smoke test**

Start API: `docker-compose up` or `cd DWT_Project && uvicorn api.main:app --reload`.

Open `http://localhost:8000/` or serve `frontend/` and verify:

1. **Load (zoom 6)**: Dark map, choropleth districts visible, legend bottom-right, stats strip populated with numbers, mode badge shows "🗺️ District View"
2. **Zoom to 8**: Layer crossfades to hex grid with 3D columns, badge → "⬡ Hex View", dynamic stat shows "⬡ N in viewport"
3. **Zoom to 10**: Hex radius shrinks from 500m to 200m columns
4. **Zoom to 12**: Layer crossfades to point markers, badge → "📍 Point View"
5. **Zoom back to 9**: Requires dropping 0.5 zoom past threshold before switching — hysteresis working
6. **Municipalities**: At zoom 9+ faint district sub-boundaries appear
7. **Filter "🚲 Bike"**: Layer reloads with bike-only data, stats update
8. **Severity "Fatal"**: Only fatal points shown (crimson with pulse rings)
9. **Year scrubber**: Drag to 2016 → choropleth updates; drag to 2024 → updates again
10. **Play button**: Click ▶ → years cycle every 1.5s; ⏸ stops
11. **Panel A "Hex" at zoom 6**: Forced hex layer at zoom where choropleth would normally show
12. **District click**: Insight panel slides in with district name + trend sparkline
13. **Hex click**: Insight panel shows cell breakdown + street name
14. **Point click (zoom ≥ 12)**: Detail card popup appears near clicked point
15. **Escape key**: Closes insight panel
16. **Console**: Zero JS errors throughout

- [ ] **Step 2: Final commit if all green**

```bash
git add -A
git commit -m "feat: zoom-driven accident map — choropleth/hex/point, floating panels, scrubber complete"
```

---

## Spec Coverage Self-Review

| Spec Requirement | Task |
|---|---|
| Zoom thresholds 5–8 / 8–12 / 12–18 | 4 |
| Hysteresis 0.5 zoom | 4 |
| Crossfade 400ms cubic-bezier | 3, 4 |
| Zoom mode badge | 4 |
| Choropleth 7-step palette | 5 |
| District borders rgba(255,255,255,0.08) | 5 |
| Hover brighten border + brightness(1.15) | 5 |
| District labels zoom ≥ 7 | 5 |
| Collapsible legend | 5 |
| Choropleth → insight panel | 5, 11 |
| HexagonLayer config (radius/colorRange/elevation) | 7 |
| Hex radius switches at zoom 10 | 7 |
| Hex tooltip (count · fatal) | 4 (getTooltip) |
| Hex click → insight panel | 7, 11 |
| Point severity styling (3 tiers) | 8 |
| Fatal pulse animation | 3 (CSS), 8 |
| Supercluster clustering zoom 12–14 | 8 |
| Cluster color weighted by severity | 8 |
| Detail card popup | 8 |
| Panel A mode selector + dropdown | 9 |
| Panel A closes on selection/outside click | 9 |
| Panel B participant + severity filters | 9 |
| Panel C stats strip | 9 |
| Dynamic stat (hex count / viewport count) | 7, 8 |
| Timeline sparkline (stacked fatal/serious/minor) | 10 |
| Draggable playhead | 10 |
| Play button 1.5s cycling | 10 |
| Insight panel slide-out (district + hex) | 11 |
| Nominatim geocode memoized in JS Map | 11 |
| Municipalities overlay zoom ≥ 9 | 6 |
| Sidebar removed | 2 |
| Hotspots/safe zones removed | 2 |
| Vendor deck.gl + Supercluster | 1 |
| CSP unchanged | 2 |
| deck.gl canvas synced to Leaflet viewport | 4 |
| moveend debounce 500ms for hex/point | 4 |
