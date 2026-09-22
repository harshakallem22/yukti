"""City search."""

CITIES = ["London", "Lisbon", "Madrid", "Manchester", "Berlin", "Bern"]


def search_cities(query: str) -> list[str]:
    if not query:
        return []
    return [city for city in CITIES if city.startswith(query)]
