-- Seed known AGS reorganisations (Destatis Gebietsstandstabelle)
-- Maps old district codes to canonical 2024 AGS so accident rows from 2016–2023
-- that reference now-defunct codes can still be joined to current regions.
-- The ETL (etl/regions.py) will upsert additional entries at runtime.
--
-- NOTE: This file seeds only well-known cases for bootstrap / offline testing.
-- The authoritative source is: Destatis Gebietsstandstabelle, available at
-- https://www.destatis.de/DE/Themen/Laender-Regionen/Regionales/Gemeindeverzeichnis/

-- Göttingen district merger (2016): old Osterode am Harz (03156) merged into Göttingen (03159)
INSERT INTO regions_history (old_ags, new_ags, change_date, change_type, source_note) VALUES
('03156', '03159', '2016-11-01', 'merger',
 'Osterode am Harz (03156) merged into Landkreis Göttingen (03159). Source: Destatis Gebietsstandstabelle 2016.')
ON CONFLICT (old_ags, new_ags) DO NOTHING;

-- Mecklenburg-Vorpommern Kreisreform (2011): several old districts → new districts
-- Demmin (13052) → Mecklenburgische Seenplatte (13071)
INSERT INTO regions_history (old_ags, new_ags, change_date, change_type, source_note) VALUES
('13052', '13071', '2011-09-04', 'merger',
 'Landkreis Demmin (13052) merged into Mecklenburgische Seenplatte (13071). Source: Destatis 2011 Kreisreform MV.')
ON CONFLICT (old_ags, new_ags) DO NOTHING;

-- Güstrow (13055) → Landkreis Rostock (13072)
INSERT INTO regions_history (old_ags, new_ags, change_date, change_type, source_note) VALUES
('13055', '13072', '2011-09-04', 'merger',
 'Landkreis Güstrow (13055) merged into Landkreis Rostock (13072). Source: Destatis 2011 Kreisreform MV.')
ON CONFLICT (old_ags, new_ags) DO NOTHING;

-- Sachsen-Anhalt Kreisreform (2007): Saalkreis (15260) → Saalekreis (15088)
INSERT INTO regions_history (old_ags, new_ags, change_date, change_type, source_note) VALUES
('15260', '15088', '2007-07-01', 'merger',
 'Saalkreis (15260) merged into Saalekreis (15088). Source: Destatis Gebietsstandstabelle.')
ON CONFLICT (old_ags, new_ags) DO NOTHING;

-- Thüringen: Stadt Erfurt absorbed Landkreis Erfurt (16051) → Erfurt (16051 stable, boundary change)
-- Placeholder example for a renumbering-type change (no real data moved here)
INSERT INTO regions_history (old_ags, new_ags, change_date, change_type, source_note) VALUES
('16051', '16051', '2018-01-01', 'boundary_change',
 'Placeholder: Erfurt boundary adjustment. Replace with real Destatis entry if affected rows found in ETL.')
ON CONFLICT (old_ags, new_ags) DO NOTHING;
