import sqlite3
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

import analystbot.bot.pipeline as pipeline
import analystbot.main as main
from analystbot.config import Config
from analystbot.query.generate import QuestionOutcome, QuestionResult
from analystbot.query.confidence import ConfidenceResult
from analystbot.storage import config_store, db, digest_history, schema_cache, threads as thread_store


def test_confirm_is_honored_once_schema_is_cached():
    assert main._confirm_locks_in_schema("confirm", schema_cached=True) is True


def test_confirm_is_case_and_whitespace_insensitive_once_schema_is_cached():
    assert main._confirm_locks_in_schema("  Confirm  ", schema_cached=True) is True


def test_confirm_is_ignored_before_a_schema_has_been_discovered():
    # A stray first message of "confirm" must not lock in the digest channel before
    # onboarding has ever run, or _deps() would be stuck on its empty-schema fallback.
    assert main._confirm_locks_in_schema("confirm", schema_cached=False) is False


def test_non_confirm_message_is_never_treated_as_confirmation():
    assert main._confirm_locks_in_schema("what happened this week?", schema_cached=True) is False


def test_previous_week_window_on_a_monday_is_the_seven_days_ending_yesterday():
    # 2026-08-03 is a Monday.
    start, end = main.previous_week_window(date(2026, 8, 3))
    assert (start, end) == (date(2026, 7, 27), date(2026, 8, 2))
    assert start.weekday() == 0 and end.weekday() == 6


def test_previous_week_window_mid_week_is_still_the_last_complete_week():
    start, end = main.previous_week_window(date(2026, 8, 6))  # Thursday
    assert (start, end) == (date(2026, 7, 27), date(2026, 8, 2))


# --- mocked end-to-end harness -------------------------------------------------

BOT_ID = 1234567890
USER_ID = 42

SCHEMA = {
    "events": {"level_start": ["level_number"], "level_complete": ["level_number"], "user_engagement": []},
    "date_range": ("20180101", "20180419"),
    "player_count": 5000,
}


class _FakeUser:
    def __init__(self, user_id: int, bot: bool = False):
        self.id = user_id
        self.bot = bot


BOT_USER = _FakeUser(BOT_ID, bot=True)


def _config(db_path: str = ":memory:") -> Config:
    return Config(
        discord_token="d-token",
        anthropic_api_key="a-key",
        bq_billing_project="proj",
        bq_dataset_path="firebase-public-project.analytics_153293282",
        google_application_credentials="/tmp/creds.json",
        cost_threshold_bytes=1000,
        db_path=db_path,
    )


def _channel(channel_id: int = 555):
    return SimpleNamespace(id=channel_id, send=AsyncMock())


def _thread_channel(thread_id: int):
    channel = MagicMock(spec=discord.Thread)
    channel.id = thread_id
    channel.send = AsyncMock()
    return channel


def _mention_message(text: str, channel=None, author_is_bot: bool = False):
    """A channel message that @mentions the bot, mention token included verbatim."""
    return SimpleNamespace(
        content=f"<@{BOT_ID}> {text}",
        author=_FakeUser(USER_ID, bot=author_is_bot),
        channel=channel or _channel(),
        mentions=[BOT_USER],
        create_thread=AsyncMock(),
    )


def _thread_message(text: str, thread):
    """A plain (unmentioned) follow-up posted inside a bot-created thread."""
    return SimpleNamespace(content=text, author=_FakeUser(USER_ID), channel=thread, mentions=[])


@pytest.fixture
def harness(monkeypatch):
    conn = sqlite3.connect(":memory:")
    db.init_db(conn)
    backend = MagicMock()
    anthropic_client = MagicMock()

    # discover_schema and the Anthropic calls are the only external work in these paths.
    monkeypatch.setattr("analystbot.bot.onboarding.discover_schema", lambda backend, path: SCHEMA)
    monkeypatch.setattr(pipeline.confidence_mod, "score_confidence", lambda q, sql, c: ConfidenceResult(confident=True))
    monkeypatch.setattr(pipeline.confidence_mod, "score_risk", lambda sql: False)
    monkeypatch.setattr(pipeline.answer_mod, "format_answer", lambda q, rows, note, c: f"answer to: {q}")

    bot = main.build_bot(config=_config(), conn=conn, backend=backend, anthropic_client=anthropic_client)
    monkeypatch.setattr(type(bot), "user", property(lambda self: BOT_USER), raising=False)
    return SimpleNamespace(bot=bot, conn=conn, backend=backend, anthropic_client=anthropic_client)


def _stub_understanding(monkeypatch, sql="SELECT 1", outcome=QuestionOutcome.MATCH, seen=None):
    def _understand(question, schema, context, preferences, dataset_path, client):
        if seen is not None:
            seen.append({"question": question, "context": context, "schema": schema})
        return QuestionResult(outcome=outcome, sql=sql)

    monkeypatch.setattr(pipeline.generate, "understand_and_generate", _understand)


@pytest.mark.asyncio
async def test_full_mention_onboard_confirm_question_followup_sequence(harness, monkeypatch):
    bot, conn = harness.bot, harness.conn
    channel = _channel()

    # 1. First mention: onboarding report, no digest channel yet.
    await bot.on_message(_mention_message("hey what can you do", channel=channel))
    report = channel.send.await_args.args[0]
    assert "level_start" in report and "5,000 players" in report
    assert schema_cache.load_schema(conn)["player_count"] == 5000
    assert config_store.get_digest_channel(conn) is None

    # 2. "@bot confirm" — the mention token must not defeat the confirm check.
    await bot.on_message(_mention_message("confirm", channel=channel))
    assert config_store.get_digest_channel(conn) == channel.id
    assert "Confirmed" in channel.send.await_args.args[0]

    # 3. A real question opens a thread and answers there.
    seen = []
    _stub_understanding(monkeypatch, seen=seen)
    harness.backend.dry_run.return_value = 10
    harness.backend.execute.return_value = [{"n": 4213}]

    thread = _thread_channel(777)
    question_message = _mention_message("how many players started level 3", channel=_channel())
    question_message.create_thread.return_value = thread
    await bot.on_message(question_message)

    # The question handed to Claude, the thread name, and the stored history are all
    # the mention-stripped text.
    assert seen[0]["question"] == "how many players started level 3"
    assert question_message.create_thread.await_args.kwargs["name"] == "how many players started level 3"
    thread.send.assert_awaited_once_with("answer to: how many players started level 3")
    stored = thread_store.get_thread_context(conn, 777)
    assert stored[0]["question"] == "how many players started level 3"
    assert "<@" not in stored[0]["question"]

    # 4. A plain follow-up inside that thread is answered with prior context.
    await bot.on_message(_thread_message("what about level 5", thread))
    assert seen[1]["question"] == "what about level 5"
    assert any(turn["question"] == "how many players started level 3" for turn in seen[1]["context"])
    assert len(thread_store.get_thread_context(conn, 777)) == 2


@pytest.mark.asyncio
async def test_cost_warning_then_confirm_runs_the_parked_query(harness, monkeypatch):
    bot, conn = harness.bot, harness.conn
    channel = _channel()
    config_store.set_digest_channel(conn, channel.id)
    schema_cache.save_schema(conn, SCHEMA)

    _stub_understanding(monkeypatch, sql="SELECT COUNT(*) FROM big")
    harness.backend.dry_run.return_value = 10_000_000_000  # over the 1000-byte threshold

    thread = _thread_channel(888)
    question_message = _mention_message("how many players ever", channel=_channel())
    question_message.create_thread.return_value = thread
    await bot.on_message(question_message)

    assert "confirm" in thread.send.await_args.args[0]
    harness.backend.execute.assert_not_called()
    assert thread_store.get_pending_query(conn, 888)["sql"] == "SELECT COUNT(*) FROM big"

    # Confirming in the thread runs exactly the parked SQL, without re-generating it.
    monkeypatch.setattr(
        pipeline.generate, "understand_and_generate",
        lambda *a, **k: pytest.fail("confirmed query must not be regenerated"),
    )
    harness.backend.execute.return_value = [{"n": 99}]
    await bot.on_message(_thread_message("confirm", thread))

    harness.backend.execute.assert_called_once_with("SELECT COUNT(*) FROM big")
    assert thread_store.get_pending_query(conn, 888) is None
    assert thread.send.await_args.args[0] == "answer to: how many players ever"


@pytest.mark.asyncio
async def test_a_different_followup_abandons_the_parked_query(harness, monkeypatch):
    bot, conn = harness.bot, harness.conn
    config_store.set_digest_channel(conn, 555)
    schema_cache.save_schema(conn, SCHEMA)
    thread = _thread_channel(999)
    thread_store.save_thread_context(conn, 999, "how many players ever", None, "cost warning")
    thread_store.save_pending_query(conn, 999, "how many players ever", "SELECT COUNT(*) FROM big")

    _stub_understanding(monkeypatch, sql="SELECT 2")
    harness.backend.dry_run.return_value = 10
    harness.backend.execute.return_value = [{"n": 1}]

    await bot.on_message(_thread_message("never mind, what about level 5", thread))

    assert thread_store.get_pending_query(conn, 999) is None
    harness.backend.execute.assert_called_once_with("SELECT 2")


@pytest.mark.asyncio
async def test_resetup_mention_reruns_onboarding_and_requires_a_new_confirm(harness):
    bot, conn = harness.bot, harness.conn
    channel = _channel()
    config_store.set_digest_channel(conn, channel.id)
    schema_cache.save_schema(conn, {"events": {"stale": []}, "date_range": ("", ""), "player_count": 0})

    await bot.on_message(_mention_message("resetup", channel=channel))

    assert config_store.get_digest_channel(conn) is None
    assert schema_cache.load_schema(conn)["player_count"] == 5000
    assert "level_start" in channel.send.await_args.args[0]


@pytest.mark.asyncio
async def test_pipeline_failure_replies_in_the_thread_and_keeps_it_alive(harness, monkeypatch):
    bot, conn = harness.bot, harness.conn
    config_store.set_digest_channel(conn, 555)
    schema_cache.save_schema(conn, SCHEMA)

    def _boom(*args, **kwargs):
        raise RuntimeError("anthropic exploded")

    monkeypatch.setattr(pipeline.generate, "understand_and_generate", _boom)

    thread = _thread_channel(1001)
    question_message = _mention_message("where do players quit", channel=_channel())
    question_message.create_thread.return_value = thread
    await bot.on_message(question_message)

    assert "went wrong" in thread.send.await_args.args[0]
    # The thread still has context, so follow-ups in it keep routing to the bot
    # instead of being classified as IGNORE forever.
    assert thread_store.get_thread_context(conn, 1001)


@pytest.mark.asyncio
async def test_followup_failure_replies_in_the_thread(harness, monkeypatch):
    bot, conn = harness.bot, harness.conn
    config_store.set_digest_channel(conn, 555)
    schema_cache.save_schema(conn, SCHEMA)
    thread = _thread_channel(1002)
    thread_store.save_thread_context(conn, 1002, "q", None, "a")

    def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(pipeline.generate, "understand_and_generate", _boom)
    await bot.on_message(_thread_message("and level 5?", thread))
    assert "went wrong" in thread.send.await_args.args[0]


@pytest.mark.asyncio
async def test_onboarding_failure_is_reported_not_swallowed(harness, monkeypatch):
    bot = harness.bot
    channel = _channel()

    def _boom(backend, path):
        raise RuntimeError("bigquery down")

    monkeypatch.setattr("analystbot.bot.onboarding.discover_schema", _boom)
    await bot.on_message(_mention_message("hello", channel=channel))
    assert "went wrong" in channel.send.await_args.args[0]


@pytest.mark.asyncio
async def test_messages_from_other_bots_are_ignored(harness):
    bot = harness.bot
    channel = _channel()
    await bot.on_message(_mention_message("confirm", channel=channel, author_is_bot=True))
    channel.send.assert_not_awaited()


# --- weekly digest job ---------------------------------------------------------


def _digest_bot(conn, backend, channel):
    return SimpleNamespace(conn=conn, backend=backend, get_channel=lambda cid: channel if cid == 555 else None)


@pytest.mark.asyncio
async def test_weekly_digest_job_posts_a_summary_for_the_last_complete_week():
    conn = sqlite3.connect(":memory:")
    db.init_db(conn)
    config_store.set_digest_channel(conn, 555)
    schema_cache.save_schema(conn, SCHEMA)
    digest_history.save_digest(conn, {"level_complete": (3600, 10000)}, "2026-07-20")

    backend = MagicMock()
    backend.execute.side_effect = [
        [{"n": 10000}],
        [{"event_name": "level_start", "n": 9000}, {"event_name": "level_complete", "n": 4000}],
    ]
    channel = _channel()
    job = main.make_weekly_digest_job(_digest_bot(conn, backend, channel), _config())
    await job()

    summary = channel.send.await_args.args[0]
    assert "worst leak" in summary
    assert "level_complete" in summary
    # Metrics are stored under the window's Monday, not "today".
    stored = digest_history.load_last_digest(conn)
    assert date.fromisoformat(stored["week_start"]).weekday() == 0
    assert stored["metrics"]["level_complete"] == (4000, 10000)


@pytest.mark.asyncio
async def test_weekly_digest_job_skips_when_the_schema_has_no_events():
    conn = sqlite3.connect(":memory:")
    db.init_db(conn)
    config_store.set_digest_channel(conn, 555)
    schema_cache.save_schema(conn, {"events": {}, "date_range": ("", ""), "player_count": 0})

    backend = MagicMock()
    channel = _channel()
    await main.make_weekly_digest_job(_digest_bot(conn, backend, channel), _config())()

    channel.send.assert_not_awaited()
    backend.execute.assert_not_called()


@pytest.mark.asyncio
async def test_weekly_digest_job_skips_when_no_digest_channel_is_configured():
    conn = sqlite3.connect(":memory:")
    db.init_db(conn)
    schema_cache.save_schema(conn, SCHEMA)
    backend = MagicMock()
    channel = _channel()
    await main.make_weekly_digest_job(_digest_bot(conn, backend, channel), _config())()
    channel.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_weekly_digest_job_reports_failure_to_the_digest_channel():
    conn = sqlite3.connect(":memory:")
    db.init_db(conn)
    config_store.set_digest_channel(conn, 555)
    schema_cache.save_schema(conn, SCHEMA)

    backend = MagicMock()
    backend.execute.side_effect = RuntimeError("bigquery down")
    channel = _channel()
    await main.make_weekly_digest_job(_digest_bot(conn, backend, channel), _config())()

    assert "went wrong" in channel.send.await_args.args[0]
