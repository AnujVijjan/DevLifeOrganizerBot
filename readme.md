# Dev Life Organizer Bot

A Slack bot that automates the repetitive parts of a developer's day — task tracking, PR creation, Jira workflow transitions, standup reports, Deep Work mode, and more.

---

## Features

### Task Management
- `/addtask <description>` — Add a task to your to-do list
- `/listtasks` — View all pending tasks
- `/marktaskdone <task_id>` — Mark a task as complete

### PR Automation
- `/createpr <TICKET-ID> --repo <repo> [--branch feature-branch] [--transition [status]] [--assign [user]]` — Creates a PR from your feature branch into the detected dev branch, defaulting the feature branch to the ticket ID when omitted, and adds the PR link to the Jira ticket. The ticket is left as is unless you opt in: `--transition` moves it to a status (bare flag: the configured CodeReview status) and `--assign` assigns it (bare flag: the ticket's QA tester; or `me`, or a name/email). Quote values with spaces, e.g. `--transition "In QA"`
- `/createprodpr <TICKET-ID> [--branch feature-branch] [--repo repo-name]` — Reads DEV PR links from the Jira ticket, optionally narrows the run to one repo, cherry-picks the commits onto a clean PROD branch named from the feature branch or ticket ID, opens a PROD PR, and links it back to the ticket
- `/createuatpr <TICKET-ID> [--branch feature-branch] [--repo repo-name]` — Same as `/createprodpr` but targets the repo's UAT branch instead

### Stored Procedure Deployment
- `deploysp <TICKET-ID-or-Jira-link> [--env dev|uat|prod] [--repo repo-name] [--yes]` — CLI-only. Reads the PR linked on a Jira ticket for the chosen environment, finds every changed `.sql` file, rewrites `USE [<source database>]` to the environment's database, and runs each script there. `--env` defaults to `uat`, and `deploysptouat` remains as an alias for `--env uat`

### Standup Report
- `/standup` — Generates a standup draft from your GitHub commits and Jira updates from the past 24 hours

### Deep Work Mode
- `/deepworkon <minutes>` — Mutes notifications and sets an auto-reply for anyone who messages you (default: 60 minutes)
- `/deepworkoff` — Disables Deep Work Mode immediately

### Scheduled Reminders
- **10:00 AM** — Daily task summary + code review reminders
- **Every 30 minutes** — Health and break reminder
- **8:00 PM** — End-of-day standup report

---

## How PR Automation Works

### DEV PR (`/createpr`)
1. Detects the dev branch of the repo (`develop` → `dev` → `main` → `master`), unless the repo has a `dev_branch` override in `repo_config.json`
2. Uses the provided feature branch, or defaults to the ticket ID if none is provided
3. Creates a PR from your feature branch into the dev branch (or reuses an existing open one)
4. Adds the PR link to the Jira ticket as a web link
5. Only if you pass `--transition [status]`, moves the ticket to that status (or the configured CodeReview status when no value is given); if no such transition is available from the ticket's current status it is reported and the ticket stays put
6. Only if you pass `--assign [user]`, assigns the ticket to `qa` (the ticket's QA tester, the default), `me`, or the Jira user matching a name or email. The assignee is resolved before anything changes, so a bad name fails without touching the ticket

### PROD PR (`/createprodpr`)
1. Reads all `(DEV)` web links attached to the Jira ticket
2. For each repo found, detects the prod branch (`prod` → `production` → `master`, or the repo's `prod_branch` override)
3. Creates a `{feature-branch-or-ticket-ID}-Prod` branch from the prod branch's HEAD
4. Cherry-picks the DEV PR commits onto the PROD branch via the GitHub Git Data API — no dev-only history brought along
5. Opens a PROD PR with the cherry-picked commit list in the body
6. Adds the PROD PR link to the Jira ticket
7. Re-running on a ticket that already has a PROD PR will cherry-pick any new commits and refresh the PR body

### UAT PR (`/createuatpr`)
Works identically to `/createprodpr`, but targets the UAT branch instead of prod:
1. Reads all `(DEV)` web links attached to the Jira ticket
2. For each repo found, detects the UAT branch (`uat` → `staging` → `stage` → `qa`, or the repo's `uat_branch` override)
3. Creates a `{feature-branch-or-ticket-ID}-Uat` branch from the UAT branch's HEAD
4. Cherry-picks the DEV PR commits onto the UAT branch via the GitHub Git Data API — no dev-only history brought along
5. Opens a UAT PR with the cherry-picked commit list in the body
6. Adds the UAT PR link to the Jira ticket
7. Re-running on a ticket that already has a UAT PR will cherry-pick any new commits and refresh the PR body

### Stored Procedure Deployment (`deploysp`)
1. Accepts a bare Jira ticket key, a full Jira link, or (for `--env dev` and `uat`) a GitHub PR link
2. Reads the PR link tagged for the environment on the ticket: `dev` reads `(DEV)`; `uat` reads `(UAT)` and falls back to `(DEV)`; `prod` reads `(PROD)` only, with no fallback
3. Fetches the PR's changed-file list and keeps the `.sql` files that weren't removed
4. Rewrites every `USE [<SP_SOURCE_DATABASE>]` in each script to `USE [<env database name>]`
5. Asks for confirmation (`dev` and `uat`: `y/N`, skippable with `--yes`; `prod`: you must type the ticket key, `--yes` is ignored), then runs each rewritten script against the environment's connection string, one transaction per script

### Per-Repo Branch Overrides
Some repos don't follow the default branch names. Copy `repo_config.sample.json` to `repo_config.json` (gitignored) and list only the repos that differ:

```json
{
    "repos": {
        "my-repo": { "dev_branch": "integration", "uat_branch": "staging", "prod_branch": "main" }
    }
}
```

Repo names are matched case-insensitively and each key is optional. An override naming a branch that doesn't exist in the repo is reported as an error. `createpr` also refuses to run when the feature branch is the dev branch itself; pass `--branch` in that case.

---

## CLI

All Slack commands are also available as a CLI for local use:

```bash
python cli.py addtask "Fix the login bug"
python cli.py listtasks
python cli.py marktaskdone 3

python cli.py deepworkon 90
python cli.py deepworkoff

python cli.py standup

python cli.py createpr PROJ-123 --repo MyRepo
python cli.py createpr PROJ-123 --repo MyRepo --branch my-feature-branch
python cli.py createpr PROJ-123 --repo MyRepo --transition --assign
python cli.py createpr PROJ-123 --repo MyRepo --transition "In QA" --assign someone@example.com
python cli.py createprodpr PROJ-123
python cli.py createprodpr PROJ-123 --branch my-feature-branch
python cli.py createprodpr PROJ-123 --repo MyRepo
python cli.py createprodpr PROJ-123 --branch my-feature-branch --repo MyRepo
python cli.py createuatpr PROJ-123
python cli.py createuatpr PROJ-123 --branch my-feature-branch
python cli.py createuatpr PROJ-123 --repo MyRepo
python cli.py createuatpr PROJ-123 --branch my-feature-branch --repo MyRepo

python cli.py deploysp PROJ-123 --env dev
python cli.py deploysp PROJ-123 --env uat
python cli.py deploysp https://company.atlassian.net/browse/PROJ-123 --env uat --repo my-repo
python cli.py deploysp PROJ-123 --env uat --repo my-repo --yes
python cli.py deploysp PROJ-123 --env prod --repo my-repo
```

### Interactive mode

Don't want to remember flags? Run the CLI with no arguments (or `python cli.py interactive`) and pick an action from a menu:

```bash
python cli.py
```

It asks only what it needs, e.g. for a UAT PR it takes the ticket, then offers the repos that already have a DEV PR on that ticket. Before anything changes it prints the equivalent flag-based command and asks `Run it?`. Menu actions: create DEV / UAT / PROD PRs, compare PRs across environments, deploy stored procedures to DEV, UAT or PROD, standup, tasks, and Deep Work Mode. The flag-based commands above keep working unchanged.

Legacy positional syntax is still accepted for `createpr`, `createprodpr`, and `createuatpr` so existing habits keep working.

---

## Setup

### Prerequisites
- Python 3.8+
- A Slack workspace with a Slack app created ([Slack API](https://api.slack.com/apps))
- A GitHub organisation with a personal access token (`repo` + `read:org` scopes)
- A Jira cloud instance with an API token ([Atlassian API tokens](https://id.atlassian.com/manage-profile/security/api-tokens))

### 1. Clone the repository

```bash
git clone https://github.com/your-username/DevLifeOrganizerBot.git
cd DevLifeOrganizerBot
```

### 2. Create a virtual environment and install dependencies

```bash
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Configure environment variables

```bash
cp sample.env .env
```

Edit `.env` with your credentials. See [Environment Variables](#environment-variables) below for a full reference.

### 4. Configure the Slack app

- Import `manifest.json` into the [Slack Developer Portal](https://api.slack.com/apps) using **Create New App → From a manifest**
- Replace `https://yourdomain.com` in `manifest.json` with your actual public URL (or an ngrok tunnel for local dev)
- Install the app to your workspace and copy the bot/user tokens into `.env`

### 5. Run the bot

```bash
python run.py
```

For local development, expose the server with [ngrok](https://ngrok.com/):

```bash
ngrok http 5000
```

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `SLACK_BOT_TOKEN` | Yes | Bot token (`xoxb-...`) for posting to channels |
| `SLACK_USER_TOKEN` | Yes | User token (`xoxp-...`) for Deep Work DMs |
| `SLACK_CHANNEL` | Yes | Channel where the bot posts (e.g. `#dev-life`) |
| `SLACK_USER_ID` | Yes | Your Slack user ID (e.g. `U012AB3CD`) |
| `GITHUB_TOKEN` | Yes | Personal access token with `repo` + `read:org` scopes |
| `GITHUB_USERNAME` | Yes | Your GitHub username |
| `GITHUB_ORG` | Yes | GitHub organisation name |
| `GITHUB_BRANCH_NAMES` | Yes | Comma-separated branches to monitor (e.g. `master,develop`) |
| `REPO_SEARCH_KEYWORDS` | Yes | Comma-separated keywords to filter repos by name |
| `JIRA_BASE_URL` | Yes | Your Jira instance URL (e.g. `https://company.atlassian.net`) |
| `JIRA_EMAIL` | Yes | Email linked to your Jira account |
| `JIRA_API_TOKEN` | Yes | Jira API token |
| `JIRA_PROJECT_KEY` | Yes | Project key for standup JQL queries (e.g. `PROJ`) |
| `JIRA_STATUS_CODE_REVIEW` | No | Status used when `--transition` is given without a value (default: `CodeReview`) |
| `JIRA_QA_TESTER_FIELD` | No | Custom field ID for QA tester; needed for `--assign` / `--assign qa` |
| `SP_SOURCE_DATABASE` | For `deploysp` | Database name used in your scripts' `USE [...]` statements |
| `DEV_DATABASE_NAME` | For `deploysp --env dev` | Database name the scripts are rewritten to for DEV |
| `DEV_DATABASE_CONNECTION_STRING` | For `deploysp --env dev` | ODBC connection string for the DEV database |
| `UAT_DATABASE_NAME` | For `deploysp --env uat` | Database name the scripts are rewritten to for UAT |
| `UAT_DATABASE_CONNECTION_STRING` | For `deploysp --env uat` | ODBC connection string for the UAT database |
| `PROD_DATABASE_NAME` | For `deploysp --env prod` | Database name the scripts are rewritten to for PROD |
| `PROD_DATABASE_CONNECTION_STRING` | For `deploysp --env prod` | ODBC connection string for the PROD database |
| `SP_DEPLOY_DEFAULT_REPO` | No | Default repo `deploysp` reads PR links from |
| `REPO_CONFIG_FILE` | No | Path to the per-repo branch override file (default: `repo_config.json`) |

To find your `JIRA_QA_TESTER_FIELD` ID, visit:
```
https://yourcompany.atlassian.net/rest/api/3/field
```

---

## Contributing

Contributions are welcome. Please open an issue first to discuss what you'd like to change, then submit a pull request.
