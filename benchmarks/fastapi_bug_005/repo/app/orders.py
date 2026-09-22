"""Order handling."""

from dataclasses import dataclass
from itertools import count


@dataclass
class Order:
    id: int
    sku: str
    quantity: int
    total: float


UNIT_PRICE = 12.5


class OrderService:
    def __init__(self) -> None:
        self._ids = count(1)
        self._orders: dict[int, Order] = {}

    def place(self, sku: str, quantity: int) -> Order:
        order = Order(
            id=next(self._ids), sku=sku, quantity=quantity, total=quantity * UNIT_PRICE
        )
        self._orders[order.id] = order
        return order
