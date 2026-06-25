"""
Phase 6 ETL: precompute accident_zones (hotspot + safe) for 2022–2024.

Grid: 250 m × 250 m squares in EPSG:25832 (UTM 32N).
Hotspot: ≥5 accidents in cell, 2022–2024.
Safe:    0 accidents in cell, centroid in district with population > 0,
         cell is an immediate neighbour (8-connected, ±250 m) of a hotspot.
         Neighbour constraint keeps the stored set bounded and ensures safe
         zones are returned near dangerous areas in /zones/around.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from etl.common import finish_import_run, start_import_run

YEAR_FROM = 2016
YEAR_TO = 2024
HOTSPOT_MIN = 5
CELL = 250  # metres, EPSG:25832

_TRUNCATE = text("TRUNCATE TABLE accident_zones")

_HOTSPOT_SQL = text("""
INSERT INTO accident_zones
    (kind, accident_count, year_from, year_to, region_id,
     cell_geom_proj, cell_geom, import_run_id)
WITH acc_cells AS (
    SELECT
        (floor(ST_X(ST_Transform(geom, 25832)) / :cell)::bigint * :cell)::float8 AS cx,
        (floor(ST_Y(ST_Transform(geom, 25832)) / :cell)::bigint * :cell)::float8 AS cy
    FROM accidents
    WHERE year BETWEEN :yr_from AND :yr_to AND geom IS NOT NULL
),
cell_counts AS (
    SELECT cx, cy, COUNT(*)::int AS cnt
    FROM acc_cells
    GROUP BY cx, cy
    HAVING COUNT(*) >= :min_acc
),
cells AS (
    SELECT cx, cy, cnt,
           ST_MakeEnvelope(cx, cy, cx + :cell, cy + :cell, 25832) AS cell_geom_proj
    FROM cell_counts
)
SELECT
    'hotspot',
    c.cnt,
    CAST(:yr_from AS smallint),
    CAST(:yr_to AS smallint),
    r.ags,
    c.cell_geom_proj,
    ST_Transform(c.cell_geom_proj, 4326),
    :run_id
FROM cells c
JOIN regions r ON
    r.level = 'district'
    AND ST_Contains(r.geom,
        ST_Transform(ST_PointOnSurface(c.cell_geom_proj), 4326))
""")

_SAFE_SQL = text("""
INSERT INTO accident_zones
    (kind, accident_count, year_from, year_to, region_id,
     cell_geom_proj, cell_geom, import_run_id)
WITH hotspot_origins AS (
    SELECT
        ST_XMin(cell_geom_proj)::float8 AS cx,
        ST_YMin(cell_geom_proj)::float8 AS cy
    FROM accident_zones
    WHERE kind = 'hotspot' AND year_from = :yr_from AND year_to = :yr_to
),
offsets(dx, dy) AS (
    VALUES (-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)
),
neighbour_cells AS (
    SELECT DISTINCT
        (h.cx + o.dx * :cell)::float8 AS cx,
        (h.cy + o.dy * :cell)::float8 AS cy
    FROM hotspot_origins h CROSS JOIN offsets o
),
acc_cells AS (
    SELECT DISTINCT
        (floor(ST_X(ST_Transform(geom, 25832)) / :cell)::bigint * :cell)::float8 AS cx,
        (floor(ST_Y(ST_Transform(geom, 25832)) / :cell)::bigint * :cell)::float8 AS cy
    FROM accidents
    WHERE year BETWEEN :yr_from AND :yr_to AND geom IS NOT NULL
),
safe_candidates AS (
    SELECT
        n.cx, n.cy,
        ST_MakeEnvelope(n.cx, n.cy, n.cx + :cell, n.cy + :cell, 25832) AS cell_geom_proj
    FROM neighbour_cells n
    LEFT JOIN acc_cells a ON a.cx = n.cx AND a.cy = n.cy
    WHERE a.cx IS NULL
),
populated_districts AS (
    SELECT DISTINCT r.ags, r.geom
    FROM regions r
    JOIN indicator_values iv ON iv.region_id = r.ags
    JOIN indicators i ON i.id = iv.indicator_id AND i.name = 'population'
    WHERE r.level = 'district' AND iv.value > 0
)
SELECT
    'safe',
    0::int,
    CAST(:yr_from AS smallint),
    CAST(:yr_to AS smallint),
    pd.ags,
    sc.cell_geom_proj,
    ST_Transform(sc.cell_geom_proj, 4326),
    :run_id
FROM safe_candidates sc
JOIN populated_districts pd ON
    ST_Contains(pd.geom,
        ST_Transform(ST_PointOnSurface(sc.cell_geom_proj), 4326))
""")

_COUNT_SQL = text("SELECT kind, COUNT(*) FROM accident_zones GROUP BY kind")

_PARAMS = {
    "cell": CELL,
    "yr_from": YEAR_FROM,
    "yr_to": YEAR_TO,
    "min_acc": HOTSPOT_MIN,
}


def run_zones_etl(db: Session) -> dict:
    """Recompute all accident_zones from scratch."""
    run_id = start_import_run(db, "unfallatlas", "derived:accident_zones")
    total_ins = 0
    try:
        db.execute(_TRUNCATE)
        db.commit()

        print("[zones] Computing hotspots...")
        db.execute(_HOTSPOT_SQL, {**_PARAMS, "run_id": run_id})
        db.commit()

        print("[zones] Computing safe zones (neighbours of hotspots)...")
        db.execute(_SAFE_SQL, {**_PARAMS, "run_id": run_id})
        db.commit()

        counts = {row[0]: row[1] for row in db.execute(_COUNT_SQL).fetchall()}
        total_ins = sum(counts.values())
        print(f"[zones] Done: {counts.get('hotspot', 0)} hotspots, "
              f"{counts.get('safe', 0)} safe zones")

    except Exception as exc:
        finish_import_run(db, run_id, status="failed",
                          rows_inserted=total_ins, rows_updated=0,
                          error_message=str(exc))
        raise

    finish_import_run(db, run_id, status="success",
                      rows_inserted=total_ins, rows_updated=0)
    return {"hotspots": counts.get("hotspot", 0), "safe": counts.get("safe", 0)}
