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
