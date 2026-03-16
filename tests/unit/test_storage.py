"""Unit tests for DuckDB storage layer."""

from app.models import SkillSnapshot
from app.storage import (
    complete_run,
    fail_run,
    get_latest_completed_run_id,
    get_run,
    get_snapshot_count,
    insert_snapshots,
    start_run,
)


def _make_snapshot(run_id: int, skill_id: str = "skill_1", **kwargs) -> SkillSnapshot:
    defaults = {
        "scrape_run_id": run_id,
        "skill_id": skill_id,
        "slug": "test-skill",
        "display_name": "Test Skill",
        "summary": "A test skill",
        "stat_downloads": 100,
        "stat_stars": 10,
    }
    defaults.update(kwargs)
    return SkillSnapshot(**defaults)


class TestSchemaInit:
    def test_tables_exist(self, db):
        tables = db.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
        ).fetchall()
        table_names = {t[0] for t in tables}
        assert "scrape_runs" in table_names
        assert "skill_snapshots" in table_names

    def test_views_exist(self, db):
        views = db.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_type = 'VIEW'"
        ).fetchall()
        view_names = {v[0] for v in views}
        assert "current_skills" in view_names
        assert "previous_skills" in view_names


class TestScrapeRunLifecycle:
    def test_start_run(self, db):
        run = start_run(db)
        assert run.id is not None
        assert run.status == "running"

    def test_complete_run(self, db):
        run = start_run(db)
        complete_run(db, run.id, total_skills=50, new_skills=5, removed_skills=2, changed_skills=10)
        updated = get_run(db, run.id)
        assert updated.status == "completed"
        assert updated.total_skills == 50
        assert updated.new_skills == 5
        assert updated.removed_skills == 2
        assert updated.changed_skills == 10
        assert updated.finished_at is not None
        assert updated.duration_secs is not None

    def test_fail_run(self, db):
        run = start_run(db)
        fail_run(db, run.id)
        updated = get_run(db, run.id)
        assert updated.status == "failed"
        assert updated.finished_at is not None

    def test_sequential_run_ids(self, db):
        run1 = start_run(db)
        run2 = start_run(db)
        assert run2.id > run1.id

    def test_get_nonexistent_run(self, db):
        assert get_run(db, 999) is None


class TestInsertSnapshots:
    def test_insert_and_count(self, db):
        run = start_run(db)
        snapshots = [
            _make_snapshot(run.id, "skill_1"),
            _make_snapshot(run.id, "skill_2"),
            _make_snapshot(run.id, "skill_3"),
        ]
        count = insert_snapshots(db, snapshots)
        assert count == 3
        assert get_snapshot_count(db, run.id) == 3

    def test_insert_empty(self, db):
        count = insert_snapshots(db, [])
        assert count == 0

    def test_snapshot_data_preserved(self, db):
        run = start_run(db)
        snap = _make_snapshot(run.id, "skill_1", display_name="My Skill", stat_downloads=999)
        insert_snapshots(db, [snap])

        row = db.execute(
            "SELECT display_name, stat_downloads FROM skill_snapshots WHERE skill_id = 'skill_1'"
        ).fetchone()
        assert row[0] == "My Skill"
        assert row[1] == 999


class TestLatestCompletedRunId:
    def test_no_completed_runs(self, db):
        start_run(db)
        assert get_latest_completed_run_id(db) is None

    def test_returns_latest(self, db):
        run1 = start_run(db)
        complete_run(db, run1.id, total_skills=10)
        run2 = start_run(db)
        complete_run(db, run2.id, total_skills=20)
        assert get_latest_completed_run_id(db) == run2.id

    def test_ignores_failed(self, db):
        run1 = start_run(db)
        complete_run(db, run1.id, total_skills=10)
        run2 = start_run(db)
        fail_run(db, run2.id)
        assert get_latest_completed_run_id(db) == run1.id


class TestCurrentSkillsView:
    def test_current_skills_returns_latest_completed(self, db):
        run1 = start_run(db)
        insert_snapshots(db, [_make_snapshot(run1.id, "old_skill")])
        complete_run(db, run1.id, total_skills=1)

        run2 = start_run(db)
        insert_snapshots(db, [_make_snapshot(run2.id, "new_skill")])
        complete_run(db, run2.id, total_skills=1)

        rows = db.execute("SELECT skill_id FROM current_skills").fetchall()
        skill_ids = {r[0] for r in rows}
        assert skill_ids == {"new_skill"}
