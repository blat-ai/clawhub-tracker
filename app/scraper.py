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


def build_payload(
    cursor: str | None,
    num_items: int = ITEMS_PER_REQUEST,
    *,
    highlighted_only: bool = False,
    non_suspicious_only: bool = False,
) -> dict:
    """Build the request payload with pagination options."""
    args: dict = {
        "dir": "desc",
        "highlightedOnly": highlighted_only,
        "nonSuspiciousOnly": non_suspicious_only,
        "numItems": num_items,
        "sort": "downloads",
    }
    if cursor is not None:
        args["cursor"] = cursor

    return {
        "path": "skills:listPublicPageV4",
        "format": "convex_encoded_json",
        "args": [args],
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
            has_more = value.get("hasMore", False)
            cursor = value.get("nextCursor")

            skills = [extract_skill_data(item) for item in page_items]
            all_skills.extend(skills)

            logger.info(
                "[SCRAPER] Page {page}: got {count} items (total: {total})",
                page=page_num,
                count=len(page_items),
                total=len(all_skills),
            )

            if not has_more or not cursor:
                logger.info("[SCRAPER] Pagination complete (hasMore={more})", more=has_more)
                break

            time.sleep(0.5)

    return all_skills


def fetch_skill_ids(
    *,
    highlighted_only: bool = False,
    non_suspicious_only: bool = False,
    label: str = "",
) -> set[str]:
    """Fetch only skill IDs with specific filters (lightweight tagging pass)."""
    ids: set[str] = set()
    cursor = None
    page_num = 0

    with httpx.Client(headers=HEADERS, timeout=30.0) as client:
        while True:
            page_num += 1
            payload = build_payload(
                cursor,
                highlighted_only=highlighted_only,
                non_suspicious_only=non_suspicious_only,
            )

            response = client.post(API_URL, json=payload)
            response.raise_for_status()
            data = response.json()

            if data.get("status") != "success":
                logger.error("[SCRAPER] {label} API error: {s}", label=label, s=data.get("status"))
                break

            value = data["value"]
            for item in value.get("page", []):
                skill = item.get("skill", {})
                sid = skill.get("_id")
                if sid:
                    ids.add(sid)

            has_more = value.get("hasMore", False)
            cursor = value.get("nextCursor")

            if not has_more or not cursor:
                break
            time.sleep(0.3)

    logger.info("[SCRAPER] {label}: found {count} skill IDs", label=label, count=len(ids))
    return ids


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
    from app.models import Skill, SkillMetric
    from app.storage import (
        complete_run,
        fail_run,
        get_connection,
        get_latest_completed_run_id,
        init_schema,
        insert_skill_metrics,
        start_run,
        upsert_skills,
    )

    logger.info("[SCRAPER] Starting ClawHub skills scrape")

    conn = get_connection()
    init_schema(conn)
    run = start_run(conn)

    try:
        raw_skills = fetch_all_skills()
        save_skills(raw_skills)

        if not raw_skills:
            logger.error("[SCRAPER] API returned 0 skills — aborting to protect data")
            fail_run(conn, run.id)
            return

        # Tagging passes: identify highlighted and non-suspicious skill IDs
        highlighted_ids = fetch_skill_ids(
            highlighted_only=True, label="Highlighted"
        )
        non_suspicious_ids = fetch_skill_ids(
            non_suspicious_only=True, label="Non-suspicious"
        )

        skills = []
        metrics = []
        for s in raw_skills:
            skill = Skill.from_scraper_dict(s, run.id)
            metric = SkillMetric.from_scraper_dict(s, run.id)
            metric.is_highlighted = metric.skill_id in highlighted_ids
            metric.is_suspicious = metric.skill_id not in non_suspicious_ids
            skills.append(skill)
            metrics.append(metric)

        logger.info(
            "[SCRAPER] Tagged {hl} highlighted, {sus} suspicious out of {total}",
            hl=sum(1 for m in metrics if m.is_highlighted),
            sus=sum(1 for m in metrics if m.is_suspicious),
            total=len(metrics),
        )

        upsert_skills(conn, skills)
        insert_skill_metrics(conn, metrics)

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
            total_skills=len(skills),
            new_skills=new_count,
            removed_skills=removed_count,
            changed_skills=changed_count,
        )

        logger.info("[SCRAPER] Done. Total skills scraped: {count}", count=len(skills))

    except Exception:
        fail_run(conn, run.id)
        logger.exception("[SCRAPER] Scrape run {id} failed", id=run.id)
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
