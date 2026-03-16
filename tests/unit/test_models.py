"""Unit tests for data models."""

import json
from datetime import datetime, timezone

from app.models import SkillSnapshot, _epoch_ms_to_dt

SAMPLE_SCRAPER_DICT = {
    "skill_id": "kd7car3k6zj36bgjmcsxmyb01x805ydd",
    "slug": "web-search",
    "display_name": "Web Search",
    "summary": "Search the web using DuckDuckGo's API.",
    "created_at": 1769673454302.0,
    "updated_at": 1773630571430.0,
    "badges": {},
    "tags": {"latest": "k97e2055wfhrf2wk8ykn04x98x804v6c"},
    "stats": {
        "downloads": 18523.0,
        "stars": 23.0,
        "comments": 1.0,
        "installs_all_time": 340.0,
        "installs_current": 326.0,
        "versions": 1.0,
    },
    "owner": {
        "user_id": "kn7cz85m29bj398zc6mnggkv19805nzz",
        "handle": "billyutw",
        "display_name": "billyutw",
        "name": "billyutw",
        "image": "https://avatars.githubusercontent.com/u/26513936?v=4",
    },
    "latest_version": {
        "version_id": "k97e2055wfhrf2wk8ykn04x98x804v6c",
        "version": "1.0.0",
        "changelog": "web-search 1.0.0\n\n- Initial release.",
        "changelog_source": "auto",
        "created_at": 1769673454302.0,
    },
    "owner_handle": "billyutw",
}


class TestEpochMsToDatetime:
    def test_valid_epoch(self):
        result = _epoch_ms_to_dt(1769673454302.0)
        assert isinstance(result, datetime)
        assert result.tzinfo == timezone.utc

    def test_none_returns_none(self):
        assert _epoch_ms_to_dt(None) is None

    def test_zero_epoch(self):
        result = _epoch_ms_to_dt(0)
        assert result == datetime(1970, 1, 1, tzinfo=timezone.utc)


class TestSkillSnapshotFromScraperDict:
    def test_basic_fields(self):
        snap = SkillSnapshot.from_scraper_dict(SAMPLE_SCRAPER_DICT, scrape_run_id=1)
        assert snap.scrape_run_id == 1
        assert snap.skill_id == "kd7car3k6zj36bgjmcsxmyb01x805ydd"
        assert snap.slug == "web-search"
        assert snap.display_name == "Web Search"

    def test_stats_flattened(self):
        snap = SkillSnapshot.from_scraper_dict(SAMPLE_SCRAPER_DICT, scrape_run_id=1)
        assert snap.stat_downloads == 18523
        assert snap.stat_stars == 23
        assert snap.stat_comments == 1
        assert snap.stat_installs_all_time == 340
        assert snap.stat_installs_current == 326
        assert snap.stat_versions == 1

    def test_owner_flattened(self):
        snap = SkillSnapshot.from_scraper_dict(SAMPLE_SCRAPER_DICT, scrape_run_id=1)
        assert snap.owner_handle == "billyutw"
        assert snap.owner_user_id == "kn7cz85m29bj398zc6mnggkv19805nzz"
        assert snap.owner_handle_top == "billyutw"

    def test_version_flattened(self):
        snap = SkillSnapshot.from_scraper_dict(SAMPLE_SCRAPER_DICT, scrape_run_id=1)
        assert snap.version_number == "1.0.0"
        assert snap.version_changelog_source == "auto"
        assert snap.version_created_at is not None

    def test_timestamps_converted(self):
        snap = SkillSnapshot.from_scraper_dict(SAMPLE_SCRAPER_DICT, scrape_run_id=1)
        assert isinstance(snap.created_at, datetime)
        assert snap.created_at.tzinfo == timezone.utc

    def test_badges_tags_serialized(self):
        snap = SkillSnapshot.from_scraper_dict(SAMPLE_SCRAPER_DICT, scrape_run_id=1)
        assert snap.badges is None or json.loads(snap.badges) == {}
        tags = json.loads(snap.tags)
        assert "latest" in tags

    def test_empty_dict(self):
        snap = SkillSnapshot.from_scraper_dict({}, scrape_run_id=1)
        assert snap.skill_id == ""
        assert snap.stat_downloads == 0
        assert snap.slug is None
