# Dev Life Organizer Bot

A Slack bot that automates the repetitive parts of a developer's day — task tracking, PR creation, Jira workflow transitions, standup reports, Deep Work mode, and more.

---

## Features

### Task Management
- `/addtask <description>` — Add a task to your to-do list
- `/listtasks` — View all pending tasks
- `/marktaskdone <task_id>` — Mark a task as complete

### PR Automation
- `/createpr <TICKET-ID> [feature-branch] <repo>` — Creates a PR from your feature branch into the detected dev branch, defaulting the feature branch to the ticket ID when omitted, adds the PR link to the Jira ticket, and transitions the ticket to CodeReview
- `/createprodpr <TICKET-ID> [feature-branch]` — Reads all DEV PR links from the Jira ticket, cherry-picks their commits onto a clean PROD branch named from the feature branch or ticket ID, opens a PROD PR per repo, and links it back to the ticket

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
1. Detects the dev branch of the repo (`develop` → `dev` → `main` → `master`)
2. Uses the provided feature branch, or defaults to the ticket ID if none is provided
3. Creates a PR from your feature branch into the dev branch (or reuses an existing open one)
4. Adds the PR link to the Jira ticket as a web link
5. If the ticket is "In Progress", transitions it to CodeReview and assigns it to the QA tester

### PROD PR (`/createprodpr`)
1. Reads all `(DEV)` web links attached to the Jira ticket
2. For each repo found, detects the prod branch (`prod` → `production` → `master`)
3. Creates a `{feature-branch-or-ticket-ID}-Prod` branch from the prod branch's HEAD
4. Cherry-picks the DEV PR commits onto the PROD branch via the GitHub Git Data API — no dev-only history brought along
5. Opens a PROD PR with the cherry-picked commit list in the body
6. Adds the PROD PR link to the Jira ticket
7. Re-running on a ticket that already has a PROD PR will cherry-pick any new commits and refresh the PR body

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

python cli.py createpr CAH-123 MyRepo
python cli.py createpr CAH-123 my-feature-branch MyRepo
python cli.py createprodpr CAH-123
python cli.py createprodpr CAH-123 my-feature-branch
```

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
| `JIRA_STATUS_IN_PROGRESS` | No | Status that triggers CodeReview transition (default: `In Progress`) |
| `JIRA_STATUS_CODE_REVIEW` | No | Transition name after PR creation (default: `CodeReview`) |
| `JIRA_QA_TESTER_FIELD` | No | Custom field ID for QA tester (default: `customfield_10111`) |

To find your `JIRA_QA_TESTER_FIELD` ID, visit:
```
https://yourcompany.atlassian.net/rest/api/3/field
```

---

## Contributing

Contributions are welcome. Please open an issue first to discuss what you'd like to change, then submit a pull request.
