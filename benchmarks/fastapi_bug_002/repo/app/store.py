"""In-memory article store."""

from dataclasses import dataclass


@dataclass
class Article:
    id: int
    title: str


class ArticleStore:
    def __init__(self, count: int = 25) -> None:
        self._articles = [Article(id=i, title=f"Article {i}") for i in range(1, count + 1)]

    def page(self, page: int, size: int) -> list[Article]:
        offset = page * size
        return self._articles[offset : offset + size]

    def total(self) -> int:
        return len(self._articles)
