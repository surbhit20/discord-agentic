import pytest
from unittest.mock import AsyncMock
from analystbot.bot.routing import classify_message, dispatch, strip_bot_mention, MessageKind


def test_bot_message_is_ignored():
    assert classify_message(is_bot_author=True, mentions_bot=True, is_thread=False, thread_started_by_bot=False) == MessageKind.IGNORE


def test_mention_outside_thread_is_new_question():
    assert classify_message(is_bot_author=False, mentions_bot=True, is_thread=False, thread_started_by_bot=False) == MessageKind.NEW_QUESTION


def test_plain_message_in_bot_thread_is_followup():
    assert classify_message(is_bot_author=False, mentions_bot=False, is_thread=True, thread_started_by_bot=True) == MessageKind.THREAD_FOLLOWUP


def test_plain_message_in_other_thread_is_ignored():
    assert classify_message(is_bot_author=False, mentions_bot=False, is_thread=True, thread_started_by_bot=False) == MessageKind.IGNORE


def test_unrelated_channel_message_is_ignored():
    assert classify_message(is_bot_author=False, mentions_bot=False, is_thread=False, thread_started_by_bot=False) == MessageKind.IGNORE


@pytest.mark.asyncio
async def test_dispatch_calls_matching_handler():
    new_question_handler = AsyncMock()
    handlers = {MessageKind.NEW_QUESTION: new_question_handler, MessageKind.THREAD_FOLLOWUP: AsyncMock()}
    message = object()
    await dispatch(MessageKind.NEW_QUESTION, message, handlers)
    new_question_handler.assert_awaited_once_with(message)


@pytest.mark.asyncio
async def test_dispatch_ignores_unmapped_kind():
    await dispatch(MessageKind.IGNORE, object(), {})


def test_strip_bot_mention_removes_the_bots_own_mention():
    assert strip_bot_mention("<@1234567890> confirm", 1234567890) == "confirm"


def test_strip_bot_mention_handles_the_legacy_nickname_form():
    assert strip_bot_mention("<@!1234567890> how many players", 1234567890) == "how many players"


def test_strip_bot_mention_removes_a_trailing_or_embedded_mention():
    assert strip_bot_mention("how many players <@1234567890> started level 3", 1234567890) == (
        "how many players started level 3"
    )
    assert strip_bot_mention("confirm <@1234567890>", 1234567890) == "confirm"


def test_strip_bot_mention_leaves_other_users_mentions_alone():
    assert strip_bot_mention("<@1234567890> ask <@999> about it", 1234567890) == "ask <@999> about it"


def test_strip_bot_mention_without_a_known_id_strips_every_mention():
    # Before login the client has no user id; leaving a raw token in the text would
    # break the confirm check and pollute the question sent to Claude.
    assert strip_bot_mention("<@1234567890> confirm", None) == "confirm"


def test_strip_bot_mention_on_plain_text_is_a_no_op():
    assert strip_bot_mention("what about level 5", 1234567890) == "what about level 5"
    assert strip_bot_mention("", 1234567890) == ""
