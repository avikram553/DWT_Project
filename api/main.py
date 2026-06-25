from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.routes import regions, accidents, aggregates, zones, metadata

app = FastAPI(
    title="DBW Accident Data API",
    description="Open Data Integration with Accidents in Germany — TU Chemnitz DBW Project",
    version="0.1.0",
    license_info={"name": "dl-de/by-2-0", "url": "https://www.govdata.de/dl-de/by-2-0"},
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000",
                   "http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(regions.router)
app.include_router(accidents.router)
app.include_router(aggregates.router)
app.include_router(zones.router)
app.include_router(metadata.router)
