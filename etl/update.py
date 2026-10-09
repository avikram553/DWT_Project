"""
Mandatory ETL orchestrator.

Usage:
    python -m etl.update
    python -m etl.update --source regionalatlas
    python -m etl.update --source unfallatlas --year 2024
    python -m etl.update --dry-run
"""
import argparse

from api.db import SessionLocal


def main():
    parser = argparse.ArgumentParser(description="DBW ETL update orchestrator")
    parser.add_argument(
        "--source",
        choices=["unfallatlas", "regionalatlas", "regionalstatistik", "gvisys", "zones"],
    )
    parser.add_argument("--year", type=int, help="Process a single year (unfallatlas only)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.dry_run:
        print("[dry-run] Would run ETL for:", args.source or "all sources")
        return

    db = SessionLocal()
    try:
        # Phase 2: administrative regions (prerequisite for all other ETLs)
        if args.source is None or args.source == "regionalatlas":
            from etl.regions import run_regions_etl
            print("[update] Running regions ETL...")
            result = run_regions_etl(db)
            print(f"[update] Regions done: {result}")
            from etl.frontend_snapshots import write_region_snapshots
            write_region_snapshots(db)

        # Phase 3: accident data (2016-2024)
        if args.source is None or args.source == "unfallatlas":
            from etl.unfallatlas import run_accidents_etl
            print("[update] Running accidents ETL...")
            result = run_accidents_etl(db, specific_year=args.year)
            print(f"[update] Accidents done: {result}")
            from etl.frontend_snapshots import write_year_summary
            write_year_summary(db)

        # Phase 4: population and PKW indicators
        if args.source is None or args.source == "regionalstatistik":
            from etl.indicators import run_indicators_etl
            print("[update] Running indicators ETL...")
            result = run_indicators_etl(db)
            print(f"[update] Indicators done: {result}")

        # Phase 6: hotspot + safe zone precomputation (requires phases 3+4)
        if args.source is None or args.source == "zones":
            from etl.zones import run_zones_etl
            print("[update] Computing accident zones...")
            result = run_zones_etl(db)
            print(f"[update] Zones done: {result}")

    finally:
        db.close()


if __name__ == "__main__":
    main()
