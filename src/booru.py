from abc import ABC, abstractmethod
from typing import NamedTuple, Optional, Any
from pydantic import BaseModel


class NoRatingIsAllowedError(Exception):
    pass


class Rating(BaseModel, frozen=True):
    safe: bool
    questionable: bool
    explicit: bool

    def __post_init__(self) -> None:
        if not self.safe and not self.questionable and not self.explicit:
            raise NoRatingIsAllowedError("No rating is allowed")

    def tag(self) -> str | None:
        return rating_map[self]

    def invert(self) -> "Rating":
        return Rating(
            safe=not self.safe,
            questionable=not self.questionable,
            explicit=not self.explicit,
        )


rating_map: dict[Rating, str | None] = {
    Rating(safe=True, questionable=True, explicit=True): None,
    Rating(safe=True, questionable=False, explicit=False): "rating:safe",
    Rating(safe=False, questionable=True, explicit=False): "rating:questionable",
    Rating(safe=False, questionable=False, explicit=True): "rating:explicit",
    Rating(safe=False, questionable=True, explicit=True): "-rating:safe",
    Rating(safe=True, questionable=False, explicit=True): "-rating:questionable",
    Rating(safe=True, questionable=True, explicit=False): "-rating:explicit",
}


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
