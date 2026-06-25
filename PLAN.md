# DBW Final Project — Implementation Plan

**Project:** Open Data Integration with Accidents in Germany
**Course:** Datenbanken und Web-Techniken (DBW), TU Chemnitz
**Submission:** 25.06.2026 23:59 via OPAL · Oral exam: 02.07–16.07.2026

---

## 1. Project Summary

Build a reproducible end-to-end data platform that:

1. Integrates **≥3 official German open-data sources** into a single canonical schema
2. Stores the harmonised data in a self-hosted database
3. Exposes the data through a **documented REST API** (OpenAPI/Swagger)
4. Demonstrates the API through a **lightweight visual frontend** with geolocation
5. Refreshes itself reproducibly via a **mandatory update script**
6. Tracks **full provenance** (source, license, retrieval date, file hash, import run) and surfaces it in API responses
7. Answers all **7 mandatory examiner questions** from real stored data

---

## 2. Tech Stack

| Layer | Choice | Why |
|---|---|---|
| Database | PostgreSQL 16 + PostGIS 3.4 (image: `postgis/postgis:16-3.4`) | Native KNN (`<->`), polygon storage, mature. **Do NOT use bare `postgres:16` — it does not include PostGIS.** |
| Backend | Python 3.11 + FastAPI | Best ETL ergonomics, free OpenAPI docs |
| DB layer | SQLAlchemy 2 + GeoAlchemy2 | Type hints + raw SQL escape hatch |
| ETL | pandas + httpx + zipfile | Standard, fast for 3M rows |
| Frontend | Vanilla HTML + Leaflet.js + Chart.js | No build step, examiner-readable |
| Container | Docker Compose | One-command setup → reproducibility (25%) |
| Migrations | Plain SQL files in `db/init/` | Simpler than Alembic for this scope |
| Testing | pytest | Light coverage of ETL + critical endpoints |

---

## 3. Data Sources (≥3 required by rubric)

| # | Source | Format | Purpose | License |
|---|---|---|---|---|
| 1 | **Unfallatlas** | CSV (latin-1, ;) | Accident events (~3M rows, 2016–2024) | dl-de/by-2-0 |
| 2 | **Regionalatlas** | GeoJSON | Region polygons (states + districts) | dl-de/by-2-0 |
| 3 | **Regionalstatistik / GENESIS** | CSV / JSON API | Population + registered cars (~300k values) | dl-de/by-2-0 |
| 4 | **GV-ISys / AGS** | CSV / XLSX | Region reference codes (8-digit AGS) | dl-de/by-2-0 |

**File-format choice:** CSV for accidents (pre-projected WGS84 columns, encoding handled), GeoJSON for region polygons.

---

## 4. Database Schema — 9 Tables

```
┌──────────┐   ┌──────────────┐   ┌────────────────┐   ┌──────────────┐
│ sources  │◄──┤ import_runs  │   │   indicators   │   │ lookup_codes │
└──────────┘   └──────┬───────┘   └────────┬───────┘   └──────────────┘
                      │ FK                  │ FK
                      ▼                     ▼
                ┌──────────┐         ┌──────────────────┐
                │ regions  │◄────────┤ indicator_values │
                └────┬─────┘         └──────────────────┘
                     │ FK ▲
                     ▼   │ old_ags / new_ags
                ┌──────────┐  ┌─────────────────┐  ┌────────────────┐
                │accidents │  │ regions_history │  │ accident_zones │
                └──────────┘  └─────────────────┘  └────────────────┘
```

| # | Table | Rows | Purpose |
|---|---|---|---|
| 1 | `regions` | ~12,000 | Admin region catalog with polygons (canonical 2024 AGS) |
| 2 | `accidents` | ~3,000,000 | Main fact table |
| 3 | `indicators` | ~5–10 | Indicator catalog |
| 4 | `indicator_values` | ~300,000 | Population & vehicles per region/year |
| 5 | `accident_zones` | ~100,000 | Computed hotspot/safe classifications |
| 6 | `sources` | ~5 | Dataset metadata + license |
| 7 | `import_runs` | ~100 | Audit log of every ETL execution |
| 8 | `lookup_codes` | ~50 | Code→label translation (DE + EN) |
| 9 | `regions_history` | ~20 | AGS reorganisation lookup (Destatis Gebietsstandstabelle) — `old_ags`, `new_ags`, `change_date`, `change_type`, `source_note` |

Full DDL lives in `db/init/01_schema.sql`; `regions_history` is seeded from `db/init/05_seed_ags_history.sql`. See `docs/SCHEMA.md` for column-level documentation.

### Critical column contracts (call out in DDL)

- **`regions`**: `ags TEXT PRIMARY KEY` (string, never integer — leading-zero bug); `level region_level NOT NULL` (enum: `'state'|'district'|'municipality'`); `parent_ags TEXT REFERENCES regions(ags)` (district→state, municipality→district); `population_latest BIGINT` (denormalised from `indicator_values` for the ≥50k filter — avoids re-joining 300k rows on every Q7 request); `geom GEOMETRY(MULTIPOLYGON, 4326)`.
- **`accidents`**: `accident_uid TEXT NOT NULL UNIQUE` — holds `UIDENTSTLAE` for 2018+ rows, synthesised SHA-1 surrogate for 2016–2017 (see §9 step 5); `region_id TEXT REFERENCES regions(ags)` always points at canonical 2024 AGS via `regions_history` resolution; `import_run_id BIGINT REFERENCES import_runs(id)` per row for honest provenance under partial reloads; `geom GEOMETRY(POINT, 4326)` projected from `XGCSWGS84`/`YGCSWGS84`.
- **`accident_zones`**: `cell_geom_proj GEOMETRY(POLYGON, 25832)` is the storage geometry (see §7 Phase 6 — grid generation must be in metric SRID); `cell_geom GEOMETRY(POLYGON, 4326)` is the API/frontend output; both indexed.
- **`indicator_values`**: `value INTEGER` (population fits in int32; vehicle counts too at district level); composite PK `(indicator_id, region_id, year)`.

### Required indexes

| Table | Index | Used by |
|---|---|---|
| `accidents` | B-tree `(year)` | Q1, Q3, Q4 (`MIN(year)`) |
| `accidents` | B-tree `(region_id, year)` | Q2, Q5, Q6, Q7, every aggregate endpoint |
| `accidents` | B-tree `(year, category)` | Q2 (severity filter) |
| `accidents` | Partial B-tree `(region_id, year) WHERE category = 1` | Q7 (fatal-only ranking — fatal is ~2.5% of rows) |
| `accidents` | GIST `(geom)` | hotspot point-in-cell, frontend bbox queries |
| `regions` | B-tree `(level, parent_ags)` | `/regions?level=district` listing |
| `regions` | GIST `(geom)` | map rendering, `ST_Contains` |
| `accident_zones` | GIST `(cell_geom_proj)` | KNN `<->` for `/zones/around` (must be metric SRID for distance to be meaningful) |
| `indicator_values` | B-tree `(indicator_id, region_id, year DESC)` | population fallback CTE |

Phase 5 verification: `EXPLAIN ANALYZE` on the Q7 query path must show index scans, p95 < 200ms cold cache.

---

## 5. API Endpoints (planned)

### Core endpoints
- `GET /regions?level={state|district|municipality}`
- `GET /regions/{ags}`
- `GET /accidents?state=SN&year=2023&category=1&limit=100`
- `GET /aggregates/accidents?level=district&year=2023`
- `GET /aggregates/accident-rate?level=district&year=2023&denominator={population|cars_pkw}`
- `GET /aggregates/accident-rate/top?level=district&year=2024&severity=fatal&denominator=population&limit=5&min_population=50000`

`min_population` defaults to `50000` (Destatis "Großstädte und Kreise" cutoff). Rate responses surface `min_population_filter`, `population_year_used`, and `requested_year` in metadata so the examiner sees both the threshold and any population-year fallback (see §10).

### Hotspot / safe-zone endpoints
- `GET /zones/nearest?lat=&lon=&type={hotspot|safe}&year=&limit=`
- `GET /zones/around?lat=&lon=&year=` *(returns hotspots + safe + your_zone in one call)*

### Provenance endpoints (PDF-required)
- `GET /metadata/sources`
- `GET /import-runs`
- `GET /healthz` and `GET /healthz/data-quality`

Every response carries `metadata.license`, `metadata.snapshot_date`, `metadata.sources_used`.

---

## 6. Mandatory Examiner Questions

| # | Question | Endpoint(s) used |
|---|---|---|
| 1 | Earliest accident year in dataset? | `/aggregates/accidents?aggregate=earliest_year` |
| 2 | Personal-injury accidents in Saxony 2023? | `/aggregates/accidents?state=SN&year=2023&category=2` |
| 3 | Earliest year for North Rhine-Westphalia? | `/aggregates/accidents?state=NW&aggregate=earliest_year` |
| 4 | Earliest year for Mecklenburg-Western Pomerania? | `/aggregates/accidents?state=MV&aggregate=earliest_year` |
| 5 | Pedestrian accidents in Berlin 2023? | `/accidents?state=BE&year=2023&participant=pedestrian` |
| 6 | **Cross-dataset:** Accidents per 100k cars in a region | `/aggregates/accident-rate?denominator=cars_pkw` |
| 7 | Top 5 districts by fatal-accident rate per 100k inhabitants in 2024 (≥50k pop) | `/aggregates/accident-rate/top?level=district&year=2024&severity=fatal&denominator=population&limit=5` |

---

## 7. Phased Implementation

| Phase | Goal | Done when… | Rubric target |
|---|---|---|---|
| **0. Skeleton** | Repo + Docker compose + stub API | `curl /healthz` returns ok | — |
| **1. Schema** | All 9 tables + seeds | `docker compose up` produces schemed empty DB | 20% (schema) |
| **2. Regions ETL** | ~12k regions loaded | `GET /regions?level=state` returns 16 | 25% (integration) |
| **3. Accidents ETL** | ~3M rows loaded, idempotent | Mandatory Q1–Q5 answerable | 25% (integration) |
| **4. Indicators ETL** | ~300k values loaded | `GET /regions/{ags}/indicators` works | 25% (integration) |
| **5. Aggregation API** | Filters, ranks, rates | All 7 mandatory Qs pass | 20% (API correctness) |
| **6. Hotspots feature** | Zones precomputed + KNN | `/zones/around?lat=&lon=` <50ms | 20% + bonus |
| **7. Frontend** | Map + geolocation + presets | Demo flow runs end-to-end | 10% (live demo) |
| **8. Update script** | `python -m etl.update` from scratch | Fresh DB → loaded in one command | 25% (reproducibility) |
| **9. API docs** | OpenAPI export + Swagger UI | `/docs` complete, `api-docs/openapi.json` exists | 15% (docs) |
| **10. Quality checks** | Plausibility + limitations doc | `LIMITATIONS.md` + `/healthz/data-quality` | 10% (quality) |
| **11. Term paper** | ~5 pages, A4 | PDF in `paper/` ready for submission | First mark |
| **12. Submission** | ZIP + rehearsal | Outer ZIP uploaded by 25.06.2026 23:59 | Pass/Fail |

**Phase 6 hotspot/safe-zone rule (locked):**
- Grid: **250m × 250m squares in EPSG:25832** (ETRS89 / UTM 32N — the standard metric SRID for Germany). Use `ST_SquareGrid(250, ST_Transform(bbox_4326, 25832))`. **Do NOT grid in EPSG:4326** — `0.0023°` produces ~150×256 m rectangles at German latitudes, breaking the *Unfallhäufungsstellen* defence on zoom-in.
- Generate over the bounding box of inhabited regions only (`population > 0` join with `regions`)
- Hotspot: ≥5 accidents in cell during 2022–2024
- Safe: 0 accidents in cell during 2022–2024 AND centroid in region with `population > 0`
- Otherwise: unclassified (omitted from `accident_zones` entirely)
- Cell-to-region attribution: `ST_PointOnSurface(cell_geom_proj)` — same rule for hotspot and safe (boundary cells unambiguous)
- Storage: persist both `cell_geom_proj` (EPSG:25832, indexed for KNN distance) and `cell_geom` (EPSG:4326, served to frontend). API output transforms back via `ST_Transform(cell_geom_proj, 4326)` if storing only the projected version.
- GIST index on `accident_zones.cell_geom_proj` for KNN `<->` queries (verify in Phase 1) — KNN distance is only meaningful in a metric SRID

Justification (term paper / oral defence): 250 m chosen because Unfallatlas point precision is ~10–50 m; cells aggregate without losing meaningful signal. Threshold ≥5 in 3 years follows the German road-safety norm of *Unfallhäufungsstellen* (5 accidents same type within 1–3 years). 3-year window stays inside one Unfallatlas schema generation (encodings shifted ~2018→2020). Grid built in EPSG:25832 because `ST_SquareGrid` interprets size in the SRID's units — 250 in a metric SRID is exactly 250 metres; 0.0023° in EPSG:4326 is rectangles, not squares.

**Graceful-degradation ladder (replaces single 'cut Phase 6' decision):**

If Phase 3 slips and Phase 6 is at risk, descend the ladder rung-by-rung — do **not** silently skip. Each rung lists what changes in §4, §5, §7, §14:

1. **Full** (target): hotspot + safe zones, both endpoints (`/zones/nearest`, `/zones/around`), Leaflet rendering both layers.
2. **Hotspot-only** (saves ~2 h): drop safe-zone classification entirely. `accident_zones.kind` is always `'hotspot'`. Frontend hides the safe-zone toggle. Term paper §7 limitations gains one sentence ("safe-zone classification deferred — would require population-coverage validation across all rural cells"). No schema change beyond CHECK constraint relaxation.
3. **Static top-100 JSON** (saves ~5 h): no `accident_zones` table at all. Phase 6 outputs a precomputed `frontend/data/hotspots_top100.json` (district name + lat/lon + count). `/zones/nearest` and `/zones/around` removed from §5 and §6. Schema diagram (§4) drops `accident_zones`. Term paper §3 derived-table justification is removed; §5 endpoint section shrinks; rubric bonus likely lost but core Phase 7 demo (map + geolocation + 7 mandatory questions) is preserved.

If a different cut is needed, **Phase 10's `/healthz/data-quality` endpoint** is a better target than Phase 6: degrade it to a Markdown report in `LIMITATIONS.md` with a `python -m etl.checks` CLI, save ~1 h, zero rubric loss. Phase 6 is a resume differentiator and frontend showpiece — cut last.

**Phase dependencies:**
```
0 → 1 → 2 ┬→ 3 ┐
          └→ 4 ┴→ 5 → 6 → 7
8 orchestrates all ETL · 9, 10, 11 run in parallel late · 12 last
```

---

## 8. Folder Layout

```
DWT_Project/
├── PLAN.md                     ← this file
├── README.md                   ← user-facing setup guide
├── docker-compose.yml
├── pyproject.toml
├── .env.example
├── .gitignore
├── db/
│   └── init/
│       ├── 01_schema.sql
│       ├── 02_seed_sources.sql
│       ├── 03_seed_indicators.sql
│       ├── 04_seed_lookup_codes.sql
│       └── 05_seed_ags_history.sql
├── api/
│   ├── main.py
│   ├── db.py
│   ├── models.py
│   ├── routes/
│   │   ├── regions.py
│   │   ├── accidents.py
│   │   ├── aggregates.py
│   │   ├── zones.py
│   │   └── metadata.py
│   └── lib/responses.py        ← license envelope helper
├── etl/
│   ├── update.py               ← mandatory orchestrator
│   ├── unfallatlas.py
│   ├── regions.py
│   ├── indicators.py
│   ├── zones.py
│   ├── checks.py
│   ├── common.py               ← download / hash / run-tracking
│   └── mappers/
│       └── unfallatlas_columns.py  ← per-year column branches (LICHT→ULICHTVERH ~2020, STRZUSTAND 2020+, UIDENTSTLAE 2018+)
├── frontend/
│   ├── index.html
│   ├── app.js
│   ├── style.css
│   └── vendor/                 ← bundled MIT-licensed deps (offline-safe demo)
│       ├── leaflet/
│       └── chart.js/
├── rawData/                    ← downloaded raw files (gitignored)
├── resources/                  ← reference PDFs (data dictionaries)
├── api-docs/                   ← exported OpenAPI JSON
├── docs/
│   ├── SCHEMA.md
│   ├── LIMITATIONS.md
│   └── USAGE.md
├── tests/
│   ├── test_etl_unfallatlas.py
│   └── test_api_endpoints.py
└── paper/
    └── term-paper.md
```

---

## 9. Update Workflow & Reproducibility

The update script is mandatory per the rubric. It must:

1. **Discover** what's available at the source (parse manifest where possible)
2. **Skip** anything already current (compare `import_runs.source_timestamp` vs remote)
3. **Download → Hash (SHA-256) → Verify → Unzip**
4. **Parse** with the correct encoding (`latin-1` for Unfallatlas) and dtypes (`str` for AGS components)
5. **UPSERT** into target tables keyed by stable IDs into the `accidents.accident_uid` column. Source for the key depends on year:
   - **2018+:** `UIDENTSTLAE` (present and stable in Unfallatlas schema)
   - **2016–2017:** `UIDENTSTLAE` is absent. Synthesise a deterministic SHA-1 surrogate:
     ```
     accident_uid = 'sha1:' || sha1(
       year || '|' || OBJECTID || '|' || ULAND || '|' || UREGBEZ || '|' ||
       UKREIS || '|' || UGEMEINDE || '|' || XGCSWGS84 || '|' || YGCSWGS84
     )
     ```
     Same input file → same hash → re-running ETL is idempotent. Document the choice in `LIMITATIONS.md` and term paper §6.
   - For other tables: `UPSERT (indicator_id, region_id, year)` for `indicator_values`; `UPSERT (ags)` for `regions`.
6. **Record** every run in `import_runs` with file URL, hash, row counts, status
7. **Recompute** derived tables (`accident_zones`) after primary loads finish
8. **Surface** failures cleanly — partial success is logged, never silent

```bash
# Full refresh from scratch
docker compose up -d
python -m etl.update

# Refresh single source
python -m etl.update --source unfallatlas

# Refresh single year
python -m etl.update --source unfallatlas --year 2024

# Dry run (list what would happen)
python -m etl.update --dry-run
```

---

## 10. Provenance & Licensing Strategy

Every API response includes:

```json
{
  "results": [...],
  "metadata": {
    "sources_used": ["unfallatlas", "regionalstatistik"],
    "licenses": ["dl-de/by-2-0"],
    "snapshot_date": "2026-06-15",
    "import_run_ids": [42, 47],
    "requested_year": 2024,
    "population_year_used": 2023,
    "min_population_filter": 50000
  }
}
```

Rate endpoints auto-pick `MAX(year) ≤ requested_year` from `indicator_values` for the population denominator and surface the actual year used in `population_year_used`; this absorbs Destatis's multi-month publishing lag without crashing the demo. `min_population_filter` (default `50000`, the Destatis Großstädte cutoff) prevents per-capita ranking artifacts in tiny districts.

The `sources` table is hand-populated from each portal's metadata page. **Geoportal.NRW's CSW metadata service is acknowledged but not consumed programmatically** — manual transcription is rubric-aligned and avoids run-time dependency on a third-party metadata server. This decision is documented in the term paper.

---

## 11. Plausibility Checks (Phase 10)

Automated post-ETL checks:

- [ ] Total 2023 accidents ≈ 320k (matches Destatis published figure)
- [ ] Every state has accident data for ≥1 year
- [ ] Every imported year has ≥1 record
- [ ] No accident has `lat/lon` outside Germany's bounding box (47.27–55.06°N, 5.87–15.04°E)
- [ ] Every accident has a non-NULL `region_id`
- [ ] Every district has a state parent in the hierarchy
- [ ] Population indicator exists for every state for every year imported
- [ ] No ASCII replacement characters (`?`, `\ufffd`) in any text column
- [ ] Every `accident.region_id` resolves to a `regions` row (catches missing AGS history rows)
- [ ] Every state has population data for ≥1 year ≤ each accident year imported
- [ ] ETL fails loud if a source AGS is unknown to both `regions` and `regions_history` (no silent drop)
- [ ] **Idempotency:** re-running `python -m etl.update` against the same `rawData/` files produces identical row counts in every fact table — catches surrogate-key drift in 2016–2017 accidents before the examiner does

Failures surface via `GET /healthz/data-quality` and block submission until resolved.

---

## 12. Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| AGS leading-zero bug breaks joins | High | Critical | `dtype=str` everywhere; unit test in Phase 1 |
| CSV encoding corrupts umlauts | Medium | High | Force `latin-1`; assert no replacement chars |
| GENESIS API auth blocks ETL | Medium | Medium | Use Regionalstatistik CSV path |
| Submission deadline slip | Medium | Critical | Phase 11 target = 23.06; 2-day buffer |
| 3M-row import too slow | Low | Medium | Use psycopg `COPY`, not row-by-row |
| Live demo network failure | Medium | High | All data local; pre-recorded backup video |
| 2018 size dip hides bugs | Medium | Medium | Per-state-per-year row count assertions |
| Frontend bugs eat time | High | Medium | Vanilla JS only, no build step |
| Inner ZIP exceeds 10 MiB | Low | High | Don't ship `rawData/`; only source code |
| Plagiarism flag | Low | Critical | No code sharing with classmates; cite all libraries |

---

## 13. Submission Checklist (Phase 12)

**Inner ZIP (≤10 MiB):**
- [ ] `db/init/*.sql`
- [ ] `api/`, `etl/`, `frontend/` source code
- [ ] `docker-compose.yml`, `pyproject.toml`, `README.md`
- [ ] `api-docs/openapi.json`
- [ ] `docs/USAGE.md` — short usage manual
- [ ] No `rawData/` directory
- [ ] No `__pycache__/`, `.venv/`, or build artifacts
- [ ] No secrets (verify `.env.example` only, no `.env`)
- [ ] Run pre-zip cleanup: `find . -name "__pycache__" -type d -exec rm -rf {} +`
- [ ] Run pre-zip cleanup: `find . -name ".DS_Store" -delete`
- [ ] Run pre-zip cleanup: `find . -name "*.pyc" -delete`
- [ ] Use **explicit-list** `zip` (not `zip -r .`); verify final size < 2 MiB

**Outer ZIP `<matriculation_number>.zip`:**
- [ ] Term paper PDF (~5 pages content, A4 format)
- [ ] Inner ZIP

**Verify on a clean machine:**
- [ ] Unzip works
- [ ] `docker compose up -d` succeeds
- [ ] DB readiness wait: `docker compose exec db pg_isready -t 60` returns ready (Postgres accepts connections **before** running ETL — `compose up` returns before this is true)
- [ ] PostGIS extension present: `docker compose exec db psql -U postgres -c "SELECT PostGIS_Version();"` returns 3.4.x
- [ ] `python -m etl.update` produces working API
- [ ] All 7 mandatory questions answer correctly via API + frontend

**Demo rehearsal (10 minutes):**
- [ ] 1 min: architecture intro
- [ ] 2 min: Swagger UI walkthrough
- [ ] 5 min: frontend live demo of 7 mandatory questions + hotspot feature
- [ ] 2 min: Q&A buffer

**Administrative:**
- [ ] Submitted via OPAL by **25.06.2026 23:59**
- [ ] Enrolled for oral defense slot **26.06.2026 09:00** (first come first serve)

---

## 14. Term-Paper Outline (Phase 11)

Target: ~5 pages of content (cover/index/appendix/bibliography excluded).

1. **Introduction & motivation** (½ page) — what problem, why open data
2. **Source selection & access paths** (1 page) — the 4 sources, formats chosen, why CSV vs Shapefile
3. **Schema mapping & data harmonisation** (1 page) — the 9 tables, AGS as universal join key (canonical 2024 + `regions_history` lookup), ER diagram
4. **Database design & indexing** (1 page) — PostGIS choice, KNN index, fact-vs-indicator split
5. **API design decisions** (½ page) — REST endpoints, license envelope, error semantics
6. **Update workflow & reproducibility** (½ page) — manifest discovery, idempotency, hashing
7. **Limitations, plausibility checks, data quality** (½ page) — coverage gaps, AGS reorganizations, threshold rationale
8. **Appendix:** full API documentation (OpenAPI export)
9. **Cover page:** name, study course, matriculation number

Drafts of each section are written *during* the corresponding phase, not all at the end.

---

## 15. Open Decisions

All design decisions are closed:

- [x] Tech stack confirmed: Python + FastAPI + Postgres+PostGIS + Vanilla JS
- [x] Year scope confirmed: **2016–2024 full** (~3M rows, maximalist)
- [x] Indicator path confirmed: **Regionalstatistik CSV** (no auth, demo-reliable)
- [x] Solo submission confirmed

> All design decisions captured in `brainstorms/2026-06-18-plan-md-grilling.md`. The items below are *implementation-time* verifications, tracked per-phase, not design questions — they do **not** block Phase 0.

### Phase-time verifications

- **Phase 1:** GIST index DDL on `accident_zones.cell_geom_proj` (EPSG:25832 — see §7 Phase 6 projection note)
- **Phase 3:** per-year column mapper file at `etl/mappers/unfallatlas_columns.py`
- **Phase 4:** confirm Regionalstatistik table codes (candidates `12411-01-01-4` population, `46251-01-01-4` vehicles)
- **Phase 7:** "Use Chemnitz coordinates" geolocation fallback button in `frontend/app.js` (modern browsers require HTTPS for geolocation)
- **Phase 11:** AI-tool-disclosure sentence in term paper "tools used" section

---

## 16. Status Tracker

Update this table as phases complete:

| Phase | Status | Started | Completed | Notes |
|---|---|---|---|---|
| 0. Skeleton | ✅ Complete | 2026-06-22 | 2026-06-22 | Docker compose + stub API |
| 1. Schema | ✅ Complete | 2026-06-22 | 2026-06-22 | 9 tables + seeds + indexes |
| 2. Regions ETL | ✅ Complete | 2026-06-22 | 2026-06-22 | VG250 shapefile, /regions endpoints |
| 3. Accidents ETL | ✅ Complete | 2026-06-23 | 2026-06-23 | 2016-2024, SHA-1 surrogate for 2016/2018/2019, per-year column mapper |
| 4. Indicators ETL | ✅ Complete | 2026-06-23 | 2026-06-23 | Regionalstatistik pop+PKW, /regions/{ags}/indicators |
| 5. Aggregation API | ✅ Complete | 2026-06-23 | 2026-06-23 | All 7 mandatory Qs wired |
| 6. Hotspots feature | ⬜ Not started | — | — | |
| 7. Frontend | ⬜ Not started | — | — | |
| 8. Update script | ⬜ Not started | — | — | |
| 9. API docs | ⬜ Not started | — | — | |
| 10. Quality checks | ⬜ Not started | — | — | |
| 11. Term paper | ⬜ Not started | — | — | |
| 12. Submission | ⬜ Not started | — | — | |

Status legend: ⬜ Not started · 🟡 In progress · ✅ Complete · ⚠️ Blocked

---

## 17. References

- Project specification: `resources/DBW_Project_en.pdf`
- Data dictionary (EN): `resources/DSB_Unfallatlas_EN.pdf`
- Data dictionary (DE): `resources/DSB_Unfallatlas.pdf`
- Unfallatlas portal: https://www.opengeodata.nrw.de/produkte/transport_verkehr/unfallatlas/
- Unfallatlas viewer: https://unfallatlas.statistikportal.de/
- Regionalatlas: https://regionalatlas.statistikportal.de/
- Regionalstatistik: https://www.regionalstatistik.de/genesis/online
- GENESIS: https://www-genesis.destatis.de/datenbank/online
- GV-ISys: https://www.destatis.de/DE/Themen/Laender-Regionen/Regionales/Gemeindeverzeichnis/_inhalt.html
- License: https://www.govdata.de/dl-de/by-2-0
