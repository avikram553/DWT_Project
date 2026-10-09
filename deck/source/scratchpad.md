# GeoCrash DE — Defense Deck Outline

**Style:** clean light academic. Serif titles (Spectral), Plex Sans body, Plex Mono for code/labels. Red accent (#ce3b33) + warm neutrals. 1920×1080. 10-min oral defense.

Title style: short topic noun-phrases (textbook chapter style).

## Title sequence (read top-to-bottom = the story)
1. GeoCrash DE — title / front page
2. Agenda
3. Motivation & Task
4. Project Goals
5. Data Sources
6. Design Decisions
7. Database Design
8. System Architecture
9. API Design
10. Mandatory Questions
11. Bonus Question — Zero-Accident Municipalities
12. Student Question — Nearby Hazards
13. Challenges
14. Live Demo

## Content notes
- Author: Aditya Vikram · 910541 · Datenbanken und Web-Techniken · TU Chemnitz
- 4 sources (≥3 required): Unfallatlas, Regionalatlas/VG250, Regionalstatistik, AGS history
- DB: one PostgreSQL+PostGIS, 9 tables split by grain (fact/dimension/computed/bookkeeping)
- Arch: Open data → ETL → PostGIS → FastAPI → Frontend (Leaflet+deck.gl+Chart.js)
- Mandatory: 5 single-source + 2 cross-dataset (rate) questions
- Bonus: zero-accident municipalities (absence of rows = the answer)
- Student: "accidents within 500m of me" + Nearby Hazards hotspots via geolocation/KNN
- Challenges highlighted: AGS leading-zero/Kreisreform · rendering 3M points via zoom layers
- Demo: cue slide + checklist, switch to localhost:8000
- Images: styled placeholders labelled for map + Swagger
