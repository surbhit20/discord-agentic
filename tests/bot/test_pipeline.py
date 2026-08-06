import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock
import analystbot.bot.pipeline as pipeline
from analystbot.query.generate import QuestionResult, QuestionOutcome
from analystbot.query.confidence import ConfidenceResult


@pytest.mark.asyncio
async def test_refusal_short_circuits_before_sql_execution(monkeypatch):
    monkeypatch.setattr(
        pipeline.generate, "understand_and_generate",
        lambda q, s, c, p, a: QuestionResult(outcome=QuestionOutcome.REFUSAL, message="you don't log session end"),
    )
    deps = SimpleNamespace(backend=MagicMock(), schema={}, anthropic_client=MagicMock(), cost_threshold_bytes=1000)
    reply, sql = await pipeline.answer_question("avg session length", 1, [], [], deps)
    assert "session end" in reply
    assert sql is None
    deps.backend.execute.assert_not_called()


@pytest.mark.asyncio
async def test_clarify_short_circuits(monkeypatch):
    monkeypatch.setattr(
        pipeline.generate, "understand_and_generate",
        lambda q, s, c, p, a: QuestionResult(outcome=QuestionOutcome.CLARIFY, message="did you mean X or Y?"),
    )
    deps = SimpleNamespace(backend=MagicMock(), schema={}, anthropic_client=MagicMock(), cost_threshold_bytes=1000)
    reply, sql = await pipeline.answer_question("vibe economy", 1, [], [], deps)
    assert "X or Y" in reply
    assert sql is None


@pytest.mark.asyncio
async def test_expensive_query_returns_cost_warning_without_executing(monkeypatch):
    monkeypatch.setattr(
        pipeline.generate, "understand_and_generate",
        lambda q, s, c, p, a: QuestionResult(outcome=QuestionOutcome.MATCH, sql="SELECT 1"),
    )
    deps = SimpleNamespace(
        backend=MagicMock(dry_run=MagicMock(return_value=10_000_000_000)),
        schema={}, anthropic_client=MagicMock(), cost_threshold_bytes=1000,
    )
    reply, sql = await pipeline.answer_question("how many players ever", 1, [], [], deps)
    assert "confirm" in reply
    deps.backend.execute.assert_not_called()


@pytest.mark.asyncio
async def test_confident_safe_answer_has_no_caution(monkeypatch):
    monkeypatch.setattr(
        pipeline.generate, "understand_and_generate",
        lambda q, s, c, p, a: QuestionResult(outcome=QuestionOutcome.MATCH, sql="SELECT COUNT(*) FROM x"),
    )
    monkeypatch.setattr(pipeline, "check_cost", lambda backend, sql, threshold: (False, 10))
    monkeypatch.setattr(pipeline.confidence_mod, "score_confidence", lambda q, sql, c: ConfidenceResult(confident=True))
    monkeypatch.setattr(pipeline.confidence_mod, "score_risk", lambda sql: False)
    monkeypatch.setattr(pipeline.answer_mod, "format_answer", lambda q, rows, note, c: "22% of players quit here.")
    deps = SimpleNamespace(
        backend=MagicMock(execute=MagicMock(return_value=[{"n": 220}])),
        schema={}, anthropic_client=MagicMock(), cost_threshold_bytes=1000,
    )
    reply, sql = await pipeline.answer_question("where do players quit", 1, [], [], deps)
    assert reply == "22% of players quit here."
    assert "caution" not in reply.lower()


@pytest.mark.asyncio
async def test_low_confidence_answer_gets_caution_flag(monkeypatch):
    monkeypatch.setattr(
        pipeline.generate, "understand_and_generate",
        lambda q, s, c, p, a: QuestionResult(outcome=QuestionOutcome.MATCH, sql="SELECT COUNT(*) FROM x"),
    )
    monkeypatch.setattr(pipeline, "check_cost", lambda backend, sql, threshold: (False, 10))
    monkeypatch.setattr(
        pipeline.confidence_mod, "score_confidence",
        lambda q, sql, c: ConfidenceResult(confident=False, reason="unsure which param"),
    )
    monkeypatch.setattr(pipeline.confidence_mod, "score_risk", lambda sql: False)
    monkeypatch.setattr(pipeline.answer_mod, "format_answer", lambda q, rows, note, c: "22% of players quit here.")
    deps = SimpleNamespace(
        backend=MagicMock(execute=MagicMock(return_value=[{"n": 220}])),
        schema={}, anthropic_client=MagicMock(), cost_threshold_bytes=1000,
    )
    reply, sql = await pipeline.answer_question("where do players quit", 1, [], [], deps)
    assert "caution" in reply.lower()
    assert "unsure which param" in reply
