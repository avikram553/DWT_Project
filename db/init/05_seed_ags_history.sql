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

-- ─── Hamburg city-state Stadtteile → Hamburg district (02000) ──────────────────
-- The Unfallatlas accident data uses Stadtteil-level AGS codes for Hamburg
-- (02xxx) rather than the city-state code. All map to the single district 02000.
-- Sources: Statistikamt Nord, Hamburg Stadtteil-Verzeichnis.
INSERT INTO regions_history (old_ags, new_ags, change_date, change_type, source_note) VALUES
  ('02101', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02102', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02103', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02104', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02105', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02106', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02107', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02108', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02111', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02112', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02113', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02114', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02115', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02116', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02117', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02118', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02119', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02120', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02201', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02202', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02203', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02204', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02205', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02206', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02207', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02208', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02209', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02210', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02211', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02212', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02213', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02214', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02301', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02302', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02303', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02304', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02305', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02306', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02307', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02308', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02309', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02401', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02402', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02403', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02404', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02405', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02406', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02407', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02408', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02409', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02410', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02411', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02412', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02413', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02501', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02502', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02503', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02504', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02505', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02506', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02507', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02508', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02509', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02510', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02511', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02512', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02513', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02514', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02515', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02516', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02517', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02518', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02601', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02602', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02603', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02604', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02605', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02606', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02607', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02608', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02609', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02610', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02611', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02612', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02613', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02614', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02701', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02702', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02703', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02704', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02705', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02706', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02707', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02708', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02709', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02710', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02711', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02712', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02713', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02714', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02715', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02716', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.'),
  ('02717', '02000', NULL, 'city_state_subcode', 'Hamburg Stadtteil code used in Unfallatlas; maps to Hamburg district 02000.')
ON CONFLICT (old_ags, new_ags) DO NOTHING;

-- Thüringen: Eisenach kreisfreie Stadt (16056) → Wartburgkreis (16063), effective 2021-12-01
-- Accidents 2019–2021 with code 16056 must map to 16063.
-- Source: Destatis Gebietsstandstabelle; Thüringen GVBl. 2021 S. 669.
INSERT INTO regions_history (old_ags, new_ags, change_date, change_type, source_note) VALUES
('16056', '16063', '2021-12-01', 'merger',
 'Kreisfreie Stadt Eisenach (16056) merged into Wartburgkreis (16063) on 2021-12-01. Source: Destatis Gebietsstandstabelle 2021.')
ON CONFLICT (old_ags, new_ags) DO NOTHING;

-- ─── Berlin city-state Bezirke → Berlin district (11000) ───────────────────────
-- The Unfallatlas accident data uses Bezirk-level AGS codes for Berlin (11001–11012).
-- All 12 Bezirke map to the single district code 11000.
-- Source: Amt für Statistik Berlin-Brandenburg.
INSERT INTO regions_history (old_ags, new_ags, change_date, change_type, source_note) VALUES
  ('11001', '11000', NULL, 'city_state_subcode', 'Berlin Bezirk code used in Unfallatlas; maps to Berlin district 11000.'),
  ('11002', '11000', NULL, 'city_state_subcode', 'Berlin Bezirk code used in Unfallatlas; maps to Berlin district 11000.'),
  ('11003', '11000', NULL, 'city_state_subcode', 'Berlin Bezirk code used in Unfallatlas; maps to Berlin district 11000.'),
  ('11004', '11000', NULL, 'city_state_subcode', 'Berlin Bezirk code used in Unfallatlas; maps to Berlin district 11000.'),
  ('11005', '11000', NULL, 'city_state_subcode', 'Berlin Bezirk code used in Unfallatlas; maps to Berlin district 11000.'),
  ('11006', '11000', NULL, 'city_state_subcode', 'Berlin Bezirk code used in Unfallatlas; maps to Berlin district 11000.'),
  ('11007', '11000', NULL, 'city_state_subcode', 'Berlin Bezirk code used in Unfallatlas; maps to Berlin district 11000.'),
  ('11008', '11000', NULL, 'city_state_subcode', 'Berlin Bezirk code used in Unfallatlas; maps to Berlin district 11000.'),
  ('11009', '11000', NULL, 'city_state_subcode', 'Berlin Bezirk code used in Unfallatlas; maps to Berlin district 11000.'),
  ('11010', '11000', NULL, 'city_state_subcode', 'Berlin Bezirk code used in Unfallatlas; maps to Berlin district 11000.'),
  ('11011', '11000', NULL, 'city_state_subcode', 'Berlin Bezirk code used in Unfallatlas; maps to Berlin district 11000.'),
  ('11012', '11000', NULL, 'city_state_subcode', 'Berlin Bezirk code used in Unfallatlas; maps to Berlin district 11000.')
ON CONFLICT (old_ags, new_ags) DO NOTHING;
