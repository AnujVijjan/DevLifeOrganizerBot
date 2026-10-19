import pytest

from app import helper


def test_override_is_used_case_insensitively(repo_config):
    repo_config({"MyRepo": {"dev_branch": "integration", "prod_branch": "main"}})
    branches = ["integration", "main", "uat"]

    assert helper.detect_dev_branch(branches, "myrepo") == "integration"
    assert helper.detect_prod_branch(branches, "MYREPO") == "main"
    assert helper.detect_uat_branch(branches, "MyRepo") == "uat"


def test_override_naming_a_missing_branch_errors(repo_config):
    repo_config({"MyRepo": {"dev_branch": "integration"}})

    with pytest.raises(Exception, match="not found"):
        helper.detect_dev_branch(["main"], "MyRepo")


def test_repo_without_override_falls_back_to_detection(repo_config):
    repo_config({"MyRepo": {"dev_branch": "integration"}})

    assert helper.detect_dev_branch(["develop", "main"], "Other") == "develop"
    assert helper.detect_dev_branch(["develop", "main"]) == "develop"


def test_missing_config_file_means_no_overrides(tmp_path, monkeypatch):
    monkeypatch.setattr(helper, "REPO_CONFIG_FILE", str(tmp_path / "absent.json"))
    helper.load_repo_config.cache_clear()

    assert helper.detect_prod_branch(["prod", "main"], "MyRepo") == "prod"
    helper.load_repo_config.cache_clear()


def test_undetectable_branch_errors(repo_config):
    repo_config({})

    with pytest.raises(Exception, match="Unable to determine"):
        helper.detect_prod_branch(["main"], "Other")


def test_feature_branch_must_differ_from_dev_branch():
    helper.ensure_feature_branch_differs("PROJ-2", "PROJ-1")

    with pytest.raises(Exception, match="same as the dev branch"):
        helper.ensure_feature_branch_differs("PROJ-1", "PROJ-1")
