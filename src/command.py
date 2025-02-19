from typing import NamedTuple, Self, Any, TYPE_CHECKING
from aiohttp import ClientSession, ClientResponse, ClientResponseError
from nio import RoomMessageText, UploadError
import re

from booru import Rating, ImageProps, ReceivedZeroPostsError, InvalidPostJsonError

if TYPE_CHECKING:
    # Prevent cylic import.
    # We only need bot for its types.
    from bot import Bot

CG_PREFIXES = frozenset[str](
    (
        "!cg",
        "!catgirl",
        "!neko",
        "!nekomimi",
        "!mimi",
        "!mimir",
        "!nya",
        "!nyaa",
    ),
)

RATING_SEPARATOR = " "


def make_rating_map() -> dict[str, Rating]:
    rating_map = {
        "s": Rating(safe=True, questionable=False, explicit=False),
        "safe": Rating(safe=True, questionable=False, explicit=False),
        "q": Rating(safe=False, questionable=True, explicit=False),
        "questionable": Rating(safe=False, questionable=True, explicit=False),
        "e": Rating(safe=False, questionable=False, explicit=True),
        "explicit": Rating(safe=False, questionable=False, explicit=True),
    }
    # Create a complementary rating for each rating.
    # Eg, {"safe": Rating(s=T, q=F, e=F)} produces {"-safe": Rating(s=F, q=T, e=T)}
    for key, value in list(rating_map.items()):
        inverted_key = f"-{key}"
        rating_map[inverted_key] = value.invert()

    return rating_map


RATING_MAP = make_rating_map()


def make_regex():
    """Examples:
    "!cg"
    "!cg s"
    "!nyaa questionable"
    """
    command_prefixes = "|".join(map(re.escape, CG_PREFIXES))
    rating_specifiers = "|".join(map(re.escape, RATING_MAP.keys()))
    rating_separator = re.escape(RATING_SEPARATOR)

    pattern = f"^({command_prefixes})({rating_separator}({rating_specifiers}))?$"
    return re.compile(pattern, re.IGNORECASE)


REGEX = make_regex()


class ParsedCommand(NamedTuple):
    rating: Rating | None

    @classmethod
    def parse_message(
        cls,
        message: RoomMessageText,
    ) -> Self | None:
        body = message.body.strip()

        match = REGEX.match(body)
        if match is None:
            return None

        rating: Rating | None = None
        # command_prefix = match.group(1)
        # rating_separator = match.group(2)
        rating_specifier = match.group(3)
        if rating_specifier is not None:
            rating = RATING_MAP[rating_specifier]

        return cls(rating=rating)


def raise_resp_error(resp: ClientResponse) -> ClientResponseError:
    # Copy-pasted from:
    # resp.raise_for_status()

    # reason should always be not None for a started response
    assert resp.reason is not None

    # If we're in a context we can rely on __aexit__() to release as the
    # exception propagates.
    if not resp._in_context:
        resp.release()

    raise ClientResponseError(
        resp.request_info,
        resp.history,
        status=resp.status,
        message=resp.reason,
        headers=resp.headers,
    )


class UploadedFile(NamedTuple):
    size: int
    json: dict[str, Any]


class Command(NamedTuple):
    parsed: ParsedCommand
    message_id: str
    room_id: str
    command_id: int
    bot: "Bot"

    async def respond(self) -> None:
        try:
            post = await self._get_random_post()

            image = self.bot._booru.parse_post_json(post)
            if isinstance(image, ReceivedZeroPostsError):
                self._log_abort(f"Received zero posts from booru: {post}")
                await self._reply(
                    "no catgirl for you this time :3\n"
                    "whatcha gonna do? pounce on me???? >.<"
                )
                return
            if isinstance(image, InvalidPostJsonError):
                self._log_abort(f"Invalid post JSON from booru: {post}")
                await self._reply("da boowu sent me baad post (ಥ﹏ಥ)")
                return

            enc_file = await self._stream_image_to_matrix(image)
            if isinstance(enc_file, str):
                self._log_abort(enc_file)
                await self._reply("i couwd now upwoad to matwix seuweuo (╥﹏╥)")
                return

            await self._send_image_reply(image, enc_file)
            self.log("DONE:3 Cat served")

        except ClientResponseError as err:
            self._log_abort(f"{err}")
            return

    def log(self, message: str):
        self.bot._log(f"Catgirl {self.command_id}: {message}")

    def _log_abort(self, message: str):
        self.log(f"ABORT: {message}")

    async def _get_random_post(self) -> Any:
        async with ClientSession() as session:
            rating_override = self.parsed.rating
            get_url = self.bot._booru.get_random_post(rating_override)

            self.log(f"GET {get_url}")
            async with session.get(get_url) as resp:
                if resp.status != 200:
                    raise_resp_error(resp)

                post_json = await resp.json()
                return post_json

    async def _stream_image_to_matrix(
        self,
        image: ImageProps,
    ) -> UploadedFile | str:
        async with ClientSession() as session:
            get_url = image.url
            self.log(f"GET {get_url}")
            async with session.get(get_url) as img_resp:
                if img_resp.status != 200:
                    raise_resp_error(img_resp)

                self.log("Uploading image to matrix")
                file_size = img_resp.content_length
                if file_size is None:
                    file_size = image.file_size

                enc_file, img_keys = await self.bot._client.upload(
                    lambda a, b: img_resp.content,
                    encrypt=True,
                    content_type=image.mime_type,
                    filesize=file_size,
                )

        if isinstance(enc_file, UploadError):
            return f"{enc_file}"

        if img_keys is None:
            return "Cryptographic informaton missing from encrypted file upload call"

        file_json = {
            "url": enc_file.content_uri,
            "v": img_keys["v"],
            "key": img_keys["key"],
            "iv": img_keys["iv"],
            "hashes": img_keys["hashes"],
        }
        return UploadedFile(
            size=file_size,
            json=file_json,
        )

    async def _send_image_reply(
        self, image: ImageProps, enc_file: UploadedFile
    ) -> None:
        msg_content = {
            "body": f"catgirl by {image.author}: {image.post_url}",
            "filename": image.filename,
            "info": {
                "size": enc_file.size,
                "mimetype": image.mime_type,
                "thumbnail_info": None,
                "thumbnail_url": None,
                "w": image.width,
                "h": image.height,
            },
            "msgtype": "m.image",
            "file": enc_file.json,
            "m.relates_to": {
                "m.in_reply_to": {
                    "event_id": self.message_id,
                },
            },
        }
        self.log("Sending message with the catgirl image attached")
        await self.bot._lib_bot.api._send_room(
            room_id=self.room_id,
            content=msg_content,
        )

    async def _reply(self, message: str) -> None:
        await self.bot._lib_bot.api.send_text_message(
            room_id=self.room_id,
            reply_to=self.message_id,
            message=message,
        )
