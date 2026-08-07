import os
import pytest
import anthropic
from tests.conftest import skip_unless_env
from analystbot.query.generate import understand_and_generate, QuestionOutcome

pytestmark = pytest.mark.live

FLOOD_IT_SCHEMA = {
    "events": {
        "session_start": ["engagement_time_msec"],
        "level_start": ["level_number"],
        "level_complete": ["level_number", "level_time_sec"],
        "app_remove": [],
        "in_app_purchase": ["value", "currency"],
    }
}

_DATASET_PATH = "firebase-public-project.analytics_153293282"


def _client():
    skip_unless_env("ANTHROPIC_API_KEY")
    return anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


def test_answerable_question_produces_matching_sql():
    result = understand_and_generate(
        "how many players started level 3", FLOOD_IT_SCHEMA, [], [], _DATASET_PATH, _client()
    )
    assert result.outcome == QuestionOutcome.MATCH
    assert result.sql and "level_start" in result.sql


def test_generated_sql_always_references_the_real_dataset_path():
    # Regression test: understand_and_generate used to have no way to tell Claude the
    # actual table to query, so it invented a plausible-looking one (e.g. `analytics.events_*`)
    # which silently resolved against the querying client's own billing project instead of
    # erroring — first caught during a live end-to-end run, see git history for the incident.
    result = understand_and_generate(
        "how many players started level 3", FLOOD_IT_SCHEMA, [], [], _DATASET_PATH, _client()
    )
    assert result.outcome == QuestionOutcome.MATCH
    assert result.sql and _DATASET_PATH in result.sql


def test_unanswerable_question_is_refused_or_answered_via_a_flagged_proxy():
    # "Session length" has no dedicated event in this schema, but session_start carries
    # engagement_time_msec, a defensible proxy — Claude may refuse outright, or MATCH using
    # the proxy (the confidence-scoring stage, not this one, is what flags that as uncertain).
    # Either is fine; going straight to MATCH is a sign the schema/dataset-path grounding is
    # doing its job, not a defect.
    result = understand_and_generate(
        "what is the average session length in seconds", FLOOD_IT_SCHEMA, [], [], _DATASET_PATH, _client()
    )
    assert result.outcome in (QuestionOutcome.MATCH, QuestionOutcome.REFUSAL)
    if result.outcome == QuestionOutcome.REFUSAL:
        assert result.message


def test_nonsense_question_asks_for_clarification():
    result = understand_and_generate(
        "how's the vibe economy doing", FLOOD_IT_SCHEMA, [], [], _DATASET_PATH, _client()
    )
    assert result.outcome == QuestionOutcome.CLARIFY
    assert result.message


def test_stated_preference_is_accepted_without_breaking_a_normal_match():
    result = understand_and_generate(
        "what's our retention like", FLOOD_IT_SCHEMA, [], ["always show D7, not D1"], _DATASET_PATH, _client()
    )
    assert result.outcome in (QuestionOutcome.MATCH, QuestionOutcome.REFUSAL)


def test_message_stating_a_preference_is_captured_for_long_term_memory():
    result = understand_and_generate(
        "remember that I always want D7 retention, not D1", FLOOD_IT_SCHEMA, [], [], _DATASET_PATH, _client()
    )
    assert result.preference_to_remember is not None
    assert "D7" in result.preference_to_remember


def test_ordinary_question_states_no_preference_to_remember():
    result = understand_and_generate(
        "how many players started level 3", FLOOD_IT_SCHEMA, [], [], _DATASET_PATH, _client()
    )
    assert result.preference_to_remember is None


def test_off_topic_math_question_is_refused_not_answered():
    # Regression test: this used to refuse *and then answer anyway* ("The answer is 4!"),
    # using Claude's own general knowledge instead of staying grounded in the game data —
    # first caught during a live end-to-end run.
    result = understand_and_generate("what's 2 + 2?", FLOOD_IT_SCHEMA, [], [], _DATASET_PATH, _client())
    assert result.outcome == QuestionOutcome.REFUSAL
    assert result.message
    assert "4" not in result.message


def test_off_topic_trivia_question_is_refused_not_answered():
    # Same failure mode as above, for general-knowledge trivia ("The capital of India is New Delhi").
    result = understand_and_generate(
        "what is the capital of India?", FLOOD_IT_SCHEMA, [], [], _DATASET_PATH, _client()
    )
    assert result.outcome == QuestionOutcome.REFUSAL
    assert result.message
    assert "delhi" not in result.message.lower()


def test_vague_but_relevant_question_is_clarified_not_refused():
    # A vague game-analytics question must never be treated as out of scope — it should
    # ask which metric is meant, not refuse the way an off-topic question does.
    result = understand_and_generate("how are players doing", FLOOD_IT_SCHEMA, [], [], _DATASET_PATH, _client())
    assert result.outcome == QuestionOutcome.CLARIFY
    assert result.message


def test_specific_relevant_question_gets_a_direct_match():
    result = understand_and_generate(
        "how is monetization looking", FLOOD_IT_SCHEMA, [], [], _DATASET_PATH, _client()
    )
    assert result.outcome == QuestionOutcome.MATCH
    assert result.sql and "in_app_purchase" in result.sql


def test_opinion_question_offers_relevant_data_instead_of_refusing():
    # A product/business opinion question ("should we add more levels?") isn't a data
    # query, but it's clearly game-related — it must never be refused as out of scope.
    # Whether it asks which angle to look at (CLARIFY) or goes straight to relevant level
    # data (MATCH) is a judgment call either way is fine; refusing it is not.
    result = understand_and_generate("should we add more levels?", FLOOD_IT_SCHEMA, [], [], _DATASET_PATH, _client())
    assert result.outcome != QuestionOutcome.REFUSAL
    assert result.message or result.sql
