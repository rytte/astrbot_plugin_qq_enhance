from __future__ import annotations

import time

import pytest

from astrbot_plugin_qq_extension_tools.storage import Storage


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
