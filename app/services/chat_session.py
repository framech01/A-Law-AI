"""
챗봇 대화 세션 저장소

Redis(TTL)에 대화 이력을 저장해 서버 재시작/수평 확장 시에도 세션을 유지합니다.
Redis에 연결할 수 없으면 프로세스 메모리로 대체합니다(개발/테스트용).
"""
import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime

from loguru import logger

from app.core.config import settings

KEY_PREFIX = "chat:session:"


@dataclass
class ChatMessage:
    role: str  # "user" | "assistant"
    content: str
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))


class InMemorySessionBackend:
    def __init__(self):
        self._data: dict[str, tuple[float, list[str]]] = {}

    def _alive(self, key: str) -> list[str] | None:
        entry = self._data.get(key)
        if entry is None:
            return None
        expires, items = entry
        if expires < time.time():
            self._data.pop(key, None)
            return None
        return items

    async def append(self, key: str, value: str, ttl: int) -> None:
        items = self._alive(key) or []
        items.append(value)
        self._data[key] = (time.time() + ttl, items)

    async def get_all(self, key: str) -> list[str]:
        return list(self._alive(key) or [])

    async def delete(self, key: str) -> bool:
        return self._data.pop(key, None) is not None

    async def trim(self, key: str, keep_last: int) -> None:
        items = self._alive(key)
        if items is not None and len(items) > keep_last:
            expires, _ = self._data[key]
            self._data[key] = (expires, items[-keep_last:])


class RedisSessionBackend:
    def __init__(self, client):
        self.client = client

    async def append(self, key: str, value: str, ttl: int) -> None:
        pipe = self.client.pipeline()
        pipe.rpush(key, value)
        pipe.expire(key, ttl)
        await pipe.execute()

    async def get_all(self, key: str) -> list[str]:
        return await self.client.lrange(key, 0, -1)

    async def delete(self, key: str) -> bool:
        return bool(await self.client.delete(key))

    async def trim(self, key: str, keep_last: int) -> None:
        await self.client.ltrim(key, -keep_last, -1)


class ChatSessionStore:
    # 저장 상한: 프롬프트에 쓰는 턴 수보다 넉넉하게 보관
    MAX_STORED_MESSAGES = 100

    def __init__(self, backend=None, ttl: int | None = None):
        self.backend = backend or InMemorySessionBackend()
        self.ttl = ttl or settings.CHAT_SESSION_TTL

    async def append(self, session_id: str, role: str, content: str) -> ChatMessage:
        message = ChatMessage(role=role, content=content)
        key = KEY_PREFIX + session_id
        await self.backend.append(key, json.dumps(asdict(message), ensure_ascii=False), self.ttl)
        await self.backend.trim(key, self.MAX_STORED_MESSAGES)
        return message

    async def history(self, session_id: str, last_n: int | None = None) -> list[ChatMessage]:
        raw = await self.backend.get_all(KEY_PREFIX + session_id)
        messages = []
        for item in raw:
            try:
                messages.append(ChatMessage(**json.loads(item)))
            except (TypeError, ValueError):
                continue
        return messages[-last_n:] if last_n else messages

    async def delete(self, session_id: str) -> bool:
        return await self.backend.delete(KEY_PREFIX + session_id)


_store: ChatSessionStore | None = None


async def get_session_store() -> ChatSessionStore:
    """Redis 연결을 시도하고 실패하면 메모리 저장소 사용"""
    global _store
    if _store is not None:
        return _store
    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(settings.REDIS_URL, decode_responses=True, socket_connect_timeout=2)
        await client.ping()
        _store = ChatSessionStore(RedisSessionBackend(client))
        logger.info("Chat session store: Redis")
    except Exception as e:
        logger.warning(f"Redis unavailable, using in-memory chat sessions: {e}")
        _store = ChatSessionStore(InMemorySessionBackend())
    return _store


def set_session_store(store: ChatSessionStore | None) -> None:
    """테스트용 주입"""
    global _store
    _store = store
