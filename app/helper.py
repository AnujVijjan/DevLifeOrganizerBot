import re
import requests
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

def get_jira_remote_links(ticket: str) -> List[Dict[str, Any]]:
    """
    Returns all remote links attached to a Jira ticket.
    """

    url = f"{JIRA_BASE_URL}/rest/api/3/issue/{ticket}/remotelink"

    response = requests.get(url, headers=JIRA_HEADERS)

    if response.status_code != 200:
        raise Exception(f"Failed to fetch remote links for {ticket}: {response.text}")

    return response.json()

def get_dev_pr_links(ticket: str) -> List[Dict[str, Any]]:
    """
    Returns DEV PR links from a Jira ticket's remote links.
    Each item has: url, title, repo.
    """

    links = get_jira_remote_links(ticket)

    dev_links = []

    for link in links:
        obj = link.get("object", {})
        title = obj.get("title", "")
        url = obj.get("url", "")

        if title.endswith("(DEV)") and url:
            repo = title[: -len("(DEV)")].strip()
            dev_links.append({"url": url, "title": title, "repo": repo})

    return dev_links

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

def get_pr_number_from_url(pr_url: str) -> int:
    """
    Extracts PR number from a GitHub PR URL.
    e.g. https://github.com/{org}/{repo}/pull/42 -> 42
    """

    parts = pr_url.rstrip("/").split("/")
    return int(parts[-1])

def get_pr_commits(repo: str, pr_number: int) -> List[Dict[str, Any]]:
    """
    Returns commit list for a given PR (sha + first line of message).
    """

    url = f"{GITHUB_BASE_URI}/repos/{GITHUB_ORG}/{repo}/pulls/{pr_number}/commits"

    response = requests.get(url, headers=GITHUB_HEADERS)

    if response.status_code != 200:
        return []

    return response.json()

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

def detect_prod_branch(branches: List[str]) -> str:
    """
    Detects the production branch using priority: prod > production > master > main.
    """

    branch_set = set(branches)

    for branch in ["prod", "production", "master"]:
        if branch in branch_set:
            return branch

    raise Exception(f"Unable to determine prod branch from branches: {branches}")

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

def update_pull_request_body(repo: str, pr_number: int, body: str) -> None:
    """
    Updates the body of an existing pull request.
    """

    url = f"{GITHUB_BASE_URI}/repos/{GITHUB_ORG}/{repo}/pulls/{pr_number}"

    response = requests.patch(url, headers=GITHUB_HEADERS, json={"body": body})

    if response.status_code not in (200, 201):
        raise Exception(f"Failed to update PR #{pr_number} body: {response.text}")

def cherry_pick_commits_onto_branch(
    repo: str,
    commits: List[Dict[str, Any]],
    branch_name: str,
) -> int:
    """
    Cherry-picks a list of commits (output of get_pr_commits) onto branch_name.

    For each non-merge commit:
      1. Compare the commit to its parent to get the exact file changes.
      2. Apply those changes on top of the PROD branch's current tree.
      3. Create a new commit and advance the branch ref.

    Skips merge commits (>1 parent) and commits already cherry-picked onto the
    branch (detected via the "(cherry picked from commit XXXXXXX)" marker).
    Returns the number of commits picked.
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

        # 3. Build tree entries — apply the diff to the PROD branch tree
        tree_entries = []
        for f in files:
            path = f["filename"]
            status = f["status"]

            if status == "removed":
                # sha=None deletes the file from the tree
                tree_entries.append({"path": path, "mode": "100644", "type": "blob", "sha": None})

            elif status in ("added", "modified"):
                blob_sha = f.get("sha")
                if blob_sha:
                    tree_entries.append({"path": path, "mode": "100644", "type": "blob", "sha": blob_sha})

            elif status == "renamed":
                prev = f.get("previous_filename")
                blob_sha = f.get("sha")
                if prev:
                    tree_entries.append({"path": prev, "mode": "100644", "type": "blob", "sha": None})
                if blob_sha:
                    tree_entries.append({"path": path, "mode": "100644", "type": "blob", "sha": blob_sha})

        if not tree_entries:
            continue

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
