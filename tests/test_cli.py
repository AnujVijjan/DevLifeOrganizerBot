import argparse
import sys
from types import SimpleNamespace

import pytest

import cli
import wizard
from app.constants import DEPLOY_ENVIRONMENTS

BRANCHES = ["integration", "main", "PROJ-1", "PROJ-2"]
PR_URL = "https://github.com/test-org/MyRepo/pull/9"
NO_WORKFLOW = {"status_before": None, "transitioned": False, "assigned": False}


def createpr_args(**overrides):
    values = dict(ticket="PROJ-1", legacy_args=[], branch=None, repo="MyRepo", transition=None, assign=None)
    values.update(overrides)
    return argparse.Namespace(**values)


@pytest.fixture
def github(monkeypatch, repo_config):
    repo_config({"MyRepo": {"dev_branch": "integration", "prod_branch": "main"}})
    state = SimpleNamespace(created=[], workflow=[], branch_shas=[])
    monkeypatch.setattr(cli, "get_repo_branches", lambda repo: BRANCHES)
    monkeypatch.setattr(cli, "validate_branch_exists", lambda repo, branch: None)
    monkeypatch.setattr(cli, "get_existing_pr", lambda *args: None)
    monkeypatch.setattr(cli, "jira_weblink_exists", lambda *args: True)
    monkeypatch.setattr(cli, "create_pull_request", lambda **kwargs: state.created.append(kwargs) or {"html_url": PR_URL})
    monkeypatch.setattr(cli, "apply_jira_workflow", lambda *args: state.workflow.append(args) or NO_WORKFLOW)
    return state


def test_createpr_targets_the_configured_dev_branch_and_leaves_jira_alone(github):
    cli.cmd_createpr(createpr_args(branch="PROJ-2"))

    assert github.created[0]["dev_branch"] == "integration"
    assert github.workflow == [("PROJ-1", None, None)]


def test_createpr_passes_transition_and_assign_through(github):
    cli.cmd_createpr(createpr_args(transition="In QA", assign="a@example.com", branch="PROJ-2"))

    assert github.workflow == [("PROJ-1", "In QA", "a@example.com")]


def test_createpr_refuses_a_pr_from_the_dev_branch_into_itself(github):
    with pytest.raises(SystemExit) as exit_info:
        cli.cmd_createpr(createpr_args(branch="integration"))

    assert exit_info.value.code == 1
    assert github.created == []


def test_createprodpr_branches_from_the_configured_prod_branch(github, monkeypatch):
    links = [{"repo": "MyRepo", "url": PR_URL}]
    monkeypatch.setattr(cli, "get_dev_pr_links", lambda ticket: links)
    monkeypatch.setattr(cli, "get_pr_commits", lambda repo, number: [])
    monkeypatch.setattr(cli, "get_branch_sha", lambda repo, branch: github.branch_shas.append(branch) or "sha")
    monkeypatch.setattr(cli, "create_branch", lambda *args: None)
    monkeypatch.setattr(cli, "cherry_pick_commits_onto_branch", lambda *args: 0)
    monkeypatch.setattr(cli, "get_existing_pr", lambda *args: {"html_url": "existing", "number": 1})

    cli.cmd_createprodpr(argparse.Namespace(ticket="PROJ-1", legacy_args=[], branch=None, repo=None))

    assert github.branch_shas == ["main"]


LINKS = {
    "DEV": [{"repo": "r", "url": "https://github.com/test-org/r/pull/1"}],
    "UAT": [],
    "PROD": [],
}


@pytest.fixture
def deploy(monkeypatch):
    state = SimpleNamespace(deployed=[], prompts=[], answers=[], links=dict(LINKS))
    procs = [{"path": "a.sql", "status": "modified", "content": "x"}]
    result = [{"path": "a.sql", "success": True, "use_statements_rewritten": 1}]

    def fake_input(prompt=""):
        state.prompts.append(prompt)
        return state.answers.pop(0)

    monkeypatch.setattr(cli, "get_env_pr_links", lambda ticket, env: state.links.get(env, []))
    monkeypatch.setattr(cli, "get_changed_stored_procedures", lambda repo, number: procs)
    monkeypatch.setattr(cli, "deploy_stored_procs", lambda items, env: state.deployed.append(env) or result)
    monkeypatch.setattr("builtins.input", fake_input)
    return state


def deploy_args(**overrides):
    values = dict(ticket="PROJ-1", env="uat", repo=None, yes=False)
    values.update(overrides)
    return argparse.Namespace(**values)


@pytest.fixture
def prod_configured(monkeypatch):
    prod = DEPLOY_ENVIRONMENTS["prod"]
    monkeypatch.setitem(prod, "target_database", "SourceDb")
    monkeypatch.setitem(prod, "connection_string", "prod-connection")


def test_uat_reads_the_dev_pr_when_there_is_no_uat_pr(deploy):
    cli.cmd_deploysp(deploy_args(yes=True))

    assert deploy.deployed == ["uat"]
    assert deploy.prompts == []


def test_dev_deploy_reads_the_dev_pr_and_asks_for_confirmation(deploy):
    deploy.answers = ["y"]

    cli.cmd_deploysp(deploy_args(env="dev"))

    assert deploy.deployed == ["dev"]
    assert len(deploy.prompts) == 1


def test_declining_the_prompt_deploys_nothing(deploy):
    deploy.answers = ["n"]

    cli.cmd_deploysp(deploy_args(env="dev"))

    assert deploy.deployed == []


def test_prod_without_configuration_exits_before_any_work(deploy):
    with pytest.raises(SystemExit) as exit_info:
        cli.cmd_deploysp(deploy_args(env="prod"))

    assert exit_info.value.code == 2
    assert deploy.deployed == []


def test_prod_rejects_a_direct_pr_link(deploy, prod_configured):
    with pytest.raises(SystemExit) as exit_info:
        cli.cmd_deploysp(deploy_args(env="prod", ticket="https://github.com/o/r/pull/5"))

    assert exit_info.value.code == 2
    assert deploy.deployed == []


def test_prod_has_no_dev_fallback(deploy, prod_configured):
    with pytest.raises(SystemExit) as exit_info:
        cli.cmd_deploysp(deploy_args(env="prod"))

    assert exit_info.value.code == 1
    assert deploy.deployed == []


def test_prod_requires_the_typed_ticket_key_even_with_yes(deploy, prod_configured):
    deploy.links["PROD"] = [{"repo": "r", "url": "https://github.com/test-org/r/pull/2"}]
    deploy.answers = ["wrong"]

    cli.cmd_deploysp(deploy_args(env="prod", yes=True))
    assert deploy.deployed == []
    assert len(deploy.prompts) == 1

    deploy.answers = ["proj-1"]
    cli.cmd_deploysp(deploy_args(env="prod", yes=True))
    assert deploy.deployed == ["prod"]


def test_deploysptouat_is_an_alias_for_uat(monkeypatch):
    seen = []
    monkeypatch.setattr(cli, "cmd_deploysp", lambda args: seen.append(args.env))
    monkeypatch.setattr(sys, "argv", ["cli.py", "deploysptouat", "PROJ-1"])

    cli.main()

    assert seen == ["uat"]


@pytest.mark.parametrize(
    "argv, expected",
    [
        (["createpr", "P-1", "--repo", "R"], (None, None)),
        (["createpr", "P-1", "--repo", "R", "--transition", "--assign"], ("CodeReview", "qa")),
        (["createpr", "P-1", "--repo", "R", "--transition", "In QA", "--assign", "a@example.com"], ("In QA", "a@example.com")),
    ],
)
def test_createpr_flag_parsing(monkeypatch, argv, expected):
    seen = []
    monkeypatch.setattr(cli, "cmd_createpr", lambda args: seen.append((args.transition, args.assign)))
    monkeypatch.setattr(sys, "argv", ["cli.py"] + argv)

    cli.main()

    assert seen == [expected]


def test_removed_no_transition_flag_is_rejected(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["cli.py", "createpr", "P-1", "--repo", "R", "--no-transition"])

    with pytest.raises(SystemExit) as exit_info:
        cli.main()

    assert exit_info.value.code == 2


def test_no_arguments_starts_interactive_mode(monkeypatch):
    seen = []
    monkeypatch.setattr(cli, "cmd_interactive", lambda args: seen.append(True))
    monkeypatch.setattr(sys, "argv", ["cli.py"])

    cli.main()

    assert seen == [True]


def test_interactive_mode_exposes_every_command(monkeypatch):
    captured = {}
    monkeypatch.setattr(wizard, "run", lambda commands: captured.update(commands))

    cli.cmd_interactive(argparse.Namespace())

    assert set(captured) == {
        "addtask", "listtasks", "marktaskdone", "deepworkon", "deepworkoff", "standup",
        "createpr", "createprodpr", "createuatpr", "comparepr", "deploysp",
    }
