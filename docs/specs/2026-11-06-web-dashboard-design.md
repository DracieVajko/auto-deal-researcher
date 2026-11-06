# Design: Web Dashboard for Search Results (Sub-project 7)

**Date:** 2026-11-06  
**Source:** `autodeal searcher deepresearch.txt` Goal 4 (UX: "simple web dashboard for viewing search results without heavy frameworks")  
**Status:** Draft — proceeding to implementation per "run until finished" instruction

## Problem

The Auto Deal Searcher generates JSON/Markdown/CSV/XLSX result files in `results/`, but there's no way to browse, compare, or revisit past searches through a UI. Users must open files manually. The deep research goal #4 asks for "a simple web dashboard for viewing search results (without heavy frameworks)."

## Scope

**In scope:**

1. **Web dashboard module** (`src/dashboard/`): A lightweight HTTP server using only Python stdlib (`http.server`) that serves:
   - Dashboard index listing all past search runs (results JSON files) sorted by date
   - Per-run detail page showing deals ranked by score, with price, site, condition, verdict, specs, pros/cons
   - Price alert status display (from price_alerts field if present)
   - Simple filtering/sorting (by price, score, site, condition)
   - No external dependencies beyond stdlib

2. **CLI command** (`ads dashboard` or `ads serve`): Starts the dashboard server on a configurable port (default 8765), opens the browser automatically

3. **Integration**: Works with existing results JSON output — no changes to the search pipeline needed

**Out of scope:**
- Real-time search execution from the dashboard (read-only view of existing results)
- User accounts/authentication (advanced technical users, local use)
- WebSocket/live updates (refresh to reload)
- Editing/deleting results

## Architecture

```
src/dashboard/
├── __init__.py
├── server.py          — HTTP server (http.server.ThreadingHTTPServer)
├── app.py             — Route handlers + HTML templates
└── data.py            — Load and parse results JSON files from results dir
```

CLI:
```
src/cli/app.py         — Add `ads dashboard [--port PORT] [--results-dir DIR]` command
```

## Data flow

1. User runs `ads dashboard`
2. Server scans `results/` directory for `results_*.json` files
3. Index page lists runs: timestamp, prompt, deal count, site count
4. User clicks a run → detail page with deal table (rank, title, price, site, score, verdict, link)
5. Click a deal → expanded details (specs, pros/cons, alternatives, price breakdown)
6. Refresh to reload after new runs

## Data model

Results JSON payload (existing):
```json
{
  "prompt": "...",
  "generated_at": "...",
  "count": N,
  "deals": [{...}],
  "filtered_out": [{...}],
  "price_alerts": [...]
}
```

## Error handling

- Missing results directory: show empty dashboard with message
- Corrupt JSON file: skip that file, log warning, continue
- Port already in use: suggest alternative port, exit gracefully
- No results files: show empty state with "Run a search first" message

## Testing

- Unit tests for data loading (parse results JSON, sort by date, filter)
- Unit tests for HTML rendering (basic structure checks)
- Integration test: start server, fetch index page, verify content
- Full suite must remain green (751 passed, 11 skipped baseline)

## Files to create/modify

**Create:**
- `src/dashboard/__init__.py`
- `src/dashboard/server.py`
- `src/dashboard/app.py`
- `src/dashboard/data.py`
- `tests/test_dashboard.py`

**Modify:**
- `src/cli/app.py` — add `dashboard` command
- `docs/specs/2026-11-06-web-dashboard-design.md` — this file

## Design decisions

- **stdlib-only HTTP server**: No Flask/Django/FastAPI — keeps dependency footprint zero per project constraints
- **Read-only**: Dashboard only reads existing results; no write operations
- **Inline HTML templates**: Simple f-string templates, no Jinja2 dependency
- **Results dir configurable**: Default to `./results` but overridable via CLI flag
- **Port configurable**: Default 8765, overridable via `--port`
