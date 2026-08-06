import os
from datetime import date, timedelta
import discord
import anthropic
from analystbot.config import load_config
from analystbot.storage import db, threads as thread_store, user_memory, config_store, schema_cache
from analystbot.query.backend import BigQueryBackend
from analystbot.bot.client import AnalystBot
from analystbot.bot.onboarding import run_onboarding
from analystbot.bot.pipeline import answer_question
from analystbot.digest.compute import run_digest, query_weekly_metrics
from analystbot.digest.scheduler import start_scheduler
from types import SimpleNamespace


def build_bot() -> AnalystBot:
    config = load_config(dict(os.environ))
    conn = db.get_connection(config.db_path)
    backend = BigQueryBackend(project=config.bq_billing_project, credentials_path=config.google_application_credentials)
    anthropic_client = anthropic.Anthropic(api_key=config.anthropic_api_key)

    def _long_term_context(user_id: int) -> tuple[list[dict], list[str]]:
        recent = user_memory.get_recent_history(conn, user_id)
        context = [{"question": r["question"], "sql": None, "answer": r["answer"]} for r in recent]
        preferences = user_memory.get_preferences(conn, user_id)
        return context, preferences

    def _deps() -> SimpleNamespace:
        schema = schema_cache.load_schema(conn) or {"events": {}, "date_range": ("", ""), "player_count": 0}
        return SimpleNamespace(backend=backend, schema=schema, anthropic_client=anthropic_client, cost_threshold_bytes=config.cost_threshold_bytes)

    async def handle_new_question(message: discord.Message) -> None:
        thread = await message.create_thread(name=message.content[:80])
        long_term_context, preferences = _long_term_context(message.author.id)
        reply, sql = await answer_question(message.content, message.author.id, long_term_context, preferences, _deps())
        await thread.send(reply)
        thread_store.save_thread_context(conn, thread.id, message.content, sql, reply)
        user_memory.add_question_history(conn, message.author.id, message.content, reply)

    async def handle_followup(message: discord.Message) -> None:
        thread_context = thread_store.get_thread_context(conn, message.channel.id)
        long_term_context, preferences = _long_term_context(message.author.id)
        reply, sql = await answer_question(
            message.content, message.author.id, thread_context + long_term_context, preferences, _deps()
        )
        await message.channel.send(reply)
        thread_store.save_thread_context(conn, message.channel.id, message.content, sql, reply)
        user_memory.add_question_history(conn, message.author.id, message.content, reply)

    async def handle_onboarding(message: discord.Message) -> None:
        if message.content.strip().lower() == "confirm":
            config_store.set_digest_channel(conn, message.channel.id)
            await message.channel.send("Confirmed. I'll post the weekly digest here.")
        else:
            await run_onboarding(message, backend, config.bq_dataset_path, conn)

    intents = discord.Intents.default()
    intents.message_content = True
    return AnalystBot(
        conn=conn, backend=backend, dataset_path=config.bq_dataset_path,
        anthropic_client=anthropic_client, cost_threshold_bytes=config.cost_threshold_bytes,
        handle_new_question=handle_new_question, handle_followup=handle_followup,
        handle_onboarding=handle_onboarding, intents=intents,
    )


def main() -> None:
    config = load_config(dict(os.environ))
    bot = build_bot()

    async def weekly_digest_job() -> None:
        channel_id = config_store.get_digest_channel(bot.conn)
        if channel_id is None:
            return
        channel = bot.get_channel(channel_id)
        if channel is None:
            return
        schema = schema_cache.load_schema(bot.conn)
        if schema is None:
            return
        today = date.today()
        suffix_end = today.strftime("%Y%m%d")
        suffix_start = (today - timedelta(days=6)).strftime("%Y%m%d")
        current_metrics = query_weekly_metrics(bot.backend, config.bq_dataset_path, list(schema["events"].keys()), suffix_start, suffix_end)
        result = run_digest(bot.conn, today.isoformat(), current_metrics)
        await channel.send(result.summary)

    start_scheduler(weekly_digest_job)
    bot.run(config.discord_token)


if __name__ == "__main__":
    main()
