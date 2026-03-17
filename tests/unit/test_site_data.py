"""Unit tests for site data queries."""

from datetime import datetime, timezone

from app.models import Skill, SkillMetric
from app.site_data import (
    api_index,
    dashboard_data,
    leaderboard_data,
    owner_detail_data,
    owners_data,
    rising_data,
    skill_detail_data,
    top_owners_for_detail,
    top_skills_for_detail,
)
from app.storage import complete_run, insert_skill_metrics, start_run, upsert_skills


def _ts(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Fields that belong to each model
# ---------------------------------------------------------------------------
_SKILL_FIELDS = {
    "skill_id",
    "slug",
    "display_name",
    "summary",
    "created_at",
    "updated_at",
    "badges",
    "tags",
    "owner_user_id",
    "owner_handle",
    "owner_display_name",
    "owner_name",
    "owner_image",
    "owner_handle_top",
    "first_seen_run_id",
    "last_seen_run_id",
}

_METRIC_FIELDS = {
    "scrape_run_id",
    "skill_id",
    "stat_downloads",
    "stat_stars",
    "stat_comments",
    "stat_installs_all_time",
    "stat_installs_current",
    "stat_versions",
    "version_id",
    "version_number",
    "version_changelog",
    "version_changelog_source",
    "version_created_at",
    "is_highlighted",
    "is_suspicious",
}


def _make(run_id: int, skill_id: str, **kwargs) -> tuple[Skill, SkillMetric]:
    """Build a ``(Skill, SkillMetric)`` pair from merged *kwargs*.

    Static fields are routed to :class:`Skill`, metric fields to
    :class:`SkillMetric`.  Shared key ``skill_id`` goes to both.
    """
    defaults: dict = {
        "slug": f"slug-{skill_id}",
        "display_name": f"Skill {skill_id}",
        "owner_handle": "owner1",
        "stat_downloads": 100,
        "stat_stars": 10,
        "stat_installs_all_time": 50,
        "stat_installs_current": 25,
        "stat_versions": 1,
        "version_number": "1.0.0",
    }
    defaults.update(kwargs)

    skill_kwargs: dict = {"skill_id": skill_id}
    metric_kwargs: dict = {"scrape_run_id": run_id, "skill_id": skill_id}

    for key, value in defaults.items():
        if key == "scrape_run_id":
            continue
        if key in _SKILL_FIELDS:
            skill_kwargs[key] = value
        if key in _METRIC_FIELDS:
            metric_kwargs[key] = value

    return Skill(**skill_kwargs), SkillMetric(**metric_kwargs)


def _insert(db, pairs: list[tuple[Skill, SkillMetric]]) -> None:
    """Upsert skills and insert metrics from a list of ``(Skill, SkillMetric)`` pairs."""
    skills = [s for s, _ in pairs]
    metrics = [m for _, m in pairs]
    upsert_skills(db, skills)
    insert_skill_metrics(db, metrics)


def _seed(db, skills_fn):
    run = start_run(db)
    pairs = skills_fn(run.id)
    _insert(db, pairs)
    complete_run(db, run.id, total_skills=len(pairs))
    return run.id


class TestDashboardData:
    def test_totals(self, db):
        _seed(
            db,
            lambda rid: [
                _make(rid, "a", stat_downloads=5000, stat_stars=50, owner_handle="alice"),
                _make(rid, "b", stat_downloads=3000, stat_stars=30, owner_handle="bob"),
                _make(rid, "c", stat_downloads=200, stat_stars=5, owner_handle="alice"),
            ],
        )
        data = dashboard_data(db)
        assert data["total_skills"] == 3
        assert data["total_downloads"] == 8200
        assert data["total_stars"] == 85
        assert data["total_owners"] == 2

    def test_weekly_growth(self, db):
        _seed(
            db,
            lambda rid: [
                _make(rid, "w1a", created_at=_ts(2026, 1, 6)),
                _make(rid, "w1b", created_at=_ts(2026, 1, 7)),
                _make(rid, "w2a", created_at=_ts(2026, 1, 13)),
            ],
        )
        data = dashboard_data(db)
        weeks = data["weekly_growth"]
        assert len(weeks) >= 2
        first = weeks[0]
        assert "week_start" in first
        assert "new_count" in first
        assert "cumulative" in first

    def test_sparkline_downloads(self, db):
        run1 = start_run(db)
        _insert(db, [_make(run1.id, "a", stat_downloads=100)])
        complete_run(db, run1.id, total_skills=1)
        run2 = start_run(db)
        _insert(db, [_make(run2.id, "a", stat_downloads=300)])
        complete_run(db, run2.id, total_skills=1)
        data = dashboard_data(db)
        sparkline = data["download_sparkline"]
        assert len(sparkline) == 2
        assert sparkline[0] == 100
        assert sparkline[1] == 300

    def test_download_percentiles(self, db):
        _seed(
            db,
            lambda rid: [
                _make(rid, "a", stat_downloads=10),
                _make(rid, "b", stat_downloads=100),
                _make(rid, "c", stat_downloads=1000),
                _make(rid, "d", stat_downloads=10000),
            ],
        )
        data = dashboard_data(db)
        pcts = data["download_percentiles"]
        assert len(pcts) == 1
        entry = pcts[0]
        assert "run_date" in entry
        assert entry["skill_count"] == 4
        assert entry["p50"] <= entry["p90"] <= entry["p95"] <= entry["p99"]

    def test_empty_db(self, db):
        data = dashboard_data(db)
        assert data["total_skills"] == 0
        assert data["total_downloads"] == 0
        assert data["weekly_growth"] == []
        assert data["download_sparkline"] == []
        assert data["download_percentiles"] == []

    def test_download_wow_pct(self, db):
        run1 = start_run(db)
        _insert(db, [_make(run1.id, "a", stat_downloads=1000)])
        complete_run(db, run1.id, total_skills=1)
        run2 = start_run(db)
        _insert(db, [_make(run2.id, "a", stat_downloads=1100)])
        complete_run(db, run2.id, total_skills=1)
        data = dashboard_data(db)
        assert data["download_wow_pct"] == 10.0

    def test_forecast_current_week(self, db):
        _seed(
            db,
            lambda rid: [
                *[_make(rid, f"prev-{i}", created_at=_ts(2026, 3, 9)) for i in range(10)],
                *[_make(rid, f"cur-{i}", created_at=_ts(2026, 3, 16)) for i in range(3)],
            ],
        )
        data = dashboard_data(db, now=_ts(2026, 3, 16))
        weeks = data["weekly_growth"]
        current = weeks[-1]
        assert current["is_forecast"] is True
        assert current["new_count"] == 3
        assert current["forecast_count"] == 21
        assert current["wow_pct"] is not None

    def test_avg_wow_pct_excludes_forecast(self, db):
        _seed(
            db,
            lambda rid: [
                *[_make(rid, f"w1-{i}", created_at=_ts(2026, 3, 2)) for i in range(10)],
                *[_make(rid, f"w2-{i}", created_at=_ts(2026, 3, 9)) for i in range(20)],
                *[_make(rid, f"w3-{i}", created_at=_ts(2026, 3, 16)) for i in range(5)],
            ],
        )
        data = dashboard_data(db, now=_ts(2026, 3, 16))
        assert data["avg_wow_pct"] is not None
        assert data["avg_wow_pct"] == 100.0

    def test_complete_week_not_forecast(self, db):
        _seed(
            db,
            lambda rid: [
                _make(rid, "a", created_at=_ts(2026, 3, 2)),
                _make(rid, "b", created_at=_ts(2026, 3, 9)),
            ],
        )
        data = dashboard_data(db, now=_ts(2026, 3, 23))
        for w in data["weekly_growth"]:
            assert w["is_forecast"] is False
            assert w["forecast_count"] is None

    def test_empty_db_has_new_fields(self, db):
        data = dashboard_data(db)
        assert data["avg_wow_pct"] is None
        assert data["download_wow_pct"] is None


class TestRisingData:
    def test_returns_empty_with_single_run(self, db):
        _seed(db, lambda rid: [_make(rid, "a", created_at=_ts(2026, 3, 10), stat_downloads=100)])
        data = rising_data(db, now=_ts(2026, 3, 16))
        assert data["skills"] == []

    def test_ranks_by_dl_per_day(self, db):
        run1 = start_run(db)
        _insert(
            db,
            [
                _make(run1.id, "slow", created_at=_ts(2026, 3, 1), stat_downloads=100),
                _make(run1.id, "fast", created_at=_ts(2026, 3, 10), stat_downloads=100),
            ],
        )
        complete_run(db, run1.id, total_skills=2)
        run2 = start_run(db)
        _insert(
            db,
            [
                _make(run2.id, "slow", created_at=_ts(2026, 3, 1), stat_downloads=200),
                _make(run2.id, "fast", created_at=_ts(2026, 3, 10), stat_downloads=500),
            ],
        )
        complete_run(db, run2.id, total_skills=2)
        data = rising_data(db, now=_ts(2026, 3, 16))
        slugs = [s["slug"] for s in data["skills"]]
        assert slugs[0] == "slug-fast"

    def test_includes_delta(self, db):
        run1 = start_run(db)
        _insert(db, [_make(run1.id, "a", created_at=_ts(2026, 3, 10), stat_downloads=100)])
        complete_run(db, run1.id, total_skills=1)
        run2 = start_run(db)
        _insert(db, [_make(run2.id, "a", created_at=_ts(2026, 3, 10), stat_downloads=500)])
        complete_run(db, run2.id, total_skills=1)
        data = rising_data(db, now=_ts(2026, 3, 16))
        assert data["skills"][0]["delta"] == 400

    def test_includes_velocity_array(self, db):
        for i in range(3):
            run = start_run(db)
            _insert(
                db, [_make(run.id, "a", created_at=_ts(2026, 3, 10), stat_downloads=(i + 1) * 100)]
            )
            complete_run(db, run.id, total_skills=1)
        data = rising_data(db, now=_ts(2026, 3, 16))
        assert data["skills"][0]["velocity_chart"] == [100, 200, 300]

    def test_excludes_old_skills(self, db):
        run1 = start_run(db)
        _insert(db, [_make(run1.id, "old", created_at=_ts(2026, 1, 1), stat_downloads=100)])
        complete_run(db, run1.id, total_skills=1)
        run2 = start_run(db)
        _insert(db, [_make(run2.id, "old", created_at=_ts(2026, 1, 1), stat_downloads=9999)])
        complete_run(db, run2.id, total_skills=1)
        data = rising_data(db, now=_ts(2026, 3, 16))
        assert data["skills"] == []


class TestLeaderboardData:
    def test_all_time_ordered_by_downloads(self, db):
        _seed(
            db,
            lambda rid: [
                _make(rid, "low", stat_downloads=10),
                _make(rid, "high", stat_downloads=9999),
                _make(rid, "mid", stat_downloads=500),
            ],
        )
        data = leaderboard_data(db)
        slugs = [s["slug"] for s in data["all_time"]]
        assert slugs == ["slug-high", "slug-mid", "slug-low"]

    def test_fastest_growing_requires_two_runs(self, db):
        _seed(db, lambda rid: [_make(rid, "a", stat_downloads=100)])
        data = leaderboard_data(db)
        assert data["fastest_growing"] == []

    def test_fastest_growing_with_acceleration(self, db):
        for i in range(4):
            run = start_run(db)
            _insert(
                db,
                [
                    _make(
                        run.id, "accel", stat_downloads=100 + i * 200, created_at=_ts(2026, 1, 1)
                    ),
                    _make(run.id, "flat", stat_downloads=100 + i * 10, created_at=_ts(2026, 1, 1)),
                ],
            )
            complete_run(db, run.id, total_skills=2)
        data = leaderboard_data(db)
        if data["fastest_growing"]:
            assert data["fastest_growing"][0]["slug"] == "slug-accel"

    def test_trend_arrow(self, db):
        for i in range(4):
            run = start_run(db)
            _insert(
                db, [_make(run.id, "up", stat_downloads=100 * (2**i), created_at=_ts(2026, 1, 1))]
            )
            complete_run(db, run.id, total_skills=1)
        data = leaderboard_data(db)
        entry = data["all_time"][0]
        assert entry["trend"] in ("up", "down", "flat")

    def test_empty_db(self, db):
        data = leaderboard_data(db)
        assert data["all_time"] == []
        assert data["fastest_growing"] == []


class TestOwnersData:
    def test_by_downloads(self, db):
        _seed(
            db,
            lambda rid: [
                _make(
                    rid,
                    "a",
                    owner_handle="alice",
                    stat_downloads=5000,
                    stat_stars=50,
                    created_at=_ts(2026, 1, 15),
                ),
                _make(
                    rid,
                    "b",
                    owner_handle="alice",
                    stat_downloads=3000,
                    stat_stars=30,
                    created_at=_ts(2026, 1, 20),
                ),
                _make(
                    rid,
                    "c",
                    owner_handle="bob",
                    stat_downloads=1000,
                    stat_stars=10,
                    created_at=_ts(2026, 2, 1),
                ),
            ],
        )
        data = owners_data(db, now=_ts(2026, 3, 16))
        by_dl = data["by_downloads"]
        assert len(by_dl) == 2
        assert by_dl[0]["handle"] == "alice"
        assert by_dl[0]["total_downloads"] == 8000
        assert by_dl[0]["skill_count"] == 2
        assert by_dl[0]["dl_pct"] > 0
        assert by_dl[0]["star_pct"] > 0

    def test_by_skill_count(self, db):
        _seed(
            db,
            lambda rid: [
                _make(
                    rid, "a", owner_handle="prolific", stat_downloads=10, created_at=_ts(2026, 1, 1)
                ),
                _make(
                    rid, "b", owner_handle="prolific", stat_downloads=10, created_at=_ts(2026, 1, 2)
                ),
                _make(
                    rid, "c", owner_handle="prolific", stat_downloads=10, created_at=_ts(2026, 1, 3)
                ),
                _make(
                    rid, "d", owner_handle="whale", stat_downloads=9000, created_at=_ts(2026, 1, 1)
                ),
            ],
        )
        data = owners_data(db, now=_ts(2026, 3, 16))
        by_sc = data["by_skill_count"]
        assert by_sc[0]["handle"] == "prolific"
        assert by_sc[0]["skill_count"] == 3

    def test_empty_db(self, db):
        data = owners_data(db)
        assert data["by_downloads"] == []
        assert data["by_stars"] == []
        assert data["by_skill_count"] == []


class TestSkillDetailData:
    def test_history_across_runs(self, db):
        for i in range(3):
            run = start_run(db)
            _insert(
                db,
                [
                    _make(
                        run.id,
                        "a",
                        stat_downloads=(i + 1) * 100,
                        stat_stars=(i + 1) * 10,
                        created_at=_ts(2026, 1, 1),
                    )
                ],
            )
            complete_run(db, run.id, total_skills=1)
        data = skill_detail_data(db, "slug-a")
        assert len(data["history"]) == 3
        assert data["history"][0]["downloads"] == 100
        assert data["history"][2]["downloads"] == 300

    def test_version_releases_detected(self, db):
        run1 = start_run(db)
        _insert(db, [_make(run1.id, "a", version_number="1.0.0", created_at=_ts(2026, 1, 1))])
        complete_run(db, run1.id, total_skills=1)
        run2 = start_run(db)
        _insert(
            db,
            [
                _make(
                    run2.id,
                    "a",
                    version_number="1.1.0",
                    version_changelog="Bug fix",
                    created_at=_ts(2026, 1, 1),
                )
            ],
        )
        complete_run(db, run2.id, total_skills=1)
        data = skill_detail_data(db, "slug-a")
        assert len(data["version_releases"]) == 1
        assert data["version_releases"][0]["version_number"] == "1.1.0"
        assert data["version_releases"][0]["changelog"] == "Bug fix"

    def test_returns_none_for_unknown_slug(self, db):
        _seed(db, lambda rid: [_make(rid, "a")])
        data = skill_detail_data(db, "nonexistent")
        assert data is None


class TestOwnerDetailData:
    def test_portfolio_summary(self, db):
        _seed(
            db,
            lambda rid: [
                _make(
                    rid, "s1", owner_handle="alice", stat_downloads=5000, created_at=_ts(2026, 1, 1)
                ),
                _make(
                    rid, "s2", owner_handle="alice", stat_downloads=3000, created_at=_ts(2026, 2, 1)
                ),
                _make(
                    rid, "s3", owner_handle="bob", stat_downloads=1000, created_at=_ts(2026, 1, 1)
                ),
            ],
        )
        data = owner_detail_data(db, "alice")
        assert data["total_downloads"] == 8000
        assert data["skill_count"] == 2
        assert len(data["skills"]) == 2

    def test_download_trajectory(self, db):
        for i in range(3):
            run = start_run(db)
            _insert(db, [_make(run.id, "s1", owner_handle="alice", stat_downloads=(i + 1) * 100)])
            complete_run(db, run.id, total_skills=1)
        data = owner_detail_data(db, "alice")
        assert len(data["download_trajectory"]) == 3
        assert data["download_trajectory"] == [100, 200, 300]

    def test_returns_none_for_unknown_handle(self, db):
        _seed(db, lambda rid: [_make(rid, "a", owner_handle="alice")])
        data = owner_detail_data(db, "nonexistent")
        assert data is None


class TestThresholds:
    def test_top_skills_by_downloads(self, db):
        _seed(
            db,
            lambda rid: [
                _make(rid, "big", stat_downloads=9999, slug="big-skill"),
                _make(rid, "small", stat_downloads=1, slug="small-skill"),
            ],
        )
        slugs = top_skills_for_detail(db, limit=1)
        assert slugs == ["big-skill"]

    def test_skips_null_slugs(self, db):
        _seed(
            db,
            lambda rid: [
                _make(rid, "a", stat_downloads=9999, slug=None),
                _make(rid, "b", stat_downloads=5000, slug="has-slug"),
            ],
        )
        slugs = top_skills_for_detail(db, limit=10)
        assert "has-slug" in slugs
        assert None not in slugs

    def test_top_owners(self, db):
        _seed(
            db,
            lambda rid: [
                _make(rid, "a1", owner_handle="alice", stat_downloads=5000),
                _make(rid, "a2", owner_handle="alice", stat_downloads=3000),
                _make(rid, "b1", owner_handle="bob", stat_downloads=100),
            ],
        )
        handles = top_owners_for_detail(db, limit=1)
        assert handles == ["alice"]


class TestApiIndex:
    def test_structure(self, db):
        _seed(
            db,
            lambda rid: [
                _make(rid, "a", slug="skill-a", owner_handle="alice", stat_downloads=5000),
            ],
        )
        data = api_index(skill_slugs=["skill-a"], owner_handles=["alice"])
        assert "endpoints" in data
        assert "skills" in data
        assert data["skills"]["count"] == 1
        assert data["owners"]["count"] == 1
        assert "generated_at" in data
