from __future__ import annotations

import hashlib
import sqlite3
import time

import pytest

from astrbot_plugin_qq_enhance.storage import Storage


@pytest.mark.asyncio
@pytest.mark.parametrize("has_legacy_images", [False, True])
async def test_qq_no_longer_creates_or_cleans_image_archive(
    tmp_path, has_legacy_images
):
    database_path = tmp_path / "data.sqlite3"
    if has_legacy_images:
        with sqlite3.connect(database_path) as db:
            db.execute(
                "CREATE TABLE context_images (image_ref TEXT PRIMARY KEY, path TEXT)"
            )
            db.execute(
                "INSERT INTO context_images VALUES ('legacy-reference', 'legacy-file.png')"
            )
    storage = Storage(database_path)
    await storage.initialize()
    await storage.cleanup(1, 1)
    with sqlite3.connect(database_path) as db:
        exists = db.execute(
            "SELECT 1 FROM sqlite_master WHERE name='context_images'"
        ).fetchone()
        assert bool(exists) == has_legacy_images
        if exists:
            assert db.execute("SELECT * FROM context_images").fetchall() == [
                ("legacy-reference", "legacy-file.png")
            ]


@pytest.mark.asyncio
async def test_request_notification_binding_is_scoped_persistent_and_hash_only(
    tmp_path,
):
    database_path = tmp_path / "data.sqlite3"
    storage = Storage(database_path)
    await storage.initialize()
    request_id = await storage.add_event(
        {
            "created_at": int(time.time()),
            "platform_id": "platform-a",
            "post_type": "request",
            "event_type": "group",
            "sub_type": "add",
            "actor_id": "20001",
            "group_id": "30001",
            "event_key": "request-one",
            "flag": "private-flag",
            "comment_hash": "comment-digest",
        }
    )
    prompt = "平台事件；申请附言不应重复保存到插件元数据"
    await storage.bind_request_notification(
        request_id, "session-a", "conversation-a", "initial"
    )
    await storage.bind_request_notification(
        request_id, "session-a", "conversation-a", prompt
    )
    storage = Storage(database_path)
    expected = [
        {
            "prompt_hash": hashlib.sha256(prompt.encode()).hexdigest(),
            "request_type": "group",
            "status": "pending",
        }
    ]
    assert (
        await storage.get_request_notification_bindings(
            "platform-a", "session-a", "conversation-a"
        )
        == expected
    )
    for scope in [
        ("platform-b", "session-a", "conversation-a"),
        ("platform-a", "session-b", "conversation-a"),
        ("platform-a", "session-a", "conversation-b"),
    ]:
        assert await storage.get_request_notification_bindings(*scope) == []
    with sqlite3.connect(database_path) as connection:
        rows = connection.execute("SELECT * FROM request_notifications").fetchall()
    assert len(rows) == 1
    assert prompt not in str(rows)
    assert "private-flag" not in str(rows)
    await storage.update_request("private-flag", "approved")
    expected[0]["status"] = "approved"
    assert (
        await storage.get_request_notification_bindings(
            "platform-a", "session-a", "conversation-a"
        )
        == expected
    )
    await storage.cleanup(event_retention_days=0, audit_retention_days=0)
    with sqlite3.connect(database_path) as connection:
        connection.execute("UPDATE requests SET created_at = 1")
    await storage.cleanup(event_retention_days=1, audit_retention_days=1)
    with sqlite3.connect(database_path) as connection:
        assert (
            connection.execute("SELECT * FROM request_notifications").fetchall() == []
        )


@pytest.mark.asyncio
async def test_pending_is_bound_and_single_use(tmp_path) -> None:
    storage = Storage(tmp_path / "data.sqlite3")
    await storage.initialize()
    now = int(time.time())
    await storage.create_pending(
        {
            "pending_id": "a1b2c3d4",
            "caller_id": "10001",
            "session_id": "session-a",
            "platform_id": "platform-a",
            "operation_id": "qq_friend_manage.delete",
            "action": "delete_friend",
            "params": {"action_params": {"user_id": 10001}},
            "target_kind": "private",
            "target_id": "10001",
            "summary": "test",
            "created_at": now,
            "expires_at": now + 60,
        }
    )
    assert (
        await storage.claim_pending(
            "a1b2c3d4", "another-user", "session-a", "platform-a"
        )
        is None
    )
    claimed = await storage.claim_pending(
        "a1b2c3d4", "10001", "session-a", "platform-a"
    )
    assert claimed is not None
    assert claimed["params"]["action_params"]["user_id"] == 10001
    assert (
        await storage.claim_pending("a1b2c3d4", "10001", "session-a", "platform-a")
        is None
    )


@pytest.mark.asyncio
async def test_expired_pending_cannot_be_claimed(tmp_path) -> None:
    storage = Storage(tmp_path / "data.sqlite3")
    await storage.initialize()
    now = int(time.time())
    await storage.create_pending(
        {
            "pending_id": "deadbeef",
            "caller_id": "10001",
            "session_id": "session-a",
            "platform_id": "platform-a",
            "operation_id": "qq_friend_manage.delete",
            "action": "delete_friend",
            "params": {"user_id": 10001},
            "target_kind": "private",
            "target_id": "10001",
            "summary": "expired",
            "created_at": now - 100,
            "expires_at": now - 1,
        }
    )
    assert (
        await storage.claim_pending("deadbeef", "10001", "session-a", "platform-a")
        is None
    )


@pytest.mark.asyncio
async def test_dashboard_pending_list_omits_action_parameters_and_expired_rows(
    tmp_path,
) -> None:
    storage = Storage(tmp_path / "data.sqlite3")
    await storage.initialize()
    now = int(time.time())
    for pending_id, expires_at in (
        ("a1b2c3d4", now + 60),
        ("deadbeef", now - 1),
    ):
        await storage.create_pending(
            {
                "pending_id": pending_id,
                "caller_id": "10001",
                "session_id": "session-a",
                "platform_id": "platform-a",
                "operation_id": "qq_friend_manage.delete",
                "action": "delete_friend",
                "params": {"action_params": {"user_id": 10001}},
                "target_kind": "private",
                "target_id": "10001",
                "summary": "Delete one friend",
                "created_at": now,
                "expires_at": expires_at,
            }
        )

    rows = await storage.list_live_pending()

    assert [row["pending_id"] for row in rows] == ["a1b2c3d4"]
    assert "action" not in rows[0]
    assert "params_json" not in rows[0]
    assert "session_id" not in rows[0]


@pytest.mark.asyncio
async def test_request_event_is_stored_once_and_returns_request_id(tmp_path) -> None:
    storage = Storage(tmp_path / "data.sqlite3")
    await storage.initialize()
    record = {
        "created_at": int(time.time()),
        "platform_id": "platform-a",
        "post_type": "request",
        "event_type": "friend",
        "sub_type": "",
        "actor_id": "10001",
        "group_id": "",
        "event_key": "same-request-event",
        "data": {},
        "flag": "request-flag",
        "comment_hash": "comment-hash",
    }

    request_id = await storage.add_event(record)
    duplicate_id = await storage.add_event(record)

    assert request_id == 1
    assert duplicate_id is None
    requests = await storage.list_requests("friend")
    assert len(requests) == 1
    assert requests[0]["request_id"] == request_id
    assert await storage.get_pending_request(request_id, "platform-a") == requests[0]
    assert await storage.get_pending_request(request_id, "platform-b") is None
