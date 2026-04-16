import requests
from slack_sdk import WebClient
from datetime import datetime, timedelta
from typing import List, Tuple, Dict, Any, Optional
from .models import get_tasks_from_db
import sqlite3
from .helper import (
    fetch_filtered_repositories,
    fetch_pull_requests,
    fetch_recent_commits,
    fetch_recent_jira_updates,
    get_repo_branches,
    detect_dev_branch,
    detect_prod_branch,
    validate_branch_exists,
    get_existing_pr,
    jira_weblink_exists,
    create_pull_request,
    add_jira_pr_link,
    get_jira_issue_status,
    get_qa_tester_account_id,
    assign_jira_issue,
    get_jira_transitions,
    transition_jira_issue,
    get_dev_pr_links,
    filter_dev_pr_links,
    get_pr_number_from_url,
    get_pr_commits,
    get_branch_sha,
    create_branch,
    cherry_pick_commits_onto_branch,
    update_pull_request_body,
    create_prod_pull_request,
    add_jira_prod_pr_link,
)
from .constants import *

client = WebClient(token=SLACK_BOT_TOKEN)
user_client = WebClient(token=SLACK_USER_TOKEN)

def get_review_reminders() -> Tuple[List[str], List[str], List[str]]:
    """
    Checks PRs across filtered repositories in the organization and categorizes them.

    :return: Tuple[List[str], List[str], List[str]] ->
             A tuple containing lists of assigned PRs, PRs waiting for review, and stale PRs.
    :raises requests.RequestException: If fetching repositories or PRs fails.
    """
    repos: List[str] = fetch_filtered_repositories()
    assigned_prs: List[str] = []
    pending_reviews: List[str] = []
    stale_prs: List[str] = []

    stale_threshold: datetime = datetime.utcnow() - timedelta(days=7)

    for repo in repos:
        prs = fetch_pull_requests(repo)

        for pr in prs:
            pr_title: str = pr["title"]
            pr_url: str = pr["html_url"]
            pr_updated_at: datetime = datetime.strptime(pr["updated_at"], "%Y-%m-%dT%H:%M:%SZ")
            pr_assignees: List[str] = [assignee["login"] for assignee in pr.get("assignees", [])]

            if GITHUB_USERNAME in pr_assignees:
                assigned_prs.append(f"🔹 *[{repo}]* {pr_title} - {pr_url}")

            if pr_updated_at < stale_threshold:
                stale_prs.append(f"⚠️ *[{repo}]* {pr_title} (Stale for 7+ days) - {pr_url}")

            review_url: str = pr["_links"]["review_comments"]["href"]
            review_response = requests.get(review_url, headers=GITHUB_HEADERS)
            if review_response.status_code == 200 and len(review_response.json()) == 0:
                pending_reviews.append(f"📌 *[{repo}]* {pr_title} - {pr_url} (Waiting for review)")

    return assigned_prs, pending_reviews, stale_prs


def send_code_review_reminder() -> None:
    """
    Sends a Slack notification for PR reviews and stale PRs.

    :return: None
    """
    assigned_prs, pending_reviews, stale_prs = get_review_reminders()
    messages: List[str] = []

    if assigned_prs:
        messages.append("*📢 PRs Assigned to You:*")
        messages.extend(assigned_prs)

    if pending_reviews:
        messages.append("\n*⏳ PRs Waiting for Review:*")
        messages.extend(pending_reviews)

    if stale_prs:
        messages.append("\n*⚠️ Stale PRs (No activity for 7+ days):*")
        messages.extend(stale_prs)

    message: str = "\n".join(messages) if messages else "✅ No pending PRs or stale reviews. Keep coding! 🚀"

    client.chat_postMessage(channel=SLACK_CHANNEL, text=message)


def send_message_to_slack(client: WebClient, message: str, channel: str) -> None:
    """
    Sends a message to a specified Slack channel or user.

    :param client: WebClient -> The Slack WebClient instance used to send the message.
    :param message: str -> The text message to be sent.
    :param channel: str -> The Slack channel ID or user ID where the message will be sent.
    :return: None
    :raises SlackApiError: If the Slack API call fails due to an invalid token, network issue, or permission error.
    """
    client.chat_postMessage(channel=channel, text=message)


def send_daily_summary() -> None:
    """
    Sends a daily summary of tasks to Slack.

    :return: None
    """
    tasks = get_tasks_from_db()
    message: str = (
        "No tasks for today! 🚀"
        if not tasks
        else "📝 *Your Tasks for Today:*\n" + "\n".join(f"• {task[0]}" for task in tasks)
    )

    send_message_to_slack(client, message, SLACK_CHANNEL)


def send_health_reminder() -> None:
    """
    Sends a health reminder to the user after a certain period of inactivity.
    Reminds them to take a break, drink water, or stretch.
    :return: None
    """
    message: str = (
        "💪 Time to take a break! Stretch, hydrate, or just step away from your screen for a few minutes. "
        "Your body needs it! 🌱"
    )

    send_message_to_slack(client, message, SLACK_USER_ID)


def is_deep_work_active() -> bool:
    """
    Checks if Deep Work Mode is currently active.

    :return: True if active, False otherwise.
    """
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT end_time FROM deep_work WHERE active = 1")
    row = cursor.fetchone()
    conn.close()

    if row:
        end_time = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S.%f")
        if datetime.utcnow() < end_time:
            return True
        else:
            from .routes import disable_deep_work_mode
            disable_deep_work_mode()  # Auto disable if time expired
    return False


def handle_slack_mention(event: Dict[str, Any]) -> None:
    """
    Handles Slack mentions and sends an auto-reply if Deep Work Mode is active.

    :param event: The Slack event payload.
    :return: None
    """
    if is_deep_work_active():
        user_id = event["user"]

        message = (
            f"🔕 Hey <@{user_id}>, I'm currently in *Deep Work Mode* and not receiving notifications. "
            "I'll get back to you once I'm available! ⏳"
        )

        send_message_to_slack(user_client, message, user_id)


def generate_standup_report() -> str:
    """
    Generates a standup report summarizing recent GitHub commits and Jira ticket updates.

    :return: A formatted string containing the standup summary.
    """
    commits = fetch_recent_commits()
    jira_updates = fetch_recent_jira_updates()

    standup_text = "*🚀 Daily Standup Summary:*\n\n"

    if commits:
        standup_text += "*✅ Code Commits:*\n" + "\n".join(commits) + "\n\n"
    else:
        standup_text += "*✅ Code Commits:*\nNo recent commits.\n\n"

    if jira_updates:
        standup_text += "*📌 Jira Updates:*\n" + "\n".join(jira_updates)
    else:
        standup_text += "*📌 Jira Updates:*\nNo recent activity."

    return standup_text


def async_generate_standup() -> None:
    """
    Generates the standup report asynchronously and sends it to Slack using a response URL.

    :param response_url: The Slack response URL to send the delayed message.
    :return: None
    """
    standup_report = generate_standup_report()
    send_message_to_slack(client, standup_report, SLACK_CHANNEL)


def handle_create_pr(
    jira_ticket: str,
    repo_name: str,
    feature_branch: Optional[str] = None,
    move_to_review: bool = True,
) -> None:
    """
    Creates PR and manages Jira automation.
    """

    try:
        feature_branch = feature_branch or jira_ticket
        ticket_link = f"<{JIRA_BASE_URL}/browse/{jira_ticket}|{jira_ticket}>"

        pr_created = False
        jira_link_added = False
        ticket_moved = False
        ticket_assigned = False

        branches = get_repo_branches(repo_name)

        if not branches:
            send_message_to_slack(
                client,
                f"Unable to fetch branches for repo `{repo_name}`.",
                SLACK_CHANNEL
            )
            return

        dev_branch = detect_dev_branch(branches)

        validate_branch_exists(repo_name, feature_branch)

        existing_pr = get_existing_pr(repo_name, feature_branch, dev_branch)

        if existing_pr:
            pr_url = existing_pr["html_url"]
        else:

            pr = create_pull_request(
                repo=repo_name,
                feature_branch=feature_branch,
                dev_branch=dev_branch,
                jira_ticket=jira_ticket
            )

            pr_url = pr["html_url"]
            pr_created = True

        if not jira_weblink_exists(jira_ticket, pr_url):

            add_jira_pr_link(
                ticket=jira_ticket,
                pr_url=pr_url,
                repo=repo_name
            )

            jira_link_added = True

        current_status = get_jira_issue_status(jira_ticket)

        if move_to_review:

            transitions = get_jira_transitions(jira_ticket)

            code_review_transition = next(
                (
                    t for t in transitions
                    if t["name"].lower() == JIRA_STATUS_CODE_REVIEW.lower()
                ),
                None
            )

            if code_review_transition:

                transition_jira_issue(
                    jira_ticket,
                    code_review_transition["id"]
                )

                ticket_moved = True

                qa_account_id = get_qa_tester_account_id(jira_ticket)

                assign_jira_issue(
                    jira_ticket,
                    qa_account_id
                )

                ticket_assigned = True

        message = [
            "*PR Automation Result*",
            "",
            f"*Ticket:* {ticket_link}",
            f"*Repo:* {repo_name}",
            f"*Feature Branch:* {feature_branch}",
            f"*Dev Branch:* {dev_branch}",
            "",
            f"*PR:* {pr_url}",
            ""
        ]

        if pr_created:
            message.append("• PR was created.")

        else:
            message.append("• PR already existed.")

        if jira_link_added:
            message.append("• Jira PR link was added.")

        else:
            message.append("• Jira PR link already existed.")

        if ticket_moved:
            message.append("• Ticket moved to *CodeReview*.")

        if ticket_assigned:
            message.append("• Ticket assigned to QA tester.")

        if move_to_review and not ticket_moved:
            message.append(
                f"• Ticket status is `{current_status}`, so no workflow change was performed."
            )

        send_message_to_slack(
            client,
            "\n".join(message),
            SLACK_CHANNEL
        )

    except Exception as e:

        send_message_to_slack(
            client,
            f"PR automation failed: {str(e)}",
            SLACK_CHANNEL
        )


def handle_create_prod_pr(
    jira_ticket: str,
    feature_branch: Optional[str] = None,
    repo_name: Optional[str] = None,
) -> None:
    """
    For a given Jira ticket, reads the open DEV PR links (optionally filtered to one repo), then:
      1. Fetches commits from the DEV PR (for reference in the PR body).
      2. Detects the prod branch.
      3. Creates a branch named '{feature-branch-or-ticket-id}-Prod' from prod's HEAD.
      4. Opens a PROD PR from that branch into the prod branch.
      5. Adds the PROD PR link back to the Jira ticket.
    """

    try:
        feature_branch = feature_branch or jira_ticket
        ticket_link = f"<{JIRA_BASE_URL}/browse/{jira_ticket}|{jira_ticket}>"

        dev_links = get_dev_pr_links(jira_ticket)

        if not dev_links:
            send_message_to_slack(
                client,
                f"No DEV PR links found on ticket {ticket_link}. Add DEV PRs first via `/createpr`.",
                SLACK_CHANNEL
            )
            return

        if repo_name:
            filtered_dev_links = filter_dev_pr_links(dev_links, repo_name)
            if not filtered_dev_links:
                available_repos = ", ".join(sorted({link["repo"] for link in dev_links}))
                send_message_to_slack(
                    client,
                    (
                        f"No DEV PR link found for repo `{repo_name}` on ticket {ticket_link}. "
                        f"Available repos: {available_repos}"
                    ),
                    SLACK_CHANNEL
                )
                return
            dev_links = filtered_dev_links

        prod_branch_name = f"{feature_branch}-Prod"
        results = []

        for link in dev_links:

            repo = link["repo"]
            dev_pr_url = link["url"]

            try:

                pr_number = get_pr_number_from_url(dev_pr_url)

                # Collect commit references from the DEV PR for the PROD PR body
                raw_commits = get_pr_commits(repo, pr_number)
                commit_refs = [
                    (c["sha"], c["commit"]["message"].split("\n")[0])
                    for c in raw_commits
                ]

                branches = get_repo_branches(repo)
                prod_branch = detect_prod_branch(branches)

                # Create PROD branch from production's HEAD (clean base, no dev-only commits)
                prod_head_sha = get_branch_sha(repo, prod_branch)

                branch_created = False
                try:
                    create_branch(repo, prod_branch_name, prod_head_sha)
                    branch_created = True
                except Exception as branch_err:
                    if "already exists" not in str(branch_err):
                        raise

                # Cherry-pick each DEV commit onto the PROD branch
                picked = cherry_pick_commits_onto_branch(repo, raw_commits, prod_branch_name)

                # Check for an existing open PROD PR before creating one
                existing_pr = get_existing_pr(repo, prod_branch_name, prod_branch)

                if existing_pr:
                    prod_pr_url = existing_pr["html_url"]
                    pr_created = False
                    # Refresh the PR body with the latest cherry-picked commit list
                    if commit_refs:
                        updated_body = (
                            f"Jira ticket: {jira_ticket}\n\n"
                            f"**Cherry-picked commits from DEV PR:**\n"
                            + "\n".join(f"- `{sha[:7]}` {msg}" for sha, msg in commit_refs)
                        )
                        update_pull_request_body(repo, existing_pr["number"], updated_body)
                else:
                    prod_pr = create_prod_pull_request(
                        repo=repo,
                        prod_branch_name=prod_branch_name,
                        target_prod_branch=prod_branch,
                        jira_ticket=jira_ticket,
                        commit_refs=commit_refs
                    )
                    prod_pr_url = prod_pr["html_url"]
                    pr_created = True

                jira_link_added = False
                if not jira_weblink_exists(jira_ticket, prod_pr_url):
                    add_jira_prod_pr_link(jira_ticket, prod_pr_url, repo)
                    jira_link_added = True

                results.append({
                    "repo": repo,
                    "prod_branch": prod_branch,
                    "prod_pr_url": prod_pr_url,
                    "branch_created": branch_created,
                    "pr_created": pr_created,
                    "jira_link_added": jira_link_added,
                    "commits_picked": picked,
                    "error": None
                })

            except Exception as repo_err:
                results.append({"repo": repo, "error": str(repo_err)})

        # Build the Slack summary
        message = [
            "*PROD PR Automation Result*",
            "",
            f"*Ticket:* {ticket_link}",
            f"*PROD Branch Name:* {prod_branch_name}",
            f"*Repo Filter:* `{repo_name}`" if repo_name else "*Repo Filter:* All repos",
            f"*DEV PRs processed:* {len(dev_links)}",
            ""
        ]

        for r in results:
            if r["error"]:
                message.append(f"*{r['repo']}:* Failed — {r['error']}")
            else:
                bullets = []

                if r["branch_created"]:
                    bullets.append(f"Branch `{prod_branch_name}` created from `{r['prod_branch']}`.")
                else:
                    bullets.append(f"Branch `{prod_branch_name}` already existed.")

                if r["pr_created"]:
                    bullets.append(f"PROD PR created: {r['prod_pr_url']}")
                else:
                    bullets.append(f"PROD PR already existed: {r['prod_pr_url']}")

                if r["jira_link_added"]:
                    bullets.append("Jira PROD link added.")
                else:
                    bullets.append("Jira PROD link already existed.")

                bullets.append(f"Commits cherry-picked: {r['commits_picked']}")

                message.append(f"*{r['repo']}:*")
                message.extend([f"  • {b}" for b in bullets])

            message.append("")

        send_message_to_slack(client, "\n".join(message), SLACK_CHANNEL)

    except Exception as e:

        send_message_to_slack(
            client,
            f"PROD PR automation failed: {str(e)}",
            SLACK_CHANNEL
        )
