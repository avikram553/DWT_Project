-- Seed indicator catalog
-- Regionalstatistik table codes confirmed: 12411-01-01-4 (population), 46251-01-01-4 (PKW)

INSERT INTO indicators (name, unit, description, source_id) VALUES
(
    'population',
    'persons',
    'Bevölkerung — resident population per region per year. Source: Regionalstatistik table 12411-01-01-4.',
    (SELECT id FROM sources WHERE name = 'regionalstatistik')
),
(
    'cars_pkw',
    'vehicles',
    'PKW-Bestand — registered passenger cars (Pkw) per region per year. Source: Regionalstatistik table 46251-01-01-4.',
    (SELECT id FROM sources WHERE name = 'regionalstatistik')
)
ON CONFLICT (name) DO UPDATE SET
    unit        = EXCLUDED.unit,
    description = EXCLUDED.description,
    source_id   = EXCLUDED.source_id;
