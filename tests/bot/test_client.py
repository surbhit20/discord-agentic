import pytest
from unittest.mock import AsyncMock
from analystbot.bot.routing import MessageKind
from analystbot.bot.client import AnalystBot


@pytest.mark.asyncio
async def test_route_message_dispatches_new_question_handler():
    handlers = {MessageKind.NEW_QUESTION: AsyncMock(), MessageKind.THREAD_FOLLOWUP: AsyncMock()}
    message = object()
    await AnalystBot.route_message(
        message, handlers,
        is_bot_author=False, mentions_bot=True, is_thread=False, thread_started_by_bot=False,
    )
    handlers[MessageKind.NEW_QUESTION].assert_awaited_once_with(message)
    handlers[MessageKind.THREAD_FOLLOWUP].assert_not_awaited()


@pytest.mark.asyncio
async def test_route_message_dispatches_followup_handler_in_bot_thread():
    handlers = {MessageKind.NEW_QUESTION: AsyncMock(), MessageKind.THREAD_FOLLOWUP: AsyncMock()}
    message = object()
    await AnalystBot.route_message(
        message, handlers,
        is_bot_author=False, mentions_bot=False, is_thread=True, thread_started_by_bot=True,
    )
    handlers[MessageKind.THREAD_FOLLOWUP].assert_awaited_once_with(message)
    handlers[MessageKind.NEW_QUESTION].assert_not_awaited()
