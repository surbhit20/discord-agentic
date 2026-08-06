import asyncio
import logging
import os
from datetime import date, timedelta
from types import SimpleNamespace

import anthropic
import discord
from dotenv import load_dotenv

from analystbot.bot.client import AnalystBot
from analystbot.bot.onboarding import run_onboarding
from analystbot.bot.pipeline import answer_question, run_pending_query
from analystbot.bot.routing import strip_bot_mention
from analystbot.config import Config, load_config
from analystbot.digest.compute import query_weekly_metrics, run_digest
from analystbot.digest.scheduler import start_scheduler
from analystbot.query.backend import BigQueryBackend
from analystbot.storage import config_store, db, schema_cache, threads as thread_store, user_memory

logger = logging.getLogger(__name__)

_GENERIC_FAILURE = "Something went wrong answering that — try rephrasing?"
_ONBOARDING_FAILURE = "Something went wrong reading the dataset — mention me again to retry."
_DIGEST_FAILURE = "Something went wrong building this week's digest — I'll try again next Monday."

# Mentioning the bot with exactly this word re-runs schema discovery and re-opens the
# confirmation step, even once a digest channel is configured. It is the only way to
# refresh the cached schema without a redeploy (the spec calls for a refresh "on each
# onboarding run or re-confirmation", and there are no slash commands).
_RESET_TRIGGER = "resetup"

_CONFIRM = "confirm"


def _confirm_locks_in_schema(content: str, schema_cached: bool) -> bool:
    """True only when the message is exactly "confirm" AND a schema has already been
    discovered and cached for this guild.

    `content` must already have the bot's mention stripped — messages reach this path
    only via an @mention, so `message.content` itself is always "<@id> confirm".

    Without the `schema_cached` check, a user's very first message being "@bot confirm"
    would set the digest channel before `run_onboarding` ever ran, permanently routing
    NEW_QUESTION away from onboarding and leaving `_deps()` stuck on its empty-schema
    fallback forever (every question would look unanswerable against `{"events": {}}`).
    """
    return content.strip().lower() == _CONFIRM and schema_cached


def _is_reset_request(content: str) -> bool:
    return content.strip().lower() == _RESET_TRIGGER


def previous_week_window(today: date) -> tuple[date, date]:
    """The last complete Monday–Sunday week before `today`.

    Run on a Monday (the scheduled day), this is the seven days ending yesterday.
    The previous rolling `today-6 … today` window straddled two weeks.
    """
    this_monday = today - timedelta(days=today.weekday())
    return this_monday - timedelta(days=7), this_monday - timedelta(days=1)


async def _safe_send(target, text: str) -> None:
    """Best-effort reply. A failure to deliver the error message must not raise again."""
    try:
        await target.send(text)
    except Exception:
        logger.exception("failed to send message to %r", target)


def build_bot(*, config: Config, conn, backend, anthropic_client) -> AnalystBot:
    """Assemble the bot from already-constructed collaborators.

    Everything external is injected so the handlers can be exercised in tests without
    env vars, a credential file, or a real Anthropic client. `build_bot_from_env` is the
    thin production wrapper that builds those collaborators from the environment.
    """
    # Handlers are defined before the client exists, so they read the bot's user id
    # (needed to strip its own mention) through this late-bound holder.
    holder = SimpleNamespace(bot=None)

    def _bot_user_id() -> int | None:
        bot = holder.bot
        user = getattr(bot, "user", None) if bot is not None else None
        return getattr(user, "id", None)

    def _question_text(message) -> str:
        return strip_bot_mention(message.content, _bot_user_id())

    def _long_term_context(user_id: int) -> tuple[list[dict], list[str]]:
        recent = user_memory.get_recent_history(conn, user_id)
        context = [{"question": r["question"], "sql": None, "answer": r["answer"]} for r in recent]
        preferences = user_memory.get_preferences(conn, user_id)
        return context, preferences

    def _deps() -> SimpleNamespace:
        schema = schema_cache.load_schema(conn) or {"events": {}, "date_range": ("", ""), "player_count": 0}
        return SimpleNamespace(
            backend=backend,
            schema=schema,
            anthropic_client=anthropic_client,
            cost_threshold_bytes=config.cost_threshold_bytes,
            conn=conn,
        )

    async def _rerun_onboarding(message) -> None:
        # Re-confirmation: drop the digest channel so the next `confirm` re-designates
        # it, and re-discover the schema from scratch.
        config_store.clear_digest_channel(conn)
        await run_onboarding(message, backend, config.bq_dataset_path, conn)

    async def handle_new_question(message: discord.Message) -> None:
        thread = None
        question = ""
        try:
            question = _question_text(message)
            if _is_reset_request(question):
                await _rerun_onboarding(message)
                return

            thread = await message.create_thread(name=(question or "question")[:80])
            long_term_context, preferences = _long_term_context(message.author.id)
            reply, sql = await answer_question(
                question, message.author.id, long_term_context, preferences, _deps(), thread_id=thread.id
            )
            await thread.send(reply)
            thread_store.save_thread_context(conn, thread.id, question, sql, reply)
            user_memory.add_question_history(conn, message.author.id, question, reply)
        except Exception:
            logger.exception("handle_new_question failed")
            await _safe_send(thread or message.channel, _GENERIC_FAILURE)
            if thread is not None:
                # Record the turn anyway: `thread_started_by_bot` is "this thread has
                # context", so skipping the write would leave a thread where every
                # follow-up is silently ignored forever.
                try:
                    thread_store.save_thread_context(conn, thread.id, question, None, _GENERIC_FAILURE)
                except Exception:
                    logger.exception("failed to record failed turn for thread %s", getattr(thread, "id", None))

    async def handle_followup(message: discord.Message) -> None:
        try:
            question = _question_text(message)
            thread_id = message.channel.id
            pending = thread_store.get_pending_query(conn, thread_id)

            if pending is not None and question.strip().lower() == _CONFIRM:
                # The user approved the expensive query: run exactly that SQL, no
                # re-generation and no second cost check.
                thread_store.clear_pending_query(conn, thread_id)
                reply, sql = await run_pending_query(pending["question"], pending["sql"], _deps())
                question = pending["question"]
            else:
                if pending is not None:
                    # Anything else abandons the parked query.
                    thread_store.clear_pending_query(conn, thread_id)
                thread_context = thread_store.get_thread_context(conn, thread_id)
                long_term_context, preferences = _long_term_context(message.author.id)
                reply, sql = await answer_question(
                    question, message.author.id, thread_context + long_term_context, preferences,
                    _deps(), thread_id=thread_id,
                )

            await message.channel.send(reply)
            thread_store.save_thread_context(conn, thread_id, question, sql, reply)
            user_memory.add_question_history(conn, message.author.id, question, reply)
        except Exception:
            logger.exception("handle_followup failed")
            await _safe_send(message.channel, _GENERIC_FAILURE)

    async def handle_onboarding(message: discord.Message) -> None:
        try:
            content = _question_text(message)
            schema_cached = schema_cache.load_schema(conn) is not None
            if _confirm_locks_in_schema(content, schema_cached):
                config_store.set_digest_channel(conn, message.channel.id)
                await message.channel.send(
                    "Confirmed. I'll post the weekly digest here. "
                    f"Mention me with `{_RESET_TRIGGER}` any time to re-run schema discovery."
                )
            else:
                await run_onboarding(message, backend, config.bq_dataset_path, conn)
        except Exception:
            logger.exception("handle_onboarding failed")
            await _safe_send(message.channel, _ONBOARDING_FAILURE)

    intents = discord.Intents.default()
    intents.message_content = True
    bot = AnalystBot(
        conn=conn, backend=backend, dataset_path=config.bq_dataset_path,
        anthropic_client=anthropic_client, cost_threshold_bytes=config.cost_threshold_bytes,
        handle_new_question=handle_new_question, handle_followup=handle_followup,
        handle_onboarding=handle_onboarding, intents=intents,
    )
    holder.bot = bot
    return bot


def build_bot_from_env(env: dict[str, str] | None = None) -> tuple[AnalystBot, Config]:
    config = load_config(dict(env if env is not None else os.environ))
    conn = db.get_connection(config.db_path)
    backend = BigQueryBackend(
        project=config.bq_billing_project, credentials_path=config.google_application_credentials
    )
    anthropic_client = anthropic.Anthropic(api_key=config.anthropic_api_key)
    bot = build_bot(config=config, conn=conn, backend=backend, anthropic_client=anthropic_client)
    return bot, config


def make_weekly_digest_job(bot, config: Config):
    async def weekly_digest_job() -> None:
        try:
            channel_id = config_store.get_digest_channel(bot.conn)
            if channel_id is None:
                return
            channel = bot.get_channel(channel_id)
            if channel is None:
                logger.warning("digest channel %s is not visible to the bot", channel_id)
                return
            schema = schema_cache.load_schema(bot.conn)
            if not schema or not schema.get("events"):
                # run_digest takes min() over the metric set, so an empty schema (or an
                # empty metric result) would raise rather than post anything useful.
                logger.warning("no cached schema events; skipping digest")
                return

            week_start, week_end = previous_week_window(date.today())
            current_metrics = await asyncio.to_thread(
                query_weekly_metrics,
                bot.backend, config.bq_dataset_path, list(schema["events"].keys()),
                week_start.strftime("%Y%m%d"), week_end.strftime("%Y%m%d"),
            )
            if not current_metrics:
                logger.warning("weekly metrics came back empty; skipping digest")
                return

            result = run_digest(bot.conn, week_start.isoformat(), current_metrics)
            await channel.send(result.summary)
        except Exception:
            logger.exception("weekly_digest_job failed")
            channel = bot.get_channel(config_store.get_digest_channel(bot.conn) or 0)
            if channel is not None:
                await _safe_send(channel, _DIGEST_FAILURE)

    return weekly_digest_job


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    load_dotenv()
    bot, config = build_bot_from_env()
    weekly_digest_job = make_weekly_digest_job(bot, config)

    @bot.event
    async def on_ready() -> None:
        # AsyncIOScheduler must attach to a running event loop, and weekly_digest_job
        # touches bot.conn (a thread-affine sqlite3.Connection) and the bot's own
        # aiohttp session — both require running on this exact loop/thread. on_ready
        # fires after bot.run() has started that loop, so this is the first safe point
        # to start it. on_ready can fire again after a reconnect, so guard against
        # scheduling the job a second time.
        if not getattr(bot, "_scheduler_started", False):
            bot._scheduler_started = True
            start_scheduler(weekly_digest_job)

    bot.run(config.discord_token)


if __name__ == "__main__":
    main()
