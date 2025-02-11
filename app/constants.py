import os
import base64
from dotenv import load_dotenv

# Ensure environment variables are loaded
load_dotenv()

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'instance', 'bot_data.db')

# GitHub Constants
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

# Jira Constants
JIRA_BASE_URL = os.getenv("JIRA_BASE_URL")
JIRA_EMAIL = os.getenv("JIRA_EMAIL")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")
JIRA_PROJECT_KEY = os.getenv("JIRA_PROJECT_KEY")

JIRA_HEADERS = {
    "Authorization": f"Basic {base64.b64encode(f'{JIRA_EMAIL}:{JIRA_API_TOKEN}'.encode()).decode()}",
    "Content-Type": "application/json"
}

SLACK_BOT_TOKEN: str = os.getenv("SLACK_BOT_TOKEN")
SLACK_CHANNEL: str = os.getenv("SLACK_CHANNEL")
SLACK_USER_TOKEN: str = os.getenv("SLACK_USER_TOKEN")
SLACK_USER_ID: str = os.getenv("SLACK_USER_ID")
