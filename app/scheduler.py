from apscheduler.schedulers.background import BackgroundScheduler
from .slack_bot import (
    send_daily_summary, 
    send_code_review_reminder, 
    send_health_reminder, 
    async_generate_standup,
    DB_FILE, SLACK_CHANNEL, SLACK_BOT_TOKEN
)
from datetime import datetime
import sqlite3
from slack_sdk import WebClient

client = WebClient(token=SLACK_BOT_TOKEN)

def auto_disable_deep_work_mode() -> None:
    """
    Automatically disables Deep Work Mode if the time has expired.

    :return: None
    """
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT end_time FROM deep_work WHERE active = 1")
    row = cursor.fetchone()

    if row:
        end_time = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S.%f")
        if datetime.utcnow() >= end_time:
            cursor.execute("DELETE FROM deep_work")
            client.chat_postMessage(channel=SLACK_CHANNEL, text="✅ Deep Work Mode has ended. You're back online!")
            conn.commit()

    conn.close()


def start_scheduler() -> None:
    """
    Initializes and starts the background scheduler for automated Slack notifications.

    - Sends a daily task summary at 10 AM.
    - Sends code review reminders at 10 AM.
    - Sends health reminders every 30 minutes.
    - Checks and auto-disables Deep Work Mode every 30 seconds.
    - Sends a daily standup report to Slack at 8 PM.

    :return: None
    """
    scheduler = BackgroundScheduler()

    scheduler.add_job(send_daily_summary, "cron", hour=10, minute=0)
    scheduler.add_job(send_code_review_reminder, "cron", hour=10, minute=0)
    scheduler.add_job(send_health_reminder, "interval", minutes=30)
    scheduler.add_job(auto_disable_deep_work_mode, "interval", seconds=30)
    scheduler.add_job(async_generate_standup, "cron", hour=20, minute=0)

    scheduler.start()
