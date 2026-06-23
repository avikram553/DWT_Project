"""
Mandatory ETL orchestrator.

Usage:
    python -m etl.update
    python -m etl.update --source regionalatlas
    python -m etl.update --dry-run
"""
import argparse

from api.db import SessionLocal


def main():
    parser = argparse.ArgumentParser(description="DBW ETL update orchestrator")
    parser.add_argument(
        "--source",
        choices=["unfallatlas", "regionalatlas", "regionalstatistik", "gvisys"],
    )
    parser.add_argument("--year", type=int)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.dry_run:
        print("[dry-run] Would run ETL for:", args.source or "all sources")
        return

    db = SessionLocal()
    try:
        if args.source is None or args.source == "regionalatlas":
            from etl.regions import run_regions_etl
            print("[update] Running regions ETL...")
            result = run_regions_etl(db)
            print(f"[update] Regions done: {result}")

        # Phase 3: unfallatlas ETL goes here
        # Phase 4: regionalstatistik ETL goes here
    finally:
        db.close()


if __name__ == "__main__":
    main()
