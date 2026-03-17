"""DuckDB storage layer for ClawHub skill data."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import duckdb
from loguru import logger

from app.models import ScrapeRun, Skill, SkillMetric  # noqa: F401

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

CREATE TABLE IF NOT EXISTS skills (
    skill_id            VARCHAR PRIMARY KEY,
    slug                VARCHAR,
    display_name        VARCHAR,
    summary             VARCHAR,
    created_at          TIMESTAMP,
    updated_at          TIMESTAMP,
    badges              JSON,
    tags                JSON,
    owner_user_id       VARCHAR,
    owner_handle        VARCHAR,
    owner_display_name  VARCHAR,
    owner_name          VARCHAR,
    owner_image         VARCHAR,
    owner_handle_top    VARCHAR,
    first_seen_run_id   INTEGER,
    last_seen_run_id    INTEGER
);

CREATE TABLE IF NOT EXISTS skill_metrics (
    scrape_run_id             INTEGER NOT NULL,
    skill_id                  VARCHAR NOT NULL,
    stat_downloads            BIGINT DEFAULT 0,
    stat_stars                BIGINT DEFAULT 0,
    stat_comments             BIGINT DEFAULT 0,
    stat_installs_all_time    BIGINT DEFAULT 0,
    stat_installs_current     BIGINT DEFAULT 0,
    stat_versions             BIGINT DEFAULT 0,
    version_id                VARCHAR,
    version_number            VARCHAR,
    version_changelog         VARCHAR,
    version_changelog_source  VARCHAR,
    version_created_at        TIMESTAMP,
    is_highlighted            BOOLEAN DEFAULT FALSE,
    is_suspicious             BOOLEAN DEFAULT FALSE,
    PRIMARY KEY (scrape_run_id, skill_id)
);

CREATE OR REPLACE VIEW current_skills AS
SELECT sk.*, sm.stat_downloads, sm.stat_stars, sm.stat_comments,
       sm.stat_installs_all_time, sm.stat_installs_current, sm.stat_versions,
       sm.version_id, sm.version_number, sm.version_changelog,
       sm.version_changelog_source, sm.version_created_at,
       sm.is_highlighted, sm.is_suspicious, sm.scrape_run_id
FROM skills sk
JOIN skill_metrics sm ON sk.skill_id = sm.skill_id
JOIN (SELECT id FROM scrape_runs WHERE status='completed' ORDER BY id DESC LIMIT 1) r
  ON sm.scrape_run_id = r.id;

CREATE OR REPLACE VIEW previous_skills AS
SELECT sk.*, sm.stat_downloads, sm.stat_stars, sm.stat_comments,
       sm.stat_installs_all_time, sm.stat_installs_current, sm.stat_versions,
       sm.version_id, sm.version_number, sm.version_changelog,
       sm.version_changelog_source, sm.version_created_at,
       sm.is_highlighted, sm.is_suspicious, sm.scrape_run_id
FROM skills sk
JOIN skill_metrics sm ON sk.skill_id = sm.skill_id
JOIN (SELECT id FROM scrape_runs WHERE status='completed' ORDER BY id DESC LIMIT 1 OFFSET 1) r
  ON sm.scrape_run_id = r.id;
"""


def get_connection(db_path: str | Path | None = None) -> duckdb.DuckDBPyConnection:
    """Open a DuckDB connection. Use ':memory:' for testing."""
    if db_path is None:
        db_path = DEFAULT_DB_PATH
    path_str = str(db_path)
    if path_str != ":memory:":
        Path(path_str).parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(path_str)


def _table_exists(conn: duckdb.DuckDBPyConnection, name: str) -> bool:
    row = conn.execute(
        "SELECT COUNT(*) FROM information_schema.tables "
        "WHERE table_schema = 'main' AND table_name = ?",
        [name],
    ).fetchone()
    return row[0] > 0


def _migrate_from_snapshots(conn: duckdb.DuckDBPyConnection) -> None:
    """One-time migration: populate skills + skill_metrics from skill_snapshots."""
    if not _table_exists(conn, "skill_snapshots"):
        return

    logger.info("[STORAGE] Migrating skill_snapshots -> skills + skill_metrics")

    # Idempotent: clear new tables in case of a previous partial migration
    conn.execute("DELETE FROM skill_metrics")
    conn.execute("DELETE FROM skills")

    # Populate skills from the latest snapshot per skill
    conn.execute("""
        INSERT INTO skills
        SELECT
            skill_id, slug, display_name, summary, created_at, updated_at,
            badges, tags, owner_user_id, owner_handle, owner_display_name,
            owner_name, owner_image, owner_handle_top,
            scrape_run_id AS first_seen_run_id,
            scrape_run_id AS last_seen_run_id
        FROM (
            SELECT *, ROW_NUMBER() OVER (PARTITION BY skill_id ORDER BY scrape_run_id DESC) AS rn
            FROM skill_snapshots
        ) sub
        WHERE rn = 1
    """)

    # Update first_seen_run_id to actual first run
    conn.execute("""
        UPDATE skills SET first_seen_run_id = sub.first_run
        FROM (
            SELECT skill_id, MIN(scrape_run_id) AS first_run
            FROM skill_snapshots GROUP BY skill_id
        ) sub
        WHERE skills.skill_id = sub.skill_id
    """)

    # Update last_seen_run_id to actual last run
    conn.execute("""
        UPDATE skills SET last_seen_run_id = sub.last_run
        FROM (
            SELECT skill_id, MAX(scrape_run_id) AS last_run
            FROM skill_snapshots GROUP BY skill_id
        ) sub
        WHERE skills.skill_id = sub.skill_id
    """)

    # Populate skill_metrics from all snapshots
    # Old table may lack is_highlighted/is_suspicious columns — check first
    old_cols = {r[0] for r in conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name='skill_snapshots'"
    ).fetchall()}

    hl_expr = "COALESCE(is_highlighted, FALSE)" if "is_highlighted" in old_cols else "FALSE"
    sus_expr = "COALESCE(is_suspicious, FALSE)" if "is_suspicious" in old_cols else "FALSE"

    conn.execute(f"""
        INSERT INTO skill_metrics
        SELECT
            scrape_run_id, skill_id,
            stat_downloads, stat_stars, stat_comments,
            stat_installs_all_time, stat_installs_current, stat_versions,
            version_id, version_number, version_changelog,
            version_changelog_source, version_created_at,
            {hl_expr},
            {sus_expr}
        FROM skill_snapshots
    """)

    conn.execute("DROP TABLE skill_snapshots")
    logger.info("[STORAGE] Migration complete — skill_snapshots dropped")


def init_schema(conn: duckdb.DuckDBPyConnection) -> None:
    """Create tables, sequences, and views if they don't exist."""
    for statement in SCHEMA_DDL.strip().split(";"):
        stmt = statement.strip()
        if stmt:
            conn.execute(stmt)
    _migrate_from_snapshots(conn)
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


def upsert_skills(
    conn: duckdb.DuckDBPyConnection,
    skills: list[Skill],
) -> int:
    """Upsert skills (static metadata). Returns count upserted."""
    if not skills:
        return 0

    conn.executemany(
        """
        INSERT INTO skills (
            skill_id, slug, display_name, summary,
            created_at, updated_at, badges, tags,
            owner_user_id, owner_handle, owner_display_name, owner_name, owner_image,
            owner_handle_top, first_seen_run_id, last_seen_run_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (skill_id) DO UPDATE SET
            slug = EXCLUDED.slug,
            display_name = EXCLUDED.display_name,
            summary = EXCLUDED.summary,
            created_at = EXCLUDED.created_at,
            updated_at = EXCLUDED.updated_at,
            badges = EXCLUDED.badges,
            tags = EXCLUDED.tags,
            owner_user_id = EXCLUDED.owner_user_id,
            owner_handle = EXCLUDED.owner_handle,
            owner_display_name = EXCLUDED.owner_display_name,
            owner_name = EXCLUDED.owner_name,
            owner_image = EXCLUDED.owner_image,
            owner_handle_top = EXCLUDED.owner_handle_top,
            last_seen_run_id = EXCLUDED.last_seen_run_id
        """,
        [
            (
                s.skill_id,
                s.slug,
                s.display_name,
                s.summary,
                s.created_at,
                s.updated_at,
                s.badges,
                s.tags,
                s.owner_user_id,
                s.owner_handle,
                s.owner_display_name,
                s.owner_name,
                s.owner_image,
                s.owner_handle_top,
                s.first_seen_run_id,
                s.last_seen_run_id,
            )
            for s in skills
        ],
    )
    logger.info("[STORAGE] Upserted {count} skills", count=len(skills))
    return len(skills)


def insert_skill_metrics(
    conn: duckdb.DuckDBPyConnection,
    metrics: list[SkillMetric],
) -> int:
    """Bulk insert skill metrics. Returns count inserted."""
    if not metrics:
        return 0

    conn.executemany(
        """
        INSERT INTO skill_metrics (
            scrape_run_id, skill_id,
            stat_downloads, stat_stars, stat_comments,
            stat_installs_all_time, stat_installs_current, stat_versions,
            version_id, version_number, version_changelog, version_changelog_source,
            version_created_at, is_highlighted, is_suspicious
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                m.scrape_run_id,
                m.skill_id,
                m.stat_downloads,
                m.stat_stars,
                m.stat_comments,
                m.stat_installs_all_time,
                m.stat_installs_current,
                m.stat_versions,
                m.version_id,
                m.version_number,
                m.version_changelog,
                m.version_changelog_source,
                m.version_created_at,
                m.is_highlighted,
                m.is_suspicious,
            )
            for m in metrics
        ],
    )
    logger.info("[STORAGE] Inserted {count} skill metrics", count=len(metrics))
    return len(metrics)


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
    """Count skill metrics for a given run."""
    row = conn.execute(
        "SELECT COUNT(*) FROM skill_metrics WHERE scrape_run_id = ?", [run_id]
    ).fetchone()
    return row[0]
