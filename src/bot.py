import simplematrixbotlib as botlib
from nio import MatrixRoom, Event as RoomEvent, ToDeviceEvent, RoomMessageText
from typing import Type, Callable, Awaitable, Any, Optional
from datetime import datetime
from asyncio import get_event_loop, sleep, TaskGroup

from options import Options
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


class Bot:
    _options: Options
    _log: LogFn
    _lib_bot: botlib.Bot
    _booru: Booru
    _command_id_counter: IdCounter
    _ran_startup: bool = False

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

    def _add_room_event_callback[Ev: RoomEvent](
        self,
        event_type: Type[Ev],
        event_handler: EventHandler[Ev],
    ):
        self._client.add_event_callback(
            event_handler,  # type: ignore
            event_type,
        )

        self._handle_text_message

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
        if parsed_command is None:
            self._log(message_log)
            return

        command_id = self._command_id_counter.acquire_new_id()
        command = Command(
            parsed=parsed_command,
            command_id=command_id,
            message_id=message.event_id,
            room_id=room.room_id,
            bot=self,
        )
        command.log(message_log)

        await command.respond()
