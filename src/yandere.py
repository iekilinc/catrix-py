from typing import Any, Optional, Callable
from booru import Rating
from jsonschema import validate
from jsonschema.exceptions import ValidationError
from mimetypes import guess_type
from urllib.parse import unquote
from booru import Booru, ImageProps, ReceivedZeroPostsError, InvalidPostJsonError

post_json_schema = {
    "type": "object",
    "properties": {
        "id": {"type": "number"},
        "author": {"type": "string"},
        "sample_url": {"type": "string"},
        "sample_width": {"type": "number"},
        "sample_height": {"type": "number"},
        "sample_file_size": {"type": "number"},
    },
    "required": [
        "id",
        "author",
        "sample_url",
        "sample_width",
        "sample_height",
        "sample_file_size",
    ],
}

TAG_SEPERATOR = "+"

type LogFn = Callable[[str], None]


class YandeRe(Booru):
    default_rating: Rating
    log: LogFn

    def __init__(self, default_rating: Rating, log: LogFn) -> None:
        self.default_rating = default_rating
        self.log = log

    def get_random_post(
        self,
        rating_override: Optional[Rating] = None,
    ) -> str:
        url = "https://yande.re/post.json?limit=1"

        rating = self.default_rating if rating_override is None else rating_override
        rating_tag = rating.tag()

        tags = set[str](("order:random",))
        if rating_tag is not None:
            tags.add(rating_tag)

        tags_str = TAG_SEPERATOR.join(tags)
        if tags_str != "":
            url = f"{url}&tags={tags_str}"

        return url

    def parse_post_json(
        self,
        json: Any,
    ) -> ImageProps | ReceivedZeroPostsError | InvalidPostJsonError:
        post = self._extract_post_json(json)
        if isinstance(post, InvalidPostJsonError):
            return post
        if isinstance(post, ReceivedZeroPostsError):
            return post

        url = str(post["sample_url"])
        *_, tail = url.split("/")
        filename = unquote(tail)

        mime_type, *_ = guess_type(filename)
        if mime_type is None or mime_type == "":
            return InvalidPostJsonError(
                f"Could not guess MIME type of image from filename '{filename}'"
            )

        width = int(post["sample_width"])
        height = int(post["sample_height"])
        file_size = int(post["sample_file_size"])

        author = str(post["author"])
        post_id = str(post["id"])
        post_url = f"https://yande.re/posts/show/{post_id}"

        return ImageProps(
            url=url,
            filename=filename,
            mime_type=mime_type,
            file_size=file_size,
            width=width,
            height=height,
            author=author,
            post_url=post_url,
        )

    def _extract_post_json(
        self, posts: Any
    ) -> InvalidPostJsonError | ReceivedZeroPostsError | Any:
        try:
            posts_json_schema = {
                "type": "array",
                "items": post_json_schema,
            }
            validate(posts, posts_json_schema)
        except ValidationError as err:
            return InvalidPostJsonError(err)

        if len(posts) == 0:
            return ReceivedZeroPostsError()
        elif len(posts) == 1:
            return posts[0]
        else:
            self.log(
                f"WARNING: Received more 1 post ({len(posts)}). Using the first post in the list."
            )
            return posts[0]
