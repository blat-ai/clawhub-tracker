"""Unit tests for report generation."""

from datetime import datetime, timezone

from app.models import Skill, SkillMetric
from app.report import (
    cohort_quality,
    growth_timeline,
    hot_new_skills,
    owner_ecosystem,
    platform_snapshot,
    platform_velocity,
    quality_signals,
    rising_skills,
    top_skills,
)
from app.storage import complete_run, insert_skill_metrics, start_run, upsert_skills

# ---------------------------------------------------------------------------
# Fields that belong to the Skill model (static / slowly-changing metadata)
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


def _ts(year: int, month: int, day: int) -> datetime:
    """Create a UTC datetime for fixture data."""
    return datetime(year, month, day, tzinfo=timezone.utc)


def _make(run_id: int, skill_id: str, **kwargs) -> tuple[Skill, SkillMetric]:
    """Build a (Skill, SkillMetric) pair with sensible defaults.

    Keyword arguments are routed to the correct dataclass automatically:
    static / identity fields go to Skill, metric fields go to SkillMetric.
    """
    # Defaults that span both models
    defaults: dict = {
        "skill_id": skill_id,
        "slug": f"slug-{skill_id}",
        "display_name": f"Skill {skill_id}",
        "owner_handle": "owner1",
        "stat_downloads": 100,
        "stat_stars": 10,
        "stat_installs_all_time": 50,
        "stat_versions": 1,
    }
    defaults.update(kwargs)

    # Split into Skill kwargs vs SkillMetric kwargs
    skill_kw: dict = {}
    metric_kw: dict = {}
    for key, val in defaults.items():
        if key in _SKILL_FIELDS:
            skill_kw[key] = val
        else:
            metric_kw[key] = val

    skill = Skill(
        first_seen_run_id=run_id,
        last_seen_run_id=run_id,
        **skill_kw,
    )
    metric = SkillMetric(
        scrape_run_id=run_id,
        skill_id=skill_id,
        **metric_kw,
    )
    return skill, metric


def _insert(db, pairs):
    """Upsert skills then insert metrics from a list of (Skill, SkillMetric) pairs."""
    upsert_skills(db, [p[0] for p in pairs])
    insert_skill_metrics(db, [p[1] for p in pairs])


def _seed(db, skills_fn):
    """Create one completed run with given skills and return run_id."""
    run = start_run(db)
    pairs = skills_fn(run.id)
    _insert(db, pairs)
    complete_run(db, run.id, total_skills=len(pairs))
    return run.id


class TestPlatformSnapshot:
    def test_totals_and_power_law(self, db):
        _seed(
            db,
            lambda rid: [
                _make(rid, "big", stat_downloads=10000, stat_stars=100, stat_installs_all_time=500),
                _make(rid, "med", stat_downloads=500, stat_stars=20, stat_installs_all_time=100),
                _make(rid, "sm1", stat_downloads=10, stat_stars=1, stat_installs_all_time=2),
                _make(rid, "sm2", stat_downloads=5, stat_stars=0, stat_installs_all_time=1),
            ],
        )
        out = platform_snapshot(db)
        assert "PLATFORM SNAPSHOT" in out
        assert "4" in out  # 4 skills
        assert "10,515" in out  # total downloads
        assert "Top 1% captures" in out
        assert "Top 10% captures" in out

    def test_empty_db(self, db):
        _seed(db, lambda rid: [_make(rid, "one", stat_downloads=0, stat_stars=0)])
        out = platform_snapshot(db)
        assert "PLATFORM SNAPSHOT" in out


class TestGrowthTimeline:
    def test_weekly_bars_with_wow(self, db):
        _seed(
            db,
            lambda rid: [
                _make(rid, "a", created_at=_ts(2026, 1, 6)),  # W01
                _make(rid, "b", created_at=_ts(2026, 1, 7)),  # W01
                _make(rid, "c", created_at=_ts(2026, 1, 13)),  # W02
                _make(rid, "d", created_at=_ts(2026, 2, 3)),  # W05
            ],
        )
        out = growth_timeline(db)
        assert "PLATFORM GROWTH TIMELINE" in out
        assert "cum:" in out
        # Should have multiple week rows
        assert out.count("new") >= 3
        # WoW% should appear (at least for 2nd week onward)
        assert "%" in out

    def test_no_created_at(self, db):
        _seed(db, lambda rid: [_make(rid, "x", created_at=None)])
        out = growth_timeline(db)
        assert "No created_at data" in out


class TestCohortQuality:
    def test_monthly_cohorts(self, db):
        _seed(
            db,
            lambda rid: [
                # Jan cohort: high quality
                _make(
                    rid,
                    "jan1",
                    created_at=_ts(2026, 1, 15),
                    stat_downloads=5000,
                    stat_stars=50,
                    stat_installs_all_time=2000,
                ),
                _make(
                    rid,
                    "jan2",
                    created_at=_ts(2026, 1, 20),
                    stat_downloads=3000,
                    stat_stars=30,
                    stat_installs_all_time=1000,
                ),
                # Feb cohort: lower quality
                _make(
                    rid,
                    "feb1",
                    created_at=_ts(2026, 2, 10),
                    stat_downloads=800,
                    stat_stars=8,
                    stat_installs_all_time=200,
                ),
                _make(
                    rid,
                    "feb2",
                    created_at=_ts(2026, 2, 15),
                    stat_downloads=200,
                    stat_stars=2,
                    stat_installs_all_time=40,
                ),
                # Mar cohort: lowest
                _make(
                    rid,
                    "mar1",
                    created_at=_ts(2026, 3, 1),
                    stat_downloads=50,
                    stat_stars=1,
                    stat_installs_all_time=5,
                ),
            ],
        )
        now = _ts(2026, 3, 16)
        out = cohort_quality(db, now=now)
        assert "COHORT QUALITY ANALYSIS" in out
        assert "2026-01" in out
        assert "2026-02" in out
        assert "2026-03" in out
        # Jan avg_dl should be 4000 = (5000+3000)/2
        assert "4,000" in out
        # DL/day column should be present
        assert "DL/day" in out

    def test_dl_per_day_normalizes_age(self, db):
        """Newer cohort with fewer raw downloads can have higher DL/day."""
        _seed(
            db,
            lambda rid: [
                # Old skill: 600 downloads over 60 days = 10 dl/day
                _make(
                    rid,
                    "old",
                    created_at=_ts(2026, 1, 15),
                    stat_downloads=600,
                ),
                # New skill: 150 downloads over 15 days = 10 dl/day
                _make(
                    rid,
                    "new",
                    created_at=_ts(2026, 3, 1),
                    stat_downloads=150,
                ),
            ],
        )
        now = _ts(2026, 3, 16)
        out = cohort_quality(db, now=now)
        # Both should show similar dl/day despite 4x raw difference
        assert "DL/day" in out
        # Raw avg_dl: Jan=600, Mar=150 (very different)
        # DL/day: Jan=10.0, Mar=10.0 (same velocity)
        assert "10.0" in out

    def test_no_data(self, db):
        _seed(db, lambda rid: [_make(rid, "x", created_at=None)])
        out = cohort_quality(db)
        assert "No created_at data" in out


class TestHotNewSkills:
    def test_finds_recent_skills(self, db):
        now = _ts(2026, 3, 15)
        _seed(
            db,
            lambda rid: [
                _make(rid, "old", created_at=_ts(2026, 1, 1), stat_downloads=9999),
                _make(rid, "new1", created_at=_ts(2026, 3, 1), stat_downloads=500),
                _make(rid, "new2", created_at=_ts(2026, 3, 10), stat_downloads=300),
            ],
        )
        out = hot_new_skills(db, now=now)
        assert "HOT NEW SKILLS" in out
        assert "Skill new1" in out
        assert "Skill new2" in out
        # "old" should NOT appear (created >30 days ago)
        assert "Skill old" not in out

    def test_no_recent(self, db):
        now = _ts(2026, 3, 15)
        _seed(
            db,
            lambda rid: [_make(rid, "old", created_at=_ts(2026, 1, 1))],
        )
        out = hot_new_skills(db, now=now)
        assert "No skills created" in out


class TestTopSkills:
    def test_ordered_by_downloads(self, db):
        _seed(
            db,
            lambda rid: [
                _make(rid, "low", stat_downloads=10),
                _make(rid, "high", stat_downloads=9999),
                _make(rid, "mid", stat_downloads=500),
            ],
        )
        out = top_skills(db)
        assert "TOP 10 SKILLS" in out
        # "high" should appear before "mid"
        pos_high = out.index("Skill high")
        pos_mid = out.index("Skill mid")
        assert pos_high < pos_mid


class TestQualitySignals:
    def test_star_ratio_and_versions(self, db):
        _seed(
            db,
            lambda rid: [
                _make(rid, "loved", stat_downloads=200, stat_stars=100, stat_versions=15),
                _make(rid, "meh", stat_downloads=200, stat_stars=2, stat_versions=1),
                # Below threshold - should not appear in star ratio
                _make(rid, "tiny", stat_downloads=5, stat_stars=5, stat_versions=1),
            ],
        )
        out = quality_signals(db)
        assert "QUALITY SIGNALS" in out
        assert "Best star-to-download ratio" in out
        assert "Most actively maintained" in out
        # "loved" should be top ratio
        ratio_section = out.split("Most actively maintained")[0]
        assert "Skill loved" in ratio_section
        # "loved" with 15 versions should be top maintained
        version_section = out.split("Most actively maintained")[1]
        assert "Skill loved" in version_section


class TestOwnerEcosystem:
    def test_top_owners(self, db):
        _seed(
            db,
            lambda rid: [
                _make(rid, "a1", owner_handle="alice", stat_downloads=5000),
                _make(rid, "a2", owner_handle="alice", stat_downloads=3000),
                _make(rid, "b1", owner_handle="bob", stat_downloads=1000),
            ],
        )
        out = owner_ecosystem(db)
        assert "OWNER ECOSYSTEM" in out
        assert "alice" in out
        assert "bob" in out
        # alice should appear before bob
        assert out.index("alice") < out.index("bob")

    def test_spam_detection(self, db):
        skills = []

        def make_skills(rid):
            # Create 55 low-quality skills for a spammer
            for i in range(55):
                skills.append(_make(rid, f"spam_{i}", owner_handle="spammer", stat_downloads=10))
            # And a legit owner
            skills.append(_make(rid, "legit", owner_handle="legit_owner", stat_downloads=5000))
            return skills

        _seed(db, make_skills)
        out = owner_ecosystem(db)
        assert "Suspected spam" in out
        assert "spammer" in out

    def test_no_spam(self, db):
        _seed(
            db,
            lambda rid: [
                _make(rid, "a", owner_handle="alice", stat_downloads=5000),
            ],
        )
        out = owner_ecosystem(db)
        assert "No suspected spam" in out


class TestPlatformVelocity:
    def test_returns_none_with_single_run(self, db):
        _seed(
            db,
            lambda rid: [_make(rid, "a", stat_downloads=100)],
        )
        assert platform_velocity(db) is None

    def test_shows_delta_with_two_runs(self, db):
        # Run 1
        run1 = start_run(db)
        pairs1 = [_make(run1.id, "a", stat_downloads=100)]
        _insert(db, pairs1)
        complete_run(db, run1.id, total_skills=1)

        # Run 2 - downloads grew
        run2 = start_run(db)
        pairs2 = [
            _make(run2.id, "a", stat_downloads=300),
            _make(run2.id, "b", stat_downloads=50),
        ]
        _insert(db, pairs2)
        complete_run(db, run2.id, total_skills=2)

        out = platform_velocity(db)
        assert out is not None
        assert "PLATFORM VELOCITY" in out
        assert "DL Delta" in out
        # Run 2 total is 350, run 1 total is 100, delta is +250
        assert "+250" in out

    def test_shows_avg_velocity_with_three_runs(self, db):
        for i in range(3):
            run = start_run(db)
            pairs = [
                _make(
                    run.id,
                    f"s{i}",
                    stat_downloads=(i + 1) * 1000,
                ),
            ]
            _insert(db, pairs)
            complete_run(db, run.id, total_skills=1)

        out = platform_velocity(db)
        assert out is not None
        assert "Avg download velocity" in out


class TestRisingSkills:
    def test_returns_none_with_single_run(self, db):
        _seed(
            db,
            lambda rid: [
                _make(rid, "a", created_at=_ts(2026, 3, 10)),
            ],
        )
        assert rising_skills(db) is None

    def test_shows_delta_between_runs(self, db):
        # Run 1: skill with 100 downloads
        run1 = start_run(db)
        pairs1 = [
            _make(
                run1.id,
                "rising",
                created_at=_ts(2026, 3, 10),
                stat_downloads=100,
            ),
        ]
        _insert(db, pairs1)
        complete_run(db, run1.id, total_skills=1)

        # Run 2: same skill now at 500 downloads
        run2 = start_run(db)
        pairs2 = [
            _make(
                run2.id,
                "rising",
                created_at=_ts(2026, 3, 10),
                stat_downloads=500,
            ),
        ]
        _insert(db, pairs2)
        complete_run(db, run2.id, total_skills=1)

        out = rising_skills(db)
        assert out is not None
        assert "RISING SKILLS" in out
        assert "+400" in out

    def test_shows_new_skill_with_no_previous(self, db):
        # Run 1: only skill A
        run1 = start_run(db)
        pairs1 = [
            _make(
                run1.id,
                "old",
                created_at=_ts(2026, 3, 1),
                stat_downloads=1000,
            ),
        ]
        _insert(db, pairs1)
        complete_run(db, run1.id, total_skills=1)

        # Run 2: skill A + brand new skill B
        run2 = start_run(db)
        pairs2 = [
            _make(
                run2.id,
                "old",
                created_at=_ts(2026, 3, 1),
                stat_downloads=1100,
            ),
            _make(
                run2.id,
                "brand_new",
                created_at=_ts(2026, 3, 14),
                stat_downloads=300,
            ),
        ]
        _insert(db, pairs2)
        complete_run(db, run2.id, total_skills=2)

        out = rising_skills(db)
        assert out is not None
        # brand_new has delta of +300 (no previous snapshot)
        assert "+300" in out

    def test_excludes_old_skills(self, db):
        # Run 1
        run1 = start_run(db)
        pairs1 = [
            _make(
                run1.id,
                "ancient",
                created_at=_ts(2026, 1, 1),
                stat_downloads=100,
            ),
        ]
        _insert(db, pairs1)
        complete_run(db, run1.id, total_skills=1)

        # Run 2
        run2 = start_run(db)
        pairs2 = [
            _make(
                run2.id,
                "ancient",
                created_at=_ts(2026, 1, 1),
                stat_downloads=9999,
            ),
        ]
        _insert(db, pairs2)
        complete_run(db, run2.id, total_skills=1)

        # ancient is >14 days old, should return None
        out = rising_skills(db)
        assert out is None
