import re
from enum import Enum
from typing import Awaitable, Callable

# discord.py leaves mention tokens in `message.content` verbatim: "<@123>" (or the
# legacy nickname form "<@!123>"). Every question therefore arrives with the bot's own
# mention embedded in it, which has to come off before the text is treated as the
# question, the thread name, or a "confirm" check.
_ANY_MENTION = re.compile(r"<@!?\d+>")
_HORIZONTAL_RUNS = re.compile(r"[ \t]{2,}")


class MessageKind(Enum):
    NEW_QUESTION = "new_question"
    THREAD_FOLLOWUP = "thread_followup"
    IGNORE = "ignore"


def strip_bot_mention(content: str, bot_user_id: int | None) -> str:
    """Return `content` with the bot's own mention token(s) removed.

    When `bot_user_id` is unknown (the client isn't logged in yet), every user mention
    is stripped instead — the alternative is leaving a raw "<@123>" in the text that
    then gets compared against "confirm" or sent to Claude as the question.
    """
    pattern = _ANY_MENTION if bot_user_id is None else re.compile(rf"<@!?{int(bot_user_id)}>")
    stripped = pattern.sub(" ", content or "")
    return _HORIZONTAL_RUNS.sub(" ", stripped).strip()


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
