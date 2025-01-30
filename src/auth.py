from typing import NamedTuple
from getpass import getpass
import json
import traceback
from typing import Optional
import aiofiles
import jsonschema
import os
import simplematrixbotlib as botlib

CREDENTIALS_JSON_PATH = os.path.abspath("credentials.json")
AUTH_TXT_PATH = os.path.abspath("session/auth.txt")


class PersistentCredentials(NamedTuple):
    homeserver: str
    username: str
    password: str
    device_name: str
    allowed_command_users: set[str]


class Credentials(NamedTuple):
    bot_creds: botlib.Creds
    allowed_command_users: set[str]


def to_json(c: PersistentCredentials) -> str:
    return json.dumps(
        {
            "homeserver": c.homeserver,
            "username": c.username,
            "password": c.password,
            "device_name": c.device_name,
            "allowed_command_users": list(c.allowed_command_users),
        },
        indent=2,
    )


def print_creds_safe(c: PersistentCredentials) -> None:
    print(
        f"\thomeserver={c.homeserver}\n\tusername={c.username}\n\tpassword=[redacted]\n\tdevice_name={c.device_name}\n\tpassword=[redacted]\n\tallowed_command_users={c.allowed_command_users}"
    )


async def resolve_credentials() -> Optional[Credentials]:
    if not os.path.exists(CREDENTIALS_JSON_PATH):
        # Interactive login
        print(f"No {CREDENTIALS_JSON_PATH} found. Asking login credentials.")

        homeserver_default = "https://matrix-client.matrix.org"
        homeserver = input(
            f"Enter full homeserver URL [{homeserver_default}]: "
        ).strip()
        if homeserver == "":
            homeserver = homeserver_default

        username = input("Enter full user ID (eg, @name:matrix.org): ").strip()
        password = getpass("Enter password (hidden while typing): ")
        device_name = input("Enter arbitrary name for device (eg, bot): ").strip()
        allowed_command_users = set[str]()
        while True:
            allowed_user = input(
                "Enter full user ID of a user that will be allowed to run commands by this bot, or enter nothing to continue: "
            ).strip()
            if allowed_user == "":
                break
            else:
                allowed_command_users.add(allowed_user)

        creds = PersistentCredentials(
            homeserver=homeserver,
            username=username,
            password=password,
            device_name=device_name,
            allowed_command_users=allowed_command_users,
        )
        print_creds_safe(creds)

        # Save credentials to disk
        async with aiofiles.open(CREDENTIALS_JSON_PATH, "w") as f:
            await f.write(to_json(creds))
        print(f"Credentials written to {CREDENTIALS_JSON_PATH}")

        bot_creds = creds_to_botlib_creds(creds)
        return Credentials(
            bot_creds=bot_creds, allowed_command_users=creds.allowed_command_users
        )

    else:
        # Read credentials from disk
        async with aiofiles.open(CREDENTIALS_JSON_PATH, "r") as f:
            text = await f.read()

        try:
            json_creds = json.loads(text)
        except Exception as e:
            print(f"Malformed json inside of {CREDENTIALS_JSON_PATH}")
            traceback.print_exception(e)
            return None

        schema = {
            "type": "object",
            "properties": {
                "homeserver": {"type": "string"},
                "username": {"type": "string"},
                "password": {"type": "string"},
                "device_name": {"type": "string"},
                "allowed_command_users": {
                    "type": "array",
                    "items": {
                        "type": "string",
                    },
                },
            },
        }

        try:
            jsonschema.validate(json_creds, schema)
        except Exception as e:
            print(f"Malformed {CREDENTIALS_JSON_PATH} file: {e}")
            return None

        print(f"Retreived credentials from {CREDENTIALS_JSON_PATH}")
        creds = PersistentCredentials(
            homeserver=json_creds["homeserver"],
            username=json_creds["username"],
            password=json_creds["password"],
            device_name=json_creds["device_name"],
            allowed_command_users=set(json_creds["allowed_command_users"]),
        )
        print_creds_safe(creds)

        bot_creds = creds_to_botlib_creds(creds)
        return Credentials(
            bot_creds=bot_creds,
            allowed_command_users=creds.allowed_command_users,
        )


def creds_to_botlib_creds(creds: PersistentCredentials) -> botlib.Creds:
    bot_creds = botlib.Creds(
        homeserver=creds.homeserver,
        username=creds.username,
        password=creds.password,
        session_stored_file=AUTH_TXT_PATH,
    )
    bot_creds.device_name = creds.device_name
    return bot_creds
