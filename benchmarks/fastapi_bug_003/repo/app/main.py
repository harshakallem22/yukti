"""Product API."""

from fastapi import FastAPI
from pydantic import BaseModel

from app.repo import ProductRepo


class ProductOut(BaseModel):
    id: int | None = None
    name: str | None = None
    price: float | None = None


def create_app() -> FastAPI:
    app = FastAPI(title="Products API")
    repo = ProductRepo()

    @app.get("/products/{product_id}", response_model=ProductOut)
    def get_product(product_id: int) -> ProductOut:
        product = repo.find(product_id)
        if product is None:
            return ProductOut()
        return ProductOut(id=product.id, name=product.name, price=product.price)

    return app


app = create_app()
