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
                "sha": branch
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

def get_repo_branches(repo: str) -> List[str]:
    """
    Fetch all branches for a repository.
    """

    url = f"{GITHUB_BASE_URI}/repos/{GITHUB_ORG}/{repo}/branches"

    response = requests.get(url, headers=GITHUB_HEADERS)

    if response.status_code != 200:
        raise Exception(f"Unable to fetch branches: {response.text}")

    return [branch["name"] for branch in response.json()]

def detect_dev_branch(branches: List[str]) -> str:
    """
    Determines dev branch using priority detection.
    """

    branch_set = set(branches)

    for branch in ["develop", "dev", "main", "master"]:
        if branch in branch_set:
            return branch

    raise Exception(f"Unable to determine dev branch from branches: {branches}")

def validate_branch_exists(repo: str, branch: str) -> None:
    """
    Ensures the feature branch exists in repo.
    """

    url = f"{GITHUB_BASE_URI}/repos/{GITHUB_ORG}/{repo}/branches/{branch}"

    response = requests.get(url, headers=GITHUB_HEADERS)

    if response.status_code != 200:
        raise Exception(f"Branch `{branch}` does not exist in repo `{repo}`.")
    
def get_existing_pr(repo: str, feature_branch: str, dev_branch: str):
    """
    Returns existing PR if present.
    """

    url = f"{GITHUB_BASE_URI}/repos/{GITHUB_ORG}/{repo}/pulls"

    params = {
        "head": f"{GITHUB_ORG}:{feature_branch}",
        "base": dev_branch,
        "state": "open"
    }

    response = requests.get(url, headers=GITHUB_HEADERS, params=params)

    if response.status_code != 200:
        return None

    prs = response.json()

    if prs:
        return prs[0]

    return None

def create_pull_request(repo: str, feature_branch: str, dev_branch: str, jira_ticket: str) -> Dict[str, Any]:

    url = f"{GITHUB_BASE_URI}/repos/{GITHUB_ORG}/{repo}/pulls"

    payload = {
        "title": f"[{jira_ticket}] Merge {feature_branch} into {dev_branch}",
        "head": feature_branch,
        "base": dev_branch,
        "body": f"Auto-created PR for Jira ticket {jira_ticket}"
    }

    response = requests.post(url, headers=GITHUB_HEADERS, json=payload)

    if response.status_code not in [200, 201]:
        raise Exception(f"GitHub PR creation failed: {response.text}")

    return response.json()

def add_jira_pr_link(ticket: str, pr_url: str, repo: str):

    url = f"{JIRA_BASE_URL}/rest/api/3/issue/{ticket}/remotelink"

    payload = {
        "object": {
            "url": pr_url,
            "title": f"{repo} (DEV)"
        }
    }

    response = requests.post(url, headers=JIRA_HEADERS, json=payload)

    if response.status_code not in [200, 201]:
        raise Exception(f"Failed to add Jira link: {response.text}")
    
def jira_weblink_exists(ticket: str, url: str) -> bool:
    """
    Checks if a Jira issue already has the PR web link.
    """

    api = f"{JIRA_BASE_URL}/rest/api/3/issue/{ticket}/remotelink"

    response = requests.get(api, headers=JIRA_HEADERS)

    if response.status_code != 200:
        return False

    links = response.json()

    for link in links:
        if link.get("object", {}).get("url") == url:
            return True

    return False

def get_jira_issue(ticket: str):

    url = f"{JIRA_BASE_URL}/rest/api/3/issue/{ticket}"

    response = requests.get(url, headers=JIRA_HEADERS)

    if response.status_code != 200:
        raise Exception(f"Unable to fetch Jira issue {ticket}")

    return response.json()

def get_jira_issue(ticket: str):

    url = f"{JIRA_BASE_URL}/rest/api/3/issue/{ticket}"

    response = requests.get(url, headers=JIRA_HEADERS)

    if response.status_code != 200:
        raise Exception(f"Unable to fetch Jira issue {ticket}")

    return response.json()

def get_qa_tester_account_id(ticket: str):

    issue = get_jira_issue(ticket)

    qa_field = issue["fields"].get(JIRA_QA_TESTER_FIELD)

    if not qa_field:
        raise Exception("QA Tester not set on Jira ticket.")

    # If field returns a list (multi user picker)
    if isinstance(qa_field, list):
        return qa_field[0]["accountId"]

    # If field returns a single user
    return qa_field["accountId"]

def assign_jira_issue(ticket: str, account_id: str):

    url = f"{JIRA_BASE_URL}/rest/api/3/issue/{ticket}/assignee"

    payload = {
        "accountId": account_id
    }

    response = requests.put(url, headers=JIRA_HEADERS, json=payload)

    if response.status_code not in [200, 204]:
        raise Exception("Failed to assign Jira issue.")
    
def get_jira_transitions(ticket: str):

    url = f"{JIRA_BASE_URL}/rest/api/3/issue/{ticket}/transitions"

    response = requests.get(url, headers=JIRA_HEADERS)

    if response.status_code != 200:
        raise Exception("Failed to fetch Jira transitions")

    data = response.json()

    return data.get("transitions", [])

def transition_jira_issue(ticket: str, transition_id: str):

    url = f"{JIRA_BASE_URL}/rest/api/3/issue/{ticket}/transitions"

    payload = {
        "transition": {
            "id": transition_id
        }
    }

    response = requests.post(url, headers=JIRA_HEADERS, json=payload)

    if response.status_code not in [200, 204]:
        raise Exception("Failed to transition Jira issue.")
    
def get_jira_issue_status(ticket: str) -> str:
    """
    Returns the current Jira issue status.
    """

    issue = get_jira_issue(ticket)

    return issue["fields"]["status"]["name"]