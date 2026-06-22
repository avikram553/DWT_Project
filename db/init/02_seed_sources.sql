-- Seed the 4 official German open-data sources used by this project
-- License: dl-de/by-2-0 (Datenlizenz Deutschland – Namensnennung – Version 2.0)

INSERT INTO sources (name, url, license, description, last_checked) VALUES
(
    'unfallatlas',
    'https://www.opengeodata.nrw.de/produkte/transport_verkehr/unfallatlas/',
    'dl-de/by-2-0',
    'Unfallatlas — Straßenverkehrsunfälle in Deutschland 2016–2024. CSV format, latin-1 encoding, semicolon-separated. ~3M rows.',
    '2026-06-15'
),
(
    'regionalatlas',
    'https://regionalatlas.statistikportal.de/',
    'dl-de/by-2-0',
    'Regionalatlas Deutschland — administrative region polygons (states, districts, municipalities) as GeoJSON. Coordinates in WGS84.',
    '2026-06-15'
),
(
    'regionalstatistik',
    'https://www.regionalstatistik.de/genesis/online',
    'dl-de/by-2-0',
    'Regionalstatistik / GENESIS — population (table 12411-01-01-4) and registered PKW (table 46251-01-01-4) per region and year. CSV download path used (no auth required).',
    '2026-06-15'
),
(
    'gvisys',
    'https://www.destatis.de/DE/Themen/Laender-Regionen/Regionales/Gemeindeverzeichnis/_inhalt.html',
    'dl-de/by-2-0',
    'GV-ISys / AGS Gemeindeverzeichnis (Destatis) — official 8-digit AGS region reference codes. Used to resolve leading-zero-safe region identifiers.',
    '2026-06-15'
)
ON CONFLICT (name) DO UPDATE SET
    url          = EXCLUDED.url,
    license      = EXCLUDED.license,
    description  = EXCLUDED.description,
    last_checked = EXCLUDED.last_checked;
