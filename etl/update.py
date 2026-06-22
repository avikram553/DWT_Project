"""
Mandatory ETL orchestrator.

Usage:
    python -m etl.update
    python -m etl.update --source unfallatlas
    python -m etl.update --source unfallatlas --year 2024
    python -m etl.update --dry-run
"""
import argparse


def main():
    parser = argparse.ArgumentParser(description="DBW ETL update orchestrator")
    parser.add_argument("--source", choices=["unfallatlas", "regionalatlas", "regionalstatistik", "gvisys"])
    parser.add_argument("--year", type=int)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.dry_run:
        print("[dry-run] Would run ETL for:", args.source or "all sources", "year:", args.year or "all")
        return

    # TODO Phase 8: implement full orchestration
    print("ETL update not yet implemented — see Phase 8")


if __name__ == "__main__":
    main()
