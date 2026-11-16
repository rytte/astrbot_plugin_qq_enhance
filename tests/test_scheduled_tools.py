from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
import pytest_asyncio

from astrbot.core.agent.tool import FunctionTool, ToolSet
from astrbot.core.cron.events import CronMessageEvent
from astrbot.core.platform.message_session import MessageSession
from astrbot.core.platform.platform_metadata import PlatformMetadata
from astrbot.core.provider.entities import ProviderRequest
from astrbot_plugin_qq_enhance.catalog import TOOL_OPERATIONS
from astrbot_plugin_qq_enhance.main import QQEnhancePlugin
from astrbot_plugin_qq_enhance.web_reader import WebReader

from test_runtime import FakeClient, FakeEvent, make_runtime
from test_web_reader import provide_page


def platform(client, platform_id="platform-a", name="aiocqhttp"):
    return SimpleNamespace(
        meta=lambda: PlatformMetadata(id=platform_id, name=name, description=""),
        get_client=lambda: client,
    )


@pytest_asyncio.fixture
async def scheduled_runtime(tmp_path):
    runtime, client, storage = await make_runtime(tmp_path)
    platforms = [platform(client)]
    runtime.context.platform_manager = SimpleNamespace(platform_insts=platforms)
    runtime.context.get_platform_inst = lambda platform_id: next(
        (item for item in platforms if item.meta().id == platform_id), None
    )
    return runtime, client, storage


def cron_event(
    runtime, session="platform-a:FriendMessage:10001", *, admin=True, sender=None
):
    session = MessageSession.from_str(session)
    payload = (
        {"origin": "api"} if sender is None else {"origin": "tool", "sender_id": sender}
    )
    event = CronMessageEvent(
        context=runtime.context,
        session=session,
        message="修改个人资料名称",
        message_type=session.message_type,
        extras={"cron_payload": payload, "cron_job": {"id": "test-job"}},
    )
    event.role = "admin" if admin else "member"
    return event


async def set_profile(runtime, event):
    return json.loads(
        await runtime.execute(
            event, "qq_account_manage", "set_profile", {"nickname": "定时昵称"}
        )
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["NapCat.Onebot", "SnowLuma"])
@pytest.mark.parametrize(
    "session",
    [
        "platform-a:FriendMessage:10001",
        "platform-a:GroupMessage:30001",
        "platform-a:GroupMessage:10001_30001",
    ],
)
async def test_scheduled_profile_uses_bound_qq_without_mutating_source(
    scheduled_runtime, session, provider
):
    runtime, client, storage = scheduled_runtime
    if provider == "SnowLuma":
        client.version_info = {
            "app_name": provider,
            "app_version": "1.14.22",
            "protocol_version": "v11",
        }
    event = cron_event(runtime, session)
    original_sender = event.get_sender_id()

    result = await set_profile(runtime, event)

    assert result["ok"], result
    assert client.calls == [
        ("get_version_info", {}),
        ("get_login_info", {}),
        ("set_qq_profile", {"nickname": "定时昵称"}),
    ]
    assert event.get_platform_name() == "cron"
    assert event.get_self_id() == "astrbot"
    assert event.get_sender_id() == original_sender
    assert event.get_group_id() == ""
    assert event.unified_msg_origin == session
    assert (await storage.list_audit())[0]["platform_id"] == "platform-a"


@pytest.mark.asyncio
@pytest.mark.parametrize("configured", [False, True])
async def test_background_profile_uses_unique_or_configured_qq(
    scheduled_runtime, configured
):
    runtime, client, storage = scheduled_runtime
    if configured:
        runtime.config["platform"]["platform_id"] = "platform-a"
        runtime.context.platform_manager.platform_insts.append(
            platform(FakeClient(), "platform-b")
        )
    event = cron_event(runtime, "cron:OtherMessage:test-job")

    result = await set_profile(runtime, event)

    assert result["ok"], result
    assert client.calls[-1] == ("set_qq_profile", {"nickname": "定时昵称"})
    assert event.get_platform_id() == "cron"
    assert event.unified_msg_origin == "cron:OtherMessage:test-job"
    assert (await storage.list_audit())[0]["caller_id"] == "cron:test-job"


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [0, 2])
async def test_background_task_requires_unambiguous_adapter(scheduled_runtime, count):
    runtime, client, _ = scheduled_runtime
    platforms = runtime.context.platform_manager.platform_insts
    platforms[:] = [platform(client, f"platform-{index}") for index in range(count)]

    result = await set_profile(
        runtime, cron_event(runtime, "cron:OtherMessage:test-job")
    )

    assert result["error"]["code"] == "unsupported_platform"
    assert "选择 QQ 会话" in result["error"]["message"]
    assert client.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "session,configured",
    [
        ("other:FriendMessage:10001", ""),
        ("missing:FriendMessage:10001", ""),
        ("platform-a:FriendMessage:10001", "platform-b"),
        ("cron:OtherMessage:test-job", "missing"),
        ("cron:OtherMessage:test-job", "other"),
    ],
)
async def test_scheduled_task_never_falls_back_from_invalid_binding(
    scheduled_runtime, session, configured
):
    runtime, client, _ = scheduled_runtime
    runtime.config["platform"]["platform_id"] = configured
    runtime.context.platform_manager.platform_insts.append(
        platform(client, "other", "webchat")
    )

    result = await set_profile(runtime, cron_event(runtime, session))

    assert result["error"]["code"] == "unsupported_platform"
    assert client.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "session,sender",
    [
        ("platform-a:FriendMessage:10001", "20001"),
        ("platform-a:FriendMessage:10001", None),
        ("cron:OtherMessage:test-job", "20001"),
    ],
)
async def test_scheduled_task_keeps_creator_permissions(
    scheduled_runtime, session, sender
):
    runtime, client, _ = scheduled_runtime

    result = await set_profile(
        runtime, cron_event(runtime, session, admin=False, sender=sender)
    )

    assert result["error"]["code"] == "permission_denied"
    assert all(action != "set_qq_profile" for action, _ in client.calls)


@pytest.mark.asyncio
async def test_scheduled_task_still_checks_protocol_version(scheduled_runtime):
    runtime, client, _ = scheduled_runtime
    client.version_info["app_version"] = "4.0.0"

    result = await set_profile(runtime, cron_event(runtime))

    assert not result["ok"]
    assert client.calls == [("get_version_info", {})]


@pytest.mark.asyncio
async def test_bound_tasks_keep_multiple_qq_accounts_separate(scheduled_runtime):
    runtime, first, _ = scheduled_runtime
    second = FakeClient()
    second.responses["get_login_info"] = {"user_id": 88888}
    runtime.context.platform_manager.platform_insts.append(
        platform(second, "platform-b")
    )

    first_result = await set_profile(runtime, cron_event(runtime))
    second_result = await set_profile(
        runtime, cron_event(runtime, "platform-b:FriendMessage:10001")
    )

    assert first_result["ok"] and second_result["ok"]
    for client in (first, second):
        assert client.calls.count(("set_qq_profile", {"nickname": "定时昵称"})) == 1
        assert client.calls.count(("get_version_info", {})) == 1


@pytest.mark.asyncio
async def test_scheduled_operation_still_requires_bound_user_confirmation(
    scheduled_runtime,
):
    runtime, client, _ = scheduled_runtime
    event = cron_event(runtime, "platform-a:GroupMessage:30001", sender="10001")

    result = json.loads(
        await runtime.execute(
            event,
            "qq_group_manage",
            "name",
            {"group_id": 30001, "group_name": "定时群名"},
        )
    )

    assert result["error"]["code"] == "confirmation_required"
    assert all(action != "set_group_name" for action, _ in client.calls)
    confirmed = await runtime.confirm(FakeEvent(group_id="30001"), result["pending_id"])
    assert confirmed["status"] == "executed", confirmed
    assert client.calls[-1] == (
        "set_group_name",
        {"group_id": 30001, "group_name": "定时群名"},
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("session_id", ["30001", "10001_30001"])
@pytest.mark.parametrize("sender,allowed", [("10001", True), ("20001", False)])
async def test_scheduled_group_permissions_use_creator_and_real_bot(
    scheduled_runtime, session_id, sender, allowed
):
    runtime, client, _ = scheduled_runtime
    runtime.config["confirmation"]["operations"] = []
    event = cron_event(
        runtime, f"platform-a:GroupMessage:{session_id}", admin=False, sender=sender
    )

    result = json.loads(
        await runtime.execute(
            event,
            "qq_group_manage",
            "name",
            {"group_id": 30001, "group_name": "定时群名"},
        )
    )

    assert result["ok"] is allowed, result
    assert (
        "get_group_member_info",
        {"group_id": 30001, "user_id": int(sender), "no_cache": True},
    ) in client.calls
    if allowed:
        assert (
            "get_group_member_info",
            {"group_id": 30001, "user_id": 99999, "no_cache": True},
        ) in client.calls
        assert client.calls[-1] == (
            "set_group_name",
            {"group_id": 30001, "group_name": "定时群名"},
        )
    else:
        assert result["error"]["code"] == "permission_denied"
        assert all(action != "set_group_name" for action, _ in client.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "session,target,expected",
    [
        (
            "platform-a:FriendMessage:10001",
            {"type": "current"},
            ("send_private_msg", "user_id", 10001),
        ),
        (
            "platform-a:GroupMessage:10001_30001",
            {"type": "current"},
            ("send_group_msg", "group_id", 30001),
        ),
        (
            "cron:OtherMessage:test-job",
            {"type": "group", "id": 30001},
            ("send_group_msg", "group_id", 30001),
        ),
        ("cron:OtherMessage:test-job", {"type": "current"}, None),
    ],
)
async def test_scheduled_messages_require_real_targets(
    scheduled_runtime, session, target, expected
):
    runtime, client, _ = scheduled_runtime
    event = cron_event(runtime, session)

    result = json.loads(
        await runtime.execute(
            event,
            "qq_send_message",
            "send",
            {"target": target, "components": [{"type": "text", "text": "定时消息"}]},
        )
    )

    if expected is None:
        assert result["error"]["code"] == "invalid_parameters"
        assert all(not action.startswith("send_") for action, _ in client.calls)
    else:
        assert result["ok"], result
        action, key, value = expected
        assert client.calls[-1] == (
            action,
            {key: value, "message": [{"type": "text", "data": {"text": "定时消息"}}]},
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("admin", [True, False])
async def test_scheduled_tool_selection_keeps_permission_filtering(
    scheduled_runtime, admin
):
    runtime, _, _ = scheduled_runtime
    plugin = object.__new__(QQEnhancePlugin)
    plugin.runtime = runtime
    plugin.config = runtime.config
    event = cron_event(runtime, admin=admin, sender="10001" if admin else "20001")
    request = ProviderRequest(
        func_tool=ToolSet(
            [
                FunctionTool(name=name, description="", parameters={"type": "object"})
                for name in [*TOOL_OPERATIONS, "unrelated"]
            ]
        )
    )

    await plugin.select_tools(event, request)

    assert (request.func_tool.get_tool("qq_account_manage") is not None) is admin
    assert request.func_tool.get_tool("qq_status") is not None
    assert request.func_tool.get_tool("unrelated") is not None
    assert event.get_platform_name() == "cron"


@pytest.mark.asyncio
async def test_background_web_pages_keep_job_and_bot_scope(
    scheduled_runtime, tmp_path, monkeypatch
):
    runtime, _, _ = scheduled_runtime
    reader = WebReader(runtime)
    provide_page(reader, tmp_path, monkeypatch, "定时任务读取的网页正文")
    event = cron_event(runtime, "cron:OtherMessage:test-job")
    try:
        first = json.loads(
            await reader.execute(event, "read_url", {"url": "https://example.test"})
        )
        assert first["ok"], first
        page_id = first["data"]["page_id"]
        assert reader.pages[page_id].owner == (
            "platform-a",
            "99999",
            event.unified_msg_origin,
            "cron:test-job",
        )
        other = cron_event(runtime, "cron:OtherMessage:other-job")
        denied = json.loads(
            await reader.execute(other, "read_page_section", {"page_id": page_id})
        )
        assert denied["error"]["code"] == "page_unavailable"
        continued = json.loads(
            await reader.execute(event, "read_page_section", {"page_id": page_id})
        )
        assert continued["ok"], continued
    finally:
        await reader.close()


@pytest.mark.asyncio
async def test_platform_name_alone_cannot_enable_cron_compatibility(scheduled_runtime):
    runtime, client, _ = scheduled_runtime

    result = await set_profile(runtime, FakeEvent(platform_name="cron"))

    assert result["error"]["code"] == "unsupported_platform"
    assert client.calls == []
