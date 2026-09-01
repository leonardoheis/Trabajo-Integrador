from pydantic import BaseModel


class User(BaseModel):
    email: str
    is_active: bool = True
    is_admin: bool = False
    picture: str | None = None


class AuthToken(BaseModel):
    access_token: str
    token_type: str = "bearer"
