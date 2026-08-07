import sqlite3
import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock
import analystbot.bot.pipeline as pipeline
from analystbot.query.generate import QuestionResult, QuestionOutcome
from analystbot.query.confidence import ConfidenceResult
from analystbot.storage import db, digest_history, threads as thread_store, user_memory

_DATASET_PATH = "firebase-public-project.analytics_153293282"


@pytest.mark.asyncio
async def test_refusal_short_circuits_before_sql_execution(monkeypatch):
    monkeypatch.setattr(
        pipeline.generate, "understand_and_generate",
        lambda q, s, c, p, d, a: QuestionResult(outcome=QuestionOutcome.REFUSAL, message="you don't log session end"),
    )
    deps = SimpleNamespace(
        backend=MagicMock(), schema={}, dataset_path=_DATASET_PATH,
        anthropic_client=MagicMock(), cost_threshold_bytes=1000,
    )
    reply, sql = await pipeline.answer_question("avg session length", 1, [], [], deps)
    assert "session end" in reply
    assert sql is None
    deps.backend.execute.assert_not_called()


@pytest.mark.asyncio
async def test_clarify_short_circuits(monkeypatch):
    monkeypatch.setattr(
        pipeline.generate, "understand_and_generate",
        lambda q, s, c, p, d, a: QuestionResult(outcome=QuestionOutcome.CLARIFY, message="did you mean X or Y?"),
    )
    deps = SimpleNamespace(
        backend=MagicMock(), schema={}, dataset_path=_DATASET_PATH,
        anthropic_client=MagicMock(), cost_threshold_bytes=1000,
    )
    reply, sql = await pipeline.answer_question("vibe economy", 1, [], [], deps)
    assert "X or Y" in reply
    assert sql is None


@pytest.mark.asyncio
async def test_expensive_query_returns_cost_warning_without_executing(monkeypatch):
    monkeypatch.setattr(
        pipeline.generate, "understand_and_generate",
        lambda q, s, c, p, d, a: QuestionResult(outcome=QuestionOutcome.MATCH, sql="SELECT 1"),
    )
    deps = SimpleNamespace(
        backend=MagicMock(dry_run=MagicMock(return_value=10_000_000_000)),
        schema={}, dataset_path=_DATASET_PATH, anthropic_client=MagicMock(), cost_threshold_bytes=1000,
        price_per_tib_usd=6.25,
    )
    reply, sql = await pipeline.answer_question("how many players ever", 1, [], [], deps)
    assert "confirm" in reply
    deps.backend.execute.assert_not_called()


@pytest.mark.asyncio
async def test_confident_safe_answer_has_no_caution(monkeypatch):
    monkeypatch.setattr(
        pipeline.generate, "understand_and_generate",
        lambda q, s, c, p, d, a: QuestionResult(outcome=QuestionOutcome.MATCH, sql="SELECT COUNT(*) FROM x"),
    )
    monkeypatch.setattr(pipeline, "check_cost", lambda backend, sql, threshold: (False, 10))
    monkeypatch.setattr(pipeline.confidence_mod, "score_confidence", lambda q, sql, c: ConfidenceResult(confident=True))
    monkeypatch.setattr(pipeline.confidence_mod, "score_risk", lambda sql: False)
    monkeypatch.setattr(pipeline.answer_mod, "format_answer", lambda q, rows, note, c: "22% of players quit here.")
    deps = SimpleNamespace(
        backend=MagicMock(execute=MagicMock(return_value=[{"n": 220}])),
        schema={}, dataset_path=_DATASET_PATH, anthropic_client=MagicMock(), cost_threshold_bytes=1000,
    )
    reply, sql = await pipeline.answer_question("where do players quit", 1, [], [], deps)
    assert reply == "22% of players quit here."
    assert "caution" not in reply.lower()


@pytest.mark.asyncio
async def test_low_confidence_answer_gets_caution_flag(monkeypatch):
    monkeypatch.setattr(
        pipeline.generate, "understand_and_generate",
        lambda q, s, c, p, d, a: QuestionResult(outcome=QuestionOutcome.MATCH, sql="SELECT COUNT(*) FROM x"),
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
        schema={}, dataset_path=_DATASET_PATH, anthropic_client=MagicMock(), cost_threshold_bytes=1000,
    )
    reply, sql = await pipeline.answer_question("where do players quit", 1, [], [], deps)
    assert "caution" in reply.lower()
    assert "unsure which param" in reply


def _memory_conn():
    conn = sqlite3.connect(":memory:")
    db.init_db(conn)
    return conn


def _deps(conn=None, **overrides):
    base = dict(
        backend=MagicMock(execute=MagicMock(return_value=[{"n": 220}])),
        schema={},
        dataset_path=_DATASET_PATH,
        anthropic_client=MagicMock(),
        cost_threshold_bytes=1000,
        price_per_tib_usd=6.25,
        conn=conn,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _stub_execution_path(monkeypatch, answer="22% of players quit here.", captured_note=None):
    monkeypatch.setattr(pipeline, "check_cost", lambda backend, sql, threshold: (False, 10))
    monkeypatch.setattr(pipeline.confidence_mod, "score_confidence", lambda q, sql, c: ConfidenceResult(confident=True))
    monkeypatch.setattr(pipeline.confidence_mod, "score_risk", lambda sql: False)

    def _format_answer(q, rows, note, client):
        if captured_note is not None:
            captured_note.append(note)
        return answer

    monkeypatch.setattr(pipeline.answer_mod, "format_answer", _format_answer)


@pytest.mark.asyncio
async def test_refusal_without_a_message_does_not_render_none(monkeypatch):
    monkeypatch.setattr(
        pipeline.generate, "understand_and_generate",
        lambda q, s, c, p, d, a: QuestionResult(outcome=QuestionOutcome.REFUSAL),
    )
    reply, sql = await pipeline.answer_question("avg session length", 1, [], [], _deps())
    assert "None" not in reply
    assert sql is None


@pytest.mark.asyncio
async def test_clarify_without_a_message_does_not_render_none(monkeypatch):
    monkeypatch.setattr(
        pipeline.generate, "understand_and_generate",
        lambda q, s, c, p, d, a: QuestionResult(outcome=QuestionOutcome.CLARIFY),
    )
    reply, sql = await pipeline.answer_question("vibe economy", 1, [], [], _deps())
    assert "None" not in reply
    assert reply.strip()


@pytest.mark.asyncio
async def test_stated_preference_is_written_to_user_memory(monkeypatch):
    monkeypatch.setattr(
        pipeline.generate, "understand_and_generate",
        lambda q, s, c, p, d, a: QuestionResult(
            outcome=QuestionOutcome.MATCH, sql="SELECT COUNT(*) FROM x",
            preference_to_remember="always show D7, not D1",
        ),
    )
    _stub_execution_path(monkeypatch)
    conn = _memory_conn()
    await pipeline.answer_question("what's retention, always show me D7 not D1", 7, [], [], _deps(conn))
    assert user_memory.get_preferences(conn, 7) == ["always show D7, not D1"]


@pytest.mark.asyncio
async def test_preference_is_remembered_even_when_the_question_is_refused(monkeypatch):
    monkeypatch.setattr(
        pipeline.generate, "understand_and_generate",
        lambda q, s, c, p, d, a: QuestionResult(
            outcome=QuestionOutcome.REFUSAL, message="you don't log session end",
            preference_to_remember="remember that I care about the tutorial funnel",
        ),
    )
    conn = _memory_conn()
    await pipeline.answer_question("remember I care about the tutorial funnel", 7, [], [], _deps(conn))
    assert user_memory.get_preferences(conn, 7) == ["remember that I care about the tutorial funnel"]


@pytest.mark.asyncio
async def test_no_preference_means_no_write(monkeypatch):
    monkeypatch.setattr(
        pipeline.generate, "understand_and_generate",
        lambda q, s, c, p, d, a: QuestionResult(outcome=QuestionOutcome.MATCH, sql="SELECT COUNT(*) FROM x"),
    )
    _stub_execution_path(monkeypatch)
    conn = _memory_conn()
    await pipeline.answer_question("where do players quit", 7, [], [], _deps(conn))
    assert user_memory.get_preferences(conn, 7) == []


@pytest.mark.asyncio
async def test_two_group_result_passes_a_significance_note_to_answer_formatting(monkeypatch):
    monkeypatch.setattr(
        pipeline.generate, "understand_and_generate",
        lambda q, s, c, p, d, a: QuestionResult(outcome=QuestionOutcome.MATCH, sql="SELECT 1"),
    )
    notes = []
    _stub_execution_path(monkeypatch, captured_note=notes)
    deps = _deps(backend=MagicMock(execute=MagicMock(return_value=[
        {"cohort": "before", "retained": 3600, "total": 10000},
        {"cohort": "after", "retained": 4000, "total": 10000},
    ])))
    await pipeline.answer_question("did retention drop after last week's build", 1, [], [], deps)
    assert notes[0] is not None
    assert "significant" in notes[0]
    assert "before" in notes[0] and "after" in notes[0]


@pytest.mark.asyncio
async def test_single_row_result_gets_no_significance_note(monkeypatch):
    monkeypatch.setattr(
        pipeline.generate, "understand_and_generate",
        lambda q, s, c, p, d, a: QuestionResult(outcome=QuestionOutcome.MATCH, sql="SELECT 1"),
    )
    notes = []
    _stub_execution_path(monkeypatch, captured_note=notes)
    await pipeline.answer_question("how many players started level 3", 1, [], [], _deps())
    assert notes == [None]


@pytest.mark.asyncio
async def test_last_week_question_gets_the_cached_digest_as_context(monkeypatch):
    seen = {}

    def _capture(question, schema, context, preferences, dataset_path, client):
        seen["context"] = context
        return QuestionResult(outcome=QuestionOutcome.MATCH, sql="SELECT 1")

    monkeypatch.setattr(pipeline.generate, "understand_and_generate", _capture)
    _stub_execution_path(monkeypatch)
    conn = _memory_conn()
    digest_history.save_digest(conn, {"level_complete": (400, 1000)}, "2026-07-27")
    await pipeline.answer_question("did retention drop after last week's build", 1, [], [], _deps(conn))
    digest_turns = [t for t in seen["context"] if "cached weekly digest" in t["question"]]
    assert len(digest_turns) == 1
    assert "level_complete" in digest_turns[0]["answer"]
    assert "2026-07-27" in digest_turns[0]["question"]


@pytest.mark.asyncio
async def test_question_without_last_week_phrasing_skips_the_cached_digest(monkeypatch):
    seen = {}

    def _capture(question, schema, context, preferences, dataset_path, client):
        seen["context"] = context
        return QuestionResult(outcome=QuestionOutcome.MATCH, sql="SELECT 1")

    monkeypatch.setattr(pipeline.generate, "understand_and_generate", _capture)
    _stub_execution_path(monkeypatch)
    conn = _memory_conn()
    digest_history.save_digest(conn, {"level_complete": (400, 1000)}, "2026-07-27")
    await pipeline.answer_question("how many players started level 3", 1, [], [], _deps(conn))
    assert seen["context"] == []


@pytest.mark.asyncio
async def test_cost_warning_parks_the_pending_query_for_the_thread(monkeypatch):
    monkeypatch.setattr(
        pipeline.generate, "understand_and_generate",
        lambda q, s, c, p, d, a: QuestionResult(outcome=QuestionOutcome.MATCH, sql="SELECT COUNT(*) FROM big"),
    )
    conn = _memory_conn()
    deps = _deps(conn, backend=MagicMock(dry_run=MagicMock(return_value=10_000_000_000)))
    reply, sql = await pipeline.answer_question("how many players ever", 1, [], [], deps, thread_id=42)
    assert "confirm" in reply
    deps.backend.execute.assert_not_called()
    pending = thread_store.get_pending_query(conn, 42)
    assert pending == {"question": "how many players ever", "sql": "SELECT COUNT(*) FROM big"}


@pytest.mark.asyncio
async def test_run_pending_query_executes_without_regenerating_or_cost_checking(monkeypatch):
    def _explode(*args, **kwargs):
        raise AssertionError("a confirmed query must not be regenerated or re-cost-checked")

    monkeypatch.setattr(pipeline.generate, "understand_and_generate", _explode)
    monkeypatch.setattr(pipeline, "check_cost", _explode)
    monkeypatch.setattr(pipeline.confidence_mod, "score_confidence", lambda q, sql, c: ConfidenceResult(confident=True))
    monkeypatch.setattr(pipeline.confidence_mod, "score_risk", lambda sql: False)
    monkeypatch.setattr(pipeline.answer_mod, "format_answer", lambda q, rows, note, c: "4213 players.")

    deps = _deps()
    reply, sql = await pipeline.run_pending_query("how many players ever", "SELECT COUNT(*) FROM big", deps)
    assert reply == "4213 players."
    assert sql == "SELECT COUNT(*) FROM big"
    deps.backend.execute.assert_called_once_with("SELECT COUNT(*) FROM big")
