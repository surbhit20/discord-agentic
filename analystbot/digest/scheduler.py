from typing import Awaitable, Callable
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger


def start_scheduler(job: Callable[[], Awaitable[None]]) -> AsyncIOScheduler:
    """Schedule `job` to run every Monday at 09:00 on the caller's own running event loop.

    Uses AsyncIOScheduler (not BackgroundScheduler) so the job runs as a coroutine on
    the same thread/loop that called this function, rather than in an APScheduler
    worker thread. This matters because `job` typically touches a sqlite3.Connection
    (thread-affine by default) and a discord.py client whose internal aiohttp session
    is bound to its own event loop — both would break under a cross-thread executor.
    Callers must invoke this from within the event loop they want the job to run on
    (e.g. from an `on_ready` handler after `bot.run()` has started the loop), not
    before that loop exists.
    """
    scheduler = AsyncIOScheduler()
    scheduler.add_job(job, CronTrigger(day_of_week="mon", hour=9))
    scheduler.start()
    return scheduler
