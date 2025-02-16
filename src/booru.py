from abc import ABC, abstractmethod
from typing import NamedTuple, Optional, Literal, Any

type Tag = Literal["safe"] | Literal["questionable"] | Literal["explicit"]

ALL_TAGS = frozenset[Tag](("safe", "questionable", "explicit"))


class Rating(NamedTuple):
    safe: bool
    questionable: bool
    explicit: bool

    def tags(self) -> frozenset[str]:
        if self in rating_tags_memo:
            return rating_tags_memo[self]

        tags = set[Tag]()
        if self.safe:
            tags.add("safe")
        if self.questionable:
            tags.add("questionable")
        if self.explicit:
            tags.add("explicit")

        result: frozenset[str]
        if len(tags) == 3:
            result = frozenset()
        elif len(tags) == 2:
            (exclude,) = ALL_TAGS.difference(tags)
            tag = f"-rating:{exclude}"
            result = frozenset((tag,))
        elif len(tags) == 1:
            (include,) = ALL_TAGS.intersection(tags)
            tag = f"rating:{include}"
            result = frozenset((tag,))
        else:
            raise RuntimeError("len(tags) must be [0, 3]")

        rating_tags_memo[self] = result
        return result


rating_tags_memo = dict[Rating, frozenset[str]]()


class ImageProps(NamedTuple):
    url: str
    filename: str
    mime_type: str
    file_size: int
    width: int
    height: int
    author: str
    post_url: str


class ReceivedZeroPostsError(Exception):
    pass


class InvalidPostJsonError(Exception):
    pass


class Booru(ABC):
    @abstractmethod
    def get_random_post(
        self,
        rating_override: Optional[Rating] = None,
    ) -> str:
        pass

    @abstractmethod
    def parse_post_json(
        self,
        json: Any,
    ) -> ImageProps | ReceivedZeroPostsError | InvalidPostJsonError:
        pass
