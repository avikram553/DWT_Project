# GeoCrash DE — Architecture, Database Design & Defense Document

**Project:** Spatial analysis platform for German traffic accidents (2016–2024)
**Course:** TU Chemnitz — *Datenbanken und Web-Techniken* (DBW)
**Purpose of this document:** a single place to (a) explain every architecture and database decision and its trade-off, (b) justify why this stack is the right one, and (c) walk into a 10-minute presentation + live demo knowing exactly what will be asked and how each question is answered by a decision already baked into the system.

Read the README for a run-it/take-it-over orientation. Read **this** file to *defend* the project.

---

## 0. The 30-second pitch (say this first, verbatim if you like)

> Germany publishes accident data, population, vehicle registrations, and administrative boundaries as four separate open datasets — different formats, different schedules, region codes that get reorganized over time. None of it is queryable together out of the box. GeoCrash fuses them into **one PostGIS database**, exposes them through **one FastAPI service**, and renders them on **one interactive map** — reproducible from scratch with two commands. The interesting problems here are all at the seams: joining data across grains to compute a per-capita rate, doing point-in-polygon and nearest-neighbour lookups over 2.1 million points fast, and rendering 2.1 million points without melting the browser.

That paragraph maps 1:1 to the four moving parts and to the three hardest problems. Everything below expands it.

---

## 1. The 10-minute presentation blueprint

You have ~10 minutes. Don't narrate code. Tell the story of the data moving through the system, then prove it live.

| Time | Segment | What you show | The one sentence that must land |
| --- | --- | --- | --- |
| 0:00–1:00 | **Problem** | The 4-source diagram | "Four datasets, one queryable whole, regenerable on demand." |
| 1:00–3:00 | **Architecture** | The one-way pipeline (ETL → DB → API → map) | "Each arrow is a one-way, one-purpose contract — nothing leaks backwards." |
| 3:00–5:00 | **Database design** | Schema diagram + the 3 spatial operations | "Nine tables split **by grain, not by source** — so one query can join accidents × regions × population." |
| 5:00–9:30 | **Live demo** | Map + the 7 mandatory questions + hotspots | "Every answer on screen comes from stored data, and the metadata block shows its source and license." |
| 9:30–10:00 | **Reproducibility & close** | `docker compose up` + `python -m etl.update` | "Two commands rebuild the entire thing on a clean machine." |

**Golden rule for the demo:** everything is local. No live network calls during the demo (that was a deliberate design choice — see §5, Regionalstatistik). If Wi-Fi dies, the demo still runs.

---

## 2. Architecture

### 2.1 The four moving parts

```
   open data portals            one database              one API                one page
  ┌──────────────────┐      ┌──────────────────┐      ┌──────────────┐      ┌───────────────────┐
  │ Unfallatlas       │      │                  │      │              │      │ Leaflet base map  │
  │ Regionalatlas     │ ETL  │  PostgreSQL 16   │ SQL  │  FastAPI     │ HTTP │ + deck.gl overlay  │
  │ Regionalstatistik │─────▶│  + PostGIS 3.4   │─────▶│  (Python)    │─────▶│ + Chart.js panels  │
  │ AGS history       │      │  9 tables        │      │              │      │                   │
  └──────────────────┘      └──────────────────┘      └──────────────┘      └───────────────────┘
        (write-only)            (store + query)          (URL → SQL → JSON)      (JSON → pixels)
```

### 2.2 The one-way contracts (this is the architecture's whole thesis)

Each arrow points one way and does exactly one job. This is the single most defensible thing about the design, because it means each layer can be reasoned about, tested, and swapped in isolation.

- **ETL only writes rows.** It never serves a request, never renders anything. It is a batch process you run on demand.
- **The database only stores and answers queries.** It has no opinion about HTTP or pixels.
- **The API only turns a URL into parameterized SQL, and SQL results into JSON** — tagged with which source and license backs the answer.
- **The frontend only turns JSON into visuals.** It never talks to Postgres directly; it only knows the API.

**Why this matters in the exam:** if asked "how would you add a new indicator / new endpoint / new map layer," the answer is always "at exactly one layer, without touching the others." That's the payoff of one-way contracts.

### 2.3 Why two containers and a static frontend — not microservices

The whole system is **two Docker containers** (`db`, `api`) plus a static frontend served by the `api` container. That is deliberately *not* a microservice architecture.

- **Trade-off considered:** microservices (separate ETL service, tile server, API gateway, etc.).
- **Why rejected:** for a one-person, ~10-day academic project, microservices add orchestration, network, and failure surface that buy nothing. The rubric rewards *reproducibility and correctness*, not distributed-systems ceremony.
- **What we kept from "proper" infra:** containerization (reproducible Postgres+PostGIS version pinned to `postgis/postgis:16-3.4`), a health-checked DB dependency, and idempotent ETL. Enough to be reproducible; not so much it becomes its own maintenance burden.

---

## 3. Database design — decisions and rationale

This is the heart of a *Datenbanken* project, so it gets the most defense.

### 3.1 One database, nine tables — split **by grain, not by source**

It looks like "many databases" in the diagram. It is not. It is **one PostgreSQL database `dwt`, one PostGIS extension, nine tables.** There are nine tables because each concept has a genuinely different *grain* — what one row represents:

| Table | One row is | Type | Notable columns |
| --- | --- | --- | --- |
| `accidents` | one crash (~2,100,000) | **fact** | `accident_uid` (unique idempotency key), `year`, `category`, six `participant_*` booleans, `geom POINT(4326)` |
| `indicator_values` | one (indicator, region, year) measurement | **fact** | composite PK `(indicator_id, region_id, year)` |
| `regions` | one state/district/municipality | dimension | `ags TEXT` PK (never integer), `level` enum, `parent_ags`, `population_latest`, `geom MULTIPOLYGON(4326)` |
| `indicators` | one indicator definition (`population`, `cars_pkw`) | dimension | `name`, `unit`, `source_id` |
| `lookup_codes` | one coded value → label | dimension | `category`, `code`, `label_de`, `label_en` |
| `sources` | one external dataset's metadata | dimension | `name`, `license`, `url`, `last_checked` |
| `accident_zones` | one classified 250 m grid cell | **derived** | `kind` (`hotspot`/`safe`), `cell_geom_proj` (25832), `cell_geom` (4326) |
| `regions_history` | one old→new AGS mapping | bookkeeping | resolves pre-reform codes to current |
| `import_runs` | one ETL execution | bookkeeping | status, row counts, file hash, timestamps |

**Why by grain and not by source:**

- **Splitting by source** would duplicate a district's population into every one of its ~thousands of accident rows, and force rewriting millions of rows every time a population figure changed. That violates normalization and destroys update integrity.
- **Splitting into separate databases per source** would make the *entire point* of the project — joining accidents against population and vehicles to compute a rate — either impossible or dependent on cross-database plumbing (`postgres_fdw`) that adds complexity and buys nothing at this scale.
- **One database, normalized by grain,** lets a single SQL statement join `accidents × regions × indicator_values` for a per-capita rate. That join *is* the project.

**The `indicator_values` design is the cleverest normalization move:** population *and* registered cars live in the **same tidy (long-format) table**, distinguished by which `indicators` row they point to. Adding a third indicator later (e.g. road length, bicycle counts) needs **zero schema changes** — just a new `indicators` row and new `indicator_values` rows. This is textbook tidy-data / EAV-done-right.

### 3.2 Fact vs. dimension (the star-schema lens)

- **Facts** (high-volume, event/measurement grain): `accidents`, `indicator_values`.
- **Dimensions** (small, descriptive, join targets): `regions`, `indicators`, `lookup_codes`, `sources`.
- **Derived**: `accident_zones` is not sourced externally at all — it is **computed** from the fact table.

If an examiner asks "is this a data warehouse?" — it's a small star-ish schema: fact tables in the middle, dimension tables around them, joined on `region_id`/`year`. Not a formal OLAP cube, but the same shape and the same reasoning.

### 3.3 Why PostGIS earns its place — three operations are inherently spatial

This is not "a relational DB that happens to store coordinates." Three operations only make sense with real spatial types and indexes:

1. **Point-in-polygon** — which district does this accident sit inside? → `ST_Contains`
2. **Nearest-neighbour** — which precomputed hotspot is closest to where the user clicked? → the `<->` KNN operator against a GiST index
3. **Polygon rendering** — turning district boundaries into GeoJSON Leaflet can draw

Store lat/lon as two floats and boundaries as WKT text instead, and all three collapse into application-code loops with **no index support** — a bounding-box query over 2.1M rows becomes a full table scan on every map pan. PostGIS's `GEOMETRY` types + GiST indexes make all three **index-backed** and interactive.

### 3.4 Why `accident_zones` stores **two** geometry columns

- `cell_geom_proj GEOMETRY(POLYGON, 25832)` — **EPSG:25832 is a metric projection for Germany.** KNN distance (`<->`) and `ST_Distance` only return meaningful *metres* in a metric SRID. This is the column the KNN index sits on.
- `cell_geom GEOMETRY(POLYGON, 4326)` — **WGS84**, what the frontend/GeoJSON layer expects.

Both are computed **once at ETL time**, not reprojected on every read. Storage is cheap; per-request `ST_Transform` on every pan is not.

**Why the 250 m grid is built in 25832, not lat/lon:** a "250" cell size only means *250 real metres* in a metric SRID. The same number in EPSG:4326 means 250 *degrees*; and even a converted-equivalent degree value produces **non-square rectangles** at German latitudes, because a degree of longitude is shorter than a degree of latitude away from the equator.

### 3.5 Why `ags` is `TEXT`, never integer

German AGS region codes carry **meaningful leading zeros** (`"01001"` ≠ integer `1001`). Casting to int silently breaks joins and comparisons. It's a hard project rule enforced with `dtype=str` throughout the ETL and `TEXT` primary keys in the schema. (This is the single most likely "gotcha" question — see §7.)

### 3.6 Indexes exist for exactly the queries that need them

| Index | Backs | Note |
| --- | --- | --- |
| `accidents(year)` | Q1, Q3, Q4 (`MIN(year)`) | B-tree |
| `accidents(region_id, year)` | Q2, Q5, Q6, Q7 + every aggregate | the workhorse composite |
| `accidents(year, category)` | Q2 severity filter | |
| `accidents(region_id, year) WHERE category = 1` | **partial** index — Q7 fatal-only ranking | fatal is ~2.5% of rows; indexing only those keeps it tiny |
| `accidents USING GiST(geom)` | bbox + point-in-polygon | |
| `regions USING GiST(geom)` | choropleth rendering, `ST_Contains` | |
| `accident_zones USING GiST(cell_geom_proj)` | KNN `<->` for `/zones/around` | metric SRID |
| `indicator_values(indicator_id, region_id, year DESC)` | population fallback (`MAX year ≤ requested`) | |

**Verification claim you can make:** `EXPLAIN ANALYZE` on the Q7 path shows index scans, p95 < 200 ms cold cache. The **partial index** is the show-off decision — it demonstrates you index for a *query shape*, not reflexively for a column.

### 3.7 The one deliberate denormalization: `regions.population_latest`

`population_latest` is copied out of `indicator_values` into `regions`. Pure normalization says don't. It's there so Q7's `≥50k population` filter doesn't re-join 300k `indicator_values` rows on every request. **Named, justified, controlled denormalization** for a hot path — exactly the kind of trade-off a DB course wants to see you reason about out loud, not hide.

---

## 4. Database trade-offs — what was chosen over what, and why

The full decision table. Memorize the "Because" column.

| Chose | Over | Because |
| --- | --- | --- |
| **PostgreSQL + PostGIS** | MongoDB / MySQL / SQLite | Only PostGIS gives mature, indexed `ST_Contains` / KNN / polygon storage out of the box. MySQL spatial is weaker; SQLite/SpatiaLite is single-file and lacks the concurrency + planner maturity; a document store would mean reimplementing spatial indexing by hand. |
| **One DB, normalized by grain** | One DB per source / one giant flat table | A single join across accidents × regions × population is the project's core; flat tables duplicate population into millions of rows; separate DBs need `postgres_fdw` for nothing. |
| **`indicator_values` long/tidy table** | One column per indicator (wide) | Adding an indicator = new row, **zero schema change**. Wide tables need a migration per indicator. |
| **Hand-written parameterized SQL** (`text()`) | SQLAlchemy ORM queries | Spatial predicates (`ST_Contains`, `<->`, `ST_Transform`) and dynamic optional filters are clearer and `EXPLAIN ANALYZE`-inspectable as raw SQL than as ORM-generated SQL. |
| **Precomputed `accident_zones`** | Live per-request aggregation | 2.1M-row live spatial aggregation is too slow for interactive panning; precompute → KNN lookups become index-driven and instant. |
| **Two stored geometry columns** | Reproject on every read | `ST_Transform` per request wastes CPU; store both once at ETL time. |
| **`ags TEXT`** | `ags INTEGER` | Leading zeros are meaningful; int casting silently corrupts joins. |
| **Partial index on `category = 1`** | Full index on `(region_id, year)` for fatals | Fatal is ~2.5% of rows; partial index is far smaller and faster for the fatal-ranking query. |
| **Plain SQL files in `db/init/`** | Alembic migrations | Schema is created once per fresh Docker volume; a migration framework is lifecycle overhead this project doesn't need. |
| **CSV snapshot of Regionalstatistik** | Live GENESIS API | Removes an auth/rate-limit/uptime dependency from a **live oral-exam demo**; snapshot date recorded + exposed via metadata. Still an official source, so the "≥3 sources" rubric holds. |
| **SHA-1 surrogate key for 2016–2017** | Dropping years with no native stable ID | Keeps full 2016–2024 range while preserving idempotent re-runs. |

### 4.1 The "why not NoSQL?" answer, expanded

A document store (Mongo) would let you dump each dataset as-is, but:
- **No spatial join.** You'd hand-roll point-in-polygon and nearest-neighbour, without a GiST index.
- **No relational integrity.** `region_id` foreign keys, the `regions_history` remapping, and the `(indicator_id, region_id, year)` composite key all express constraints Mongo can't enforce.
- **The core deliverable is a *join* across grains** — per-capita rates. Relational is the natural home for that; document stores fight it.

The honest one-liner: *"The project is fundamentally about joining heterogeneous data on shared keys and doing spatial math on it. That's the exact workload relational + PostGIS was built for."*

---

## 5. Why this stack is the best fit (layer by layer)

| Layer | Choice | Why it's right *for this project* |
| --- | --- | --- |
| **DB** | PostgreSQL 16 + PostGIS 3.4 | The only free, mature, standards-based option that does indexed spatial joins **and** relational integrity in one engine. Version-pinned in Docker for reproducibility. |
| **ETL** | Python + pandas + Shapely/pyproj | pandas handles the messy German CSVs (latin-1, comma decimals, per-year column renames); Shapely/pyproj do geometry + reprojection; all idempotent via `ON CONFLICT`. |
| **API** | FastAPI + SQLAlchemy (`text()`) + psycopg3 | **Free OpenAPI/Swagger docs from type hints** — a rubric deliverable — with minimal boilerplate. SQLAlchemy gives connection pooling + per-request sessions; raw SQL keeps queries inspectable. |
| **Frontend** | Vanilla JS + Leaflet + deck.gl + Chart.js | **No build step** — an examiner can open `app.js` and read it; nothing minified or compiled in between. Leaflet = base map, deck.gl = GPU density, Chart.js = panels. |
| **Infra** | Docker Compose, 2 containers | Reproducible from a clean machine with two commands; not a microservice zoo. |

**The through-line:** every choice optimizes for two things a DBW project is actually graded on — **reproducibility** (anyone can rebuild it) and **inspectability** (an examiner can read and trust every layer). Fashionable choices (a React SPA, an ORM abstraction, a microservice split) would trade *away* both for benefits this project doesn't need.

---

## 6. The live demo script (5 minutes, the 7 mandatory questions)

Have the map open at `http://localhost:8000` and a terminal ready with curl. Answer each mandatory question **twice** — once by clicking the map/preset, once by curl — so the examiner sees the frontend and the API agree, and the metadata block proves the source.

| # | Question | Endpoint / curl |
| --- | --- | --- |
| 1 | Earliest accident year in the dataset? | `/aggregates/accidents?aggregate=earliest_year` |
| 2 | Personal-injury accidents in Saxony 2023? | `/aggregates/accidents?state=SN&year=2023&category=2` |
| 3 | Earliest year for North Rhine-Westphalia? | `/aggregates/accidents?state=NW&aggregate=earliest_year` |
| 4 | Earliest year for Mecklenburg-Western Pomerania? | `/aggregates/accidents?state=MV&aggregate=earliest_year` |
| 5 | Pedestrian accidents in Berlin 2023? | `/accidents?state=BE&year=2023&participant=pedestrian&limit=100` |
| 6 | **Cross-dataset:** accidents per 100k cars in a region? | `/aggregates/accident-rate?denominator=cars_pkw&year=2023&level=district` |
| 7 | Top 5 districts by fatal-accident rate per 100k inhabitants, 2024, ≥50k pop? | `/aggregates/accident-rate/top?level=district&year=2024&severity=fatal&denominator=population&limit=5&min_population=50000` |

Then the **bonus feature** — the hotspot layer:

```bash
curl "http://localhost:8000/zones/nearest?lat=52.52&lon=13.405&limit=5"   # nearest official hotspots to a clicked point
```

**Demo narration beats:**
- Q1/Q3/Q4 are the same endpoint with a `state` filter — "one query shape, filtered." Shows the `(year)` and `(region_id, year)` indexes at work.
- Q5 shows the **participant filter** — set up the SQL-injection answer here (§7): it's a column name from a closed allowlist.
- Q6 is the **cross-dataset join** — accidents (fact) × indicator_values (fact) × regions (dimension). This is *the* question the whole normalized-by-grain design exists to answer. Point at it explicitly.
- Q7 shows the **partial index**, the **population fallback** (`MAX(year) ≤ requested`), and the **≥50k denormalized filter** all at once.
- Every JSON response carries a `metadata` block (`sources_used`, `licenses`, `snapshot_date`) — open one and show it: "every answer is self-documenting about where it came from."
- Zoom the map out→in to show the **three-layer rendering strategy** (choropleth → hex → points) without ever downloading 2.1M points.

---

## 7. The big-question bank — every likely question and the decision that answers it

Grouped by theme. For each: the question, the answer, and **which design decision pre-answers it** (so you can point at something concrete, not hand-wave).

### Architecture & scope

**"Why does the diagram look like many databases?"**
It's one PostgreSQL database, one PostGIS extension, nine tables split by grain (crash vs. region vs. indicator-value vs. computed zone), not by source. The point is that one query joins across all of them. → *§3.1*

**"Why not microservices?"**
One-person, 10-day project. Two containers is enough to be reproducible; microservices add failure surface that buys nothing at this scale. → *§2.3*

**"How would you add a new data source / endpoint / map layer?"**
At exactly one layer, thanks to the one-way contracts: new source → a file under `etl/` + a `sources` seed row; new endpoint → `api/routes/` + register in `main.py`; new layer → `frontend/app.js`. → *§2.2*

### Database design

**"Why PostgreSQL/PostGIS over NoSQL or plain relational?"**
Three inherently spatial operations — point-in-polygon attribution, nearest-hotspot, polygon rendering — need indexed spatial support. PostGIS gives `ST_Contains`, the `<->` KNN operator, and GiST indexes out of the box; Mongo/MySQL/SQLite would mean reimplementing or scanning. → *§3.3, §4.1*

**"Fact table vs. dimension table here?"**
Facts: `accidents`, `indicator_values` (high-volume events/measurements). Dimensions: `regions`, `indicators`, `lookup_codes`, `sources`. `accident_zones` is derived, not sourced. → *§3.2*

**"Why is `ags` TEXT, never integer?"**
Leading zeros are meaningful (`"01001"` ≠ `1001`); int-casting silently breaks joins. Enforced with `dtype=str` end-to-end. → *§3.5*

**"Why two geometry columns on `accident_zones`?"**
`cell_geom_proj` (25832, metric) makes KNN distance meaningful in real metres; `cell_geom` (4326) is what the frontend expects. Both computed once at ETL, not per-read. → *§3.4*

**"Why a 250 m grid built in EPSG:25832 rather than lat/lon?"**
250 only means 250 metres in a metric SRID; in 4326 it would mean 250 degrees, and even a converted value gives non-square cells at German latitudes. 250 m also matches Unfallatlas point precision — coarse enough to reveal clustering, fine enough not to merge distinct hotspots. → *§3.4*

**"Why the partial index?"**
Fatal accidents are ~2.5% of rows; the Q7 fatal-ranking query only ever touches them, so `WHERE category = 1` indexes far fewer rows. You index for a query shape, not a column. → *§3.6*

**"Isn't `population_latest` a denormalization?"**
Yes — deliberate and controlled. It avoids re-joining 300k rows on every Q7 request. Named trade-off, not an accident. → *§3.7*

**"ORM or raw SQL?"**
Raw parameterized SQL via SQLAlchemy `text()`, on a pooled per-request session. The queries are spatial with dynamic optional filters — raw SQL expresses that more directly and stays `EXPLAIN ANALYZE`-inspectable. → *§4, §5*

**"SQL-injection risk?"**
The only place a *column name* (not a value) is interpolated is the participant filter, resolved through a closed hard-coded dictionary (`_PARTICIPANT_COL`) guarded by an assertion — only six known literals can ever reach the SQL. Everything else is a bound parameter. → *§6 (Q5 beat)*

### ETL & data quality

**"How do you know the ETL is idempotent (a requirement)?"**
Every insert is `ON CONFLICT DO NOTHING`/`DO UPDATE` on a stable key. 2018+ rows use Destatis's `UIDENTSTLAE`; 2016–2017 rows (no native ID) get a deterministic SHA-1 surrogate over stable fields — same file in, same hash out, no duplicates on re-run. → *§4 table*

**"How did the point coordinates become usable geometry?"**
`XGCSWGS84`/`YGCSWGS84` use a **comma** decimal separator (German CSV convention); parsed to floats, then written into a `POINT(4326)` in the *same* INSERT as the raw lat/lon, so geometry and raw columns can never drift. → *README §Part 2.4*

**"What happens when a district code can't be resolved?"**
Counted, not dropped. If >5% of a year's rows fail to resolve, the ETL raises and stops — loud failure over silent corruption. → *README §Part 2.4 step 7*

**"How are Kreisreform boundary changes handled?"**
`regions_history` maps retired AGS codes to their canonical 2024 equivalent; every accident's raw code is resolved through both `regions` and `regions_history` before storage, so old accidents attribute to today's boundaries. → *§3.1 table*

**"Why a CSV snapshot instead of the live GENESIS API?"**
Removes an auth/rate-limit/uptime dependency from a live demo; snapshot date recorded and exposed via `/metadata/sources`. Still an official source. → *§4 table, §5*

### Frontend & rendering

**"With 2.1M points, how do you avoid rendering everything?"**
Zoom-dependent strategy: choropleth counts when zoomed out, deck.gl GPU-aggregated hex bins at medium zoom, individual canvas markers only at street level — each layer fetching only its current viewport bbox, capped by a zoom-dependent point limit. → *README §Part 2.5, §6 demo*

**"Why deck.gl on top of Leaflet, not just Leaflet markers?"**
Leaflet markers don't scale past a few thousand points and don't express density via extrusion. deck.gl's `HexagonLayer` is GPU-accelerated and aggregates on the fly; Leaflet stays the base map + point/choropleth layer. → *README §Part 2.5*

**"The live hex layer and the hotspot layer look redundant — why both?"**
The hex layer is live, client-side, re-aggregated every pan — a "density right now" aid. The hotspot layer comes from the precomputed `accident_zones` table built with an explicit, defensible rule (≥5 accidents / 250 m / 3 yr = *Unfallhäufungsstelle*) — the authoritative answer, served via a KNN index instead of a live 2.1M-row scan. → *§3.4, §6*

### Reproducibility & operations

**"Reproduce this on a clean machine?"**
`docker compose up -d --build` creates the containers and applies the schema to a fresh volume; `python -m etl.update` downloads, hashes, and loads every source in one command. That exact path is exercised before submission. → *§1, README §Part 1*

**"How do you know if an import failed or went stale?"**
`import_runs` logs every ETL run — status, row counts, file hash, error message — surfaced without DB access via `GET /import-runs` and `GET /healthz/data-quality`. → *§3.1 table*

---

## 8. Anticipated hard follow-ups (the ones that trip people up)

- **"Is `accident_zones` ever stale?"** Yes — it's a **snapshot**. Recompute with `python -m etl.update --source zones` after loading new accident years, or the hotspot layer serves stale data. Say this proactively; hiding it looks worse than owning it.
- **"Your participant flag maps blank → FALSE, not NULL."** True and known. "Unknown" and "confirmed not involved" aren't currently distinguishable; a `WHERE participant_pedestrian IS NULL` query won't find those rows. It's a documented rough edge, not a silent bug.
- **"Hamburg/Berlin sub-districts?"** Resolved via a structural prefix rule (`02xxx→02000`, `11xxx→11000`) instead of listing each code; a genuinely new prefix outside those two would need a manual `regions_history` row.
- **"Why not Alembic / migrations?"** The schema is applied once per fresh Docker volume; there's no production DB to evolve in place. Migrations would be overhead for a lifecycle that only ever does `down -v && up`.
- **"p95 latency claim?"** `EXPLAIN ANALYZE` on the Q7 path shows index scans, p95 < 200 ms cold cache — the partial index and the `(region_id, year)` composite are why.

---

## 9. One-page cheat sheet (glance before you walk in)

- **What:** 4 German open datasets → 1 PostGIS DB → 1 FastAPI → 1 map. Reproducible in 2 commands.
- **DB thesis:** one database, **9 tables split by grain not source**, so one join computes per-capita rates.
- **PostGIS thesis:** 3 inherently spatial ops (point-in-polygon, KNN, polygon render) → indexed, not app-code scans.
- **Rate query (Q6/Q7) is the whole point** — accidents × indicator_values × regions.
- **`ags` is TEXT** (leading zeros). **`indicator_values` is long/tidy** (add indicators free). **Partial index** on fatals. **Two geometries** (25832 metric for KNN, 4326 for frontend).
- **Raw parameterized SQL**, injection-safe (participant = closed allowlist).
- **Idempotent ETL** (`ON CONFLICT` on `UIDENTSTLAE` / SHA-1 surrogate). **Loud failure** at >5% unresolved.
- **2.1M points never all rendered** — choropleth → hex → points by zoom, viewport-bounded.
- **Metadata block** on every response = source + license, self-documenting.
- **Own the rough edges:** zones are a snapshot; participant blank→FALSE; local-only demo by design.

---

## 10. Per-slide question map (deck-keyed)

The defense deck (`deck/GeoCrash DE Defense Deck.html`) is 14 slides. For each, the questions most likely to land *on that slide*, and where §7 answers them. When an examiner interrupts, you know which slide invited it and which answer to give.

| # | Slide | Questions it invites | Answer ref |
| --- | --- | --- | --- |
| 01 | Title | "What is this / what was your role?" | §0 pitch |
| 02 | Agenda | — (roadmap only) | — |
| 03 | Motivation & Task | "Why fuse into one system — why not query each dataset separately?" · "What does *reproducible from scratch* mean?" | §0, §3.1, §1 |
| 04 | Project Goals | "Which are the rubric goals?" · "Reproducible how, exactly?" | §1, §5 (Infra), §7 Reproducibility |
| 05 | Data Sources | "Why 4 sources when 3 are required?" · "Why a CSV snapshot instead of the live GENESIS API?" · "What's the join key across all four?" · "Licensing?" | §4 table, §5, §3.5 (AGS join key) |
| 06 | Design Decisions | "Why PostGIS over NoSQL?" · "ORM or raw SQL?" · "Why vanilla JS, no framework?" · "Why precompute zones?" | §3.3, §4, §4.1, §5 |
| 07 | Database Design | "Isn't this many databases?" · "Fact vs. dimension?" · "Why `ags` TEXT?" · "What is *grain*?" · "Why does `indicator_values` hold both population and cars?" | §3.1, §3.2, §3.5 |
| 08 | System Architecture | "Why not microservices?" · "What are the one-way contracts?" · "How would you add a new source / endpoint / layer?" | §2.2, §2.3 |
| 09 | API Design | "Any SQL-injection risk?" · "Why the metadata/provenance block on every response?" · "Why 5 routers?" · "Where do the Swagger docs come from?" | §7 (injection), §3.1 (metadata), §5 (FastAPI) |
| 10 | Mandatory Questions | "Walk Q1→Q7." · "Why is Q7 fast (fatal ranking)?" · "How does the population denominator handle missing years?" · "What makes Q6/Q7 *cross-dataset*?" | §3.6 (partial index), §3.7 (denorm + `MAX year ≤`), §6 |
| 11 | Bonus — Zero-Accident Municipalities | "Why `NOT IN` / anti-join instead of counting?" · "`ST_Within(a.geom, r.geom)` vs `ST_Contains(r.geom, a.geom)` — same thing?" · "Why does this prove the *region catalog* is complete?" | §3.1 (regions = full catalog), §3.3 (point-in-polygon) |
| 12 | Student Q — Nearby Hazards | "How is *within 500 m* computed?" · "Why EPSG:25832 for the radius/KNN?" · "Isn't scanning 2.1M points slow?" · "How does geolocation feed the query?" | §3.4 (metric SRID, KNN `<->`), §6 (`/zones/nearest`) |
| 13 | Challenges | "AGS leading-zero problem?" · "How are Kreisreform boundary changes handled?" · "How do you render 2.1M points?" | §3.5, §3.1 (`regions_history`), §8, README §Part 2.5 |
| 14 | Live Demo | "Show it." · "What if the network drops mid-demo?" | §6 (demo script), §8 (local-only, backup video) |

**Two slide-specific answers not already in §7:**

- **Slide 11, `ST_Within` vs `ST_Contains`:** they're inverses of the same test — `ST_Within(a.geom, r.geom)` ≡ `ST_Contains(r.geom, a.geom)` (is the accident point inside the region polygon). The bonus query uses `ST_Within` because the accident is the subject being tested. Same GiST-indexed spatial predicate either way. The *point* of the slide is the **anti-join**: the answer is the *absence* of rows, so it only works because `regions` is a complete catalog independent of `accidents`.
- **Slide 12, "why not just scan 2.1M points for within-500 m?":** a raw radius scan is a full table scan. Instead it's a KNN `<->` lookup on a GiST index in EPSG:25832, so "nearest hotspots" and "count within 500 m" are index-driven and return in metres, not a sequential 2.1M-row distance computation.

---

*Companion docs: `README.md` (orientation + run), `PLAN.md` (full original design rationale), `Challenges.md` (line-anchored review findings — verify against current code), `deck/` (the 14-slide defense deck this map is keyed to).*
