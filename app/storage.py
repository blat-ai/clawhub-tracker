"""DuckDB storage layer for ClawHub skill snapshots."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import duckdb
from loguru import logger

from app.models import ScrapeRun, SkillSnapshot

DEFAULT_DB_PATH = Path(__file__).parent.parent / "data" / "clawhub.duckdb"

SCHEMA_DDL = """
CREATE SEQUENCE IF NOT EXISTS scrape_run_id_seq START 1;

CREATE TABLE IF NOT EXISTS scrape_runs (
    id            INTEGER PRIMARY KEY DEFAULT nextval('scrape_run_id_seq'),
    started_at    TIMESTAMP NOT NULL,
    finished_at   TIMESTAMP,
    total_skills  INTEGER DEFAULT 0,
    status        VARCHAR DEFAULT 'running',
    duration_secs DOUBLE,
    new_skills    INTEGER DEFAULT 0,
    removed_skills INTEGER DEFAULT 0,
    changed_skills INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS skill_snapshots (
    scrape_run_id       INTEGER NOT NULL,
    skill_id            VARCHAR NOT NULL,
    slug                VARCHAR,
    display_name        VARCHAR,
    summary             VARCHAR,
    created_at          TIMESTAMP,
    updated_at          TIMESTAMP,
    badges              JSON,
    tags                JSON,
    stat_downloads      BIGINT DEFAULT 0,
    stat_stars          BIGINT DEFAULT 0,
    stat_comments       BIGINT DEFAULT 0,
    stat_installs_all_time BIGINT DEFAULT 0,
    stat_installs_current  BIGINT DEFAULT 0,
    stat_versions       BIGINT DEFAULT 0,
    owner_user_id       VARCHAR,
    owner_handle        VARCHAR,
    owner_display_name  VARCHAR,
    owner_name          VARCHAR,
    owner_image         VARCHAR,
    version_id          VARCHAR,
    version_number      VARCHAR,
    version_changelog   VARCHAR,
    version_changelog_source VARCHAR,
    version_created_at  TIMESTAMP,
    owner_handle_top    VARCHAR,
    PRIMARY KEY (scrape_run_id, skill_id)
);

CREATE OR REPLACE VIEW current_skills AS
SELECT s.*
FROM skill_snapshots s
JOIN (
    SELECT id FROM scrape_runs
    WHERE status = 'completed'
    ORDER BY id DESC
    LIMIT 1
) r ON s.scrape_run_id = r.id;

CREATE OR REPLACE VIEW previous_skills AS
SELECT s.*
FROM skill_snapshots s
JOIN (
    SELECT id FROM scrape_runs
    WHERE status = 'completed'
    ORDER BY id DESC
    LIMIT 1 OFFSET 1
) r ON s.scrape_run_id = r.id;
"""


def get_connection(db_path: str | Path | None = None) -> duckdb.DuckDBPyConnection:
    """Open a DuckDB connection. Use ':memory:' for testing."""
    if db_path is None:
        db_path = DEFAULT_DB_PATH
    path_str = str(db_path)
    if path_str != ":memory:":
        Path(path_str).parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(path_str)


def init_schema(conn: duckdb.DuckDBPyConnection) -> None:
    """Create tables, sequences, and views if they don't exist."""
    for statement in SCHEMA_DDL.strip().split(";"):
        stmt = statement.strip()
        if stmt:
            conn.execute(stmt)
    logger.info("[STORAGE] Schema initialized")


def start_run(conn: duckdb.DuckDBPyConnection) -> ScrapeRun:
    """Insert a new scrape run and return it with its assigned ID."""
    now = datetime.now(timezone.utc)
    result = conn.execute(
        "INSERT INTO scrape_runs (started_at) VALUES (?) RETURNING id",
        [now],
    ).fetchone()
    run = ScrapeRun(id=result[0], started_at=now)
    logger.info("[STORAGE] Started scrape run {id}", id=run.id)
    return run


def complete_run(
    conn: duckdb.DuckDBPyConnection,
    run_id: int,
    *,
    total_skills: int = 0,
    new_skills: int = 0,
    removed_skills: int = 0,
    changed_skills: int = 0,
) -> None:
    """Mark a scrape run as completed with final stats."""
    now = datetime.now(timezone.utc)
    conn.execute(
        """
        UPDATE scrape_runs
        SET status = 'completed',
            finished_at = ?,
            total_skills = ?,
            duration_secs = EPOCH(? - started_at),
            new_skills = ?,
            removed_skills = ?,
            changed_skills = ?
        WHERE id = ?
        """,
        [now, total_skills, now, new_skills, removed_skills, changed_skills, run_id],
    )
    logger.info(
        "[STORAGE] Completed run {id}: {total} skills"
        " ({new} new, {removed} removed, {changed} changed)",
        id=run_id,
        total=total_skills,
        new=new_skills,
        removed=removed_skills,
        changed=changed_skills,
    )


def fail_run(conn: duckdb.DuckDBPyConnection, run_id: int) -> None:
    """Mark a scrape run as failed."""
    now = datetime.now(timezone.utc)
    conn.execute(
        """
        UPDATE scrape_runs
        SET status = 'failed',
            finished_at = ?,
            duration_secs = EPOCH(? - started_at)
        WHERE id = ?
        """,
        [now, now, run_id],
    )
    logger.info("[STORAGE] Failed run {id}", id=run_id)


def insert_snapshots(
    conn: duckdb.DuckDBPyConnection,
    snapshots: list[SkillSnapshot],
) -> int:
    """Bulk insert skill snapshots. Returns count inserted."""
    if not snapshots:
        return 0

    conn.executemany(
        """
        INSERT INTO skill_snapshots (
            scrape_run_id, skill_id, slug, display_name, summary,
            created_at, updated_at, badges, tags,
            stat_downloads, stat_stars, stat_comments,
            stat_installs_all_time, stat_installs_current, stat_versions,
            owner_user_id, owner_handle, owner_display_name, owner_name, owner_image,
            version_id, version_number, version_changelog, version_changelog_source,
            version_created_at, owner_handle_top
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                s.scrape_run_id,
                s.skill_id,
                s.slug,
                s.display_name,
                s.summary,
                s.created_at,
                s.updated_at,
                s.badges,
                s.tags,
                s.stat_downloads,
                s.stat_stars,
                s.stat_comments,
                s.stat_installs_all_time,
                s.stat_installs_current,
                s.stat_versions,
                s.owner_user_id,
                s.owner_handle,
                s.owner_display_name,
                s.owner_name,
                s.owner_image,
                s.version_id,
                s.version_number,
                s.version_changelog,
                s.version_changelog_source,
                s.version_created_at,
                s.owner_handle_top,
            )
            for s in snapshots
        ],
    )
    logger.info("[STORAGE] Inserted {count} snapshots", count=len(snapshots))
    return len(snapshots)


def get_run(conn: duckdb.DuckDBPyConnection, run_id: int) -> ScrapeRun | None:
    """Fetch a scrape run by ID."""
    row = conn.execute("SELECT * FROM scrape_runs WHERE id = ?", [run_id]).fetchone()
    if row is None:
        return None
    return ScrapeRun(
        id=row[0],
        started_at=row[1],
        finished_at=row[2],
        total_skills=row[3],
        status=row[4],
        duration_secs=row[5],
        new_skills=row[6],
        removed_skills=row[7],
        changed_skills=row[8],
    )


def get_latest_completed_run_id(conn: duckdb.DuckDBPyConnection) -> int | None:
    """Return the ID of the most recent completed run, or None."""
    row = conn.execute(
        "SELECT id FROM scrape_runs WHERE status = 'completed' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return row[0] if row else None


def get_snapshot_count(conn: duckdb.DuckDBPyConnection, run_id: int) -> int:
    """Count snapshots for a given run."""
    row = conn.execute(
        "SELECT COUNT(*) FROM skill_snapshots WHERE scrape_run_id = ?", [run_id]
    ).fetchone()
    return row[0]
