# PLAN.md: Brainstorm / Discovery Notes
Date: 2026-06-18 · Goal: Pressure-test every decision in PLAN.md before Phase 0 begins (7 days to deadline)

## Context
- Project: DBW Final Project — "Open Data Integration with Accidents in Germany" (TU Chemnitz)
- Submission deadline: **2026-06-25 23:59** (7 days from today)
- Oral exam window: 2026-07-02 – 2026-07-16
- Existing PLAN.md is 385 lines and already very detailed
- Raw accident data already downloaded under `rawData/Accidents/`
- Stack pre-selected: Python + FastAPI + Postgres+PostGIS + Vanilla JS + Leaflet + Docker Compose
- User's goal: grade 1 + resume-grade artefact

## Summary / key decisions
(updated as we go)

- **Year scope: 2016–2024** (full, 9 years, ~3M rows). Maximalist.
- **Indicators path: Regionalstatistik CSV** (no API auth, offline-safe, demo-reliable).
- **Solo submission confirmed.** Single matriculation-numbered ZIP, no shared code.
- **Hotspot/safe-zone feature: KEPT.** Phase 6 stays. Grid-cell precompute, KNN query, Leaflet map, geolocation.
- **Hotspot rule: 250m × 250m grid, ≥5 accidents in 2022–2024 = hotspot; 0 accidents in 2022–2024 AND centroid in region with population>0 = safe zone; otherwise unclassified.** Justification: matches German *Unfallhäufungsstellen* norm; 3-year window stays within single Unfallatlas schema generation; population check prevents "forest = safe" false positives.
- **Time budget: Full-time, ~8h/day, ~56h total.** Maximalist plan feasible. No extra buffer for major scope additions.
- **7th examiner question: "Top 5 districts by fatal-accident rate per 100,000 inhabitants in 2024."** Cross-source (accidents + population). Strong map demo. Endpoint: `GET /aggregates/accident-rate/top?level=district&year=2024&participant_or_severity=fatal&denominator=population&limit=5`.
- **AGS strategy: 2024 canonical + historical mapping table.** Pre-reorg AGS values mapped to current AGS via `regions_history` lookup table seeded from Destatis Gebietsstandstabelle. All joins use canonical 2024 AGS. Document mapping completeness as a known limitation.
- **Submission packaging: bundle frontend deps locally** (Leaflet + Chart.js in `frontend/vendor/`). Inner ZIP target ~1.2 MiB (well under 10 MiB cap). Demo works offline. Explicit-list `zip` command with cleanup pre-step.
- **Min-population filter for Q7 top-rate ranking: ≥50k inhabitants** (Destatis "Großstädte und Kreise" cutoff). Hard floor in default query, surfaced in response metadata.

## Q&A log

### Q1 — Year scope (PLAN §15)
- Asked: 2020-2024 vs 2016-2024 vs 2018-2024
- Captured: **2016–2024 full range**. User explicitly chose maximalist. Resume-grade priority over schedule safety.
- Implications:
  - ~3M-row Unfallatlas import (vs 1.5M for compact)
  - **Per-year column mappers required** for legacy years (LICHT→ULICHTVERH rename ~2020; STRZUSTAND only present 2020+; UIDENTSTLAE only present 2018+, OBJECTID before)
  - "Earliest year overall" answer = 2016
  - "Earliest year per state" varies because regional rollout was staggered — must verify and document in `LIMITATIONS.md`
- Flags:
  - Per-year column mapper file not in §8 folder layout — propose `etl/mappers/unfallatlas_columns.py` with year-range branches
  - 2018 size dip (already in §12 risk row 7) — must add per-state-per-year row count assertion to plausibility checks (§11)
  - Year-by-year idempotent loading explicitly required: `etl.update --source unfallatlas --year YYYY` must work in isolation

### Q2 — Indicators data path (PLAN §15)
- Asked: Regionalstatistik CSV vs GENESIS REST API vs hybrid
- Captured: **Regionalstatistik CSV** (download once, no auth)
- Rationale: aligns with "no abusing external services" PDF rule, demo-day reliable, no token dependency
- Implications:
  - Term paper §6 (update workflow) describes manual CSV refresh, not API polling
  - Resume narrative becomes "I integrated 4 file/CSV-based sources" (Unfallatlas CSV, Regionalatlas GeoJSON, Regionalstatistik CSV, GV-ISys CSV/XLSX) — still 4 distinct formats which is strong
  - File caching strategy: store downloaded CSVs in `rawData/Indicators/` with date-stamped filenames; ETL reads from disk, never from URL at request time
  - Indicators needed: population (for accident rate per 100k inhabitants) + registered passenger cars / Bestand an Kraftfahrzeugen (for Q6 cross-source)
- Flags:
  - Specific Regionalstatistik table codes not yet pinned: 12411-01-01-4 (population by district), 46251-01-01-4 (vehicles by district)? Need to confirm exact codes during Phase 4
  - Indicator coverage may differ from accident year coverage (some indicators only available 2018+); document gaps in LIMITATIONS.md

### Q3 — Solo work confirmation (PLAN §15)
- Asked: solo or with classmates
- Captured: **Solo, all own code**. PDF §6 mandate honoured.
- Implications:
  - Single matriculation-number ZIP submission
  - Citing public libraries (FastAPI, pandas, geopandas, leaflet, etc.) in term paper is required and fine
  - AI-assisted code (Claude, Copilot) is the user's own code if reviewed and integrated personally — but the term paper should still cite tools transparently in "tools used" section
- Flags: none

### Q4 — Hotspot/safe-zone feature (PLAN §5, §7 Phase 6)
- Asked: keep / cut / half-keep
- Captured: **Keep — full Phase 6 as planned**. Grid-cell precompute approach.
- Rationale: resume differentiator + strong live-demo moment (geolocation + map + dynamic zones)
- Implications:
  - `accident_zones` table stays in §4 schema
  - Precompute step in ETL update workflow (`etl/zones.py`)
  - Frontend (Phase 7) needs Leaflet marker rendering + browser geolocation prompt
  - Term paper §3 (schema) must explain why `accident_zones` is a derived/materialised table, not a base table
  - `/zones/nearest` and `/zones/around` endpoints must appear in OpenAPI export
- Flags / under-specified items now requiring resolution:
  - **Hotspot threshold not yet pinned**: PLAN says "compute totals, rates and regional summaries" but doesn't define what makes a cell a hotspot. Need to commit to: grid resolution (e.g. 250m × 250m), threshold count (e.g. ≥5 accidents in N years), time window (e.g. last 3 years vs. all years), severity weighting (count fatalities heavier?)
  - **"Safe zone" definition**: opposite of hotspot? Cells with zero accidents? Both polygons covering all of Germany or only inhabited areas? Risk of false-positive "safe" labels in uninhabited rural areas
  - **KNN index choice**: PostGIS `GIST` on `geometry` is standard but spatial KNN with `<->` requires careful index tuning. Should confirm `accident_zones` has the right index in `db/init/01_schema.sql`
  - **Demo-day fallback**: if browser geolocation fails (HTTPS required for geolocation in modern browsers, but local dev usually runs http://), need a hardcoded "Chemnitz" coordinate fallback button so demo never depends on browser permissions

### Q5 — Hotspot rule definition (resolves Q4 flags)
- Asked: 250m/≥5/3yr vs 1km/≥10/5yr vs severity-weighted
- Captured: **250m grid, ≥5 accidents in 2022–2024 = hotspot, 0 accidents in 2022–2024 AND population>0 region = safe zone, else unclassified.**
- Defence-ready justification (use verbatim in term paper §7 / oral exam):
  > "250m chosen because Unfallatlas point precision is ~10–50m; the cell aggregates without losing meaningful spatial signal. Threshold ≥5 in 3 years follows the German road-safety norm of *Unfallhäufungsstellen* (5 accidents same type within 1–3 years). 3-year window not 5-year because Unfallatlas categorical encodings shift around 2018→2020; staying inside one schema generation avoids comparing different definitions."
- Implications for code:
  - `etl/zones.py` uses PostGIS `ST_SquareGrid(0.0023, ...)` (~250m at DE latitudes) for cell generation
  - Cell generation runs only over bounding box of inhabited regions (population>0 join with regions table) — saves compute, prevents forest=safe false positives
  - `accident_zones` schema needs columns: `cell_id`, `cell_geom (POLYGON)`, `kind ('hotspot'|'safe')`, `accident_count`, `year_window`, `computed_at`
  - GIST index on `cell_geom` for KNN performance
- Implications for term paper:
  - §3 (schema) must justify `accident_zones` as derived/materialised
  - §7 (limitations) must mention: cells exactly at boundary edges may be miscounted; safe-zone classification depends on which year's population data is joined; rural cells with population=0 are deliberately excluded from "safe" set
- Flags resolved by this answer:
  - ✅ hotspot threshold pinned
  - ✅ safe-zone definition pinned
  - ⚠️ KNN index — still to verify in DDL during Phase 1
  - ⚠️ demo-day geolocation HTTPS fallback — explicit "Use Chemnitz coordinates" button required in `frontend/app.js`

### Q6 — Time budget reality check
- Asked: full-time / part-time / limited
- Captured: **Full-time, ~8h/day, ~56h total over 7 days.** No other commitments.
- Implication: maximalist plan stays. PLAN.md §7 phased schedule (12 phases) is feasible at this rate.
- Phase-by-phase rough budget (my estimate, to validate against PLAN.md §7):
  - Phase 0 (Skeleton): 3h
  - Phase 1 (Schema + indexes + seeds): 6h
  - Phase 2 (Regions ETL): 4h
  - Phase 3 (Accidents ETL — biggest, includes column mappers): 12h
  - Phase 4 (Indicators ETL): 4h
  - Phase 5 (Aggregation API + 7 examiner queries): 8h
  - Phase 6 (Hotspots: zones table, ETL step, endpoints): 6h
  - Phase 7 (Frontend + Leaflet + geolocation): 5h
  - Phase 8 (Update script orchestration + dry-run): 2h (mostly already done in Phases 2–4)
  - Phase 9 (OpenAPI export + Swagger UI polish): 1h
  - Phase 10 (Plausibility checks + LIMITATIONS.md): 2h
  - Phase 11 (Term paper, ~5 pages): 6h
  - Phase 12 (Submission ZIP + clean-machine verification): 1h
  - **Total: ~60h.** ~4h slack against 56h budget. Tight but realistic.
- Flags:
  - If Phase 3 slips by >3h, Phase 6 (hotspots) is the cut candidate, NOT term paper or plausibility checks
  - Term paper drafted *during* corresponding phases (already in PLAN §14), not all at end
  - Phase 12 must include a "demo rehearsal on a clean machine" — this is the most-skipped, highest-impact step

### Q7 — 7th examiner question (PLAN §6 row 7)
- Asked: top-5 fatal-rate ranking vs spatial bicycle-near-school vs YoY pedestrian rate
- Captured: **Top 5 districts by fatal-accident-rate per 100k inhabitants 2024**
- Rationale: strong map demo, cross-source (accidents + population indicator), no new data source, hits both rates/rankings rubric category
- Endpoint contract:
  - `GET /aggregates/accident-rate/top?level=district&year=2024&severity=fatal&denominator=population&limit=5`
  - Response: ordered list of 5 districts with `{ags, name, accident_count, population, rate_per_100k}` plus metadata envelope (sources, licenses)
  - Frontend demo: highlight the 5 polygons on Leaflet map with red shading
- Implications:
  - PLAN.md §6 row 7 changes from "TBD" to this specific question
  - "fatal" filter requires the Unfallatlas accident-category column (UKATEGORIE = 1)
  - Population denominator must come from indicator_values for matching year (2024) and matching AGS
  - If 2024 population not yet released by Destatis (often available with 6-month lag), fall back to most recent available year and surface that in metadata
- Flags:
  - 2024 population data availability — check during Phase 4
  - Rate=0 districts (zero fatal accidents) shouldn't appear in "top" — must be excluded by query, not just sorted
  - Tiny districts can artificially top this list (e.g. district of 50,000 with 1 fatal accident = rate of 2.0). Should we add a minimum-population filter (e.g. population ≥ 100k)? Worth raising in oral exam as honest limitation.

### Q8 — AGS reorganization handling (PLAN §12 risk row 1)
- Asked: canonical 2024 AGS + historical mapping table vs as-is + no harmonisation vs document-only
- Captured: **Canonical = 2024 AGS, with historical mapping table** (`regions_history`)
- Rationale: cross-year joins must be safe; "as-is" breaks Q3/Q4 (earliest year per state) silently; document-only fails the rubric's "data harmonisation" criterion
- Implementation:
  - New seed file `db/init/05_seed_ags_history.sql` populates `regions_history(old_ags, new_ags, change_date, change_type, source_note)`
  - ETL `regions.py` and `unfallatlas.py` resolve source AGS → canonical AGS at load time via lookup
  - `accidents.region_id` always points at canonical 2024 region — no per-year region rows
  - Seed must cover at minimum:
    - 2016-11-01: Göttingen + Osterode am Harz merge → 03159 (was 03152, 03156)
    - 2018: Eichsfeld minor adjustments
    - 2021: Berlin Bezirke flagged (only relevant if drilling below district)
  - Source: Destatis Gebietsstandstabelle (Gebietsänderungen)
- Schema impact: adds 9th table `regions_history` to PLAN §4 (was 8 tables)
- Term paper impact:
  - §3 (schema) explains harmonisation strategy with Göttingen as case study
  - §7 (limitations) lists any reorganizations not covered by seed
- Flags:
  - Seed completeness: must verify Destatis source is read end-to-end; missing rows silently produce orphan accidents
  - ETL must FAIL LOUD if a source AGS is neither in `regions` nor `regions_history` (don't silently drop)
  - Add plausibility check: every accident.region_id resolves to a `regions` row

### Q10 — Min-population filter for Q7 ranking
- Asked: ≥50k vs ≥100k vs no filter vs query param
- Captured: **≥50k inhabitants** (hard floor in default query)
- Rationale: matches Destatis "Großstädte und Kreise" reporting cutoff; keeps mid-size rural districts visible; prevents 30k-district-with-1-fatality artifacts
- Implementation:
  - Default query in `api/routes/aggregates.py` adds `WHERE iv.value >= 50000` on the population join
  - Response metadata includes `"min_population_filter": 50000` so examiner sees the threshold
  - Term paper §7 (limitations) explains the choice: ranking interprets only districts with statistically meaningful denominator
- Defence-ready justification (term paper / oral):
  > "Per-capita rate rankings are sensitive to small denominators — a single fatal accident in a district of 30,000 produces a rate that mechanically dominates Berlin's. We adopt the Destatis 'Großstädte und Kreise' threshold of 50,000 inhabitants, matching their published district-level reporting practice."
- Flags resolved: ✅ tiny-district artifact concern from Q7

### Q11 — 2024 population data availability fallback
- Asked: auto-fallback to latest vs hard-fail vs hardcode 2023 vs use projection
- Captured: **Auto-fallback to latest available year**, with `population_year_used` surfaced in response metadata
- Rationale: Destatis publishes Bevölkerungsfortschreibung district-level with 6–9 month lag; demo must never crash; transparency via metadata satisfies the rubric's provenance criterion
- Implementation:
  - `api/routes/aggregates.py` query for accident-rate uses a CTE that picks `MAX(year) <= :requested_year` from `indicator_values WHERE indicator_id = 'population'` per region
  - Response metadata includes:
    - `"requested_year": 2024`
    - `"population_year_used": 2023` (or whatever was actually joined)
    - `"snapshot_date"` already covered by §10 envelope
  - ETL: no special-case logic; Phase 4 just loads whatever years Regionalstatistik publishes
- Plausibility check addition:
  - Phase 10: assert "every state has population data for ≥1 year ≤ each accident year imported" — surfaces gaps before submission
- Term paper §7 (limitations):
  > "Population is published with a multi-month lag; the rate query joins on the most recent available year ≤ the requested accident year, with the actual year reported in response metadata."
- Flags resolved: ✅ 2024 population data availability concern from Q7

### Q9 — Inner ZIP packaging strategy (PLAN §13)
- Asked: CDN frontend vs locally bundled frontend vs hybrid
- Captured: **Bundle Leaflet + Chart.js locally in `frontend/vendor/`** (Strategy B)
- Rationale: demo-day reliability; ZIP still tiny (~1.2 MiB); shows reproducibility-mindedness
- Implementation:
  - Add `frontend/vendor/leaflet/` and `frontend/vendor/chart.js/` (each MIT-licensed)
  - Cite both in term paper bibliography
  - Reference via relative paths in `frontend/index.html`
- Pre-submission checklist (must run before zipping):
  - `find . -name "__pycache__" -type d -exec rm -rf {} +`
  - `find . -name ".DS_Store" -delete`
  - `find . -name "*.pyc" -delete`
  - Use **explicit-list** zip (not `zip -r .`) so junk files can't sneak in
  - Verify size < 2 MiB after zipping
- Strict exclusions from inner ZIP:
  - `rawData/` (PDF explicitly forbids)
  - `.venv/`, `__pycache__/`, `node_modules/`, `.git/`, `*.log`, `.DS_Store`
  - Postgres data volume if bind-mounted in project folder (use named volume to avoid this)
- Outer ZIP `<matriculation>.zip` contains: term paper PDF (A4) + inner ZIP only
- Flags resolved:
  - ✅ 10 MiB cap concern eliminated (target ~1.2 MiB)

## Open flags (pending input)

- ✅ Confirm tech stack — Python+FastAPI+Postgres+PostGIS+Vanilla JS (already accepted earlier)
- ✅ Confirm year scope — 2016–2024 (Q1)
- ✅ Confirm indicator path — Regionalstatistik CSV (Q2)
- ✅ Confirm working alone (Q3)
- ✅ Hotspot/safe-zone scoring method (Q5)
- ✅ 7th examiner question — Top 5 fatal-rate districts 2024 (Q7)
- ✅ AGS reorganization handling — canonical 2024 + history table (Q8)
- ❓ **Minimum-population filter** for top-rate ranking — ✅ resolved (Q10): ≥50k inhabitants, hard floor
- ❓ **2024 population data availability** in Regionalstatistik — ✅ resolved (Q11): auto-fallback to latest available year, surface `population_year_used` in metadata
- ❓ **10 MiB inner-ZIP budget** — frontend assets + OpenAPI export not yet sized; need a guardrail before Phase 12
- ❓ **Per-year column mapper** location — propose `etl/mappers/unfallatlas_columns.py`, needs §8 folder layout update
- ❓ **Indicator table codes** in Regionalstatistik — pin exact codes during Phase 4 (12411-01-01-4 candidate for population, 46251-01-01-4 candidate for vehicles)
- ❓ **KNN index** — verify GIST index on `accident_zones.cell_geom` during Phase 1
- ❓ **Geolocation HTTPS fallback** — "Use Chemnitz" button required in `frontend/app.js`
- ❓ **Term paper "tools used" disclosure** — single sentence for AI-assistance transparency
