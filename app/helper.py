import requests
import os
from datetime import datetime, timedelta
from typing import List, Dict, Any
from .constants import *

def fetch_filtered_repositories() -> List[str]:
    """
    Fetches all repositories in the organization that match search keywords, handling pagination.
    :return: List[str] -> A list of filtered repository names.
    """
    url = f"{GITHUB_BASE_URI}/orgs/{GITHUB_ORG}/repos"
    response = requests.get(url, headers=GITHUB_HEADERS)
    if response.status_code != 200:
        return []
    
    search_keywords = os.getenv("REPO_SEARCH_KEYWORDS", "").split(",")
    repos = response.json()
    return [repo["name"] for repo in repos if any(k.lower() in repo["name"].lower() for k in search_keywords)]

def fetch_pull_requests(repo: str) -> List[Dict[str, Any]]:
    """
    Fetches open pull requests for a given repository.
    :param repo: str -> The name of the repository.
    :return: List[Dict[str, Any]] -> A list of open pull requests.
    """
    url = f"{GITHUB_BASE_URI}/repos/{GITHUB_ORG}/{repo}/pulls"
    response = requests.get(url, headers=GITHUB_HEADERS)
    if response.status_code == 200:
        return response.json()
    return []

def fetch_recent_commits() -> List[str]:
    """
    Fetches recent commits from tracked repositories.
    :return: A list of formatted commit messages with repository names and URLs.
    """
    since = (datetime.utcnow() - timedelta(days=1)).isoformat() + "Z"
    repositories = fetch_filtered_repositories()
    user_commits = []

    for repo in repositories:
        url = f"{GITHUB_BASE_URI}/repos/{GITHUB_ORG}/{repo}/commits"
        response = requests.get(url, headers=GITHUB_HEADERS, params={"author": GITHUB_USERNAME, "since": since})
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
