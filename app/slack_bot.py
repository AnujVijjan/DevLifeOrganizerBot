import requests
from slack_sdk import WebClient
from datetime import datetime, timedelta
from typing import List, Tuple, Dict, Any
from .models import get_tasks_from_db
import sqlite3
from .helper import (
    fetch_filtered_repositories, 
    fetch_pull_requests, 
    fetch_recent_commits, 
    fetch_recent_jira_updates,
    get_repo_branches,
    detect_dev_branch,
    validate_branch_exists,
    get_existing_pr,
    jira_weblink_exists,
    create_pull_request,
    add_jira_pr_link,
    get_jira_issue_status,
    get_qa_tester_account_id,
    assign_jira_issue,
    get_jira_transitions,
    transition_jira_issue
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


def handle_create_pr(jira_ticket: str, feature_branch: str, repo_name: str) -> None:
    """
    Creates PR and manages Jira automation.
    """

    try:

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

        if current_status == JIRA_STATUS_IN_PROGRESS:

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

        if current_status != JIRA_STATUS_IN_PROGRESS:
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