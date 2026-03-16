# ClawHub Tracker Website — Design Spec

## Overview

A static website generated from DuckDB analytics data, providing historical trend visibility into the ClawHub skill marketplace. ClawHub.ai shows what exists now; this site shows what's moving and how things evolve over time.

**Primary audience**: AI agents (JSON API) and developers browsing trending skills (HTML).

## Architecture

**Approach**: Python Static Site Generator (SSG)

The scraper runs daily, populates DuckDB. A new generation step reads DuckDB, computes aggregated metrics, and outputs static HTML + JSON files to a `build/` directory. No runtime server required.

**Stack**:
- Jinja2 for HTML templates
- Chart.js via CDN for client-side charts
- Single `style.css`, dark theme
- No JS framework (vanilla HTML + Chart.js)
- Deploy to any static host (Azure Static Web Apps free tier, GitHub Pages, etc.)

**Data pipeline**:
```
Scraper (daily 03:00) → DuckDB → site_data.py (queries) → site_html.py (Jinja2) → build/
```

## Pages

### 1. Dashboard (`/index.html`)

Platform health at a glance.

**KPI cards** (4 cards, each with sparkline + % change):
- Total downloads (with WoW %)
- New skills per week (with WoW %)
- Total unique owners — `COUNT(DISTINCT owner_handle)` from current run (with MoM %)
- Median DL/day for skills created in the last 30 days — compared to the median of skills created in the 30 days before that (MoM %)

**Growth timeline table**: Weekly rows showing new skills count, cumulative total, WoW %, and horizontal bar.

**JSON**: `/api/dashboard.json`

### 2. Rising Skills (`/rising.html`)

Skills gaining momentum right now.

- Top 50 skills ranked by download velocity (DL/day)
- Mini velocity chart per skill (last 10 scrape runs, configurable via `VELOCITY_CHART_RUNS = 10`)
- Delta since last run (e.g., "+1,200")
- Age indicator (e.g., "created 3 days ago")
- Client-side filter: last 7d / 14d / 30d

**JSON**: `/api/rising.json`

### 3. Leaderboard (`/leaderboard.html`)

Two views toggled client-side:

- **All Time**: Top 100 by total downloads
- **Fastest Growing**: Top 100 by acceleration — defined as `(velocity_recent - velocity_prior) / velocity_prior * 100` where `velocity_recent` is avg DL/day over the last 3 runs and `velocity_prior` is avg DL/day over the 3 runs before that. Minimum 50 total downloads to qualify.

Each row shows: skill name, owner, download count, velocity, trend arrow. Trend thresholds: up = velocity increased >5% vs prior period, down = decreased >5%, flat = within +/-5%.

**JSON**: `/api/leaderboard.json` (contains both lists)

### 4. Cohorts (`/cohorts.html`)

Are newer skills performing better or worse than older ones?

**Percentile table**: One row per monthly cohort. Columns: cohort month, skill count, P25, P50 (median), P75, P90, P99, average — all in DL/day (normalized for age).

**Box plot chart** (Chart.js): Visual distribution of DL/day per cohort. Whiskers at P10/P90, box at P25-P75, median line, P99 outlier dots.

**Star-to-download ratio** per cohort: computed as `SUM(stat_stars) / NULLIF(SUM(stat_downloads), 0)` across all skills in the cohort (aggregate ratio, not per-skill average, to avoid small-skill noise).

**JSON**: `/api/cohorts.json`

### 5. Skill Detail (`/skills/{slug}.html`)

Pre-generated for top ~200 skills (by downloads or velocity).

- Download count line chart over time (across scrape runs)
- Stars line chart over time
- Version releases marked on timeline — detected by comparing `version_number` across consecutive scrape runs; when it changes, record `{version_number, run_date, changelog}` as a release event
- Current velocity (DL/day) and acceleration (same formula as leaderboard)
- Owner info with link to owner page
- Summary and tags

**JSON**: `/api/skills/{slug}.json`

### 6. Owners (`/owners/{handle}.html`)

Pre-generated for top ~50 owners (by total downloads).

- Total downloads across all skills
- Number of skills and average quality (DL/day)
- Combined download trajectory chart
- List of their skills with individual stats

**JSON**: `/api/owners/{handle}.json`

### API Discovery

`/api/index.json` — catalog for agent discovery. Example structure:

```json
{
  "generated_at": "2026-03-16T03:15:00Z",
  "endpoints": {
    "dashboard": {"url": "/api/dashboard.json", "description": "Platform health metrics and sparklines"},
    "rising": {"url": "/api/rising.json", "description": "Top 50 skills by download velocity"},
    "leaderboard": {"url": "/api/leaderboard.json", "description": "Top 100 by downloads and acceleration"},
    "cohorts": {"url": "/api/cohorts.json", "description": "Monthly cohort percentile analysis"}
  },
  "skills": {"count": 200, "url_pattern": "/api/skills/{slug}.json"},
  "owners": {"count": 50, "url_pattern": "/api/owners/{handle}.json"}
}
```

## Data Strategy

### Pre-computed (served as static JSON, ~1-2 MB total)

- Dashboard KPIs with sparkline data points (last 12 weeks)
- Rising skills top 50 with velocity arrays (last N runs per skill)
- Leaderboard top 100 in two views
- Cohort percentiles per month
- ~200 individual skill history arrays
- ~50 owner profiles with aggregated stats

### Not served (stays in DuckDB)

- Full history of 10K+ skills
- Raw snapshots from every scrape run
- Skills below top 200 threshold
- Owners below top 50 threshold
- Ad-hoc analytics (CLI report unchanged)

### Thresholds

- **Skill detail pages**: generated for skills in the top 200 by total downloads OR top 50 by current DL/day velocity
- **Owner pages**: generated for owners in the top 50 by total downloads across their portfolio
- These thresholds are configurable constants in `site_data.py`
- Skills with `slug IS NULL` are skipped (no detail page generated)
- Owner handles are sanitized for URL/filesystem safety: lowercased, non-alphanumeric characters (except `-` and `_`) replaced with `-`

## File Structure

### New files

```
app/site.py              — orchestrator: reads DuckDB, calls data + html builders, writes build/
app/site_data.py         — SQL queries returning dicts for each page
app/site_html.py         — Jinja2 template rendering (render_page functions per template)
app/templates/
  base.html              — shared layout (nav, head, Chart.js CDN, footer)
  dashboard.html         — dashboard page template
  rising.html            — rising skills template
  leaderboard.html       — leaderboard template
  cohorts.html           — cohort analysis template
  skill_detail.html      — individual skill page template
  owner_detail.html      — individual owner page template
app/static/
  style.css              — dark theme styles
tests/unit/
  test_site_data.py      — unit tests for all query functions
```

### Generated output (gitignored)

```
build/
  index.html
  rising.html
  leaderboard.html
  cohorts.html
  skills/{slug}.html     (top ~200)
  owners/{handle}.html   (top ~50)
  api/
    index.json
    dashboard.json
    rising.json
    leaderboard.json
    cohorts.json
    skills/{slug}.json
    owners/{handle}.json
  static/
    style.css
```

## Query Functions (`site_data.py`)

Each function takes a DuckDB connection and returns a dict ready for JSON serialization and template rendering.

### `dashboard_data(conn) → dict`
- Total skills, downloads, stars, owners (current run)
- Weekly new skill counts for last 12 weeks with WoW %
- Total downloads per scrape run (for sparkline)
- Median DL/day for skills created in the last 30 days

### `rising_data(conn, limit=50, max_age_days=30) → dict`
- Skills created within `max_age_days`, ranked by DL/day
- For each skill: velocity array across last 10 runs (for mini chart), delta since previous run
- Includes skill metadata: name, slug, owner, created_at, summary

### `leaderboard_data(conn, limit=100) → dict`
- `all_time`: top skills by total downloads with current velocity
- `fastest_growing`: top skills by DL/day acceleration (comparing recent vs prior velocity)

### `cohorts_data(conn) → dict`
- Monthly cohorts with: skill count, P25/P50/P75/P90/P99 of DL/day, average DL/day
- Star-to-download ratio per cohort
- All metrics normalized by age using `stat_downloads / GREATEST(DATE_DIFF('day', created_at, now), 1)`

### `skill_detail_data(conn, slug) → dict`
- Full history: list of `{run_date, downloads, stars, installs_all_time, installs_current}` across all scrape runs
- Version releases: detected by `version_number` changes across consecutive runs, returns `{version_number, run_date, changelog}`
- Current metrics: velocity (DL/day), acceleration (same formula as leaderboard)
- Owner info

### `owner_detail_data(conn, handle) → dict`
- All skills by this owner with current stats
- Combined download trajectory across runs
- Portfolio summary: total downloads, skill count, avg DL/day

### `api_index(conn) → dict`
- Lists all generated endpoints with URLs and descriptions
- Counts of available skill/owner detail pages

### `top_skills_for_detail(conn, limit=200) → list[str]`
- Returns slugs of skills that qualify for detail page generation
- Selection: top 200 by downloads UNION top 50 by DL/day velocity

### `top_owners_for_detail(conn, limit=50) → list[str]`
- Returns handles of owners that qualify for detail page generation
- Selection: top 50 by total downloads across their portfolio

## HTML Templates

### `base.html`
- Dark theme, Catppuccin Mocha color palette
- Navigation bar: Dashboard | Rising | Leaderboard | Cohorts
- Chart.js loaded via CDN
- Footer with "Last updated: {timestamp}" and link to JSON API
- Responsive: works on mobile (single column) and desktop

### Chart specifications
- **Sparklines** (dashboard KPIs): Line chart, no axes, no legend, just the curve. ~50px tall.
- **Velocity mini charts** (rising page): Tiny line chart per skill row. ~30px tall, inline.
- **Box plots** (cohorts): One box per monthly cohort. Uses `@sgratzl/chartjs-chart-boxplot` plugin via CDN alongside Chart.js.
- **Line charts** (skill detail): Full-width, download + stars as two datasets, version releases as vertical markers.

## CSS Theme

Dark theme using Catppuccin Mocha palette:
- Background: `#1e1e2e` (base), `#181825` (mantle)
- Surface: `#313244`
- Text: `#cdd6f4` (primary), `#a6adc8` (secondary), `#585b70` (muted)
- Accent colors: `#89b4fa` (blue), `#a6e3a1` (green), `#f9e2af` (yellow), `#fab387` (peach), `#f38ba8` (red), `#cba6f7` (mauve)

## Pipeline Integration

### Post-scraper step

After the scraper completes, the site generator runs:

```bash
python -m app.site
```

This wipes the `build/` directory and regenerates all files from scratch. Full rebuild ensures stale pages (skills that dropped out of the top 200) are removed.

### Crontab update

```
0 3 * * * python -m app.scraper
15 3 * * * python -m app.site
```

### Docker integration

Add to `docker-compose.yml` as a post-scraper step or a separate service triggered after scraper completion.

### Earthfile

New target `+site` that runs the generator and produces the `build/` directory as an artifact.

## Dependencies

New Python dependencies:
- `jinja2` — template rendering

No other new dependencies. Chart.js is loaded via CDN (no build step).

## Testing

Unit tests in `tests/unit/test_site_data.py`:
- Each query function tested with in-memory DuckDB (same pattern as existing `test_report.py`)
- Test cases for: empty database, single run, multiple runs, edge cases (skills with 0 downloads, cohorts with 1 skill)
- Verify JSON output structure matches what templates expect
- Verify percentile calculations are correct
- Verify threshold functions return correct slugs/handles

Integration test (optional): generate full `build/` directory from a seeded DuckDB and verify all files exist and are valid HTML/JSON.

## Edge Cases

### Insufficient data

When fewer than 2 completed scrape runs exist:
- **Velocity, deltas, acceleration**: show "N/A" in the UI, `null` in JSON
- **WoW %**: show "—" (no comparison possible)
- **Sparklines**: hidden (nothing to chart)
- **Rising skills page**: shows message "Needs at least 2 scrape runs to compute velocity"

The generator never crashes on insufficient data — it degrades gracefully, matching the existing `report.py` pattern of returning `None` for optional sections.

### Empty database

If no completed runs exist, `app/site.py` logs a warning and exits without generating the `build/` directory.

## Out of Scope

- User authentication
- Search functionality (agents use the catalog, developers browse pages)
- Real-time updates (data refreshes daily)
- Skills below top 200 threshold (no detail page)
- Custom date range queries (static data only)
- MCP server (can be added later wrapping the JSON API)
