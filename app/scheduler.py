from apscheduler.schedulers.background import BackgroundScheduler
from .slack_bot import send_daily_summary, send_code_review_reminder

def start_scheduler():
    scheduler = BackgroundScheduler()
    
    # Send daily task summary at 9 AM
    scheduler.add_job(send_daily_summary, "cron", hour=10, minute=0)

    # Send PR review reminders at 10 AM
    scheduler.add_job(send_code_review_reminder, "cron", hour=10, minute=0)

    scheduler.start()
