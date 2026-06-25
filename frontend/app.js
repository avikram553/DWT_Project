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

// ── Years ──────────────────────────────────────────────────────────────────
const YEARS = [2016,2017,2018,2019,2020,2021,2022,2023,2024];

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
const map = L.map('map', {
  zoom: 6, center: [51.2, 10.5], zoomControl: false,
  zoomSnap: 0.25,           // allow fractional zoom levels
  zoomDelta: 0.5,           // smaller step per button click
  wheelPxPerZoomLevel: 80,  // more pixels per level = slower, smoother scroll
  zoomAnimation: true,
});
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
  if (state.activeLayer === 'choropleth' && name !== 'choropleth') {
    map.removeLayer(layers.choropleth);
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
  let url = `/accidents?year=${state.year}&lat_min=${b.getSouth()}&lat_max=${b.getNorth()}&lon_min=${b.getWest()}&lon_max=${b.getEast()}&limit=5000`;
  if (state.category)    url += `&category=${state.category}`;
  if (state.participant) url += `&participant=${state.participant}`;

  let res;
  try { res = await apiFetch(url); } catch { return; }

  const data = res.results.map(a => ({ position: [a.lon, a.lat], category: a.category }));
  deckInstance.setProps({ layers: [buildHexLayer(data)] });
  updateDynamicStat(`⬡ ${data.length.toLocaleString('en-US')}`, 'in viewport');
}

function getParticipantIcon(acc) {
  if (acc.participant_bike)       return '🚲';
  if (acc.participant_pedestrian) return '🚶';
  if (acc.participant_truck)      return '🚛';
  if (acc.participant_car)        return '🚗';
  return '💥';
}

function renderSinglePoint(acc) {
  const icon = getParticipantIcon(acc);
  const marker = L.marker([acc.lat, acc.lon], {
    icon: L.divIcon({
      className: '',
      html: `<div class="acc-icon">${icon}</div>`,
      iconSize: [20, 20], iconAnchor: [10, 10],
    }),
  });
  marker.on('click', () => showDetailCard(acc, [acc.lat, acc.lon]));
  return marker;
}

async function loadPoints() {
  layers.accidents.clearLayers();
  const b = map.getBounds();
  let url = `/accidents?year=${state.year}&lat_min=${b.getSouth()}&lat_max=${b.getNorth()}&lon_min=${b.getWest()}&lon_max=${b.getEast()}&limit=5000`;
  if (state.category)    url += `&category=${state.category}`;
  if (state.participant) url += `&participant=${state.participant}`;

  let res;
  try { res = await apiFetch(url); } catch { return; }
  const accidents = res.results;

  for (const acc of accidents) {
    renderSinglePoint(acc).addTo(layers.accidents);
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

async function updateKPIs() {
  let url = `/aggregates/accidents?year=${state.year}`;
  if (state.category)    url += `&category=${state.category}`;

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
    const res = await apiFetch(`/aggregates/accidents?level=district&ags=${ags}`);
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

// ── Init ───────────────────────────────────────────────────────────────────
async function init() {
  await checkApiStatus();
  wirePanelA();
  wirePanelB();
  wireScrubber();
  document.getElementById('insight-close').addEventListener('click', closeInsightPanel);
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closeInsightPanel(); });
  await Promise.all([loadChoropleth(), updateKPIs(), loadAllYearData()]);
}

document.addEventListener('DOMContentLoaded', () => init().catch(console.error));
