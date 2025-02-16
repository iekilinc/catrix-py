from typing import NamedTuple
from getpass import getpass
from json import dumps, loads
from typing import Optional
import aiofiles
from jsonschema import validate
import simplematrixbotlib as botlib
from datetime import datetime
from typing import Self, Any, Callable
from .booru import Rating


json_schema = {
    "type": "object",
    "properties": {
        "homeserver": {"type": "string"},
        "username": {"type": "string"},
        "password": {"type": "string"},
        "device_name": {"type": "string"},
        "allowed_command_users": {
            "type": "array",
            "items": {"type": "string"},
        },
        "default_rating": {
            "type": "object",
            "properties": {
                "safe": {"type": "boolean"},
                "questionable": {"type": "boolean"},
                "explicit": {"type": "boolean"},
            },
            "required": ["safe", "questionable", "explicit"],
        },
    },
    "required": [
        "homeserver",
        "username",
        "password",
        "device_name",
        "allowed_command_users",
        "default_rating",
    ],
}


class Options(NamedTuple):
    homeserver: str
    username: str
    password: str
    device_name: str
    auth_txt_path: str
    allowed_command_users: set[str]
    default_rating: Rating
    allow_interactive: bool

    def to_json_str(self, redact_sensitive: bool) -> str:
        json = {
            "homeserver": self.homeserver,
            "username": self.username,
            "password": redact(str(self.password), redact_sensitive),
            "device_name": self.device_name,
            "allowed_command_users": list(self.allowed_command_users),
            "default_rating": {
                "safe": self.default_rating.safe,
                "questionable": self.default_rating.questionable,
                "explicit": self.default_rating.explicit,
            },
        }
        validate(json, json_schema)
        return dumps(json, indent=4)

    @classmethod
    def from_json(cls, json: Any, auth_txt_path: str, allow_interactive: bool) -> Self:
        validate(json, json_schema)
        rating_json = json["default_rating"]
        options = cls(
            homeserver=json["homeserver"],
            username=json["username"],
            password=json["password"],
            device_name=json["device_name"],
            auth_txt_path=auth_txt_path,
            allowed_command_users=set(json["allowed_command_users"]),
            default_rating=Rating(
                safe=rating_json["safe"],
                questionable=rating_json["questionable"],
                explicit=rating_json["explicit"],
            ),
            allow_interactive=allow_interactive,
        )
        return options

    def botlib_creds(self) -> botlib.Creds:
        creds = botlib.Creds(
            homeserver=self.homeserver,
            username=self.username,
            password=self.password,
            session_stored_file=self.auth_txt_path,
        )
        return creds


def redact(source: str, do_redact: bool) -> str:
    if do_redact:
        return "<redacted>"
    else:
        return source


def prompt(message: str, default: Optional[str] = None, password: bool = False) -> str:
    msg = f"{message}: "
    if default is not None:
        msg = f"{msg} [{default}] "

    fn: Callable[[str], str]
    if password:
        fn = getpass
    else:
        fn = input
    while True:
        answer = fn(msg).strip()
        if answer != "":
            return answer
        if default is not None:
            return default


def prompt_bool(message: str, default: Optional[bool] = None) -> bool:
    msg = f"{message}: "
    if default is None:
        msg = f"{msg} [y/n] "
    else:
        if default:
            msg = f"{msg} [Y/n] "
        else:
            msg = f"{msg} [y/N] "

    while True:
        answer = input(msg).strip().lower()
        if answer == "y":
            return True
        if answer == "n":
            return False


def prompt_list(message: str) -> list[str]:
    msg = f"{message}: (Empty to finish) "
    answers = list[str]()

    while True:
        answer = input(msg).strip()
        if answer == "":
            return answers
        answers.append(answer)


def log(message: str):
    print(f"{datetime.now().isoformat()}: {message}")


def prompt_options(auth_txt_path: str) -> Options:
    homeserver = prompt(
        "Enter full homeserver URL", default="https://matrix-client.matrix.org"
    )
    username = prompt("Enter full user ID (eg, @name:matrix.org)")
    password = prompt("Enter password (hidden while typing)", password=True)
    device_name = prompt("Enter arbitrary name for device (eg, bot)")
    allowed_command_users = prompt_list(
        "Enter full user ID of a user to allow them to run commands"
    )
    allow_safe = prompt_bool("Allow rating:safe?", default=True)
    allow_questionable = prompt_bool("Allow rating:questionable?")
    allow_explicit = prompt_bool("Allow rating:explicit?")
    return Options(
        homeserver=homeserver,
        username=username,
        password=password,
        device_name=device_name,
        auth_txt_path=auth_txt_path,
        allowed_command_users=set(allowed_command_users),
        allow_interactive=True,
        default_rating=Rating(
            safe=allow_safe,
            questionable=allow_questionable,
            explicit=allow_explicit,
        ),
    )


async def resolve_options(
    options_json_path: str, auth_txt_path: str, allow_interactive: bool
) -> Optional[Options]:
    try:
        async with aiofiles.open(options_json_path, mode="r") as r_file:
            log(f"Options file found at {options_json_path}")

            contents = await r_file.read()
            json = loads(contents)
            return Options.from_json(
                json,
                auth_txt_path=auth_txt_path,
                allow_interactive=allow_interactive,
            )

    except FileNotFoundError:
        log(f"Options file not found at {options_json_path}")

        if not allow_interactive:
            log("Interactivity not allowed. Will not prompt for options.")
            return None

        options = prompt_options(auth_txt_path=auth_txt_path)
        json_str_sensitive = options.to_json_str(redact_sensitive=False)
        json_str_redacted = options.to_json_str(redact_sensitive=True)

        log(f"Options: {json_str_redacted}")
        log(f"Saving options to file at {options_json_path}")
        async with aiofiles.open(options_json_path, "w") as w_file:
            await w_file.write(json_str_sensitive)
