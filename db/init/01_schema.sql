-- Phase 1: Schema — all 9 tables + indexes
-- AGS is always TEXT — never cast to integer (leading-zero bug: "01001" != 1001)

CREATE EXTENSION IF NOT EXISTS postgis;

-- ─── 1. sources ────────────────────────────────────────────────────────────────
CREATE TABLE sources (
    id           SERIAL PRIMARY KEY,
    name         TEXT NOT NULL UNIQUE,
    url          TEXT,
    license      TEXT NOT NULL,
    description  TEXT,
    last_checked DATE
);

-- ─── 2. import_runs ────────────────────────────────────────────────────────────
CREATE TABLE import_runs (
    id                BIGSERIAL PRIMARY KEY,
    source_id         INTEGER REFERENCES sources(id),
    started_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at       TIMESTAMPTZ,
    status            TEXT NOT NULL DEFAULT 'running', -- 'running'|'success'|'failed'
    file_url          TEXT,
    file_hash_sha256  TEXT,
    rows_inserted     INTEGER,
    rows_updated      INTEGER,
    rows_skipped      INTEGER,
    error_message     TEXT,
    source_timestamp  DATE
);

-- ─── 3. regions ────────────────────────────────────────────────────────────────
CREATE TYPE region_level AS ENUM ('state', 'district', 'municipality');

CREATE TABLE regions (
    ags               TEXT PRIMARY KEY,        -- string, NEVER integer (leading-zero)
    name              TEXT NOT NULL,
    level             region_level NOT NULL,
    parent_ags        TEXT REFERENCES regions(ags),
    population_latest BIGINT,                  -- denormalised from indicator_values for Q7 ≥50k filter
    geom              GEOMETRY(MULTIPOLYGON, 4326),
    import_run_id     BIGINT REFERENCES import_runs(id)
);

-- ─── 4. lookup_codes ───────────────────────────────────────────────────────────
CREATE TABLE lookup_codes (
    id         SERIAL PRIMARY KEY,
    category   TEXT NOT NULL,
    code       TEXT NOT NULL,
    label_de   TEXT,
    label_en   TEXT,
    UNIQUE(category, code)
);

-- ─── 5. accidents ──────────────────────────────────────────────────────────────
CREATE TABLE accidents (
    id                      BIGSERIAL PRIMARY KEY,
    accident_uid            TEXT NOT NULL UNIQUE,   -- UIDENTSTLAE for 2018+; 'sha1:...' surrogate for 2016-2017
    year                    SMALLINT NOT NULL,
    month                   SMALLINT,
    hour                    SMALLINT,
    day_of_week             SMALLINT,               -- 1=Sunday … 7=Saturday (Destatis encoding)
    category                SMALLINT,               -- 1=fatal, 2=serious injury, 3=light injury
    kind                    SMALLINT,
    type                    SMALLINT,
    light                   SMALLINT,
    road_condition          SMALLINT,
    participant_car         BOOLEAN,
    participant_bike        BOOLEAN,
    participant_moped       BOOLEAN,
    participant_truck       BOOLEAN,
    participant_pedestrian  BOOLEAN,
    participant_other       BOOLEAN,
    lat                     DOUBLE PRECISION,
    lon                     DOUBLE PRECISION,
    geom                    GEOMETRY(POINT, 4326),
    region_id               TEXT REFERENCES regions(ags),  -- canonical 2024 AGS via regions_history
    import_run_id           BIGINT REFERENCES import_runs(id)
);

-- ─── 6. indicators ─────────────────────────────────────────────────────────────
CREATE TABLE indicators (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    unit        TEXT,
    description TEXT,
    source_id   INTEGER REFERENCES sources(id)
);

-- ─── 7. indicator_values ───────────────────────────────────────────────────────
CREATE TABLE indicator_values (
    indicator_id  INTEGER REFERENCES indicators(id),
    region_id     TEXT REFERENCES regions(ags),
    year          SMALLINT NOT NULL,
    value         INTEGER NOT NULL,               -- population fits in int32; vehicle counts too
    import_run_id BIGINT REFERENCES import_runs(id),
    PRIMARY KEY (indicator_id, region_id, year)
);

-- ─── 8. accident_zones ─────────────────────────────────────────────────────────
-- 250m × 250m grid cells in EPSG:25832 (metric SRID for Germany)
-- cell_geom_proj: storage + KNN distance (must be metric for distance to be meaningful)
-- cell_geom: WGS84 for API/frontend output
CREATE TABLE accident_zones (
    id              BIGSERIAL PRIMARY KEY,
    kind            TEXT NOT NULL CHECK (kind IN ('hotspot', 'safe')),
    accident_count  INTEGER NOT NULL DEFAULT 0,
    year_from       SMALLINT NOT NULL,
    year_to         SMALLINT NOT NULL,
    region_id       TEXT REFERENCES regions(ags),
    cell_geom_proj  GEOMETRY(POLYGON, 25832) NOT NULL,   -- EPSG:25832 metric, indexed for KNN
    cell_geom       GEOMETRY(POLYGON, 4326) NOT NULL,    -- WGS84 for API responses
    import_run_id   BIGINT REFERENCES import_runs(id)
);

-- ─── 9. regions_history ────────────────────────────────────────────────────────
-- AGS reorganisation lookup: maps old district codes to canonical 2024 AGS
-- Seeded in 05_seed_ags_history.sql; ETL upserts more at runtime
CREATE TABLE regions_history (
    id          SERIAL PRIMARY KEY,
    old_ags     TEXT NOT NULL,
    new_ags     TEXT NOT NULL REFERENCES regions(ags),
    change_date DATE,
    change_type TEXT,                -- e.g. 'merger', 'split', 'rename', 'renumber'
    source_note TEXT,
    UNIQUE (old_ags, new_ags)
);

-- ═══════════════════════════════════════════════════════════════════════════════
-- INDEXES
-- ═══════════════════════════════════════════════════════════════════════════════

-- accidents: Q1, Q3, Q4 (MIN(year))
CREATE INDEX idx_accidents_year ON accidents(year);

-- accidents: Q2, Q5, Q6, Q7 and every aggregate endpoint
CREATE INDEX idx_accidents_region_year ON accidents(region_id, year);

-- accidents: Q2 severity filter
CREATE INDEX idx_accidents_year_category ON accidents(year, category);

-- accidents: Q7 fatal-only ranking (~2.5% of rows)
CREATE INDEX idx_accidents_fatal_partial ON accidents(region_id, year) WHERE category = 1;

-- accidents: hotspot point-in-cell, frontend bbox queries
CREATE INDEX idx_accidents_geom ON accidents USING GIST(geom);

-- regions: /regions?level=district listing
CREATE INDEX idx_regions_level_parent ON regions(level, parent_ags);

-- regions: map rendering, ST_Contains
CREATE INDEX idx_regions_geom ON regions USING GIST(geom);

-- accident_zones: KNN <-> for /zones/around (metric SRID required for meaningful distance)
CREATE INDEX idx_zones_geom_proj ON accident_zones USING GIST(cell_geom_proj);
CREATE INDEX idx_zones_geom ON accident_zones USING GIST(cell_geom);

-- indicator_values: population fallback CTE (MAX year ≤ requested_year)
CREATE INDEX idx_indicator_values_lookup ON indicator_values(indicator_id, region_id, year DESC);

-- regions_history: ETL lookups by old_ags to resolve canonical 2024 AGS
CREATE INDEX idx_regions_history_old_ags ON regions_history(old_ags);
