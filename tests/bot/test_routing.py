import pytest
from unittest.mock import AsyncMock
from analystbot.bot.routing import classify_message, dispatch, MessageKind


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
