import asyncio
from http.client import responses
import mimetypes
import os
import sys
import traceback
import aiohttp
from datetime import datetime
import nio
from urllib.parse import unquote
from auth import resolve_credentials
from verification import register_emoji_verification
import simplematrixbotlib as botlib

STORE_DIR = os.path.abspath("session/store")
# If a message starts with this string, do not respond to the command.
# Prepend this prefix to text messages sent by this bot.
bot_message_prefix = "[]"
catgirl_id_counter = 0


def print_timestamped(msg=""):
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
    # Creds
    creds = await resolve_credentials()
    if creds is None:
        raise Exception("Could not resolve credentials")
    # Session and store dirs
    initialize_session_dir()
    initialize_store_dir()
    # Config
    config = botlib.Config()
    config.join_on_invite = False
    config.encryption_enabled = True
    config.ignore_unverified_devices = True
    config.store_path = STORE_DIR
    # Doesn't even work
    config.emoji_verify = False

    # Client
    bot = botlib.Bot(creds.bot_creds, config)

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

    tags = ("order:random", "nekomimi")
    if not creds.options.nsfw:
        tags += ("-rating:e",)
    tags_str = "+".join(tags)

    @bot.listener.on_message_event  # type: ignore
    async def on_message(room: nio.MatrixRoom, message: nio.RoomMessageText):
        print_message(message, room)
        # Reply only to commands send by allowed command users
        if message.sender not in creds.options.allowed_command_users:
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
                serve_catgirl(bot, room, message.event_id, catgirl_id, tags_str)
            )
            running_tasks.add(task)
            task.add_done_callback(running_tasks.discard)
            # await serve_catgirl(bot, room, message.event_id)
        except Exception as e:
            print_timestamped("Could not serve catgirl")
            traceback.print_exception(e)

    @bot.listener.on_startup  # type: ignore
    async def on_startup(_s):
        register_emoji_verification(bot, creds)

    return bot


async def serve_catgirl(
    bot: botlib.Bot, room: nio.MatrixRoom, in_reply_to: str, catgirl_id: int, tags: str
):
    def log(message=""):
        print_timestamped(f"Catgirl {catgirl_id}: {message}")

    log("Called serve_catgirl")
    async with aiohttp.ClientSession() as session:
        get_url = f"https://yande.re/post.json?limit=1&tags={tags}"
        log(f"GET {get_url}")
        async with session.get(get_url) as resp:
            log("Got response of post description from yande.re")
            if resp.status != 200:
                log()
                await log_bad_response(resp)
                log("No catgirl...")
                return

            # Decode JSON body
            try:
                obj = await resp.json()
            except Exception as e:
                log(f"Failed to decode JSON: {e}")
                return
            log("Decoded JSON response body")

            # Sometimes, we get 0 catgirls for some reason
            if len(obj) == 0:
                log(f"Got 0 catgirls?\n\tResponse JSON: {obj}\n\tResponse: {resp}")
                await bot.api.send_text_message(
                    room_id=room.room_id,
                    message=f"{bot_message_prefix} no catgirl for you this time :3\n"
                    "whatcha gonna do? pounce on me???? >.<",
                    reply_to=in_reply_to,
                )
                return
            # Get the info we need out and leave the response
            post = obj[0]

        # Fetch the image
        img_url = str(post["sample_url"])
        img_mime = mimetypes.guess_type(img_url)[0]
        if img_mime is None:
            log(f"Could not guess mime type of image url: {img_url}. No catgirl...")
            return
        img_size = int(post["sample_file_size"])
        img_w = int(post["sample_width"])
        img_h = int(post["sample_height"])

        *_, tail = img_url.split("/")
        img_filename = unquote(tail)

        log(f"GET {img_url}")
        async with session.get(img_url) as resp:
            log("Got response with image from yande.re")
            if resp.status != 200:
                await log_bad_response(resp)
                log("No catgirl...")
                return

            # Upload image
            log("Uploading image to matrix")
            upload_resp, img_keys = await bot.async_client.upload(
                lambda a, b: resp.content,
                encrypt=True,
                content_type=img_mime,
                filesize=img_size
                if resp.content_length is None
                else resp.content_length,
            )
            if isinstance(upload_resp, nio.UploadError):
                log(f"Image upload failed: {upload_resp}\nNo catgirl...")
                return
            if img_keys is None:
                log("Cryptographic information missing\nNo catgirl...")
                return

            log("Image uploaded")

            msg_content = {
                "body": f"{bot_message_prefix} catgirl by {post['author']}: https://yande.re/post/show/{post['id']}",
                "filename": img_filename,
                "info": {
                    "size": img_size,
                    "mimetype": img_mime,
                    "thumbnail_info": None,
                    "thumbnail_url": None,
                    "w": img_w,
                    "h": img_h,
                },
                "msgtype": "m.image",
                # "file" is for encrypted
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


def initialize_session_dir() -> None:
    SESSION_DIR = os.path.abspath("session")
    if not os.path.exists(SESSION_DIR):
        os.mkdir(SESSION_DIR)
        print_timestamped(f"Created session directory at {SESSION_DIR}")
    else:
        if not os.path.isdir(SESSION_DIR):
            raise Exception(f"session ({SESSION_DIR}) exists but is not a directory")
        else:
            print_timestamped(f"Using existing session directory at {SESSION_DIR}")


def initialize_store_dir() -> None:
    if not os.path.exists(STORE_DIR):
        os.mkdir(STORE_DIR)
        print_timestamped(f"Created store directory at {STORE_DIR}")
    else:
        if not os.path.isdir(STORE_DIR):
            raise Exception(f"Store ({STORE_DIR}) exists but is not a directory")
        else:
            print_timestamped(f"Using existing store directory at {STORE_DIR}")


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
