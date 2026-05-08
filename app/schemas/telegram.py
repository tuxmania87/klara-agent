"""Pydantic schemas for incoming Telegram webhook payloads."""
from typing import Optional
from pydantic import BaseModel


class TelegramUser(BaseModel):
    id: int
    first_name: str = ""
    last_name: str = ""
    username: Optional[str] = None
    is_bot: bool = False


class TelegramChat(BaseModel):
    id: int
    type: str


class TelegramMessage(BaseModel):
    message_id: int
    from_: Optional[TelegramUser] = None
    chat: TelegramChat
    text: Optional[str] = None
    date: int

    class Config:
        populate_by_name = True
        fields = {"from_": "from"}


class TelegramCallbackQuery(BaseModel):
    id: str
    from_: TelegramUser
    message: TelegramMessage
    data: Optional[str] = None

    class Config:
        populate_by_name = True
        fields = {"from_": "from"}


class TelegramUpdate(BaseModel):
    update_id: int
    message: Optional[TelegramMessage] = None
    callback_query: Optional[TelegramCallbackQuery] = None
