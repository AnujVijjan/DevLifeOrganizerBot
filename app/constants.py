import os
import base64
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'instance', 'bot_data.db')
REPO_CONFIG_FILE = os.getenv("REPO_CONFIG_FILE", os.path.join(BASE_DIR, "repo_config.json"))

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_USERNAME = os.getenv("GITHUB_USERNAME")
GITHUB_ORG = os.getenv("GITHUB_ORG")
GITHUB_BRANCH_NAMES = os.getenv("GITHUB_BRANCH_NAMES")
REPO_SEARCH_KEYWORDS = os.getenv("REPO_SEARCH_KEYWORDS")
GITHUB_BASE_URI = "https://api.github.com"

GITHUB_HEADERS = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json"
}

JIRA_BASE_URL = os.getenv("JIRA_BASE_URL")
JIRA_EMAIL = os.getenv("JIRA_EMAIL")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")
JIRA_PROJECT_KEY = os.getenv("JIRA_PROJECT_KEY")
JIRA_STATUS_CODE_REVIEW = os.getenv("JIRA_STATUS_CODE_REVIEW", "CodeReview")
JIRA_QA_TESTER_FIELD = os.getenv("JIRA_QA_TESTER_FIELD")
DEFAULT_ASSIGNEE = "qa"
JIRA_HEADERS = {
    "Authorization": f"Basic {base64.b64encode(f'{JIRA_EMAIL}:{JIRA_API_TOKEN}'.encode()).decode()}",
    "Content-Type": "application/json"
}

SLACK_BOT_TOKEN: str = os.getenv("SLACK_BOT_TOKEN")
SLACK_CHANNEL: str = os.getenv("SLACK_CHANNEL")
SLACK_USER_TOKEN: str = os.getenv("SLACK_USER_TOKEN")
SLACK_USER_ID: str = os.getenv("SLACK_USER_ID")

DEV_BRANCH_CANDIDATES = ["develop", "dev", "main", "master"]
UAT_BRANCH_CANDIDATES = ["uat", "staging", "stage", "qa"]
PROD_BRANCH_CANDIDATES = ["prod", "production", "master"]

BRANCH_KIND_LABELS = {
    "dev_branch": "dev",
    "uat_branch": "UAT",
    "prod_branch": "prod",
}

SP_DEPLOY_DEFAULT_REPO = os.getenv("SP_DEPLOY_DEFAULT_REPO")
SP_SOURCE_DATABASE = os.getenv("SP_SOURCE_DATABASE")

DEPLOY_ENVIRONMENTS = {
    "dev": {
        "label": "DEV",
        "pr_env": "DEV",
        "fallback_pr_env": None,
        "source_database": SP_SOURCE_DATABASE,
        "target_database": os.getenv("DEV_DATABASE_NAME"),
        "connection_string": os.getenv("DEV_DATABASE_CONNECTION_STRING"),
        "requires_typed_confirmation": False,
    },
    "uat": {
        "label": "UAT",
        "pr_env": "UAT",
        "fallback_pr_env": "DEV",
        "source_database": SP_SOURCE_DATABASE,
        "target_database": os.getenv("UAT_DATABASE_NAME"),
        "connection_string": os.getenv("UAT_DATABASE_CONNECTION_STRING"),
        "requires_typed_confirmation": False,
    },
    "prod": {
        "label": "PROD",
        "pr_env": "PROD",
        "fallback_pr_env": None,
        "source_database": SP_SOURCE_DATABASE,
        "target_database": os.getenv("PROD_DATABASE_NAME"),
        "connection_string": os.getenv("PROD_DATABASE_CONNECTION_STRING"),
        "requires_typed_confirmation": True,
    },
}
