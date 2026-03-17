"""Data models for ClawHub skills, metrics, and scrape runs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


def _epoch_ms_to_dt(val: float | int | None) -> datetime | None:
    """Convert epoch milliseconds to UTC datetime, or None."""
    if val is None:
        return None
    return datetime.fromtimestamp(val / 1000.0, tz=timezone.utc)


@dataclass
class ScrapeRun:
    """Metadata for a single scrape execution."""

    id: int | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime | None = None
    total_skills: int = 0
    status: str = "running"
    duration_secs: float | None = None
    new_skills: int = 0
    removed_skills: int = 0
    changed_skills: int = 0


@dataclass
class Skill:
    """Static / slowly-changing skill metadata (one row per skill, upserted)."""

    skill_id: str
    slug: str | None = None
    display_name: str | None = None
    summary: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    badges: str | None = None
    tags: str | None = None
    owner_user_id: str | None = None
    owner_handle: str | None = None
    owner_display_name: str | None = None
    owner_name: str | None = None
    owner_image: str | None = None
    owner_handle_top: str | None = None
    first_seen_run_id: int | None = None
    last_seen_run_id: int | None = None

    @classmethod
    def from_scraper_dict(cls, data: dict, scrape_run_id: int) -> Skill:
        """Extract static fields from a scraper dict."""
        import json

        owner = data.get("owner", {})

        badges_raw = data.get("badges")
        tags_raw = data.get("tags")

        return cls(
            skill_id=data.get("skill_id", ""),
            slug=data.get("slug"),
            display_name=data.get("display_name"),
            summary=data.get("summary"),
            created_at=_epoch_ms_to_dt(data.get("created_at")),
            updated_at=_epoch_ms_to_dt(data.get("updated_at")),
            badges=json.dumps(badges_raw) if badges_raw else None,
            tags=json.dumps(tags_raw) if tags_raw else None,
            owner_user_id=owner.get("user_id"),
            owner_handle=owner.get("handle"),
            owner_display_name=owner.get("display_name"),
            owner_name=owner.get("name"),
            owner_image=owner.get("image"),
            owner_handle_top=data.get("owner_handle"),
            first_seen_run_id=scrape_run_id,
            last_seen_run_id=scrape_run_id,
        )


@dataclass
class SkillMetric:
    """Time-varying metrics for a skill in a single scrape run."""

    scrape_run_id: int
    skill_id: str
    stat_downloads: int = 0
    stat_stars: int = 0
    stat_comments: int = 0
    stat_installs_all_time: int = 0
    stat_installs_current: int = 0
    stat_versions: int = 0
    version_id: str | None = None
    version_number: str | None = None
    version_changelog: str | None = None
    version_changelog_source: str | None = None
    version_created_at: datetime | None = None
    is_highlighted: bool = False
    is_suspicious: bool = False

    @classmethod
    def from_scraper_dict(cls, data: dict, scrape_run_id: int) -> SkillMetric:
        """Extract metric fields from a scraper dict."""
        stats = data.get("stats", {})
        version = data.get("latest_version", {})

        return cls(
            scrape_run_id=scrape_run_id,
            skill_id=data.get("skill_id", ""),
            stat_downloads=int(stats.get("downloads", 0)),
            stat_stars=int(stats.get("stars", 0)),
            stat_comments=int(stats.get("comments", 0)),
            stat_installs_all_time=int(stats.get("installs_all_time", 0)),
            stat_installs_current=int(stats.get("installs_current", 0)),
            stat_versions=int(stats.get("versions", 0)),
            version_id=version.get("version_id"),
            version_number=version.get("version"),
            version_changelog=version.get("changelog"),
            version_changelog_source=version.get("changelog_source"),
            version_created_at=_epoch_ms_to_dt(version.get("created_at")),
        )
