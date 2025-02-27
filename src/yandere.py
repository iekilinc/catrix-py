from typing import Any, Optional, Callable
from booru import Rating
from mimetypes import guess_type
from urllib.parse import unquote
from pydantic import BaseModel, ValidationError

from booru import Booru, ImageProps, ReceivedZeroPostsError, InvalidPostJsonError


class _Post(BaseModel):
    id: int
    author: str
    sample_url: str
    sample_width: int
    sample_height: int
    sample_file_size: int


class _Posts(BaseModel):
    posts: list[_Post]


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

        tags = set[str](("order:random", "nekomimi"))
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

        url = post.sample_url

        *_, tail = url.split("/")
        filename = unquote(tail)

        mime_type, *_ = guess_type(filename)
        if mime_type is None or mime_type == "":
            return InvalidPostJsonError(
                f"Could not guess MIME type of image from filename '{filename}'"
            )

        width = post.sample_width
        height = post.sample_height
        file_size = post.sample_file_size

        author = post.author
        post_id = post.id
        post_url = f"https://yande.re/post/show/{post_id}"

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
    ) -> InvalidPostJsonError | ReceivedZeroPostsError | _Post:
        try:
            posts_obj = _Posts.model_validate({"posts": posts}, strict=True)
        except ValidationError as err:
            return InvalidPostJsonError(err)

        parsed_posts = posts_obj.posts

        if len(parsed_posts) == 0:
            return ReceivedZeroPostsError()
        elif len(parsed_posts) == 1:
            return parsed_posts[0]
        else:
            self.log(
                f"WARNING: Received more than 1 post ({len(parsed_posts)}). Using the first post in the list."
            )
            return parsed_posts[0]
