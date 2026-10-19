import pytest

import wizard

TICKET_LINK = "https://example.atlassian.net/browse/PROJ-5"
PR_LINK = "https://github.com/o/MyRepo/pull/5"
QUIT = "9"
COMMAND_NAMES = [
    "addtask", "listtasks", "marktaskdone", "deepworkon", "deepworkoff", "standup",
    "createpr", "createprodpr", "createuatpr", "comparepr", "deploysp",
]


class Cancel:
    pass


CTRL_C = Cancel()


@pytest.fixture
def drive(monkeypatch, capsys):
    def run(inputs, links=None, failing=None):
        calls = []

        def recorder(name):
            def command(namespace):
                calls.append((name, namespace))
                if failing and name in failing:
                    raise SystemExit(1)

            return command

        answers = iter(inputs)

        def fake_input(prompt=""):
            answer = next(answers)
            if answer is CTRL_C:
                raise KeyboardInterrupt
            return answer

        link_map = links or {}
        monkeypatch.setattr("builtins.input", fake_input)
        monkeypatch.setattr(wizard, "get_env_pr_links", lambda ticket, env: link_map.get(env, []))
        wizard.run({name: recorder(name) for name in COMMAND_NAMES})
        return calls, capsys.readouterr().out

    return run


def test_createpr_with_a_custom_branch_and_no_jira_changes(drive):
    calls, _ = drive(["1", TICKET_LINK, "MyRepo", "feat-x", "", "", "y", QUIT])

    name, ns = calls[0]
    assert name == "createpr"
    assert (ns.ticket, ns.repo, ns.branch, ns.legacy_args) == ("PROJ-5", "MyRepo", "feat-x", [])
    assert ns.transition is None and ns.assign is None


def test_createpr_defaults_the_branch_and_accepts_default_status_and_assignee(drive):
    calls, _ = drive(["1", "PROJ-5", "MyRepo", "", "y", "", "y", "", "", QUIT])

    ns = calls[0][1]
    assert ns.branch is None
    assert ns.transition == "CodeReview" and ns.assign == "qa"


def test_createpr_shows_a_quoted_equivalent_command(drive):
    calls, out = drive(["1", "PROJ-5", "MyRepo", "", "y", "In QA", "y", "a@example.com", "y", QUIT])

    ns = calls[0][1]
    assert (ns.transition, ns.assign) == ("In QA", "a@example.com")
    assert 'python cli.py createpr PROJ-5 --repo MyRepo --transition "In QA" --assign a@example.com' in out


def test_declining_the_confirmation_runs_nothing(drive):
    calls, _ = drive(["1", "PROJ-5", "MyRepo", "", "", "", "n", QUIT])

    assert calls == []


def test_uat_offers_the_repos_found_on_the_ticket(drive):
    links = {"DEV": [{"repo": "A", "url": "u"}, {"repo": "B", "url": "u"}]}

    calls, _ = drive(["2", "PROJ-5", "3", "", "y", QUIT], links=links)

    name, ns = calls[0]
    assert name == "createuatpr" and ns.repo == "B" and ns.branch is None


def test_prod_with_all_repos_and_a_custom_branch(drive):
    links = {"DEV": [{"repo": "A", "url": "u"}, {"repo": "B", "url": "u"}]}

    calls, _ = drive(["3", "PROJ-5", "1", "my-branch", "y", QUIT], links=links)

    name, ns = calls[0]
    assert name == "createprodpr" and ns.repo is None and ns.branch == "my-branch"


def test_a_single_repo_is_selected_automatically(drive):
    calls, _ = drive(["3", "PROJ-5", "", "y", QUIT], links={"DEV": [{"repo": "Solo", "url": "u"}]})

    assert calls[0][1].repo == "Solo"


def test_compare_runs_without_confirmation_and_uses_every_environment(drive):
    links = {"UAT": [{"repo": "R", "url": "u"}], "PROD": [{"repo": "R", "url": "u"}]}

    calls, _ = drive(["4", "PROJ-5", QUIT], links=links)

    name, ns = calls[0]
    assert name == "comparepr" and ns.repo == "R"


def test_deploy_menu_order_is_dev_uat_prod(drive):
    for choice, env in (("1", "dev"), ("2", "uat")):
        calls, _ = drive(["5", choice, "PROJ-9", "", QUIT])
        assert calls[0][1].env == env


def test_deploy_to_uat_accepts_a_github_pr_link(drive):
    calls, _ = drive(["5", "2", PR_LINK, QUIT])

    ns = calls[0][1]
    assert ns.env == "uat" and ns.ticket == PR_LINK and ns.repo is None and ns.yes is False


def test_deploy_to_prod_rejects_a_pr_link_and_asks_again(drive):
    calls, out = drive(["5", "3", PR_LINK, "PROJ-9", "", QUIT])

    ns = calls[0][1]
    assert ns.env == "prod" and ns.ticket == "PROJ-9"
    assert "Could not find a Jira ticket key" in out


def test_deploy_passes_the_repo(drive):
    calls, _ = drive(["5", "2", "PROJ-9", "my-repo", QUIT])

    assert calls[0][1].repo == "my-repo"


def test_tasks_add_list_and_done(drive):
    calls, _ = drive(["7", "1", "do the thing", QUIT])
    assert calls[0][0] == "addtask" and calls[0][1].task == ["do", "the", "thing"]

    calls, _ = drive(["7", "2", QUIT])
    assert calls[0][0] == "listtasks"

    calls, _ = drive(["7", "3", "4", QUIT])
    assert [name for name, _ in calls] == ["listtasks", "marktaskdone"]
    assert calls[-1][1].task_id == 4


def test_deep_work_on_and_off(drive):
    calls, _ = drive(["8", "1", "90", QUIT])
    assert calls[0][0] == "deepworkon" and calls[0][1].minutes == 90

    calls, _ = drive(["8", "2", QUIT])
    assert calls[0][0] == "deepworkoff"


def test_standup(drive):
    calls, _ = drive(["6", QUIT])

    assert calls[0][0] == "standup"


def test_a_failing_command_returns_to_the_menu(drive):
    calls, out = drive(["1", "PROJ-5", "R", "", "", "", "y", "6", QUIT], failing={"createpr"})

    assert [name for name, _ in calls] == ["createpr", "standup"]
    assert "exit code 1" in out


def test_ctrl_c_cancels_a_flow_then_exits_from_the_menu(drive):
    calls, out = drive(["1", CTRL_C, CTRL_C])

    assert calls == []
    assert "Cancelled" in out and "Bye" in out
