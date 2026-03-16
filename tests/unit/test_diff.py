"""Unit tests for SQL-based diff detection."""

from app.diff import changed_skills, compute_diff, new_skills, removed_skills
from app.models import SkillSnapshot
from app.storage import complete_run, insert_snapshots, start_run


def _make_snapshot(run_id: int, skill_id: str = "skill_1", **kwargs) -> SkillSnapshot:
    defaults = {
        "scrape_run_id": run_id,
        "skill_id": skill_id,
        "slug": f"slug-{skill_id}",
        "display_name": f"Skill {skill_id}",
        "stat_downloads": 100,
        "stat_stars": 10,
    }
    defaults.update(kwargs)
    return SkillSnapshot(**defaults)


def _setup_two_runs(db, run1_skills, run2_skills):
    """Helper to create two completed runs with given skills."""
    run1 = start_run(db)
    insert_snapshots(db, run1_skills(run1.id))
    complete_run(db, run1.id, total_skills=len(run1_skills(run1.id)))

    run2 = start_run(db)
    insert_snapshots(db, run2_skills(run2.id))
    complete_run(db, run2.id, total_skills=len(run2_skills(run2.id)))

    return run1.id, run2.id


class TestNewSkills:
    def test_detects_new_skill(self, db):
        run1_id, run2_id = _setup_two_runs(
            db,
            lambda rid: [_make_snapshot(rid, "skill_a")],
            lambda rid: [_make_snapshot(rid, "skill_a"), _make_snapshot(rid, "skill_b")],
        )
        result = new_skills(db, run2_id, run1_id)
        assert len(result) == 1
        assert result[0]["skill_id"] == "skill_b"

    def test_no_new_skills(self, db):
        run1_id, run2_id = _setup_two_runs(
            db,
            lambda rid: [_make_snapshot(rid, "skill_a")],
            lambda rid: [_make_snapshot(rid, "skill_a")],
        )
        result = new_skills(db, run2_id, run1_id)
        assert len(result) == 0


class TestRemovedSkills:
    def test_detects_removed_skill(self, db):
        run1_id, run2_id = _setup_two_runs(
            db,
            lambda rid: [_make_snapshot(rid, "skill_a"), _make_snapshot(rid, "skill_b")],
            lambda rid: [_make_snapshot(rid, "skill_a")],
        )
        result = removed_skills(db, run2_id, run1_id)
        assert len(result) == 1
        assert result[0]["skill_id"] == "skill_b"

    def test_no_removed_skills(self, db):
        run1_id, run2_id = _setup_two_runs(
            db,
            lambda rid: [_make_snapshot(rid, "skill_a")],
            lambda rid: [_make_snapshot(rid, "skill_a")],
        )
        result = removed_skills(db, run2_id, run1_id)
        assert len(result) == 0


class TestChangedSkills:
    def test_detects_stat_change(self, db):
        run1_id, run2_id = _setup_two_runs(
            db,
            lambda rid: [_make_snapshot(rid, "skill_a", stat_downloads=100)],
            lambda rid: [_make_snapshot(rid, "skill_a", stat_downloads=200)],
        )
        result = changed_skills(db, run2_id, run1_id)
        assert len(result) == 1
        assert result[0]["changes"]["stat_downloads"]["from"] == 100
        assert result[0]["changes"]["stat_downloads"]["to"] == 200

    def test_detects_name_change(self, db):
        run1_id, run2_id = _setup_two_runs(
            db,
            lambda rid: [_make_snapshot(rid, "skill_a", display_name="Old Name")],
            lambda rid: [_make_snapshot(rid, "skill_a", display_name="New Name")],
        )
        result = changed_skills(db, run2_id, run1_id)
        assert len(result) == 1
        assert "display_name" in result[0]["changes"]

    def test_no_changes(self, db):
        run1_id, run2_id = _setup_two_runs(
            db,
            lambda rid: [_make_snapshot(rid, "skill_a", stat_downloads=100)],
            lambda rid: [_make_snapshot(rid, "skill_a", stat_downloads=100)],
        )
        result = changed_skills(db, run2_id, run1_id)
        assert len(result) == 0


class TestComputeDiff:
    def test_full_diff(self, db):
        run1_id, run2_id = _setup_two_runs(
            db,
            lambda rid: [
                _make_snapshot(rid, "kept", stat_downloads=10),
                _make_snapshot(rid, "removed"),
                _make_snapshot(rid, "changed", stat_stars=5),
            ],
            lambda rid: [
                _make_snapshot(rid, "kept", stat_downloads=10),
                _make_snapshot(rid, "added"),
                _make_snapshot(rid, "changed", stat_stars=50),
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
