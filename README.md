# GeoCrash DE: Spatial Analysis of Traffic Accidents in Germany

TU Chemnitz · Datenbanken und Web-Techniken · Submission: 25.06.2026

## Quick Start

```bash
# 1. Copy env template (no changes needed for local dev)
cp .env.example .env

# 2. Start database + API
docker compose up -d

# 3. Wait for DB readiness
docker compose exec db pg_isready -U postgres -t 60

# 4. Verify API is up
curl http://localhost:8000/healthz

# 5. Load all data (downloads ~500 MB)
python -m etl.update

# 6. Open API docs
open http://localhost:8000/docs
```

## Services

| Service | URL |
|---------|-----|
| REST API + Swagger UI | http://localhost:8000/docs |
| Health check | http://localhost:8000/healthz |
| PostgreSQL | localhost:5432 (user: postgres, db: dwt) |

## Data Sources

| Source | Content | License |
|--------|---------|---------|
| Unfallatlas | ~3M accident records 2016–2024 | dl-de/by-2-0 |
| Regionalatlas | Region polygons (states, districts) | dl-de/by-2-0 |
| Regionalstatistik | Population + registered cars | dl-de/by-2-0 |
| GV-ISys / AGS | Region reference codes | dl-de/by-2-0 |

## Update Script

```bash
# Full refresh from scratch
python -m etl.update

# Single source
python -m etl.update --source unfallatlas

# Single year
python -m etl.update --source unfallatlas --year 2024

# Dry run
python -m etl.update --dry-run
```

## Verify PostGIS

```bash
docker compose exec db psql -U postgres -c "SELECT PostGIS_Version();"
```
