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
function loadHex()                     { /* Task 7 */ }
function loadPoints()                  { /* Task 8 */ }
function wirePanelA()                  { /* Task 9 */ }
function wirePanelB()                  { /* Task 9 */ }
async function updateKPIs()            { /* Task 9 */ }
async function loadAllYearData()       { /* Task 10 */ }
function wireScrubber()                { /* Task 10 */ }
function showInsightDistrict(ags, name, count) { console.log('district click', ags, name, count); }
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
