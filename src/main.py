import asyncio
import os
import sys
import traceback
from datetime import datetime
import simplematrixbotlib as botlib

from options import resolve_options, Paths
from bot import Bot

CREDENTIALS_JSON_PATH = os.path.abspath("credentials.json")

BASE_DIR = os.path.abspath("session")
STORE_DIR = os.path.join(BASE_DIR, "store")
AUTH_PATH = os.path.join(BASE_DIR, "auth.txt")


def print_timestamped(msg: str):
    print(f"{datetime.now().isoformat()}: {msg}")


def ensure_directory(path: str) -> None:
    if not os.path.exists(path):
        os.mkdir(path)
        print_timestamped(f"Created directory at {path}")
        return

    if os.path.isdir(path):
        print_timestamped(f"Directory already exists at {path}")
    else:
        raise Exception(f"Existing path is not a directory: {path}")


async def amain() -> None:
    ensure_directory(BASE_DIR)
    ensure_directory(STORE_DIR)

    # Options
    paths = Paths(
        auth_txt=AUTH_PATH,
        store_dir=STORE_DIR,
    )
    options = await resolve_options(
        options_json_path=CREDENTIALS_JSON_PATH,
        paths=paths,
        allow_interactive=True,
    )
    if options is None:
        raise Exception("Could not resolve credentials")

    bot = Bot(options)

    await bot.amain()


async def make_client(creds: botlib.Creds) -> botlib.Bot:
    ensure_directory(BASE_DIR)
    ensure_directory(STORE_DIR)

    paths = Paths(
        auth_txt=AUTH_PATH,
        store_dir=STORE_DIR,
    )
    # Creds
    options = await resolve_options(
        options_json_path=CREDENTIALS_JSON_PATH,
        paths=paths,
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

    return bot


if __name__ == "__main__":
    try:
        asyncio.run(amain())
    except InterruptedError as e:
        print_timestamped(f"Shutting down due to interrupt signal: {e}")
    except Exception as e:
        print_timestamped("Shutting down due to irrecoverable error")
        traceback.print_exception(e)
        sys.exit(1)
