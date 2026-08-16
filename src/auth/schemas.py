from pydantic import BaseModel
from pydantic.config import ConfigDict


class UserInfo(BaseModel):
    id: int
    name: str
    email: str

    model_config = ConfigDict(from_attributes=True)


# Login


class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    user: UserInfo
    access_token: str

    model_config = ConfigDict(from_attributes=True)


# Register


class RegisterRequest(BaseModel):
    name: str
    email: str
    password: str


class RegisterResponse(BaseModel):
    user: UserInfo
    access_token: str

    model_config = ConfigDict(from_attributes=True)
