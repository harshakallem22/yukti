"""Orders API."""

from fastapi import FastAPI
from pydantic import BaseModel

from app.orders import OrderService


class OrderIn(BaseModel):
    sku: str
    quantity: int


class OrderOut(BaseModel):
    id: int
    sku: str
    quantity: int
    total: float


def create_app() -> FastAPI:
    app = FastAPI(title="Orders API")
    service = OrderService()

    @app.post("/orders", response_model=OrderOut, status_code=201)
    def place_order(payload: OrderIn) -> OrderOut:
        order = service.place(payload.sku, payload.quantity)
        return OrderOut(id=order.id, sku=order.sku, quantity=order.quantity, total=order.total)

    return app


app = create_app()
