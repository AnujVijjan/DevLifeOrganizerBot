from apscheduler.schedulers.background import BackgroundScheduler
from .slack_bot import send_daily_summary

def start_scheduler():
    scheduler = BackgroundScheduler()
    scheduler.add_job(send_daily_summary, "cron", hour=9, minute=0)
    scheduler.start()
