from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.sql import func
from database import Base

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    nickname = Column(String, unique=True, nullable=False)
    instruction = Column(Text, default="")
    outgoing_instruction = Column(Text, default="")

class Message(Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True)
    sender_id = Column(Integer, ForeignKey("users.id"))
    recipient_id = Column(Integer, ForeignKey("users.id"))
    original_text = Column(Text)
    outgoing_text = Column(Text)
    rephrased_text = Column(Text)
    instruction_used = Column(Text)
    outgoing_instruction_used = Column(Text)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
