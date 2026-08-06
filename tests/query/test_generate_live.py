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


def _client():
    skip_unless_env("ANTHROPIC_API_KEY")
    return anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


def test_answerable_question_produces_matching_sql():
    result = understand_and_generate("how many players started level 3", FLOOD_IT_SCHEMA, [], [], _client())
    assert result.outcome == QuestionOutcome.MATCH
    assert result.sql and "level_start" in result.sql


def test_unanswerable_question_is_refused_with_reason():
    result = understand_and_generate(
        "what is the average session length in seconds", FLOOD_IT_SCHEMA, [], [], _client()
    )
    assert result.outcome == QuestionOutcome.REFUSAL
    assert result.message


def test_nonsense_question_asks_for_clarification():
    result = understand_and_generate("how's the vibe economy doing", FLOOD_IT_SCHEMA, [], [], _client())
    assert result.outcome == QuestionOutcome.CLARIFY
    assert result.message


def test_stated_preference_is_accepted_without_breaking_a_normal_match():
    result = understand_and_generate(
        "what's our retention like", FLOOD_IT_SCHEMA, [], ["always show D7, not D1"], _client()
    )
    assert result.outcome in (QuestionOutcome.MATCH, QuestionOutcome.REFUSAL)
