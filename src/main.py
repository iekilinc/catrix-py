import asyncio
from http.client import responses
import os
import sys
import traceback
import aiohttp
from datetime import datetime
import nio
from typing import Any
from options import resolve_options
from verification import register_emoji_verification
from yandere import YandeRe
from booru import Booru, ReceivedZeroPostsError, InvalidPostJsonError
import simplematrixbotlib as botlib

CREDENTIALS_JSON_PATH = os.path.abspath("credentials.json")

BASE_DIR = os.path.abspath("session")
STORE_DIR = os.path.join(BASE_DIR, "store")
AUTH_PATH = os.path.join(BASE_DIR, "auth.txt")

# If a message starts with this string, do not respond to the command.
# Prepend this prefix to text messages sent by this bot.
bot_message_prefix = "[]"
catgirl_id_counter = 0


def print_timestamped(msg: str):
    print(f"{datetime.now().isoformat()}: {msg}")


async def log_bad_response(resp: aiohttp.ClientResponse):
    print_timestamped("Response:")
    print_timestamped(f"\tStatus: {resp.status} {responses[resp.status]}")
    try:
        message = await resp.text()
        print_timestamped(f"\tBody: {message}")
    except Exception:
        pass


async def make_bot() -> botlib.Bot:
    ensure_directory(BASE_DIR)
    ensure_directory(STORE_DIR)

    # Creds
    options = await resolve_options(
        options_json_path=CREDENTIALS_JSON_PATH,
        auth_txt_path=AUTH_PATH,
        allow_interactive=True,
    )
    if options is None:
        raise Exception("Could not resolve credentials")

    # Config
    config = botlib.Config()
    config.join_on_invite = False
    config.encryption_enabled = True
    config.ignore_unverified_devices = True
    config.store_path = STORE_DIR
    # Doesn't even work
    config.emoji_verify = False

    # Client
    bot = botlib.Bot(options.botlib_creds(), config)

    running_tasks = set[asyncio.Task[None]]()

    trigger_words = (
        "!catgirl",
        "!cg",
        ":3",
        "uwu",
        "ugu",
        "catgirl",
        "neko",
        "nekomimi",
        "mimi",
        "mimir",
        "i'm a cat",
        "im a cat",
        "im a catgirl",
        "you're a catgirl",
        "youre a catgirl",
        "neko neko",
        "nyaa",
        "nyaa~",
    )

    booru = YandeRe(options.default_rating, print_timestamped)

    @bot.listener.on_message_event  # type: ignore
    async def on_message(room: nio.MatrixRoom, message: nio.RoomMessageText):
        print_message(message, room)
        # Reply only to commands send by allowed command users
        if message.sender not in options.allowed_command_users:
            return
        # The message was sent by this bot, so ignore it
        if message.body.startswith(bot_message_prefix):
            return

        body = message.body.strip().lower()

        if body == "!cp":
            # Reply with scolding message and exit
            try:
                await bot.api.send_text_message(
                    room_id=room.room_id,
                    message="...\ni'm just going to trust that you misspelled '!cg'",
                    reply_to=message.event_id,
                )
                print("Sent scolding message")
            except Exception as e:
                print("Could not send scolding message")
                traceback.print_exception(e)
            return

        if body not in trigger_words:
            return
        try:
            global catgirl_id_counter
            catgirl_id = catgirl_id_counter
            catgirl_id_counter += 1

            event_loop = asyncio.get_running_loop()
            task = event_loop.create_task(
                serve_catgirl(booru, bot, room, message.event_id, catgirl_id)
            )
            running_tasks.add(task)
            task.add_done_callback(running_tasks.discard)
            # await serve_catgirl(bot, room, message.event_id)
        except Exception as e:
            print_timestamped("Could not serve catgirl")
            traceback.print_exception(e)

    @bot.listener.on_startup  # type: ignore
    async def on_startup(s):
        print_timestamped(f"Bot started up: {s}")
        register_emoji_verification(bot, options)

    return bot


async def serve_catgirl(
    booru: Booru,
    bot: botlib.Bot,
    room: nio.MatrixRoom,
    in_reply_to: str,
    catgirl_id: int,
):
    def log(message=""):
        print_timestamped(f"Catgirl {catgirl_id}: {message}")

    log("Called serve_catgirl")
    async with aiohttp.ClientSession() as session:
        post_json: Any

        get_url = booru.get_random_post()
        log(f"GET {get_url}")
        async with session.get(get_url) as resp:
            if resp.status != 200:
                log("Bad response")
                await log_bad_response(resp)
                log("No catgirl...")
                return

            # Decode JSON body
            try:
                post_json = await resp.json()
            except Exception as e:
                log(f"Failed to decode JSON: {e}")
                return
            log("Decoded JSON response body")

        image = booru.parse_post_json(post_json)
        if isinstance(image, ReceivedZeroPostsError):
            log(
                f"Got 0 catgirls?\n\tResponse JSON: {post_json}\n\tResponse: {resp}\n\tError: {image}",
            )
            await bot.api.send_text_message(
                room_id=room.room_id,
                message=f"{bot_message_prefix} no catgirl for you this time :3\n"
                "whatcha gonna do? pounce on me???? >.<",
                reply_to=in_reply_to,
            )
            return
        elif isinstance(image, InvalidPostJsonError):
            log(f"Invalid post JSON: {image}")
            return

        log(f"GET {image.url}")
        async with session.get(image.url) as resp:
            if resp.status != 200:
                log("Bad response")
                await log_bad_response(resp)
                log("No catgirl...")
                return

            # Upload image
            log("Downloading image from booru and uploading it to matrix")
            file_size = resp.content_length
            if file_size is None:
                file_size = image.file_size

            upload_resp, img_keys = await bot.async_client.upload(
                lambda a, b: resp.content,
                encrypt=True,
                content_type=image.mime_type,
                filesize=file_size,
            )

    if isinstance(upload_resp, nio.UploadError):
        log(f"Image upload failed: {upload_resp}\nNo catgirl...")
        return
    if img_keys is None:
        log("Cryptographic information missing\nNo catgirl...")
        return

    log("Image uploaded")

    msg_content = {
        "body": f"{bot_message_prefix} catgirl by {image.author}: {image.post_url}",
        "filename": image.filename,
        "info": {
            "size": file_size,
            "mimetype": image.mime_type,
            "thumbnail_info": None,
            "thumbnail_url": None,
            "w": image.width,
            "h": image.height,
        },
        "msgtype": "m.image",
        "file": {
            "url": upload_resp.content_uri,
            "v": img_keys["v"],
            "key": img_keys["key"],
            "iv": img_keys["iv"],
            "hashes": img_keys["hashes"],
        },
        "m.relates_to": {
            "m.in_reply_to": {
                "event_id": in_reply_to,
            },
        },
    }

    # Send message
    try:
        log("Sending message with the catgirl image attached")
        await bot.api._send_room(
            room_id=room.room_id,
            content=msg_content,
        )
        log("Cat served :3\n")
    except Exception as e:
        log(f"Could not send message: {e}\nNo catgirl...")
        traceback.print_exception(e)
        return


def print_message(message: nio.RoomMessageText, room: nio.MatrixRoom):
    symbol = "🛡" if message.decrypted else "⚠️"
    print_timestamped(
        f"{symbol} ({room.display_name}) <{room.user_name(message.sender)}> {message.body}"
    )


def ensure_directory(path: str) -> None:
    if not os.path.exists(path):
        os.mkdir(path)
        print_timestamped(f"Created directory at {path}")
        return

    if os.path.isdir(path):
        print_timestamped(f"Directory already exists at {path}")
    else:
        raise Exception(f"Existing path is not a directory: {path}")


if __name__ == "__main__":
    try:
        loop = asyncio.get_event_loop()
        bot = loop.run_until_complete(make_bot())
        bot.run()
    except InterruptedError as e:
        print_timestamped(f"Shutting down due to interrupt signal: {e}")
    except Exception as e:
        print_timestamped("Shutting down due to irrecoverable error")
        traceback.print_exception(e)
        sys.exit(1)
    finally:
        print_timestamped(f"{catgirl_id_counter} catgirls served on this run")
