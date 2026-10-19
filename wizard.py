"""
Interactive menu for the CLI: asks questions, then runs the matching command.

Every action maps onto an existing cli.py command, so behaviour matches the
flag-based CLI. The equivalent command line is printed before each run.
"""

import argparse
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.constants import (
    DEFAULT_ASSIGNEE,
    DEPLOY_ENVIRONMENTS,
    JIRA_STATUS_CODE_REVIEW,
    PR_ENV_DEV,
    PR_ENVIRONMENTS,
    SP_DEPLOY_DEFAULT_REPO,
)
from app.helper import extract_jira_ticket_key, get_env_pr_links, parse_github_pr_url

Commands = Dict[str, Callable[[argparse.Namespace], None]]
Session = Dict[str, Any]


class WizardCancelled(Exception):
    """Raised when the user aborts a prompt with Ctrl+C or end-of-input."""


def ask(prompt: str, default: Optional[str] = None, required: bool = True) -> str:
    """
    Prompts for text, returning the default on empty input. Re-asks while a
    required answer is empty.
    """

    suffix = f" [{default}]" if default else ""

    while True:
        try:
            value = input(f"  {prompt}{suffix}: ").strip()
        except (EOFError, KeyboardInterrupt):
            raise WizardCancelled()

        if value:
            return value
        if default:
            return default
        if not required:
            return ""


def choose(prompt: str, options: List[str]) -> int:
    """
    Shows a numbered list and returns the zero-based index of the pick.
    """

    print(f"\n  {prompt}")
    for number, option in enumerate(options, start=1):
        print(f"    {number}. {option}")

    while True:
        value = ask("Choose a number")
        if value.isdigit() and 1 <= int(value) <= len(options):
            return int(value) - 1
        print(f"  Enter a number between 1 and {len(options)}.")


def confirm(prompt: str, default: bool = True) -> bool:
    """
    Asks a yes/no question.
    """

    answer = ask(f"{prompt} ({'Y/n' if default else 'y/N'})", default="y" if default else "n")
    return answer.lower().startswith("y")


def ask_ticket(allow_pr_link: bool = False) -> str:
    """
    Asks for a Jira ticket key or link until a key can be extracted; returns the
    key, or the raw GitHub PR link when allowed.
    """

    while True:
        value = ask("Jira ticket (ID or link)" + (", or a GitHub PR link" if allow_pr_link else ""))

        if allow_pr_link and parse_github_pr_url(value):
            return value

        try:
            return extract_jira_ticket_key(value)
        except ValueError as error:
            print(f"  {error}")


def pick_repo_from_ticket(ticket: str, envs: Tuple[str, ...] = (PR_ENV_DEV,)) -> Optional[str]:
    """
    Lists the repos that have PR links on the ticket and lets the user pick one
    or all. Returns None for all repos.
    """

    try:
        repos = sorted({link["repo"] for env in envs for link in get_env_pr_links(ticket, env)})
    except Exception as error:
        print(f"  Could not read PR links from Jira: {error}")
        return ask("Repo (blank for all)", required=False) or None

    if not repos:
        print(f"  No {'/'.join(envs)} PR links found on {ticket} yet.")
        return None

    if len(repos) == 1:
        print(f"  Repo: {repos[0]}")
        return repos[0]

    index = choose("Which repo?", ["All repos"] + repos)
    return None if index == 0 else repos[index - 1]


def format_command(name: str, positional: List[str], flags: Dict[str, Optional[str]]) -> str:
    """
    Builds the equivalent flag-based command line for display.
    """

    parts = ["python cli.py", name] + positional

    for flag, value in flags.items():
        if value is True:
            parts.append(flag)
        elif value:
            text = f'"{value}"' if " " in str(value) else str(value)
            parts.append(f"{flag} {text}")

    return " ".join(parts)


def execute(
    commands: Commands,
    name: str,
    namespace: argparse.Namespace,
    shown: str,
    needs_confirmation: bool = True,
) -> None:
    """
    Prints the equivalent command, optionally confirms, then runs the command,
    absorbing the SystemExit the commands use to signal failure.
    """

    print(f"\n  Equivalent command: {shown}")

    if needs_confirmation and not confirm("Run it?"):
        print("  Cancelled.")
        return

    try:
        commands[name](namespace)
    except SystemExit as exit_signal:
        if exit_signal.code not in (None, 0):
            print(f"\n  Command finished with exit code {exit_signal.code}.")


def flow_createpr(commands: Commands, session: Session) -> None:
    ticket = ask_ticket()
    repo = ask("Repo name", default=session.get("repo"))
    session["repo"] = repo
    branch = ask("Feature branch", default=ticket)
    transition_to = None
    if confirm("Move the ticket to another status?", default=False):
        transition_to = ask("Target status", default=JIRA_STATUS_CODE_REVIEW)

    assign_to = None
    if confirm("Assign the ticket to someone?", default=False):
        assign_to = ask("Assignee (qa, me, or a name/email)", default=DEFAULT_ASSIGNEE)

    namespace = argparse.Namespace(
        ticket=ticket,
        legacy_args=[],
        repo=repo,
        branch=None if branch == ticket else branch,
        transition=transition_to,
        assign=assign_to,
    )
    shown = format_command(
        "createpr",
        [ticket],
        {"--repo": repo, "--branch": namespace.branch, "--transition": transition_to, "--assign": assign_to},
    )
    execute(commands, "createpr", namespace, shown)


def _flow_promote(commands: Commands, name: str) -> None:
    ticket = ask_ticket()
    repo = pick_repo_from_ticket(ticket)
    branch = ask("Feature branch name the new branch is based on", default=ticket)

    namespace = argparse.Namespace(
        ticket=ticket,
        legacy_args=[],
        repo=repo,
        branch=None if branch == ticket else branch,
    )
    shown = format_command(name, [ticket], {"--repo": repo, "--branch": namespace.branch})
    execute(commands, name, namespace, shown)


def flow_createuatpr(commands: Commands, session: Session) -> None:
    _flow_promote(commands, "createuatpr")


def flow_createprodpr(commands: Commands, session: Session) -> None:
    _flow_promote(commands, "createprodpr")


def flow_comparepr(commands: Commands, session: Session) -> None:
    ticket = ask_ticket()
    repo = pick_repo_from_ticket(ticket, envs=tuple(PR_ENVIRONMENTS))

    namespace = argparse.Namespace(ticket=ticket, repo=repo)
    shown = format_command("comparepr", [ticket], {"--repo": repo})
    execute(commands, "comparepr", namespace, shown, needs_confirmation=False)


def flow_deploysp(commands: Commands, session: Session) -> None:
    env_names = list(DEPLOY_ENVIRONMENTS)
    env = env_names[choose("Deploy to which environment?", [name.upper() for name in env_names])]
    allow_pr_link = not DEPLOY_ENVIRONMENTS[env]["requires_typed_confirmation"]
    target = ask_ticket(allow_pr_link=allow_pr_link)

    repo = None
    if not parse_github_pr_url(target):
        repo = ask("Repo to read PR links from", default=SP_DEPLOY_DEFAULT_REPO or session.get("repo"), required=False) or None

    namespace = argparse.Namespace(ticket=target, env=env, repo=repo, yes=False)
    shown = format_command("deploysp", [target], {"--env": env, "--repo": repo})
    execute(commands, "deploysp", namespace, shown, needs_confirmation=False)


def flow_standup(commands: Commands, session: Session) -> None:
    execute(commands, "standup", argparse.Namespace(), format_command("standup", [], {}), needs_confirmation=False)


def flow_tasks(commands: Commands, session: Session) -> None:
    index = choose("Tasks", ["Add a task", "List tasks", "Mark a task done"])

    if index == 0:
        text = ask("Task description")
        execute(commands, "addtask", argparse.Namespace(task=text.split()), format_command("addtask", [f'"{text}"'], {}), needs_confirmation=False)
    elif index == 1:
        execute(commands, "listtasks", argparse.Namespace(), format_command("listtasks", [], {}), needs_confirmation=False)
    else:
        commands["listtasks"](argparse.Namespace())
        task_id = ask("Task ID to mark done")
        if not task_id.isdigit():
            print("  Task ID must be a number.")
            return
        execute(commands, "marktaskdone", argparse.Namespace(task_id=int(task_id)), format_command("marktaskdone", [task_id], {}), needs_confirmation=False)


def flow_deepwork(commands: Commands, session: Session) -> None:
    if choose("Deep Work Mode", ["Turn on", "Turn off"]) == 1:
        execute(commands, "deepworkoff", argparse.Namespace(), format_command("deepworkoff", [], {}), needs_confirmation=False)
        return

    minutes = ask("Minutes", default="60")
    if not minutes.isdigit():
        print("  Minutes must be a number.")
        return
    execute(commands, "deepworkon", argparse.Namespace(minutes=int(minutes)), format_command("deepworkon", [minutes], {}), needs_confirmation=False)


MENU: List[Tuple[str, Callable[[Commands, Session], None]]] = [
    ("Create a DEV PR and link it to Jira", flow_createpr),
    ("Create UAT PRs from a ticket's DEV PRs", flow_createuatpr),
    ("Create PROD PRs from a ticket's DEV PRs", flow_createprodpr),
    ("Compare DEV / UAT / PROD PRs for a ticket", flow_comparepr),
    ("Deploy stored procedures to DEV, UAT or PROD", flow_deploysp),
    ("Standup report", flow_standup),
    ("Tasks", flow_tasks),
    ("Deep Work Mode", flow_deepwork),
]


def run(commands: Commands) -> None:
    """
    Shows the main menu in a loop until the user quits.
    """

    session: Session = {}
    print("\nDev Life Organizer - interactive mode (Ctrl+C to quit)")

    try:
        while True:
            index = choose("What would you like to do?", [label for label, _ in MENU] + ["Quit"])

            if index == len(MENU):
                return

            try:
                MENU[index][1](commands, session)
            except WizardCancelled:
                print("\n  Cancelled.")
    except WizardCancelled:
        print("\n  Bye.")
