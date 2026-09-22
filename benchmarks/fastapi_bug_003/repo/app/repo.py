"""Product lookup."""

from dataclasses import dataclass


@dataclass
class Product:
    id: int
    name: str
    price: float


class ProductRepo:
    def __init__(self) -> None:
        self._products = {
            1: Product(id=1, name="Keyboard", price=49.0),
            2: Product(id=2, name="Monitor", price=219.0),
        }

    def find(self, product_id: int) -> Product | None:
        return self._products.get(product_id)
