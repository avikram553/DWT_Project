// Unfallkarte Deutschland — Zoom-Driven Visualization
'use strict';

// ── State ──────────────────────────────────────────────────────────────────
const state = {
  year: 2024,
  participant: '',      // '' | 'car' | 'bike' | 'pedestrian' | 'truck' | 'moped'
  category: '',         // '' | '2' | '1'
  mode: 'auto',         // 'auto' | 'district' | 'hex' | 'point'
  activeLayer: 'choropleth',
  playInterval: null,
  yearData: {},         // year → {total, fatal, serious, minor}
  cityBounds: null,     // {south, north, west, east} when city jump active
  cityJumpInProgress: false,
  nearbyLocation: null, // {lat, lon, radiusM} when nearby hazards is active
};

// ── Years ──────────────────────────────────────────────────────────────────
const YEARS = [2016,2017,2018,2019,2020,2021,2022,2023,2024];

// ── Color scale ────────────────────────────────────────────────────────────
const SCALE = [
  { max: 0,        color: '#E5E7EB' },
  { max: 50,       color: '#FED7AA' },
  { max: 200,      color: '#FB923C' },
  { max: 500,      color: '#EA580C' },
  { max: 1000,     color: '#DC2626' },
  { max: 3000,     color: '#991B1B' },
  { max: Infinity, color: '#450A0A' },
];

// RGB arrays for deck.gl colorRange (same 7 steps as SCALE)
const SCALE_RGB = [
  [229,231,235],[254,215,170],[251,146,60],
  [234,88,12],[220,38,38],[153,27,27],[69,10,10],
];

function scaleColor(count) {
  for (const s of SCALE) if (count <= s.max) return s.color;
  return '#7F1D1D';
}

// ── Map ────────────────────────────────────────────────────────────────────
const map = L.map('map', {
  zoom: 6, center: [51.2, 10.5], zoomControl: false,
  zoomSnap: 0.5,
  zoomDelta: 0.5,
  wheelPxPerZoomLevel: 60,
  zoomAnimation: true,
  attributionControl: false,
});
L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
  attribution: '© OpenStreetMap contributors © CARTO',
  subdomains: 'abcd', maxZoom: 19,
}).addTo(map);
L.control.zoom({ position: 'bottomright' }).addTo(map);

// ── deck.gl canvas overlay ─────────────────────────────────────────────────
const deckCanvas = document.createElement('canvas');
deckCanvas.id = 'deck-canvas';
document.getElementById('map').appendChild(deckCanvas);
let deckInstance = null;
let deckLoadPromise = null;

function getDeckViewState() {
  const c = map.getCenter();
  // deck.gl uses 512px tile convention; Leaflet uses 256px → subtract 1 zoom level
  return { longitude: c.lng, latitude: c.lat, zoom: map.getZoom() - 1, pitch: 30, bearing: 0 };
}

function loadScriptOnce(src) {
  return new Promise((resolve, reject) => {
    const existing = document.querySelector(`script[src="${src}"]`);
    if (existing) {
      existing.addEventListener('load', resolve, { once: true });
      existing.addEventListener('error', reject, { once: true });
      if (window.deck) resolve();
      return;
    }
    const script = document.createElement('script');
    script.src = src;
    script.async = true;
    script.onload = resolve;
    script.onerror = reject;
    document.head.appendChild(script);
  });
}

async function ensureDeckInstance() {
  if (deckInstance) return deckInstance;
  if (!deckLoadPromise) {
    deckLoadPromise = loadScriptOnce('vendor/deck.gl/deck.gl.min.js').then(() => {
      deckInstance = new deck.Deck({
        canvas: deckCanvas,
        width: '100%',
        height: '100%',
        initialViewState: getDeckViewState(),
        controller: false,
        layers: [],
        onError: (error) => {
          console.warn('deck.gl disabled:', error?.message || error);
          deckCanvas.style.opacity = '0';
          deckCanvas.classList.remove('hex-active');
          showToast('3D hex rendering is unavailable in this browser.');
          return true;
        },
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
      return deckInstance;
    });
  }
  return deckLoadPromise;
}

map.on('move', () => {
  if (deckInstance) deckInstance.setProps({ viewState: getDeckViewState() });
});

// ── Leaflet layer groups ───────────────────────────────────────────────────
const layers = {
  choropleth:     L.layerGroup().addTo(map),
  municipalities: L.layerGroup(),
  stateBoundary:  L.layerGroup().addTo(map),
  accidents:      L.layerGroup().addTo(map),
  hazards:        L.layerGroup().addTo(map),
  hotspots:       L.layerGroup().addTo(map),
};
const pointRenderer = L.canvas({ padding: 0.35 });
const POINT_EMOJI_MIN_ZOOM = 13;
const POINT_EMOJI_MARKER_LIMITS = [
  { zoom: 16, limit: 2000 },
  { zoom: 15, limit: 1400 },
  { zoom: 14, limit: 900 },
  { zoom: 13, limit: 500 },
];

let districtGeoCache = null;
let districtTrendCache = null;
let municipalityBoundsKey = null;
let activeViewportController = null;
const apiCache = new Map();
const PERSISTENT_CACHE_PREFIX = 'geocrash:v4:';
const ONE_DAY_MS = 24 * 60 * 60 * 1000;

// ── API helper ─────────────────────────────────────────────────────────────
async function apiFetch(path, options = {}) {
  const { cache = true, persist = false, maxAgeMs = ONE_DAY_MS, signal } = options;
  if (cache && apiCache.has(path)) return apiCache.get(path);
  const persistentKey = `${PERSISTENT_CACHE_PREFIX}${path}`;
  if (cache && persist) {
    try {
      const cached = JSON.parse(localStorage.getItem(persistentKey) || 'null');
      if (cached && Date.now() - cached.savedAt < maxAgeMs) {
        apiCache.set(path, cached.data);
        return cached.data;
      }
    } catch {
      localStorage.removeItem(persistentKey);
    }
  }
  const res = await fetch(`http://localhost:8000${path}`, { signal });
  if (!res.ok) throw new Error(`${res.status} ${path}`);
  const data = await res.json();
  if (cache) apiCache.set(path, data);
  if (cache && persist) {
    try {
      localStorage.setItem(persistentKey, JSON.stringify({ savedAt: Date.now(), data }));
    } catch {
      // Storage can be full or unavailable; in-memory caching is still useful.
    }
  }
  return data;
}

function activeViewportSignal() {
  if (activeViewportController) activeViewportController.abort();
  activeViewportController = new AbortController();
  return activeViewportController.signal;
}

function roundedBoundsKey(b, precision = 2) {
  return [
    b.getSouth().toFixed(precision),
    b.getNorth().toFixed(precision),
    b.getWest().toFixed(precision),
    b.getEast().toFixed(precision),
  ].join(',');
}

function distanceMeters(aLat, aLon, bLat, bLon) {
  const toRad = deg => deg * Math.PI / 180;
  const earthRadiusM = 6371000;
  const dLat = toRad(bLat - aLat);
  const dLon = toRad(bLon - aLon);
  const lat1 = toRad(aLat);
  const lat2 = toRad(bLat);
  const h = Math.sin(dLat / 2) ** 2
    + Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon / 2) ** 2;
  return 2 * earthRadiusM * Math.asin(Math.min(1, Math.sqrt(h)));
}

function boundsAround(lat, lon, radiusM) {
  const latDelta = radiusM / 111320;
  const lonDelta = radiusM / (111320 * Math.max(0.2, Math.cos(lat * Math.PI / 180)));
  return {
    south: lat - latDelta,
    north: lat + latDelta,
    west: lon - lonDelta,
    east: lon + lonDelta,
  };
}

// ── Zoom state machine ─────────────────────────────────────────────────────
const ZOOM_HEX   = 9;
const ZOOM_POINT = 12;
const HYSTERESIS = 0.5;
const HEX_POINT_LIMIT = 50000;

function targetLayerForZoom(z, currentLayer = state.activeLayer) {
  const hexExit = ZOOM_HEX - HYSTERESIS;
  const pointExit = ZOOM_POINT - HYSTERESIS;

  if (currentLayer === 'point') {
    if (z >= pointExit) return 'point';
    if (z >= hexExit) return 'hex';
    return 'choropleth';
  }

  if (currentLayer === 'hex') {
    if (z >= ZOOM_POINT) return 'point';
    if (z >= hexExit) return 'hex';
    return 'choropleth';
  }

  if (z >= ZOOM_POINT) return 'point';
  if (z >= ZOOM_HEX) return 'hex';
  return 'choropleth';
}

function syncLegendVisibility() {
  const el = document.getElementById('choropleth-legend');
  if (el) el.classList.toggle('legend-hidden', state.activeLayer !== 'choropleth');
}

function syncModeControl(mode) {
  state.mode = mode;
  document.querySelectorAll('#panel-a-dropdown .mode-option').forEach(o => {
    o.classList.toggle('mode-option--active', o.dataset.mode === mode);
  });
}

function applyLayerVisibility(name) {
  const showChoropleth = name === 'choropleth';
  const showBoundary = name !== 'point';

  if (showChoropleth) {
    if (!map.hasLayer(layers.choropleth)) map.addLayer(layers.choropleth);
  } else if (map.hasLayer(layers.choropleth)) {
    map.removeLayer(layers.choropleth);
  }

  if (showBoundary) {
    if (!map.hasLayer(layers.stateBoundary)) map.addLayer(layers.stateBoundary);
  } else if (map.hasLayer(layers.stateBoundary)) {
    map.removeLayer(layers.stateBoundary);
  }

  if (name === 'point') {
    if (!map.hasLayer(layers.accidents)) map.addLayer(layers.accidents);
  } else {
    layers.accidents.clearLayers();
    if (map.hasLayer(layers.accidents)) map.removeLayer(layers.accidents);
  }

  if (!showChoropleth && map.hasLayer(layers.municipalities)) {
    map.removeLayer(layers.municipalities);
  }

  layers.hazards.clearLayers();
}

function switchLayer(name) {
  state.nearbyLocation = null;
  applyLayerVisibility(name);
  if (state.activeLayer === name) {
    syncLegendVisibility();
    return;
  }

  if (state.activeLayer === 'hex') {
    deckCanvas.style.opacity = '0';
    deckCanvas.classList.remove('hex-active');
    if (deckInstance) deckInstance.setProps({ layers: [] });
  }

  state.activeLayer = name;
  updateZoomBadge(name);
  syncLegendVisibility();

  if (name === 'choropleth') {
    if (!map.hasLayer(layers.choropleth)) map.addLayer(layers.choropleth);
    loadChoropleth();
  } else if (name === 'hex') {
    deckCanvas.style.opacity = '1';
    deckCanvas.classList.add('hex-active');
    loadHex();
  } else if (name === 'point') {
    loadPoints();
  }
}

function onZoomEnd() {
  maybeLoadMunicipalities();
  if (state.mode !== 'auto') return;

  const z = map.getZoom();
  const target = targetLayerForZoom(z);

  if (target === state.activeLayer) {
    // Same layer — reload choropleth so district labels appear/disappear at zoom 7.
    // Hex/point reloads are handled by moveend after the viewport settles.
    if (state.activeLayer === 'choropleth') loadChoropleth();
    return;
  }

  switchLayer(target);
}

map.on('zoomend', onZoomEnd);

function updateZoomBadge(layer) {
  const el = document.getElementById('zoom-badge');
  if (!el) return;
  el.textContent = layer === 'hex' ? '⬡ Hex View'
                 : layer === 'point' ? '📍 Point View'
                 : layer === 'nearby' ? '📍 500 m View'
                 : '🗺️ District View';
}

function updateDynamicStat(val, lbl) {
  document.getElementById('stat-dynamic').classList.remove('hidden');
  document.getElementById('stat-dynamic-val').textContent = val;
  document.getElementById('stat-dynamic-lbl').textContent = lbl;
}

function setMapLoading(visible, label = 'Loading') {
  const el = document.getElementById('map-loading');
  if (!el) return;
  el.textContent = label;
  el.classList.toggle('visible', visible);
}

function runWhenIdle(fn) {
  if ('requestIdleCallback' in window) {
    window.requestIdleCallback(fn, { timeout: 2500 });
  } else {
    setTimeout(fn, 250);
  }
}

// ── Reload active layer on filter / year change ───────────────────────────
function reloadActiveLayer() {
  if (state.activeLayer === 'choropleth') loadChoropleth();
  else if (state.activeLayer === 'hex')   loadHex();
  else if (state.activeLayer === 'point') loadPoints();
  else if (state.activeLayer === 'nearby' && state.nearbyLocation) {
    const { lat, lon, radiusM } = state.nearbyLocation;
    renderNearbyAccidents(lat, lon, radiusM, false)
      .catch(() => showToast('Could not load accidents within 500 m.'));
  }
  updateKPIs();
}

function clearCityBoundsForManualViewportChange() {
  if (!state.cityJumpInProgress) state.cityBounds = null;
}

// ── moveend: reload hex/point for new viewport ─────────────────────────────
let moveendTimer = null;
map.on('zoomstart', clearCityBoundsForManualViewportChange);
map.on('dragstart', clearCityBoundsForManualViewportChange);
map.on('moveend', () => {
  clearTimeout(moveendTimer);
  moveendTimer = setTimeout(() => {
    maybeLoadMunicipalities();
    if (state.activeLayer === 'hex')   loadHex();
    if (state.activeLayer === 'point') loadPoints();
  }, 500);
});

// ── API status ─────────────────────────────────────────────────────────────
async function checkApiStatus() {
  const el = document.getElementById('api-status');
  try {
    await apiFetch('/metadata/sources', { persist: true, maxAgeMs: ONE_DAY_MS });
    el.textContent = '● Live'; el.className = 'api-status live';
  } catch {
    el.textContent = '● Offline'; el.className = 'api-status error';
  }
}

// ── Stubs filled by Tasks 5–11 ─────────────────────────────────────────────
async function loadChoropleth() {
  setMapLoading(true, 'Loading districts');
  layers.choropleth.clearLayers();

  let countUrl = `/aggregates/accidents?level=district&year=${state.year}`;
  if (state.category)    countUrl += `&category=${state.category}`;

  let countRes;
  let geoRes;
  try {
    [countRes, geoRes] = await Promise.all([
      apiFetch(countUrl, { persist: true, maxAgeMs: ONE_DAY_MS }),
      districtGeoCache ?? apiFetch('/data/districts_simplified.json', { persist: true, maxAgeMs: ONE_DAY_MS }).then(r => { districtGeoCache = r; return r; }),
    ]);
  } catch {
    setMapLoading(false);
    return;
  }

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
      fillOpacity: 0.82,
      color: 'rgba(0,0,0,0.15)',
      weight: 0.7,
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
      lyr.on('mouseover', () => lyr.setStyle({ color: 'rgba(0,0,0,0.5)', weight: 1.5 }));
      lyr.on('mouseout',  () => lyr.setStyle({ color: 'rgba(0,0,0,0.15)', weight: 0.7 }));
      lyr.on('click', () => showInsightDistrict(feature.properties.ags, feature.properties.name, count));
    },
  }).addTo(layers.choropleth);

  renderLegend();
  setMapLoading(false);
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
    ['#E5E7EB','0'], ['#FED7AA','1–50'], ['#FB923C','51–200'],
    ['#EA580C','201–500'], ['#DC2626','501–1k'], ['#991B1B','1k–3k'], ['#450A0A','3k+'],
  ].map(([color, label]) =>
    `<div class="legend-row"><div class="legend-swatch" style="background:${color}"></div><span>${label}</span></div>`
  ).join('');
  syncLegendVisibility();
}
async function loadMunicipalities() {
  // Full municipality GeoJSON is too large for interactive rendering.
  // Keep district/state outlines as the fast boundary layer.
  municipalityBoundsKey = `${map.getZoom().toFixed(1)}:${roundedBoundsKey(map.getBounds(), 1)}`;
}

function maybeLoadMunicipalities() {
  if (state.activeLayer !== 'choropleth') {
    if (map.hasLayer(layers.municipalities)) map.removeLayer(layers.municipalities);
    return;
  }

  if (map.getZoom() >= 9) {
    if (!map.hasLayer(layers.municipalities)) map.addLayer(layers.municipalities);
    loadMunicipalities();
  } else {
    if (map.hasLayer(layers.municipalities)) map.removeLayer(layers.municipalities);
    municipalityBoundsKey = null;
  }
}

async function loadStateBoundaries() {
  try {
    const res = await apiFetch('/data/states_simplified.json', { persist: true, maxAgeMs: ONE_DAY_MS });
    const features = res.results.map(r => ({
      type: 'Feature',
      properties: {},
      geometry: r.geom,
    }));
    L.geoJSON(features, {
      style: { fillOpacity: 0, color: 'rgba(13,148,136,0.6)', weight: 1.8 },
      interactive: false,
    }).addTo(layers.stateBoundary);
  } catch { /* non-critical */ }
}

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
  if (map.getZoom() < ZOOM_HEX - HYSTERESIS) {
    syncModeControl('auto');
    switchLayer('choropleth');
    return;
  }

  setMapLoading(true, 'Loading hexes');
  let deckApi;
  try {
    deckApi = await ensureDeckInstance();
  } catch {
    setMapLoading(false);
    showToast('3D hex rendering is unavailable in this browser.');
    return;
  }
  const signal = activeViewportSignal();
  const b = map.getBounds();
  let url = `/accidents?year=${state.year}&lat_min=${b.getSouth()}&lat_max=${b.getNorth()}&lon_min=${b.getWest()}&lon_max=${b.getEast()}&limit=${HEX_POINT_LIMIT}`;
  if (state.category)    url += `&category=${state.category}`;
  if (state.participant) url += `&participant=${state.participant}`;

  let res;
  try { res = await apiFetch(url, { cache: false, signal }); } catch { setMapLoading(false); return; }
  // Rows are ordered by insertion, so a capped result is not a fair viewport sample.
  if ((res.results || []).length >= HEX_POINT_LIMIT) {
    deckApi.setProps({ layers: [] });
    setMapLoading(false);
    updateDynamicStat('Zoom in', 'for hex detail');
    return;
  }

  const data = res.results.map(a => ({ position: [a.lon, a.lat], category: a.category }));
  deckApi.setProps({ layers: [buildHexLayer(data)] });
  updateDynamicStat(`⬡ ${data.length.toLocaleString('en-US')}`, 'in viewport');
  setMapLoading(false);
}

function getSeverityPointStyle(acc) {
  if (acc.category === 1) {
    return {
      radius: map.getZoom() >= 15 ? 5 : 4,
      color: '#7F1D1D',
      fillColor: '#DC2626',
      fillOpacity: 0.78,
      weight: 1,
    };
  }
  if (acc.category === 2) {
    return {
      radius: map.getZoom() >= 15 ? 4.5 : 3.5,
      color: '#9A3412',
      fillColor: '#F97316',
      fillOpacity: 0.68,
      weight: 1,
    };
  }
  return {
    radius: map.getZoom() >= 15 ? 4 : 3,
    color: '#1E3A8A',
    fillColor: '#3B82F6',
    fillOpacity: 0.55,
    weight: 1,
  };
}

const PARTICIPANT_ICON = {
  car: '🚗',
  bike: '🚲',
  pedestrian: '🚶',
  truck: '🚛',
  moped: '🏍️',
  other: '⚠️',
};

function getParticipantIcon(acc) {
  if (state.participant && PARTICIPANT_ICON[state.participant]) {
    return PARTICIPANT_ICON[state.participant];
  }
  if (acc.participant_bike)       return '🚲';
  if (acc.participant_pedestrian) return '🚶';
  if (acc.participant_truck)      return '🚛';
  if (acc.participant_moped)      return '🏍️';
  if (acc.participant_car)        return '🚗';
  return '⚠️';
}

function shouldUseEmojiMarkers(accidentCount, zoom = map.getZoom()) {
  if (zoom < POINT_EMOJI_MIN_ZOOM) return false;
  const rule = POINT_EMOJI_MARKER_LIMITS.find(({ zoom: threshold }) => zoom >= threshold);
  return accidentCount <= (rule?.limit ?? 0);
}

function renderSinglePoint(acc, useEmojiMarker = false) {
  if (useEmojiMarker) {
    const icon = getParticipantIcon(acc);
    const marker = L.marker([acc.lat, acc.lon], {
      icon: L.divIcon({
        className: '',
        html: `<div class="acc-icon">${icon}</div>`,
        iconSize: [22, 22],
        iconAnchor: [11, 11],
      }),
    });
    marker.on('click', () => showDetailCard(acc, [acc.lat, acc.lon]));
    return marker;
  }

  const marker = L.circleMarker([acc.lat, acc.lon], {
    ...getSeverityPointStyle(acc),
    renderer: pointRenderer,
  });
  marker.on('click', () => showDetailCard(acc, [acc.lat, acc.lon]));
  return marker;
}

async function loadPoints() {
  if (map.getZoom() < ZOOM_POINT - HYSTERESIS && !state.cityBounds) {
    syncModeControl('auto');
    switchLayer(targetLayerForZoom(map.getZoom()));
    return;
  }

  layers.accidents.clearLayers();
  setMapLoading(true, 'Loading points');
  const signal = activeViewportSignal();
  const cb = state.cityBounds;
  const south = cb ? cb.south : map.getBounds().getSouth();
  const north = cb ? cb.north : map.getBounds().getNorth();
  const west  = cb ? cb.west  : map.getBounds().getWest();
  const east  = cb ? cb.east  : map.getBounds().getEast();
  let url = `/accidents?year=${state.year}&lat_min=${south}&lat_max=${north}&lon_min=${west}&lon_max=${east}&limit=2000`;
  if (state.category)    url += `&category=${state.category}`;
  if (state.participant) url += `&participant=${state.participant}`;

  let res;
  try { res = await apiFetch(url, { cache: false, signal }); } catch { setMapLoading(false); return; }
  const accidents = res.results;
  const markers = [];
  const useEmojiMarkers = shouldUseEmojiMarkers(accidents.length);

  for (const acc of accidents) {
    markers.push(renderSinglePoint(acc, useEmojiMarkers));
  }
  L.layerGroup(markers).addTo(layers.accidents);

  updateDynamicStat(accidents.length.toLocaleString('en-US'), 'in viewport');
  setMapLoading(false);
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
      syncModeControl(opt.dataset.mode);
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

function wireLeftPanel() {
  // Participant filter
  document.getElementById('lp-participant').addEventListener('click', e => {
    const btn = e.target.closest('.lp-pill');
    if (!btn) return;
    document.querySelectorAll('#lp-participant .lp-pill').forEach(b => b.classList.remove('lp-pill--active'));
    btn.classList.add('lp-pill--active');
    state.participant = btn.dataset.participant;
    reloadActiveLayer();
  });

  // Severity filter
  document.getElementById('lp-severity').addEventListener('click', e => {
    const btn = e.target.closest('.lp-pill');
    if (!btn) return;
    document.querySelectorAll('#lp-severity .lp-pill').forEach(b => b.classList.remove('lp-pill--active'));
    btn.classList.add('lp-pill--active');
    state.category = btn.dataset.category;
    reloadActiveLayer();
  });

  // City jump → enter point view for inspection, then let auto mode handle zoom-out.
  document.getElementById('lp-city').addEventListener('change', e => {
    const val = e.target.value;
    if (!val) return;
    const [lat, lon, rawZoom] = val.split(',').map(Number);
    const z = Math.max(rawZoom, ZOOM_POINT);
    const r = z >= 13 ? 0.07 : z >= 12 ? 0.14 : 0.28;
    state.cityBounds = { south: lat - r, north: lat + r, west: lon - r * 1.6, east: lon + r * 1.6 };
    state.cityJumpInProgress = true;
    syncModeControl('auto');
    switchLayer('point');
    map.flyTo([lat, lon], z, { duration: 1.2 });
    setTimeout(() => {
      state.cityJumpInProgress = false;
      state.cityBounds = null;
      if (state.activeLayer === 'point') loadPoints();
      e.target.value = '';
    }, 1500);
  });

  map.on('dragend', () => { state.cityBounds = null; });

  // Queries
  document.querySelectorAll('#lp-queries .lp-query').forEach(card => {
    const q   = parseInt(card.dataset.q);
    const btn = card.querySelector('.lp-run');
    const out = card.querySelector('.lp-result');
    const selects = card.querySelectorAll('select[data-param]');

    btn.addEventListener('click', async () => {
      const args = {};
      const labels = {};
      selects.forEach(sel => {
        const key = sel.dataset.param;
        args[key] = key === 'year' ? parseInt(sel.value) : sel.value;
        labels[key] = sel.selectedOptions[0]?.textContent ?? '';
      });
      btn.textContent = '…'; btn.classList.add('loading');
      try {
        const res = await EQ_QUERIES[q](args);
        out.innerHTML = formatEqResult(q, res, labels);
        out.classList.remove('hidden');
      } catch {
        out.innerHTML = '<span style="color:#EF4444">Request failed</span>';
        out.classList.remove('hidden');
      } finally {
        btn.textContent = 'Run'; btn.classList.remove('loading');
      }
    });
  });
}

async function updateKPIs() {
  try {
    if (!state.yearData[state.year]) await loadAllYearData();
    const yearly = state.yearData[state.year] || {};
    const total = state.category === '1' ? (yearly.fatal || 0)
      : state.category === '2' ? (yearly.serious || 0)
      : (yearly.total || 0);
    const fatal = yearly.fatal || 0;
    document.querySelector('#stat-total .stat-num').textContent = total.toLocaleString('en-US');
    document.querySelector('#stat-fatal .stat-num').textContent = fatal.toLocaleString('en-US');
  } catch { /* keep dashes */ }
}
async function loadAllYearData() {
  try {
    const res = await apiFetch('/data/year_summary.json', { persist: true, maxAgeMs: ONE_DAY_MS });
    const byYear = {};
    for (const r of res.results) byYear[r.year] = r;

    for (const y of YEARS) {
      const d = byYear[y] || {};
      state.yearData[y] = {
        total:   d.total   || 0,
        fatal:   d.fatal   || 0,
        serious: d.serious || 0,
        minor:   d.minor   || 0,
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
    }, 3000);
  });
}
// ── Insight panel ──────────────────────────────────────────────────────────
function openInsightPanel(html) {
  document.getElementById('insight-content').innerHTML = html;
  document.getElementById('insight-panel').classList.add('open');
}

function closeInsightPanel() {
  document.getElementById('insight-panel').classList.remove('open');
}

async function showInsightDistrict(ags, name, count) {
  let trend = YEARS.map(() => 0);
  try {
    const res = districtTrendCache ?? await apiFetch('/aggregates/accidents?level=district', { persist: true, maxAgeMs: ONE_DAY_MS });
    districtTrendCache = res;
    const byYear = {};
    for (const r of res.results) {
      if (String(r.region_id) === ags) byYear[r.year] = (byYear[r.year] || 0) + r.accident_count;
    }
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
      <span>Accidents (${zone.year_from}–${zone.year_to})</span>
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

function enterNearbyHazardsMode(lat, lon, radiusM) {
  state.mode = 'nearby';
  state.activeLayer = 'nearby';
  state.nearbyLocation = { lat, lon, radiusM };
  state.cityBounds = null;

  document.querySelectorAll('#panel-a-dropdown .mode-option')
    .forEach(o => o.classList.remove('mode-option--active'));

  if (deckInstance) deckInstance.setProps({ layers: [] });
  deckCanvas.style.opacity = '0';
  deckCanvas.classList.remove('hex-active');

  layers.choropleth.clearLayers();
  layers.municipalities.clearLayers();
  layers.stateBoundary.clearLayers();
  layers.accidents.clearLayers();
  layers.hazards.clearLayers();

  if (map.hasLayer(layers.choropleth)) map.removeLayer(layers.choropleth);
  if (map.hasLayer(layers.municipalities)) map.removeLayer(layers.municipalities);
  if (map.hasLayer(layers.stateBoundary)) map.removeLayer(layers.stateBoundary);
  if (map.hasLayer(layers.accidents)) map.removeLayer(layers.accidents);
  if (!map.hasLayer(layers.hazards)) map.addLayer(layers.hazards);

  updateZoomBadge('nearby');
  syncLegendVisibility();
}

async function fetchNearbyAccidents(lat, lon, radiusM, signal) {
  const b = boundsAround(lat, lon, radiusM);
  const pageSize = 5000;
  const maxRows = 20000;
  const matches = [];

  for (let offset = 0; offset < maxRows; offset += pageSize) {
    let url = `/accidents?lat_min=${b.south}&lat_max=${b.north}&lon_min=${b.west}&lon_max=${b.east}&limit=${pageSize}&offset=${offset}`;
    if (state.category)    url += `&category=${state.category}`;
    if (state.participant) url += `&participant=${state.participant}`;
    const res = await apiFetch(url, { cache: false, signal });
    const rows = res.results || [];

    for (const acc of rows) {
      if (acc.year < 2016 || acc.year > 2024) continue;
      const distanceM = Math.round(distanceMeters(lat, lon, acc.lat, acc.lon));
      if (distanceM <= radiusM) matches.push({ ...acc, distance_m: distanceM });
    }

    if (rows.length < pageSize) break;
  }

  return matches.sort((a, b) => a.distance_m - b.distance_m || a.year - b.year);
}

async function renderNearbyAccidents(lat, lon, radiusM, flyToLocation) {
  setMapLoading(true, 'Loading 500 m accidents');
  layers.hazards.clearLayers();
  const signal = activeViewportSignal();
  const detailZoom = 16;
  if (flyToLocation) map.flyTo([lat, lon], detailZoom, { duration: 1.2 });

  try {
    let accidents;
    try {
      accidents = await fetchNearbyAccidents(lat, lon, radiusM, signal);
    } catch (err) {
      // A newer load superseded this one and will render instead.
      if (err.name === 'AbortError') return;
      throw err;
    }

    L.circle([lat, lon], {
      radius: radiusM,
      color: '#2563EB',
      weight: 2,
      opacity: 0.75,
      fillColor: '#3B82F6',
      fillOpacity: 0.08,
      interactive: false,
    }).addTo(layers.hazards);

    L.marker([lat, lon], {
      icon: L.divIcon({
        className: '',
        html: '<div style="width:14px;height:14px;border-radius:50%;background:#3B82F6;border:3px solid #fff;box-shadow:0 0 6px rgba(59,130,246,0.8)"></div>',
        iconSize: [14, 14],
        iconAnchor: [7, 7],
      }),
    }).addTo(layers.hazards);

    if (accidents.length === 0) {
      showToast('No accidents found within 500 m of your location.');
    } else {
      const markerZoom = flyToLocation ? detailZoom : map.getZoom();
      const useEmojiMarkers = shouldUseEmojiMarkers(accidents.length, markerZoom);
      for (const acc of accidents) renderSinglePoint(acc, useEmojiMarkers).addTo(layers.hazards);
    }

    updateDynamicStat(accidents.length.toLocaleString('en-US'), 'within 500 m');
  } finally {
    if (!signal.aborted) setMapLoading(false);
  }
}

async function loadNearbyHazards() {
  const btn = document.getElementById('btn-nearby-hazards');
  btn.textContent = 'Loading…';
  btn.disabled = true;

  if (!navigator.geolocation) {
    showToast('Geolocation not supported by your browser.');
    btn.textContent = '📍 500 m Accidents';
    btn.disabled = false;
    return;
  }

  navigator.geolocation.getCurrentPosition(
    async (pos) => {
      const lat = pos.coords.latitude;
      const lon = pos.coords.longitude;
      const radiusM = 500;
      enterNearbyHazardsMode(lat, lon, radiusM);

      try {
        await renderNearbyAccidents(lat, lon, radiusM, true);
      } catch (err) {
        const msg = String(err).includes('422')
          ? 'Your location is outside Germany.'
          : 'Could not load accidents within 500 m.';
        showToast(msg);
      }
      btn.textContent = '📍 500 m Accidents';
      btn.disabled = false;
    },
    () => {
      showToast('Location access denied — allow location in your browser.');
      setMapLoading(false);
      btn.textContent = '📍 500 m Accidents';
      btn.disabled = false;
    }
  );
}

function wireNearbyHazards() {
  document.getElementById('btn-nearby-hazards')
    .addEventListener('click', loadNearbyHazards);
}

const HOTSPOT_CLICK_MIN_ZOOM = POINT_EMOJI_MIN_ZOOM;

function loadHotspotHazards() {
  const btn = document.getElementById('btn-hotspot-hazards');

  if (map.getZoom() < HOTSPOT_CLICK_MIN_ZOOM) {
    showToast('Zoom in closer to use this.');
    return;
  }

  btn.textContent = '📍 Click the map…';
  btn.disabled = true;
  map.getContainer().style.cursor = 'crosshair';

  map.once('click', async (e) => {
    map.getContainer().style.cursor = '';
    layers.hotspots.clearLayers();

    try {
      const { lat, lng } = e.latlng;
      const res = await apiFetch(`/zones/nearest?lat=${lat}&lon=${lng}`);
      const zones = res.results || [];

      if (zones.length === 0) {
        showToast('No hotspots found near that point.');
      } else {
        for (const zone of zones) {
          const [zLat, zLon] = cellCentroid(zone.cell_geom);
          L.marker([zLat, zLon], {
            icon: L.divIcon({
              className: '',
              html: '<div class="hazard-marker"></div>',
              iconSize: [20, 20],
              iconAnchor: [10, 10],
            }),
          }).on('click', () => showInsightHazard(zone))
            .addTo(layers.hotspots);
        }
      }
    } catch (err) {
      const msg = String(err).includes('422')
        ? 'That point is outside Germany.'
        : 'Could not load hotspots near that point.';
      showToast(msg);
    }
    btn.textContent = '📍 Nearby Hazards';
    btn.disabled = false;
  });
}

function wireHotspotHazards() {
  document.getElementById('btn-hotspot-hazards')
    .addEventListener('click', loadHotspotHazards);
}

// ── Init ───────────────────────────────────────────────────────────────────
const EQ_QUERIES = {
  1: ()              => apiFetch('/aggregates/accidents?aggregate=earliest_year'),
  // Personal injury = all categories (fatal+serious+slight), no category filter
  2: ({year})        => apiFetch(`/aggregates/accidents?state=SN&year=${year}`),
  3: ()              => apiFetch('/aggregates/accidents?state=NW&aggregate=earliest_year'),
  4: ()              => apiFetch('/aggregates/accidents?state=MV&aggregate=earliest_year'),
  5: ({year, city})  => apiFetch(`/accidents?ags=${city}&year=${year}&participant=pedestrian`, { persist: true, maxAgeMs: ONE_DAY_MS }),
  // Multi-source: joins accident data with registered car counts
  6: ({year, state}) => {
    const stateClause = state ? `&state=${state}` : '';
    return apiFetch(`/aggregates/accident-rate/top?level=district&denominator=cars_pkw&year=${year}&limit=5${stateClause}`);
  },
  // Multi-source: joins accident data with population figures
  7: ({year, severity}) => {
    const sevClause = severity === 'all' ? '' : `&severity=${severity}`;
    return apiFetch(`/aggregates/accident-rate/top?level=district&year=${year}${sevClause}&denominator=population&limit=5&min_population=50000`);
  },
  // Raw fatal count top-5 (single-source, client-sorted)
  8: ({year})        => apiFetch(`/aggregates/accidents?level=district&year=${year}&category=1`),
  // Bicycle accidents in selected city + vehicle
  9: ({year, city, vehicle}) => apiFetch(`/accidents?ags=${city}&year=${year}&participant=${vehicle}`, { persist: true, maxAgeMs: ONE_DAY_MS }),
  // Bonus: zero-accident municipalities — uses PostGIS spatial join on backend
  10: ({year, state}) => apiFetch(`/aggregates/zero-accident-regions?level=municipality&state=${state}&year=${year}`),
};

function formatEqResult(q, res, labels = {}) {
  const row = (label, val) =>
    `<div class="lp-result-row"><span>${label}</span><span>${val}</span></div>`;

  if (q === 1 || q === 3 || q === 4) {
    const yr = res.results?.earliest_year ?? '—';
    return row('Earliest year', yr);
  }
  if (q === 2) {
    const total = res.metadata?.total_count
      ?? (res.results || []).reduce((s, r) => s + (r.accident_count || 0), 0);
    return row('Personal injury accidents', Number(total).toLocaleString('en-US'));
  }
  if (q === 5) {
    const total = res.metadata?.total_count ?? res.results?.length ?? '—';
    const city = labels.city || 'Berlin';
    return row(`Pedestrian accidents in ${city}`, Number(total).toLocaleString('en-US'));
  }
  if (q === 6) {
    const rows6 = (res.results || []).filter(r => r.rate_per_100k != null).slice(0, 5);
    if (!rows6.length) {
      return row('No district rows', 'No district-level car denominator data for this state');
    }
    return rows6.map((r, i) => row(`${r.rank ?? i + 1}. ${r.name}`, `${r.rate_per_100k} / 100k`)).join('');
  }
  if (q === 7) {
    const rows7 = res.results || [];
    if (!rows7.length) return row('No data', 'No matching fatal-rate rows for this filter');
    const sev = (labels.severity || '').toLowerCase();
    const tag = (sev && sev !== 'all') ? ` (${sev})` : '';
    return rows7.map(r => row(`${r.rank}. ${r.name}${tag}`, `${r.rate_per_100k ?? '—'} / 100k`)).join('');
  }
  if (q === 8) {
    const top5 = (res.results || [])
      .sort((a, b) => (b.accident_count || 0) - (a.accident_count || 0))
      .slice(0, 5);
    return top5.map((r, i) =>
      row(`${i + 1}. ${r.region_name || r.region_id}`, (r.accident_count || 0).toLocaleString('en-US'))
    ).join('');
  }
  if (q === 9) {
    const total = res.metadata?.total_count ?? res.results?.length ?? '—';
    const vehicle = labels.vehicle || 'Bike';
    const city = labels.city || 'Dresden';
    return row(`${vehicle} accidents in ${city}`, Number(total).toLocaleString('en-US'));
  }
  if (q === 10) {
    const zero = res.results || [];
    const total = res.metadata?.total_regions ?? '?';
    const state = res.metadata?.state ?? '';
    const header = row(`Zero-accident (${state})`, `${zero.length} / ${total} municipalities`);
    if (!zero.length) return header;
    const items = zero.map((r, i) =>
      `<div class="lp-result-list-item">${i + 1}. ${r.name}</div>`
    ).join('');
    return header + `<div class="lp-result-list">${items}</div>`;
  }
  return '';
}


async function init() {
  wirePanelA();
  wireLeftPanel();
  wireNearbyHazards();
  wireHotspotHazards();
  wireScrubber();
  setTimeout(() => map.invalidateSize(), 0);
  document.getElementById('insight-close').addEventListener('click', closeInsightPanel);
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closeInsightPanel(); });
  checkApiStatus();
  loadChoropleth();
  updateKPIs();
  runWhenIdle(loadStateBoundaries);
  runWhenIdle(loadAllYearData);
  setTimeout(() => map.invalidateSize(), 250);
}

document.addEventListener('DOMContentLoaded', () => init().catch(console.error));
