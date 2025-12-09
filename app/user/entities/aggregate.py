from datetime import datetime
from typing import Any

from pydantic import BaseModel

from .entity import  User


class UserAggregate(BaseModel):
    user: User
    events: list[str] = []

