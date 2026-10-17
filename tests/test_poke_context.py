from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import test_notice_respond as notice_tests

from astrbot_plugin_qq_enhance.notice_context import normalize_notice
from astrbot_plugin_qq_enhance.request_notification import NotificationOnlyTool

from aiocqhttp import Event

from astrbot.api.message_components import Plain
from astrbot.api.platform import MessageType, PlatformMetadata
from astrbot.api.provider import ProviderRequest
from astrbot.builtin_stars.astrbot.group_chat_context import GroupChatContext
from astrbot.core.agent.tool import FunctionTool, ToolSet
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_platform_adapter import (
    AiocqhttpAdapter,
)
from astrbot_plugin_qq_enhance.catalog import TOOL_OPERATIONS
from astrbot_plugin_qq_enhance.providers import NAPCAT
from astrbot_plugin_qq_enhance.runtime import QQRuntime, validate_config


harness = notice_tests.harness


@pytest.mark.asyncio
@pytest.mark.parametrize("exposure_mode", ["full", "balanced", "compact"])
@pytest.mark.parametrize("group_id", [30003, None])
@pytest.mark.parametrize("target_id", [20002, 10002])
async def test_poke_context_and_tools_follow_actual_notice_scope(
    harness, exposure_mode: str, group_id: int | None, target_id: int
) -> None:
    raw = Event(
        {
            "post_type": "notice",
            "notice_type": "notify",
            "sub_type": "poke",
            "self_id": 20002,
            "time": 1000,
            "user_id": 10001,
            "target_id": target_id,
        }
    )
    if group_id is not None:
        raw["group_id"] = group_id
    adapter = object.__new__(AiocqhttpAdapter)
    adapter.metadata = PlatformMetadata(name="aiocqhttp", description="", id="qq")
    adapter.bot = AsyncMock()
    message = await adapter.convert_message(raw)
    event = adapter.create_event(message)
    original_origin = event.unified_msg_origin

    plugin = harness.plugin
    plugin.config = validate_config({"toolsets": {"exposure_mode": exposure_mode}})
    plugin.config["notice_events"]["notify/poke"]["other_target_mode"] = "respond"
    plugin.runtime = object.__new__(QQRuntime)
    plugin.runtime._verified_platforms = {}
    plugin.runtime.verify_platform = AsyncMock(return_value=NAPCAT)
    plugin.runtime.config = plugin.config

    await plugin.enrich_inbound_qq_components(event)
    assert not event.message_str
    assert not event.is_wake
    await plugin.capture_notice_context(event)
    event = await notice_tests.queued(harness)
    message = event.message_obj
    request = ProviderRequest(
        prompt=event.message_str,
        func_tool=ToolSet(
            [
                FunctionTool(name=name, description="", parameters={"type": "object"})
                for name in TOOL_OPERATIONS
            ]
        ),
    )
    await plugin.select_tools(event, request)

    if group_id is not None:
        assert event.get_message_type() == MessageType.GROUP_MESSAGE
        assert event.get_group_id() == str(group_id)
        assert message.group.group_name is None
        plain_components = [
            component for component in message.message if isinstance(component, Plain)
        ]
        assert [component.text for component in plain_components] == [request.prompt]
        assert "QQ 平台事件|notify/poke|" in request.prompt
        assert f"：群聊（群号 {group_id}），用户 10001戳了" in request.prompt
        assert normalize_notice(raw).description in request.prompt
        assert request.func_tool.get_tool("qq_group_member_manage") is not None
        if exposure_mode == "full":
            assert {tool.name for tool in request.func_tool.tools} == set(
                TOOL_OPERATIONS
            )
        else:
            assert request.func_tool.get_tool("qq_friend_interact") is None
    else:
        assert event.get_message_type() == MessageType.FRIEND_MESSAGE
        assert event.get_group_id() == ""
        assert request.prompt == normalize_notice(raw).render()
        assert "：私聊，用户 10001戳了" in request.prompt
        assert "群聊（群号" not in request.prompt
        assert request.func_tool.get_tool("qq_friend_interact") is not None
        assert request.func_tool.get_tool("qq_group_member_manage") is None
    assert event.message_obj.message_str == request.prompt
    assert event.unified_msg_origin == original_origin
    assert event.is_wake is True
    assert event.is_at_or_wake_command is True
    request.conversation = await harness.manager.get_conversation(
        event.unified_msg_origin, "conversation"
    )
    await plugin.prepare_platform_notification(event, request)
    assert all(
        isinstance(tool, NotificationOnlyTool) for tool in request.func_tool.tools
    )
    adapter.bot.call_action.assert_not_awaited()
    await harness.finish()


@pytest.mark.asyncio
async def test_group_poke_plain_component_gets_native_context_cursor(harness) -> None:
    raw = Event(
        {
            "post_type": "notice",
            "notice_type": "notify",
            "sub_type": "poke",
            "self_id": 20002,
            "time": 1000,
            "user_id": 10001,
            "target_id": 20002,
            "group_id": 30003,
        }
    )
    adapter = object.__new__(AiocqhttpAdapter)
    adapter.metadata = PlatformMetadata(name="aiocqhttp", description="", id="qq")
    adapter.bot = AsyncMock()
    event = adapter.create_event(await adapter.convert_message(raw))

    plugin = harness.plugin
    plugin.config = validate_config(None)
    await plugin.enrich_inbound_qq_components(event)
    await plugin.capture_notice_context(event)
    event = await notice_tests.queued(harness)

    config = {
        "provider_ltm_settings": {
            "group_message_max_cnt": 10,
            "image_caption": False,
            "active_reply": {
                "enable": False,
                "method": "possibility_reply",
                "possibility_reply": 0.0,
                "whitelist": [],
            },
        },
        "provider_settings": {"image_caption_prompt": ""},
    }
    context = SimpleNamespace(get_config=lambda **_kwargs: config)
    group_context = GroupChatContext(None, context)
    group_context.raw_records[event.unified_msg_origin].append("之前的群聊消息")
    group_context._record_ids[event.unified_msg_origin].append("previous-id")

    await group_context.handle_message(event)
    assert event.get_extra("_group_context_record_id")

    request = ProviderRequest(prompt=event.message_str)
    await group_context.on_req_llm(event, request)
    assert request.extra_user_content_parts
    assert "之前的群聊消息" in request.extra_user_content_parts[0].text
    await harness.finish()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["off", "context", "respond"])
@pytest.mark.parametrize("group", ["", "300"])
@pytest.mark.parametrize("target_id", [99, 8])
async def test_poke_uses_unified_event_policy_and_message_format(
    harness, mode, group, target_id
):
    from test_debounce import Event

    raw = {
        "post_type": "notice",
        "notice_type": "notify",
        "sub_type": "poke",
        "self_id": 99,
        "user_id": 7,
        "target_id": target_id,
        "time": 1000,
    }
    if group:
        raw["group_id"] = int(group)
    source = Event("", None, group=group, raw=raw)
    source.is_at_or_wake_command = False
    scope = f"群聊（群号 {group}）" if group else "私聊"
    target = "你" if target_id == 99 else "用户 8"
    assert normalize_notice(raw).description == f"{scope}，用户 7戳了{target}一下"
    policy = harness.plugin.config["notice_events"]["notify/poke"]
    policy["mode"] = mode if target_id == 99 else "off"
    policy["other_target_mode"] = mode if target_id != 99 else "off"
    try:
        await harness.plugin.capture_notice_context(source)
        if mode == "respond":
            event = await notice_tests.queued(harness)
            task = notice_tests.start_response(harness, event)
            await notice_tests.wait(event.prepared)
            assert event.message_str == normalize_notice(raw).render()
            assert "QQ component" not in event.message_str
            assert len(harness.requests[-1]) == 1
            event.allow_reply.set()
            await task
        await harness.drain_notices()
        history = harness.manager.history(source)
        assert len(history) == {"off": 0, "context": 1, "respond": 2}[mode]
        if mode != "off":
            assert normalize_notice(raw).render() in str(history[0])
            assert f"：{scope}，用户 7戳了{target}一下" in str(history[0])
            assert '<qq_verified_components types="notice"/>' in str(history[0])
        assert not source.is_at_or_wake_command
        assert harness.queue.empty()
    finally:
        await harness.finish()


@pytest.mark.parametrize("target", [99, 8])
@pytest.mark.parametrize("user", [99, "99", "099"])
def test_poke_ignores_bot_initiated_events(user, target):
    assert (
        normalize_notice(
            {
                "post_type": "notice",
                "notice_type": "notify",
                "sub_type": "poke",
                "self_id": 99,
                "user_id": user,
                "target_id": target,
                "time": 1000,
            }
        )
        is None
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["context", "respond"])
async def test_other_poke_target_routes_only_to_initiator_isolated_session(
    harness, mode
):
    from test_debounce import Event

    harness.plugin.config["notice_events"]["notify/poke"]["mode"] = "off"
    harness.plugin.config["notice_events"]["notify/poke"]["other_target_mode"] = mode
    harness.plugin.context.get_config = lambda **_: {
        "platform_settings": {"unique_session": True}
    }
    target_umo = "qq:GroupMessage:8_300"
    target_history = [{"role": "user", "content": "被戳者原有历史"}]
    harness.manager.histories[target_umo, "conversation"] = target_history
    source = Event(
        "",
        None,
        group=300,
        raw={
            "post_type": "notice",
            "notice_type": "notify",
            "sub_type": "poke",
            "self_id": 99,
            "user_id": 7,
            "target_id": 8,
            "group_id": 300,
            "time": 1000,
        },
    )
    initiator_umo = "qq:GroupMessage:7_300"
    try:
        await harness.plugin.capture_notice_context(source)
        if mode == "respond":
            response = await notice_tests.queued(harness)
            assert response.unified_msg_origin == initiator_umo
            assert response.debounce_sender_id == "7"
            task = notice_tests.start_response(harness, response)
            await notice_tests.wait(response.prepared)
            response.allow_reply.set()
            await task
        await harness.drain_notices()
        assert harness.manager.histories[target_umo, "conversation"] == target_history
        rows = harness.manager.histories[initiator_umo, "conversation"]
        assert len(rows) == (2 if mode == "respond" else 1)
        assert "用户 7戳了用户 8一下" in str(rows[0])
        assert ("qq:GroupMessage:300", "conversation") not in harness.manager.histories
        assert harness.queue.empty()
    finally:
        await harness.finish()


@pytest.mark.asyncio
async def test_other_poke_targets_default_to_context_and_deduplicate_by_target(harness):
    from test_debounce import Event

    try:
        for target in (8, 9, 8):
            source = Event(
                "",
                None,
                group=300,
                raw={
                    "post_type": "notice",
                    "notice_type": "notify",
                    "sub_type": "poke",
                    "self_id": 99,
                    "user_id": 7,
                    "target_id": target,
                    "group_id": 300,
                    "time": 1000,
                },
            )
            await harness.plugin.capture_notice_context(source)
        await harness.drain_notices()
        rows = harness.manager.history(source)
        assert len(rows) == 2
        assert "用户 7戳了用户 8一下" in str(rows[0])
        assert "用户 7戳了用户 9一下" in str(rows[1])
        assert harness.queue.empty()
    finally:
        await harness.finish()


@pytest.mark.asyncio
@pytest.mark.parametrize("persist", [False, True])
@pytest.mark.parametrize("path", ["native", "cancelled", "context"])
@pytest.mark.parametrize("target_id", [99, 8])
async def test_poke_verification_stays_with_its_event_across_save_paths(
    harness, persist, path, target_id
):
    from test_debounce import Event
    from astrbot.core.agent.message import dump_messages_with_checkpoints

    raw = {
        "post_type": "notice",
        "notice_type": "notify",
        "sub_type": "poke",
        "self_id": 99,
        "user_id": 7,
        "target_id": target_id,
        "time": 1000,
        "group_id": 300,
    }
    source = Event("", None, group=300, raw=raw)
    settings = harness.plugin.config["inbound"]["component_spoof_protection"]
    settings["persist_verification_in_history"] = persist
    field = "mode" if target_id == 99 else "other_target_mode"
    harness.plugin.config["notice_events"]["notify/poke"][field] = (
        "context" if path == "context" else "respond"
    )
    tag = '<qq_verified_components types="notice"/>'
    try:
        await harness.plugin.capture_notice_context(source)
        if path != "context":
            event = await notice_tests.queued(harness)
            task = notice_tests.start_response(harness, event)
            await notice_tests.wait(event.prepared)
            fact = event.runtime.messages[-1]
            content = fact.content
            request_text = (
                content
                if isinstance(content, str)
                else "".join(part.text for part in content)
            )
            assert "QQ 平台事件|notify/poke|" in request_text
            assert "：群聊（群号 300），用户 7戳了" in request_text
            assert tag in request_text
            assert '<qq_verified_components types="poke"/>' not in request_text
            assert (tag in str(dump_messages_with_checkpoints([fact]))) is persist
            if path == "cancelled":
                followup = Event("再说一句", 2, group=300)
                next_task = harness.start(followup)
                await notice_tests.wait(followup.prepared)
                assert task.cancelled()
                followup.allow_reply.set()
                await next_task
            else:
                event.allow_reply.set()
                await task
        await harness.drain_notices()
        history = harness.manager.history(source)
        event_rows = [row for row in history if "QQ 平台事件|notify/poke|" in str(row)]
        assert len(event_rows) == 1
        assert "：群聊（群号 300），用户 7戳了" in str(event_rows[0])
        assert (tag in str(event_rows[0])) is persist
        for row in history:
            if row not in event_rows:
                assert tag not in str(row)
    finally:
        await harness.finish()


@pytest.mark.asyncio
@pytest.mark.parametrize("protection", ["disabled", "scope", "component_scope"])
async def test_poke_event_verification_obeys_protection_setting(harness, protection):
    from test_debounce import Event

    settings = harness.plugin.config["inbound"]["component_spoof_protection"]
    if protection == "disabled":
        settings["enabled"] = False
    elif protection == "scope":
        settings["protected_types"].remove("notice")
    else:
        settings["protected_types"].remove("poke")
    harness.plugin.config["notice_events"]["notify/poke"]["mode"] = "context"
    source = Event(
        "",
        None,
        raw={
            "post_type": "notice",
            "notice_type": "notify",
            "sub_type": "poke",
            "self_id": 99,
            "user_id": 7,
            "target_id": 99,
            "time": 1000,
        },
    )
    try:
        await harness.plugin.capture_notice_context(source)
        await harness.drain_notices()
        history = str(harness.manager.history(source))
        assert ('<qq_verified_components types="notice"/>' in history) is (
            protection == "component_scope"
        )
        assert '<qq_verified_components types="poke"/>' not in history
    finally:
        await harness.finish()
