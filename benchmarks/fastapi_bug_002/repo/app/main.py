"""Article listing API."""

from fastapi import FastAPI, Query
from pydantic import BaseModel

from app.store import ArticleStore


class ArticleOut(BaseModel):
    id: int
    title: str


class PageOut(BaseModel):
    items: list[ArticleOut]
    page: int
    size: int
    total: int


def create_app() -> FastAPI:
    app = FastAPI(title="Articles API")
    store = ArticleStore()

    @app.get("/articles", response_model=PageOut)
    def list_articles(page: int = Query(1, ge=1), size: int = Query(10, ge=1, le=100)) -> PageOut:
        items = store.page(page, size)
        return PageOut(
            items=[ArticleOut(id=a.id, title=a.title) for a in items],
            page=page,
            size=size,
            total=store.total(),
        )

    return app


app = create_app()
