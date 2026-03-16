"""Pre-built analytics queries for ClawHub skill data."""

from __future__ import annotations

import duckdb
from loguru import logger


def top_skills_by_downloads(
    conn: duckdb.DuckDBPyConnection,
    limit: int = 20,
) -> list[dict]:
    """Top skills by download count from the latest completed run."""
    rows = conn.execute(
        """
        SELECT skill_id, slug, display_name, owner_handle, stat_downloads, stat_stars
        FROM current_skills
        ORDER BY stat_downloads DESC
        LIMIT ?
        """,
        [limit],
    ).fetchall()
    logger.info("[ANALYTICS] Top {n} skills by downloads", n=len(rows))
    return [
        {
            "skill_id": r[0],
            "slug": r[1],
            "display_name": r[2],
            "owner_handle": r[3],
            "stat_downloads": r[4],
            "stat_stars": r[5],
        }
        for r in rows
    ]


def top_skills_by_stars(
    conn: duckdb.DuckDBPyConnection,
    limit: int = 20,
) -> list[dict]:
    """Top skills by star count from the latest completed run."""
    rows = conn.execute(
        """
        SELECT skill_id, slug, display_name, owner_handle, stat_stars, stat_downloads
        FROM current_skills
        ORDER BY stat_stars DESC
        LIMIT ?
        """,
        [limit],
    ).fetchall()
    logger.info("[ANALYTICS] Top {n} skills by stars", n=len(rows))
    return [
        {
            "skill_id": r[0],
            "slug": r[1],
            "display_name": r[2],
            "owner_handle": r[3],
            "stat_stars": r[4],
            "stat_downloads": r[5],
        }
        for r in rows
    ]


def download_growth(
    conn: duckdb.DuckDBPyConnection,
    limit: int = 20,
) -> list[dict]:
    """Skills with the most download growth between the two latest runs."""
    rows = conn.execute(
        """
        SELECT
            c.skill_id,
            c.slug,
            c.display_name,
            c.owner_handle,
            p.stat_downloads AS prev_downloads,
            c.stat_downloads AS curr_downloads,
            (c.stat_downloads - p.stat_downloads) AS growth
        FROM current_skills c
        JOIN previous_skills p ON c.skill_id = p.skill_id
        WHERE c.stat_downloads > p.stat_downloads
        ORDER BY growth DESC
        LIMIT ?
        """,
        [limit],
    ).fetchall()
    logger.info("[ANALYTICS] Download growth leaders: {n}", n=len(rows))
    return [
        {
            "skill_id": r[0],
            "slug": r[1],
            "display_name": r[2],
            "owner_handle": r[3],
            "prev_downloads": r[4],
            "curr_downloads": r[5],
            "growth": r[6],
        }
        for r in rows
    ]


def owner_leaderboard(
    conn: duckdb.DuckDBPyConnection,
    limit: int = 20,
) -> list[dict]:
    """Owners ranked by total downloads across all their skills."""
    rows = conn.execute(
        """
        SELECT
            owner_handle,
            COUNT(*) AS skill_count,
            SUM(stat_downloads) AS total_downloads,
            SUM(stat_stars) AS total_stars
        FROM current_skills
        WHERE owner_handle IS NOT NULL
        GROUP BY owner_handle
        ORDER BY total_downloads DESC
        LIMIT ?
        """,
        [limit],
    ).fetchall()
    logger.info("[ANALYTICS] Owner leaderboard: {n} entries", n=len(rows))
    return [
        {
            "owner_handle": r[0],
            "skill_count": r[1],
            "total_downloads": r[2],
            "total_stars": r[3],
        }
        for r in rows
    ]


def platform_totals(conn: duckdb.DuckDBPyConnection) -> dict:
    """Aggregate platform-wide totals from the latest completed run."""
    row = conn.execute(
        """
        SELECT
            COUNT(*) AS total_skills,
            COALESCE(SUM(stat_downloads), 0) AS total_downloads,
            COALESCE(SUM(stat_stars), 0) AS total_stars,
            COALESCE(SUM(stat_comments), 0) AS total_comments,
            COALESCE(SUM(stat_installs_all_time), 0) AS total_installs,
            COUNT(DISTINCT owner_handle) AS unique_owners
        FROM current_skills
        """
    ).fetchone()
    logger.info("[ANALYTICS] Platform totals computed")
    return {
        "total_skills": row[0],
        "total_downloads": row[1],
        "total_stars": row[2],
        "total_comments": row[3],
        "total_installs": row[4],
        "unique_owners": row[5],
    }
