#!/usr/bin/env python3
"""
CLI interface for DevLifeOrganizerBot — mirrors every Slack slash command.

Usage
-----
  python cli.py addtask "Fix the login bug"
  python cli.py listtasks
  python cli.py marktaskdone 3
  python cli.py deepworkon 60
  python cli.py deepworkoff
  python cli.py standup
  python cli.py createpr CAH-123 --repo repo-name
  python cli.py createpr CAH-123 --repo repo-name --branch feature-branch
  python cli.py createprodpr CAH-123
  python cli.py createprodpr CAH-123 --branch feature-branch
  python cli.py createprodpr CAH-123 --repo repo-name
  python cli.py createprodpr CAH-123 --branch feature-branch --repo repo-name
"""

import argparse
import sqlite3
import sys
import os
from datetime import datetime, timedelta

# Make sure the project root is importable regardless of where the script is invoked from
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.models import add_task_to_db, get_tasks_from_db, update_task_to_db
from app.constants import (
    DB_FILE,
    JIRA_BASE_URL,
    JIRA_STATUS_IN_PROGRESS,
    JIRA_STATUS_CODE_REVIEW,
)
from app.helper import (
    # DEV PR helpers
    get_repo_branches,
    detect_dev_branch,
    validate_branch_exists,
    get_existing_pr,
    create_pull_request,
    jira_weblink_exists,
    add_jira_pr_link,
    get_jira_issue_status,
    get_jira_transitions,
    transition_jira_issue,
    get_qa_tester_account_id,
    assign_jira_issue,
    # PROD PR helpers
    detect_prod_branch,
    get_dev_pr_links,
    filter_dev_pr_links,
    resolve_createpr_inputs,
    resolve_createprodpr_inputs,
    get_pr_number_from_url,
    get_pr_commits,
    get_branch_sha,
    create_branch,
    cherry_pick_commits_onto_branch,
    update_pull_request_body,
    create_prod_pull_request,
    add_jira_prod_pr_link,
    # Standup helpers
    fetch_recent_commits,
    fetch_recent_jira_updates,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ok(msg: str) -> None:
    print(f"[OK]  {msg}")

def _info(msg: str) -> None:
    print(f"      {msg}")

def _err(msg: str) -> None:
    print(f"[ERR] {msg}", file=sys.stderr)

def _section(title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")

# ---------------------------------------------------------------------------
# Task commands
# ---------------------------------------------------------------------------

def cmd_addtask(args: argparse.Namespace) -> None:
    task_text = " ".join(args.task)
    add_task_to_db(task_text)
    _ok(f"Task added: \"{task_text}\"")


def cmd_listtasks(args: argparse.Namespace) -> None:
    tasks = get_tasks_from_db()
    if not tasks:
        _info("No pending tasks.")
        return
    _section("Pending Tasks")
    for task_id, task, _ in tasks:
        print(f"  {task_id}. {task}")


def cmd_marktaskdone(args: argparse.Namespace) -> None:
    update_task_to_db(args.task_id)
    _ok(f"Task {args.task_id} marked as done.")

# ---------------------------------------------------------------------------
# Deep Work commands
# ---------------------------------------------------------------------------

def cmd_deepworkon(args: argparse.Namespace) -> None:
    duration = args.minutes
    end_time = datetime.utcnow() + timedelta(minutes=duration)

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM deep_work")
    cursor.execute("INSERT INTO deep_work (active, end_time) VALUES (1, ?)", (end_time,))
    conn.commit()
    conn.close()

    _ok(f"Deep Work Mode ON for {duration} minute(s). Ends at {end_time.strftime('%H:%M:%S')} UTC.")


def cmd_deepworkoff(args: argparse.Namespace) -> None:
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM deep_work")
    conn.commit()
    conn.close()
    _ok("Deep Work Mode OFF.")

# ---------------------------------------------------------------------------
# Standup command
# ---------------------------------------------------------------------------

def cmd_standup(args: argparse.Namespace) -> None:
    _section("Daily Standup")

    commits = fetch_recent_commits()
    if commits:
        print("\nCode Commits:")
        for c in commits:
            print(f"  {c}")
    else:
        print("\nCode Commits: No recent commits.")

    jira_updates = fetch_recent_jira_updates()
    if jira_updates:
        print("\nJira Updates:")
        for u in jira_updates:
            print(f"  {u}")
    else:
        print("\nJira Updates: No recent activity.")

# ---------------------------------------------------------------------------
# Create DEV PR command
# ---------------------------------------------------------------------------

def cmd_createpr(args: argparse.Namespace) -> None:
    jira_ticket = args.ticket
    try:
        feature_branch, repo_name = resolve_createpr_inputs(
            jira_ticket=jira_ticket,
            legacy_args=args.legacy_args,
            feature_branch=args.branch,
            repo_name=args.repo,
        )
    except ValueError as e:
        _err(str(e))
        sys.exit(2)
    move_to_review = not args.no_transition

    _section(f"Creating DEV PR — {jira_ticket} / {repo_name}")

    try:
        pr_created = False
        jira_link_added = False
        ticket_moved = False
        ticket_assigned = False

        branches = get_repo_branches(repo_name)
        if not branches:
            _err(f"Unable to fetch branches for repo '{repo_name}'.")
            return

        dev_branch = detect_dev_branch(branches)
        _info(f"Dev branch detected: {dev_branch}")

        validate_branch_exists(repo_name, feature_branch)
        _info(f"Feature branch confirmed: {feature_branch}")

        existing_pr = get_existing_pr(repo_name, feature_branch, dev_branch)
        if existing_pr:
            pr_url = existing_pr["html_url"]
            _info(f"PR already exists: {pr_url}")
        else:
            pr = create_pull_request(
                repo=repo_name,
                feature_branch=feature_branch,
                dev_branch=dev_branch,
                jira_ticket=jira_ticket,
            )
            pr_url = pr["html_url"]
            pr_created = True
            _ok(f"PR created: {pr_url}")

        if not jira_weblink_exists(jira_ticket, pr_url):
            add_jira_pr_link(ticket=jira_ticket, pr_url=pr_url, repo=repo_name)
            jira_link_added = True
            _ok("Jira DEV link added.")
        else:
            _info("Jira DEV link already existed.")

        current_status = get_jira_issue_status(jira_ticket)
        _info(f"Jira ticket status: {current_status}")

        if move_to_review:
            transitions = get_jira_transitions(jira_ticket)
            code_review_transition = next(
                (t for t in transitions if t["name"].lower() == JIRA_STATUS_CODE_REVIEW.lower()),
                None,
            )

            if code_review_transition:
                transition_jira_issue(jira_ticket, code_review_transition["id"])
                ticket_moved = True
                _ok(f"Ticket moved to '{JIRA_STATUS_CODE_REVIEW}'.")

                qa_account_id = get_qa_tester_account_id(jira_ticket)
                assign_jira_issue(jira_ticket, qa_account_id)
                ticket_assigned = True
                _ok("Ticket assigned to QA tester.")
            else:
                _info(f"Status is '{current_status}' — no workflow change performed.")

        print()
        print(f"  Ticket:         {JIRA_BASE_URL}/browse/{jira_ticket}")
        print(f"  Repo:           {repo_name}")
        print(f"  Feature branch: {feature_branch}")
        print(f"  Dev branch:     {dev_branch}")
        print(f"  PR:             {pr_url}")
        print(f"  PR created:     {pr_created}")
        print(f"  Jira link:      {jira_link_added}")
        print(f"  Ticket moved:   {ticket_moved}")
        print(f"  Ticket assigned:{ticket_assigned}")

    except Exception as e:
        _err(str(e))
        sys.exit(1)

# ---------------------------------------------------------------------------
# Create PROD PR command
# ---------------------------------------------------------------------------

def cmd_createprodpr(args: argparse.Namespace) -> None:
    jira_ticket = args.ticket
    try:
        feature_branch, repo_filter = resolve_createprodpr_inputs(
            jira_ticket=jira_ticket,
            legacy_args=args.legacy_args,
            feature_branch=args.branch,
            repo_name=args.repo,
        )
    except ValueError as e:
        _err(str(e))
        sys.exit(2)

    _section(f"Creating PROD PRs — {jira_ticket}")

    try:
        dev_links = get_dev_pr_links(jira_ticket)

        if not dev_links:
            _err(
                f"No DEV PR links found on ticket {jira_ticket}. "
                "Create DEV PRs first with 'createpr'."
            )
            sys.exit(1)

        if repo_filter:
            filtered_dev_links = filter_dev_pr_links(dev_links, repo_filter)
            if not filtered_dev_links:
                available_repos = ", ".join(sorted({link["repo"] for link in dev_links}))
                _err(
                    f"No DEV PR link found for repo '{repo_filter}' on ticket {jira_ticket}. "
                    f"Available repos: {available_repos}"
                )
                sys.exit(1)
            dev_links = filtered_dev_links
            _info(f"Repo filter applied: {repo_filter}")

        _info(f"DEV PR links found: {len(dev_links)}")

        prod_branch_name = f"{feature_branch}-Prod"

        for link in dev_links:
            repo = link["repo"]
            dev_pr_url = link["url"]

            print(f"\n  Repo: {repo}")
            print(f"  DEV PR: {dev_pr_url}")

            try:
                pr_number = get_pr_number_from_url(dev_pr_url)

                raw_commits = get_pr_commits(repo, pr_number)
                commit_refs = [
                    (c["sha"], c["commit"]["message"].split("\n")[0])
                    for c in raw_commits
                ]
                _info(f"DEV commits found: {len(commit_refs)}")
                for sha, msg in commit_refs:
                    print(f"    - {sha[:7]}  {msg}")

                branches = get_repo_branches(repo)
                prod_branch = detect_prod_branch(branches)
                _info(f"Prod branch detected: {prod_branch}")

                # Create PROD branch from production's HEAD (clean base)
                prod_head_sha = get_branch_sha(repo, prod_branch)

                branch_created = False
                try:
                    create_branch(repo, prod_branch_name, prod_head_sha)
                    branch_created = True
                    _ok(f"Branch '{prod_branch_name}' created from '{prod_branch}'.")
                except Exception as branch_err:
                    if "already exists" in str(branch_err):
                        _info(f"Branch '{prod_branch_name}' already existed.")
                    else:
                        raise

                # Cherry-pick each DEV commit onto the PROD branch
                picked = cherry_pick_commits_onto_branch(repo, raw_commits, prod_branch_name)
                _ok(f"Cherry-picked {picked} commit(s) onto '{prod_branch_name}'.")

                existing_pr = get_existing_pr(repo, prod_branch_name, prod_branch)
                if existing_pr:
                    prod_pr_url = existing_pr["html_url"]
                    pr_created = False
                    _info(f"PROD PR already existed: {prod_pr_url}")
                    # Refresh the PR body with the latest cherry-picked commit list
                    if commit_refs:
                        updated_body = (
                            f"Jira ticket: {jira_ticket}\n\n"
                            f"**Cherry-picked commits from DEV PR:**\n"
                            + "\n".join(f"- `{sha[:7]}` {msg}" for sha, msg in commit_refs)
                        )
                        update_pull_request_body(repo, existing_pr["number"], updated_body)
                        _ok("PR body updated with latest commits.")
                else:
                    prod_pr = create_prod_pull_request(
                        repo=repo,
                        prod_branch_name=prod_branch_name,
                        target_prod_branch=prod_branch,
                        jira_ticket=jira_ticket,
                        commit_refs=commit_refs,
                    )
                    prod_pr_url = prod_pr["html_url"]
                    pr_created = True
                    _ok(f"PROD PR created: {prod_pr_url}")

                jira_link_added = False
                if not jira_weblink_exists(jira_ticket, prod_pr_url):
                    add_jira_prod_pr_link(jira_ticket, prod_pr_url, repo)
                    jira_link_added = True
                    _ok("Jira PROD link added.")
                else:
                    _info("Jira PROD link already existed.")

            except Exception as repo_err:
                _err(f"{repo}: {repo_err}")

    except Exception as e:
        _err(str(e))
        sys.exit(1)

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="cli.py",
        description="DevLifeOrganizerBot CLI — run bot actions without Slack.",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="<command>")
    subparsers.required = True

    # addtask
    p = subparsers.add_parser("addtask", help="Add a task to your to-do list")
    p.add_argument("task", nargs="+", help="Task description")
    p.set_defaults(func=cmd_addtask)

    # listtasks
    p = subparsers.add_parser("listtasks", help="List all pending tasks")
    p.set_defaults(func=cmd_listtasks)

    # marktaskdone
    p = subparsers.add_parser("marktaskdone", help="Mark a task as done")
    p.add_argument("task_id", type=int, help="Task ID")
    p.set_defaults(func=cmd_marktaskdone)

    # deepworkon
    p = subparsers.add_parser("deepworkon", help="Enable Deep Work Mode")
    p.add_argument("minutes", type=int, nargs="?", default=60, help="Duration in minutes (default: 60)")
    p.set_defaults(func=cmd_deepworkon)

    # deepworkoff
    p = subparsers.add_parser("deepworkoff", help="Disable Deep Work Mode")
    p.set_defaults(func=cmd_deepworkoff)

    # standup
    p = subparsers.add_parser("standup", help="Print today's standup report")
    p.set_defaults(func=cmd_standup)

    # createpr
    p = subparsers.add_parser(
        "createpr",
        help="Create a DEV PR and link it to a Jira ticket",
        usage="cli.py createpr ticket --repo REPO [--branch FEATURE_BRANCH] [--no-transition]",
        description=(
            "Create a DEV PR and link it to a Jira ticket. "
            "Legacy positional syntax still works: createpr TICKET [feature-branch] repo"
        ),
    )
    p.add_argument("ticket", help="Jira ticket ID, e.g. CAH-123")
    p.add_argument("legacy_args", nargs="*", help=argparse.SUPPRESS)
    p.add_argument("--branch", help="Feature branch name (defaults to the Jira ticket ID)")
    p.add_argument("--repo", help="Repository name")
    p.add_argument("--no-transition", action="store_true", help="Skip moving the Jira ticket to CodeReview")
    p.set_defaults(func=cmd_createpr)

    # createprodpr
    p = subparsers.add_parser(
        "createprodpr",
        help="Create PROD PRs from DEV PRs on a Jira ticket",
        usage="cli.py createprodpr ticket [--branch FEATURE_BRANCH] [--repo REPO]",
        description=(
            "Create PROD PRs from DEV PRs on a Jira ticket. "
            "Legacy positional feature-branch syntax still works: createprodpr TICKET [feature-branch]"
        ),
    )
    p.add_argument("ticket", help="Jira ticket ID, e.g. CAH-123")
    p.add_argument("legacy_args", nargs="*", help=argparse.SUPPRESS)
    p.add_argument("--branch", help="Feature branch name used to derive the PROD branch name (defaults to the Jira ticket ID)")
    p.add_argument("--repo", help="Only create the PROD PR for the specified repository")
    p.set_defaults(func=cmd_createprodpr)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
