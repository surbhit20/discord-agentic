from enum import Enum
from typing import Awaitable, Callable


class MessageKind(Enum):
    NEW_QUESTION = "new_question"
    THREAD_FOLLOWUP = "thread_followup"
    IGNORE = "ignore"


def classify_message(is_bot_author: bool, mentions_bot: bool, is_thread: bool, thread_started_by_bot: bool) -> MessageKind:
    if is_bot_author:
        return MessageKind.IGNORE
    if is_thread and thread_started_by_bot:
        return MessageKind.THREAD_FOLLOWUP
    if mentions_bot and not is_thread:
        return MessageKind.NEW_QUESTION
    return MessageKind.IGNORE


async def dispatch(kind: MessageKind, message, handlers: dict[MessageKind, Callable[[object], Awaitable[None]]]) -> None:
    handler = handlers.get(kind)
    if handler:
        await handler(message)
