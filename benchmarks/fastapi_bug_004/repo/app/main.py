"""Search API."""

from fastapi import FastAPI
from pydantic import BaseModel

from app.search import search_cities


class SearchOut(BaseModel):
    query: str
    results: list[str]


def create_app() -> FastAPI:
    app = FastAPI(title="Search API")

    @app.get("/search", response_model=SearchOut)
    def search(q: str = "") -> SearchOut:
        return SearchOut(query=q, results=search_cities(q))

    return app


app = create_app()
