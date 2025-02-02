import os
import requests
from slack_sdk import WebClient
from dotenv import load_dotenv
from datetime import datetime, timedelta
from .models import get_tasks_from_db

# Load environment variables
load_dotenv()

SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_CHANNEL = os.getenv("SLACK_CHANNEL")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_USERNAME = os.getenv("GITHUB_USERNAME")
GITHUB_ORG = os.getenv("GITHUB_ORG")

GITHUB_BASE_URI = "https://api.github.com"

client = WebClient(token=SLACK_BOT_TOKEN)

HEADERS = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json"
}

def fetch_filtered_repositories():
    """ Fetches all repositories in the organization that match search keywords, handling pagination. """
    url = f"{GITHUB_BASE_URI}/orgs/{GITHUB_ORG}/repos"
    all_repos = []
    page = 1

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

    search_keywords = os.getenv("REPO_SEARCH_KEYWORDS", "").split(",")

    filtered_repos = [
        repo["name"]
        for repo in all_repos
        if any(keyword.strip().lower() in repo["name"].lower() for keyword in search_keywords)
    ]

    return filtered_repos

def fetch_pull_requests(repo):
    """ Fetches open pull requests assigned to the user. """
    url = f"{GITHUB_BASE_URI}/repos/{GITHUB_ORG}/{repo}/pulls"
    response = requests.get(url, headers=HEADERS)

    if response.status_code == 200:
        return response.json()
    else:
        return []   

def get_review_reminders():
    """ Checks PRs across filtered repositories in the organization """
    repos = fetch_filtered_repositories()
    assigned_prs, pending_reviews, stale_prs = [], [], []

    # Define stale PR threshold (7 days without activity)
    stale_threshold = datetime.utcnow() - timedelta(days=7)

    for repo in repos:
        prs = fetch_pull_requests(repo)

        for pr in prs:
            pr_title = pr["title"]
            pr_url = pr["html_url"]
            pr_updated_at = datetime.strptime(pr["updated_at"], "%Y-%m-%dT%H:%M:%SZ")
            pr_assignees = [assignee["login"] for assignee in pr.get("assignees", [])]

            # Check if the user is assigned to a PR
            if GITHUB_USERNAME in pr_assignees:
                assigned_prs.append(f"🔹 *[{repo}]* {pr_title} - {pr_url}")

            # Check if the PR is stale (no updates for a week)
            if pr_updated_at < stale_threshold:
                stale_prs.append(f"⚠️ *[{repo}]* {pr_title} (Stale for 7+ days) - {pr_url}")

            # Check if PR is waiting for review
            review_url = pr["_links"]["review_comments"]["href"]
            review_response = requests.get(review_url, headers=HEADERS)
            if review_response.status_code == 200 and len(review_response.json()) == 0:
                pending_reviews.append(f"📌 *[{repo}]* {pr_title} - {pr_url} (Waiting for review)")

    return assigned_prs, pending_reviews, stale_prs

def send_code_review_reminder():
    """ Sends a Slack notification for PR reviews and stale PRs. """
    assigned_prs, pending_reviews, stale_prs = get_review_reminders()
    messages = []

    if assigned_prs:
        messages.append("*📢 PRs Assigned to You:*")
        messages.extend(assigned_prs)

    if pending_reviews:
        messages.append("\n*⏳ PRs Waiting for Review:*")
        messages.extend(pending_reviews)

    if stale_prs:
        messages.append("\n*⚠️ Stale PRs (No activity for 7+ days):*")
        messages.extend(stale_prs)

    if messages:
        message = "\n".join(messages)
    else:
        message = "✅ No pending PRs or stale reviews. Keep coding! 🚀"

    client.chat_postMessage(channel=SLACK_CHANNEL, text=message)

def send_message_to_slack(message):
    client.chat_postMessage(channel=SLACK_CHANNEL, text=message)

def send_daily_summary():
    tasks = get_tasks_from_db()
    if not tasks:
        message = "No tasks for today! 🚀"
    else:
        message = "📝 *Your Tasks for Today:*\n" + "\n".join(f"• {task[0]}" for task in tasks)

    send_message_to_slack(message)
