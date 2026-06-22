-- Seed lookup_codes: human-readable labels for coded columns in accidents table
-- Source: Unfallatlas data dictionary (DSB_Unfallatlas_EN.pdf)

-- ─── Accident category (UKATEGORIE) ───────────────────────────────────────────
INSERT INTO lookup_codes (category, code, label_de, label_en) VALUES
('accident_category', '1', 'Unfall mit Getöteten',         'Fatal accident'),
('accident_category', '2', 'Unfall mit Schwerverletzten',  'Serious injury accident'),
('accident_category', '3', 'Unfall mit Leichtverletzten',  'Light injury accident')
ON CONFLICT (category, code) DO UPDATE SET
    label_de = EXCLUDED.label_de,
    label_en = EXCLUDED.label_en;

-- ─── Day of week (UWOCHENTAG) — Destatis encoding: 1=Sunday, 7=Saturday ───────
INSERT INTO lookup_codes (category, code, label_de, label_en) VALUES
('day_of_week', '1', 'Sonntag',    'Sunday'),
('day_of_week', '2', 'Montag',     'Monday'),
('day_of_week', '3', 'Dienstag',   'Tuesday'),
('day_of_week', '4', 'Mittwoch',   'Wednesday'),
('day_of_week', '5', 'Donnerstag', 'Thursday'),
('day_of_week', '6', 'Freitag',    'Friday'),
('day_of_week', '7', 'Samstag',    'Saturday')
ON CONFLICT (category, code) DO UPDATE SET
    label_de = EXCLUDED.label_de,
    label_en = EXCLUDED.label_en;

-- ─── Light conditions (ULICHTVERH / LICHT pre-2020) ──────────────────────────
INSERT INTO lookup_codes (category, code, label_de, label_en) VALUES
('light_condition', '0', 'Tageslicht',                'Daylight'),
('light_condition', '1', 'Dämmerung',                 'Twilight'),
('light_condition', '2', 'Dunkelheit',                'Darkness')
ON CONFLICT (category, code) DO UPDATE SET
    label_de = EXCLUDED.label_de,
    label_en = EXCLUDED.label_en;

-- ─── Road surface condition (STRZUSTAND, available from 2020) ────────────────
INSERT INTO lookup_codes (category, code, label_de, label_en) VALUES
('road_condition', '0', 'trocken',    'dry'),
('road_condition', '1', 'nass/feucht', 'wet/moist'),
('road_condition', '2', 'winterglatt', 'winter slippery')
ON CONFLICT (category, code) DO UPDATE SET
    label_de = EXCLUDED.label_de,
    label_en = EXCLUDED.label_en;

-- ─── Accident type (UART) ─────────────────────────────────────────────────────
INSERT INTO lookup_codes (category, code, label_de, label_en) VALUES
('accident_type', '1', 'Fahrunfall',                        'Single vehicle accident'),
('accident_type', '2', 'Abbiegeunfall',                     'Turning accident'),
('accident_type', '3', 'Einbiegen/Kreuzen-Unfall',          'Merging/crossing accident'),
('accident_type', '4', 'Überschreiten-Unfall',              'Pedestrian crossing accident'),
('accident_type', '5', 'Unfall durch ruhenden Verkehr',     'Stationary traffic accident'),
('accident_type', '6', 'Unfall im Längsverkehr',            'Longitudinal traffic accident'),
('accident_type', '7', 'sonstiger Unfall',                  'Other accident')
ON CONFLICT (category, code) DO UPDATE SET
    label_de = EXCLUDED.label_de,
    label_en = EXCLUDED.label_en;
