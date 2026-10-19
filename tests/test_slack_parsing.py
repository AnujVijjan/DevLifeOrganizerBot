import pytest
from flask import Flask

from app import routes

OPTIONAL = {"--transition", "--assign"}


def parse(parts):
    return routes._parse_slack_command_parts(
        parts,
        value_flags={"--branch", "--repo"},
        switch_flags=set(),
        optional_value_flags=OPTIONAL,
    )


def test_bare_optional_flags_record_empty_values():
    positional, options, _ = parse(["PROJ-1", "--repo", "R", "--transition", "--assign"])

    assert positional == ["PROJ-1"]
    assert options == {"--repo": "R", "--transition": "", "--assign": ""}


def test_optional_flag_takes_the_next_token_unless_it_is_a_flag():
    _, options, _ = parse(["PROJ-1", "--transition", "In QA", "--assign", "a@example.com", "--repo", "R"])

    assert options == {"--transition": "In QA", "--assign": "a@example.com", "--repo": "R"}


def test_equals_form_is_accepted():
    _, options, _ = parse(["PROJ-1", "--transition=Done", "--assign"])

    assert options == {"--transition": "Done", "--assign": ""}


@pytest.mark.parametrize("parts", [["P-1", "--transition", "--transition"], ["P-1", "--no-transition"]])
def test_duplicate_or_unknown_options_are_rejected(parts):
    with pytest.raises(ValueError):
        parse(parts)


@pytest.fixture
def client(monkeypatch):
    started = {}

    class FakeThread:
        def __init__(self, target, args):
            started["args"] = args

        def start(self):
            pass

    monkeypatch.setattr(routes.threading, "Thread", FakeThread)
    app = Flask(__name__)
    app.register_blueprint(routes.app_routes)
    with app.test_client() as test_client:
        test_client.started = started
        yield test_client


def test_createpr_defaults_leave_the_ticket_alone(client):
    client.post("/slack/createpr", data={"text": "PROJ-1 --repo R"})

    assert client.started["args"] == ("PROJ-1", "R", "PROJ-1", None, None)


def test_createpr_bare_flags_use_the_defaults(client):
    client.post("/slack/createpr", data={"text": "PROJ-1 --repo R --transition --assign"})

    assert client.started["args"] == ("PROJ-1", "R", "PROJ-1", "CodeReview", "qa")


def test_createpr_quoted_status_and_assignee(client):
    client.post("/slack/createpr", data={"text": 'PROJ-1 --repo R --branch feat --transition "In QA" --assign a@example.com'})

    assert client.started["args"] == ("PROJ-1", "R", "feat", "In QA", "a@example.com")


def test_createpr_unbalanced_quote_returns_usage(client):
    response = client.post("/slack/createpr", data={"text": 'PROJ-1 --repo "R'})

    assert "Usage" in response.get_json()["text"]
    assert "args" not in client.started


def test_removed_no_transition_flag_is_rejected(client):
    response = client.post("/slack/createpr", data={"text": "PROJ-1 --repo R --no-transition"})

    assert "Unknown option" in response.get_json()["text"]
    assert "args" not in client.started
