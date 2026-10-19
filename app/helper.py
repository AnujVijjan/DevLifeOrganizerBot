import os
import re
import json
import base64
import difflib
import requests
from functools import lru_cache
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple
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
    Fetch all branches for a repository, handling pagination.
    """

    url = f"{GITHUB_BASE_URI}/repos/{GITHUB_ORG}/{repo}/branches"
    all_branches: List[str] = []
    page = 1

    while True:
        response = requests.get(url, headers=GITHUB_HEADERS, params={"per_page": 100, "page": page})

        if response.status_code != 200:
            raise Exception(f"Unable to fetch branches: {response.text}")

        branches = response.json()

        if not branches:
            break

        all_branches.extend(branch["name"] for branch in branches)
        page += 1

    return all_branches

@lru_cache(maxsize=1)
def load_repo_config() -> Dict[str, Dict[str, str]]:
    """
    Loads per-repo branch overrides from REPO_CONFIG_FILE as a lowercase-keyed
    {repo: {dev_branch|uat_branch|prod_branch: name}} map. A missing file means
    no overrides.
    """

    if not os.path.isfile(REPO_CONFIG_FILE):
        return {}

    with open(REPO_CONFIG_FILE, encoding="utf-8") as config_file:
        data = json.load(config_file)

    return {name.lower(): overrides for name, overrides in data.get("repos", {}).items()}

def get_branch_override(repo: Optional[str], kind: str) -> Optional[str]:
    """
    Returns the configured branch for a repo and kind (dev_branch, uat_branch or
    prod_branch), or None when no override is set.
    """

    if not repo:
        return None

    return load_repo_config().get(repo.lower(), {}).get(kind)

def _resolve_branch(
    branches: List[str],
    repo: Optional[str],
    kind: str,
    candidates: List[str],
) -> str:
    """
    Returns the repo's configured override for the branch kind when present,
    validating it exists; otherwise the first candidate found in branches.
    """

    label = BRANCH_KIND_LABELS[kind]
    override = get_branch_override(repo, kind)

    if override:
        if override not in branches:
            raise Exception(
                f"Configured {label} branch `{override}` for `{repo}` was not found in the repo's branches."
            )
        return override

    branch_set = set(branches)

    for branch in candidates:
        if branch in branch_set:
            return branch

    raise Exception(f"Unable to determine {label} branch from branches: {branches}")

def detect_dev_branch(branches: List[str], repo: Optional[str] = None) -> str:
    """
    Determines the dev branch: the repo's configured override, else the first of
    DEV_BRANCH_CANDIDATES present.
    """

    return _resolve_branch(branches, repo, "dev_branch", DEV_BRANCH_CANDIDATES)

def ensure_feature_branch_differs(feature_branch: str, dev_branch: str) -> None:
    """
    Raises when the feature branch is the dev branch itself, which would make a
    PR that targets itself.
    """

    if feature_branch == dev_branch:
        raise Exception(
            f"Feature branch `{feature_branch}` is the same as the dev branch. "
            "Pass a different feature branch with `--branch`."
        )

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
        "body": f"Jira ticket: {jira_ticket}"
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
    
def extract_jira_ticket_key(value: str) -> str:
    """
    Extracts a bare Jira ticket key (e.g. PROJ-123) from either a full Jira link
    (https://company.atlassian.net/browse/PROJ-123) or an already-bare key.
    """

    match = re.search(r"([A-Za-z][A-Za-z0-9]*-\d+)", value)
    if not match:
        raise ValueError(f"Could not find a Jira ticket key in '{value}'.")

    return match.group(1).upper()

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

def get_qa_tester_account_id(ticket: str) -> Optional[str]:
    """
    Returns the QA tester's Jira account id from the ticket's QA field, or None
    when JIRA_QA_TESTER_FIELD is not configured. Raises if the field is
    configured but empty on the ticket.
    """

    if not JIRA_QA_TESTER_FIELD:
        return None

    issue = get_jira_issue(ticket)

    qa_field = issue["fields"].get(JIRA_QA_TESTER_FIELD)

    if not qa_field:
        raise Exception("QA Tester not set on Jira ticket.")

    if isinstance(qa_field, list):
        return qa_field[0]["accountId"]

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

def get_jira_myself_account_id() -> str:
    """
    Returns the Jira account id of the user the API token belongs to.
    """

    response = requests.get(f"{JIRA_BASE_URL}/rest/api/3/myself", headers=JIRA_HEADERS)

    if response.status_code != 200:
        raise Exception("Failed to fetch the current Jira user.")

    return response.json()["accountId"]

def find_jira_user_account_id(query: str) -> str:
    """
    Finds a single active Jira user by name or email. Raises when there is no
    match or the query is ambiguous.
    """

    response = requests.get(
        f"{JIRA_BASE_URL}/rest/api/3/user/search",
        headers=JIRA_HEADERS,
        params={"query": query},
    )

    if response.status_code != 200:
        raise Exception(f"Failed to search Jira users for `{query}`: {response.text}")

    users = [
        user for user in response.json()
        if user.get("accountType", "atlassian") == "atlassian" and user.get("active", True)
    ]
    wanted = query.lower()
    exact = [
        user for user in users
        if wanted in (user.get("emailAddress", "").lower(), user.get("displayName", "").lower())
    ]
    matches = exact or users

    if not matches:
        raise Exception(f"No Jira user found for `{query}`.")

    if len(matches) > 1:
        names = ", ".join(user.get("displayName", user["accountId"]) for user in matches[:5])
        raise Exception(f"`{query}` matches several Jira users ({names}). Use a fuller name or email.")

    return matches[0]["accountId"]

def resolve_assignee_account_id(ticket: str, assignee: str) -> str:
    """
    Resolves an assignee to a Jira account id: `qa` is the ticket's QA tester,
    `me` is the API user, anything else is looked up by name or email.
    """

    key = assignee.strip().lower()

    if key == DEFAULT_ASSIGNEE:
        account_id = get_qa_tester_account_id(ticket)
        if not account_id:
            raise Exception("JIRA_QA_TESTER_FIELD is not configured, so `qa` can't be resolved. Pass a name or email.")
        return account_id

    if key == "me":
        return get_jira_myself_account_id()

    return find_jira_user_account_id(assignee.strip())

def find_jira_transition(ticket: str, target: str) -> Optional[Dict[str, Any]]:
    """
    Returns the available transition whose name or destination status matches
    target (case-insensitive), or None.
    """

    wanted = target.strip().lower()

    return next(
        (
            t for t in get_jira_transitions(ticket)
            if t["name"].lower() == wanted or t.get("to", {}).get("name", "").lower() == wanted
        ),
        None,
    )

def apply_jira_workflow(
    ticket: str,
    transition_to: Optional[str] = None,
    assign_to: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Optionally moves the ticket to a status and assigns it. The assignee is
    resolved first so a bad name fails before anything changes. Returns
    {"status_before", "transitioned", "assigned"}; transitioned is False when no
    matching transition is available from the current status.
    """

    result = {"status_before": None, "transitioned": False, "assigned": False}

    account_id = resolve_assignee_account_id(ticket, assign_to) if assign_to else None

    if transition_to:
        result["status_before"] = get_jira_issue_status(ticket)
        transition = find_jira_transition(ticket, transition_to)

        if transition:
            transition_jira_issue(ticket, transition["id"])
            result["transitioned"] = True

    if account_id:
        assign_jira_issue(ticket, account_id)
        result["assigned"] = True

    return result

def get_jira_remote_links(ticket: str) -> List[Dict[str, Any]]:
    """
    Returns all remote links attached to a Jira ticket.
    """

    url = f"{JIRA_BASE_URL}/rest/api/3/issue/{ticket}/remotelink"

    response = requests.get(url, headers=JIRA_HEADERS)

    if response.status_code != 200:
        raise Exception(f"Failed to fetch remote links for {ticket}: {response.text}")

    return response.json()

def get_env_pr_links(ticket: str, env_label: str) -> List[Dict[str, Any]]:
    """
    Returns PR links tagged for the given environment (e.g. "DEV", "UAT", "PROD")
    from a Jira ticket's remote links. Each item has: url, title, repo.
    """

    links = get_jira_remote_links(ticket)
    suffix = f"({env_label})"

    env_links = []

    for link in links:
        obj = link.get("object", {})
        title = obj.get("title", "")
        url = obj.get("url", "")

        if title.endswith(suffix) and url:
            repo = title[: -len(suffix)].strip()
            env_links.append({"url": url, "title": title, "repo": repo})

    return env_links

def get_dev_pr_links(ticket: str) -> List[Dict[str, Any]]:
    """
    Returns DEV PR links from a Jira ticket's remote links.
    Each item has: url, title, repo.
    """

    return get_env_pr_links(ticket, "DEV")

def get_uat_pr_links(ticket: str) -> List[Dict[str, Any]]:
    """
    Returns UAT PR links from a Jira ticket's remote links.
    Each item has: url, title, repo.
    """

    return get_env_pr_links(ticket, "UAT")

def get_prod_pr_links(ticket: str) -> List[Dict[str, Any]]:
    """
    Returns PROD PR links from a Jira ticket's remote links.
    Each item has: url, title, repo.
    """

    return get_env_pr_links(ticket, "PROD")

def filter_dev_pr_links(
    dev_links: List[Dict[str, Any]],
    repo: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Optionally narrows DEV PR links to a single repo using a case-insensitive match.
    """

    if not repo:
        return dev_links

    repo_name = repo.strip().lower()
    return [link for link in dev_links if link.get("repo", "").lower() == repo_name]

def resolve_createpr_inputs(
    jira_ticket: str,
    legacy_args: List[str],
    feature_branch: Optional[str] = None,
    repo_name: Optional[str] = None,
) -> Tuple[str, str]:
    """
    Resolves preferred flag-based inputs while keeping the legacy positional format valid.
    Legacy forms:
      createpr TICKET repo
      createpr TICKET feature-branch repo
    Preferred form:
      createpr TICKET --repo repo [--branch feature-branch]
    """

    resolved_branch = feature_branch.strip() if feature_branch else None
    resolved_repo = repo_name.strip() if repo_name else None
    positional = [arg.strip() for arg in legacy_args if arg and arg.strip()]

    if len(positional) > 2:
        raise ValueError(
            "Too many positional arguments. Use `createpr TICKET --repo REPO [--branch FEATURE]`."
        )

    if resolved_repo:
        if len(positional) == 2:
            raise ValueError("Repo was provided both positionally and with `--repo`.")
        if len(positional) == 1:
            if resolved_branch:
                raise ValueError(
                    "Do not mix legacy positional arguments with both `--branch` and `--repo`."
                )
            resolved_branch = positional[0]
    else:
        if not positional:
            raise ValueError(
                "Repository name is required. Use `--repo REPO` or the legacy positional form."
            )
        if len(positional) == 1:
            resolved_repo = positional[0]
        else:
            if resolved_branch:
                raise ValueError("Feature branch was provided both positionally and with `--branch`.")
            resolved_branch = positional[0]
            resolved_repo = positional[1]

    return resolved_branch or jira_ticket, resolved_repo

def resolve_createprodpr_inputs(
    jira_ticket: str,
    legacy_args: List[str],
    feature_branch: Optional[str] = None,
    repo_name: Optional[str] = None,
) -> Tuple[str, Optional[str]]:
    """
    Resolves preferred flag-based inputs while keeping the legacy positional feature branch valid.
    Legacy form:
      createprodpr TICKET [feature-branch]
    Preferred form:
      createprodpr TICKET [--branch feature-branch] [--repo repo]
    """

    resolved_branch = feature_branch.strip() if feature_branch else None
    resolved_repo = repo_name.strip() if repo_name else None
    positional = [arg.strip() for arg in legacy_args if arg and arg.strip()]

    if len(positional) > 1:
        raise ValueError(
            "Too many positional arguments. Use `createprodpr TICKET [--branch FEATURE] [--repo REPO]`."
        )

    if positional:
        if resolved_branch:
            raise ValueError("Feature branch was provided both positionally and with `--branch`.")
        resolved_branch = positional[0]

    return resolved_branch or jira_ticket, resolved_repo

def resolve_createuatpr_inputs(
    jira_ticket: str,
    legacy_args: List[str],
    feature_branch: Optional[str] = None,
    repo_name: Optional[str] = None,
) -> Tuple[str, Optional[str]]:
    """
    Resolves preferred flag-based inputs while keeping the legacy positional feature branch valid.
    Legacy form:
      createuatpr TICKET [feature-branch]
    Preferred form:
      createuatpr TICKET [--branch feature-branch] [--repo repo]
    """

    resolved_branch = feature_branch.strip() if feature_branch else None
    resolved_repo = repo_name.strip() if repo_name else None
    positional = [arg.strip() for arg in legacy_args if arg and arg.strip()]

    if len(positional) > 1:
        raise ValueError(
            "Too many positional arguments. Use `createuatpr TICKET [--branch FEATURE] [--repo REPO]`."
        )

    if positional:
        if resolved_branch:
            raise ValueError("Feature branch was provided both positionally and with `--branch`.")
        resolved_branch = positional[0]

    return resolved_branch or jira_ticket, resolved_repo

def get_pr_number_from_url(pr_url: str) -> int:
    """
    Extracts PR number from a GitHub PR URL.
    e.g. https://github.com/{org}/{repo}/pull/42 -> 42
    """

    parts = pr_url.rstrip("/").split("/")
    return int(parts[-1])

def parse_github_pr_url(value: str) -> Optional[Tuple[str, int]]:
    """
    Parses a GitHub PR URL (https://github.com/{org}/{repo}/pull/{number}) into
    (repo, pr_number). Returns None if value isn't a GitHub PR URL.
    """

    match = re.search(r"github\.com/[^/]+/(?P<repo>[^/]+)/pull/(?P<number>\d+)", value)
    if not match:
        return None

    return match.group("repo"), int(match.group("number"))

def get_pr_commits(repo: str, pr_number: int) -> List[Dict[str, Any]]:
    """
    Returns commit list for a given PR (sha + first line of message).
    """

    url = f"{GITHUB_BASE_URI}/repos/{GITHUB_ORG}/{repo}/pulls/{pr_number}/commits"

    response = requests.get(url, headers=GITHUB_HEADERS)

    if response.status_code != 200:
        return []

    return response.json()

def get_pr_files(repo: str, pr_number: int) -> List[Dict[str, Any]]:
    """
    Returns the changed-file list for a PR (filename, status, blob sha), handling
    pagination.
    """

    url = f"{GITHUB_BASE_URI}/repos/{GITHUB_ORG}/{repo}/pulls/{pr_number}/files"
    all_files: List[Dict[str, Any]] = []
    page = 1

    while True:
        response = requests.get(url, headers=GITHUB_HEADERS, params={"per_page": 100, "page": page})

        if response.status_code != 200:
            raise Exception(f"Failed to fetch files for PR #{pr_number} in `{repo}`: {response.text}")

        files = response.json()

        if not files:
            break

        all_files.extend(files)
        page += 1

    return all_files

def get_pr_file_content(repo: str, file_entry: Dict[str, Any]) -> Optional[str]:
    """
    Fetches a PR-changed file's full text content at the PR head commit, using the
    blob sha from a get_pr_files() entry. Returns None if the blob isn't decodable
    as UTF-8 text (e.g. binary).
    """

    lines = _get_blob_lines(repo, file_entry["sha"])
    if lines is None:
        return None

    return "".join(lines)

def get_pr_head_sha(repo: str, pr_number: int) -> str:
    """
    Returns the HEAD commit SHA of the PR's source branch.
    Used to create the PROD branch at the same point as the feature branch
    so the resulting PR against prod is not empty.
    """

    url = f"{GITHUB_BASE_URI}/repos/{GITHUB_ORG}/{repo}/pulls/{pr_number}"

    response = requests.get(url, headers=GITHUB_HEADERS)

    if response.status_code != 200:
        raise Exception(f"Failed to fetch PR #{pr_number} in `{repo}`: {response.text}")

    return response.json()["head"]["sha"]

def detect_prod_branch(branches: List[str], repo: Optional[str] = None) -> str:
    """
    Detects the production branch: the repo's configured override, else the first
    of PROD_BRANCH_CANDIDATES present.
    """

    return _resolve_branch(branches, repo, "prod_branch", PROD_BRANCH_CANDIDATES)

def detect_uat_branch(branches: List[str], repo: Optional[str] = None) -> str:
    """
    Detects the UAT branch: the repo's configured override, else the first of
    UAT_BRANCH_CANDIDATES present.
    """

    return _resolve_branch(branches, repo, "uat_branch", UAT_BRANCH_CANDIDATES)

def get_branch_sha(repo: str, branch: str) -> str:
    """
    Returns the HEAD commit SHA of a branch.
    """

    url = f"{GITHUB_BASE_URI}/repos/{GITHUB_ORG}/{repo}/branches/{branch}"

    response = requests.get(url, headers=GITHUB_HEADERS)

    if response.status_code != 200:
        raise Exception(f"Failed to fetch branch `{branch}` in `{repo}`: {response.text}")

    return response.json()["commit"]["sha"]

def create_branch(repo: str, branch_name: str, sha: str) -> None:
    """
    Creates a new branch pointing at the given commit SHA.
    Raises if the branch already exists or the API call fails.
    """

    url = f"{GITHUB_BASE_URI}/repos/{GITHUB_ORG}/{repo}/git/refs"

    payload = {
        "ref": f"refs/heads/{branch_name}",
        "sha": sha
    }

    response = requests.post(url, headers=GITHUB_HEADERS, json=payload)

    if response.status_code == 422:
        raise Exception(f"Branch `{branch_name}` already exists in `{repo}`.")

    if response.status_code not in [200, 201]:
        raise Exception(f"Failed to create branch `{branch_name}`: {response.text}")

def create_prod_pull_request(
    repo: str,
    prod_branch_name: str,
    target_prod_branch: str,
    jira_ticket: str,
    commit_refs: List[tuple]
) -> Dict[str, Any]:
    """
    Creates a PROD PR. commit_refs is a list of (sha, message) tuples from the DEV PR.
    """

    url = f"{GITHUB_BASE_URI}/repos/{GITHUB_ORG}/{repo}/pulls"

    if commit_refs:
        commit_list = "\n".join(f"- `{sha[:7]}` {msg}" for sha, msg in commit_refs)
        body = f"Jira ticket: {jira_ticket}\n\n**Cherry-picked commits from DEV PR:**\n{commit_list}"
    else:
        body = f"Jira ticket: {jira_ticket}"

    payload = {
        "title": f"[{jira_ticket}] PROD - Merge {prod_branch_name} into {target_prod_branch}",
        "head": prod_branch_name,
        "base": target_prod_branch,
        "body": body
    }

    response = requests.post(url, headers=GITHUB_HEADERS, json=payload)

    if response.status_code not in [200, 201]:
        raise Exception(f"GitHub PROD PR creation failed: {response.text}")

    return response.json()

def create_uat_pull_request(
    repo: str,
    uat_branch_name: str,
    target_uat_branch: str,
    jira_ticket: str,
    commit_refs: List[tuple]
) -> Dict[str, Any]:
    """
    Creates a UAT PR. commit_refs is a list of (sha, message) tuples from the DEV PR.
    """

    url = f"{GITHUB_BASE_URI}/repos/{GITHUB_ORG}/{repo}/pulls"

    if commit_refs:
        commit_list = "\n".join(f"- `{sha[:7]}` {msg}" for sha, msg in commit_refs)
        body = f"Jira ticket: {jira_ticket}\n\n**Cherry-picked commits from DEV PR:**\n{commit_list}"
    else:
        body = f"Jira ticket: {jira_ticket}"

    payload = {
        "title": f"[{jira_ticket}] UAT - Merge {uat_branch_name} into {target_uat_branch}",
        "head": uat_branch_name,
        "base": target_uat_branch,
        "body": body
    }

    response = requests.post(url, headers=GITHUB_HEADERS, json=payload)

    if response.status_code not in [200, 201]:
        raise Exception(f"GitHub UAT PR creation failed: {response.text}")

    return response.json()

def update_pull_request_body(repo: str, pr_number: int, body: str) -> None:
    """
    Updates the body of an existing pull request.
    """

    url = f"{GITHUB_BASE_URI}/repos/{GITHUB_ORG}/{repo}/pulls/{pr_number}"

    response = requests.patch(url, headers=GITHUB_HEADERS, json={"body": body})

    if response.status_code not in (200, 201):
        raise Exception(f"Failed to update PR #{pr_number} body: {response.text}")

class CherryPickConflictError(Exception):
    """
    Raised when a commit's changes can't be safely applied onto the target branch:
    a real 3-way line merge was attempted (mirroring `git`'s "Auto-merging")
    and the target's edits genuinely overlap the commit's edits at one or more
    paths, so there's no way to combine them without a person deciding. Purely
    disjoint edits (the common case — e.g. an unrelated hotfix elsewhere in the
    same file) are merged automatically and do NOT raise this. Cherry-picking
    stops immediately without writing that commit (or anything after it) — no
    auto-resolution of a genuine conflict.
    """

    def __init__(self, commit_sha: str, commit_message: str, conflicting_paths: List[str]):
        self.commit_sha = commit_sha
        self.commit_message = commit_message
        self.conflicting_paths = conflicting_paths
        first_line = commit_message.splitlines()[0] if commit_message else ""
        paths = ", ".join(conflicting_paths)
        super().__init__(
            f"Merge conflict cherry-picking commit {commit_sha[:7]} ({first_line}): "
            f"target branch has diverged on {paths}. Stopped without applying this "
            f"commit — resolve manually and re-run."
        )


def _get_tree_blob_shas(repo: str, tree_sha: str) -> Dict[str, str]:
    """
    Returns a {path: blob_sha} map for every blob in the given tree (recursive).
    """

    url = f"{GITHUB_BASE_URI}/repos/{GITHUB_ORG}/{repo}/git/trees/{tree_sha}"
    response = requests.get(url, headers=GITHUB_HEADERS, params={"recursive": "1"})

    if response.status_code != 200:
        raise Exception(f"Failed to read tree {tree_sha[:7]}: {response.text}")

    return {
        entry["path"]: entry["sha"]
        for entry in response.json().get("tree", [])
        if entry.get("type") == "blob"
    }


def _diff_targets(f: Dict[str, Any], parent_tree_map: Dict[str, str]) -> List[Tuple[str, Optional[str], Optional[str]]]:
    """
    Returns (path, base_sha_expected, desired_end_sha) for each path a file-diff
    entry touches. base_sha_expected is what the commit's parent had at that path
    (None if the path didn't exist there); desired_end_sha is None for a path that
    should be deleted (`removed`, or the old half of a `renamed`), or the commit's
    post-image blob sha otherwise. Entries with no blob sha (e.g. submodule refs)
    are skipped, same as the original tree-building code did.
    """

    status = f["status"]
    path = f["filename"]

    if status == "removed":
        return [(path, parent_tree_map.get(path), None)]

    if status in ("added", "modified"):
        blob_sha = f.get("sha")
        if not blob_sha:
            return []
        return [(path, parent_tree_map.get(path), blob_sha)]

    if status == "renamed":
        targets = []
        prev = f.get("previous_filename")
        if prev:
            targets.append((prev, parent_tree_map.get(prev), None))
        blob_sha = f.get("sha")
        if blob_sha:
            targets.append((path, parent_tree_map.get(path), blob_sha))
        return targets

    return []


def _get_blob_lines(repo: str, blob_sha: str) -> Optional[List[str]]:
    """
    Fetches a blob's content as a list of lines (line endings kept, so joining
    them back is lossless). Returns None if the blob isn't decodable as UTF-8
    text — i.e. it's binary, which can't be line-merged.
    """

    url = f"{GITHUB_BASE_URI}/repos/{GITHUB_ORG}/{repo}/git/blobs/{blob_sha}"
    response = requests.get(url, headers=GITHUB_HEADERS)

    if response.status_code != 200:
        raise Exception(f"Failed to read blob {blob_sha[:7]}: {response.text}")

    data = response.json()
    if data.get("encoding") != "base64":
        return None

    try:
        raw = base64.b64decode(data["content"])
        text = raw.decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None

    return text.splitlines(keepends=True)


def _create_blob(repo: str, lines: List[str]) -> str:
    """
    Creates a new blob from merged line content and returns its sha.
    """

    response = requests.post(
        f"{GITHUB_BASE_URI}/repos/{GITHUB_ORG}/{repo}/git/blobs",
        headers=GITHUB_HEADERS,
        json={"content": "".join(lines), "encoding": "utf-8"},
    )

    if response.status_code not in (200, 201):
        raise Exception(f"Failed to create merged blob: {response.text}")

    return response.json()["sha"]


def _opcodes_as_edits(base_lines: List[str], other_lines: List[str]) -> List[Tuple[int, int, List[str]]]:
    """
    Returns the non-equal hunks of a base<->other line diff as
    (base_start, base_end, replacement_lines) triples, in base-index order.
    """

    matcher = difflib.SequenceMatcher(None, base_lines, other_lines, autojunk=False)
    edits = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != "equal":
            edits.append((i1, i2, other_lines[j1:j2]))
    return edits


def _edits_overlap(a: Tuple[int, int, List[str]], b: Tuple[int, int, List[str]]) -> bool:
    """
    Whether two base-indexed edits touch overlapping base content — a real
    conflict — as opposed to disjoint regions, which can be combined safely.
    """

    a1, a2, _ = a
    b1, b2, _ = b

    if a1 == a2 and b1 == b2:
        return a1 == b1
    if a1 == a2:
        return b1 < a1 < b2
    if b1 == b2:
        return a1 < b1 < a2
    return max(a1, b1) < min(a2, b2)


def _three_way_merge(
    base_lines: List[str], ours_lines: List[str], theirs_lines: List[str]
) -> Tuple[Optional[List[str]], bool]:
    """
    Line-level 3-way merge (diff3-style) of base->ours (the target branch's
    current content) and base->theirs (the commit being cherry-picked) —
    mirrors `git`'s default "Auto-merging" behavior.

    Hunks touching disjoint regions of base are combined automatically. Hunks
    touching the same base lines with different replacement content are a real
    conflict. Returns (merged_lines, conflict); merged_lines is None on conflict.
    """

    ours_edits = _opcodes_as_edits(base_lines, ours_lines)
    theirs_edits = _opcodes_as_edits(base_lines, theirs_lines)

    for oe in ours_edits:
        for te in theirs_edits:
            if _edits_overlap(oe, te) and oe[2] != te[2]:
                return None, True

    merged_edits = list(ours_edits)
    existing = {(e[0], e[1], tuple(e[2])) for e in ours_edits}
    for te in theirs_edits:
        key = (te[0], te[1], tuple(te[2]))
        if key not in existing:
            merged_edits.append(te)

    merged_edits.sort(key=lambda e: (e[0], e[1]))

    merged_lines: List[str] = []
    pos = 0
    for i1, i2, replacement in merged_edits:
        if i1 < pos:
            # Shouldn't happen given the overlap check above — bail out conservatively.
            return None, True
        merged_lines.extend(base_lines[pos:i1])
        merged_lines.extend(replacement)
        pos = i2
    merged_lines.extend(base_lines[pos:])

    return merged_lines, False


def cherry_pick_commits_onto_branch(
    repo: str,
    commits: List[Dict[str, Any]],
    branch_name: str,
) -> int:
    """
    Cherry-picks a list of commits (output of get_pr_commits) onto branch_name.

    For each non-merge commit:
      1. Compare the commit to its parent to get the exact file changes.
      2. Check that the target branch's current content at each touched path still
         matches what the commit expects (or already matches the desired result) —
         if it has diverged, raise CherryPickConflictError instead of overwriting.
      3. Apply those changes on top of the PROD branch's current tree.
      4. Create a new commit and advance the branch ref.

    Skips merge commits (>1 parent) and commits already cherry-picked onto the
    branch (detected via the "(cherry picked from commit XXXXXXX)" marker).
    Returns the number of commits picked. Raises CherryPickConflictError on the
    first conflicting commit, leaving every commit picked before it in place.
    """

    # Build a set of source SHAs (7-char) already on the branch so we can skip
    # commits that were cherry-picked in a previous run.
    already_picked: set[str] = set()
    existing_commits_resp = requests.get(
        f"{GITHUB_BASE_URI}/repos/{GITHUB_ORG}/{repo}/commits",
        headers=GITHUB_HEADERS,
        params={"sha": branch_name, "per_page": 100},
    )
    if existing_commits_resp.status_code == 200:
        _marker = re.compile(r"\(cherry picked from commit ([0-9a-f]{7})\)")
        for ec in existing_commits_resp.json():
            msg = ec.get("commit", {}).get("message", "")
            for m in _marker.findall(msg):
                already_picked.add(m)

    picked = 0

    for commit in commits:
        commit_sha = commit["sha"]
        parents = commit.get("parents", [])

        # Skip merge commits — they bring in unrelated branch history
        if len(parents) != 1:
            continue

        # Skip commits already cherry-picked onto this branch
        if commit_sha[:7] in already_picked:
            continue

        parent_sha = parents[0]["sha"]
        commit_message = commit["commit"]["message"]

        # 1. Get file-level diff between parent and this commit
        compare_url = (
            f"{GITHUB_BASE_URI}/repos/{GITHUB_ORG}/{repo}"
            f"/compare/{parent_sha}...{commit_sha}"
        )
        compare_resp = requests.get(compare_url, headers=GITHUB_HEADERS)
        if compare_resp.status_code != 200:
            raise Exception(
                f"Failed to compare {parent_sha[:7]}...{commit_sha[:7]}: {compare_resp.text}"
            )
        files = compare_resp.json().get("files", [])

        if not files:
            continue

        # 2. Get current PROD branch HEAD and its tree
        branch_url = f"{GITHUB_BASE_URI}/repos/{GITHUB_ORG}/{repo}/branches/{branch_name}"
        branch_resp = requests.get(branch_url, headers=GITHUB_HEADERS)
        if branch_resp.status_code != 200:
            raise Exception(f"Failed to read branch `{branch_name}`: {branch_resp.text}")
        branch_data = branch_resp.json()
        current_head_sha = branch_data["commit"]["sha"]
        current_tree_sha = branch_data["commit"]["commit"]["tree"]["sha"]

        # 2b. Resolve each touched path. If the target branch hasn't diverged
        # from what this commit expects, reuse the commit's content as-is. If it
        # has diverged, attempt a real 3-way line merge (mirrors `git`'s
        # "Auto-merging") — only a genuine overlapping edit becomes a conflict.
        parent_commit_resp = requests.get(
            f"{GITHUB_BASE_URI}/repos/{GITHUB_ORG}/{repo}/commits/{parent_sha}",
            headers=GITHUB_HEADERS,
        )
        if parent_commit_resp.status_code != 200:
            raise Exception(
                f"Failed to read parent commit {parent_sha[:7]}: {parent_commit_resp.text}"
            )
        parent_tree_sha = parent_commit_resp.json()["commit"]["tree"]["sha"]

        parent_tree_map = _get_tree_blob_shas(repo, parent_tree_sha)
        current_tree_map = _get_tree_blob_shas(repo, current_tree_sha)

        resolved_paths: Dict[str, Optional[str]] = {}
        conflicting_paths = []

        for f in files:
            for path, base_sha, desired_sha in _diff_targets(f, parent_tree_map):
                current_sha = current_tree_map.get(path)

                if current_sha == base_sha or current_sha == desired_sha:
                    # Clean fast-forward, or this path already matches the desired result.
                    resolved_paths[path] = desired_sha
                    continue

                # Target has diverged from what this commit expects — try a real merge.
                base_lines = _get_blob_lines(repo, base_sha) if base_sha else []
                ours_lines = _get_blob_lines(repo, current_sha) if current_sha else []
                theirs_lines = _get_blob_lines(repo, desired_sha) if desired_sha else []

                if base_lines is None or ours_lines is None or theirs_lines is None or desired_sha is None:
                    # Binary/non-UTF-8 content, or this touches a deletion — can't
                    # safely auto-merge, so any divergence here is a real conflict.
                    conflicting_paths.append(path)
                    continue

                merged_lines, has_conflict = _three_way_merge(base_lines, ours_lines, theirs_lines)

                if has_conflict:
                    conflicting_paths.append(path)
                    continue

                resolved_paths[path] = _create_blob(repo, merged_lines)

        if conflicting_paths:
            raise CherryPickConflictError(commit_sha, commit_message, sorted(set(conflicting_paths)))

        if not resolved_paths:
            continue

        # 3. Build tree entries from the resolved per-path content
        tree_entries = [
            {"path": path, "mode": "100644", "type": "blob", "sha": sha}
            for path, sha in resolved_paths.items()
        ]

        # 4. Create a new tree rooted at the PROD branch's current tree + changes
        tree_resp = requests.post(
            f"{GITHUB_BASE_URI}/repos/{GITHUB_ORG}/{repo}/git/trees",
            headers=GITHUB_HEADERS,
            json={"base_tree": current_tree_sha, "tree": tree_entries},
        )
        if tree_resp.status_code not in (200, 201):
            raise Exception(
                f"Failed to create tree for commit {commit_sha[:7]}: {tree_resp.text}"
            )
        new_tree_sha = tree_resp.json()["sha"]

        # 5. Create a new commit on top of the PROD branch
        new_commit_resp = requests.post(
            f"{GITHUB_BASE_URI}/repos/{GITHUB_ORG}/{repo}/git/commits",
            headers=GITHUB_HEADERS,
            json={
                "message": f"{commit_message}\n\n(cherry picked from commit {commit_sha[:7]})",
                "tree": new_tree_sha,
                "parents": [current_head_sha],
            },
        )
        if new_commit_resp.status_code not in (200, 201):
            raise Exception(f"Failed to create commit: {new_commit_resp.text}")
        new_commit_sha = new_commit_resp.json()["sha"]

        # 6. Advance the PROD branch ref to the new commit
        ref_resp = requests.patch(
            f"{GITHUB_BASE_URI}/repos/{GITHUB_ORG}/{repo}/git/refs/heads/{branch_name}",
            headers=GITHUB_HEADERS,
            json={"sha": new_commit_sha},
        )
        if ref_resp.status_code not in (200, 201):
            raise Exception(
                f"Failed to update branch ref after commit {commit_sha[:7]}: {ref_resp.text}"
            )

        picked += 1

    return picked

def add_jira_prod_pr_link(ticket: str, pr_url: str, repo: str) -> None:
    """
    Adds a PROD PR web link to a Jira ticket.
    """

    url = f"{JIRA_BASE_URL}/rest/api/3/issue/{ticket}/remotelink"

    payload = {
        "object": {
            "url": pr_url,
            "title": f"{repo} (PROD)"
        }
    }

    response = requests.post(url, headers=JIRA_HEADERS, json=payload)

    if response.status_code not in [200, 201]:
        raise Exception(f"Failed to add Jira PROD link: {response.text}")

def add_jira_uat_pr_link(ticket: str, pr_url: str, repo: str) -> None:
    """
    Adds a UAT PR web link to a Jira ticket.
    """

    url = f"{JIRA_BASE_URL}/rest/api/3/issue/{ticket}/remotelink"

    payload = {
        "object": {
            "url": pr_url,
            "title": f"{repo} (UAT)"
        }
    }

    response = requests.post(url, headers=JIRA_HEADERS, json=payload)

    if response.status_code not in [200, 201]:
        raise Exception(f"Failed to add Jira UAT link: {response.text}")

def compare_env_prs(jira_ticket: str, repo_name: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    For a Jira ticket, compares the changed-file content of the DEV/UAT/PROD PRs
    linked on the ticket, per repo, so drift between environments can be caught
    before merging.

    Returns a list of per-repo reports:
      {
        "repo": str,
        "envs": {"DEV": url, "UAT": url, "PROD": url}  # only envs with a PR link
        "verdict": "MATCH" | "MISMATCH" | "INCOMPLETE",
        "files": [{"path": str, "status": "OK" | "MISSING" | "DIFFERS", "missing_in": [env, ...]}],
      }
    "INCOMPLETE" means fewer than two environments have a PR yet, so there's
    nothing to compare.
    """

    dev_links = filter_dev_pr_links(get_dev_pr_links(jira_ticket), repo_name)
    uat_links = filter_dev_pr_links(get_uat_pr_links(jira_ticket), repo_name)
    prod_links = filter_dev_pr_links(get_prod_pr_links(jira_ticket), repo_name)

    repos: Dict[str, Dict[str, str]] = {}
    for env, links in (("DEV", dev_links), ("UAT", uat_links), ("PROD", prod_links)):
        for link in links:
            repos.setdefault(link["repo"], {})[env] = link["url"]

    report = []

    for repo, envs in sorted(repos.items()):
        env_files: Dict[str, Dict[str, Optional[str]]] = {}
        for env, pr_url in envs.items():
            pr_number = get_pr_number_from_url(pr_url)
            files = get_pr_files(repo, pr_number)
            env_files[env] = {f["filename"]: f.get("sha") for f in files}

        present_envs = sorted(env_files.keys())
        all_paths = sorted({path for files in env_files.values() for path in files})

        file_rows = []
        mismatch = False

        for path in all_paths:
            shas = {env: env_files[env].get(path) for env in present_envs}
            distinct_shas = {sha for sha in shas.values() if sha is not None}
            missing_in = [env for env in present_envs if shas[env] is None]

            if len(distinct_shas) > 1:
                status = "DIFFERS"
                mismatch = True
            elif missing_in:
                status = "MISSING"
                mismatch = True
            else:
                status = "OK"

            file_rows.append({"path": path, "status": status, "missing_in": missing_in})

        if len(present_envs) < 2:
            verdict = "INCOMPLETE"
        elif mismatch:
            verdict = "MISMATCH"
        else:
            verdict = "MATCH"

        report.append({
            "repo": repo,
            "envs": envs,
            "verdict": verdict,
            "files": file_rows,
        })

    return report
