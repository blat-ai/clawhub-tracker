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
            "download_percentiles": [],
            "download_wow_pct": None,
            "avg_wow_pct": None,
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
    current_week_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    # DuckDB DATE_TRUNC('week') uses Monday as week start
    current_week_start = current_week_start - timedelta(days=current_week_start.weekday())

    for week_start, new_count in weeks_raw:
        cumulative += new_count
        wow_pct = None
        is_forecast = False
        forecast_count = None

        # Detect current (incomplete) week and forecast
        ws = week_start if hasattr(week_start, "date") else None
        if ws and ws.date() >= current_week_start.date():
            days_elapsed = (now.date() - ws.date()).days + 1  # include today
            if days_elapsed < 7 and days_elapsed > 0:
                forecast_count = round(new_count / days_elapsed * 7)
                is_forecast = True

        effective_count = forecast_count if is_forecast else new_count
        if prev_count is not None and prev_count > 0:
            wow_pct = round((effective_count - prev_count) / prev_count * 100, 1)

        week_start_str = (
            week_start.isoformat() if hasattr(week_start, "isoformat") else str(week_start)
        )
        weekly_growth.append(
            {
                "week_start": week_start_str,
                "new_count": new_count,
                "cumulative": cumulative,
                "wow_pct": wow_pct,
                "is_forecast": is_forecast,
                "forecast_count": forecast_count,
            }
        )
        prev_count = effective_count

    # Keep last 12 weeks
    weekly_growth = weekly_growth[-12:]

    # Average WoW % (complete weeks only, excluding forecasted)
    complete_wow = [
        w["wow_pct"] for w in weekly_growth if w["wow_pct"] is not None and not w["is_forecast"]
    ]
    avg_wow_pct = round(sum(complete_wow) / len(complete_wow), 1) if complete_wow else None

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

    # Download WoW%: compare latest run total to ~7 runs ago
    download_wow_pct = None
    if len(download_sparkline) >= 2:
        latest_dl = download_sparkline[-1]
        # Use 7 runs back if available (daily scrapes = ~1 week), else earliest
        prev_idx = max(0, len(download_sparkline) - 8)
        prev_dl = download_sparkline[prev_idx]
        if prev_dl and prev_dl > 0:
            download_wow_pct = round((latest_dl - prev_dl) / prev_dl * 100, 1)

    # Download percentiles per completed run (P50, P90, P95, P99)
    pct_rows = conn.execute("""
        SELECT
            r.id,
            r.started_at,
            COUNT(*) as skill_count,
            PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY s.stat_downloads) as p50,
            PERCENTILE_CONT(0.90) WITHIN GROUP (ORDER BY s.stat_downloads) as p90,
            PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY s.stat_downloads) as p95,
            PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY s.stat_downloads) as p99
        FROM skill_snapshots s
        JOIN scrape_runs r ON s.scrape_run_id = r.id
        WHERE r.status = 'completed'
        GROUP BY r.id, r.started_at
        ORDER BY r.id
    """).fetchall()
    download_percentiles = []
    for row in pct_rows:
        run_date = row[1].isoformat()[:10] if row[1] else str(row[0])
        download_percentiles.append(
            {
                "run_date": run_date,
                "skill_count": row[2],
                "p50": round(float(row[3]), 0) if row[3] is not None else 0,
                "p90": round(float(row[4]), 0) if row[4] is not None else 0,
                "p95": round(float(row[5]), 0) if row[5] is not None else 0,
                "p99": round(float(row[6]), 0) if row[6] is not None else 0,
            }
        )

    return {
        "total_skills": totals[0],
        "total_downloads": totals[1],
        "total_stars": totals[2],
        "total_owners": totals[3],
        "weekly_growth": weekly_growth,
        "download_sparkline": download_sparkline,
        "download_percentiles": download_percentiles,
        "download_wow_pct": download_wow_pct,
        "avg_wow_pct": avg_wow_pct,
        "generated_at": now.isoformat(),
    }


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
    rows = conn.execute(
        """
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
    """,
        [now, prev_id, curr_id, cutoff, limit],
    ).fetchall()

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
        chart_rows = conn.execute(
            """
            SELECT scrape_run_id, stat_downloads
            FROM skill_snapshots
            WHERE skill_id = ? AND scrape_run_id IN ({})
            ORDER BY scrape_run_id
        """.format(",".join("?" * len(run_ids))),
            [skill_id] + run_ids,
        ).fetchall()
        velocity_chart = [r[1] for r in chart_rows]

        skills.append(
            {
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
            }
        )

    return {"skills": skills, "generated_at": now.isoformat()}


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
    recent_ids = run_ids[:3]  # last 3 runs
    prior_ids = run_ids[3:6]  # prior 3 runs

    all_time_rows = conn.execute(
        """
        SELECT skill_id, slug, display_name, owner_handle,
               stat_downloads, created_at
        FROM skill_snapshots
        WHERE scrape_run_id = ?
        ORDER BY stat_downloads DESC
        LIMIT ?
    """,
        [curr_id, limit],
    ).fetchall()

    all_time = []
    for row in all_time_rows:
        skill_id = row[0]
        vel_recent = _avg_velocity(conn, skill_id, recent_ids) if len(recent_ids) >= 2 else None
        vel_prior = _avg_velocity(conn, skill_id, prior_ids) if len(prior_ids) >= 2 else None
        trend = _compute_trend(vel_recent, vel_prior)
        all_time.append(
            {
                "skill_id": skill_id,
                "slug": row[1],
                "display_name": row[2],
                "owner_handle": row[3],
                "stat_downloads": row[4],
                "created_at": row[5].isoformat() if row[5] else None,
                "velocity": round(vel_recent, 1) if vel_recent is not None else None,
                "trend": trend,
            }
        )

    # --- Fastest growing by acceleration ---
    fastest_growing = []
    if len(run_ids) >= 4:
        # Get all skills with enough downloads
        candidates = conn.execute(
            """
            SELECT skill_id, slug, display_name, owner_handle,
                   stat_downloads, created_at
            FROM skill_snapshots
            WHERE scrape_run_id = ? AND stat_downloads >= ?
            ORDER BY stat_downloads DESC
        """,
            [curr_id, ACCEL_MIN_DOWNLOADS],
        ).fetchall()

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
                accel_list.append(
                    {
                        "skill_id": skill_id,
                        "slug": row[1],
                        "display_name": row[2],
                        "owner_handle": row[3],
                        "stat_downloads": row[4],
                        "created_at": row[5].isoformat() if row[5] else None,
                        "velocity": round(vel_recent, 1) if vel_recent else None,
                        "acceleration_pct": round(accel, 1),
                        "trend": _compute_trend(vel_recent, vel_prior),
                    }
                )

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
    rows = conn.execute(
        f"""
        SELECT stat_downloads
        FROM skill_snapshots
        WHERE skill_id = ? AND scrape_run_id IN ({placeholders})
        ORDER BY scrape_run_id
    """,
        [skill_id] + run_ids,
    ).fetchall()
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

    rows = conn.execute(
        """
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
    """,
        [now, now, now, now, now, now],
    ).fetchall()

    cohorts = []
    for row in rows:
        month_str = row[0].strftime("%Y-%m") if hasattr(row[0], "strftime") else str(row[0])[:7]
        total_dl = row[9] or 0
        star_dl_ratio = round(row[8] / total_dl, 4) if total_dl > 0 else 0.0
        cohorts.append(
            {
                "month": month_str,
                "skill_count": row[1],
                "p25": round(float(row[2]), 1),
                "p50": round(float(row[3]), 1),
                "p75": round(float(row[4]), 1),
                "p90": round(float(row[5]), 1),
                "p99": round(float(row[6]), 1),
                "avg_dl_per_day": round(float(row[7]), 1),
                "star_dl_ratio": star_dl_ratio,
            }
        )

    return {"cohorts": cohorts, "generated_at": now.isoformat()}


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
    meta = conn.execute(
        """
        SELECT display_name, summary, owner_handle, created_at,
               stat_downloads, stat_stars, tags
        FROM current_skills WHERE skill_id = ?
    """,
        [skill_id],
    ).fetchone()

    # History across all completed runs
    history_rows = conn.execute(
        """
        SELECT r.started_at, s.stat_downloads, s.stat_stars,
               s.stat_installs_all_time, s.stat_installs_current,
               s.version_number, s.version_changelog
        FROM skill_snapshots s
        JOIN scrape_runs r ON s.scrape_run_id = r.id
        WHERE s.skill_id = ? AND r.status = 'completed'
        ORDER BY r.id
    """,
        [skill_id],
    ).fetchall()

    history = []
    version_releases = []
    prev_version = None
    for h in history_rows:
        run_date = h[0].isoformat() if h[0] else None
        history.append(
            {
                "run_date": run_date,
                "downloads": h[1],
                "stars": h[2],
                "installs_all_time": h[3],
                "installs_current": h[4],
            }
        )
        # Detect version changes
        curr_version = h[5]
        if curr_version and curr_version != prev_version and prev_version is not None:
            version_releases.append(
                {
                    "version_number": curr_version,
                    "run_date": run_date,
                    "changelog": h[6],
                }
            )
        prev_version = curr_version

    # Compute velocity and acceleration
    created_at = meta[3]
    velocity = None
    if created_at:
        # Ensure created_at is timezone-aware
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
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
    summary = conn.execute(
        """
        SELECT
            SUM(stat_downloads) as total_downloads,
            COUNT(*) as skill_count,
            AVG(stat_downloads / GREATEST(DATE_DIFF('day', created_at, ?), 1))
                as avg_dl_per_day
        FROM current_skills
        WHERE owner_handle = ? AND created_at IS NOT NULL
    """,
        [now, handle],
    ).fetchone()

    # Individual skills
    skills_rows = conn.execute(
        """
        SELECT slug, display_name, stat_downloads, stat_stars, created_at
        FROM current_skills
        WHERE owner_handle = ?
        ORDER BY stat_downloads DESC
    """,
        [handle],
    ).fetchall()

    skills = [
        {
            "slug": r[0],
            "display_name": r[1],
            "stat_downloads": r[2],
            "stat_stars": r[3],
            "created_at": r[4].isoformat() if r[4] else None,
        }
        for r in skills_rows
    ]

    # Download trajectory across runs
    traj_rows = conn.execute(
        """
        SELECT r.id, SUM(s.stat_downloads) as total_dl
        FROM skill_snapshots s
        JOIN scrape_runs r ON s.scrape_run_id = r.id
        WHERE s.owner_handle = ? AND r.status = 'completed'
        GROUP BY r.id
        ORDER BY r.id
    """,
        [handle],
    ).fetchall()

    return {
        "handle": handle,
        "total_downloads": summary[0] or 0,
        "skill_count": summary[1],
        "avg_dl_per_day": round(float(summary[2]), 1) if summary[2] else 0.0,
        "skills": skills,
        "download_trajectory": [r[1] for r in traj_rows],
    }


# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------
def top_skills_for_detail(
    conn: duckdb.DuckDBPyConnection, limit: int = SKILL_DETAIL_LIMIT, now: datetime | None = None
) -> list[str]:
    """Slugs qualifying for detail page generation."""
    now = now or _now()
    logger.info("[SITE_DATA] Computing top skills for detail pages")
    rows = conn.execute(
        """
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
    """,
        [limit, now, SKILL_VELOCITY_LIMIT],
    ).fetchall()
    return [r[0] for r in rows]


def top_owners_for_detail(
    conn: duckdb.DuckDBPyConnection, limit: int = OWNER_DETAIL_LIMIT
) -> list[str]:
    """Handles qualifying for detail page generation."""
    logger.info("[SITE_DATA] Computing top owners for detail pages")
    rows = conn.execute(
        """
        SELECT owner_handle
        FROM current_skills
        WHERE owner_handle IS NOT NULL
        GROUP BY owner_handle
        ORDER BY SUM(stat_downloads) DESC
        LIMIT ?
    """,
        [limit],
    ).fetchall()
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
