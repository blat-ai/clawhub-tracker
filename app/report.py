"""Generate analytics report from ClawHub DuckDB data."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import duckdb
from loguru import logger

from app.storage import DEFAULT_DB_PATH, get_connection, init_schema


def _header(title: str) -> str:
    return f"\n{'=' * 60}\n  {title}\n{'=' * 60}"


# ---------------------------------------------------------------------------
# 1. Platform Snapshot
# ---------------------------------------------------------------------------


def platform_snapshot(conn: duckdb.DuckDBPyConnection) -> str:
    totals = conn.execute("""
        SELECT COUNT(*) as skills,
               COALESCE(SUM(stat_downloads), 0),
               COALESCE(SUM(stat_stars), 0),
               COALESCE(SUM(stat_installs_all_time), 0),
               COUNT(DISTINCT owner_handle)
        FROM current_skills
    """).fetchone()

    total_dl = totals[1]
    top1 = conn.execute("""
        WITH ranked AS (
            SELECT stat_downloads,
                   NTILE(100) OVER (ORDER BY stat_downloads DESC) AS pct
            FROM current_skills
        )
        SELECT SUM(stat_downloads) FROM ranked WHERE pct = 1
    """).fetchone()[0] or 0

    top10 = conn.execute("""
        WITH ranked AS (
            SELECT stat_downloads,
                   NTILE(10) OVER (ORDER BY stat_downloads DESC) AS pct
            FROM current_skills
        )
        SELECT SUM(stat_downloads) FROM ranked WHERE pct = 1
    """).fetchone()[0] or 0

    pct1 = (top1 / total_dl * 100) if total_dl else 0
    pct10 = (top10 / total_dl * 100) if total_dl else 0

    lines = [_header("PLATFORM SNAPSHOT")]
    lines.append(f"  Skills:      {totals[0]:>10,}")
    lines.append(f"  Downloads:   {totals[1]:>10,}")
    lines.append(f"  Stars:       {totals[2]:>10,}")
    lines.append(f"  Installs:    {totals[3]:>10,}")
    lines.append(f"  Owners:      {totals[4]:>10,}")
    lines.append("")
    lines.append(f"  Top 1% captures {pct1:.0f}% of downloads")
    lines.append(f"  Top 10% captures {pct10:.0f}% of downloads")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 2. Platform Growth Timeline
# ---------------------------------------------------------------------------


def growth_timeline(conn: duckdb.DuckDBPyConnection) -> str:
    rows = conn.execute("""
        SELECT
            DATE_TRUNC('week', created_at) AS week_start,
            COUNT(*) AS new_skills
        FROM current_skills
        WHERE created_at IS NOT NULL
        GROUP BY week_start
        ORDER BY week_start
    """).fetchall()

    if not rows:
        return _header("PLATFORM GROWTH TIMELINE") + "\n  No created_at data available."

    max_new = max(r[1] for r in rows)
    bar_scale = 50 / max_new if max_new else 1

    lines = [_header("PLATFORM GROWTH TIMELINE")]
    cumulative = 0
    prev_count = None
    for week_start, new_count in rows:
        cumulative += new_count
        iso_week = week_start.strftime("%Y-W%W")
        bar = "\u2588" * max(1, int(new_count * bar_scale))
        if prev_count and prev_count > 0:
            wow = (new_count - prev_count) / prev_count * 100
            wow_str = f"{wow:>+6.0f}%"
        else:
            wow_str = "      "
        lines.append(
            f"  {iso_week}  {new_count:>5} new  {wow_str}"
            f"  cum: {cumulative:>6,}  {bar}"
        )
        prev_count = new_count
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 3. Cohort Quality Analysis
# ---------------------------------------------------------------------------


def cohort_quality(conn: duckdb.DuckDBPyConnection) -> str:
    rows = conn.execute("""
        SELECT
            DATE_TRUNC('month', created_at) AS month,
            COUNT(*) AS skills,
            ROUND(AVG(stat_downloads), 0) AS avg_dl,
            ROUND(AVG(stat_stars), 1) AS avg_stars,
            ROUND(
                CASE WHEN SUM(stat_downloads) > 0
                     THEN SUM(stat_installs_all_time) * 100.0 / SUM(stat_downloads)
                     ELSE 0 END, 1
            ) AS install_pct
        FROM current_skills
        WHERE created_at IS NOT NULL
        GROUP BY month
        ORDER BY month
    """).fetchall()

    if not rows:
        return _header("COHORT QUALITY ANALYSIS") + "\n  No created_at data available."

    lines = [_header("COHORT QUALITY ANALYSIS")]
    lines.append(
        f"  {'Cohort':<12} {'Skills':>6} {'Avg DL':>10} {'Avg Stars':>10} {'Install%':>9}"
    )
    lines.append("  " + "-" * 51)
    for month, skills, avg_dl, avg_stars, install_pct in rows:
        label = month.strftime("%Y-%m")
        lines.append(
            f"  {label:<12} {skills:>6,} {avg_dl:>10,.0f} {avg_stars:>10.1f} {install_pct:>8.1f}%"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 4. Hot New Skills (last 30 days)
# ---------------------------------------------------------------------------


def hot_new_skills(
    conn: duckdb.DuckDBPyConnection,
    limit: int = 10,
    now: datetime | None = None,
) -> str:
    if now is None:
        now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=30)

    rows = conn.execute(
        """
        SELECT display_name, owner_handle, stat_downloads, stat_stars,
               stat_installs_all_time, created_at
        FROM current_skills
        WHERE created_at IS NOT NULL AND created_at >= ?
        ORDER BY stat_downloads DESC
        LIMIT ?
    """,
        [cutoff, limit],
    ).fetchall()

    lines = [_header("HOT NEW SKILLS (last 30 days)")]
    if not rows:
        lines.append("  No skills created in the last 30 days.")
        return "\n".join(lines)

    lines.append(
        f"  {'Skill':<30} {'Owner':<16} {'Downloads':>10} {'Stars':>6} {'Created':>12}"
    )
    lines.append("  " + "-" * 78)
    for r in rows:
        created = r[5].strftime("%Y-%m-%d") if r[5] else "?"
        lines.append(
            f"  {(r[0] or '?'):<30} {(r[1] or '?'):<16} {r[2]:>10,} {r[3]:>6,} {created:>12}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 5. Top 10 Skills
# ---------------------------------------------------------------------------


def top_skills(conn: duckdb.DuckDBPyConnection, limit: int = 10) -> str:
    rows = conn.execute(
        """
        SELECT display_name, owner_handle, stat_downloads, stat_stars,
               stat_installs_all_time, stat_versions
        FROM current_skills ORDER BY stat_downloads DESC LIMIT ?
    """,
        [limit],
    ).fetchall()
    lines = [_header(f"TOP {limit} SKILLS")]
    lines.append(
        f"  {'Skill':<30} {'Owner':<16} {'Downloads':>10} {'Stars':>6} {'Installs':>8} {'Ver':>4}"
    )
    lines.append("  " + "-" * 78)
    for r in rows:
        lines.append(
            f"  {(r[0] or '?'):<30} {(r[1] or '?'):<16} {r[2]:>10,} {r[3]:>6,} {r[4]:>8,} {r[5]:>4}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 6. Quality Signals
# ---------------------------------------------------------------------------


def quality_signals(conn: duckdb.DuckDBPyConnection, limit: int = 10) -> str:
    # Best star-to-download ratio (min 100 downloads)
    star_rows = conn.execute(
        """
        SELECT display_name, owner_handle, stat_downloads, stat_stars,
               ROUND(stat_stars * 100.0 / stat_downloads, 2) AS rate
        FROM current_skills
        WHERE stat_downloads >= 100
        ORDER BY stat_stars * 1.0 / stat_downloads DESC LIMIT ?
    """,
        [limit],
    ).fetchall()

    # Most actively maintained (by version count)
    version_rows = conn.execute(
        """
        SELECT display_name, owner_handle, stat_versions, stat_downloads
        FROM current_skills
        ORDER BY stat_versions DESC LIMIT ?
    """,
        [limit],
    ).fetchall()

    lines = [_header("QUALITY SIGNALS")]

    lines.append("\n  Best star-to-download ratio (min 100 downloads):")
    lines.append(
        f"  {'Skill':<30} {'Owner':<16} {'Downloads':>9} {'Stars':>6} {'Rate%':>7}"
    )
    lines.append("  " + "-" * 72)
    for r in star_rows:
        lines.append(
            f"  {(r[0] or '?'):<30} {(r[1] or '?'):<16} {r[2]:>9,} {r[3]:>6,} {r[4]:>7.2f}"
        )

    lines.append("\n  Most actively maintained (by version count):")
    lines.append(
        f"  {'Skill':<30} {'Owner':<16} {'Versions':>8} {'Downloads':>10}"
    )
    lines.append("  " + "-" * 68)
    for r in version_rows:
        lines.append(
            f"  {(r[0] or '?'):<30} {(r[1] or '?'):<16} {r[2]:>8} {r[3]:>10,}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 7. Owner Ecosystem
# ---------------------------------------------------------------------------


def owner_ecosystem(conn: duckdb.DuckDBPyConnection, limit: int = 10) -> str:
    # Top owners by downloads
    top_owners = conn.execute(
        """
        SELECT owner_handle, COUNT(*) as skills,
               SUM(stat_downloads) as total_dl
        FROM current_skills WHERE owner_handle IS NOT NULL
        GROUP BY owner_handle ORDER BY total_dl DESC LIMIT ?
    """,
        [limit],
    ).fetchall()

    # Suspected spam: >50 skills but <50 avg downloads
    spam = conn.execute("""
        SELECT owner_handle, COUNT(*) as skills,
               ROUND(AVG(stat_downloads), 0) as avg_dl
        FROM current_skills WHERE owner_handle IS NOT NULL
        GROUP BY owner_handle
        HAVING COUNT(*) > 50 AND AVG(stat_downloads) < 50
        ORDER BY skills DESC
    """).fetchall()

    lines = [_header("OWNER ECOSYSTEM")]

    lines.append(f"\n  {'Owner':<25} {'Skills':>6} {'Total Downloads':>15}")
    lines.append("  " + "-" * 50)
    for r in top_owners:
        lines.append(f"  {r[0]:<25} {r[1]:>6} {r[2]:>15,}")

    if spam:
        lines.append("\n  Suspected spam (>50 skills, <50 avg downloads):")
        lines.append(f"  {'Owner':<25} {'Skills':>6} {'Avg DL':>8}")
        lines.append("  " + "-" * 43)
        for r in spam:
            lines.append(f"  {r[0]:<25} {r[1]:>6} {r[2]:>8,.0f}")
    else:
        lines.append("\n  No suspected spam owners detected.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 8. Platform Velocity (across scrape runs)
# ---------------------------------------------------------------------------


def platform_velocity(conn: duckdb.DuckDBPyConnection) -> str | None:
    """Show download/skill totals across completed runs to reveal acceleration."""
    rows = conn.execute("""
        SELECT
            r.id,
            r.started_at,
            r.total_skills,
            COALESCE(SUM(s.stat_downloads), 0) AS total_dl,
            COALESCE(SUM(s.stat_stars), 0) AS total_stars
        FROM scrape_runs r
        JOIN skill_snapshots s ON s.scrape_run_id = r.id
        WHERE r.status = 'completed'
        GROUP BY r.id, r.started_at, r.total_skills
        ORDER BY r.id
    """).fetchall()

    if len(rows) < 2:
        return None

    lines = [_header("PLATFORM VELOCITY (across scrape runs)")]
    lines.append(
        f"  {'Run':>4} {'Date':<17} {'Skills':>7} {'Downloads':>12}"
        f" {'DL Delta':>10} {'DL/day':>10}"
    )
    lines.append("  " + "-" * 64)

    prev = None
    for run_id, started_at, total_skills, total_dl, _ in rows:
        date_str = started_at.strftime("%Y-%m-%d %H:%M")
        if prev is not None:
            dl_delta = total_dl - prev[1]
            days = max(
                (started_at - prev[0]).total_seconds() / 86400, 0.01
            )
            dl_per_day = dl_delta / days
            lines.append(
                f"  {run_id:>4} {date_str:<17} {total_skills:>7,}"
                f" {total_dl:>12,} {dl_delta:>+10,}"
                f" {dl_per_day:>+10,.0f}"
            )
        else:
            lines.append(
                f"  {run_id:>4} {date_str:<17} {total_skills:>7,}"
                f" {total_dl:>12,}{'':>10}{'':>10}"
            )
        prev = (started_at, total_dl)

    if len(rows) >= 3:
        first_dl = rows[0][3]
        last_dl = rows[-1][3]
        total_days = max(
            (rows[-1][1] - rows[0][1]).total_seconds() / 86400, 0.01
        )
        avg_dl_day = (last_dl - first_dl) / total_days
        lines.append(f"\n  Avg download velocity: {avg_dl_day:,.0f}/day"
                     f" over {total_days:.1f} days")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 9. Diff (unchanged logic)
# ---------------------------------------------------------------------------


def diff_summary(conn: duckdb.DuckDBPyConnection) -> str | None:
    """Show diff between two latest completed runs, if available."""
    runs = conn.execute("""
        SELECT id, started_at, total_skills, new_skills, removed_skills, changed_skills
        FROM scrape_runs WHERE status = 'completed'
        ORDER BY id DESC LIMIT 2
    """).fetchall()
    if len(runs) < 2:
        return None

    curr, prev = runs[0], runs[1]
    lines = [_header("CHANGES SINCE LAST SCRAPE")]
    lines.append(
        f"  Run {prev[0]} ({prev[1]:%Y-%m-%d %H:%M}) -> Run {curr[0]} ({curr[1]:%Y-%m-%d %H:%M})"
    )
    lines.append(f"  Skills: {prev[2]:,} -> {curr[2]:,}")
    lines.append(f"  New:     {curr[3]:>6,}")
    lines.append(f"  Removed: {curr[4]:>6,}")
    lines.append(f"  Changed: {curr[5]:>6,}")

    from app.diff import compute_diff

    diff = compute_diff(conn, curr[0], prev[0])

    if diff["new"]:
        lines.append("\n  New skills:")
        for s in diff["new"][:10]:
            lines.append(f"    + {s['display_name'] or s['slug']} (@{s['owner_handle']})")

    if diff["removed"]:
        lines.append("\n  Removed skills:")
        for s in diff["removed"][:10]:
            lines.append(f"    - {s['display_name'] or s['slug']} (@{s['owner_handle']})")

    if diff["changed"]:
        lines.append("\n  Top changes (by downloads):")
        for s in diff["changed"][:10]:
            changes_str = ", ".join(f"{k}: {v['from']}->{v['to']}" for k, v in s["changes"].items())
            lines.append(f"    ~ {s['display_name'] or s['slug']}: {changes_str}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Full report
# ---------------------------------------------------------------------------


def generate_report(db_path: str | None = None) -> str:
    """Generate full analytics report."""
    conn = get_connection(db_path or DEFAULT_DB_PATH)
    init_schema(conn)

    sections = [
        platform_snapshot(conn),
        growth_timeline(conn),
        cohort_quality(conn),
        hot_new_skills(conn),
        top_skills(conn),
        quality_signals(conn),
        owner_ecosystem(conn),
    ]

    velocity = platform_velocity(conn)
    if velocity:
        sections.append(velocity)

    diff = diff_summary(conn)
    if diff:
        sections.append(diff)

    conn.close()

    report = "\n".join(sections) + "\n"
    logger.info("[REPORT] Report generated")
    return report


def main():
    print(generate_report())


if __name__ == "__main__":
    main()
