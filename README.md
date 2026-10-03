# GeoCrash DE

A spatial-analysis platform for German traffic accidents (2016–2024), built as the term project for TU Chemnitz's *Datenbanken und Web-Techniken* course. Four public government datasets go in, one PostGIS database holds them, a FastAPI service exposes them, and a browser map turns them into something you can actually look at and reason about.

This document has one job: let someone who has never opened this repo understand it well enough to run it, defend it in an oral exam, and eventually take it over.

---

## Part 1 — Orientation

### What problem this solves

Germany publishes accident, population, vehicle-registration, and administrative-boundary data as separate open datasets, in separate formats, updated on separate schedules, using region codes that occasionally get reorganized. None of that is directly queryable together out of the box. This project's job is to fuse them into one coherent, queryable, mappable whole, and to do it in a way that can be regenerated from scratch on demand — not a one-time manual import.

### The four moving parts

```
   open data portals            one database              one API                one page
  ┌──────────────────┐      ┌──────────────────┐      ┌──────────────┐      ┌──────────────────┐
  │ Unfallatlas       │      │                  │      │              │      │ Leaflet map      │
  │ Regionalatlas     │ ETL  │  PostgreSQL 16   │ SQL  │  FastAPI     │ HTTP │ + deck.gl overlay │
  │ Regionalstatistik │─────▶│  + PostGIS 3.4   │─────▶│  (Python)    │─────▶│ + Chart.js panels │
  │ AGS history       │      │  9 tables        │      │              │      │                  │
  └──────────────────┘      └──────────────────┘      └──────────────┘      └──────────────────┘
```

Each arrow is a one-way, one-purpose contract:

- The **ETL** only writes rows. It never serves a request and never renders anything.
- The **database** only stores and answers queries. It has no opinion about HTTP or pixels.
- The **API** only turns a URL into SQL and SQL results into JSON, tagged with where the data came from.
- The **frontend** only turns JSON into something visual. It never talks to Postgres directly.

Nothing here is a microservice architecture — it's two Docker containers (`db`, `api`) and a static frontend served by the API container. For a one-person, ten-day academic project, that's the right amount of infrastructure: enough to be reproducible, not so much that it becomes its own maintenance burden.

### Running it

```bash
docker compose up -d --build                 # start Postgres+PostGIS and the API
docker compose exec db pg_isready -U postgres -d dwt
curl http://localhost:8000/healthz

python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

python -m etl.update                          # download, hash, parse, load everything
```

| What | Where |
| --- | --- |
| Map | http://localhost:8000 |
| Swagger docs | http://localhost:8000/docs |
| Health / data quality | http://localhost:8000/healthz, /healthz/data-quality |
| Postgres from host | `localhost:5433`, db `dwt`, user/pass `postgres`/`postgres` |

Narrower ETL runs when you don't want the whole pipeline:

```bash
python -m etl.update --dry-run
python -m etl.update --source regionalatlas
python -m etl.update --source unfallatlas --year 2024
python -m etl.update --source regionalstatistik
python -m etl.update --source zones           # recompute hotspot grid after new accident years
```

Wipe and start over:

```bash
docker compose down -v && docker compose up -d --build && python -m etl.update
```

---

## Part 2 — The five things worth understanding deeply

Everything else in this repo is detail in service of these five ideas. If you (or an examiner) only remember five things, make it these.

### 1. It's one database, not "many databases" — split by grain, not by source

Looking at the schema diagram, it's tempting to describe this as "lots of databases." It isn't. It's **one PostgreSQL database called `dwt`, with one PostGIS extension, holding 9 tables.** The reason there are 9 tables and not 1 or 2 is that each concept in this domain has a genuinely different *grain* — what one row represents:

- one row in `accidents` = one crash (≈3,000,000 of them)
- one row in `regions` = one administrative area (state, district, or municipality)
- one row in `indicator_values` = one (indicator, region, year) measurement — population *and* vehicle counts live in the same tidy table, distinguished by an `indicators` row, so adding a third indicator later needs zero schema changes
- one row in `accident_zones` = one 250m grid cell that's been classified as a hotspot or a safe zone — this table isn't sourced from the outside at all, it's **computed** from `accidents`
- `sources`, `import_runs`, `regions_history`, `lookup_codes` are small bookkeeping tables: what dataset came from where, under what license, when, and how do old region codes map to current ones

Splitting by source instead of by grain would have meant duplicating a district's population into every one of its accident rows, and rewriting millions of rows every time a population figure changed. Splitting into *separate databases* per source would have made the entire point of the project — joining accidents against population and vehicle counts to compute a rate — either impossible or dependent on cross-database plumbing (`postgres_fdw`) that buys nothing at this scale. One database, normalized by grain, is the boring and correct answer.

### 2. PostGIS earns its place because three operations are inherently spatial

This project isn't "a database that happens to store coordinates." Three real operations only make sense with proper spatial types and indexes:

- **Point-in-polygon**: which district does this accident sit inside? (`ST_Contains`)
- **Nearest-neighbour**: which precomputed hotspot is closest to where the user clicked? (the `<->` KNN operator against a GIST index)
- **Polygon rendering**: turning district boundaries into something Leaflet can draw

Plain relational storage (lat/lon as two floats, boundaries as WKT text) would force all of this logic into application code, with no index support — a bounding-box query over 3M rows would become a full table scan. PostGIS's `GEOMETRY` types plus GIST indexes make all three operations index-backed and fast. This is also why the grid used for hotspot cells is built in **EPSG:25832** (a metric projection for Germany) rather than plain lat/lon degrees — a "250" cell size only means 250 real metres in a metric SRID; the same number in EPSG:4326 would mean 250 degrees, and even a converted-equivalent value produces non-square rectangles at German latitudes, since a degree of longitude is shorter than a degree of latitude away from the equator.

### 3. The API speaks raw, parameterized SQL — deliberately, not as a shortcut

`api/db.py` sets up one SQLAlchemy engine using the `psycopg` driver, and FastAPI hands each request its own session via `Depends(get_db)` — opened, used, closed, no state shared across requests. But the actual queries in `api/routes/*.py` are hand-written `text("...")` SQL with bound parameters, not ORM-generated queries. That's intentional: the queries lean on `ST_Contains`, `ST_Distance`, `<->`, `ST_Transform`, and dynamic optional `WHERE` clauses driven by query-string filters — exactly the kind of SQL an ORM query builder tends to obscure rather than clarify. Writing it by hand keeps `EXPLAIN ANALYZE` plans directly readable, which matters when the term paper needs to justify why a particular index exists.

The one place this gets delicate is the `participant` filter (pedestrian/bike/car/etc.), where a *column name*, not a value, has to be inserted into the SQL — something bound parameters can't do, since they only parameterize values. That column name is resolved through a small closed dictionary (`_PARTICIPANT_COL`) with an assertion guarding it, so the only strings that can ever reach the SQL string are six known, hard-coded literals. Every other filter — state codes, years, categories, coordinates — is a normal bound parameter.

### 4. Point data has a journey: raw German government CSV → clean geometry → cheap-to-query fact table

The ~3 million accident points didn't arrive ready to use. `etl/unfallatlas.py` does, per year:

1. Opens a per-year ZIP from `rawData/Accidents/`, sniffs its encoding (some years are `latin-1`, some are UTF-8-with-BOM — guessing wrong corrupts every umlaut).
2. Renames whatever that year's column names happen to be into one canonical set — Destatis changed column names and added new ones across 2016–2024 (`etl/mappers/unfallatlas_columns.py` carries the year-by-year mapping so nothing downstream has to know about it).
3. Builds a stable identity for every row so the ETL can be re-run without duplicating anything: 2018-onward rows already carry a stable `UIDENTSTLAE` from Destatis; 2016–2017 rows don't have one, so a SHA-1 hash over deterministic fields (year, object ID, region codes, coordinates) is synthesised as a surrogate key — same file in, same hash out, every time.
4. Parses `XGCSWGS84`/`YGCSWGS84` — which use a **comma** as the decimal separator, per German CSV convention — into proper floats, and writes them straight into a PostGIS `POINT` geometry in the same INSERT statement that stores the raw lat/lon, so the two can never drift apart.
5. Resolves each accident's raw district code to the **current (2024)** canonical region ID, using both the live `regions` table and the `regions_history` reorganization table, plus two structural rules for Hamburg/Berlin sub-district codes that would otherwise need to be listed one by one.
6. Batches everything into `INSERT ... ON CONFLICT (accident_uid) DO NOTHING` — fast enough for 3M rows, and idempotent by construction.
7. Logs the whole run into `import_runs`, and refuses to continue silently if more than 5% of a year's rows fail to resolve to a known district — a deliberate "loud failure over silent corruption" rule.

### 5. The map never draws 3 million points — it draws a different truth at every zoom level

Rendering all 3M accidents at once would be both too slow and visually meaningless (a black smear over the whole country). Instead, `frontend/app.js` picks what to show based on how far in the user has zoomed, and always asks the API only for what's currently on screen:

- **Zoomed out** → a **choropleth**: districts colored by accident count, pulled from `/aggregates/accidents?level=district`. At this scale, individual points carry no information; a colored map does.
- **Zoomed in partway** → a **3D hex-bin layer**, rendered by deck.gl on a canvas overlaid on the Leaflet map. It aggregates whichever raw points are currently in the viewport into hexagonal bins and extrudes them by count — a GPU-accelerated way to show density without needing a server-side pre-aggregation table for this particular view.
- **Zoomed all the way in** → **individual points**, drawn as Leaflet circle markers (and, past a further threshold, small emoji markers) on a shared canvas renderer rather than one DOM element per marker, so hundreds of markers stay responsive.
- **A separate hotspot overlay**, independent of all three layers above, comes from the *precomputed* `accident_zones` table via `/zones/nearest` and `/zones/around` — this is not "live density," it's "officially meets the ≥5-accidents-in-250m-in-3-years definition," queried instantly via a KNN index instead of aggregating 3M rows on every click.

Every layer fetches only its current viewport (`lat_min/lat_max/lon_min/lon_max` query params), and a zoom-dependent cap limits how many raw points are ever requested at once. deck.gl and Leaflet don't share a coordinate convention natively (deck.gl assumes 512px tiles, Leaflet uses 256px), so the frontend subtracts 1 from Leaflet's zoom level when constructing deck.gl's view state to keep the two layers aligned.

---

## Part 3 — Reference material

### Database tables

| Table | One row is | Notable columns |
| --- | --- | --- |
| `accidents` | one crash | `accident_uid` (unique, idempotency key), `year`, `category`, six `participant_*` booleans, `geom POINT(4326)` |
| `regions` | one state/district/municipality | `ags TEXT` primary key (never integer — leading zeros are meaningful), `level`, `parent_ags`, `geom MULTIPOLYGON(4326)` |
| `regions_history` | one old→new AGS mapping | resolves pre-reform district codes to current ones |
| `indicators` | one indicator definition | e.g. `population`, `cars_pkw` |
| `indicator_values` | one region+year+indicator measurement | composite PK `(indicator_id, region_id, year)` |
| `accident_zones` | one classified 250m grid cell | `kind` (`hotspot`/`safe`), `cell_geom_proj` (EPSG:25832, for KNN), `cell_geom` (EPSG:4326, for the frontend) |
| `lookup_codes` | one coded value → label | e.g. `category=1` → "fatal" |
| `sources` | one external dataset's metadata | name, license, URL |
| `import_runs` | one ETL execution | status, row counts, file hash, timestamps |

Indexes exist for exactly the queries that need them: `(year)` and `(region_id, year)` cover the mandatory examiner questions; a **partial** index `(region_id, year) WHERE category = 1` keeps the fatal-only ranking query fast without indexing the other 97.5% of rows; GIST indexes on every geometry column back the bounding-box, point-in-polygon, and KNN queries.

### The four data sources

| Source | Gives you | Why this one, in this format |
| --- | --- | --- |
| Unfallatlas | ~3M point-level accidents, 2016–2024 | Already in WGS84 coordinate columns — no reprojection needed for the fact table |
| Regionalatlas / VG250 | State & district polygons | The official boundary source; needed for choropleths and region attribution |
| Regionalstatistik (GENESIS) | Population & registered cars per region/year | Used as a **downloaded CSV snapshot**, not the live GENESIS API — removes an auth/rate-limit/uptime dependency from a live oral-exam demo, while still satisfying "≥3 official sources" |
| GV-ISys / AGS history | Old→new district code mappings | Hand-seeded; needed because Germany periodically merges/splits districts (Kreisreform) |

### API surface

| Router | Endpoints |
| --- | --- |
| `regions` | `GET /regions?level=`, `GET /regions/{ags}`, `GET /regions/{ags}/indicators` |
| `accidents` | `GET /accidents` — filters: `state`, `ags`, `year`, `category`, `participant`, bbox params, `limit`, `offset` |
| `aggregates` | `GET /aggregates/accidents`, `GET /aggregates/accident-rate`, `GET /aggregates/accident-rate/top` |
| `zones` | `GET /zones/nearest`, `GET /zones/around`, `GET /zones/nearby-hazards` |
| `metadata` | `GET /metadata/sources`, `GET /import-runs`, `GET /healthz`, `GET /healthz/data-quality` |

Every response is wrapped the same way:

```json
{
  "results": [...],
  "metadata": {
    "sources_used": ["unfallatlas"],
    "licenses": ["dl-de/by-2-0"],
    "snapshot_date": "2026-07-06",
    "import_run_ids": []
  }
}
```

so any consumer — including an examiner poking at Swagger — can see exactly which dataset and license backs a given answer without cross-referencing separate docs.

```bash
curl "http://localhost:8000/aggregates/accidents?aggregate=earliest_year"                                            # Q1
curl "http://localhost:8000/aggregates/accidents?state=SN&year=2023&category=2"                                       # Q2
curl "http://localhost:8000/accidents?state=BE&year=2023&participant=pedestrian&limit=100"                            # Q5
curl "http://localhost:8000/aggregates/accident-rate?denominator=cars_pkw&year=2023&level=district"                   # Q6
curl "http://localhost:8000/aggregates/accident-rate/top?level=district&year=2024&severity=fatal&denominator=population&limit=5&min_population=50000"  # Q7
curl "http://localhost:8000/zones/nearest?lat=52.52&lon=13.405&limit=5"
```

### Hotspot grid, precisely

- 250m × 250m cells, built in EPSG:25832.
- **Hotspot** = ≥5 accidents in a cell, 2022–2024 — matches the German road-safety definition of an *Unfallhäufungsstelle*.
- **Safe zone** = a zero-accident cell that's an immediate 8-connected neighbour of a hotspot and sits inside a populated district — restricting to hotspot neighbours (instead of every empty cell in the country) keeps the table small and keeps "nearby hazards" results locally relevant instead of noise.
- Cell → district attribution uses `ST_PointOnSurface` (guaranteed inside the polygon, unlike a plain centroid) joined via `ST_Contains`.
- Recomputed by `python -m etl.update --source zones` — it's a **snapshot**, so it goes stale if new accident years are loaded and zones aren't recomputed afterward.

### Decisions and their alternatives

| Chose | Over | Because |
| --- | --- | --- |
| PostgreSQL + PostGIS | MongoDB / MySQL / SQLite | Only PostGIS gives mature, indexed `ST_Contains` / KNN / polygon storage out of the box |
| FastAPI | Flask / Django | Free OpenAPI docs from type hints — a rubric deliverable — with minimal boilerplate |
| Hand-written parameterized SQL | SQLAlchemy ORM queries | Spatial predicates and dynamic filters are clearer and more inspectable as SQL than as ORM-generated SQL |
| Vanilla JS + Leaflet + deck.gl | A bundled React/Vue SPA | No build step — an examiner can read `app.js` directly, nothing compiled or minified in between |
| Plain SQL files in `db/init/` | Alembic migrations | Schema is created once per fresh Docker volume; a migration framework is overhead this project's lifecycle doesn't need |
| Precomputed `accident_zones` | Live aggregation per request | 3M-row live spatial aggregation is too slow for interactive panning; precomputing keeps KNN lookups index-driven |
| CSV snapshot of Regionalstatistik | Live GENESIS API | Removes a live network dependency from the demo while still satisfying the source-count requirement |
| SHA-1 surrogate key for 2016–2017 | Dropping years without a native stable ID | Keeps the full 2016–2024 range usable while preserving idempotent re-runs |

### Known rough edges (for whoever inherits this)

- `_flag_series` in `etl/unfallatlas.py` currently maps a blank/unparseable participant flag to `FALSE` rather than `NULL` — "unknown" and "confirmed not involved" aren't currently distinguishable in the data; a `WHERE participant_pedestrian IS NULL` query won't find these rows.
- `accident_zones` is a snapshot table — recompute it after loading new accident years, or the hotspot layer quietly serves stale data.
- Hamburg/Berlin sub-district codes resolve via a structural prefix rule (`02xxx→02000`, `11xxx→11000`); a genuinely new prefix outside those two would still need a manual `regions_history` row.
- A longer, line-anchored list of past code-review findings (some already fixed) lives in `Challenges.md` — verify against current code before trusting an entry there.

### Where to make a change

| Task | File(s) |
| --- | --- |
| New API endpoint | `api/routes/<area>.py`, register in `api/main.py` |
| New/changed filter | `api/routes/accidents.py`, `api/routes/aggregates.py` |
| New data source | new file under `etl/`, wire into `etl/update.py`, seed row in `db/init/02_seed_sources.sql` |
| Accident-year parsing quirks | `etl/unfallatlas.py`, `etl/mappers/unfallatlas_columns.py` |
| Recompute hotspots | `python -m etl.update --source zones` |
| Map zoom thresholds / layer switching | `frontend/app.js` (`POINT_EMOJI_MIN_ZOOM`, `HEX_POINT_LIMIT`, `switchLayer()`) |
| Schema changes | `db/init/01_schema.sql` — only applied to a **fresh** volume (`docker compose down -v && up`), not auto-migrated |
| Full original design rationale | `PLAN.md` |

---

## Part 4 — Examiner Q&A

**Why does this look like "many databases" in the diagram?**
It isn't — one PostgreSQL database, one PostGIS extension, 9 tables split by data grain (crash vs. region vs. indicator-value vs. computed zone), not by source. The whole point is that one query can join across all of them — e.g. accidents × regions × population for a per-capita rate — which separate databases would make either impossible or dependent on cross-database plumbing that buys nothing at this scale.

**Why PostgreSQL/PostGIS instead of a NoSQL store or a plain relational database?**
Three operations are inherently spatial — point-in-polygon region attribution, nearest-hotspot lookup, and polygon rendering. PostGIS gives indexed, standards-based implementations of all three (`ST_Contains`, the `<->` KNN operator, GIST indexes). Plain MySQL/SQLite spatial support is weaker or absent; a document store would require reimplementing spatial indexing by hand.

**What's a fact table vs. a dimension table here?**
`accidents` and `indicator_values` are facts (high-volume events/measurements). `regions`, `indicators`, `lookup_codes`, `sources` are dimensions (small, descriptive). `accident_zones` is neither sourced externally — it's derived, computed from the fact table itself.

**Why is `ags` a `TEXT` column, never an integer?**
German AGS codes carry meaningful leading zeros (`"01001"` ≠ integer `1001`). Casting to int silently breaks joins and comparisons. Enforced with `dtype=str` throughout the ETL as a hard project rule.

**Why does `accident_zones` store two geometry columns?**
`cell_geom_proj` (EPSG:25832, metric) is what makes KNN distance queries meaningful in real metres. `cell_geom` (EPSG:4326) is what the frontend/GeoJSON layer expects. Both are computed once at ETL time rather than converted on every read.

**Why a 250m grid, and why build it in EPSG:25832 instead of lat/lon?**
250m roughly matches Unfallatlas's point precision (~10–50m) — coarse enough to reveal real clustering, fine enough not to merge separate hotspots into one. It has to be built in a metric SRID because a "250" cell size only means 250 real metres there; the same number in EPSG:4326 means 250 degrees, and even a converted-equivalent degree value produces non-square rectangles at German latitudes.

**Why 5+ accidents in 3 years for the hotspot threshold?**
That's the German road-safety definition of an *Unfallhäufungsstelle* — not a number invented for this project.

**How are historical district boundary changes (Kreisreform) handled?**
`regions_history` maps retired AGS codes to their canonical 2024 equivalent. Every accident's raw district code is resolved through both `regions` and `regions_history` before being stored, so old accidents attribute correctly to today's district boundaries.

**ORM or raw SQL for talking to Postgres?**
Raw parameterized SQL via SQLAlchemy's `text()`, on top of a connection pool and per-request session managed by SQLAlchemy. Deliberate: the queries are spatial and have dynamic optional filters, which raw SQL expresses more directly and keeps `EXPLAIN ANALYZE`-inspectable, versus an ORM query builder that would obscure the same logic.

**Is there any SQL-injection risk?**
The only place a *column name* (not a value) is interpolated is the `participant` filter, and it's resolved through a closed, hard-coded dictionary with an assertion — only six known literals can ever reach the SQL string. Every other filter is a bound parameter.

**How do you know the ETL is idempotent, as required?**
Every insert is `ON CONFLICT DO NOTHING`/`DO UPDATE` keyed on a stable ID. 2018+ accidents use Destatis's own `UIDENTSTLAE`; 2016–2017 (which lack one) get a deterministic SHA-1 surrogate over stable source fields — same file, same hash, every re-run, so nothing duplicates.

**How did you get the point coordinates into a usable geometry?**
`XGCSWGS84`/`YGCSWGS84` use a comma decimal separator (German CSV convention); parsed to floats, then written straight into a PostGIS `POINT(4326)` in the same INSERT that stores the raw lat/lon, so geometry and raw columns can never disagree.

**What happens when a district code can't be resolved?**
It's counted, not silently dropped. If more than 5% of a year's rows fail to resolve, the ETL raises and stops rather than continuing with `NULL` region attribution — loud failure over silent data corruption.

**Why a CSV snapshot instead of the live GENESIS API?**
Removes an auth/rate-limit/uptime dependency from a live oral-exam demo, while still satisfying the requirement of using an official public source; the snapshot date is recorded and exposed via the metadata endpoint.

**With 3M points, how do you avoid rendering everything at once?**
Rendering strategy changes with zoom: choropleth aggregate counts when zoomed out, deck.gl GPU-aggregated 3D hex bins at medium zoom, individual canvas-rendered markers only at street level — each layer fetching only its current map-viewport bounding box, capped by a zoom-dependent point limit.

**Why deck.gl on top of Leaflet instead of just Leaflet markers?**
Leaflet markers don't scale past a few thousand simultaneous points and don't express density via extrusion. deck.gl's `HexagonLayer` is GPU-accelerated and aggregates on the fly — Leaflet stays the base map and point/choropleth layer, deck.gl is a synced canvas overlay purely for the density view.

**How is the hotspot layer different from the live hex-bin layer — isn't that redundant?**
The hex layer is live, client-side, re-aggregated every pan — a "look at density right now" aid. The hotspot layer comes from the precomputed `accident_zones` table, built with an explicit, defensible rule (≥5 accidents / 250m / 3yr) — it's the authoritative answer, queried via an index instead of a live aggregation over 3M rows.

**How would someone reproduce this whole thing from a clean machine?**
`docker compose up -d --build` creates the containers and applies the schema to a fresh volume; `python -m etl.update` downloads, hashes, and loads every source in one command. That exact path is what's exercised before submission.

**How do you know if an import failed or went stale?**
`import_runs` logs every ETL execution — status, row counts, file hash, error message if any — surfaced without needing direct DB access via `GET /import-runs` and `GET /healthz/data-quality`.
