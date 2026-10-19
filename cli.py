#!/usr/bin/env python3
"""
CLI interface for DevLifeOrganizerBot — mirrors every Slack slash command.

Usage
-----
  python cli.py                      (interactive mode: asks questions, then runs the command)
  python cli.py interactive
  python cli.py addtask "Fix the login bug"
  python cli.py listtasks
  python cli.py marktaskdone 3
  python cli.py deepworkon 60
  python cli.py deepworkoff
  python cli.py standup
  python cli.py createpr PROJ-123 --repo repo-name
  python cli.py createpr PROJ-123 --repo repo-name --branch feature-branch
  python cli.py createpr PROJ-123 --repo repo-name --transition --assign
  python cli.py createpr PROJ-123 --repo repo-name --transition "In QA" --assign someone@example.com
  python cli.py createprodpr PROJ-123
  python cli.py createprodpr PROJ-123 --branch feature-branch
  python cli.py createprodpr PROJ-123 --repo repo-name
  python cli.py createprodpr PROJ-123 --branch feature-branch --repo repo-name
  python cli.py createuatpr PROJ-123
  python cli.py createuatpr PROJ-123 --branch feature-branch
  python cli.py createuatpr PROJ-123 --repo repo-name
  python cli.py createuatpr PROJ-123 --branch feature-branch --repo repo-name
  python cli.py comparepr PROJ-123
  python cli.py comparepr PROJ-123 --repo repo-name
  python cli.py deploysp PROJ-123 --env uat
  python cli.py deploysp https://company.atlassian.net/browse/PROJ-123 --env uat --repo my-repo --yes
  python cli.py deploysp https://github.com/my-org/my-repo/pull/42 --env prod
  python cli.py deploysptouat PROJ-123
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
    JIRA_STATUS_CODE_REVIEW,
    DEFAULT_ASSIGNEE,
    SP_DEPLOY_DEFAULT_REPO,
    DEPLOY_ENVIRONMENTS,
)
from app.helper import (
    get_repo_branches,
    detect_dev_branch,
    validate_branch_exists,
    get_existing_pr,
    create_pull_request,
    jira_weblink_exists,
    add_jira_pr_link,
    extract_jira_ticket_key,
    parse_github_pr_url,
    apply_jira_workflow,
    detect_prod_branch,
    get_dev_pr_links,
    get_env_pr_links,
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
    detect_uat_branch,
    ensure_feature_branch_differs,
    resolve_createuatpr_inputs,
    create_uat_pull_request,
    add_jira_uat_pr_link,
    get_uat_pr_links,
    compare_env_prs,
    fetch_recent_commits,
    fetch_recent_jira_updates,
)
from app.sql_deploy import get_changed_stored_procedures, deploy_stored_procs, get_deploy_environment

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
    transition_to = args.transition
    assign_to = args.assign

    _section(f"Creating DEV PR — {jira_ticket} / {repo_name}")

    try:
        pr_created = False
        jira_link_added = False

        branches = get_repo_branches(repo_name)
        if not branches:
            _err(f"Unable to fetch branches for repo '{repo_name}'.")
            return

        dev_branch = detect_dev_branch(branches, repo_name)
        ensure_feature_branch_differs(feature_branch, dev_branch)
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

        workflow = apply_jira_workflow(jira_ticket, transition_to, assign_to)

        if transition_to and workflow["transitioned"]:
            _ok(f"Ticket moved to '{transition_to}'.")
        elif transition_to:
            _info(f"No '{transition_to}' transition is available from '{workflow['status_before']}' — ticket not moved.")

        if workflow["assigned"]:
            _ok(f"Ticket assigned to '{assign_to}'.")

        print()
        print(f"  Ticket:         {JIRA_BASE_URL}/browse/{jira_ticket}")
        print(f"  Repo:           {repo_name}")
        print(f"  Feature branch: {feature_branch}")
        print(f"  Dev branch:     {dev_branch}")
        print(f"  PR:             {pr_url}")
        print(f"  PR created:     {pr_created}")
        print(f"  Jira link:      {jira_link_added}")
        print(f"  Ticket moved:   {workflow['transitioned']}")
        print(f"  Ticket assigned:{workflow['assigned']}")

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
                prod_branch = detect_prod_branch(branches, repo)
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
# Create UAT PR command
# ---------------------------------------------------------------------------

def cmd_createuatpr(args: argparse.Namespace) -> None:
    jira_ticket = args.ticket
    try:
        feature_branch, repo_filter = resolve_createuatpr_inputs(
            jira_ticket=jira_ticket,
            legacy_args=args.legacy_args,
            feature_branch=args.branch,
            repo_name=args.repo,
        )
    except ValueError as e:
        _err(str(e))
        sys.exit(2)

    _section(f"Creating UAT PRs — {jira_ticket}")

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

        uat_branch_name = f"{feature_branch}-Uat"

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
                uat_branch = detect_uat_branch(branches, repo)
                _info(f"UAT branch detected: {uat_branch}")

                # Create UAT branch from UAT's current HEAD (clean base)
                uat_head_sha = get_branch_sha(repo, uat_branch)

                branch_created = False
                try:
                    create_branch(repo, uat_branch_name, uat_head_sha)
                    branch_created = True
                    _ok(f"Branch '{uat_branch_name}' created from '{uat_branch}'.")
                except Exception as branch_err:
                    if "already exists" in str(branch_err):
                        _info(f"Branch '{uat_branch_name}' already existed.")
                    else:
                        raise

                # Cherry-pick each DEV commit onto the UAT branch
                picked = cherry_pick_commits_onto_branch(repo, raw_commits, uat_branch_name)
                _ok(f"Cherry-picked {picked} commit(s) onto '{uat_branch_name}'.")

                existing_pr = get_existing_pr(repo, uat_branch_name, uat_branch)
                if existing_pr:
                    uat_pr_url = existing_pr["html_url"]
                    pr_created = False
                    _info(f"UAT PR already existed: {uat_pr_url}")
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
                    uat_pr = create_uat_pull_request(
                        repo=repo,
                        uat_branch_name=uat_branch_name,
                        target_uat_branch=uat_branch,
                        jira_ticket=jira_ticket,
                        commit_refs=commit_refs,
                    )
                    uat_pr_url = uat_pr["html_url"]
                    pr_created = True
                    _ok(f"UAT PR created: {uat_pr_url}")

                jira_link_added = False
                if not jira_weblink_exists(jira_ticket, uat_pr_url):
                    add_jira_uat_pr_link(jira_ticket, uat_pr_url, repo)
                    jira_link_added = True
                    _ok("Jira UAT link added.")
                else:
                    _info("Jira UAT link already existed.")

            except Exception as repo_err:
                _err(f"{repo}: {repo_err}")

    except Exception as e:
        _err(str(e))
        sys.exit(1)

# ---------------------------------------------------------------------------
# Compare PR command
# ---------------------------------------------------------------------------

def cmd_comparepr(args: argparse.Namespace) -> None:
    jira_ticket = args.ticket
    repo_filter = args.repo

    _section(f"Comparing env PRs — {jira_ticket}")

    try:
        report = compare_env_prs(jira_ticket, repo_filter)

        if not report:
            _err(f"No DEV/UAT/PROD PR links found on ticket {jira_ticket}.")
            sys.exit(1)

        any_mismatch = False

        for r in report:
            print(f"\n  Repo: {r['repo']}")
            for env, url in sorted(r["envs"].items()):
                _info(f"{env}: {url}")

            if r["verdict"] == "MATCH":
                _ok("MATCH — changes are identical across environments.")
            elif r["verdict"] == "INCOMPLETE":
                _info("INCOMPLETE — fewer than two environments have a PR yet.")
            else:
                any_mismatch = True
                _err("MISMATCH")
                for f in r["files"]:
                    if f["status"] == "DIFFERS":
                        _err(f"  {f['path']} differs across environments")
                    elif f["status"] == "MISSING":
                        missing = ", ".join(f["missing_in"])
                        _err(f"  {f['path']} missing in: {missing}")

        if any_mismatch:
            sys.exit(1)

    except Exception as e:
        _err(str(e))
        sys.exit(1)

# ---------------------------------------------------------------------------
# Deploy stored procs command
# ---------------------------------------------------------------------------

def _confirm_deploy(env_config: dict, count: int, ticket_key: str, assume_yes: bool) -> bool:
    label = env_config["label"]

    if env_config["requires_typed_confirmation"]:
        answer = input(f"\n  Type the ticket key ({ticket_key}) to run {count} script(s) against {label}: ").strip()
        return answer.upper() == ticket_key

    if assume_yes:
        return True

    answer = input(f"\n  Run these {count} script(s) against {label}? [y/N] ").strip().lower()
    return answer == "y"


def cmd_deploysp(args: argparse.Namespace) -> None:
    env = args.env
    direct_pr = parse_github_pr_url(args.ticket)

    try:
        env_config = get_deploy_environment(env)
    except (ValueError, RuntimeError) as e:
        _err(str(e))
        sys.exit(2)

    label = env_config["label"]

    if direct_pr and env_config["requires_typed_confirmation"]:
        _err(f"A direct PR link can't be deployed to {label}. Pass the Jira ticket so its {label} PR link is used.")
        sys.exit(2)

    if not direct_pr:
        try:
            extract_jira_ticket_key(args.ticket)
        except ValueError as e:
            _err(str(e))
            sys.exit(2)

    try:
        ticket_key = ""

        if direct_pr:
            repo, pr_number = direct_pr
            links = [{"repo": repo, "url": args.ticket}]
            source_env = "PR"
            _section(f"Deploying stored procs to {label} — {repo}#{pr_number}")
        else:
            jira_ticket = extract_jira_ticket_key(args.ticket)
            ticket_key = jira_ticket
            repo_filter = args.repo

            _section(f"Deploying stored procs to {label} — {jira_ticket}")

            source_env = env_config["pr_env"]
            links = filter_dev_pr_links(get_env_pr_links(jira_ticket, source_env), repo_filter)

            fallback_env = env_config["fallback_pr_env"]
            if not links and fallback_env:
                source_env = fallback_env
                links = filter_dev_pr_links(get_env_pr_links(jira_ticket, source_env), repo_filter)

            if not links:
                searched = " or ".join(filter(None, [env_config["pr_env"], env_config["fallback_pr_env"]]))
                _err(
                    f"No {searched} PR links found on ticket {jira_ticket}"
                    + (f" for repo '{repo_filter}'." if repo_filter else ".")
                )
                sys.exit(1)

        _info(f"Reading changed stored procs from the {source_env} PR link(s).")

        any_failure = False

        for link in links:
            repo = link["repo"]
            pr_url = link["url"]

            print(f"\n  Repo: {repo}")
            print(f"  {source_env} PR: {pr_url}")

            pr_number = get_pr_number_from_url(pr_url)
            procs = get_changed_stored_procedures(repo, pr_number)

            if not procs:
                _info("No changed .sql files found in this PR.")
                continue

            _info(f"Stored procs found: {len(procs)}")
            for proc in procs:
                print(f"    - {proc['path']} ({proc['status']})")

            if not _confirm_deploy(env_config, len(procs), ticket_key, args.yes):
                _info("Skipped by user.")
                continue

            results = deploy_stored_procs(procs, env)
            for r in results:
                if r["success"]:
                    _ok(f"{r['path']} — {r['use_statements_rewritten']} USE statement(s) rewritten, executed OK.")
                else:
                    any_failure = True
                    _err(f"{r['path']} — {r['error']}")

        if any_failure:
            sys.exit(1)

    except Exception as e:
        _err(str(e))
        sys.exit(1)


def cmd_deploysptouat(args: argparse.Namespace) -> None:
    args.env = "uat"
    cmd_deploysp(args)

# ---------------------------------------------------------------------------
# Interactive mode
# ---------------------------------------------------------------------------

def cmd_interactive(args: argparse.Namespace) -> None:
    from wizard import run

    run({
        "addtask": cmd_addtask,
        "listtasks": cmd_listtasks,
        "marktaskdone": cmd_marktaskdone,
        "deepworkon": cmd_deepworkon,
        "deepworkoff": cmd_deepworkoff,
        "standup": cmd_standup,
        "createpr": cmd_createpr,
        "createprodpr": cmd_createprodpr,
        "createuatpr": cmd_createuatpr,
        "comparepr": cmd_comparepr,
        "deploysp": cmd_deploysp,
    })

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

    # interactive
    p = subparsers.add_parser("interactive", help="Pick an action from a menu and answer questions instead of passing flags")
    p.set_defaults(func=cmd_interactive)

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
        usage="cli.py createpr ticket --repo REPO [--branch FEATURE_BRANCH] [--transition [STATUS]] [--assign [USER]]",
        description=(
            "Create a DEV PR and link it to a Jira ticket. The ticket is left untouched unless "
            "--transition and/or --assign are given. "
            "Legacy positional syntax still works: createpr TICKET [feature-branch] repo"
        ),
    )
    p.add_argument("ticket", help="Jira ticket ID, e.g. PROJ-123")
    p.add_argument("legacy_args", nargs="*", help=argparse.SUPPRESS)
    p.add_argument("--branch", help="Feature branch name (defaults to the Jira ticket ID)")
    p.add_argument("--repo", help="Repository name")
    p.add_argument(
        "--transition",
        nargs="?",
        const=JIRA_STATUS_CODE_REVIEW,
        default=None,
        metavar="STATUS",
        help=f"Move the Jira ticket to STATUS (bare flag: {JIRA_STATUS_CODE_REVIEW})",
    )
    p.add_argument(
        "--assign",
        nargs="?",
        const=DEFAULT_ASSIGNEE,
        default=None,
        metavar="USER",
        help=f"Assign the Jira ticket to USER: `qa` (the ticket's QA tester), `me`, or a name/email (bare flag: {DEFAULT_ASSIGNEE})",
    )
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
    p.add_argument("ticket", help="Jira ticket ID, e.g. PROJ-123")
    p.add_argument("legacy_args", nargs="*", help=argparse.SUPPRESS)
    p.add_argument("--branch", help="Feature branch name used to derive the PROD branch name (defaults to the Jira ticket ID)")
    p.add_argument("--repo", help="Only create the PROD PR for the specified repository")
    p.set_defaults(func=cmd_createprodpr)

    # createuatpr
    p = subparsers.add_parser(
        "createuatpr",
        help="Create UAT PRs from DEV PRs on a Jira ticket",
        usage="cli.py createuatpr ticket [--branch FEATURE_BRANCH] [--repo REPO]",
        description=(
            "Create UAT PRs from DEV PRs on a Jira ticket. "
            "Legacy positional feature-branch syntax still works: createuatpr TICKET [feature-branch]"
        ),
    )
    p.add_argument("ticket", help="Jira ticket ID, e.g. PROJ-123")
    p.add_argument("legacy_args", nargs="*", help=argparse.SUPPRESS)
    p.add_argument("--branch", help="Feature branch name used to derive the UAT branch name (defaults to the Jira ticket ID)")
    p.add_argument("--repo", help="Only create the UAT PR for the specified repository")
    p.set_defaults(func=cmd_createuatpr)

    # comparepr
    p = subparsers.add_parser(
        "comparepr",
        help="Compare DEV/UAT/PROD PR changes for a Jira ticket",
        usage="cli.py comparepr ticket [--repo REPO]",
        description=(
            "Compares the changed-file content of the DEV/UAT/PROD PRs linked on a "
            "Jira ticket, per repo, as a sanity check that all environments carry "
            "the same changes before merging."
        ),
    )
    p.add_argument("ticket", help="Jira ticket ID, e.g. PROJ-123")
    p.add_argument("--repo", help="Only compare the specified repository")
    p.set_defaults(func=cmd_comparepr)

    # deploysp
    p = subparsers.add_parser(
        "deploysp",
        help="Run the stored procs changed in a PR (direct link or via a Jira ticket) against an environment",
        usage="cli.py deploysp ticket-or-jira-link-or-github-pr-link [--env dev|uat|prod] [--repo REPO] [--yes]",
        description=(
            "Finds the PR whose changed stored procs should be deployed -- either a GitHub PR "
            "link given directly (not prod), or for a Jira ticket/link the PR linked for the "
            "chosen environment (dev uses the DEV PR; uat falls back to the DEV PR; prod uses the PROD PR only) -- "
            "then, for every changed .sql file, rewrites `USE [<source database>]` to the "
            "environment's database and runs it there. prod always requires typing the ticket key."
        ),
    )
    p.add_argument(
        "ticket",
        help=(
            "Jira ticket ID, full Jira link, or a GitHub PR link, e.g. PROJ-123, "
            "https://company.atlassian.net/browse/PROJ-123, or "
            "https://github.com/org/repo/pull/42"
        ),
    )
    p.add_argument("--env", choices=list(DEPLOY_ENVIRONMENTS), default="uat", help="Target environment (default: uat)")
    p.add_argument("--repo", default=SP_DEPLOY_DEFAULT_REPO, help="Repository to read Jira PR links for; ignored for a direct GitHub PR link (default: SP_DEPLOY_DEFAULT_REPO)")
    p.add_argument("--yes", action="store_true", help="Skip the confirmation prompt (ignored for prod)")
    p.set_defaults(func=cmd_deploysp)

    # deploysptouat
    p = subparsers.add_parser(
        "deploysptouat",
        help="Alias for `deploysp --env uat`",
        usage="cli.py deploysptouat ticket-or-jira-link-or-github-pr-link [--repo REPO] [--yes]",
    )
    p.add_argument("ticket", help="Jira ticket ID, full Jira link, or a GitHub PR link")
    p.add_argument("--repo", default=SP_DEPLOY_DEFAULT_REPO, help="Repository to read Jira PR links for (default: SP_DEPLOY_DEFAULT_REPO)")
    p.add_argument("--yes", action="store_true", help="Skip the confirmation prompt")
    p.set_defaults(func=cmd_deploysptouat)

    if len(sys.argv) == 1:
        cmd_interactive(argparse.Namespace())
        return

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
