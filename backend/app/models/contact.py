from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

NAME_MAX_LENGTH = 100
# RFC 5321 limits a forward-path to 256 octets including the angle brackets.
EMAIL_MAX_LENGTH = 254
MESSAGE_MAX_LENGTH = 5000
HONEYPOT_MAX_LENGTH = 200


class ContactRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=NAME_MAX_LENGTH)
    email: EmailStr = Field(max_length=EMAIL_MAX_LENGTH)
    message: str = Field(min_length=1, max_length=MESSAGE_MAX_LENGTH)
    # Honeypot: hidden from humans in the form, so any value indicates a bot.
    website: str = Field(default="", max_length=HONEYPOT_MAX_LENGTH)


class ContactResponse(BaseModel):
    status: Literal["accepted"]
