import asyncio

import analystbot.query.generate as generate
import analystbot.query.confidence as confidence_mod
import analystbot.query.answer as answer_mod
from analystbot.digest.significance import significance_note
from analystbot.query.generate import QuestionOutcome
from analystbot.query.cost_check import check_cost
from analystbot.storage import digest_history, threads as thread_store, user_memory
from analystbot.bot.replies import format_refusal, format_clarify, format_cost_warning, format_caution

# Every external call below (Anthropic HTTP, BigQuery dry-run/execute) is a blocking
# synchronous call, so it runs inside `asyncio.to_thread` and never blocks the Discord
# gateway heartbeat. SQLite access deliberately stays on the event-loop thread: the
# connection is created there and sqlite3 connections are thread-affine.

# Claude is asked for a message alongside every refusal/clarify, but the tool schema
# can't require it conditionally — these keep a missing message from rendering as "None".
_FALLBACK_REFUSAL = "the discovered schema doesn't cover it"
_FALLBACK_CLARIFY = "I'm not sure what you're asking — can you rephrase that?"

# Phrases that make last week's stored digest relevant to an ad-hoc question. When one
# appears, the cached digest numbers are handed to question understanding as extra
# context so the bot can answer from them instead of re-querying BigQuery.
_LAST_WEEK_PHRASES = (
    "last week",
    "last week's",
    "previous week",
    "prior week",
    "week over week",
    "week-over-week",
    "since the last build",
    "last build",
)


def _conn_of(deps):
    return getattr(deps, "conn", None)


def _digest_context(question: str, deps) -> list[dict]:
    """Cached last-digest numbers as a context turn, when the question reaches backwards."""
    conn = _conn_of(deps)
    if conn is None:
        return []
    lowered = question.lower()
    if not any(phrase in lowered for phrase in _LAST_WEEK_PHRASES):
        return []
    last = digest_history.load_last_digest(conn)
    if not last or not last["metrics"]:
        return []
    numbers = ", ".join(
        f"{name}: {count}/{total} ({count / total:.0%} of active players)" if total else f"{name}: {count}/0"
        for name, (count, total) in sorted(last["metrics"].items())
    )
    return [
        {
            "question": f"(cached weekly digest, week starting {last['week_start']})",
            "sql": None,
            "answer": (
                f"Stored digest metrics — {numbers}. These are already-computed numbers for that "
                "week; prefer them over re-querying BigQuery when they answer the question."
            ),
        }
    ]


def _remember_preference(result, user_id: int, deps) -> None:
    conn = _conn_of(deps)
    if conn is None or not result.preference_to_remember:
        return
    user_memory.add_preference(conn, user_id, result.preference_to_remember)


async def _execute_and_format(question: str, sql: str, deps) -> str:
    """Confidence-score, run, and verbalise one already-approved SQL statement."""
    confidence = await asyncio.to_thread(confidence_mod.score_confidence, question, sql, deps.anthropic_client)
    risky = confidence_mod.score_risk(sql)
    rows = await asyncio.to_thread(deps.backend.execute, sql)
    note = significance_note(rows)
    answer_text = await asyncio.to_thread(answer_mod.format_answer, question, rows, note, deps.anthropic_client)

    if confidence_mod.needs_caution(confidence, risky):
        answer_text = format_caution(answer_text, confidence.reason or "generated query uses a complex shape")
    return answer_text


async def answer_question(
    question: str, user_id: int, context: list[dict], preferences: list[str], deps, thread_id: int | None = None
) -> tuple[str, str | None]:
    full_context = context + _digest_context(question, deps)
    result = await asyncio.to_thread(
        generate.understand_and_generate,
        question,
        deps.schema,
        full_context,
        preferences,
        deps.dataset_path,
        deps.anthropic_client,
    )
    _remember_preference(result, user_id, deps)

    if result.outcome == QuestionOutcome.REFUSAL:
        return format_refusal(result.message or _FALLBACK_REFUSAL), None
    if result.outcome == QuestionOutcome.CLARIFY:
        return format_clarify(result.message or _FALLBACK_CLARIFY), None

    needs_confirm, bytes_estimate = await asyncio.to_thread(
        check_cost, deps.backend, result.sql, deps.cost_threshold_bytes
    )
    if needs_confirm:
        conn = _conn_of(deps)
        if conn is not None and thread_id is not None:
            # Park the exact SQL so a `confirm` reply in this thread runs *this* query
            # rather than regenerating it and hitting the same threshold forever.
            thread_store.save_pending_query(conn, thread_id, question, result.sql)
        return format_cost_warning(bytes_estimate, deps.cost_threshold_bytes, deps.price_per_tib_usd), result.sql

    return await _execute_and_format(question, result.sql, deps), result.sql


async def run_pending_query(question: str, sql: str, deps) -> tuple[str, str | None]:
    """Run a query the user confirmed after a cost warning: no re-generation, no cost check."""
    return await _execute_and_format(question, sql, deps), sql
