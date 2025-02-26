import simplematrixbotlib as botlib
from nio import MatrixRoom, Event as RoomEvent, ToDeviceEvent, RoomMessageText
from typing import Type, Callable, Awaitable, Any, Optional
from datetime import datetime
from asyncio import get_event_loop, sleep, TaskGroup
from ollama import AsyncClient as OllamaAsyncClient, Options as ChatOptions
import re


from options import Options, Ollama as OllamaOptions
from command import ParsedCommand, Command
from booru import Booru
from yandere import YandeRe
from verification import register_emoji_verification

type LogFn = Callable[[str], None]
type EventHandler[Ev: RoomEvent] = Callable[
    [MatrixRoom, Ev],
    Awaitable[None],
]
type ToDeviceEventHandler[Ev: ToDeviceEvent] = Callable[
    [MatrixRoom, Ev],
    Awaitable[None],
]


def default_log(message: str) -> None:
    print(f"{datetime.now().isoformat()}: Bot: {message}")


def make_concurrent[Fn: Callable[..., Awaitable[Any]]](func: Fn) -> Fn:
    def wrapped(*args, **kwargs):
        get_event_loop().create_task(func(*args, **kwargs))  # type: ignore

    return wrapped  # type: ignore


class IdCounter:
    _counter: int = 0

    def acquire_new_id(self) -> int:
        new_id = self._counter
        self._counter += 1
        return new_id


class Ollama:
    options: OllamaOptions
    client: OllamaAsyncClient
    past_messages: dict[str, list[RoomMessageText]]
    prompt_id_counter: IdCounter
    ingore_prefix: str
    reply_regex: re.Pattern[str]

    def __init__(self, options: OllamaOptions, client: OllamaAsyncClient) -> None:
        self.options = options
        self.client = client
        self.past_messages = dict()
        self.done_pulling_model = False
        self.prompt_id_counter = IdCounter()
        self.ingore_prefix = "\N{ZERO WIDTH SPACE}"

        bot_name = re.escape(options.bot_name)
        self.reply_regex = re.compile(bot_name, re.IGNORECASE)


class Bot:
    _options: Options
    _log: LogFn
    _lib_bot: botlib.Bot
    _booru: Booru
    _command_id_counter: IdCounter
    _ran_startup: bool = False
    _ollama: Optional[Ollama]
    # _past_messages: dict[str, list[RoomMessageText]] = dict()
    # _ollama: Optional[OllamaAsyncClient]

    @property
    def _client(self):
        return self._lib_bot.async_client

    def __init__(self, options: Options, log: Optional[LogFn] = None):
        self._options = options
        self._log = default_log if log is None else log
        self._command_id_counter = IdCounter()

        # Initialize _lib_bot
        config = botlib.Config()
        config.join_on_invite = False
        config.encryption_enabled = True
        config.ignore_unverified_devices = True
        config.store_path = options.paths.store_dir
        # Doesn't work
        config.emoji_verify = False

        self._lib_bot = botlib.Bot(options.botlib_creds(), config)
        # The callback must be async but the typing says it must not be async...
        self._lib_bot.listener.on_startup(self._on_startup)  # type: ignore

        # Initialize _booru
        def booru_log(message: str):
            self._log(f"YandeRe: {message}")

        self._booru = YandeRe(default_rating=options.default_rating, log=booru_log)

    async def amain(self) -> None:
        async with TaskGroup() as tg:
            tg.create_task(self._lib_bot.main())
            tg.create_task(self._ensure_on_startup_runs())

    async def _on_startup(self, source: str) -> None:
        if self._ran_startup:
            return
        self._ran_startup = True
        self._log(f"Startup: Signal received: {source}")

        self._register_event_handlers()
        self._log("Startup: Event handlers registered")

        if self._options.ollama is not None:
            ollama_task = self._initialize_ollama(self._options.ollama)
            get_event_loop().create_task(ollama_task)

    def _add_room_event_callback[Ev: RoomEvent](
        self,
        event_type: Type[Ev],
        event_handler: EventHandler[Ev],
    ):
        self._client.add_event_callback(
            event_handler,  # type: ignore
            event_type,
        )

    # def _add_to_device_callback[Ev: ToDeviceEvent](
    #     self,
    #     event_type: Type[Ev],
    #     event_handler: ToDeviceEventHandler[Ev],
    # ):
    #     pass

    def _register_event_handlers(self) -> None:
        self._add_room_event_callback(RoomMessageText, self._handle_text_message)
        register_emoji_verification(self._lib_bot, self._options)

    async def _ensure_on_startup_runs(self) -> None:
        timeous_sec = 40
        await sleep(timeous_sec)
        await self._on_startup("_ensure_on_startup_runs")

    # Receive text message

    @make_concurrent
    async def _handle_text_message(
        self,
        room: MatrixRoom,
        message: RoomMessageText,
    ) -> None:
        if not room.encrypted:
            # Don't operate in unencrypted rooms.
            return None

        if message.sender not in self._options.allowed_command_users:
            # The sender is not the the list of users who are allowed to use
            # this bot.
            return
        verification_symbol = "🛡" if message.decrypted else "⚠️"
        message_log = f"{verification_symbol} ({room.display_name}) <{room.user_name(message.sender)}> {message.body!r}"

        parsed_command = ParsedCommand.parse_message(message)

        if parsed_command is not None:
            command_id = self._command_id_counter.acquire_new_id()
            command = Command(
                parsed=parsed_command,
                command_id=command_id,
                message_id=message.event_id,
                room_id=room.room_id,
                bot=self,
            )
            command.log(message_log)

            return await command.respond()

        self._log(message_log)

        if self._ollama is not None:
            did_handle = await self._handle_ollama(
                room,
                message,
            )
            if did_handle:
                return

    async def _initialize_ollama(self, options: OllamaOptions):
        self._log("Startup: Initializing Ollama")

        ollama_client = OllamaAsyncClient(host="http://ollama:11434")
        self._ollama = Ollama(
            options=options,
            client=ollama_client,
        )

        model = self._ollama.options.model

        async for progress in await ollama_client.pull(model=model, stream=True):
            message = f"Startup: Pulling model {model}"
            if progress.completed is not None and progress.total is not None:
                message = f"{message}: {progress.completed}/{progress.total}"

        self._log("Startup: Done pulling model")
        self._ollama.done_pulling_model = True

    async def _handle_ollama(self, room: MatrixRoom, message: RoomMessageText) -> bool:
        assert self._ollama is not None
        ollama = self._ollama

        key = room.room_id
        if key not in ollama.past_messages:
            ollama.past_messages[key] = []

        past_messages_ref = ollama.past_messages[key]

        # Add this message to history.
        past_messages_ref.append(message)

        # Remove past messages if over history limit.
        assert ollama.options.last_n_messages >= 1
        while len(past_messages_ref) > ollama.options.last_n_messages:
            past_messages_ref.pop(0)

        # Make a copy for this prompt only.
        past_messages = past_messages_ref.copy()

        if not ollama.done_pulling_model:
            # We can't prompt until the model has been pulled.
            return False

        if message.body.startswith(ollama.ingore_prefix):
            # Prevent self-response loops.
            return False

        if ollama.reply_regex.search(message.body) is None:
            # The bot was not prompted.
            return False

        # The bot was prompted.
        prompt_id = ollama.prompt_id_counter.acquire_new_id()

        def log(msg: str) -> None:
            self._log(f"Prompt {prompt_id}: {msg}")

        past_messages_str = ""
        for msg in past_messages:
            time = datetime.fromtimestamp(msg.server_timestamp / 1000)
            time_str = time.strftime("At %I:%M %p on %A, %B %d, %Y")

            past_messages_str += (
                f"\n{time_str} - user {room.user_name(msg.sender)} said: {msg.body!r}"
            )

        prompt = f"""
{ollama.options.prompt_prefix}
{past_messages_str}

Now, keep all of these messages in mind and respond directly to the very last message, producing human-readable output. Please provide a complete response within 60 tokens.
"""

        log(f"Sending prompt to Ollama: {prompt!r}")
        response = await ollama.client.chat(
            model=ollama.options.model,
            messages=[
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
            stream=False,
            options=ChatOptions(
                num_predict=120,
                temperature=ollama.options.temperature,
            ),
        )
        log(f"Got response: {response.model_dump_json(indent=2)}")

        response_message = response.message.content
        if response_message is None:
            log("ERROR: Got no message content from Ollama chat response")
            return True

        response_message = ollama.ingore_prefix + response_message

        await self._lib_bot.api.send_text_message(
            room_id=room.room_id,
            reply_to=message.event_id,
            message=response_message,
        )
        log("DONE:3 Responded to prompt")

        return True
