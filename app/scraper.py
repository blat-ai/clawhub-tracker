"""ClawHub skills scraper - paginated fetch from Convex API."""

import json
import time
from pathlib import Path

import httpx
from loguru import logger

API_URL = "https://wry-manatee-359.convex.cloud/api/query"
ITEMS_PER_REQUEST = 180
OUTPUT_DIR = Path(__file__).parent.parent / "data"
OUTPUT_FILE = OUTPUT_DIR / "skills.json"

HEADERS = {
    "accept": "*/*",
    "content-type": "application/json",
    "convex-client": "npm-1.33.0",
    "origin": "https://clawhub.ai",
    "referer": "https://clawhub.ai/",
}


def build_payload(cursor: str | None, num_items: int = ITEMS_PER_REQUEST) -> dict:
    """Build the request payload with pagination options."""
    pagination_opts: dict = {"cursor": cursor, "numItems": num_items}

    return {
        "path": "skills:listPublicPageV2",
        "format": "convex_encoded_json",
        "args": [
            {
                "dir": "desc",
                "highlightedOnly": False,
                "nonSuspiciousOnly": False,
                "paginationOpts": pagination_opts,
                "sort": "downloads",
            }
        ],
    }


def extract_skill_data(item: dict) -> dict:
    """Extract relevant fields from a raw skill item."""
    skill = item.get("skill", {})
    owner = item.get("owner", {})
    latest_version = item.get("latestVersion", {})
    stats = skill.get("stats", {})

    return {
        "skill_id": skill.get("_id"),
        "slug": skill.get("slug"),
        "display_name": skill.get("displayName"),
        "summary": skill.get("summary"),
        "created_at": skill.get("createdAt"),
        "updated_at": skill.get("updatedAt"),
        "badges": skill.get("badges", {}),
        "tags": skill.get("tags", {}),
        "stats": {
            "downloads": stats.get("downloads", 0),
            "stars": stats.get("stars", 0),
            "comments": stats.get("comments", 0),
            "installs_all_time": stats.get("installsAllTime", 0),
            "installs_current": stats.get("installsCurrent", 0),
            "versions": stats.get("versions", 0),
        },
        "owner": {
            "user_id": owner.get("_id"),
            "handle": owner.get("handle"),
            "display_name": owner.get("displayName"),
            "name": owner.get("name"),
            "image": owner.get("image"),
        },
        "latest_version": {
            "version_id": latest_version.get("_id"),
            "version": latest_version.get("version"),
            "changelog": latest_version.get("changelog"),
            "changelog_source": latest_version.get("changelogSource"),
            "created_at": latest_version.get("createdAt"),
        },
        "owner_handle": item.get("ownerHandle"),
    }


def fetch_all_skills() -> list[dict]:
    """Fetch all skills from ClawHub API with pagination."""
    all_skills = []
    cursor = None
    page_num = 0

    with httpx.Client(headers=HEADERS, timeout=30.0) as client:
        while True:
            page_num += 1
            payload = build_payload(cursor)

            logger.info(
                "[SCRAPER] Fetching page {page} (cursor: {cursor})",
                page=page_num,
                cursor=cursor[:40] + "..." if cursor else "None",
            )

            response = client.post(API_URL, json=payload)
            response.raise_for_status()
            data = response.json()

            if data.get("status") != "success":
                logger.error(
                    "[SCRAPER] API returned non-success status: {status}",
                    status=data.get("status"),
                )
                break

            value = data["value"]
            page_items = value.get("page", [])
            is_done = value.get("isDone", True)
            cursor = value.get("continueCursor")

            skills = [extract_skill_data(item) for item in page_items]
            all_skills.extend(skills)

            logger.info(
                "[SCRAPER] Page {page}: got {count} items (total: {total})",
                page=page_num,
                count=len(page_items),
                total=len(all_skills),
            )

            if is_done or not cursor:
                logger.info("[SCRAPER] Pagination complete (isDone={done})", done=is_done)
                break

            time.sleep(0.5)

    return all_skills


def save_skills(skills: list[dict]) -> Path:
    """Save skills to JSON file."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps(skills, indent=2, ensure_ascii=False))
    logger.info(
        "[SCRAPER] Saved {count} skills to {path}",
        count=len(skills),
        path=OUTPUT_FILE,
    )
    return OUTPUT_FILE


def main():
    from app.diff import compute_diff
    from app.models import SkillSnapshot
    from app.storage import (
        complete_run,
        fail_run,
        get_connection,
        get_latest_completed_run_id,
        init_schema,
        insert_snapshots,
        start_run,
    )

    logger.info("[SCRAPER] Starting ClawHub skills scrape")

    conn = get_connection()
    init_schema(conn)
    run = start_run(conn)

    try:
        raw_skills = fetch_all_skills()
        save_skills(raw_skills)

        snapshots = [SkillSnapshot.from_scraper_dict(s, run.id) for s in raw_skills]
        insert_snapshots(conn, snapshots)

        previous_run_id = get_latest_completed_run_id(conn)
        new_count = 0
        removed_count = 0
        changed_count = 0

        if previous_run_id is not None:
            diff = compute_diff(conn, run.id, previous_run_id)
            new_count = len(diff["new"])
            removed_count = len(diff["removed"])
            changed_count = len(diff["changed"])
            logger.info(
                "[SCRAPER] Diff vs run {prev}: {new} new, {removed} removed, {changed} changed",
                prev=previous_run_id,
                new=new_count,
                removed=removed_count,
                changed=changed_count,
            )
        else:
            logger.info("[SCRAPER] First run - no previous data to diff against")

        complete_run(
            conn,
            run.id,
            total_skills=len(snapshots),
            new_skills=new_count,
            removed_skills=removed_count,
            changed_skills=changed_count,
        )

        logger.info("[SCRAPER] Done. Total skills scraped: {count}", count=len(snapshots))

    except Exception:
        fail_run(conn, run.id)
        logger.exception("[SCRAPER] Scrape run {id} failed", id=run.id)
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
