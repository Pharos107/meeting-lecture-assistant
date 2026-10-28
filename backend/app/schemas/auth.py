"""Body tài khoản."""

import uuid

from pydantic import BaseModel


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str
    expires_in: int
    refresh_token: str
    user: UserOut
