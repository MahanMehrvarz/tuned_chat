from sqlalchemy import select
from models import User, Message
from typing import Dict

async def get_user_by_nickname(db, nickname: str):
    result = await db.execute(select(User).where(User.nickname == nickname))
    return result.scalar_one_or_none()

async def create_user(db, nickname: str):
    user = User(nickname=nickname)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user

async def get_users(db):
    result = await db.execute(select(User))
    return result.scalars().all()

async def update_instruction(db, user_id: int, instruction: str):
    user = await db.get(User, user_id)
    if not user:
        return None
    user.instruction = instruction or ""
    await db.commit()
    await db.refresh(user)
    return user

async def update_outgoing_instruction(db, user_id: int, instruction: str):
    user = await db.get(User, user_id)
    if not user:
        return None
    user.outgoing_instruction = instruction or ""
    await db.commit()
    await db.refresh(user)
    return user

async def create_message(
    db,
    sender_id,
    recipient_id,
    original_text,
    outgoing_text,
    rephrased_text,
    outgoing_instruction,
    instruction,
):
    msg = Message(
        sender_id=sender_id,
        recipient_id=recipient_id,
        original_text=original_text,
        outgoing_text=outgoing_text,
        rephrased_text=rephrased_text,
        instruction_used=instruction,
        outgoing_instruction_used=outgoing_instruction,
    )
    db.add(msg)
    await db.commit()
    await db.refresh(msg)
    return msg

async def get_messages(db, sender_id, recipient_id):
    stmt = (
        select(Message)
        .where(
            ((Message.sender_id == sender_id) & (Message.recipient_id == recipient_id))
            | ((Message.sender_id == recipient_id) & (Message.recipient_id == sender_id))
        )
        .order_by(Message.timestamp)
    )
    result = await db.execute(stmt)
    return result.scalars().all()

async def get_conversation_summaries(db, user_id: int) -> Dict[int, dict]:
    users_result = await db.execute(select(User))
    users = {user.id: user for user in users_result.scalars().all() if user.id != user_id}
    summaries: Dict[int, dict] = {
        uid: {
            "peer_id": uid,
            "nickname": users[uid].nickname,
            "last_message_id": None,
            "last_message_sender_id": None,
            "last_message_text": None,
            "last_message_timestamp": None,
        }
        for uid in users
    }

    msgs_result = await db.execute(
        select(Message)
        .where((Message.sender_id == user_id) | (Message.recipient_id == user_id))
        .order_by(Message.timestamp.desc())
    )
    for msg in msgs_result.scalars():
        peer_id = msg.recipient_id if msg.sender_id == user_id else msg.sender_id
        if peer_id not in summaries:
            continue
        summary = summaries[peer_id]
        if summary["last_message_id"] is not None:
            continue
        mine = msg.sender_id == user_id
        text = (
            (msg.outgoing_text or msg.rephrased_text or msg.original_text or "")
            if mine
            else (msg.rephrased_text or msg.outgoing_text or msg.original_text or "")
        )
        summary["last_message_id"] = msg.id
        summary["last_message_sender_id"] = msg.sender_id
        summary["last_message_text"] = text
        summary["last_message_timestamp"] = msg.timestamp

    return summaries
