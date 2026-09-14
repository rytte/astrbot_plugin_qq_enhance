from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from aiocqhttp import Event

from astrbot.api.platform import MessageType, PlatformMetadata
from astrbot.api.provider import ProviderRequest
from astrbot.core.agent.tool import FunctionTool, ToolSet
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_platform_adapter import (
    AiocqhttpAdapter,
)
from astrbot_plugin_qq_enhance.catalog import TOOL_OPERATIONS
from astrbot_plugin_qq_enhance.main import QQEnhancePlugin
from astrbot_plugin_qq_enhance.runtime import QQRuntime, validate_config


@pytest.mark.asyncio
@pytest.mark.parametrize("exposure_mode", ["full", "balanced", "compact"])
@pytest.mark.parametrize("group_id", [30003, None])
async def test_poke_context_and_tools_follow_actual_notice_scope(
    exposure_mode: str, group_id: int | None
) -> None:
    raw = Event(
        {
            "post_type": "notice",
            "notice_type": "notify",
            "sub_type": "poke",
            "self_id": 20002,
            "user_id": 10001,
            "target_id": 20002,
        }
    )
    if group_id is not None:
        raw["group_id"] = group_id
    adapter = object.__new__(AiocqhttpAdapter)
    adapter.metadata = PlatformMetadata(
        name="aiocqhttp", description="", id="platform-a"
    )
    adapter.bot = AsyncMock()
    message = await adapter.convert_message(raw)
    event = adapter.create_event(message)
    original_origin = event.unified_msg_origin

    plugin = object.__new__(QQEnhancePlugin)
    plugin.config = validate_config({"toolsets": {"exposure_mode": exposure_mode}})
    plugin.runtime = object.__new__(QQRuntime)
    plugin.runtime.config = plugin.config

    await plugin.enrich_inbound_qq_components(event)
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
        assert request.prompt == (
            "[QQ component|QQ互动：群聊（群号 30003），用户 10001 戳了你]"
        )
        assert request.func_tool.get_tool("qq_group_member_manage") is not None
        assert request.func_tool.get_tool("qq_friend_interact") is None
    else:
        assert event.get_message_type() == MessageType.FRIEND_MESSAGE
        assert event.get_group_id() == ""
        assert request.prompt == "[QQ component|QQ互动：私聊，用户 10001 戳了你]"
        assert request.func_tool.get_tool("qq_friend_interact") is not None
        assert request.func_tool.get_tool("qq_group_member_manage") is None
    assert event.message_obj.message_str == request.prompt
    assert event.unified_msg_origin == original_origin
    assert event.is_wake is True
    assert event.is_at_or_wake_command is True
    adapter.bot.call_action.assert_not_awaited()
