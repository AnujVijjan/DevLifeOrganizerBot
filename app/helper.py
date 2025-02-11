import requests
from datetime import datetime, timedelta
from typing import List, Dict, Any
from .constants import *

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
        response = requests.get(url, headers=GITHUB_HEADERS, params={"per_page": 100, "page": page})

        if response.status_code != 200:
            print(f"Error fetching repos: {response.json()}")
            return []

        repos = response.json()
        if not repos:
            break

        all_repos.extend(repos)
        page += 1

    search_keywords: List[str] = REPO_SEARCH_KEYWORDS.split(",")

    filtered_repos: List[str] = [
        repo["name"]
        for repo in all_repos
        if any(keyword.strip().lower() in repo["name"].lower() for keyword in search_keywords)
    ]

    return filtered_repos

def fetch_pull_requests(repo: str) -> List[Dict[str, Any]]:
    """
    Fetches open pull requests for a given repository, filtering by specified branch names.
    
    :param repo: str -> The name of the repository.
    :return: List[Dict[str, Any]] -> A list of open pull requests that target one of the specified branches.
    """
    url = f"{GITHUB_BASE_URI}/repos/{GITHUB_ORG}/{repo}/pulls"
    response = requests.get(url, headers=GITHUB_HEADERS)
    if response.status_code != 200:
        return []
    
    pr_list = response.json()
    branch_names = [branch.strip() for branch in GITHUB_BRANCH_NAMES.split(",") if branch.strip()]
    # Filter PRs to include only those where the base branch is in our list
    filtered_pr_list = [
        pr for pr in pr_list if pr.get("base", {}).get("ref") in branch_names
    ]
    
    return filtered_pr_list

def fetch_recent_commits() -> List[str]:
    """
    Fetches recent commits from tracked repositories on the specified branches.
    
    :return: A list of formatted commit messages with repository names, branch, and commit URLs.
    """
    since = (datetime.utcnow() - timedelta(days=1)).isoformat() + "Z"
    repositories = fetch_filtered_repositories()
    user_commits = []
    branch_names = [branch.strip() for branch in GITHUB_BRANCH_NAMES.split(",") if branch.strip()]
    
    for repo in repositories:
        for branch in branch_names:
            url = f"{GITHUB_BASE_URI}/repos/{GITHUB_ORG}/{repo}/commits"
            params = {
                "author": GITHUB_USERNAME,
                "since": since,
                "sha": branch  # specify branch to fetch commits from
            }
            response = requests.get(url, headers=GITHUB_HEADERS, params=params)
            if response.status_code == 200:
                commits = response.json()
                for commit in commits:
                    message = commit["commit"]["message"]
                    commit_url = commit["html_url"]
                    user_commits.append(f"🔹 *{repo}* ({branch}) - {message} [{commit_url}]")
    
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
