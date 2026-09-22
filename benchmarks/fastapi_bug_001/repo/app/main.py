"""HTTP API for user registration."""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.service import UserService


class UserCreate(BaseModel):
    email: str
    name: str


class UserOut(BaseModel):
    id: int
    email: str
    name: str


def create_app() -> FastAPI:
    app = FastAPI(title="Users API")
    service = UserService()

    @app.post("/users", response_model=UserOut, status_code=201)
    def create_user(payload: UserCreate) -> UserOut:
        user = service.register(payload.email, payload.name)
        return UserOut(id=user.id, email=user.email, name=user.name)

    @app.get("/users/{user_id}", response_model=UserOut)
    def get_user(user_id: int) -> UserOut:
        user = service.get(user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="user not found")
        return UserOut(id=user.id, email=user.email, name=user.name)

    @app.get("/users", response_model=list[UserOut])
    def list_users() -> list[UserOut]:
        return [UserOut(id=u.id, email=u.email, name=u.name) for u in service.list_users()]

    return app


app = create_app()
