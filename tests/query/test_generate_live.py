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


def test_unanswerable_question_is_refused_with_reason():
    result = understand_and_generate(
        "what is the average session length in seconds", FLOOD_IT_SCHEMA, [], [], _DATASET_PATH, _client()
    )
    assert result.outcome == QuestionOutcome.REFUSAL
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
