import asyncio
import os
import sys
import traceback
from datetime import datetime

from options import resolve_options, Paths
from bot import Bot


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
    CREDENTIALS_JSON_PATH = os.path.abspath("credentials.json")

    BASE_DIR = os.path.abspath("session")
    STORE_DIR = os.path.join(BASE_DIR, "store")
    AUTH_DIR = os.path.join(BASE_DIR, "auth")

    ensure_directory(BASE_DIR)
    ensure_directory(STORE_DIR)
    ensure_directory(AUTH_DIR)

    # Options
    paths = Paths(
        auth_dir=AUTH_DIR,
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


if __name__ == "__main__":
    try:
        asyncio.run(amain())
    except InterruptedError as e:
        print_timestamped(f"Shutting down due to interrupt signal: {e}")
    except Exception as e:
        print_timestamped("Shutting down due to irrecoverable error")
        traceback.print_exception(e)
        sys.exit(1)
