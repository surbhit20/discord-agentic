import asyncio

import analystbot.query.generate as generate
import analystbot.query.confidence as confidence_mod
import analystbot.query.answer as answer_mod
from analystbot.query.generate import QuestionOutcome
from analystbot.query.cost_check import check_cost
from analystbot.bot.replies import format_refusal, format_clarify, format_cost_warning, format_caution

# Every external call below (Anthropic HTTP, BigQuery dry-run/execute) is a blocking
# synchronous call, so it runs inside `asyncio.to_thread` and never blocks the Discord
# gateway heartbeat. SQLite access deliberately stays on the event-loop thread: the
# connection is created there and sqlite3 connections are thread-affine.


async def answer_question(
    question: str, user_id: int, context: list[dict], preferences: list[str], deps
) -> tuple[str, str | None]:
    result = await asyncio.to_thread(
        generate.understand_and_generate, question, deps.schema, context, preferences, deps.anthropic_client
    )

    if result.outcome == QuestionOutcome.REFUSAL:
        return format_refusal(result.message), None
    if result.outcome == QuestionOutcome.CLARIFY:
        return format_clarify(result.message), None

    needs_confirm, bytes_estimate = await asyncio.to_thread(
        check_cost, deps.backend, result.sql, deps.cost_threshold_bytes
    )
    if needs_confirm:
        return format_cost_warning(bytes_estimate), result.sql

    confidence = await asyncio.to_thread(
        confidence_mod.score_confidence, question, result.sql, deps.anthropic_client
    )
    risky = confidence_mod.score_risk(result.sql)
    rows = await asyncio.to_thread(deps.backend.execute, result.sql)
    answer_text = await asyncio.to_thread(
        answer_mod.format_answer, question, rows, None, deps.anthropic_client
    )

    if confidence_mod.needs_caution(confidence, risky):
        answer_text = format_caution(answer_text, confidence.reason or "generated query uses a complex shape")

    return answer_text, result.sql
