from unittest.mock import patch

from apscheduler.triggers.cron import CronTrigger

from analystbot.digest.scheduler import start_scheduler


def test_start_scheduler_uses_asyncio_scheduler_and_adds_job_directly():
    async def job() -> None:
        pass

    with patch("analystbot.digest.scheduler.AsyncIOScheduler") as MockScheduler:
        instance = MockScheduler.return_value
        result = start_scheduler(job)

    # The job coroutine function must be handed to APScheduler as-is: no
    # `lambda: asyncio.run(job())` wrapper, which would run it on a fresh event
    # loop/thread disconnected from the caller's own running loop.
    instance.add_job.assert_called_once()
    args, _ = instance.add_job.call_args
    assert args[0] is job
    assert isinstance(args[1], CronTrigger)

    instance.start.assert_called_once()
    assert result is instance


def test_start_scheduler_trigger_fires_monday_at_9am():
    async def job() -> None:
        pass

    with patch("analystbot.digest.scheduler.AsyncIOScheduler") as MockScheduler:
        instance = MockScheduler.return_value
        start_scheduler(job)

    _, trigger = instance.add_job.call_args[0]
    trigger_str = str(trigger)
    assert "mon" in trigger_str
    assert "hour='9'" in trigger_str
