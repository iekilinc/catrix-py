from typing import NamedTuple
from getpass import getpass
from json import dumps, loads
from typing import Optional
import aiofiles
import simplematrixbotlib as botlib
from datetime import datetime
from typing import Self, Any, Callable
from booru import Rating
from pydantic import BaseModel


class Paths(NamedTuple):
    auth_txt: str
    store_dir: str


class Ollama(BaseModel, frozen=True):
    bot_name: str
    model: str
    last_n_messages: int
    prompt_prefix: str
    temperature: Optional[float] = None
    max_token_suggestion: int = 60


class OptionsJson(BaseModel, frozen=True):
    homeserver: str
    username: str
    password: str
    device_name: str
    allowed_command_users: list[str]
    default_rating: Rating
    ollama: Optional[Ollama] = None


class Options(BaseModel, frozen=True):
    homeserver: str
    username: str
    password: str
    device_name: str
    allowed_command_users: set[str]
    default_rating: Rating
    ollama: Optional[Ollama]
    allow_interactive: bool
    paths: Paths
    as_json: OptionsJson

    def to_json_str(self, redact_sensitive: bool) -> str:
        json = self.as_json.model_dump()
        if redact_sensitive:
            json["password"] = "<redacted>"

        return dumps(json, indent=2)

    @classmethod
    def from_options_json(
        cls,
        options: OptionsJson,
        paths: Paths,
        allow_interactive: bool,
    ) -> Self:
        return cls(
            homeserver=options.homeserver,
            username=options.username,
            password=options.password,
            device_name=options.device_name,
            allowed_command_users=set(options.allowed_command_users),
            default_rating=options.default_rating,
            ollama=options.ollama,
            allow_interactive=allow_interactive,
            paths=paths,
            as_json=options,
        )

    @classmethod
    def from_json(
        cls,
        json: Any,
        paths: Paths,
        allow_interactive: bool,
    ) -> Self:
        options = OptionsJson.model_validate(json, strict=True)
        return cls.from_options_json(
            options,
            paths=paths,
            allow_interactive=allow_interactive,
        )

    def botlib_creds(self) -> botlib.Creds:
        creds = botlib.Creds(
            homeserver=self.homeserver,
            username=self.username,
            password=self.password,
            device_name=self.device_name,
            session_stored_file=self.paths.auth_txt,
        )
        return creds


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


def prompt_options(paths: Paths) -> Options:
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

    options = OptionsJson(
        homeserver=homeserver,
        username=username,
        password=password,
        device_name=device_name,
        allowed_command_users=allowed_command_users,
        default_rating=Rating(
            safe=allow_safe,
            questionable=allow_questionable,
            explicit=allow_explicit,
        ),
    )
    return Options.from_options_json(options, paths=paths, allow_interactive=True)


async def resolve_options(
    options_json_path: str,
    paths: Paths,
    allow_interactive: bool,
) -> Optional[Options]:
    try:
        async with aiofiles.open(options_json_path, mode="r") as r_file:
            log(f"Options file found at {options_json_path}")

            contents = await r_file.read()
            json = loads(contents)
            return Options.from_json(
                json,
                paths=paths,
                allow_interactive=allow_interactive,
            )

    except FileNotFoundError:
        log(f"Options file not found at {options_json_path}")

        if not allow_interactive:
            log("Interactivity not allowed. Will not prompt for options.")
            return None

        options = prompt_options(paths=paths)
        json_str_sensitive = options.to_json_str(redact_sensitive=False)
        json_str_redacted = options.to_json_str(redact_sensitive=True)

        log(f"Options: {json_str_redacted}")
        log(f"Saving options to file at {options_json_path}")
        async with aiofiles.open(options_json_path, "w") as w_file:
            await w_file.write(json_str_sensitive)

        return options
