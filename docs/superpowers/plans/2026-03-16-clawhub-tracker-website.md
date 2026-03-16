# ClawHub Tracker Website Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python static site generator that reads DuckDB skill data and outputs HTML pages + JSON API files for AI agents and developers to browse trending ClawHub skills with historical evolution data.

**Architecture:** Python SSG pipeline — `site_data.py` queries DuckDB and returns dicts, `site_html.py` renders Jinja2 templates, `site.py` orchestrates both and writes to `build/`. Chart.js via CDN for client-side charts. Catppuccin Mocha dark theme.

**Tech Stack:** Python 3.12+, DuckDB, Jinja2, Chart.js (CDN), `@sgratzl/chartjs-chart-boxplot` (CDN), pytest, ruff

**Spec:** `docs/superpowers/specs/2026-03-16-clawhub-tracker-website-design.md`

---

## File Structure

```
New files:
  app/site.py              — orchestrator: wipes build/, calls data + html, writes output
  app/site_data.py         — SQL queries returning dicts (dashboard, rising, leaderboard, cohorts, skill detail, owner detail, thresholds, api index)
  app/site_html.py         — Jinja2 env setup + render functions per page
  app/templates/base.html  — shared layout (nav, Chart.js CDN, footer)
  app/templates/dashboard.html
  app/templates/rising.html
  app/templates/leaderboard.html
  app/templates/cohorts.html
  app/templates/skill_detail.html
  app/templates/owner_detail.html
  app/static/style.css     — Catppuccin Mocha dark theme
  tests/unit/test_site_data.py — unit tests for all query functions

Modified files:
  pyproject.toml           — add jinja2 dependency
  Earthfile                — add +site target
  docker-compose.yml       — add site generator service
  crontab                  — add site generation after scraper
```

---

## Chunk 1: Foundation + Data Layer (site_data.py)

### Task 1: Add jinja2 dependency

**Files:**
- Modify: `pyproject.toml:6-9`

- [ ] **Step 1: Add jinja2 to dependencies**

In `pyproject.toml`, add `"jinja2>=3.1"` to the `dependencies` list:

```toml
dependencies = [
    "duckdb>=1.2",
    "httpx>=0.28",
    "jinja2>=3.1",
    "loguru>=0.7",
]
```

- [ ] **Step 2: Install the dependency**

Run: `cd /home/pontsoul/code/lab/clawhub-tracker && .venv/bin/uv pip install -e ".[dev]"`
Expected: Successfully installed jinja2

- [ ] **Step 3: Verify import works**

Run: `.venv/bin/python -c "import jinja2; print(jinja2.__version__)"`
Expected: prints version number (3.1.x)

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "Add jinja2 dependency for site generator"
```

---

### Task 2: dashboard_data() — platform KPIs and growth timeline

**Files:**
- Create: `app/site_data.py`
- Create: `tests/unit/test_site_data.py`

- [ ] **Step 1: Write the test file scaffold with helpers**

Create `tests/unit/test_site_data.py`:

```python
"""Unit tests for site data queries."""

from datetime import datetime, timezone

from app.models import SkillSnapshot
from app.storage import complete_run, insert_snapshots, start_run


def _ts(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


def _make(run_id: int, skill_id: str, **kwargs) -> SkillSnapshot:
    defaults = {
        "scrape_run_id": run_id,
        "skill_id": skill_id,
        "slug": f"slug-{skill_id}",
        "display_name": f"Skill {skill_id}",
        "owner_handle": "owner1",
        "stat_downloads": 100,
        "stat_stars": 10,
        "stat_installs_all_time": 50,
        "stat_installs_current": 25,
        "stat_versions": 1,
        "version_number": "1.0.0",
    }
    defaults.update(kwargs)
    return SkillSnapshot(**defaults)


def _seed(db, skills_fn):
    run = start_run(db)
    skills = skills_fn(run.id)
    insert_snapshots(db, skills)
    complete_run(db, run.id, total_skills=len(skills))
    return run.id
```

- [ ] **Step 2: Write failing test for dashboard_data()**

Append to `tests/unit/test_site_data.py`:

```python
from app.site_data import dashboard_data


class TestDashboardData:
    def test_totals(self, db):
        _seed(
            db,
            lambda rid: [
                _make(rid, "a", stat_downloads=5000, stat_stars=50,
                      owner_handle="alice"),
                _make(rid, "b", stat_downloads=3000, stat_stars=30,
                      owner_handle="bob"),
                _make(rid, "c", stat_downloads=200, stat_stars=5,
                      owner_handle="alice"),
            ],
        )
        data = dashboard_data(db)
        assert data["total_skills"] == 3
        assert data["total_downloads"] == 8200
        assert data["total_stars"] == 85
        assert data["total_owners"] == 2

    def test_weekly_growth(self, db):
        _seed(
            db,
            lambda rid: [
                _make(rid, "w1a", created_at=_ts(2026, 1, 6)),
                _make(rid, "w1b", created_at=_ts(2026, 1, 7)),
                _make(rid, "w2a", created_at=_ts(2026, 1, 13)),
            ],
        )
        data = dashboard_data(db)
        weeks = data["weekly_growth"]
        assert len(weeks) >= 2
        # Each week has: week_start, new_count, cumulative, wow_pct
        first = weeks[0]
        assert "week_start" in first
        assert "new_count" in first
        assert "cumulative" in first

    def test_sparkline_downloads(self, db):
        # Two runs to get sparkline data
        run1 = start_run(db)
        insert_snapshots(db, [_make(run1.id, "a", stat_downloads=100)])
        complete_run(db, run1.id, total_skills=1)

        run2 = start_run(db)
        insert_snapshots(db, [_make(run2.id, "a", stat_downloads=300)])
        complete_run(db, run2.id, total_skills=1)

        data = dashboard_data(db)
        sparkline = data["download_sparkline"]
        assert len(sparkline) == 2
        assert sparkline[0] == 100
        assert sparkline[1] == 300

    def test_empty_db(self, db):
        data = dashboard_data(db)
        assert data["total_skills"] == 0
        assert data["total_downloads"] == 0
        assert data["weekly_growth"] == []
        assert data["download_sparkline"] == []

    def test_median_dl_per_day(self, db):
        _seed(
            db,
            lambda rid: [
                # 30 day old skill: 300 DL / 30 days = 10 DL/day
                _make(rid, "a", created_at=_ts(2026, 2, 14),
                      stat_downloads=300),
                # 15 day old skill: 300 DL / 15 days = 20 DL/day
                _make(rid, "b", created_at=_ts(2026, 3, 1),
                      stat_downloads=300),
            ],
        )
        data = dashboard_data(db, now=_ts(2026, 3, 16))
        # Median of [10.0, 20.0] = 15.0
        assert data["median_dl_per_day"] == 15.0
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/test_site_data.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.site_data'`

- [ ] **Step 4: Implement dashboard_data()**

Create `app/site_data.py`:

```python
"""SQL queries that produce dicts for the static site generator."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import duckdb
from loguru import logger

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
VELOCITY_CHART_RUNS = 10
SKILL_DETAIL_LIMIT = 200
SKILL_VELOCITY_LIMIT = 50
OWNER_DETAIL_LIMIT = 50
TREND_THRESHOLD_PCT = 5.0
ACCEL_MIN_DOWNLOADS = 50


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
def dashboard_data(conn: duckdb.DuckDBPyConnection, now: datetime | None = None) -> dict:
    """Platform health KPIs, weekly growth, and sparkline data."""
    now = now or _now()
    logger.info("[SITE_DATA] Computing dashboard data")

    # Check for completed runs
    run_row = conn.execute(
        "SELECT id FROM scrape_runs WHERE status = 'completed' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if run_row is None:
        return {
            "total_skills": 0,
            "total_downloads": 0,
            "total_stars": 0,
            "total_owners": 0,
            "weekly_growth": [],
            "download_sparkline": [],
            "median_dl_per_day": None,
            "median_dl_per_day_prev": None,
            "generated_at": now.isoformat(),
        }

    # Totals from current run
    totals = conn.execute("""
        SELECT
            COUNT(*) as total_skills,
            COALESCE(SUM(stat_downloads), 0) as total_downloads,
            COALESCE(SUM(stat_stars), 0) as total_stars,
            COUNT(DISTINCT owner_handle) as total_owners
        FROM current_skills
    """).fetchone()

    # Weekly growth (last 12 weeks)
    weeks_raw = conn.execute("""
        SELECT
            DATE_TRUNC('week', created_at) as week_start,
            COUNT(*) as new_count
        FROM current_skills
        WHERE created_at IS NOT NULL
        GROUP BY 1
        ORDER BY 1
    """).fetchall()

    weekly_growth = []
    cumulative = 0
    prev_count = None
    for week_start, new_count in weeks_raw:
        cumulative += new_count
        wow_pct = None
        if prev_count is not None and prev_count > 0:
            wow_pct = round((new_count - prev_count) / prev_count * 100, 1)
        weekly_growth.append({
            "week_start": week_start.isoformat() if hasattr(week_start, "isoformat") else str(week_start),
            "new_count": new_count,
            "cumulative": cumulative,
            "wow_pct": wow_pct,
        })
        prev_count = new_count

    # Keep last 12 weeks
    weekly_growth = weekly_growth[-12:]

    # Download sparkline: total downloads per completed run
    sparkline_rows = conn.execute("""
        SELECT SUM(s.stat_downloads) as total_dl
        FROM skill_snapshots s
        JOIN scrape_runs r ON s.scrape_run_id = r.id
        WHERE r.status = 'completed'
        GROUP BY r.id
        ORDER BY r.id
    """).fetchall()
    download_sparkline = [row[0] for row in sparkline_rows]

    # Median DL/day for skills created in last 30 days
    median_dl = conn.execute("""
        SELECT MEDIAN(
            stat_downloads / GREATEST(DATE_DIFF('day', created_at, ?), 1)
        )
        FROM current_skills
        WHERE created_at IS NOT NULL
          AND created_at >= ? - INTERVAL 30 DAY
    """, [now, now]).fetchone()[0]

    # Median DL/day for skills created 30-60 days ago (for MoM comparison)
    median_dl_prev = conn.execute("""
        SELECT MEDIAN(
            stat_downloads / GREATEST(DATE_DIFF('day', created_at, ?), 1)
        )
        FROM current_skills
        WHERE created_at IS NOT NULL
          AND created_at >= ? - INTERVAL 60 DAY
          AND created_at < ? - INTERVAL 30 DAY
    """, [now, now, now]).fetchone()[0]

    return {
        "total_skills": totals[0],
        "total_downloads": totals[1],
        "total_stars": totals[2],
        "total_owners": totals[3],
        "weekly_growth": weekly_growth,
        "download_sparkline": download_sparkline,
        "median_dl_per_day": round(float(median_dl), 1) if median_dl is not None else None,
        "median_dl_per_day_prev": round(float(median_dl_prev), 1) if median_dl_prev is not None else None,
        "generated_at": now.isoformat(),
    }
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/test_site_data.py::TestDashboardData -v`
Expected: All 5 tests PASS

- [ ] **Step 6: Run ruff**

Run: `.venv/bin/ruff check app/site_data.py tests/unit/test_site_data.py && .venv/bin/ruff format app/site_data.py tests/unit/test_site_data.py`
Expected: No errors

- [ ] **Step 7: Commit**

```bash
git add app/site_data.py tests/unit/test_site_data.py
git commit -m "Add dashboard_data() with KPIs, weekly growth, and sparkline"
```

---

### Task 3: rising_data() — top skills by velocity

**Files:**
- Modify: `app/site_data.py`
- Modify: `tests/unit/test_site_data.py`

- [ ] **Step 1: Write failing tests for rising_data()**

Append to `tests/unit/test_site_data.py`:

```python
from app.site_data import rising_data


class TestRisingData:
    def test_returns_empty_with_single_run(self, db):
        _seed(
            db,
            lambda rid: [
                _make(rid, "a", created_at=_ts(2026, 3, 10), stat_downloads=100),
            ],
        )
        data = rising_data(db, now=_ts(2026, 3, 16))
        assert data["skills"] == []

    def test_ranks_by_dl_per_day(self, db):
        run1 = start_run(db)
        insert_snapshots(db, [
            _make(run1.id, "slow", created_at=_ts(2026, 3, 1),
                  stat_downloads=100),
            _make(run1.id, "fast", created_at=_ts(2026, 3, 10),
                  stat_downloads=100),
        ])
        complete_run(db, run1.id, total_skills=2)

        run2 = start_run(db)
        insert_snapshots(db, [
            _make(run2.id, "slow", created_at=_ts(2026, 3, 1),
                  stat_downloads=200),
            _make(run2.id, "fast", created_at=_ts(2026, 3, 10),
                  stat_downloads=500),
        ])
        complete_run(db, run2.id, total_skills=2)

        data = rising_data(db, now=_ts(2026, 3, 16))
        slugs = [s["slug"] for s in data["skills"]]
        assert slugs[0] == "slug-fast"  # higher DL/day

    def test_includes_delta(self, db):
        run1 = start_run(db)
        insert_snapshots(db, [
            _make(run1.id, "a", created_at=_ts(2026, 3, 10),
                  stat_downloads=100),
        ])
        complete_run(db, run1.id, total_skills=1)

        run2 = start_run(db)
        insert_snapshots(db, [
            _make(run2.id, "a", created_at=_ts(2026, 3, 10),
                  stat_downloads=500),
        ])
        complete_run(db, run2.id, total_skills=1)

        data = rising_data(db, now=_ts(2026, 3, 16))
        assert data["skills"][0]["delta"] == 400

    def test_includes_velocity_array(self, db):
        for i in range(3):
            run = start_run(db)
            insert_snapshots(db, [
                _make(run.id, "a", created_at=_ts(2026, 3, 10),
                      stat_downloads=(i + 1) * 100),
            ])
            complete_run(db, run.id, total_skills=1)

        data = rising_data(db, now=_ts(2026, 3, 16))
        assert data["skills"][0]["velocity_chart"] == [100, 200, 300]

    def test_excludes_old_skills(self, db):
        run1 = start_run(db)
        insert_snapshots(db, [
            _make(run1.id, "old", created_at=_ts(2026, 1, 1),
                  stat_downloads=100),
        ])
        complete_run(db, run1.id, total_skills=1)

        run2 = start_run(db)
        insert_snapshots(db, [
            _make(run2.id, "old", created_at=_ts(2026, 1, 1),
                  stat_downloads=9999),
        ])
        complete_run(db, run2.id, total_skills=1)

        data = rising_data(db, now=_ts(2026, 3, 16))
        assert data["skills"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/test_site_data.py::TestRisingData -v`
Expected: FAIL — `ImportError: cannot import name 'rising_data'`

- [ ] **Step 3: Implement rising_data()**

Append to `app/site_data.py`:

```python
# ---------------------------------------------------------------------------
# Rising Skills
# ---------------------------------------------------------------------------
def rising_data(
    conn: duckdb.DuckDBPyConnection,
    limit: int = 50,
    max_age_days: int = 30,
    now: datetime | None = None,
) -> dict:
    """Top skills by download velocity with mini-chart arrays."""
    now = now or _now()
    logger.info("[SITE_DATA] Computing rising skills data")

    # Get the two latest completed run IDs
    runs = conn.execute(
        "SELECT id FROM scrape_runs WHERE status = 'completed' ORDER BY id DESC LIMIT 2"
    ).fetchall()
    if len(runs) < 2:
        return {"skills": [], "generated_at": now.isoformat()}

    curr_id, prev_id = runs[0][0], runs[1][0]
    cutoff = now - timedelta(days=max_age_days)

    # Recent skills with DL/day and delta
    rows = conn.execute("""
        SELECT
            c.skill_id,
            c.slug,
            c.display_name,
            c.owner_handle,
            c.summary,
            c.created_at,
            c.stat_downloads,
            c.stat_downloads / GREATEST(DATE_DIFF('day', c.created_at, ?), 1) as dl_per_day,
            c.stat_downloads - COALESCE(p.stat_downloads, 0) as delta
        FROM skill_snapshots c
        LEFT JOIN skill_snapshots p
            ON c.skill_id = p.skill_id AND p.scrape_run_id = ?
        WHERE c.scrape_run_id = ?
          AND c.created_at IS NOT NULL
          AND c.created_at >= ?
        ORDER BY dl_per_day DESC
        LIMIT ?
    """, [now, prev_id, curr_id, cutoff, limit]).fetchall()

    # Build velocity arrays for each skill (last N runs)
    all_run_ids = conn.execute(
        "SELECT id FROM scrape_runs WHERE status = 'completed' ORDER BY id DESC LIMIT ?",
        [VELOCITY_CHART_RUNS],
    ).fetchall()
    run_ids = [r[0] for r in reversed(all_run_ids)]

    skills = []
    for row in rows:
        skill_id = row[0]
        # Fetch download counts across runs for mini chart
        chart_rows = conn.execute("""
            SELECT scrape_run_id, stat_downloads
            FROM skill_snapshots
            WHERE skill_id = ? AND scrape_run_id IN ({})
            ORDER BY scrape_run_id
        """.format(",".join("?" * len(run_ids))),
            [skill_id] + run_ids,
        ).fetchall()
        velocity_chart = [r[1] for r in chart_rows]

        skills.append({
            "skill_id": row[0],
            "slug": row[1],
            "display_name": row[2],
            "owner_handle": row[3],
            "summary": row[4],
            "created_at": row[5].isoformat() if row[5] else None,
            "stat_downloads": row[6],
            "dl_per_day": round(float(row[7]), 1),
            "delta": row[8],
            "velocity_chart": velocity_chart,
        })

    return {"skills": skills, "generated_at": now.isoformat()}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/test_site_data.py::TestRisingData -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Run ruff and commit**

```bash
.venv/bin/ruff check app/site_data.py tests/unit/test_site_data.py
.venv/bin/ruff format app/site_data.py tests/unit/test_site_data.py
git add app/site_data.py tests/unit/test_site_data.py
git commit -m "Add rising_data() with velocity charts and deltas"
```

---

### Task 4: leaderboard_data() — all-time + fastest growing

**Files:**
- Modify: `app/site_data.py`
- Modify: `tests/unit/test_site_data.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/unit/test_site_data.py`:

```python
from app.site_data import leaderboard_data


class TestLeaderboardData:
    def test_all_time_ordered_by_downloads(self, db):
        _seed(
            db,
            lambda rid: [
                _make(rid, "low", stat_downloads=10),
                _make(rid, "high", stat_downloads=9999),
                _make(rid, "mid", stat_downloads=500),
            ],
        )
        data = leaderboard_data(db)
        slugs = [s["slug"] for s in data["all_time"]]
        assert slugs == ["slug-high", "slug-mid", "slug-low"]

    def test_fastest_growing_requires_two_runs(self, db):
        _seed(
            db,
            lambda rid: [_make(rid, "a", stat_downloads=100)],
        )
        data = leaderboard_data(db)
        assert data["fastest_growing"] == []

    def test_fastest_growing_with_acceleration(self, db):
        # 3 runs to compute velocity_recent and velocity_prior
        for i in range(4):
            run = start_run(db)
            insert_snapshots(db, [
                _make(run.id, "accel",
                      stat_downloads=100 + i * 200,
                      created_at=_ts(2026, 1, 1)),
                _make(run.id, "flat",
                      stat_downloads=100 + i * 10,
                      created_at=_ts(2026, 1, 1)),
            ])
            complete_run(db, run.id, total_skills=2)

        data = leaderboard_data(db)
        if data["fastest_growing"]:
            assert data["fastest_growing"][0]["slug"] == "slug-accel"

    def test_trend_arrow(self, db):
        for i in range(4):
            run = start_run(db)
            insert_snapshots(db, [
                _make(run.id, "up",
                      stat_downloads=100 * (2 ** i),
                      created_at=_ts(2026, 1, 1)),
            ])
            complete_run(db, run.id, total_skills=1)

        data = leaderboard_data(db)
        # All-time entry should have a trend
        entry = data["all_time"][0]
        assert entry["trend"] in ("up", "down", "flat")

    def test_empty_db(self, db):
        data = leaderboard_data(db)
        assert data["all_time"] == []
        assert data["fastest_growing"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/test_site_data.py::TestLeaderboardData -v`
Expected: FAIL — `ImportError: cannot import name 'leaderboard_data'`

- [ ] **Step 3: Implement leaderboard_data()**

Append to `app/site_data.py`:

```python
# ---------------------------------------------------------------------------
# Leaderboard
# ---------------------------------------------------------------------------
def leaderboard_data(
    conn: duckdb.DuckDBPyConnection, limit: int = 100, now: datetime | None = None
) -> dict:
    """Top skills by total downloads and by acceleration."""
    now = now or _now()
    logger.info("[SITE_DATA] Computing leaderboard data")

    run_row = conn.execute(
        "SELECT id FROM scrape_runs WHERE status = 'completed' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if run_row is None:
        return {"all_time": [], "fastest_growing": [], "generated_at": now.isoformat()}

    # --- All-time top by downloads ---
    # Get completed run IDs for velocity calculation
    run_ids_rows = conn.execute(
        "SELECT id FROM scrape_runs WHERE status = 'completed' ORDER BY id DESC LIMIT 6"
    ).fetchall()
    run_ids = [r[0] for r in run_ids_rows]
    curr_id = run_ids[0]
    recent_ids = run_ids[:3]   # last 3 runs
    prior_ids = run_ids[3:6]   # prior 3 runs

    all_time_rows = conn.execute("""
        SELECT skill_id, slug, display_name, owner_handle,
               stat_downloads, created_at
        FROM skill_snapshots
        WHERE scrape_run_id = ?
        ORDER BY stat_downloads DESC
        LIMIT ?
    """, [curr_id, limit]).fetchall()

    all_time = []
    for row in all_time_rows:
        skill_id = row[0]
        vel_recent = _avg_velocity(conn, skill_id, recent_ids) if len(recent_ids) >= 2 else None
        vel_prior = _avg_velocity(conn, skill_id, prior_ids) if len(prior_ids) >= 2 else None
        trend = _compute_trend(vel_recent, vel_prior)
        all_time.append({
            "skill_id": skill_id,
            "slug": row[1],
            "display_name": row[2],
            "owner_handle": row[3],
            "stat_downloads": row[4],
            "created_at": row[5].isoformat() if row[5] else None,
            "velocity": round(vel_recent, 1) if vel_recent is not None else None,
            "trend": trend,
        })

    # --- Fastest growing by acceleration ---
    fastest_growing = []
    if len(run_ids) >= 4:
        # Get all skills with enough downloads
        candidates = conn.execute("""
            SELECT skill_id, slug, display_name, owner_handle,
                   stat_downloads, created_at
            FROM skill_snapshots
            WHERE scrape_run_id = ? AND stat_downloads >= ?
            ORDER BY stat_downloads DESC
        """, [curr_id, ACCEL_MIN_DOWNLOADS]).fetchall()

        accel_list = []
        for row in candidates:
            skill_id = row[0]
            vel_recent = _avg_velocity(conn, skill_id, recent_ids)
            vel_prior = _avg_velocity(conn, skill_id, prior_ids)
            if vel_prior and vel_prior > 0:
                accel = (vel_recent - vel_prior) / vel_prior * 100
            else:
                accel = None
            if accel is not None:
                accel_list.append({
                    "skill_id": skill_id,
                    "slug": row[1],
                    "display_name": row[2],
                    "owner_handle": row[3],
                    "stat_downloads": row[4],
                    "created_at": row[5].isoformat() if row[5] else None,
                    "velocity": round(vel_recent, 1) if vel_recent else None,
                    "acceleration_pct": round(accel, 1),
                    "trend": _compute_trend(vel_recent, vel_prior),
                })

        accel_list.sort(key=lambda x: x["acceleration_pct"], reverse=True)
        fastest_growing = accel_list[:limit]

    return {
        "all_time": all_time,
        "fastest_growing": fastest_growing,
        "generated_at": now.isoformat(),
    }


def _avg_velocity(
    conn: duckdb.DuckDBPyConnection, skill_id: str, run_ids: list[int]
) -> float | None:
    """Average DL delta per run across given run IDs."""
    if len(run_ids) < 2:
        return None
    placeholders = ",".join("?" * len(run_ids))
    rows = conn.execute(f"""
        SELECT stat_downloads
        FROM skill_snapshots
        WHERE skill_id = ? AND scrape_run_id IN ({placeholders})
        ORDER BY scrape_run_id
    """, [skill_id] + run_ids).fetchall()
    if len(rows) < 2:
        return None
    downloads = [r[0] for r in rows]
    deltas = [downloads[i + 1] - downloads[i] for i in range(len(downloads) - 1)]
    return sum(deltas) / len(deltas) if deltas else None


def _compute_trend(vel_recent: float | None, vel_prior: float | None) -> str:
    """Return 'up', 'down', or 'flat' based on velocity change threshold."""
    if vel_recent is None or vel_prior is None or vel_prior == 0:
        return "flat"
    change_pct = (vel_recent - vel_prior) / abs(vel_prior) * 100
    if change_pct > TREND_THRESHOLD_PCT:
        return "up"
    elif change_pct < -TREND_THRESHOLD_PCT:
        return "down"
    return "flat"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/test_site_data.py::TestLeaderboardData -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Run ruff and commit**

```bash
.venv/bin/ruff check app/site_data.py tests/unit/test_site_data.py
.venv/bin/ruff format app/site_data.py tests/unit/test_site_data.py
git add app/site_data.py tests/unit/test_site_data.py
git commit -m "Add leaderboard_data() with all-time and acceleration rankings"
```

---

### Task 5: cohorts_data() — percentile distributions

**Files:**
- Modify: `app/site_data.py`
- Modify: `tests/unit/test_site_data.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/unit/test_site_data.py`:

```python
from app.site_data import cohorts_data


class TestCohortsData:
    def test_monthly_cohorts_with_percentiles(self, db):
        _seed(
            db,
            lambda rid: [
                _make(rid, "jan1", created_at=_ts(2026, 1, 15),
                      stat_downloads=5000, stat_stars=50),
                _make(rid, "jan2", created_at=_ts(2026, 1, 20),
                      stat_downloads=3000, stat_stars=30),
                _make(rid, "feb1", created_at=_ts(2026, 2, 10),
                      stat_downloads=800, stat_stars=8),
                _make(rid, "mar1", created_at=_ts(2026, 3, 1),
                      stat_downloads=50, stat_stars=1),
            ],
        )
        data = cohorts_data(db, now=_ts(2026, 3, 16))
        cohorts = data["cohorts"]
        assert len(cohorts) == 3
        jan = cohorts[0]
        assert jan["month"] == "2026-01"
        assert jan["skill_count"] == 2
        assert "p50" in jan
        assert "p25" in jan
        assert "p75" in jan
        assert "p90" in jan
        assert "p99" in jan
        assert "avg_dl_per_day" in jan

    def test_star_to_download_ratio(self, db):
        _seed(
            db,
            lambda rid: [
                _make(rid, "a", created_at=_ts(2026, 1, 15),
                      stat_downloads=1000, stat_stars=100),
                _make(rid, "b", created_at=_ts(2026, 1, 20),
                      stat_downloads=1000, stat_stars=50),
            ],
        )
        data = cohorts_data(db, now=_ts(2026, 3, 16))
        jan = data["cohorts"][0]
        # 150 stars / 2000 downloads = 0.075
        assert jan["star_dl_ratio"] == 0.075

    def test_empty_db(self, db):
        data = cohorts_data(db)
        assert data["cohorts"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/test_site_data.py::TestCohortsData -v`
Expected: FAIL — `ImportError: cannot import name 'cohorts_data'`

- [ ] **Step 3: Implement cohorts_data()**

Append to `app/site_data.py`:

```python
# ---------------------------------------------------------------------------
# Cohorts
# ---------------------------------------------------------------------------
def cohorts_data(conn: duckdb.DuckDBPyConnection, now: datetime | None = None) -> dict:
    """Monthly cohort percentiles for DL/day distribution."""
    now = now or _now()
    logger.info("[SITE_DATA] Computing cohort data")

    run_row = conn.execute(
        "SELECT id FROM scrape_runs WHERE status = 'completed' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if run_row is None:
        return {"cohorts": [], "generated_at": now.isoformat()}

    rows = conn.execute("""
        SELECT
            DATE_TRUNC('month', created_at) as cohort_month,
            COUNT(*) as skill_count,
            PERCENTILE_CONT(0.25) WITHIN GROUP (
                ORDER BY stat_downloads / GREATEST(DATE_DIFF('day', created_at, ?), 1)
            ) as p25,
            PERCENTILE_CONT(0.50) WITHIN GROUP (
                ORDER BY stat_downloads / GREATEST(DATE_DIFF('day', created_at, ?), 1)
            ) as p50,
            PERCENTILE_CONT(0.75) WITHIN GROUP (
                ORDER BY stat_downloads / GREATEST(DATE_DIFF('day', created_at, ?), 1)
            ) as p75,
            PERCENTILE_CONT(0.90) WITHIN GROUP (
                ORDER BY stat_downloads / GREATEST(DATE_DIFF('day', created_at, ?), 1)
            ) as p90,
            PERCENTILE_CONT(0.99) WITHIN GROUP (
                ORDER BY stat_downloads / GREATEST(DATE_DIFF('day', created_at, ?), 1)
            ) as p99,
            AVG(stat_downloads / GREATEST(DATE_DIFF('day', created_at, ?), 1)) as avg_dl_per_day,
            SUM(stat_stars) as total_stars,
            SUM(stat_downloads) as total_downloads
        FROM current_skills
        WHERE created_at IS NOT NULL
        GROUP BY 1
        ORDER BY 1
    """, [now, now, now, now, now, now]).fetchall()

    cohorts = []
    for row in rows:
        month_str = row[0].strftime("%Y-%m") if hasattr(row[0], "strftime") else str(row[0])[:7]
        total_dl = row[9] or 0
        star_dl_ratio = round(row[8] / total_dl, 4) if total_dl > 0 else 0.0
        cohorts.append({
            "month": month_str,
            "skill_count": row[1],
            "p25": round(float(row[2]), 1),
            "p50": round(float(row[3]), 1),
            "p75": round(float(row[4]), 1),
            "p90": round(float(row[5]), 1),
            "p99": round(float(row[6]), 1),
            "avg_dl_per_day": round(float(row[7]), 1),
            "star_dl_ratio": star_dl_ratio,
        })

    return {"cohorts": cohorts, "generated_at": now.isoformat()}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/test_site_data.py::TestCohortsData -v`
Expected: All 3 tests PASS

- [ ] **Step 5: Run ruff and commit**

```bash
.venv/bin/ruff check app/site_data.py tests/unit/test_site_data.py
.venv/bin/ruff format app/site_data.py tests/unit/test_site_data.py
git add app/site_data.py tests/unit/test_site_data.py
git commit -m "Add cohorts_data() with percentile distributions and star/DL ratio"
```

---

### Task 6: skill_detail_data() and owner_detail_data()

**Files:**
- Modify: `app/site_data.py`
- Modify: `tests/unit/test_site_data.py`

- [ ] **Step 1: Write failing tests for skill_detail_data()**

Append to `tests/unit/test_site_data.py`:

```python
from app.site_data import skill_detail_data


class TestSkillDetailData:
    def test_history_across_runs(self, db):
        for i in range(3):
            run = start_run(db)
            insert_snapshots(db, [
                _make(run.id, "a", stat_downloads=(i + 1) * 100,
                      stat_stars=(i + 1) * 10,
                      created_at=_ts(2026, 1, 1)),
            ])
            complete_run(db, run.id, total_skills=1)

        data = skill_detail_data(db, "slug-a")
        assert len(data["history"]) == 3
        assert data["history"][0]["downloads"] == 100
        assert data["history"][2]["downloads"] == 300

    def test_version_releases_detected(self, db):
        run1 = start_run(db)
        insert_snapshots(db, [
            _make(run1.id, "a", version_number="1.0.0",
                  created_at=_ts(2026, 1, 1)),
        ])
        complete_run(db, run1.id, total_skills=1)

        run2 = start_run(db)
        insert_snapshots(db, [
            _make(run2.id, "a", version_number="1.1.0",
                  version_changelog="Bug fix",
                  created_at=_ts(2026, 1, 1)),
        ])
        complete_run(db, run2.id, total_skills=1)

        data = skill_detail_data(db, "slug-a")
        assert len(data["version_releases"]) == 1
        assert data["version_releases"][0]["version_number"] == "1.1.0"
        assert data["version_releases"][0]["changelog"] == "Bug fix"

    def test_returns_none_for_unknown_slug(self, db):
        _seed(db, lambda rid: [_make(rid, "a")])
        data = skill_detail_data(db, "nonexistent")
        assert data is None
```

- [ ] **Step 2: Write failing tests for owner_detail_data()**

Append to `tests/unit/test_site_data.py`:

```python
from app.site_data import owner_detail_data


class TestOwnerDetailData:
    def test_portfolio_summary(self, db):
        _seed(
            db,
            lambda rid: [
                _make(rid, "s1", owner_handle="alice",
                      stat_downloads=5000, created_at=_ts(2026, 1, 1)),
                _make(rid, "s2", owner_handle="alice",
                      stat_downloads=3000, created_at=_ts(2026, 2, 1)),
                _make(rid, "s3", owner_handle="bob",
                      stat_downloads=1000, created_at=_ts(2026, 1, 1)),
            ],
        )
        data = owner_detail_data(db, "alice")
        assert data["total_downloads"] == 8000
        assert data["skill_count"] == 2
        assert len(data["skills"]) == 2

    def test_download_trajectory(self, db):
        for i in range(3):
            run = start_run(db)
            insert_snapshots(db, [
                _make(run.id, "s1", owner_handle="alice",
                      stat_downloads=(i + 1) * 100),
            ])
            complete_run(db, run.id, total_skills=1)

        data = owner_detail_data(db, "alice")
        assert len(data["download_trajectory"]) == 3
        assert data["download_trajectory"] == [100, 200, 300]

    def test_returns_none_for_unknown_handle(self, db):
        _seed(db, lambda rid: [_make(rid, "a", owner_handle="alice")])
        data = owner_detail_data(db, "nonexistent")
        assert data is None
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/test_site_data.py::TestSkillDetailData tests/unit/test_site_data.py::TestOwnerDetailData -v`
Expected: FAIL — import errors

- [ ] **Step 4: Implement skill_detail_data()**

Append to `app/site_data.py`:

```python
# ---------------------------------------------------------------------------
# Skill Detail
# ---------------------------------------------------------------------------
def skill_detail_data(
    conn: duckdb.DuckDBPyConnection, slug: str, now: datetime | None = None
) -> dict | None:
    """Full history for a single skill by slug."""
    now = now or _now()
    logger.info("[SITE_DATA] Computing skill detail for {}", slug)

    # Find skill_id from slug in current run
    row = conn.execute(
        "SELECT skill_id FROM current_skills WHERE slug = ? LIMIT 1", [slug]
    ).fetchone()
    if row is None:
        return None
    skill_id = row[0]

    # Current skill metadata
    meta = conn.execute("""
        SELECT display_name, summary, owner_handle, created_at,
               stat_downloads, stat_stars, tags
        FROM current_skills WHERE skill_id = ?
    """, [skill_id]).fetchone()

    # History across all completed runs
    history_rows = conn.execute("""
        SELECT r.started_at, s.stat_downloads, s.stat_stars,
               s.stat_installs_all_time, s.stat_installs_current,
               s.version_number, s.version_changelog
        FROM skill_snapshots s
        JOIN scrape_runs r ON s.scrape_run_id = r.id
        WHERE s.skill_id = ? AND r.status = 'completed'
        ORDER BY r.id
    """, [skill_id]).fetchall()

    history = []
    version_releases = []
    prev_version = None
    for h in history_rows:
        run_date = h[0].isoformat() if h[0] else None
        history.append({
            "run_date": run_date,
            "downloads": h[1],
            "stars": h[2],
            "installs_all_time": h[3],
            "installs_current": h[4],
        })
        # Detect version changes
        curr_version = h[5]
        if curr_version and curr_version != prev_version and prev_version is not None:
            version_releases.append({
                "version_number": curr_version,
                "run_date": run_date,
                "changelog": h[6],
            })
        prev_version = curr_version

    # Compute velocity and acceleration
    created_at = meta[3]
    velocity = None
    if created_at:
        age_days = max((now - created_at).days, 1)
        velocity = round(meta[4] / age_days, 1)

    # Acceleration (same formula as leaderboard)
    acceleration_pct = None
    run_ids_rows = conn.execute(
        "SELECT id FROM scrape_runs WHERE status = 'completed' ORDER BY id DESC LIMIT 6"
    ).fetchall()
    run_ids = [r[0] for r in run_ids_rows]
    if len(run_ids) >= 4:
        recent_ids = run_ids[:3]
        prior_ids = run_ids[3:6]
        vel_recent = _avg_velocity(conn, skill_id, recent_ids)
        vel_prior = _avg_velocity(conn, skill_id, prior_ids)
        if vel_prior and vel_prior > 0 and vel_recent is not None:
            acceleration_pct = round((vel_recent - vel_prior) / vel_prior * 100, 1)

    return {
        "skill_id": skill_id,
        "slug": slug,
        "display_name": meta[0],
        "summary": meta[1],
        "owner_handle": meta[2],
        "created_at": meta[3].isoformat() if meta[3] else None,
        "stat_downloads": meta[4],
        "stat_stars": meta[5],
        "tags": meta[6],
        "velocity": velocity,
        "acceleration_pct": acceleration_pct,
        "history": history,
        "version_releases": version_releases,
    }
```

- [ ] **Step 5: Implement owner_detail_data()**

Append to `app/site_data.py`:

```python
# ---------------------------------------------------------------------------
# Owner Detail
# ---------------------------------------------------------------------------
def owner_detail_data(
    conn: duckdb.DuckDBPyConnection, handle: str, now: datetime | None = None
) -> dict | None:
    """Owner portfolio with download trajectory."""
    now = now or _now()
    logger.info("[SITE_DATA] Computing owner detail for {}", handle)

    # Check owner exists in current run
    check = conn.execute(
        "SELECT COUNT(*) FROM current_skills WHERE owner_handle = ?", [handle]
    ).fetchone()
    if check[0] == 0:
        return None

    # Portfolio summary from current run
    summary = conn.execute("""
        SELECT
            SUM(stat_downloads) as total_downloads,
            COUNT(*) as skill_count,
            AVG(stat_downloads / GREATEST(DATE_DIFF('day', created_at, ?), 1))
                as avg_dl_per_day
        FROM current_skills
        WHERE owner_handle = ? AND created_at IS NOT NULL
    """, [now, handle]).fetchone()

    # Individual skills
    skills_rows = conn.execute("""
        SELECT slug, display_name, stat_downloads, stat_stars, created_at
        FROM current_skills
        WHERE owner_handle = ?
        ORDER BY stat_downloads DESC
    """, [handle]).fetchall()

    skills = [{
        "slug": r[0],
        "display_name": r[1],
        "stat_downloads": r[2],
        "stat_stars": r[3],
        "created_at": r[4].isoformat() if r[4] else None,
    } for r in skills_rows]

    # Download trajectory across runs
    traj_rows = conn.execute("""
        SELECT r.id, SUM(s.stat_downloads) as total_dl
        FROM skill_snapshots s
        JOIN scrape_runs r ON s.scrape_run_id = r.id
        WHERE s.owner_handle = ? AND r.status = 'completed'
        GROUP BY r.id
        ORDER BY r.id
    """, [handle]).fetchall()

    return {
        "handle": handle,
        "total_downloads": summary[0] or 0,
        "skill_count": summary[1],
        "avg_dl_per_day": round(float(summary[2]), 1) if summary[2] else 0.0,
        "skills": skills,
        "download_trajectory": [r[1] for r in traj_rows],
    }
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/test_site_data.py::TestSkillDetailData tests/unit/test_site_data.py::TestOwnerDetailData -v`
Expected: All 6 tests PASS

- [ ] **Step 7: Run ruff and commit**

```bash
.venv/bin/ruff check app/site_data.py tests/unit/test_site_data.py
.venv/bin/ruff format app/site_data.py tests/unit/test_site_data.py
git add app/site_data.py tests/unit/test_site_data.py
git commit -m "Add skill_detail_data() and owner_detail_data() with history tracking"
```

---

### Task 7: Threshold functions + api_index()

**Files:**
- Modify: `app/site_data.py`
- Modify: `tests/unit/test_site_data.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/unit/test_site_data.py`:

```python
from app.site_data import top_skills_for_detail, top_owners_for_detail, api_index


class TestThresholds:
    def test_top_skills_by_downloads(self, db):
        _seed(
            db,
            lambda rid: [
                _make(rid, "big", stat_downloads=9999, slug="big-skill"),
                _make(rid, "small", stat_downloads=1, slug="small-skill"),
            ],
        )
        slugs = top_skills_for_detail(db, limit=1)
        assert slugs == ["big-skill"]

    def test_skips_null_slugs(self, db):
        _seed(
            db,
            lambda rid: [
                _make(rid, "a", stat_downloads=9999, slug=None),
                _make(rid, "b", stat_downloads=5000, slug="has-slug"),
            ],
        )
        slugs = top_skills_for_detail(db, limit=10)
        assert "has-slug" in slugs
        assert None not in slugs

    def test_top_owners(self, db):
        _seed(
            db,
            lambda rid: [
                _make(rid, "a1", owner_handle="alice", stat_downloads=5000),
                _make(rid, "a2", owner_handle="alice", stat_downloads=3000),
                _make(rid, "b1", owner_handle="bob", stat_downloads=100),
            ],
        )
        handles = top_owners_for_detail(db, limit=1)
        assert handles == ["alice"]


class TestApiIndex:
    def test_structure(self, db):
        _seed(
            db,
            lambda rid: [
                _make(rid, "a", slug="skill-a", owner_handle="alice",
                      stat_downloads=5000),
            ],
        )
        data = api_index(
            skill_slugs=["skill-a"],
            owner_handles=["alice"],
        )
        assert "endpoints" in data
        assert "skills" in data
        assert data["skills"]["count"] == 1
        assert data["owners"]["count"] == 1
        assert "generated_at" in data
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/test_site_data.py::TestThresholds tests/unit/test_site_data.py::TestApiIndex -v`
Expected: FAIL — import errors

- [ ] **Step 3: Implement threshold functions and api_index()**

Append to `app/site_data.py`:

```python
# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------
def top_skills_for_detail(
    conn: duckdb.DuckDBPyConnection, limit: int = SKILL_DETAIL_LIMIT, now: datetime | None = None
) -> list[str]:
    """Slugs qualifying for detail page generation."""
    now = now or _now()
    logger.info("[SITE_DATA] Computing top skills for detail pages")
    rows = conn.execute("""
        SELECT DISTINCT slug FROM (
            (SELECT slug FROM current_skills
             WHERE slug IS NOT NULL
             ORDER BY stat_downloads DESC
             LIMIT ?)
            UNION
            (SELECT slug FROM current_skills
             WHERE slug IS NOT NULL AND created_at IS NOT NULL
             ORDER BY stat_downloads / GREATEST(DATE_DIFF('day', created_at, ?), 1) DESC
             LIMIT ?)
        )
    """, [limit, now, SKILL_VELOCITY_LIMIT]).fetchall()
    return [r[0] for r in rows]


def top_owners_for_detail(conn: duckdb.DuckDBPyConnection, limit: int = OWNER_DETAIL_LIMIT) -> list[str]:
    """Handles qualifying for detail page generation."""
    logger.info("[SITE_DATA] Computing top owners for detail pages")
    rows = conn.execute("""
        SELECT owner_handle
        FROM current_skills
        WHERE owner_handle IS NOT NULL
        GROUP BY owner_handle
        ORDER BY SUM(stat_downloads) DESC
        LIMIT ?
    """, [limit]).fetchall()
    return [r[0] for r in rows]


# ---------------------------------------------------------------------------
# API Index
# ---------------------------------------------------------------------------
def api_index(skill_slugs: list[str], owner_handles: list[str]) -> dict:
    """Generate the API catalog for agent discovery."""
    return {
        "generated_at": _now().isoformat(),
        "endpoints": {
            "dashboard": {
                "url": "/api/dashboard.json",
                "description": "Platform health metrics and sparklines",
            },
            "rising": {
                "url": "/api/rising.json",
                "description": "Top 50 skills by download velocity",
            },
            "leaderboard": {
                "url": "/api/leaderboard.json",
                "description": "Top 100 by downloads and acceleration",
            },
            "cohorts": {
                "url": "/api/cohorts.json",
                "description": "Monthly cohort percentile analysis",
            },
        },
        "skills": {
            "count": len(skill_slugs),
            "url_pattern": "/api/skills/{slug}.json",
            "available": skill_slugs,
        },
        "owners": {
            "count": len(owner_handles),
            "url_pattern": "/api/owners/{handle}.json",
            "available": owner_handles,
        },
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/test_site_data.py::TestThresholds tests/unit/test_site_data.py::TestApiIndex -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Run all tests to confirm nothing is broken**

Run: `.venv/bin/pytest tests/unit/test_site_data.py -v`
Expected: All tests PASS (dashboard: 5, rising: 5, leaderboard: 5, cohorts: 3, skill_detail: 3, owner_detail: 3, thresholds: 3, api_index: 1 = 28 total)

- [ ] **Step 6: Run ruff and commit**

```bash
.venv/bin/ruff check app/site_data.py tests/unit/test_site_data.py
.venv/bin/ruff format app/site_data.py tests/unit/test_site_data.py
git add app/site_data.py tests/unit/test_site_data.py
git commit -m "Add threshold functions and API index builder"
```

---

## Chunk 2: Templates, Rendering, and Orchestration

### Task 8: CSS theme + base template

**Files:**
- Create: `app/static/style.css`
- Create: `app/templates/base.html`

- [ ] **Step 1: Create the CSS file**

Create `app/static/style.css` with Catppuccin Mocha dark theme:

```css
/* Catppuccin Mocha palette */
:root {
    --base: #1e1e2e;
    --mantle: #181825;
    --surface0: #313244;
    --surface1: #45475a;
    --text: #cdd6f4;
    --subtext0: #a6adc8;
    --overlay0: #6c7086;
    --muted: #585b70;
    --blue: #89b4fa;
    --green: #a6e3a1;
    --yellow: #f9e2af;
    --peach: #fab387;
    --red: #f38ba8;
    --mauve: #cba6f7;
}

* { margin: 0; padding: 0; box-sizing: border-box; }

body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, monospace;
    background: var(--base);
    color: var(--text);
    line-height: 1.6;
}

.container { max-width: 1200px; margin: 0 auto; padding: 0 20px; }

/* Navigation */
nav {
    background: var(--mantle);
    border-bottom: 1px solid var(--surface0);
    padding: 12px 0;
    position: sticky;
    top: 0;
    z-index: 100;
}
nav .container { display: flex; align-items: center; gap: 24px; }
nav .logo { color: var(--blue); font-weight: 700; font-size: 18px; text-decoration: none; }
nav a {
    color: var(--subtext0);
    text-decoration: none;
    font-size: 14px;
    padding: 4px 8px;
    border-radius: 4px;
    transition: color 0.2s, background 0.2s;
}
nav a:hover, nav a.active { color: var(--text); background: var(--surface0); }

/* Page header */
.page-header { margin: 32px 0 24px; }
.page-header h1 { font-size: 28px; font-weight: 700; }
.page-header .subtitle { color: var(--subtext0); font-size: 14px; margin-top: 4px; }

/* KPI Cards */
.kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 16px; margin-bottom: 24px; }
.kpi-card {
    background: var(--mantle);
    border-radius: 8px;
    padding: 16px;
    border: 1px solid var(--surface0);
}
.kpi-card .label { color: var(--subtext0); font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px; }
.kpi-card .value { font-size: 28px; font-weight: 700; margin: 4px 0; }
.kpi-card .change { font-size: 13px; }
.kpi-card .change.up { color: var(--green); }
.kpi-card .change.down { color: var(--red); }
.kpi-card .change.flat { color: var(--muted); }
.kpi-card .sparkline-container { height: 50px; margin-top: 8px; }

/* Tables */
table { width: 100%; border-collapse: collapse; font-size: 14px; }
thead th {
    text-align: left;
    padding: 10px 12px;
    color: var(--subtext0);
    border-bottom: 2px solid var(--surface0);
    font-weight: 600;
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}
tbody td { padding: 10px 12px; border-bottom: 1px solid var(--surface0); }
tbody tr:hover { background: var(--mantle); }
td.number { text-align: right; font-variant-numeric: tabular-nums; }
td .bar { height: 14px; background: var(--blue); opacity: 0.4; border-radius: 2px; }

/* Trend arrows */
.trend-up { color: var(--green); }
.trend-down { color: var(--red); }
.trend-flat { color: var(--muted); }

/* Tabs (leaderboard) */
.tabs { display: flex; gap: 8px; margin-bottom: 16px; }
.tab-btn {
    padding: 8px 16px;
    border: 1px solid var(--surface0);
    background: transparent;
    color: var(--subtext0);
    border-radius: 6px;
    cursor: pointer;
    font-size: 14px;
}
.tab-btn.active { background: var(--surface0); color: var(--text); }
.tab-content { display: none; }
.tab-content.active { display: block; }

/* Mini velocity chart */
.velocity-chart { display: inline-block; width: 80px; height: 30px; }

/* Detail pages */
.detail-header { margin-bottom: 24px; }
.detail-header h1 { font-size: 24px; }
.detail-header .meta { color: var(--subtext0); font-size: 14px; margin-top: 4px; }
.detail-header .meta a { color: var(--blue); text-decoration: none; }
.chart-container { background: var(--mantle); border-radius: 8px; padding: 16px; margin-bottom: 24px; border: 1px solid var(--surface0); }
.chart-container h3 { font-size: 14px; color: var(--subtext0); margin-bottom: 12px; }
.stat-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px; margin-bottom: 24px; }
.stat-item { background: var(--mantle); padding: 12px; border-radius: 6px; border: 1px solid var(--surface0); }
.stat-item .label { font-size: 11px; color: var(--subtext0); text-transform: uppercase; }
.stat-item .value { font-size: 20px; font-weight: 700; }

/* Footer */
footer {
    margin-top: 48px;
    padding: 24px 0;
    border-top: 1px solid var(--surface0);
    color: var(--muted);
    font-size: 12px;
    text-align: center;
}
footer a { color: var(--blue); text-decoration: none; }

/* Responsive */
@media (max-width: 768px) {
    .kpi-grid { grid-template-columns: 1fr 1fr; }
    .stat-grid { grid-template-columns: 1fr 1fr; }
    table { font-size: 12px; }
    nav .container { flex-wrap: wrap; gap: 8px; }
}
@media (max-width: 480px) {
    .kpi-grid { grid-template-columns: 1fr; }
}

/* Filter buttons (rising page) */
.filters { display: flex; gap: 8px; margin-bottom: 16px; }
.filter-btn {
    padding: 6px 12px;
    border: 1px solid var(--surface0);
    background: transparent;
    color: var(--subtext0);
    border-radius: 4px;
    cursor: pointer;
    font-size: 13px;
}
.filter-btn.active { background: var(--blue); color: var(--mantle); border-color: var(--blue); }

/* Skill list on owner page */
.skill-list { list-style: none; }
.skill-list li {
    padding: 12px;
    border-bottom: 1px solid var(--surface0);
    display: flex;
    justify-content: space-between;
    align-items: center;
}
.skill-list li a { color: var(--blue); text-decoration: none; }
.skill-list li .stats { color: var(--subtext0); font-size: 13px; }

/* Empty state */
.empty-state {
    text-align: center;
    padding: 48px 0;
    color: var(--muted);
    font-size: 16px;
}
```

- [ ] **Step 2: Create the base template**

Create `app/templates/base.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}ClawHub Tracker{% endblock %}</title>
    <link rel="stylesheet" href="{{ static_prefix }}static/style.css">
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
    {% block head_extra %}{% endblock %}
</head>
<body>
    <nav>
        <div class="container">
            <a href="{{ static_prefix }}index.html" class="logo">ClawHub Tracker</a>
            <a href="{{ static_prefix }}index.html" {% if active_page == 'dashboard' %}class="active"{% endif %}>Dashboard</a>
            <a href="{{ static_prefix }}rising.html" {% if active_page == 'rising' %}class="active"{% endif %}>Rising</a>
            <a href="{{ static_prefix }}leaderboard.html" {% if active_page == 'leaderboard' %}class="active"{% endif %}>Leaderboard</a>
            <a href="{{ static_prefix }}cohorts.html" {% if active_page == 'cohorts' %}class="active"{% endif %}>Cohorts</a>
        </div>
    </nav>

    <main class="container">
        {% block content %}{% endblock %}
    </main>

    <footer>
        <div class="container">
            Last updated: {{ generated_at }} &middot;
            <a href="{{ static_prefix }}api/index.json">JSON API</a>
        </div>
    </footer>

    {% block scripts %}{% endblock %}
</body>
</html>
```

- [ ] **Step 3: Commit**

```bash
git add app/static/style.css app/templates/base.html
git commit -m "Add CSS theme and base HTML template"
```

---

### Task 9: Page templates (dashboard, rising, leaderboard, cohorts, detail pages)

**Files:**
- Create: `app/templates/dashboard.html`
- Create: `app/templates/rising.html`
- Create: `app/templates/leaderboard.html`
- Create: `app/templates/cohorts.html`
- Create: `app/templates/skill_detail.html`
- Create: `app/templates/owner_detail.html`

- [ ] **Step 1: Create dashboard.html**

Create `app/templates/dashboard.html`:

```html
{% extends "base.html" %}
{% block title %}Dashboard — ClawHub Tracker{% endblock %}

{% block content %}
<div class="page-header">
    <h1>Platform Dashboard</h1>
    <p class="subtitle">ClawHub skill marketplace health at a glance</p>
</div>

<div class="kpi-grid">
    <div class="kpi-card">
        <div class="label">Total Downloads</div>
        <div class="value">{{ "{:,}".format(data.total_downloads) }}</div>
        {% if data.weekly_growth|length >= 2 %}
        {% set wow = data.weekly_growth[-1].wow_pct %}
        <div class="change {% if wow and wow > 0 %}up{% elif wow and wow < 0 %}down{% else %}flat{% endif %}">
            {% if wow is not none %}{{ "%+.1f"|format(wow) }}% WoW{% else %}&mdash;{% endif %}
        </div>
        {% endif %}
        <div class="sparkline-container"><canvas id="sparkDl"></canvas></div>
    </div>
    <div class="kpi-card">
        <div class="label">New Skills / Week</div>
        <div class="value">{{ data.weekly_growth[-1].new_count if data.weekly_growth else 0 }}</div>
        {% if data.weekly_growth|length >= 2 %}
        {% set wow = data.weekly_growth[-1].wow_pct %}
        <div class="change {% if wow and wow > 0 %}up{% elif wow and wow < 0 %}down{% else %}flat{% endif %}">
            {% if wow is not none %}{{ "%+.1f"|format(wow) }}% WoW{% else %}&mdash;{% endif %}
        </div>
        {% endif %}
    </div>
    <div class="kpi-card">
        <div class="label">Total Owners</div>
        <div class="value">{{ "{:,}".format(data.total_owners) }}</div>
    </div>
    <div class="kpi-card">
        <div class="label">Median DL/day (new skills)</div>
        <div class="value">{{ data.median_dl_per_day if data.median_dl_per_day is not none else "N/A" }}</div>
        {% if data.median_dl_per_day is not none and data.median_dl_per_day_prev is not none and data.median_dl_per_day_prev > 0 %}
        {% set mom = ((data.median_dl_per_day - data.median_dl_per_day_prev) / data.median_dl_per_day_prev * 100) %}
        <div class="change {% if mom > 0 %}up{% elif mom < 0 %}down{% else %}flat{% endif %}">
            {{ "%+.1f"|format(mom) }}% MoM
        </div>
        {% endif %}
    </div>
</div>

{% if data.weekly_growth %}
<h2>Growth Timeline</h2>
<table>
    <thead>
        <tr>
            <th>Week</th>
            <th class="number">New Skills</th>
            <th class="number">Cumulative</th>
            <th class="number">WoW %</th>
            <th>Trend</th>
        </tr>
    </thead>
    <tbody>
    {% for w in data.weekly_growth|reverse %}
        <tr>
            <td>{{ w.week_start[:10] }}</td>
            <td class="number">{{ w.new_count }}</td>
            <td class="number">{{ "{:,}".format(w.cumulative) }}</td>
            <td class="number {% if w.wow_pct and w.wow_pct > 0 %}trend-up{% elif w.wow_pct and w.wow_pct < 0 %}trend-down{% endif %}">
                {% if w.wow_pct is not none %}{{ "%+.1f"|format(w.wow_pct) }}%{% else %}&mdash;{% endif %}
            </td>
            <td>
                {% if data.weekly_growth|length > 0 %}
                {% set max_new = data.weekly_growth|map(attribute='new_count')|max %}
                {% if max_new > 0 %}
                <div class="bar" style="width:{{ (w.new_count / max_new * 100)|int }}%"></div>
                {% endif %}
                {% endif %}
            </td>
        </tr>
    {% endfor %}
    </tbody>
</table>
{% endif %}
{% endblock %}

{% block scripts %}
<script>
{% if data.download_sparkline %}
new Chart(document.getElementById('sparkDl'), {
    type: 'line',
    data: { labels: {{ data.download_sparkline|map('string')|list|tojson }}, datasets: [{
        data: {{ data.download_sparkline|tojson }},
        borderColor: '#89b4fa', borderWidth: 2, fill: false, pointRadius: 0, tension: 0.3
    }]},
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false }},
        scales: { x: { display: false }, y: { display: false }}}
});
{% endif %}
</script>
{% endblock %}
```

- [ ] **Step 2: Create rising.html**

Create `app/templates/rising.html`:

```html
{% extends "base.html" %}
{% block title %}Rising Skills — ClawHub Tracker{% endblock %}

{% block content %}
<div class="page-header">
    <h1>Rising Skills</h1>
    <p class="subtitle">Skills gaining the most momentum right now</p>
</div>

{% if data.skills %}
<div class="filters">
    <button class="filter-btn active" onclick="filterAge(30, this)">30 days</button>
    <button class="filter-btn" onclick="filterAge(14, this)">14 days</button>
    <button class="filter-btn" onclick="filterAge(7, this)">7 days</button>
</div>

<table id="rising-table">
    <thead>
        <tr>
            <th>#</th>
            <th>Skill</th>
            <th>Owner</th>
            <th class="number">DL/day</th>
            <th class="number">Delta</th>
            <th class="number">Downloads</th>
            <th>Velocity</th>
            <th>Age</th>
        </tr>
    </thead>
    <tbody>
    {% for s in data.skills %}
        <tr data-created="{{ s.created_at }}">
            <td>{{ loop.index }}</td>
            <td><a href="skills/{{ s.slug }}.html">{{ s.display_name }}</a></td>
            <td>{{ s.owner_handle }}</td>
            <td class="number">{{ s.dl_per_day }}</td>
            <td class="number trend-up">+{{ "{:,}".format(s.delta) }}</td>
            <td class="number">{{ "{:,}".format(s.stat_downloads) }}</td>
            <td><canvas class="velocity-chart" id="vc-{{ loop.index0 }}"></canvas></td>
            <td>{{ s.created_at[:10] if s.created_at else "?" }}</td>
        </tr>
    {% endfor %}
    </tbody>
</table>
{% else %}
<div class="empty-state">Needs at least 2 scrape runs to compute velocity</div>
{% endif %}
{% endblock %}

{% block scripts %}
<script>
const velocityData = {{ data.skills|map(attribute='velocity_chart')|list|tojson }};
velocityData.forEach((vd, i) => {
    const el = document.getElementById('vc-' + i);
    if (el && vd.length > 1) {
        new Chart(el, {
            type: 'line',
            data: { labels: vd.map((_, j) => j), datasets: [{
                data: vd, borderColor: '#a6e3a1', borderWidth: 1.5, fill: false, pointRadius: 0, tension: 0.3
            }]},
            options: { responsive: false, maintainAspectRatio: false, plugins: { legend: { display: false }},
                scales: { x: { display: false }, y: { display: false }}}
        });
    }
});

function filterAge(days, btn) {
    document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    const cutoff = new Date();
    cutoff.setDate(cutoff.getDate() - days);
    document.querySelectorAll('#rising-table tbody tr').forEach(tr => {
        const created = new Date(tr.dataset.created);
        tr.style.display = created >= cutoff ? '' : 'none';
    });
}
</script>
{% endblock %}
```

- [ ] **Step 3: Create leaderboard.html**

Create `app/templates/leaderboard.html`:

```html
{% extends "base.html" %}
{% block title %}Leaderboard — ClawHub Tracker{% endblock %}

{% block content %}
<div class="page-header">
    <h1>Leaderboard</h1>
    <p class="subtitle">Top skills by downloads and acceleration</p>
</div>

<div class="tabs">
    <button class="tab-btn active" onclick="showTab('alltime', this)">All Time</button>
    <button class="tab-btn" onclick="showTab('fastest', this)">Fastest Growing</button>
</div>

<div id="tab-alltime" class="tab-content active">
<table>
    <thead>
        <tr>
            <th>#</th>
            <th>Skill</th>
            <th>Owner</th>
            <th class="number">Downloads</th>
            <th class="number">Velocity</th>
            <th>Trend</th>
        </tr>
    </thead>
    <tbody>
    {% for s in data.all_time %}
        <tr>
            <td>{{ loop.index }}</td>
            <td><a href="skills/{{ s.slug }}.html">{{ s.display_name }}</a></td>
            <td>{{ s.owner_handle }}</td>
            <td class="number">{{ "{:,}".format(s.stat_downloads) }}</td>
            <td class="number">{{ s.velocity if s.velocity is not none else "N/A" }}</td>
            <td class="trend-{{ s.trend }}">
                {% if s.trend == 'up' %}&#9650;{% elif s.trend == 'down' %}&#9660;{% else %}&#9644;{% endif %}
            </td>
        </tr>
    {% endfor %}
    </tbody>
</table>
</div>

<div id="tab-fastest" class="tab-content">
{% if data.fastest_growing %}
<table>
    <thead>
        <tr>
            <th>#</th>
            <th>Skill</th>
            <th>Owner</th>
            <th class="number">Downloads</th>
            <th class="number">Accel %</th>
            <th>Trend</th>
        </tr>
    </thead>
    <tbody>
    {% for s in data.fastest_growing %}
        <tr>
            <td>{{ loop.index }}</td>
            <td><a href="skills/{{ s.slug }}.html">{{ s.display_name }}</a></td>
            <td>{{ s.owner_handle }}</td>
            <td class="number">{{ "{:,}".format(s.stat_downloads) }}</td>
            <td class="number trend-up">{{ "%+.1f"|format(s.acceleration_pct) }}%</td>
            <td class="trend-{{ s.trend }}">
                {% if s.trend == 'up' %}&#9650;{% elif s.trend == 'down' %}&#9660;{% else %}&#9644;{% endif %}
            </td>
        </tr>
    {% endfor %}
    </tbody>
</table>
{% else %}
<div class="empty-state">Needs at least 4 scrape runs to compute acceleration</div>
{% endif %}
</div>
{% endblock %}

{% block scripts %}
<script>
function showTab(id, btn) {
    document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.getElementById('tab-' + id).classList.add('active');
    btn.classList.add('active');
}
</script>
{% endblock %}
```

- [ ] **Step 4: Create cohorts.html**

Create `app/templates/cohorts.html`:

```html
{% extends "base.html" %}
{% block title %}Cohorts — ClawHub Tracker{% endblock %}
{% block head_extra %}
<script src="https://cdn.jsdelivr.net/npm/@sgratzl/chartjs-chart-boxplot@4"></script>
{% endblock %}

{% block content %}
<div class="page-header">
    <h1>Cohort Analysis</h1>
    <p class="subtitle">Download velocity distribution by creation month (DL/day, normalized for age)</p>
</div>

{% if data.cohorts %}
<div class="chart-container">
    <h3>Distribution by Cohort</h3>
    <canvas id="boxplot" height="300"></canvas>
</div>

<table>
    <thead>
        <tr>
            <th>Cohort</th>
            <th class="number">Skills</th>
            <th class="number">P25</th>
            <th class="number">P50</th>
            <th class="number">P75</th>
            <th class="number">P90</th>
            <th class="number">P99</th>
            <th class="number">Avg DL/day</th>
            <th class="number">Star/DL</th>
        </tr>
    </thead>
    <tbody>
    {% for c in data.cohorts %}
        <tr>
            <td>{{ c.month }}</td>
            <td class="number">{{ "{:,}".format(c.skill_count) }}</td>
            <td class="number">{{ c.p25 }}</td>
            <td class="number">{{ c.p50 }}</td>
            <td class="number">{{ c.p75 }}</td>
            <td class="number">{{ c.p90 }}</td>
            <td class="number">{{ c.p99 }}</td>
            <td class="number">{{ c.avg_dl_per_day }}</td>
            <td class="number">{{ "%.4f"|format(c.star_dl_ratio) }}</td>
        </tr>
    {% endfor %}
    </tbody>
</table>
{% else %}
<div class="empty-state">No cohort data available</div>
{% endif %}
{% endblock %}

{% block scripts %}
{% if data.cohorts %}
<script>
const cohorts = {{ data.cohorts|tojson }};
new Chart(document.getElementById('boxplot'), {
    type: 'boxplot',
    data: {
        labels: cohorts.map(c => c.month),
        datasets: [{
            label: 'DL/day',
            backgroundColor: 'rgba(137, 180, 250, 0.2)',
            borderColor: '#89b4fa',
            borderWidth: 1,
            outlierColor: '#cba6f7',
            data: cohorts.map(c => ({
                min: c.p25,
                q1: c.p25,
                median: c.p50,
                q3: c.p75,
                max: c.p90,
                outliers: [c.p99]
            }))
        }]
    },
    options: {
        responsive: true,
        plugins: { legend: { display: false }},
        scales: {
            x: { ticks: { color: '#a6adc8' }, grid: { color: '#313244' }},
            y: { ticks: { color: '#a6adc8' }, grid: { color: '#313244' }}
        }
    }
});
</script>
{% endif %}
{% endblock %}
```

- [ ] **Step 5: Create skill_detail.html**

Create `app/templates/skill_detail.html`:

```html
{% extends "base.html" %}
{% block title %}{{ data.display_name }} — ClawHub Tracker{% endblock %}

{% block content %}
<div class="detail-header">
    <h1>{{ data.display_name }}</h1>
    <p class="meta">
        by <a href="{{ static_prefix }}owners/{{ data.owner_handle }}.html">{{ data.owner_handle }}</a>
        &middot; {{ data.stat_downloads|default(0) }} downloads
        &middot; {{ data.stat_stars|default(0) }} stars
        {% if data.velocity %}&middot; {{ data.velocity }} DL/day{% endif %}
    </p>
    {% if data.summary %}<p class="meta">{{ data.summary }}</p>{% endif %}
</div>

<div class="stat-grid">
    <div class="stat-item">
        <div class="label">Downloads</div>
        <div class="value">{{ "{:,}".format(data.stat_downloads|default(0)) }}</div>
    </div>
    <div class="stat-item">
        <div class="label">Stars</div>
        <div class="value">{{ "{:,}".format(data.stat_stars|default(0)) }}</div>
    </div>
    <div class="stat-item">
        <div class="label">DL/day</div>
        <div class="value">{{ data.velocity if data.velocity else "N/A" }}</div>
    </div>
    <div class="stat-item">
        <div class="label">Versions</div>
        <div class="value">{{ data.version_releases|length + 1 }}</div>
    </div>
</div>

{% if data.history %}
<div class="chart-container">
    <h3>Downloads Over Time</h3>
    <canvas id="dlChart" height="250"></canvas>
</div>
<div class="chart-container">
    <h3>Stars Over Time</h3>
    <canvas id="starsChart" height="200"></canvas>
</div>
{% endif %}

{% if data.version_releases %}
<h3>Version Releases</h3>
<table>
    <thead><tr><th>Version</th><th>Date</th><th>Changelog</th></tr></thead>
    <tbody>
    {% for v in data.version_releases|reverse %}
        <tr>
            <td>{{ v.version_number }}</td>
            <td>{{ v.run_date[:10] if v.run_date else "?" }}</td>
            <td>{{ v.changelog or "—" }}</td>
        </tr>
    {% endfor %}
    </tbody>
</table>
{% endif %}
{% endblock %}

{% block scripts %}
{% if data.history %}
<script>
const history = {{ data.history|tojson }};
const labels = history.map(h => h.run_date ? h.run_date.substring(0, 10) : '');
const dlData = history.map(h => h.downloads);
const starData = history.map(h => h.stars);

const chartOpts = (color) => ({
    responsive: true, plugins: { legend: { display: false }},
    scales: {
        x: { ticks: { color: '#a6adc8', maxRotation: 45 }, grid: { color: '#313244' }},
        y: { ticks: { color: '#a6adc8' }, grid: { color: '#313244' }}
    }
});

new Chart(document.getElementById('dlChart'), {
    type: 'line',
    data: { labels, datasets: [{ data: dlData, borderColor: '#89b4fa', borderWidth: 2, fill: false, tension: 0.3, pointRadius: 2 }]},
    options: chartOpts('#89b4fa')
});
new Chart(document.getElementById('starsChart'), {
    type: 'line',
    data: { labels, datasets: [{ data: starData, borderColor: '#f9e2af', borderWidth: 2, fill: false, tension: 0.3, pointRadius: 2 }]},
    options: chartOpts('#f9e2af')
});
</script>
{% endif %}
{% endblock %}
```

- [ ] **Step 6: Create owner_detail.html**

Create `app/templates/owner_detail.html`:

```html
{% extends "base.html" %}
{% block title %}{{ data.handle }} — ClawHub Tracker{% endblock %}

{% block content %}
<div class="detail-header">
    <h1>{{ data.handle }}</h1>
    <p class="meta">{{ data.skill_count }} skills &middot; {{ "{:,}".format(data.total_downloads) }} total downloads &middot; {{ data.avg_dl_per_day }} avg DL/day</p>
</div>

<div class="stat-grid">
    <div class="stat-item">
        <div class="label">Total Downloads</div>
        <div class="value">{{ "{:,}".format(data.total_downloads) }}</div>
    </div>
    <div class="stat-item">
        <div class="label">Skills</div>
        <div class="value">{{ data.skill_count }}</div>
    </div>
    <div class="stat-item">
        <div class="label">Avg DL/day</div>
        <div class="value">{{ data.avg_dl_per_day }}</div>
    </div>
</div>

{% if data.download_trajectory|length > 1 %}
<div class="chart-container">
    <h3>Combined Download Trajectory</h3>
    <canvas id="trajChart" height="250"></canvas>
</div>
{% endif %}

<h3>Skills</h3>
<ul class="skill-list">
{% for s in data.skills %}
    <li>
        <a href="{{ static_prefix }}skills/{{ s.slug }}.html">{{ s.display_name }}</a>
        <span class="stats">{{ "{:,}".format(s.stat_downloads) }} DL &middot; {{ s.stat_stars }} &#9733;</span>
    </li>
{% endfor %}
</ul>
{% endblock %}

{% block scripts %}
{% if data.download_trajectory|length > 1 %}
<script>
const traj = {{ data.download_trajectory|tojson }};
new Chart(document.getElementById('trajChart'), {
    type: 'line',
    data: { labels: traj.map((_, i) => 'Run ' + (i + 1)), datasets: [{
        data: traj, borderColor: '#a6e3a1', borderWidth: 2, fill: false, tension: 0.3, pointRadius: 2
    }]},
    options: {
        responsive: true, plugins: { legend: { display: false }},
        scales: {
            x: { ticks: { color: '#a6adc8' }, grid: { color: '#313244' }},
            y: { ticks: { color: '#a6adc8' }, grid: { color: '#313244' }}
        }
    }
});
</script>
{% endif %}
{% endblock %}
```

- [ ] **Step 7: Commit all templates**

```bash
git add app/templates/
git commit -m "Add all page templates: dashboard, rising, leaderboard, cohorts, detail pages"
```

---

### Task 10: site_html.py — Jinja2 rendering module

**Files:**
- Create: `app/site_html.py`

- [ ] **Step 1: Create site_html.py**

Create `app/site_html.py`:

```python
"""Jinja2 template rendering for the static site."""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from loguru import logger

TEMPLATES_DIR = Path(__file__).parent / "templates"


def _get_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=True,
    )


def render_dashboard(data: dict) -> str:
    env = _get_env()
    tmpl = env.get_template("dashboard.html")
    return tmpl.render(data=data, active_page="dashboard",
                       static_prefix="", generated_at=data.get("generated_at", ""))


def render_rising(data: dict) -> str:
    env = _get_env()
    tmpl = env.get_template("rising.html")
    return tmpl.render(data=data, active_page="rising",
                       static_prefix="", generated_at=data.get("generated_at", ""))


def render_leaderboard(data: dict) -> str:
    env = _get_env()
    tmpl = env.get_template("leaderboard.html")
    return tmpl.render(data=data, active_page="leaderboard",
                       static_prefix="", generated_at=data.get("generated_at", ""))


def render_cohorts(data: dict) -> str:
    env = _get_env()
    tmpl = env.get_template("cohorts.html")
    return tmpl.render(data=data, active_page="cohorts",
                       static_prefix="", generated_at=data.get("generated_at", ""))


def render_skill_detail(data: dict) -> str:
    env = _get_env()
    tmpl = env.get_template("skill_detail.html")
    return tmpl.render(data=data, active_page="",
                       static_prefix="../", generated_at=data.get("generated_at", ""))


def render_owner_detail(data: dict) -> str:
    env = _get_env()
    tmpl = env.get_template("owner_detail.html")
    return tmpl.render(data=data, active_page="",
                       static_prefix="../", generated_at=data.get("generated_at", ""))
```

- [ ] **Step 2: Run ruff and commit**

```bash
.venv/bin/ruff check app/site_html.py
.venv/bin/ruff format app/site_html.py
git add app/site_html.py
git commit -m "Add site_html.py rendering module"
```

---

### Task 11: site.py — orchestrator

**Files:**
- Create: `app/site.py`

- [ ] **Step 1: Create site.py**

Create `app/site.py`:

```python
"""Static site generator orchestrator.

Usage: python -m app.site [--db PATH] [--out DIR]
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

from loguru import logger

from app.site_data import (
    api_index,
    cohorts_data,
    dashboard_data,
    leaderboard_data,
    owner_detail_data,
    rising_data,
    skill_detail_data,
    top_owners_for_detail,
    top_skills_for_detail,
)
from app.site_html import (
    render_cohorts,
    render_dashboard,
    render_leaderboard,
    render_owner_detail,
    render_rising,
    render_skill_detail,
)
from app.storage import get_connection, init_schema

DEFAULT_BUILD_DIR = Path(__file__).parent.parent / "build"
STATIC_DIR = Path(__file__).parent / "static"


def _sanitize_handle(handle: str) -> str:
    """Sanitize owner handle for filesystem/URL safety."""
    return re.sub(r"[^a-z0-9_-]", "-", handle.lower())


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    logger.debug("[SITE] Wrote {}", path)


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    logger.debug("[SITE] Wrote {}", path)


def generate(db_path: str | Path | None = None, build_dir: Path | None = None) -> None:
    """Generate the full static site."""
    build_dir = build_dir or DEFAULT_BUILD_DIR
    logger.info("[SITE] Starting site generation to {}", build_dir)

    conn = get_connection(db_path)
    init_schema(conn)

    # Check for completed runs
    run = conn.execute(
        "SELECT id FROM scrape_runs WHERE status = 'completed' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if run is None:
        logger.warning("[SITE] No completed runs found — skipping generation")
        conn.close()
        return

    # Wipe and recreate build directory
    if build_dir.exists():
        shutil.rmtree(build_dir)
    build_dir.mkdir(parents=True)

    # Copy static assets
    static_dest = build_dir / "static"
    if STATIC_DIR.exists():
        shutil.copytree(STATIC_DIR, static_dest)

    # --- Generate pages + JSON ---
    # Dashboard
    logger.info("[SITE] Generating dashboard")
    dash = dashboard_data(conn)
    _write(build_dir / "index.html", render_dashboard(dash))
    _write_json(build_dir / "api" / "dashboard.json", dash)

    # Rising
    logger.info("[SITE] Generating rising skills")
    rising = rising_data(conn)
    _write(build_dir / "rising.html", render_rising(rising))
    _write_json(build_dir / "api" / "rising.json", rising)

    # Leaderboard
    logger.info("[SITE] Generating leaderboard")
    lb = leaderboard_data(conn)
    _write(build_dir / "leaderboard.html", render_leaderboard(lb))
    _write_json(build_dir / "api" / "leaderboard.json", lb)

    # Cohorts
    logger.info("[SITE] Generating cohorts")
    cohorts = cohorts_data(conn)
    _write(build_dir / "cohorts.html", render_cohorts(cohorts))
    _write_json(build_dir / "api" / "cohorts.json", cohorts)

    # Skill detail pages
    skill_slugs = top_skills_for_detail(conn)
    logger.info("[SITE] Generating {} skill detail pages", len(skill_slugs))
    for slug in skill_slugs:
        detail = skill_detail_data(conn, slug)
        if detail:
            _write(build_dir / "skills" / f"{slug}.html", render_skill_detail(detail))
            _write_json(build_dir / "api" / "skills" / f"{slug}.json", detail)

    # Owner detail pages
    owner_handles = top_owners_for_detail(conn)
    sanitized_handles = []
    logger.info("[SITE] Generating {} owner detail pages", len(owner_handles))
    for handle in owner_handles:
        detail = owner_detail_data(conn, handle)
        if detail:
            safe = _sanitize_handle(handle)
            sanitized_handles.append(safe)
            _write(build_dir / "owners" / f"{safe}.html", render_owner_detail(detail))
            _write_json(build_dir / "api" / "owners" / f"{safe}.json", detail)

    # API index
    idx = api_index(skill_slugs, sanitized_handles)
    _write_json(build_dir / "api" / "index.json", idx)

    conn.close()
    logger.info("[SITE] Site generation complete — {} files", _count_files(build_dir))


def _count_files(path: Path) -> int:
    return sum(1 for _ in path.rglob("*") if _.is_file())


if __name__ == "__main__":
    db_path = None
    build_dir = None
    args = sys.argv[1:]
    for i, arg in enumerate(args):
        if arg == "--db" and i + 1 < len(args):
            db_path = args[i + 1]
        elif arg == "--out" and i + 1 < len(args):
            build_dir = Path(args[i + 1])
    generate(db_path=db_path, build_dir=build_dir)
```

- [ ] **Step 2: Run ruff**

Run: `.venv/bin/ruff check app/site.py && .venv/bin/ruff format app/site.py`

- [ ] **Step 3: Test locally with the real database**

Run: `.venv/bin/python -m app.site`
Expected: Generates `build/` with HTML + JSON files, no errors. Check output:
Run: `ls build/` and `ls build/api/`

- [ ] **Step 4: Run all unit tests to confirm nothing broken**

Run: `.venv/bin/pytest tests/unit -v`
Expected: All existing + new tests pass

- [ ] **Step 5: Commit**

```bash
git add app/site.py
git commit -m "Add site.py orchestrator for static site generation"
```

---

### Task 12: Pipeline integration (Earthfile, docker-compose, crontab)

**Files:**
- Modify: `Earthfile`
- Modify: `crontab`
- Modify: `docker-compose.yml`

- [ ] **Step 1: Add +site target to Earthfile**

Add after the `scrape` target in `Earthfile`:

```
site:
    FROM +src
    COPY data/clawhub.duckdb data/clawhub.duckdb
    RUN .venv/bin/python -m app.site
    SAVE ARTIFACT build/ AS LOCAL build/
```

- [ ] **Step 2: Update crontab**

Replace `crontab` contents with:

```
# Run scraper daily at 03:00 UTC
0 3 * * * /app/.venv/bin/python -m app.scraper
# Generate static site at 03:15 UTC
15 3 * * * /app/.venv/bin/python -m app.site
```

- [ ] **Step 3: Add build volume to docker-compose.yml**

Add `./build:/app/build` volume mount to the scheduler service so generated site files are accessible from the host:

```yaml
  scheduler:
    build:
      # ... existing config unchanged ...
    init: true
    volumes:
      - ./data:/app/data
      - ./build:/app/build
    restart: unless-stopped
```

- [ ] **Step 4: Commit**

```bash
git add Earthfile crontab docker-compose.yml
git commit -m "Add site generation to Earthfile, crontab, and docker-compose"
```

---

### Task 13: Final verification

- [ ] **Step 1: Run full test suite**

Run: `.venv/bin/pytest tests/unit -v`
Expected: All tests pass (existing report tests + new site_data tests)

- [ ] **Step 2: Run ruff on everything**

Run: `.venv/bin/ruff check . && .venv/bin/ruff format --check .`
Expected: No issues

- [ ] **Step 3: Generate site with real data**

Run: `.venv/bin/python -m app.site`
Expected: `build/` directory populated with all HTML + JSON files

- [ ] **Step 4: Verify generated files**

Run: `ls -la build/` and `ls -la build/api/`
Expected: index.html, rising.html, leaderboard.html, cohorts.html, skills/, owners/, api/

- [ ] **Step 5: Quick smoke test — open in browser**

Run: `cd /home/pontsoul/code/lab/clawhub-tracker/build && python -m http.server 8080`
Open `http://localhost:8080` in browser. Verify:
- Dashboard loads with KPI cards and growth table
- Rising page shows skill list with velocity charts
- Leaderboard tabs work
- Cohorts page shows percentile table and box plot
- Click a skill → detail page with charts
- JSON API endpoints accessible

- [ ] **Step 6: Final commit**

```bash
git add -A
git commit -m "Complete ClawHub Tracker static website generator"
```
