// Unfallkarte Deutschland — Interactive JavaScript
// Pure vanilla JS, no build step. Requires Leaflet 1.9.4 and Chart.js 4.4.4 as globals.

const API_BASE = 'http://localhost:8000';

// --- State ---
let state = {
  year: 2024,
  participant: '',     // '' | 'car' | 'bike' | 'pedestrian' | 'truck'
  category: '',        // '' | '1,2' | '1'
  hourFilter: null,    // null | 0-23
  dayFilter: null,     // null | 1-7 (API day_of_week: 1=Sun,2=Mon..7=Sat)
  trackingId: null,    // watchPosition ID
  accidentCache: [],   // cached raw accidents for histogram/heatgrid
  choroplethData: {},  // region_id → count lookup
  userLat: null,
  userLon: null,
};

// --- Map ---
const map = L.map('map', {
  center: [51.1657, 10.4515],  // Germany center
  zoom: 6,
  zoomControl: false,
});

L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
  subdomains: 'abcd',
  maxZoom: 19,
}).addTo(map);

L.control.zoom({ position: 'topright' }).addTo(map);

// --- Layers ---
const layers = {
  choropleth: L.layerGroup().addTo(map),
  hotspots:   L.layerGroup().addTo(map),
  safeZones:  L.layerGroup().addTo(map),
  accidents:  L.layerGroup(),  // NOT added by default
  route:      L.layerGroup().addTo(map),
  user:       L.layerGroup().addTo(map),
};

// --- API Helpers ---
async function apiFetch(path) {
  const res = await fetch(API_BASE + path);
  if (!res.ok) throw new Error(`API error ${res.status}`);
  return res.json();
}

function showApiError(msg) {
  const el = document.getElementById('apiStatus');
  el.textContent = '● Fehler';
  el.className = 'badge badge--status error';
  console.error(msg);
}

// --- Choropleth ---
async function loadChoropleth() {
  layers.choropleth.clearLayers();

  // Fetch region geometries and accident counts in parallel
  const regionsPromise = apiFetch('/regions?level=district');

  // Build count URL based on category filter
  // API only supports single integer for category param.
  // If '1,2' (Schwer+): omit category to show all (pragmatic fallback — documented).
  // If '1' (fatal): send category=1.
  let countUrl = `/aggregates/accidents?level=district&year=${state.year}`;
  if (state.category === '1') countUrl += '&category=1';
  // category '1,2' → omit filter (show all accidents, closest available approximation)

  const [regionsRes, countsRes] = await Promise.all([regionsPromise, apiFetch(countUrl)]);
  const regions = regionsRes.results;

  // Build lookup: region_id → total accident_count
  const lookup = {};
  for (const r of countsRes.results) {
    lookup[r.region_id] = (lookup[r.region_id] || 0) + r.accident_count;
  }
  state.choroplethData = lookup;
  const maxCount = Math.max(...Object.values(lookup), 1);

  L.geoJSON(
    {
      type: 'FeatureCollection',
      features: regions.map(r => ({
        type: 'Feature',
        geometry: r.geom,  // GeoJSON geometry object, used directly
        properties: { ags: r.ags, name: r.name },
      })),
    },
    {
      style: (feature) => {
        const count = lookup[feature.properties.ags] || 0;
        return {
          fillColor: choroplethColor(count, maxCount),
          fillOpacity: 0.65,
          color: 'rgba(255,255,255,0.15)',
          weight: 0.5,
        };
      },
      onEachFeature: (feature, layer) => {
        const count = lookup[feature.properties.ags] || 0;
        layer.bindTooltip(
          `<strong>${feature.properties.name}</strong><br>${count.toLocaleString('de-DE')} Unfälle`,
          { sticky: true }
        );
        layer.on('click', () => handleRegionClick(feature.properties.ags, feature.properties.name));
      },
    }
  ).addTo(layers.choropleth);
}

function choroplethColor(count, max) {
  // Lerp from surface (#1A2535) at 0 → accent-red (#E84855) at max
  const t = Math.pow(Math.min(count / max, 1), 0.5);  // sqrt scale so mid-values show
  const r = Math.round(26  + t * (232 - 26));
  const g = Math.round(37  + t * (72  - 37));
  const b = Math.round(53  + t * (85  - 53));
  return `rgb(${r},${g},${b})`;
}

// --- Hotspots ---
async function loadHotspots() {
  layers.hotspots.clearLayers();
  const center = map.getCenter();
  const res = await apiFetch(`/zones/nearest?lat=${center.lat}&lon=${center.lng}&type=hotspot&limit=200`);

  let hotspotCount = 0;
  for (const zone of res.results) {
    if (!zone.cell_geom) continue;
    hotspotCount++;
    const geojson = typeof zone.cell_geom === 'string' ? JSON.parse(zone.cell_geom) : zone.cell_geom;

    // Get centroid of polygon
    const coords = geojson.coordinates[0];
    const lng = coords.reduce((s, c) => s + c[0], 0) / coords.length;
    const lat = coords.reduce((s, c) => s + c[1], 0) / coords.length;

    const icon = L.divIcon({
      className: 'hotspot-marker',
      iconSize: [12, 12],
      iconAnchor: [6, 6],
    });

    L.marker([lat, lng], { icon })
      .addTo(layers.hotspots)
      .on('click', () => showDossier(zone));

    // Also draw the cell polygon semi-transparent
    L.geoJSON(geojson, {
      style: { fillColor: '#E84855', fillOpacity: 0.12, color: '#E84855', weight: 1, opacity: 0.4 },
    }).addTo(layers.hotspots).on('click', () => showDossier(zone));
  }

  // Update KPI hotspot count
  countUp('kpiHotspots', hotspotCount);
}

// --- Safe Zones ---
async function loadSafeZones() {
  layers.safeZones.clearLayers();
  const center = map.getCenter();
  const res = await apiFetch(`/zones/nearest?lat=${center.lat}&lon=${center.lng}&type=safe&limit=150`);

  for (const zone of res.results) {
    if (!zone.cell_geom) continue;
    const geojson = typeof zone.cell_geom === 'string' ? JSON.parse(zone.cell_geom) : zone.cell_geom;
    L.geoJSON(geojson, {
      style: { fillColor: '#2EC4B6', fillOpacity: 0.25, color: '#2EC4B6', weight: 1, opacity: 0.5 },
    }).addTo(layers.safeZones).on('click', () => showDossier(zone));
  }
}

// --- Accident Dots ---
map.on('zoomend', () => {
  if (map.getZoom() >= 11 && document.getElementById('layerAccidents').checked) {
    loadAccidentDots();
  } else {
    layers.accidents.clearLayers();
  }
});

async function loadAccidentDots() {
  layers.accidents.clearLayers();

  let url = `/accidents?limit=500&year=${state.year}`;
  if (state.participant) url += `&participant=${state.participant}`;
  if (state.category === '1') url += '&category=1';

  const res = await apiFetch(url);
  state.accidentCache = res.results;
  renderHourHistogram();
  renderHeatgrid();

  const filtered = filterByHourDay(res.results);
  for (const acc of filtered) {
    if (!acc.lat || !acc.lon) continue;
    const color = acc.category === 1 ? '#E84855' : acc.category === 2 ? '#F4A261' : '#7B96B2';
    L.circleMarker([acc.lat, acc.lon], {
      radius: 4, fillColor: color, fillOpacity: 0.7, color: 'rgba(255,255,255,0.3)', weight: 0.5,
    }).addTo(layers.accidents);
  }
}

function filterByHourDay(accidents) {
  return accidents.filter(acc => {
    if (state.hourFilter !== null && acc.hour !== state.hourFilter) return false;
    if (state.dayFilter !== null && acc.day_of_week !== state.dayFilter) return false;
    return true;
  });
}

// --- KPI Stats ---
async function updateKPIs() {
  let url = `/aggregates/accidents?year=${state.year}`;
  if (state.category === '1') url += '&category=1';
  const res = await apiFetch(url);
  const total = res.metadata?.total_count || res.results.reduce((s, r) => s + r.accident_count, 0);

  // Fatal count: always fetch category=1 for kpiFatal
  const fatalRes = await apiFetch(`/aggregates/accidents?year=${state.year}&category=1`);
  const fatal = fatalRes.metadata?.total_count || fatalRes.results.reduce((s, r) => s + r.accident_count, 0);

  countUp('kpiTotal', total);
  countUp('kpiFatal', fatal);
  // kpiHotspots updated in loadHotspots()
}

function countUp(id, target) {
  const el = document.getElementById(id);
  if (!el) return;
  const start = parseInt(el.textContent.replace(/\D/g, '')) || 0;
  const duration = 600;
  const startTime = performance.now();
  const tick = (now) => {
    const t = Math.min((now - startTime) / duration, 1);
    el.textContent = Math.round(start + (target - start) * t).toLocaleString('de-DE');
    if (t < 1) requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}

// --- Year Trend Chart ---
let yearChart = null;

async function renderYearChart() {
  const years = [2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024];
  // Fetch all years at once — API returns all years when no year filter is given
  const res = await apiFetch('/aggregates/accidents');

  // Group by year
  const byYear = {};
  for (const r of res.results) {
    byYear[r.year] = (byYear[r.year] || 0) + r.accident_count;
  }

  const data = years.map(y => byYear[y] || 0);
  const ctx = document.getElementById('yearChart').getContext('2d');

  if (yearChart) yearChart.destroy();
  yearChart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: years.map(String),
      datasets: [{
        data,
        backgroundColor: years.map(y => y === state.year ? '#E84855' : 'rgba(232,72,85,0.3)'),
        borderWidth: 0,
        borderRadius: 2,
      }],
    },
    options: {
      responsive: true,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: { label: ctx => ctx.raw.toLocaleString('de-DE') + ' Unfälle' },
          backgroundColor: '#1A2535', titleColor: '#EDF2F7', bodyColor: '#7B96B2',
        },
      },
      scales: {
        x: { ticks: { color: '#3D5166', font: { size: 9, family: 'IBM Plex Mono' } }, grid: { display: false } },
        y: { ticks: { color: '#3D5166', font: { size: 9 } }, grid: { color: 'rgba(255,255,255,0.04)' } },
      },
      onClick: (e, elements) => {
        if (elements.length) {
          const yr = years[elements[0].index];
          document.getElementById('yearSlider').value = yr;
          state.year = yr;
          document.getElementById('yearLabel').textContent = yr;
          onYearChange();
        }
      },
    },
  });
}

// --- Hour Histogram ---
let hourChart = null;

function renderHourHistogram() {
  const counts = new Array(24).fill(0);
  for (const acc of state.accidentCache) {
    if (acc.hour != null) counts[acc.hour]++;
  }

  const ctx = document.getElementById('hourChart').getContext('2d');
  if (hourChart) hourChart.destroy();

  hourChart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: Array.from({ length: 24 }, (_, i) => i + 'h'),
      datasets: [{
        data: counts,
        backgroundColor: counts.map((c, i) => {
          if (state.hourFilter === i) return '#E84855';
          const t = counts.length ? c / Math.max(...counts) : 0;
          return `rgba(46,196,182,${0.2 + t * 0.7})`;
        }),
        borderWidth: 0,
        borderRadius: 1,
      }],
    },
    options: {
      responsive: true,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: { label: ctx => ctx.raw + ' Unfälle' },
          backgroundColor: '#1A2535', titleColor: '#EDF2F7', bodyColor: '#7B96B2',
        },
      },
      scales: {
        x: { ticks: { color: '#3D5166', font: { size: 8, family: 'IBM Plex Mono' } }, grid: { display: false } },
        y: { ticks: { color: '#3D5166', font: { size: 8 } }, grid: { color: 'rgba(255,255,255,0.04)' } },
      },
      onClick: (e, elements) => {
        if (!elements.length) return;
        const hour = elements[0].index;
        if (state.hourFilter === hour) {
          state.hourFilter = null;
          document.getElementById('hourFilterHint').textContent = '';
        } else {
          state.hourFilter = hour;
          document.getElementById('hourFilterHint').textContent = `Filter: ${hour}:00–${hour}:59`;
        }
        if (map.getZoom() >= 11) loadAccidentDots();
        renderHourHistogram();
      },
    },
  });
}

// --- Day × Hour Heatgrid ---
function renderHeatgrid() {
  const grid = document.getElementById('heatgrid');
  grid.innerHTML = '';

  // counts[day][hour] where day 0=Mon..6=Sun
  // API day_of_week: 1=Sun, 2=Mon, 3=Tue, 4=Wed, 5=Thu, 6=Fri, 7=Sat
  const counts = Array.from({ length: 7 }, () => new Array(24).fill(0));
  for (const acc of state.accidentCache) {
    const dw = acc.day_of_week;
    if (!dw || acc.hour == null) continue;
    const dayIdx = dw === 1 ? 6 : dw - 2;  // Convert: Mon(2)=0 .. Sat(7)=5, Sun(1)=6
    counts[dayIdx][acc.hour]++;
  }

  const maxCount = Math.max(...counts.flat(), 1);

  for (let d = 0; d < 7; d++) {
    for (let h = 0; h < 24; h++) {
      const c = counts[d][h];
      const opacity = c / maxCount;
      const cell = document.createElement('div');
      cell.className = 'heatgrid-cell';
      cell.style.background = `rgba(232, 72, 85, ${0.05 + opacity * 0.85})`;
      cell.title = `${['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So'][d]} ${h}:00 — ${c} Unfälle`;

      // Highlight active cell
      const activeDayIdx = state.dayFilter === null ? -1 : (state.dayFilter === 1 ? 6 : state.dayFilter - 2);
      if (activeDayIdx === d && state.hourFilter === h) {
        cell.style.outline = '1px solid #E84855';
      }

      cell.addEventListener('click', () => {
        const apiDayOfWeek = d === 6 ? 1 : d + 2;  // reverse convert
        if (state.dayFilter === apiDayOfWeek && state.hourFilter === h) {
          state.dayFilter = null;
          state.hourFilter = null;
          document.getElementById('heatgridHint').textContent = '';
        } else {
          state.dayFilter = apiDayOfWeek;
          state.hourFilter = h;
          document.getElementById('heatgridHint').textContent = `Filter: ${['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So'][d]} ${h}:00`;
        }
        if (map.getZoom() >= 11) loadAccidentDots();
        renderHeatgrid();
      });

      grid.appendChild(cell);
    }
  }
}

// --- Participant Chips ---
document.getElementById('participantChips').addEventListener('click', e => {
  const btn = e.target.closest('.chip');
  if (!btn) return;
  document.querySelectorAll('#participantChips .chip').forEach(c => c.classList.remove('chip--active'));
  btn.classList.add('chip--active');
  state.participant = btn.dataset.participant;
  onFilterChange();
});

// --- Severity Toggle ---
document.getElementById('severityControl').addEventListener('click', e => {
  const btn = e.target.closest('.seg-btn');
  if (!btn) return;
  document.querySelectorAll('#severityControl .seg-btn').forEach(b => b.classList.remove('seg-btn--active'));
  btn.classList.add('seg-btn--active');
  state.category = btn.dataset.category;
  onFilterChange();
});

// --- Year Slider ---
const yearSlider = document.getElementById('yearSlider');
const yearLabel = document.getElementById('yearLabel');
yearSlider.addEventListener('input', () => {
  state.year = parseInt(yearSlider.value);
  yearLabel.textContent = state.year;
});
yearSlider.addEventListener('change', onYearChange);

function onYearChange() {
  loadChoropleth();
  loadHotspots();
  loadSafeZones();
  updateKPIs();
  renderYearChart();
}

function onFilterChange() {
  loadChoropleth();
  updateKPIs();
  if (map.getZoom() >= 11) loadAccidentDots();
}

// --- Layer Toggles ---
function wireLayerToggle(checkboxId, layerGroup) {
  document.getElementById(checkboxId).addEventListener('change', e => {
    if (e.target.checked) map.addLayer(layerGroup);
    else map.removeLayer(layerGroup);
  });
}

wireLayerToggle('layerChoropleth', layers.choropleth);
wireLayerToggle('layerHotspots', layers.hotspots);
wireLayerToggle('layerSafeZones', layers.safeZones);
wireLayerToggle('layerAccidents', layers.accidents);

// --- Geolocation ---
document.getElementById('btnGeolocate').addEventListener('click', geolocate);

function geolocate() {
  if (!navigator.geolocation) {
    alert('Geolokalisierung nicht verfügbar');
    return;
  }
  navigator.geolocation.getCurrentPosition(
    pos => handlePosition(pos.coords.latitude, pos.coords.longitude),
    () => showApiError('Standort konnte nicht ermittelt werden')
  );
}

async function handlePosition(lat, lon) {
  state.userLat = lat;
  state.userLon = lon;

  // Fly to location
  map.flyTo([lat, lon], 14, { duration: 1.5 });

  // Update user dot
  updateUserDot(lat, lon);

  // Fetch zones around
  const res = await apiFetch(`/zones/around?lat=${lat}&lon=${lon}`);
  const { hotspots, safe_zones, your_zone } = res.results;

  // Show dossier for user's zone or nearest hotspot
  if (your_zone) {
    showDossier(your_zone);
  } else if (hotspots && hotspots.length) {
    showDossier(hotspots[0]);
  }

  // Risk gauge
  updateRiskGauge(your_zone, hotspots || []);

  // Danger alert
  checkDangerAlert(your_zone, hotspots || []);
}

// --- User Dot ---
let userMarker = null;

function updateUserDot(lat, lon) {
  const icon = L.divIcon({ className: 'user-dot', iconSize: [14, 14], iconAnchor: [7, 7] });
  if (userMarker) {
    userMarker.setLatLng([lat, lon]);
  } else {
    userMarker = L.marker([lat, lon], { icon, zIndexOffset: 1000 }).addTo(layers.user);
  }
}

// --- Risk Gauge ---
function updateRiskGauge(yourZone, hotspots) {
  const gauge = document.getElementById('riskGauge');
  gauge.classList.remove('hidden');

  // Compute score: base 40 if in hotspot zone, +5 per nearby hotspot, max 100
  let score = 0;
  if (yourZone && yourZone.kind === 'hotspot') score += 40;
  score += Math.min(hotspots.length * 5, 60);
  score = Math.min(100, score);

  // SVG arc: full semicircle = π × r = π × 40 ≈ 125.6
  const arcLen = 125.6;
  const dashArray = `${(score / 100) * arcLen} ${arcLen}`;

  const arcEl = document.getElementById('gaugeArc');
  const scoreEl = document.getElementById('gaugeScore');
  const labelEl = document.getElementById('gaugeLabel');

  arcEl.style.strokeDasharray = dashArray;

  if (score <= 30) {
    arcEl.style.stroke = '#2EC4B6';
    labelEl.textContent = 'Niedrig';
  } else if (score <= 70) {
    arcEl.style.stroke = '#F4A261';
    labelEl.textContent = 'Erhöht';
  } else {
    arcEl.style.stroke = '#E84855';
    labelEl.textContent = 'Kritisch';
  }
  scoreEl.textContent = score;
}

// --- Danger Alert ---
function checkDangerAlert(yourZone, hotspots) {
  const alertEl = document.getElementById('dangerAlert');

  let nearestHotspot = null;
  let minDist = Infinity;

  if (yourZone && yourZone.kind === 'hotspot') {
    nearestHotspot = yourZone;
    minDist = 0;
  } else {
    for (const h of hotspots) {
      if (h.distance_m < minDist) { minDist = h.distance_m; nearestHotspot = h; }
    }
  }

  if (nearestHotspot && minDist < 300) {
    const dist = minDist < 50 ? 'unmittelbar' : `${Math.round(minDist)}m`;
    document.getElementById('dangerAlertText').textContent =
      `⚠ Unfallschwerpunkt ${dist === 'unmittelbar' ? 'an diesem Standort' : 'in ' + dist + ' Entfernung'} (${nearestHotspot.accident_count} Unfälle in 3 Jahren)`;
    alertEl.classList.add('show');
    setTimeout(() => alertEl.classList.remove('show'), 8000);
  }
}

document.getElementById('dangerAlertClose').addEventListener('click', () => {
  document.getElementById('dangerAlert').classList.remove('show');
});

// --- Live Tracking ---
document.getElementById('btnTrack').addEventListener('click', toggleTracking);

function toggleTracking() {
  const btn = document.getElementById('btnTrack');
  if (state.trackingId !== null) {
    navigator.geolocation.clearWatch(state.trackingId);
    state.trackingId = null;
    btn.classList.remove('active');
    btn.title = 'Live-Tracking an/aus';
  } else {
    if (!navigator.geolocation) { alert('Geolokalisierung nicht verfügbar'); return; }
    btn.classList.add('active');
    btn.title = 'Tracking aktiv — klicken zum Stoppen';
    let lastUpdate = 0;
    state.trackingId = navigator.geolocation.watchPosition(
      pos => {
        const now = Date.now();
        updateUserDot(pos.coords.latitude, pos.coords.longitude);
        if (now - lastUpdate > 5000) {  // refresh zone data every 5 seconds
          lastUpdate = now;
          handlePosition(pos.coords.latitude, pos.coords.longitude);
        }
      },
      () => { toggleTracking(); }
    );
  }
}

// --- Safe Route ---
document.getElementById('routeAnalyze').addEventListener('click', analyzeRoute);

async function analyzeRoute() {
  const origin = document.getElementById('routeOrigin').value.trim();
  const dest = document.getElementById('routeDestination').value.trim();
  if (!origin || !dest) return;

  const resultEl = document.getElementById('routeResult');
  resultEl.textContent = 'Geocoding…';

  try {
    const [fromCoord, toCoord] = await Promise.all([
      geocode(origin), geocode(dest),
    ]);
    if (!fromCoord || !toCoord) {
      resultEl.textContent = 'Ort nicht gefunden';
      return;
    }

    // Draw polyline
    layers.route.clearLayers();
    const polyline = L.polyline([fromCoord, toCoord], {
      color: '#F4A261', weight: 3, opacity: 0.8, dashArray: '6 4',
    }).addTo(layers.route);
    map.fitBounds(polyline.getBounds(), { padding: [40, 40] });

    // Sample 10 points along the line and check for hotspots
    const points = sampleLine(fromCoord, toCoord, 10);
    resultEl.textContent = 'Analysiere Route…';

    // Parallel zone lookups
    const zoneResults = await Promise.all(
      points.map(([lat, lon]) => apiFetch(`/zones/around?lat=${lat}&lon=${lon}`).catch(() => null))
    );

    // Collect unique hotspots along route
    const hotspotSet = new Set();
    for (const res of zoneResults) {
      if (!res) continue;
      const { hotspots, your_zone } = res.results;
      if (your_zone && your_zone.kind === 'hotspot') {
        const key = `${your_zone.region_id}-${your_zone.year_from}`;
        if (!hotspotSet.has(key)) {
          hotspotSet.add(key);
          if (your_zone.cell_geom) {
            const geojson = typeof your_zone.cell_geom === 'string' ? JSON.parse(your_zone.cell_geom) : your_zone.cell_geom;
            L.geoJSON(geojson, {
              style: { fillColor: '#E84855', fillOpacity: 0.3, color: '#E84855', weight: 1 },
            }).addTo(layers.route);
          }
        }
      }
      for (const h of (hotspots || [])) {
        const key = `${h.region_id}-${h.year_from}`;
        if (!hotspotSet.has(key)) {
          hotspotSet.add(key);
          if (h.cell_geom) {
            const geojson = typeof h.cell_geom === 'string' ? JSON.parse(h.cell_geom) : h.cell_geom;
            L.geoJSON(geojson, {
              style: { fillColor: '#E84855', fillOpacity: 0.3, color: '#E84855', weight: 1 },
            }).addTo(layers.route);
          }
        }
      }
    }

    const total = hotspotSet.size;
    resultEl.textContent = total === 0
      ? '✓ Route kreuzt keine Schwerpunkte'
      : `⚠ Route kreuzt ${total} Schwerpunkt${total > 1 ? 'e' : ''}`;

    L.marker(fromCoord, { title: origin }).addTo(layers.route);
    L.marker(toCoord, { title: dest }).addTo(layers.route);

  } catch (e) {
    resultEl.textContent = 'Fehler bei der Analyse';
  }
}

async function geocode(query) {
  const url = `https://nominatim.openstreetmap.org/search?q=${encodeURIComponent(query + ' Germany')}&format=json&limit=1`;
  const res = await fetch(url, { headers: { 'Accept-Language': 'de' } });
  const data = await res.json();
  if (!data.length) return null;
  return [parseFloat(data[0].lat), parseFloat(data[0].lon)];
}

function sampleLine(from, to, n) {
  return Array.from({ length: n }, (_, i) => {
    const t = i / (n - 1);
    return [from[0] + t * (to[0] - from[0]), from[1] + t * (to[1] - from[1])];
  });
}

// --- Q&A Accordion ---
document.getElementById('qaAccordion').addEventListener('click', e => {
  const header = e.target.closest('.acc-header');
  if (!header) return;
  const q = header.dataset.q;
  const body = document.getElementById(`qa${q}`);
  const isOpen = !body.classList.contains('hidden');

  // Close all
  document.querySelectorAll('.acc-body').forEach(b => b.classList.add('hidden'));
  document.querySelectorAll('.acc-header').forEach(h => h.classList.remove('active'));

  if (!isOpen) {
    body.classList.remove('hidden');
    header.classList.add('active');
    fetchQA(parseInt(q));
  }
});

async function fetchQA(q) {
  switch (q) {
    case 1:
      document.getElementById('qa1Result').textContent = 'Klicke einen Landkreis auf der Karte';
      break;

    case 2: {
      const res = await apiFetch(`/aggregates/accidents?level=district&year=${state.year}&limit=10`);
      const top = res.results.slice(0, 10);
      document.getElementById('qa2Result').textContent =
        top.map(r => `${r.region_name}: ${r.accident_count.toLocaleString('de-DE')}`).join('\n');
      break;
    }

    case 3: {
      const sel = document.getElementById('qa3StateSelect');
      sel.onchange = async () => {
        if (!sel.value) return;
        const res = await apiFetch(`/aggregates/accidents?state=${sel.value}&aggregate=earliest_year`);
        document.getElementById('qa3Result').textContent = `Frühestes Jahr: ${res.results?.earliest_year ?? '—'}`;
      };
      break;
    }

    case 4:
      document.getElementById('qa4Result').textContent = 'Klicke eine Gemeinde auf der Karte';
      break;

    case 5: {
      document.getElementById('qa5Fetch').onclick = async () => {
        const res = await apiFetch('/accidents?state=BE&year=2023&participant=pedestrian&limit=1000');
        document.getElementById('qa5Result').textContent =
          `${res.results.length} Fußgängerunfälle in Berlin 2023 (erste 1000)`;
      };
      break;
    }

    case 6: {
      document.getElementById('qa6Fetch').onclick = async () => {
        const res = await apiFetch('/aggregates/accident-rate?level=district&year=2024&denominator=population');
        const top5 = res.results.sort((a, b) => b.rate - a.rate).slice(0, 5);
        document.getElementById('qa6Result').textContent =
          top5.map(r => `${r.region_name}: ${r.rate?.toFixed(1)} / 100k EW`).join('\n');
      };
      break;
    }

    case 7: {
      document.getElementById('qa7Fetch').onclick = async () => {
        const res = await apiFetch('/aggregates/accident-rate/top?level=district&year=2024&severity=fatal&denominator=population&limit=5&min_population=50000');
        document.getElementById('qa7Result').textContent =
          res.results.map((r, i) => `${i + 1}. ${r.region_name}: ${r.rate?.toFixed(2)} Tode/100k`).join('\n');
      };
      break;
    }
  }
}

// Region click handler — used by choropleth layer and Q1/Q4 accordion answers
function handleRegionClick(ags, name) {
  // Update Q1 if open (earliest year for this district's state)
  const qa1Body = document.getElementById('qa1');
  if (qa1Body && !qa1Body.classList.contains('hidden')) {
    apiFetch(`/aggregates/accidents?level=district&aggregate=earliest_year&state=${ags.substring(0, 2)}`).then(res => {
      document.getElementById('qa1Result').textContent = `${name}\nFrühestes Jahr: ${res.results?.earliest_year ?? '—'}`;
    });
  }

  // Update Q4 if open (earliest year for this district/Gemeinde)
  const qa4Body = document.getElementById('qa4');
  if (qa4Body && !qa4Body.classList.contains('hidden')) {
    apiFetch(`/aggregates/accidents?level=district&aggregate=earliest_year&state=${ags.substring(0, 2)}`).then(res => {
      document.getElementById('qa4Result').textContent = `${name}\nFrühestes Jahr: ${res.results?.earliest_year ?? '—'}`;
    });
  }
}

// --- Dossier Card ---
function showDossier(zone) {
  const d = document.getElementById('dossier');
  document.getElementById('dossierKind').textContent = zone.kind === 'hotspot' ? 'SCHWERPUNKT' : 'SICHER';
  document.getElementById('dossierKind').className = `dossier-kind${zone.kind === 'safe' ? ' safe' : ''}`;
  document.getElementById('dossierCount').textContent = zone.accident_count?.toLocaleString('de-DE') ?? '—';
  document.getElementById('dossierRegion').textContent = zone.region_name ?? '—';

  // Centroid from geom
  let coords = '—';
  if (zone.cell_geom) {
    const geojson = typeof zone.cell_geom === 'string' ? JSON.parse(zone.cell_geom) : zone.cell_geom;
    const pts = geojson.coordinates[0];
    const lat = (pts.reduce((s, c) => s + c[1], 0) / pts.length).toFixed(4);
    const lon = (pts.reduce((s, c) => s + c[0], 0) / pts.length).toFixed(4);
    coords = `${lat}°N, ${lon}°E`;
  }
  document.getElementById('dossierCoords').textContent = coords;
  document.getElementById('dossierPeriod').textContent =
    zone.year_from && zone.year_to ? `${zone.year_from}–${zone.year_to}` : '—';

  // Add .show class — CSS handles the transform/transition (not removing .hidden)
  d.classList.add('show');
}

document.getElementById('dossierClose').addEventListener('click', () => {
  document.getElementById('dossier').classList.remove('show');
});

// --- API Status Ping ---
async function checkApiStatus() {
  const el = document.getElementById('apiStatus');
  try {
    await apiFetch('/metadata/sources');
    el.textContent = '● Live';
    el.className = 'badge badge--status live';
  } catch {
    el.textContent = '● Offline';
    el.className = 'badge badge--status error';
  }
}

// --- Map moveend Reload (debounced 500ms) ---
let moveendTimer = null;
map.on('moveend', () => {
  clearTimeout(moveendTimer);
  moveendTimer = setTimeout(() => {
    if (document.getElementById('layerHotspots').checked) loadHotspots();
    if (document.getElementById('layerSafeZones').checked) loadSafeZones();
  }, 500);
});

// --- Init ---
async function init() {
  await checkApiStatus();
  await Promise.all([
    loadChoropleth(),
    loadHotspots(),
    loadSafeZones(),
    updateKPIs(),
    renderYearChart(),
  ]);
}

document.addEventListener('DOMContentLoaded', init);
