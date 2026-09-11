from __future__ import annotations

import sqlite3
import time

import pytest

from astrbot_plugin_qq_enhance.storage import Storage


@pytest.mark.asyncio
async def test_initialize_removes_deprecated_context_image_source_columns(
    tmp_path,
) -> None:
    database_path = tmp_path / "data.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE context_images (
                image_ref TEXT PRIMARY KEY,
                platform_id TEXT NOT NULL,
                unified_msg_origin TEXT NOT NULL,
                conversation_id TEXT NOT NULL,
                source_message_id TEXT NOT NULL,
                source_kind TEXT NOT NULL,
                path TEXT NOT NULL,
                mime_type TEXT NOT NULL,
                width INTEGER NOT NULL,
                height INTEGER NOT NULL,
                size_bytes INTEGER NOT NULL,
                created_at INTEGER NOT NULL,
                last_accessed_at INTEGER NOT NULL,
                orphaned_at INTEGER
            )
            """
        )
        connection.execute(
            """
            INSERT INTO context_images VALUES (
                'img_0123456789abcdef01234567', 'platform-a', 'origin-a',
                'conversation-a', '456', 'message', 'image.bin', 'image/png',
                10, 20, 100, 1, 2, NULL
            )
            """
        )

    storage = Storage(database_path)
    await storage.initialize()

    with sqlite3.connect(database_path) as connection:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(context_images)")
        }
    assert "source_message_id" not in columns
    assert "source_kind" not in columns
    records = await storage.list_context_images()
    assert len(records) == 1
    assert records[0]["image_ref"] == "img_0123456789abcdef01234567"


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
