"""Unit tests for SQL-based diff detection."""

from app.diff import changed_skills, compute_diff, new_skills, removed_skills
from app.models import Skill, SkillMetric
from app.storage import complete_run, insert_skill_metrics, start_run, upsert_skills

# Fields that belong to the Skill model (static metadata).
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

# Fields that belong to SkillMetric (per-run metrics).
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


def _make(run_id: int, skill_id: str = "skill_1", **kwargs) -> tuple[Skill, SkillMetric]:
    """Build a (Skill, SkillMetric) pair with sensible defaults.

    Callers may pass mixed kwargs containing both Skill fields (e.g.
    ``display_name``) and SkillMetric fields (e.g. ``stat_downloads``).
    The helper splits them into the correct model.
    """
    skill_defaults = {
        "skill_id": skill_id,
        "slug": f"slug-{skill_id}",
        "display_name": f"Skill {skill_id}",
        "first_seen_run_id": run_id,
        "last_seen_run_id": run_id,
    }
    metric_defaults = {
        "scrape_run_id": run_id,
        "skill_id": skill_id,
        "stat_downloads": 100,
        "stat_stars": 10,
    }

    # Split caller-provided kwargs into skill vs metric buckets.
    for key, value in kwargs.items():
        if key in _SKILL_FIELDS:
            skill_defaults[key] = value
        elif key in _METRIC_FIELDS:
            metric_defaults[key] = value
        else:
            raise ValueError(f"Unknown field {key!r} for Skill or SkillMetric")

    return Skill(**skill_defaults), SkillMetric(**metric_defaults)


def _setup_two_runs(db, run1_factory, run2_factory):
    """Helper to create two completed runs with given skills.

    Each factory receives a run id and returns a list of
    ``(Skill, SkillMetric)`` tuples produced by :func:`_make`.
    """
    run1 = start_run(db)
    pairs1 = run1_factory(run1.id)
    upsert_skills(db, [s for s, _ in pairs1])
    insert_skill_metrics(db, [m for _, m in pairs1])
    complete_run(db, run1.id, total_skills=len(pairs1))

    run2 = start_run(db)
    pairs2 = run2_factory(run2.id)
    upsert_skills(db, [s for s, _ in pairs2])
    insert_skill_metrics(db, [m for _, m in pairs2])
    complete_run(db, run2.id, total_skills=len(pairs2))

    return run1.id, run2.id


class TestNewSkills:
    def test_detects_new_skill(self, db):
        run1_id, run2_id = _setup_two_runs(
            db,
            lambda rid: [_make(rid, "skill_a")],
            lambda rid: [_make(rid, "skill_a"), _make(rid, "skill_b")],
        )
        result = new_skills(db, run2_id, run1_id)
        assert len(result) == 1
        assert result[0]["skill_id"] == "skill_b"

    def test_no_new_skills(self, db):
        run1_id, run2_id = _setup_two_runs(
            db,
            lambda rid: [_make(rid, "skill_a")],
            lambda rid: [_make(rid, "skill_a")],
        )
        result = new_skills(db, run2_id, run1_id)
        assert len(result) == 0


class TestRemovedSkills:
    def test_detects_removed_skill(self, db):
        run1_id, run2_id = _setup_two_runs(
            db,
            lambda rid: [_make(rid, "skill_a"), _make(rid, "skill_b")],
            lambda rid: [_make(rid, "skill_a")],
        )
        result = removed_skills(db, run2_id, run1_id)
        assert len(result) == 1
        assert result[0]["skill_id"] == "skill_b"

    def test_no_removed_skills(self, db):
        run1_id, run2_id = _setup_two_runs(
            db,
            lambda rid: [_make(rid, "skill_a")],
            lambda rid: [_make(rid, "skill_a")],
        )
        result = removed_skills(db, run2_id, run1_id)
        assert len(result) == 0


class TestChangedSkills:
    def test_detects_stat_change(self, db):
        run1_id, run2_id = _setup_two_runs(
            db,
            lambda rid: [_make(rid, "skill_a", stat_downloads=100)],
            lambda rid: [_make(rid, "skill_a", stat_downloads=200)],
        )
        result = changed_skills(db, run2_id, run1_id)
        assert len(result) == 1
        assert result[0]["changes"]["stat_downloads"]["from"] == 100
        assert result[0]["changes"]["stat_downloads"]["to"] == 200

    def test_display_name_change_not_detected(self, db):
        """display_name is a static Skill field, not a tracked metric.

        changed_skills only compares SkillMetric fields listed in
        TRACKED_FIELDS, so a display_name-only change must *not* appear.
        """
        run1_id, run2_id = _setup_two_runs(
            db,
            lambda rid: [_make(rid, "skill_a", display_name="Old Name")],
            lambda rid: [_make(rid, "skill_a", display_name="New Name")],
        )
        result = changed_skills(db, run2_id, run1_id)
        assert len(result) == 0

    def test_no_changes(self, db):
        run1_id, run2_id = _setup_two_runs(
            db,
            lambda rid: [_make(rid, "skill_a", stat_downloads=100)],
            lambda rid: [_make(rid, "skill_a", stat_downloads=100)],
        )
        result = changed_skills(db, run2_id, run1_id)
        assert len(result) == 0


class TestComputeDiff:
    def test_full_diff(self, db):
        run1_id, run2_id = _setup_two_runs(
            db,
            lambda rid: [
                _make(rid, "kept", stat_downloads=10),
                _make(rid, "removed"),
                _make(rid, "changed", stat_stars=5),
            ],
            lambda rid: [
                _make(rid, "kept", stat_downloads=10),
                _make(rid, "added"),
                _make(rid, "changed", stat_stars=50),
            ],
        )
        diff = compute_diff(db, run2_id, run1_id)
        assert diff["current_run_id"] == run2_id
        assert diff["previous_run_id"] == run1_id
        assert len(diff["new"]) == 1
        assert len(diff["removed"]) == 1
        assert len(diff["changed"]) == 1
        assert diff["new"][0]["skill_id"] == "added"
        assert diff["removed"][0]["skill_id"] == "removed"
        assert diff["changed"][0]["skill_id"] == "changed"
