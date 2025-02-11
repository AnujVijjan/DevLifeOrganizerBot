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
    fetch_recent_jira_updates
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