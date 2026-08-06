from typing import Awaitable, Callable
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import asyncio


def start_scheduler(job: Callable[[], Awaitable[None]]) -> BackgroundScheduler:
    scheduler = BackgroundScheduler()
    scheduler.add_job(lambda: asyncio.run(job()), CronTrigger(day_of_week="mon", hour=9))
    scheduler.start()
    return scheduler
