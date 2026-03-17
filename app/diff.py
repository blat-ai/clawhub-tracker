"""SQL-based diff detection between consecutive scrape runs."""

from __future__ import annotations

import duckdb
from loguru import logger

TRACKED_FIELDS = [
    "stat_downloads",
    "stat_stars",
    "stat_comments",
    "stat_installs_all_time",
    "stat_installs_current",
    "stat_versions",
    "version_number",
    "version_id",
]


def new_skills(
    conn: duckdb.DuckDBPyConnection,
    current_run_id: int,
    previous_run_id: int,
) -> list[dict]:
    """Skills present in current run but not in previous."""
    rows = conn.execute(
        """
        SELECT c.skill_id, sk.slug, sk.display_name, sk.owner_handle, c.stat_downloads
        FROM skill_metrics c
        JOIN skills sk ON c.skill_id = sk.skill_id
        LEFT JOIN skill_metrics p
            ON c.skill_id = p.skill_id AND p.scrape_run_id = ?
        WHERE c.scrape_run_id = ? AND p.skill_id IS NULL
        ORDER BY c.stat_downloads DESC
        """,
        [previous_run_id, current_run_id],
    ).fetchall()
    logger.info("[DIFF] Found {count} new skills", count=len(rows))
    return [
        {
            "skill_id": r[0],
            "slug": r[1],
            "display_name": r[2],
            "owner_handle": r[3],
            "stat_downloads": r[4],
        }
        for r in rows
    ]


def removed_skills(
    conn: duckdb.DuckDBPyConnection,
    current_run_id: int,
    previous_run_id: int,
) -> list[dict]:
    """Skills present in previous run but not in current."""
    rows = conn.execute(
        """
        SELECT p.skill_id, sk.slug, sk.display_name, sk.owner_handle, p.stat_downloads
        FROM skill_metrics p
        JOIN skills sk ON p.skill_id = sk.skill_id
        LEFT JOIN skill_metrics c
            ON p.skill_id = c.skill_id AND c.scrape_run_id = ?
        WHERE p.scrape_run_id = ? AND c.skill_id IS NULL
        ORDER BY p.stat_downloads DESC
        """,
        [current_run_id, previous_run_id],
    ).fetchall()
    logger.info("[DIFF] Found {count} removed skills", count=len(rows))
    return [
        {
            "skill_id": r[0],
            "slug": r[1],
            "display_name": r[2],
            "owner_handle": r[3],
            "stat_downloads": r[4],
        }
        for r in rows
    ]


def changed_skills(
    conn: duckdb.DuckDBPyConnection,
    current_run_id: int,
    previous_run_id: int,
) -> list[dict]:
    """Skills present in both runs where tracked fields differ."""
    change_conditions = " OR ".join(f"c.{f} IS DISTINCT FROM p.{f}" for f in TRACKED_FIELDS)

    rows = conn.execute(
        f"""
        SELECT
            c.skill_id,
            sk.slug,
            sk.display_name,
            {", ".join(f"p.{f} AS prev_{f}, c.{f} AS curr_{f}" for f in TRACKED_FIELDS)}
        FROM skill_metrics c
        JOIN skill_metrics p
            ON c.skill_id = p.skill_id
            AND p.scrape_run_id = ?
        JOIN skills sk ON c.skill_id = sk.skill_id
        WHERE c.scrape_run_id = ?
            AND ({change_conditions})
        ORDER BY c.stat_downloads DESC
        """,
        [previous_run_id, current_run_id],
    ).fetchall()

    columns = ["skill_id", "slug", "display_name"]
    for f in TRACKED_FIELDS:
        columns.extend([f"prev_{f}", f"curr_{f}"])

    results = []
    for row in rows:
        record = dict(zip(columns, row))
        changes = {}
        for f in TRACKED_FIELDS:
            prev_val = record[f"prev_{f}"]
            curr_val = record[f"curr_{f}"]
            if prev_val != curr_val:
                changes[f] = {"from": prev_val, "to": curr_val}
        record["changes"] = changes
        results.append(record)

    logger.info("[DIFF] Found {count} changed skills", count=len(results))
    return results


def compute_diff(
    conn: duckdb.DuckDBPyConnection,
    current_run_id: int,
    previous_run_id: int,
) -> dict:
    """Compute full diff summary between two runs."""
    return {
        "current_run_id": current_run_id,
        "previous_run_id": previous_run_id,
        "new": new_skills(conn, current_run_id, previous_run_id),
        "removed": removed_skills(conn, current_run_id, previous_run_id),
        "changed": changed_skills(conn, current_run_id, previous_run_id),
    }
