"""Unit tests for ClawHub skills scraper."""

import json
from unittest.mock import MagicMock, patch

from app.scraper import build_payload, extract_skill_data, fetch_all_skills, save_skills

SAMPLE_ITEM = {
    "latestVersion": {
        "_creationTime": 1769673454302.0,
        "_id": "k97e2055wfhrf2wk8ykn04x98x804v6c",
        "changelog": "web-search 1.0.0\n\n- Initial release.",
        "changelogSource": "auto",
        "createdAt": 1769673454302.0,
        "version": "1.0.0",
    },
    "owner": {
        "_creationTime": 0.0,
        "_id": "kn7cz85m29bj398zc6mnggkv19805nzz",
        "displayName": "billyutw",
        "handle": "billyutw",
        "image": "https://avatars.githubusercontent.com/u/26513936?v=4",
        "name": "billyutw",
    },
    "ownerHandle": "billyutw",
    "skill": {
        "_creationTime": 1769673454302.0,
        "_id": "kd7car3k6zj36bgjmcsxmyb01x805ydd",
        "badges": {},
        "createdAt": 1769673454302.0,
        "displayName": "Web Search",
        "latestVersionId": "k97e2055wfhrf2wk8ykn04x98x804v6c",
        "ownerUserId": "kn7cz85m29bj398zc6mnggkv19805nzz",
        "slug": "web-search",
        "stats": {
            "comments": 1.0,
            "downloads": 18523.0,
            "installsAllTime": 340.0,
            "installsCurrent": 326.0,
            "stars": 23.0,
            "versions": 1.0,
        },
        "summary": "Search the web using DuckDuckGo's API.",
        "tags": {"latest": "k97e2055wfhrf2wk8ykn04x98x804v6c"},
        "updatedAt": 1773630571430.0,
    },
}


class TestBuildPayload:
    def test_first_page_no_cursor(self):
        payload = build_payload(None)
        args = payload["args"][0]
        assert args["paginationOpts"]["cursor"] is None
        assert args["paginationOpts"]["numItems"] == 180
        assert args["sort"] == "downloads"
        assert args["dir"] == "desc"

    def test_subsequent_page_with_cursor(self):
        cursor = "abc123cursor"
        payload = build_payload(cursor)
        args = payload["args"][0]
        assert args["paginationOpts"]["cursor"] == cursor

    def test_custom_num_items(self):
        payload = build_payload(None, num_items=50)
        args = payload["args"][0]
        assert args["paginationOpts"]["numItems"] == 50

    def test_payload_structure(self):
        payload = build_payload(None)
        assert payload["path"] == "skills:listPublicPageV2"
        assert payload["format"] == "convex_encoded_json"
        assert isinstance(payload["args"], list)
        assert len(payload["args"]) == 1


class TestExtractSkillData:
    def test_extracts_all_fields(self):
        result = extract_skill_data(SAMPLE_ITEM)

        assert result["skill_id"] == "kd7car3k6zj36bgjmcsxmyb01x805ydd"
        assert result["slug"] == "web-search"
        assert result["display_name"] == "Web Search"
        assert result["owner_handle"] == "billyutw"

    def test_extracts_stats(self):
        result = extract_skill_data(SAMPLE_ITEM)
        stats = result["stats"]

        assert stats["downloads"] == 18523.0
        assert stats["stars"] == 23.0
        assert stats["comments"] == 1.0
        assert stats["installs_all_time"] == 340.0
        assert stats["installs_current"] == 326.0
        assert stats["versions"] == 1.0

    def test_extracts_owner(self):
        result = extract_skill_data(SAMPLE_ITEM)
        owner = result["owner"]

        assert owner["handle"] == "billyutw"
        assert owner["display_name"] == "billyutw"
        assert "github" in owner["image"]

    def test_extracts_latest_version(self):
        result = extract_skill_data(SAMPLE_ITEM)
        version = result["latest_version"]

        assert version["version"] == "1.0.0"
        assert version["changelog_source"] == "auto"

    def test_handles_missing_fields(self):
        result = extract_skill_data({})
        assert result["skill_id"] is None
        assert result["slug"] is None
        assert result["stats"]["downloads"] == 0


class TestFetchAllSkills:
    @patch("app.scraper.httpx.Client")
    def test_single_page_done(self, mock_client_cls):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "status": "success",
            "value": {
                "continueCursor": None,
                "isDone": True,
                "page": [SAMPLE_ITEM],
            },
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.post.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_client

        skills = fetch_all_skills()
        assert len(skills) == 1
        assert skills[0]["slug"] == "web-search"

    @patch("app.scraper.time.sleep")
    @patch("app.scraper.httpx.Client")
    def test_multi_page_pagination(self, mock_client_cls, mock_sleep):
        response_page1 = MagicMock()
        response_page1.json.return_value = {
            "status": "success",
            "value": {
                "continueCursor": "next_cursor_123",
                "isDone": False,
                "page": [SAMPLE_ITEM],
            },
        }
        response_page1.raise_for_status = MagicMock()

        response_page2 = MagicMock()
        response_page2.json.return_value = {
            "status": "success",
            "value": {
                "continueCursor": None,
                "isDone": True,
                "page": [SAMPLE_ITEM],
            },
        }
        response_page2.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.post.side_effect = [response_page1, response_page2]
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_client

        skills = fetch_all_skills()
        assert len(skills) == 2
        assert mock_client.post.call_count == 2

    @patch("app.scraper.httpx.Client")
    def test_handles_error_status(self, mock_client_cls):
        mock_response = MagicMock()
        mock_response.json.return_value = {"status": "error"}
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.post.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_client

        skills = fetch_all_skills()
        assert len(skills) == 0


class TestSaveSkills:
    def test_saves_json_file(self, tmp_path):
        skills = [extract_skill_data(SAMPLE_ITEM)]

        with patch("app.scraper.OUTPUT_DIR", tmp_path):
            with patch("app.scraper.OUTPUT_FILE", tmp_path / "skills.json"):
                path = save_skills(skills)

        saved = json.loads(path.read_text())
        assert len(saved) == 1
        assert saved[0]["slug"] == "web-search"
