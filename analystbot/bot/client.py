import discord
from analystbot.bot.routing import classify_message, dispatch, MessageKind
from analystbot.storage import threads as thread_store
from analystbot.storage import config_store


class AnalystBot(discord.Client):
    def __init__(self, *, conn, backend, dataset_path, anthropic_client, cost_threshold_bytes,
                 handle_new_question, handle_followup, handle_onboarding, **kwargs):
        super().__init__(**kwargs)
        self.conn = conn
        self.backend = backend
        self.dataset_path = dataset_path
        self.anthropic_client = anthropic_client
        self.cost_threshold_bytes = cost_threshold_bytes
        self._handlers = {
            MessageKind.NEW_QUESTION: handle_new_question,
            MessageKind.THREAD_FOLLOWUP: handle_followup,
        }
        self._handle_onboarding = handle_onboarding

    @staticmethod
    async def route_message(message, handlers: dict, *, is_bot_author: bool, mentions_bot: bool,
                             is_thread: bool, thread_started_by_bot: bool) -> None:
        kind = classify_message(
            is_bot_author=is_bot_author, mentions_bot=mentions_bot,
            is_thread=is_thread, thread_started_by_bot=thread_started_by_bot,
        )
        await dispatch(kind, message, handlers)

    async def on_message(self, message: discord.Message) -> None:
        if self.user is None or message.author == self.user:
            return
        is_thread = isinstance(message.channel, discord.Thread)
        thread_started_by_bot = bool(thread_store.get_thread_context(self.conn, message.channel.id)) if is_thread else False
        mentions_bot = self.user in message.mentions

        handlers = dict(self._handlers)
        if config_store.get_digest_channel(self.conn) is None:
            handlers[MessageKind.NEW_QUESTION] = self._handle_onboarding

        await self.route_message(
            message, handlers,
            is_bot_author=bool(getattr(message.author, "bot", False)), mentions_bot=mentions_bot,
            is_thread=is_thread, thread_started_by_bot=thread_started_by_bot,
        )
