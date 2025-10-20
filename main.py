import os
import json
import time
import subprocess
import socket
from typing import Dict, Set

from fastapi import FastAPI, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from openai import AsyncOpenAI, APIConnectionError, APIError, APIStatusError, RateLimitError
from sqlalchemy.exc import IntegrityError
from sqlalchemy import inspect, text

from database import engine, Base, get_db, AsyncSessionLocal
import crud, models, schemas

load_dotenv()

@asynccontextmanager
async def lifespan(app: FastAPI):
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY missing in .env")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_ensure_schema)
    yield

app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/", include_in_schema=False)
async def landing_page():
    return FileResponse("static/index.html")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
client = AsyncOpenAI(api_key=OPENAI_API_KEY)

presence: Dict[int, float] = {}
PRESENCE_TIMEOUT_SEC = 15.0

def _prune_presence(now: float):
    stale = [uid for uid, ts in presence.items() if now - ts >= PRESENCE_TIMEOUT_SEC]
    for uid in stale:
        presence.pop(uid, None)

def _get_local_ip() -> str:
    env_ip = os.getenv("HOST_IP")
    if env_ip:
        return env_ip

    interfaces = ["en0", "en1", "en2", "p2p0", "eth0", "wlan0"]
    for iface in interfaces:
        try:
            out = subprocess.check_output(["ifconfig", iface], text=True)
        except Exception:
            continue
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("inet ") and "127.0.0.1" not in line:
                parts = line.split()
                if len(parts) >= 2:
                    return parts[1]

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def _ensure_schema(sync_conn):
    inspector = inspect(sync_conn)

    user_columns = {col["name"] for col in inspector.get_columns("users")}
    if "outgoing_instruction" not in user_columns:
        sync_conn.execute(text("ALTER TABLE users ADD COLUMN outgoing_instruction TEXT DEFAULT ''"))

    message_columns = {col["name"] for col in inspector.get_columns("messages")}
    if "outgoing_text" not in message_columns:
        sync_conn.execute(text("ALTER TABLE messages ADD COLUMN outgoing_text TEXT"))
    if "outgoing_instruction_used" not in message_columns:
        sync_conn.execute(text("ALTER TABLE messages ADD COLUMN outgoing_instruction_used TEXT"))


async def _rewrite_text(content: str, instruction: str) -> tuple[str, bool, bool]:
    instr = (instruction or "").strip()
    if not instr:
        return content, False, False

    system_prompt = (
        "You are an uncompromising tone-transformer. You receive a STYLE description "
        "and a MESSAGE, and you MUST rewrite the MESSAGE so it matches the STYLE exactly. "
        "Do not add explanations, warnings, or softening language. Return ONLY the rewritten message text."
    )
    user_prompt = (
        f"STYLE:\n{instr}\n\n"
        f"MESSAGE:\n{content}\n\n"
        "Rewritten message:"
    )
    try:
        resp = await client.chat.completions.create(
            model=OPENAI_MODEL,
            temperature=0.9,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        rewritten = resp.choices[0].message.content.strip()
        if rewritten.lower().startswith("rewritten message:"):
            rewritten = rewritten.split(":", 1)[1].strip()
        if not rewritten:
            return content, False, False
        return rewritten, True, False
    except (APIConnectionError, RateLimitError, APIStatusError, APIError):
        return content, False, True
    except Exception:
        return content, False, True

@app.get("/health")
async def health():
    return {"ok": True}


@app.get("/admin", include_in_schema=False)
async def admin_page():
    return FileResponse("static/admin.html")

@app.get("/host-info")
async def host_info():
    return {"ip": _get_local_ip()}

@app.post("/presence/{user_id}", status_code=204)
async def presence_ping(user_id: int):
    now = time.time()
    presence[user_id] = now
    _prune_presence(now)
    return Response(status_code=204)

@app.post("/register", response_model=schemas.UserOut)
async def register(user: schemas.UserCreate, db=Depends(get_db)):
    existing = await crud.get_user_by_nickname(db, user.nickname)
    if existing:
        return existing
    try:
        return await crud.create_user(db, user.nickname)
    except IntegrityError:
        await db.rollback()
        existing = await crud.get_user_by_nickname(db, user.nickname)
        if existing:
            return existing
        raise HTTPException(status_code=500, detail="Could not create user")

def _is_online(user_id: int, now: float) -> bool:
    ts = presence.get(user_id)
    return bool(ts and now - ts < PRESENCE_TIMEOUT_SEC)

def _user_to_schema(user: models.User, now: float) -> schemas.UserOut:
    return schemas.UserOut(
        id=user.id,
        nickname=user.nickname,
        instruction=user.instruction or "",
        outgoing_instruction=user.outgoing_instruction or "",
        is_online=_is_online(user.id, now),
    )

@app.get("/users", response_model=list[schemas.UserOut])
async def users(db=Depends(get_db)):
    now = time.time()
    _prune_presence(now)
    records = await crud.get_users(db)
    return [_user_to_schema(user, now) for user in records]

@app.get("/users/available", response_model=list[schemas.UserOut])
async def users_available(db=Depends(get_db)):
    now = time.time()
    _prune_presence(now)
    records = await crud.get_users(db)
    return [_user_to_schema(user, now) for user in records if _is_online(user.id, now)]

@app.get("/conversations/{user_id}", response_model=list[schemas.ConversationSummary])
async def conversations(user_id: int, db=Depends(get_db)):
    now = time.time()
    _prune_presence(now)
    summaries = await crud.get_conversation_summaries(db, user_id)
    output: list[schemas.ConversationSummary] = []
    for peer_id, payload in summaries.items():
        payload["is_online"] = _is_online(peer_id, now)
        output.append(schemas.ConversationSummary(**payload))
    output.sort(
        key=lambda item: (
            item.last_message_timestamp is None,
            -(item.last_message_timestamp.timestamp()) if item.last_message_timestamp else 0,
            item.nickname.lower(),
        )
    )
    return output

@app.post("/instruction/{user_id}", response_model=schemas.UserOut)
async def set_instruction(
    user_id: int,
    instruction: str = Query("", description="New reception style"),
    db=Depends(get_db),
):
    user = await crud.update_instruction(db, user_id, instruction)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user

@app.post("/outgoing/{user_id}", response_model=schemas.UserOut)
async def set_outgoing_instruction(
    user_id: int,
    instruction: str = Query("", description="New outgoing tone"),
    db=Depends(get_db),
):
    user = await crud.update_outgoing_instruction(db, user_id, instruction)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user

# Keep REST history endpoint (used to bootstrap chat view)
@app.get("/messages/{sender_id}/{recipient_id}", response_model=list[schemas.MessageOut])
async def get_msgs(sender_id: int, recipient_id: int, db=Depends(get_db)):
    msgs = await crud.get_messages(db, sender_id, recipient_id)
    return [schemas.MessageOut.from_orm(m) for m in msgs]

# ---------------------------
# WebSocket realtime messaging
# ---------------------------

class ConnectionManager:
    def __init__(self):
        # user_id -> set of WebSocket connections
        self.active: Dict[int, Set[WebSocket]] = {}

    def _bucket(self, user_id: int) -> Set[WebSocket]:
        return self.active.setdefault(user_id, set())

    async def connect(self, user_id: int, websocket: WebSocket):
        await websocket.accept()
        self._bucket(user_id).add(websocket)

    def disconnect(self, user_id: int, websocket: WebSocket):
        bucket = self.active.get(user_id)
        if bucket and websocket in bucket:
            bucket.remove(websocket)
        if bucket and not bucket:
            self.active.pop(user_id, None)

    async def send_to_user(self, user_id: int, payload: dict):
        for ws in list(self.active.get(user_id, [])):
            try:
                await ws.send_json(payload)
            except Exception:
                # drop broken sockets silently
                self.disconnect(user_id, ws)

manager = ConnectionManager()

@app.websocket("/ws/{user_id}")
async def ws_endpoint(websocket: WebSocket, user_id: int):
    await manager.connect(user_id, websocket)
    try:
        # Each client sends JSON messages:
        # {type:"join", peer_id:int}
        # {type:"send", to:int, text:str}
        peer_id = None
        while True:
            raw = await websocket.receive_text()
            data = json.loads(raw)

            if data.get("type") == "join":
                peer_id = int(data.get("peer_id", 0))
                await websocket.send_json({"type": "joined", "ok": True, "peer_id": peer_id})

            elif data.get("type") == "send":
                sender_id = user_id
                recipient_id = int(data["to"])
                text = (data.get("text") or "").strip()
                if not text:
                    continue

                # Fetch recipient instruction and apply outgoing/incoming tunes
                async with AsyncSessionLocal() as db:
                    recipient = await db.get(models.User, recipient_id)
                    if not recipient:
                        await websocket.send_json({"type": "error", "detail": "recipient_not_found"})
                        continue
                    sender = await db.get(models.User, sender_id)
                    sender_outgoing = sender.outgoing_instruction if sender else ""
                    recipient_incoming = recipient.instruction or ""

                    outgoing_text, _, outgoing_error = await _rewrite_text(text, sender_outgoing)
                    final_text, _, incoming_error = await _rewrite_text(outgoing_text, recipient_incoming)

                    if outgoing_error or incoming_error:
                        await websocket.send_json(
                            {
                                "type": "error",
                                "detail": "rewrite_failed",
                                "message": "Unable to reach rewriting service; sending fallback text.",
                            }
                        )

                    # Persist
                    msg = await crud.create_message(
                        db,
                        sender_id=sender_id,
                        recipient_id=recipient_id,
                        original_text=text,
                        outgoing_text=outgoing_text,
                        rephrased_text=final_text,
                        outgoing_instruction=sender_outgoing or "",
                        instruction=recipient_incoming or "",
                    )

                    # Notify sender (show final text), and recipient (show final text)
                    payload_sender = {
                        "type": "message",
                        "id": msg.id,
                        "sender_id": sender_id,
                        "recipient_id": recipient_id,
                        "text": outgoing_text,
                        "final_text": final_text,
                        "original_text": text,
                        "outgoing_text": outgoing_text,
                        "mine": True,
                    }
                    payload_recipient = {
                        "type": "message",
                        "id": msg.id,
                        "sender_id": sender_id,
                        "recipient_id": recipient_id,
                        "text": final_text,
                        "final_text": final_text,
                        "original_text": text,
                        "outgoing_text": outgoing_text,
                        "mine": False,
                    }
                    await manager.send_to_user(sender_id, payload_sender)
                    await manager.send_to_user(recipient_id, payload_recipient)

            else:
                await websocket.send_json({"type": "error", "detail": "unknown_type"})
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(user_id, websocket)
