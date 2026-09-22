"""User registration service."""

from dataclasses import dataclass
from itertools import count


class DuplicateEmailError(Exception):
    """Raised when an email address is already registered."""

    def __init__(self, email: str) -> None:
        super().__init__(f"email already registered: {email}")
        self.email = email


@dataclass
class User:
    id: int
    email: str
    name: str


class UserService:
    def __init__(self) -> None:
        self._users: dict[int, User] = {}
        self._emails: set[str] = set()
        self._ids = count(1)

    def register(self, email: str, name: str) -> User:
        normalised = email.strip().lower()
        if normalised in self._emails:
            raise DuplicateEmailError(normalised)
        user = User(id=next(self._ids), email=normalised, name=name)
        self._users[user.id] = user
        self._emails.add(normalised)
        return user

    def get(self, user_id: int) -> User | None:
        return self._users.get(user_id)

    def list_users(self) -> list[User]:
        return list(self._users.values())
