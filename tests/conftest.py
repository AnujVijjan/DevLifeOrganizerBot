"""
Pytest setup: keeps tests independent of any real .env and fixes the config
the application reads at import time.
"""

import os
import sys

import dotenv

dotenv.load_dotenv = lambda *args, **kwargs: False

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

UNSET = [
    "JIRA_STATUS_CODE_REVIEW",
    "SP_DEPLOY_DEFAULT_REPO",
    "REPO_CONFIG_FILE",
    "PROD_DATABASE_NAME",
    "PROD_DATABASE_CONNECTION_STRING",
]

TEST_ENV = {
    "GITHUB_TOKEN": "test-token",
    "GITHUB_ORG": "test-org",
    "GITHUB_USERNAME": "tester",
    "JIRA_BASE_URL": "https://jira.example.com",
    "JIRA_EMAIL": "tester@example.com",
    "JIRA_API_TOKEN": "test-token",
    "JIRA_QA_TESTER_FIELD": "customfield_test",
    "SP_SOURCE_DATABASE": "SourceDb",
    "DEV_DATABASE_NAME": "SourceDb_DEV",
    "DEV_DATABASE_CONNECTION_STRING": "dev-connection",
    "UAT_DATABASE_NAME": "SourceDb_UAT",
    "UAT_DATABASE_CONNECTION_STRING": "uat-connection",
}

for key in UNSET:
    os.environ.pop(key, None)
os.environ.update(TEST_ENV)

import json

import pytest

from app import helper


@pytest.fixture
def repo_config(tmp_path, monkeypatch):
    """
    Writes a repo_config.json with the given repos and points the helper at it.
    """

    def write(repos):
        path = tmp_path / "repo_config.json"
        path.write_text(json.dumps({"repos": repos}), encoding="utf-8")
        monkeypatch.setattr(helper, "REPO_CONFIG_FILE", str(path))
        helper.load_repo_config.cache_clear()

    yield write
    helper.load_repo_config.cache_clear()
