"""Generate analytics report from ClawHub DuckDB data."""

from __future__ import annotations

import duckdb
from loguru import logger

from app.storage import DEFAULT_DB_PATH, get_connection, init_schema


def _header(title: str) -> str:
    return f"\n{'=' * 60}\n  {title}\n{'=' * 60}"


def platform_totals(conn: duckdb.DuckDBPyConnection) -> str:
    r = conn.execute("""
        SELECT COUNT(*) as skills, SUM(stat_downloads), SUM(stat_stars),
               SUM(stat_comments), SUM(stat_installs_all_time),
               COUNT(DISTINCT owner_handle)
        FROM current_skills
    """).fetchone()
    return (
        _header("PLATFORM TOTALS")
        + f"\n  Skills:      {r[0]:>10,}"
        + f"\n  Downloads:   {r[1]:>10,}"
        + f"\n  Stars:       {r[2]:>10,}"
        + f"\n  Comments:    {r[3]:>10,}"
        + f"\n  Installs:    {r[4]:>10,}"
        + f"\n  Owners:      {r[5]:>10,}"
    )


def top_by_downloads(conn: duckdb.DuckDBPyConnection, limit: int = 15) -> str:
    rows = conn.execute(
        """
        SELECT display_name, owner_handle, stat_downloads, stat_stars,
               stat_installs_all_time, stat_versions
        FROM current_skills ORDER BY stat_downloads DESC LIMIT ?
    """,
        [limit],
    ).fetchall()
    lines = [_header(f"TOP {limit} SKILLS BY DOWNLOADS")]
    lines.append(
        f"  {'Skill':<32} {'Owner':<18} {'Downloads':>10} {'Stars':>6} {'Installs':>8} {'Ver':>4}"
    )
    lines.append("  " + "-" * 84)
    for r in rows:
        lines.append(
            f"  {(r[0] or '?'):<32} {(r[1] or '?'):<18} {r[2]:>10,} {r[3]:>6,} {r[4]:>8,} {r[5]:>4}"
        )
    return "\n".join(lines)


def top_by_stars(conn: duckdb.DuckDBPyConnection, limit: int = 15) -> str:
    rows = conn.execute(
        """
        SELECT display_name, owner_handle, stat_stars, stat_downloads
        FROM current_skills ORDER BY stat_stars DESC LIMIT ?
    """,
        [limit],
    ).fetchall()
    lines = [_header(f"TOP {limit} SKILLS BY STARS")]
    lines.append(f"  {'Skill':<35} {'Owner':<20} {'Stars':>6} {'Downloads':>10}")
    lines.append("  " + "-" * 75)
    for r in rows:
        lines.append(f"  {(r[0] or '?'):<35} {(r[1] or '?'):<20} {r[2]:>6,} {r[3]:>10,}")
    return "\n".join(lines)


def owner_leaderboard(conn: duckdb.DuckDBPyConnection, limit: int = 15) -> str:
    rows = conn.execute(
        """
        SELECT owner_handle, COUNT(*) as skills,
               SUM(stat_downloads), SUM(stat_stars), SUM(stat_installs_all_time)
        FROM current_skills WHERE owner_handle IS NOT NULL
        GROUP BY owner_handle ORDER BY SUM(stat_downloads) DESC LIMIT ?
    """,
        [limit],
    ).fetchall()
    lines = [_header(f"TOP {limit} OWNERS BY DOWNLOADS")]
    lines.append(f"  {'Owner':<25} {'Skills':>6} {'Downloads':>12} {'Stars':>7} {'Installs':>9}")
    lines.append("  " + "-" * 63)
    for r in rows:
        lines.append(f"  {r[0]:<25} {r[1]:>6} {r[2]:>12,} {r[3]:>7,} {r[4]:>9,}")
    return "\n".join(lines)


def prolific_owners(conn: duckdb.DuckDBPyConnection, limit: int = 10) -> str:
    rows = conn.execute(
        """
        SELECT owner_handle, COUNT(*) as skills, SUM(stat_downloads)
        FROM current_skills WHERE owner_handle IS NOT NULL
        GROUP BY owner_handle ORDER BY skills DESC LIMIT ?
    """,
        [limit],
    ).fetchall()
    lines = [_header("MOST PROLIFIC OWNERS (by skill count)")]
    lines.append(f"  {'Owner':<25} {'Skills':>6} {'Total Downloads':>15}")
    lines.append("  " + "-" * 50)
    for r in rows:
        lines.append(f"  {r[0]:<25} {r[1]:>6} {r[2]:>15,}")
    return "\n".join(lines)


def download_distribution(conn: duckdb.DuckDBPyConnection) -> str:
    rows = conn.execute("""
        SELECT
            CASE
                WHEN stat_downloads = 0 THEN '0'
                WHEN stat_downloads BETWEEN 1 AND 10 THEN '1-10'
                WHEN stat_downloads BETWEEN 11 AND 100 THEN '11-100'
                WHEN stat_downloads BETWEEN 101 AND 1000 THEN '101-1K'
                WHEN stat_downloads BETWEEN 1001 AND 10000 THEN '1K-10K'
                WHEN stat_downloads BETWEEN 10001 AND 100000 THEN '10K-100K'
                ELSE '100K+'
            END as bucket,
            COUNT(*) as count,
            ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM current_skills), 1)
        FROM current_skills
        GROUP BY bucket
        ORDER BY MIN(stat_downloads)
    """).fetchall()
    lines = [_header("DOWNLOAD DISTRIBUTION")]
    for r in rows:
        bar = "#" * int(r[2])
        lines.append(f"  {r[0]:<10} {r[1]:>6} ({r[2]:>5.1f}%) {bar}")
    return "\n".join(lines)


def star_distribution(conn: duckdb.DuckDBPyConnection) -> str:
    rows = conn.execute("""
        SELECT
            CASE
                WHEN stat_stars = 0 THEN '0'
                WHEN stat_stars BETWEEN 1 AND 5 THEN '1-5'
                WHEN stat_stars BETWEEN 6 AND 20 THEN '6-20'
                WHEN stat_stars BETWEEN 21 AND 100 THEN '21-100'
                WHEN stat_stars BETWEEN 101 AND 500 THEN '101-500'
                ELSE '500+'
            END as bucket,
            COUNT(*) as count,
            ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM current_skills), 1)
        FROM current_skills
        GROUP BY bucket
        ORDER BY MIN(stat_stars)
    """).fetchall()
    lines = [_header("STAR DISTRIBUTION")]
    for r in rows:
        bar = "#" * int(r[2])
        lines.append(f"  {r[0]:<10} {r[1]:>6} ({r[2]:>5.1f}%) {bar}")
    return "\n".join(lines)


def best_star_ratio(conn: duckdb.DuckDBPyConnection, limit: int = 10) -> str:
    rows = conn.execute(
        """
        SELECT display_name, owner_handle, stat_downloads, stat_stars,
               ROUND(stat_stars * 100.0 / stat_downloads, 2)
        FROM current_skills
        WHERE stat_downloads >= 100
        ORDER BY stat_stars * 1.0 / stat_downloads DESC LIMIT ?
    """,
        [limit],
    ).fetchall()
    lines = [_header("BEST STAR-TO-DOWNLOAD RATIO (min 100 downloads)")]
    lines.append(f"  {'Skill':<30} {'Owner':<18} {'Downloads':>9} {'Stars':>6} {'Rate%':>7}")
    lines.append("  " + "-" * 74)
    for r in rows:
        lines.append(
            f"  {(r[0] or '?'):<30} {(r[1] or '?'):<18} {r[2]:>9,} {r[3]:>6,} {r[4]:>7.2f}"
        )
    return "\n".join(lines)


def install_conversion(conn: duckdb.DuckDBPyConnection, limit: int = 15) -> str:
    rows = conn.execute(
        """
        SELECT display_name, stat_downloads, stat_installs_all_time,
               ROUND(stat_installs_all_time * 100.0 / stat_downloads, 2)
        FROM current_skills
        WHERE stat_downloads > 0
        ORDER BY stat_downloads DESC LIMIT ?
    """,
        [limit],
    ).fetchall()
    lines = [_header(f"INSTALL CONVERSION (top {limit} by downloads)")]
    lines.append(f"  {'Skill':<35} {'Downloads':>10} {'Installs':>9} {'Conv%':>7}")
    lines.append("  " + "-" * 65)
    for r in rows:
        lines.append(f"  {(r[0] or '?'):<35} {r[1]:>10,} {r[2]:>9,} {r[3]:>7.2f}")
    return "\n".join(lines)


def most_versions(conn: duckdb.DuckDBPyConnection, limit: int = 10) -> str:
    rows = conn.execute(
        """
        SELECT display_name, owner_handle, stat_versions, stat_downloads, stat_stars
        FROM current_skills
        ORDER BY stat_versions DESC LIMIT ?
    """,
        [limit],
    ).fetchall()
    lines = [_header("MOST ACTIVELY MAINTAINED (by version count)")]
    lines.append(f"  {'Skill':<30} {'Owner':<18} {'Versions':>8} {'Downloads':>10} {'Stars':>6}")
    lines.append("  " + "-" * 76)
    for r in rows:
        lines.append(f"  {(r[0] or '?'):<30} {(r[1] or '?'):<18} {r[2]:>8} {r[3]:>10,} {r[4]:>6,}")
    return "\n".join(lines)


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


def generate_report(db_path: str | None = None) -> str:
    """Generate full analytics report."""
    conn = get_connection(db_path or DEFAULT_DB_PATH)
    init_schema(conn)

    sections = [
        platform_totals(conn),
        top_by_downloads(conn),
        top_by_stars(conn),
        owner_leaderboard(conn),
        prolific_owners(conn),
        download_distribution(conn),
        star_distribution(conn),
        best_star_ratio(conn),
        install_conversion(conn),
        most_versions(conn),
    ]

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
