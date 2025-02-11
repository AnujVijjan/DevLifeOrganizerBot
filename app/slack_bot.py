import os
import requests
from slack_sdk import WebClient
from dotenv import load_dotenv
from datetime import datetime, timedelta
from typing import List, Tuple, Dict, Any
from .models import get_tasks_from_db
import sqlite3
import os
import base64

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'instance', 'bot_data.db')

# Load environment variables
load_dotenv()

SLACK_BOT_TOKEN: str = os.getenv("SLACK_BOT_TOKEN")
SLACK_CHANNEL: str = os.getenv("SLACK_CHANNEL")
GITHUB_TOKEN: str = os.getenv("GITHUB_TOKEN")
GITHUB_USERNAME: str = os.getenv("GITHUB_USERNAME")
GITHUB_ORG: str = os.getenv("GITHUB_ORG")

GITHUB_BASE_URI: str = "https://api.github.com"

SLACK_USER_TOKEN: str = os.getenv("SLACK_USER_TOKEN")
SLACK_USER_ID: str = os.getenv("SLACK_USER_ID")

client = WebClient(token=SLACK_BOT_TOKEN)

user_client = WebClient(token=SLACK_USER_TOKEN)

HEADERS: Dict[str, str] = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json"
}

JIRA_BASE_URL: str = os.getenv("JIRA_BASE_URL")
JIRA_EMAIL: str = os.getenv("JIRA_EMAIL")
JIRA_API_TOKEN: str = os.getenv("JIRA_API_TOKEN")
JIRA_PROJECT_KEY: str = os.getenv("JIRA_PROJECT_KEY")

JIRA_HEADERS: Dict[str, str] = {
    "Authorization": f"Basic {base64.b64encode(f'{JIRA_EMAIL}:{JIRA_API_TOKEN}'.encode()).decode()}",
    "Content-Type": "application/json"
}


def fetch_filtered_repositories() -> List[str]:
    """
    Fetches all repositories in the organization that match search keywords, handling pagination.

    :return: List[str] -> A list of filtered repository names.
    :raises requests.RequestException: If the request to GitHub API fails.
    """
    url: str = f"{GITHUB_BASE_URI}/orgs/{GITHUB_ORG}/repos"
    all_repos: List[Dict[str, Any]] = []
    page: int = 1

    while True:
        response = requests.get(url, headers=HEADERS, params={"per_page": 100, "page": page})

        if response.status_code != 200:
            print(f"Error fetching repos: {response.json()}")
            return []

        repos = response.json()
        if not repos:
            break

        all_repos.extend(repos)
        page += 1

    search_keywords: List[str] = os.getenv("REPO_SEARCH_KEYWORDS", "").split(",")

    filtered_repos: List[str] = [
        repo["name"]
        for repo in all_repos
        if any(keyword.strip().lower() in repo["name"].lower() for keyword in search_keywords)
    ]

    return filtered_repos


def fetch_pull_requests(repo: str) -> List[Dict[str, Any]]:
    """
    Fetches open pull requests for a given repository.

    :param repo: str -> The name of the repository.
    :return: List[Dict[str, Any]] -> A list of open pull requests.
    :raises requests.RequestException: If the request to GitHub API fails.
    """
    url: str = f"{GITHUB_BASE_URI}/repos/{GITHUB_ORG}/{repo}/pulls"
    response = requests.get(url, headers=HEADERS)

    if response.status_code == 200:
        return response.json()
    else:
        return []


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
            review_response = requests.get(review_url, headers=HEADERS)
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


def fetch_recent_commits() -> List[str]:
    """
    Fetches recent commits from tracked repositories for the authenticated user.

    :return: A list of formatted commit messages with repository names and URLs.
    """
    since = (datetime.utcnow() - timedelta(days=1)).isoformat() + "Z"
    repositories = fetch_filtered_repositories()
    user_commits = []

    for repo in repositories:
        url = f"{GITHUB_BASE_URI}/repos/{GITHUB_ORG}/{repo}/commits"
        response = requests.get(url, headers=HEADERS, params={"author": GITHUB_USERNAME, "since": since})
        
        if response.status_code == 200:
            commits = response.json()
            for commit in commits:
                message = commit["commit"]["message"]
                url = commit["html_url"]
                user_commits.append(f"🔹 *{repo}* - {message} [{url}]")

    return user_commits


def fetch_recent_jira_updates() -> List[str]:
    """
    Fetches Jira issues that were updated in the last 24 hours for the authenticated user.

    :return: A list of formatted Jira issue updates with their status and URLs.
    """
    since = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M")
    jql_query = f'project = {JIRA_PROJECT_KEY} AND assignee = "{JIRA_EMAIL}" AND updated >= "{since}" ORDER BY updated DESC'
    
    url = f"{JIRA_BASE_URL}/rest/api/2/search"
    response = requests.get(url, headers=JIRA_HEADERS, params={"jql": jql_query, "maxResults": 10})
    
    updates = []
    if response.status_code == 200:
        issues = response.json()["issues"]
        for issue in issues:
            key = issue["key"]
            summary = issue["fields"]["summary"]
            status = issue["fields"]["status"]["name"]
            url = f"{JIRA_BASE_URL}/browse/{key}"
            updates.append(f"📝 *{key}* - {summary} ({status}) [{url}]")

    return updates


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