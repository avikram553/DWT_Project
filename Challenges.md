 [
    {
      "file": "etl/indicators.py",
      "line": 240,
      "summary": "_get_indicator_id RuntimeError is outside the per-indicator 
  try/except, aborting the entire ETL if one indicator row is missing from the 
  DB",
      "failure_scenario": "If 'population' exists in INDICATOR_SOURCES but not 
  in the DB indicators table (e.g. seed SQL not applied), _get_indicator_id 
  raises RuntimeError. This propagates past the per-indicator try/except (which 
  ends at line 238) to the outer except at line 246, which marks the whole run 
  'failed' and re-raises — meaning 'cars_pkw' is never processed, all indicator 
  data is lost, and the import_run record is marked failed with no per-indicator
  granularity."
    },
    {
      "file": "etl/unfallatlas.py",
      "line": 102,
      "summary": "_flag_series returns False (not None) for NaN cells — missing 
  participant flags stored as FALSE in DB instead of NULL",
      "failure_scenario": "pd.to_numeric(..., errors='coerce') coerces 
  empty/non-numeric cells to NaN; .eq(1) on NaN returns numpy.bool_(False), not 
  None. _py(numpy.bool_(False)) → Python False → SQL FALSE. A row where IstPKW 
  is blank (e.g. encoding artefact or truncated row) is stored as 
  participant_car=FALSE ('definitely not involved') rather than NULL 
  ('unknown'). Queries filtering WHERE participant_car IS NULL to find 
  unclassified accidents will miss these rows."
    },
    {
      "file": "api/routes/accidents.py",
      "line": 46,
      "summary": "Unknown state abbreviation silently drops the filter, 
  returning the full unfiltered dataset instead of a 422 or empty result",
      "failure_scenario": "GET /accidents?state=XY → _STATE_CODE.get('XY') 
  returns None → 'if state_prefix:' is False → no WHERE clause added → query 
  returns all ~3M accidents across Germany. Same silent-ignore applies in all 
  three handlers in aggregates.py via _state_prefix(). A caller that typos a 
  state code gets Germany-wide aggregates with no indication the filter was 
  dropped."
    },
    {
      "file": "etl/indicators.py",
      "line": 80,
      "summary": "Separator auto-detection falls back to '\\t' if no known 
  separator found in first 500 chars, silently producing single-column rows and 
  a misleading parse error",
      "failure_scenario": "for/break with no else; if none of ';', ',' or '\\t' 
  appears in content[:500], sep stays '\\t' (last loop value). All subsequent 
  splitting is tab-separated, producing single-field rows that fail the 
  parts[0].isdigit() guard, resulting in 'No data rows found' ValueError with no
  indication the separator was misdetected."
    },
    {
      "file": "etl/indicators.py",
      "line": 64,
      "summary": "_find_data_start can trigger on a GENESIS metadata row 
  containing the table code (e.g. '12411'), returning the wrong line as data 
  start",
      "failure_scenario": "GENESIS CSV exports include the retrieval table code 
  (e.g. '12411-01-01-4' or just '12411') in metadata rows. If such a row appears
  before the actual data header, first.isdigit() is True and len(first) is 5, 
  exactly matching the AGS criterion. The 'header' is then set to the line above
  it (blank or title), producing garbled column names. Parsing continues 
  without error (subsequent numeric rows also match), silently loading wrong 
  data."
    },
    {
      "file": "etl/indicators.py",
      "line": 110,
      "summary": "DataFrame is constructed with header truncated to the column 
  count of the first data row, silently dropping year columns if the first row 
  is shorter than subsequent rows",
      "failure_scenario": "header_parts[:len(data_lines[0])] anchors column 
  count to the first data row. If GENESIS adds a trailing semicolon to some rows
  but not others (making field counts inconsistent), subsequent rows raise 
  ValueError. If the first row is unusually short (e.g. missing the most recent 
  year column), all rows silently have year columns dropped and the resulting 
  long_df has no recent-year data, with no error raised."
    },
    {
      "file": "api/routes/aggregates.py",
      "line": 90,
      "summary": "group_cols and select_name are assigned but never read — the 
  f-string SQL inlines its own conditionals, making these variables dead code",
      "failure_scenario": "Lines 90-96 assign group_cols and select_name, but 
  the SQL f-strings on lines 101-107 use their own inline if-level expressions. 
  A maintainer who tries to change the GROUP BY or SELECT by editing 
  group_cols/select_name will have no visible effect and no error, causing 
  silent query shape divergence from the edited variables."
    },
    {
      "file": "etl/indicators.py",
      "line": 110,
      "summary": "DataFrame is constructed with header truncated to the column count of the first data row, silently dropping year columns if the first row is shorter than
  subsequent rows",
      "failure_scenario": "header_parts[:len(data_lines[0])] anchors column count to the first data row. If GENESIS adds a trailing semicolon to some rows but not others (making
  field counts inconsistent), subsequent rows raise ValueError. If the first row is unusually short (e.g. missing the most recent year column), all rows silently have year columns
  dropped and the resulting long_df has no recent-year data, with no error raised."
    },
    {
      "file": "api/routes/aggregates.py",
      "line": 90,
      "summary": "group_cols and select_name are assigned but never read — the f-string SQL inlines its own conditionals, making these variables dead code",
      "failure_scenario": "Lines 90-96 assign group_cols and select_name, but the SQL f-strings on lines 101-107 use their own inline if-level expressions. A maintainer who tries to
  change the GROUP BY or SELECT by editing group_cols/select_name will have no visible effect and no error, causing silent query shape divergence from the edited variables."
    },
    {
      "file": "api/routes/accidents.py",
      "line": 11,
      "summary": "_STATE_CODE dict is defined identically in accidents.py and aggregates.py — any correction to one will not propagate to the other",
      "failure_scenario": "Both files define the same 16-entry dict. If a mapping is corrected (e.g. a future reunification changes a prefix), the fix applied to one file leaves the
  other stale. /accidents and /aggregates/accidents then produce different results for the same state= filter, producing inconsistent API behavior across endpoints."
    },
    {
      "file": "api/routes/accidents.py",
      "line": 63,
      "summary": "Participant column name is interpolated directly into f-string SQL rather than parameterised — safe only because _PARTICIPANT_COL is a closed literal dict",
      "failure_scenario": "conditions.append(f'{col} = TRUE') at line 63 injects col verbatim into SQL. Today col can only be one of 6 known column names from _PARTICIPANT_COL. If
  the dict is extended with values derived from configuration or a DB table, or if a code path bypasses the .get() guard, the column name becomes a SQL injection vector. The same
  where string is reused for the COUNT(*) query at line 85, doubling the surface."
    },
    {
      "file": "db/init/05_seed_ags_history.sql",
      "line": 46,
      "summary": "Hamburg Stadtteil (02xxx) and Berlin Bezirk (11xxx) codes are enumerated individually rather than resolved by a prefix rule in _build_ags_map",
      "failure_scenario": "Each known code is a separate INSERT row. A future Unfallatlas release that adds a new Hamburg Stadtteil code (or if any existing code was omitted)
  produces region_id=NULL for those rows with no warning. The 5% threshold may not fire if Hamburg/Berlin combined are <5% of national accidents in that year. The fix belongs in
  _build_ags_map: `if ags[:2] in ('02', '11'): canonical[ags] = ags[:2] + '000'`, which handles all present and future subcodes structurally."
    }
  ]
