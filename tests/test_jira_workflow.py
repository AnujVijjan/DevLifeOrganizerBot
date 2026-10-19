import pytest

from app import helper

TRANSITIONS = [
    {"id": "11", "name": "Send to review", "to": {"name": "CodeReview"}},
    {"id": "12", "name": "Done"},
]

USERS = [
    {"accountId": "1", "displayName": "Ann Lee", "emailAddress": "ann@example.com", "accountType": "atlassian", "active": True},
    {"accountId": "2", "displayName": "Ann Smith", "accountType": "atlassian", "active": True},
    {"accountId": "3", "displayName": "Bot", "accountType": "app", "active": True},
]


class Response:
    def __init__(self, data, status_code=200):
        self.status_code = status_code
        self._data = data
        self.text = ""

    def json(self):
        return self._data


@pytest.fixture
def jira(monkeypatch):
    calls = {"transitions": [], "assignments": []}
    monkeypatch.setattr(helper, "get_jira_issue_status", lambda ticket: "In Progress")
    monkeypatch.setattr(helper, "get_jira_transitions", lambda ticket: TRANSITIONS)
    monkeypatch.setattr(helper, "transition_jira_issue", lambda ticket, tid: calls["transitions"].append((ticket, tid)))
    monkeypatch.setattr(helper, "assign_jira_issue", lambda ticket, account: calls["assignments"].append((ticket, account)))
    monkeypatch.setattr(helper, "get_qa_tester_account_id", lambda ticket: "qa-account")
    monkeypatch.setattr(helper, "find_jira_user_account_id", lambda query: "user-account")
    monkeypatch.setattr(helper, "get_jira_myself_account_id", lambda: "me-account")
    return calls


def test_transition_matches_name_or_destination_status_case_insensitively(jira):
    assert helper.find_jira_transition("P-1", "codereview")["id"] == "11"
    assert helper.find_jira_transition("P-1", "Send to review")["id"] == "11"
    assert helper.find_jira_transition("P-1", "done")["id"] == "12"
    assert helper.find_jira_transition("P-1", "Nope") is None


def test_no_options_leaves_the_ticket_untouched(jira):
    result = helper.apply_jira_workflow("P-1")

    assert result == {"status_before": None, "transitioned": False, "assigned": False}
    assert jira == {"transitions": [], "assignments": []}


def test_transition_and_qa_assignment(jira):
    result = helper.apply_jira_workflow("P-1", "CodeReview", "qa")

    assert result == {"status_before": "In Progress", "transitioned": True, "assigned": True}
    assert jira["transitions"] == [("P-1", "11")]
    assert jira["assignments"] == [("P-1", "qa-account")]


def test_assign_without_transition(jira):
    result = helper.apply_jira_workflow("P-1", None, "someone@example.com")

    assert result["assigned"] and not result["transitioned"]
    assert jira["assignments"] == [("P-1", "user-account")]
    assert jira["transitions"] == []


def test_assign_me(jira):
    helper.apply_jira_workflow("P-1", None, "me")

    assert jira["assignments"] == [("P-1", "me-account")]


def test_unavailable_transition_is_reported_not_raised(jira):
    result = helper.apply_jira_workflow("P-1", "Unknown Status")

    assert result == {"status_before": "In Progress", "transitioned": False, "assigned": False}
    assert jira["transitions"] == []


def test_unresolvable_assignee_fails_before_the_ticket_changes(jira, monkeypatch):
    monkeypatch.setattr(helper, "get_qa_tester_account_id", lambda ticket: None)

    with pytest.raises(Exception, match="not configured"):
        helper.apply_jira_workflow("P-1", "CodeReview", "qa")

    assert jira["transitions"] == []


def test_user_search_prefers_exact_match_and_rejects_ambiguity(monkeypatch):
    monkeypatch.setattr(helper.requests, "get", lambda *args, **kwargs: Response(USERS))

    assert helper.find_jira_user_account_id("ann@example.com") == "1"
    assert helper.find_jira_user_account_id("Ann Smith") == "2"

    with pytest.raises(Exception, match="several"):
        helper.find_jira_user_account_id("ann")


def test_user_search_with_no_match(monkeypatch):
    monkeypatch.setattr(helper.requests, "get", lambda *args, **kwargs: Response([]))

    with pytest.raises(Exception, match="No Jira user"):
        helper.find_jira_user_account_id("zed")


def test_pr_link_title_round_trip(monkeypatch):
    assert helper.format_pr_link_title("my-repo", "UAT") == "my-repo (UAT)"

    links = [
        {"object": {"title": "repo-a (DEV)", "url": "https://github.com/o/repo-a/pull/1"}},
        {"object": {"title": "repo-b (UAT)", "url": "https://github.com/o/repo-b/pull/2"}},
        {"object": {"title": "Design doc", "url": "https://example.com"}},
    ]
    monkeypatch.setattr(helper, "get_jira_remote_links", lambda ticket: links)

    assert helper.get_dev_pr_links("P-1") == [
        {"url": "https://github.com/o/repo-a/pull/1", "title": "repo-a (DEV)", "repo": "repo-a"}
    ]
    assert [link["repo"] for link in helper.get_uat_pr_links("P-1")] == ["repo-b"]
    assert helper.get_prod_pr_links("P-1") == []


def test_add_env_pr_link_posts_the_tagged_title(monkeypatch):
    posted = {}

    def fake_post(url, headers, json):
        posted.update(url=url, payload=json)
        return Response({}, 201)

    monkeypatch.setattr(helper.requests, "post", fake_post)

    helper.add_jira_prod_pr_link("P-1", "https://github.com/o/r/pull/3", "r")

    assert posted["url"].endswith("/rest/api/3/issue/P-1/remotelink")
    assert posted["payload"]["object"] == {"url": "https://github.com/o/r/pull/3", "title": "r (PROD)"}


def test_add_env_pr_link_failure_names_the_env(monkeypatch):
    monkeypatch.setattr(helper.requests, "post", lambda *args, **kwargs: Response({}, 400))

    with pytest.raises(Exception, match="Failed to add Jira UAT link"):
        helper.add_jira_uat_pr_link("P-1", "u", "r")


def test_filter_pr_links_by_repo_is_case_insensitive():
    links = [{"repo": "Repo-A"}, {"repo": "repo-b"}]

    assert helper.filter_dev_pr_links(links, "repo-a") == [{"repo": "Repo-A"}]
    assert helper.filter_dev_pr_links(links, None) == links
