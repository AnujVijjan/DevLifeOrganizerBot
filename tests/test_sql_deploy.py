import pyodbc
import pytest

from app import sql_deploy
from app.constants import DEPLOY_ENVIRONMENTS


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection

    def execute(self, batch):
        if "FAIL" in batch:
            raise pyodbc.Error("boom")
        self.connection.executed.append(batch)


class FakeConnection:
    def __init__(self):
        self.executed = []
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


@pytest.fixture
def fake_connection(monkeypatch):
    connection = FakeConnection()
    monkeypatch.setattr(sql_deploy.pyodbc, "connect", lambda *args, **kwargs: connection)
    return connection


def test_use_statement_is_rewritten_for_each_env():
    text, count = sql_deploy.rewrite_use_statement("USE [SourceDb]\nGO\nuse[sourcedb]\nSELECT 1\nUSE   [SourceDb]", "uat")

    assert count == 3
    assert text.count("SourceDb_UAT") == 3
    assert "SourceDb]" not in text.replace("SourceDb_UAT]", "")

    dev_text, dev_count = sql_deploy.rewrite_use_statement("USE [SourceDb] SELECT 1", "dev")
    assert dev_count == 1 and "USE [SourceDb_DEV]" in dev_text


def test_text_without_use_statement_is_unchanged():
    text, count = sql_deploy.rewrite_use_statement("SELECT 1", "uat")

    assert (text, count) == ("SELECT 1", 0)


def test_unknown_env_is_rejected():
    with pytest.raises(ValueError):
        sql_deploy.get_deploy_environment("qa")


def test_unconfigured_env_names_the_missing_variables():
    with pytest.raises(RuntimeError, match="PROD_DATABASE_NAME"):
        sql_deploy.get_deploy_environment("prod")


def test_env_order_is_dev_uat_prod():
    assert list(DEPLOY_ENVIRONMENTS) == ["dev", "uat", "prod"]


def test_prod_alone_requires_typed_confirmation():
    assert DEPLOY_ENVIRONMENTS["prod"]["requires_typed_confirmation"]
    assert not DEPLOY_ENVIRONMENTS["dev"]["requires_typed_confirmation"]
    assert not DEPLOY_ENVIRONMENTS["uat"]["requires_typed_confirmation"]


def test_uat_falls_back_to_dev_but_prod_does_not():
    assert DEPLOY_ENVIRONMENTS["uat"]["fallback_pr_env"] == "DEV"
    assert DEPLOY_ENVIRONMENTS["prod"]["fallback_pr_env"] is None
    assert DEPLOY_ENVIRONMENTS["dev"]["fallback_pr_env"] is None


def test_scripts_are_split_on_go_and_committed_per_script(fake_connection):
    procs = [{"path": "a.sql", "content": "USE [SourceDb]\nGO\nSELECT 1\nGO\nSELECT 2"}]

    results = sql_deploy.deploy_stored_procs(procs, "uat")

    assert results == [{"path": "a.sql", "success": True, "use_statements_rewritten": 1}]
    assert fake_connection.executed == ["USE [SourceDb_UAT]", "SELECT 1", "SELECT 2"]
    assert fake_connection.commits == 1
    assert fake_connection.closed


def test_failed_script_rolls_back_and_later_scripts_still_run(fake_connection):
    procs = [
        {"path": "bad.sql", "content": "FAIL"},
        {"path": "good.sql", "content": "SELECT 1"},
    ]

    results = sql_deploy.deploy_stored_procs(procs, "uat")

    assert results[0]["success"] is False and "boom" in results[0]["error"]
    assert results[1]["success"] is True
    assert fake_connection.rollbacks == 1
    assert fake_connection.commits == 1


def test_changed_stored_procedures_skips_removed_non_sql_and_binary(monkeypatch):
    files = [
        {"filename": "keep.sql", "status": "modified"},
        {"filename": "KEEP_TOO.SQL", "status": "added"},
        {"filename": "gone.sql", "status": "removed"},
        {"filename": "readme.md", "status": "modified"},
        {"filename": "binary.sql", "status": "modified"},
    ]
    monkeypatch.setattr(sql_deploy, "get_pr_files", lambda repo, number: files)
    monkeypatch.setattr(
        sql_deploy,
        "get_pr_file_content",
        lambda repo, entry: None if entry["filename"] == "binary.sql" else f"content of {entry['filename']}",
    )

    procs = sql_deploy.get_changed_stored_procedures("repo", 1)

    assert [p["path"] for p in procs] == ["keep.sql", "KEEP_TOO.SQL"]
    assert procs[0]["content"] == "content of keep.sql"
