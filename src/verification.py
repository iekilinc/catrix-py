from datetime import datetime
from typing import Type, Callable, Awaitable
from dataclasses import dataclass
import simplematrixbotlib as botlib
import nio
import jsonschema
import jsonschema.exceptions
import traceback
from auth import Credentials


type LogFn = Callable[[str], None]
type EventType = nio.ToDeviceEvent | KeyVerificationRequest | KeyVerificationDone
type EventHandler[Ev: EventType] = Callable[[Ev, LogFn], Awaitable[None]]
type InternalEventHandler[Ev: EventType] = Callable[[Ev], Awaitable[None]]


def print_timestamped(msg=""):
    print(f"{datetime.now().isoformat()}: {msg}")


def make_log_fn(event: EventType) -> LogFn:
    def log(msg: str):
        print_timestamped(f"From <{event.sender}>: {event.__class__.__name__}: {msg}")

    return log


def with_logger[Ev: EventType](event_type: Type[Ev]):
    def decorate(callback: EventHandler[Ev]) -> InternalEventHandler[Ev]:
        async def wrapper(event: Ev) -> None:
            log = make_log_fn(event)
            await callback(event, log)

        return wrapper

    return decorate


def with_logs[Ev: EventType](event_type: Type[Ev]):
    def decorate(callback: EventHandler[Ev]) -> EventHandler[Ev]:
        async def wrapper(event: Ev, log: LogFn) -> None:
            log("Handling event...")
            try:
                await callback(event, log)
                log("Done")
            except Exception as e:
                log("Done: ERROR: Exception while handling event:")
                traceback.print_exception(e)

        return wrapper

    return decorate


def with_allowed_sender_only[Ev: EventType](event_type: Type[Ev], creds: Credentials):
    def decorate(callback: EventHandler[Ev]) -> EventHandler[Ev]:
        async def wrapper(event: Ev, log: LogFn) -> None:
            if event.sender not in creds.allowed_command_users:
                log("User is not in the list of allowed command users. Ignoring event.")
                return

            log("Received event from an allowed command user.")
            await callback(event, log)

        return wrapper

    return decorate


def safe_handler[Ev: EventType](event_type: Type[Ev], creds: Credentials):
    def decorate(callback: EventHandler[Ev]) -> InternalEventHandler[Ev]:
        @with_logger(event_type)
        @with_logs(event_type)
        @with_allowed_sender_only(event_type, creds)
        async def wrapper(event: Ev, log: LogFn) -> None:
            await callback(event, log)

        return wrapper

    return decorate


def register_handler[Ev: nio.ToDeviceEvent](
    event_type: Type[Ev], bot: botlib.Bot, handler: InternalEventHandler[Ev]
):
    bot.async_client.add_to_device_callback(
        handler,  # type: ignore
        (event_type,),
    )


key_verification_request_schema = {
    "type": "object",
    "properties": {
        "type": {"constant": "m.key.verification.request"},
        "content": {
            "type": "object",
            "properties": {
                "from_device": {"type": "string"},
                "methods": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "timestamp": {"type": "number"},
                "transaction_id": {"type": "string"},
            },
        },
    },
}


@dataclass
class KeyVerificationRequest:
    base: nio.UnknownToDeviceEvent
    from_device: str
    methods: list[str]
    timestamp: int
    transaction_id: str

    @property
    def sender(self):
        return self.base.sender


key_verification_done_schema = {
    "type": "object",
    "properties": {
        "type": {"constant": "m.key.verification.done"},
        "content": {
            "type": "object",
            "properties": {
                "transaction_id": {"type": "string"},
            },
        },
    },
}


@dataclass
class KeyVerificationDone:
    base: nio.UnknownToDeviceEvent
    transaction_id: str

    @property
    def sender(self):
        return self.base.sender


# Inspired by https://github.com/matrix-nio/matrix-nio/blob/706597708eb109e763d7537d30bed97533f958b0/examples/verify_with_emoji.py and https://github.com/wreald/matrix-nio/commit/5cb8e99965bcb622101b1d6ad6fa86f5a9debb9a
# Related: https://github.com/matrix-nio/matrix-nio/issues/430
def register_emoji_verification(bot: botlib.Bot, creds: Credentials):
    def register[Ev: nio.ToDeviceEvent](event_type: Type[Ev]):
        def decorate(callback: EventHandler[Ev]) -> None:
            handler = safe_handler(event_type, creds)(callback)
            register_handler(event_type, bot, handler)

        return decorate

    @safe_handler(KeyVerificationRequest, creds)
    async def on_key_verification_request(
        event: KeyVerificationRequest, log: LogFn
    ) -> None:
        if "m.sas.v1" not in event.methods:
            log("Sender does not support SAS v1 verification")
            return

        assert bot.async_client.device_id is not None

        ready_msg = nio.ToDeviceMessage(
            type="m.key.verification.ready",
            recipient=event.sender,
            recipient_device=event.from_device,
            content={
                "from_device": bot.async_client.device_id,
                "methods": ["m.sas.v1"],
                "transaction_id": event.transaction_id,
            },
        )
        log("Sending m.key.verification.ready event...")
        ready_resp = await bot.async_client.to_device(ready_msg, event.transaction_id)
        if isinstance(ready_resp, nio.ToDeviceError):
            log(f"Failed to send ready event: {ready_resp}")
            return
        log("Sent ready event.")
        log("Request/ready step executed successfully.")

    @register(nio.KeyVerificationStart)
    async def on_key_verification_start(
        event: nio.KeyVerificationStart, log: LogFn
    ) -> None:
        if "emoji" not in event.short_authentication_string:
            log("Sender's device does not support emoji verification.")
            return

        accept_resp = await bot.async_client.accept_key_verification(
            event.transaction_id
        )
        if isinstance(accept_resp, nio.ToDeviceError):
            log(f"Failed to accept key verification: {accept_resp}")
            return

        sas = bot.async_client.key_verifications[event.transaction_id]

        to_device_msg = sas.share_key()
        msg_resp = await bot.async_client.to_device(to_device_msg)
        if isinstance(msg_resp, nio.ToDeviceError):
            log(f"Failed to share key with sender: {msg_resp}")
            return

        log("Stage executed successfully.")

    @register(nio.KeyVerificationCancel)
    async def on_key_verification_cancel(
        event: nio.KeyVerificationCancel, log: LogFn
    ) -> None:
        log(f"Canceled by {event.sender}. Reason: {event.reason}")
        try:
            bot.async_client.key_verifications.pop(event.transaction_id)
        except KeyError:
            return

    @register(nio.KeyVerificationKey)
    async def on_key_verification_key(
        event: nio.KeyVerificationKey, log: LogFn
    ) -> None:
        sas = bot.async_client.key_verifications[event.transaction_id]

        log(f"{sas.get_emoji()}")
        while True:
            answer = input("Do the emoji match? (y/n/cancel): ").strip().lower()
            if answer == "y":
                log("Confirming...")
                confirm_resp = await bot.async_client.confirm_short_auth_string(
                    event.transaction_id
                )
                if isinstance(confirm_resp, nio.ToDeviceError):
                    log(f"Confirmation failed: {confirm_resp}")
                    return
                log("Sent confirmation message.")

                done_msg = nio.ToDeviceMessage(
                    type="m.key.verification.done",
                    recipient=event.sender,
                    recipient_device=sas.other_olm_device.device_id,
                    content={
                        "transaction_id": sas.transaction_id,
                    },
                )
                log("Sending done event...")
                done_resp = await bot.async_client.to_device(
                    done_msg, sas.transaction_id
                )
                if isinstance(done_resp, nio.ToDeviceError):
                    log(f"Failed to send done event: {done_resp}")
                    return
                log("Sent done event.")
                log("Confirmation stage executed successfully")

            elif answer == "n":
                log("Rejecting...")
                reject_resp = await bot.async_client.cancel_key_verification(
                    event.transaction_id, reject=True
                )
                if isinstance(reject_resp, nio.ToDeviceError):
                    log(f"Error during rejection: {reject_resp}")
                else:
                    log("Rejected verification.")

            elif answer == "cancel":
                log("Canceling...")
                cancel_resp = await bot.async_client.cancel_key_verification(
                    event.transaction_id, reject=False
                )
                if isinstance(cancel_resp, nio.ToDeviceError):
                    log(f"Error during cancellation: {cancel_resp}")
                else:
                    log("Canceled verification.")

            else:
                continue

            break

    @register(nio.KeyVerificationMac)
    async def on_key_verification_mac(
        event: nio.KeyVerificationMac, log: LogFn
    ) -> None:
        sas = bot.async_client.key_verifications[event.transaction_id]

        try:
            to_device_msg = sas.get_mac()
        except nio.LocalProtocolError as e:
            log(f"Canceled or local protocol error: {e}")
            return

        mac_resp = await bot.async_client.to_device(to_device_msg)
        if isinstance(mac_resp, nio.ToDeviceError):
            log(f"Failed to send key verification mac: {mac_resp}")
            return

        log("Mac stage executed successfully")

    @safe_handler(KeyVerificationDone, creds)
    async def on_key_verification_done(event: KeyVerificationDone, log: LogFn) -> None:
        log(f"Emoji verification concluded: Transaction ID: {event.transaction_id}")

    @register(nio.UnknownToDeviceEvent)
    async def on_unknown_event(event: nio.UnknownToDeviceEvent, log: LogFn) -> None:
        if event.source["type"] == "m.key.verification.request":
            try:
                jsonschema.validate(event.source, key_verification_request_schema)
            except jsonschema.exceptions.ValidationError as e:
                log(f"Invalid key verification request payload: {e}")
                return

            request_event = KeyVerificationRequest(
                base=event,
                from_device=event.source["content"]["from_device"],
                methods=event.source["content"]["methods"],
                timestamp=event.source["content"]["timestamp"],
                transaction_id=event.source["content"]["transaction_id"],
            )
            await on_key_verification_request(request_event)

        elif event.source["type"] == "m.key.verification.done":
            try:
                jsonschema.validate(event.source, key_verification_done_schema)
            except jsonschema.exceptions.ValidationError as e:
                log(f"Invalid key verification done payload: {e}")
                return

            done_event = KeyVerificationDone(
                base=event,
                transaction_id=event.source["content"]["transaction_id"],
            )
            await on_key_verification_done(done_event)

        else:
            log(f"Unhandled event type {event.source['type']}")
