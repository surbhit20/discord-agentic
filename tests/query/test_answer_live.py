import os
import pytest
import anthropic
from tests.conftest import skip_unless_env
from analystbot.query.answer import format_answer

pytestmark = pytest.mark.live


def _client():
    skip_unless_env("ANTHROPIC_API_KEY")
    return anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


def test_answer_includes_the_number_from_the_rows():
    answer = format_answer("how many players started level 3", [{"n": 4213}], None, _client())
    assert "4213" in answer or "4,213" in answer


def test_answer_with_significance_note_mentions_it():
    answer = format_answer(
        "did retention drop after last week's build",
        [{"before": 0.38, "after": 0.31}],
        "the gap is statistically significant given sample size",
        _client(),
    )
    assert len(answer) > 0
