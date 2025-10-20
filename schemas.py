from typing import Optional
from datetime import datetime

from pydantic import BaseModel

class UserCreate(BaseModel):
    nickname: str

class UserOut(BaseModel):
    id: int
    nickname: str
    instruction: str
    outgoing_instruction: str
    is_online: bool = False
    class Config:
        orm_mode = True

class MessageCreate(BaseModel):
    sender_id: int
    recipient_id: int
    text: str

class MessageOut(BaseModel):
    id: int
    sender_id: int
    recipient_id: int
    original_text: Optional[str] = None
    outgoing_text: Optional[str] = None
    rephrased_text: str
    instruction_used: Optional[str] = None
    outgoing_instruction_used: Optional[str] = None
    class Config:
        orm_mode = True

class ConversationSummary(BaseModel):
    peer_id: int
    nickname: str
    is_online: bool = False
    last_message_id: Optional[int] = None
    last_message_sender_id: Optional[int] = None
    last_message_text: Optional[str] = None
    last_message_timestamp: Optional[datetime] = None
