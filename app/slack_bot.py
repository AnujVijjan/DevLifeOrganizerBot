from slack_sdk import WebClient
import os
from dotenv import load_dotenv
from .models import get_tasks_from_db

# Load environment variables
load_dotenv()

SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_CHANNEL = os.getenv("SLACK_CHANNEL")

client = WebClient(token=SLACK_BOT_TOKEN)

def send_message_to_slack(message):
    client.chat_postMessage(channel=SLACK_CHANNEL, text=message)

def send_daily_summary():
    tasks = get_tasks_from_db()
    if not tasks:
        message = "No tasks for today! 🚀"
    else:
        message = "📝 *Your Tasks for Today:*\n" + "\n".join(f"• {task[0]}" for task in tasks)

    send_message_to_slack(message)
