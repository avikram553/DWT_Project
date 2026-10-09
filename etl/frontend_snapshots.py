"""Write the static JSON snapshots served from frontend/data/."""
from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

from api.lib.responses import envelope

OUT_DIR = Path(__file__).resolve().parent.parent / "frontend" / "data"

# (level, simplify tolerance in degrees, output file)
SNAPSHOTS = [
    ("state", 0.02, "states_simplified.json"),
    ("district", 0.01, "districts_simplified.json"),
]


def write_region_snapshots(db: Session) -> None:
    for level, tolerance, filename in SNAPSHOTS:
        rows = db.execute(
            text(
                """
                SELECT ags, name, level, parent_ags, population_latest,
                       ST_AsGeoJSON(ST_SimplifyPreserveTopology(geom, :tol))::json AS geom
                FROM regions
                WHERE level = :level
                ORDER BY ags
                """
            ),
            {"level": level, "tol": tolerance},
        ).mappings().all()
        body = envelope(
            [dict(r) for r in rows],
            sources_used=["regionalatlas"],
            extra_meta={
                "include_geom": True,
                "simplify": tolerance,
                "bbox_filtered": False,
                "total_count": len(rows),
            },
        )
        (OUT_DIR / filename).write_text(json.dumps(body, separators=(",", ":")))
        print(f"[snapshots] {filename}: {len(rows)} {level}s")


def write_year_summary(db: Session) -> None:
    rows = db.execute(
        text(
            """
            SELECT year,
                   COUNT(*)                                AS total,
                   COUNT(*) FILTER (WHERE category = 1)    AS fatal,
                   COUNT(*) FILTER (WHERE category = 2)    AS serious,
                   COUNT(*) FILTER (WHERE category = 3)    AS minor
            FROM accidents
            GROUP BY year
            ORDER BY year
            """
        )
    ).mappings().all()
    results = [dict(r) for r in rows]
    body = envelope(
        results,
        sources_used=["unfallatlas"],
        extra_meta={"state": None, "total_count": sum(r["total"] for r in results)},
    )
    (OUT_DIR / "year_summary.json").write_text(json.dumps(body, separators=(",", ":")))
    print(f"[snapshots] year_summary.json: {len(results)} years")


if __name__ == "__main__":
    from api.db import SessionLocal

    with SessionLocal() as session:
        write_region_snapshots(session)
        write_year_summary(session)
