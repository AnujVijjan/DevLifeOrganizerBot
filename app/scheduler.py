from apscheduler.schedulers.background import BackgroundScheduler
from .slack_bot import send_daily_summary, send_code_review_reminder, send_health_reminder

def start_scheduler() -> None:
    """
    Initializes and starts the background scheduler for automated Slack notifications.

    - Sends a daily task summary at 10 AM.
    - Sends code review reminders at 10 AM.
    
    :return: None
    """
    scheduler = BackgroundScheduler()

    # Send daily task summary at 10 AM
    scheduler.add_job(send_daily_summary, "cron", hour=10, minute=0)

    # Send PR review reminders at 10 AM
    scheduler.add_job(send_code_review_reminder, "cron", hour=10, minute=0)

    # Send health reminders every 30 minutes
    scheduler.add_job(send_health_reminder, "interval", minutes=30)

    scheduler.start()