import os
import pytest
import anthropic
from tests.conftest import skip_unless_env
from analystbot.query.confidence import score_confidence

pytestmark = pytest.mark.live


def _client():
    skip_unless_env("ANTHROPIC_API_KEY")
    return anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


def test_confident_when_sql_clearly_matches_question():
    result = score_confidence(
        "how many level_start events happened", "SELECT COUNT(*) FROM events WHERE event_name = 'level_start'", _client()
    )
    assert result.confident is True


def test_not_confident_when_sql_makes_a_guessy_assumption():
    result = score_confidence(
        "how engaged are our players",
        "SELECT AVG(engagement_time_msec) FROM events WHERE event_name = 'user_engagement'",
        _client(),
    )
    assert result.confident is False
    assert result.reason
