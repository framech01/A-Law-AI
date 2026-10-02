from app.services.chat_session import ChatSessionStore, InMemorySessionBackend


async def test_append_and_history():
    store = ChatSessionStore(InMemorySessionBackend(), ttl=60)
    await store.append("s1", "user", "질문")
    await store.append("s1", "assistant", "답변")
    history = await store.history("s1")
    assert [(m.role, m.content) for m in history] == [("user", "질문"), ("assistant", "답변")]
    assert [m.content for m in await store.history("s1", last_n=1)] == ["답변"]


async def test_delete_and_isolation():
    store = ChatSessionStore(InMemorySessionBackend(), ttl=60)
    await store.append("a", "user", "1")
    await store.append("b", "user", "2")
    assert await store.delete("a") is True
    assert await store.history("a") == []
    assert len(await store.history("b")) == 1


async def test_expired_session_is_empty():
    store = ChatSessionStore(InMemorySessionBackend(), ttl=-1)
    await store.append("s", "user", "x")
    assert await store.history("s") == []
