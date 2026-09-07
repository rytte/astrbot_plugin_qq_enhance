from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from astrbot.core.agent.tool import FunctionTool, ToolSet
from astrbot.core.message.components import File
from astrbot.core.provider.entities import ProviderRequest
from astrbot.core.provider.func_tool_manager import FunctionToolManager
from astrbot_plugin_qq_enhance.catalog import TOOL_OPERATIONS
from astrbot_plugin_qq_enhance.main import QQEnhancePlugin
from astrbot_plugin_qq_enhance.runtime import QQRuntime, validate_config
from astrbot_plugin_qq_enhance.web_reader import (
    WEB_READER_PROMPT,
    WEB_TOOL_NAMES,
    WEB_TOOL_SCHEMAS,
)


class SelectionEvent:
    message_str = "查询群成员并发送消息"
    unified_msg_origin = "platform-a:GroupMessage:30001"
    message_obj = SimpleNamespace(raw_message={"sender": {"role": "member"}})

    def get_platform_name(self) -> str:
        return "aiocqhttp"

    def get_sender_id(self) -> str:
        return "10001"

    def get_group_id(self) -> str:
        return "30001"

    def is_admin(self) -> bool:
        return False


class PrivateAdminSelectionEvent(SelectionEvent):
    message_str = "列出机器人加入的群聊"
    unified_msg_origin = "platform-a:FriendMessage:10001"

    def get_group_id(self) -> str:
        return ""

    def is_admin(self) -> bool:
        return True


class PrivateAdminProfileSelectionEvent(PrivateAdminSelectionEvent):
    message_str = "把昵称修改为测试机器人"


class PrivateAdminRemarkSelectionEvent(PrivateAdminSelectionEvent):
    message_str = "把我的备注修改为测试备注"


class PrivateAdminFileSelectionEvent(PrivateAdminSelectionEvent):
    message_str = "[ComponentType.File]"
    message_obj = SimpleNamespace(
        raw_message={"sender": {"role": "member"}},
        message=[File(name="list.txt", url="https://example.test/list.txt")],
    )


class PrivateAdminProfileFollowUpSelectionEvent(PrivateAdminSelectionEvent):
    message_str = "改回测试机器人"


class GroupOwnerSelectionEvent(SelectionEvent):
    message_str = "执行当前群签到"
    message_obj = SimpleNamespace(raw_message={"sender": {"role": "owner"}})


class GroupAstrBotAdminSelectionEvent(SelectionEvent):
    message_str = "查询好友20001的消息历史"

    def is_admin(self) -> bool:
        return True


@pytest.mark.parametrize("web_enabled", [True, False])
@pytest.mark.asyncio
async def test_initialize_uses_registered_tool_manager_api(web_enabled) -> None:
    plugin = object.__new__(QQEnhancePlugin)
    manager = FunctionToolManager()
    for tool_name in TOOL_OPERATIONS:
        manager.func_list.append(
            FunctionTool(
                name=tool_name,
                description="",
                parameters={"type": "object"},
            )
        )
    plugin.context = SimpleNamespace(
        provider_manager=SimpleNamespace(llm_tools=manager)
    )
    plugin.config = validate_config({"web_reader": {"enabled": web_enabled}})
    plugin.storage = SimpleNamespace(initialize=AsyncMock())
    plugin.runtime = object.__new__(QQRuntime)
    plugin.runtime.config = plugin.config
    plugin.runtime.cleanup = AsyncMock()
    plugin.cleanup_task = None
    plugin.notification_tasks = set()
    plugin.notification_locks = {}
    plugin.recall_messages = {}
    plugin.web_reader = SimpleNamespace(cleanup=lambda: None, close=AsyncMock())

    await plugin.initialize()

    plugin.storage.initialize.assert_awaited_once()
    assert all(manager.get_func(tool_name) is not None for tool_name in TOOL_OPERATIONS)
    for name in WEB_TOOL_NAMES:
        tool = manager.get_func(name)
        assert tool.active is web_enabled
        if web_enabled:
            assert tool.parameters == WEB_TOOL_SCHEMAS[name]
            assert "operation" not in tool.parameters["properties"]
    assert all(
        manager.get_func(name).active
        for name in set(TOOL_OPERATIONS) - WEB_TOOL_NAMES
    )
    send_tool = manager.get_func("qq_send_message")
    params_schema = send_tool.parameters["properties"]["params"]
    params_description = params_schema["description"]
    assert params_schema["required"] == ["target", "components"]
    assert params_schema["additionalProperties"] is False
    assert params_schema["properties"]["target"]["required"] == ["type"]
    assert params_schema["properties"]["target"]["additionalProperties"] is False
    assert params_schema["properties"]["components"]["minItems"] == 1
    assert params_schema["properties"]["components"]["maxItems"] == 30
    assert params_schema["properties"]["components"]["items"]["required"] == [
        "type"
    ]
    component_schema = params_schema["properties"]["components"]["items"]
    assert component_schema["additionalProperties"] is False
    assert "text" in component_schema["properties"]
    assert "id" in component_schema["properties"]
    assert (
        '{"operation":"send","params":{"target":{"type":"current"},'
        '"components":[{"type":"rps"}]}}' in params_description
    )
    assert "operation 和 params 必须同级" in params_description
    assert "target 和 components 必须位于 params 内" in params_description
    assert "不得使用 data 包装" in params_description
    assert '"type":"share"' in params_description
    assert "不要自行拼接分享卡片 JSON" in params_description
    assert "不得擅自替换用户提供的 URL" in params_description
    assert '"music_type":"custom"' in params_description
    assert '"music_type":"qq_search"' in params_description
    assert "不得凭记忆猜歌曲 ID" in params_description
    assert "音乐卡片必须作为唯一组件单独发送" in params_description
    assert "调用成功仅表示 NapCat 已接受发送请求" in params_description
    assert "最终回复不得重复其中的正文或卡片" in params_description
    request_tool = manager.get_func("qq_group_request")
    request_description = request_tool.parameters["properties"]["params"]["description"]
    assert "通知中的 request_id" in request_description
    forward_tool = manager.get_func("qq_send_forward")
    forward_description = forward_tool.parameters["properties"]["params"]["description"]
    assert '{"message_id":正整数}' in forward_description
    assert "不得使用 type、data、name、uin 或 content 包装" in forward_description
    await plugin.terminate()


@pytest.mark.parametrize("web_enabled", [True, False])
@pytest.mark.parametrize("mode", ["compact", "balanced", "full"])
@pytest.mark.parametrize(
    "contexts",
    [
        [],
        [
            {
                "role": "tool",
                "content": '{"ok":true,"operation":"read_url.read","data":{"page_id":"example"}}',
            }
        ],
        [
            {
                "role": "assistant",
                "tool_calls": [{"function": {"name": "read_url", "arguments": "{}"}}],
            }
        ],
    ],
)
@pytest.mark.asyncio
async def test_web_switch_controls_tools_for_urls_and_followups(
    web_enabled, mode, contexts
) -> None:
    plugin = object.__new__(QQEnhancePlugin)
    plugin.config = validate_config(
        {
            "toolsets": {"exposure_mode": mode},
            "web_reader": {"enabled": web_enabled},
        }
    )
    plugin.runtime = object.__new__(QQRuntime)
    plugin.runtime.config = plugin.config
    request = ProviderRequest(
        prompt="接着说" if contexts else "读取 HTTPS://example.test/article",
        contexts=contexts,
        func_tool=ToolSet(
            [
                FunctionTool(name=name, description="", parameters={"type": "object"})
                for name in [
                    *TOOL_OPERATIONS,
                    "web_search_tavily",
                    "tavily_extract_web_page",
                ]
            ]
        ),
    )
    await plugin.select_tools(SelectionEvent(), request)
    remaining = {tool.name for tool in request.func_tool.tools}
    assert remaining & WEB_TOOL_NAMES == (WEB_TOOL_NAMES if web_enabled else set())
    assert (WEB_READER_PROMPT in (request.system_prompt or "")) is web_enabled
    assert {"web_search_tavily", "tavily_extract_web_page", "qq_send_message"} <= remaining
    if mode != "full":
        assert len(remaining & set(TOOL_OPERATIONS)) <= (10 if mode == "compact" else 15)


@pytest.mark.asyncio
async def test_web_pack_restriction_preserves_unrelated_builtin_tools() -> None:
    plugin = object.__new__(QQEnhancePlugin)
    plugin.config = validate_config(
        {
            "toolsets": {
                "enabled_packs": ["web"],
                "disabled_operations": ["find_in_page.find"],
            }
        }
    )
    plugin.runtime = object.__new__(QQRuntime)
    plugin.runtime.config = plugin.config
    request = ProviderRequest(
        prompt="读取 https://example.test",
        func_tool=ToolSet(
            [
                FunctionTool(name=name, description="", parameters={"type": "object"})
                for name in [
                    *TOOL_OPERATIONS,
                    "web_search_tavily",
                    "tavily_extract_web_page",
                ]
            ]
        ),
    )
    await plugin.select_tools(SelectionEvent(), request)
    assert {tool.name for tool in request.func_tool.tools} == {
        "read_url",
        "read_page_section",
        "web_search_tavily",
        "tavily_extract_web_page",
    }


@pytest.mark.asyncio
async def test_request_local_tool_pruning_keeps_global_tools_untouched() -> None:
    plugin = object.__new__(QQEnhancePlugin)
    plugin.config = validate_config(None)
    plugin.runtime = object.__new__(QQRuntime)
    plugin.runtime.config = plugin.config
    tools = [
        FunctionTool(name=name, description="", parameters={"type": "object"})
        for name in TOOL_OPERATIONS
    ]
    tools.append(
        FunctionTool(
            name="unrelated_tool", description="", parameters={"type": "object"}
        )
    )
    request = ProviderRequest(
        prompt="查询群成员并发送消息", func_tool=ToolSet(list(tools))
    )
    await plugin.select_tools(SelectionEvent(), request)
    remaining = {tool.name for tool in request.func_tool.tools}
    assert "qq_group_members" in remaining
    assert "qq_send_message" in remaining
    assert "unrelated_tool" in remaining
    assert "qq_friend_manage" not in remaining
    assert len(remaining & set(TOOL_OPERATIONS)) <= 15
    assert len(tools) == len(TOOL_OPERATIONS) + 1


@pytest.mark.asyncio
async def test_group_astrbot_admin_cross_private_switch_exposes_private_tool() -> None:
    plugin = object.__new__(QQEnhancePlugin)
    plugin.config = validate_config({"permissions": {"allow_cross_private": True}})
    plugin.runtime = object.__new__(QQRuntime)
    plugin.runtime.config = plugin.config
    tools = [
        FunctionTool(name=name, description="", parameters={"type": "object"})
        for name in TOOL_OPERATIONS
    ]
    request = ProviderRequest(
        prompt="查询好友20001的消息历史",
        func_tool=ToolSet(tools),
    )

    await plugin.select_tools(GroupAstrBotAdminSelectionEvent(), request)

    assert request.func_tool.get_tool("qq_friend_history") is not None


@pytest.mark.asyncio
async def test_private_admin_group_list_prompt_exposes_group_list_tool() -> None:
    plugin = object.__new__(QQEnhancePlugin)
    plugin.config = validate_config(None)
    plugin.runtime = object.__new__(QQRuntime)
    plugin.runtime.config = plugin.config
    tools = [
        FunctionTool(name=name, description="", parameters={"type": "object"})
        for name in TOOL_OPERATIONS
    ]
    request = ProviderRequest(
        prompt="列出机器人加入的群聊",
        func_tool=ToolSet(tools),
    )

    await plugin.select_tools(PrivateAdminSelectionEvent(), request)

    assert request.func_tool.get_tool("qq_group_list") is not None


@pytest.mark.asyncio
async def test_private_admin_balanced_exposes_friend_request_without_keyword() -> None:
    plugin = object.__new__(QQEnhancePlugin)
    plugin.config = validate_config(None)
    plugin.runtime = object.__new__(QQRuntime)
    plugin.runtime.config = plugin.config
    tools = [
        FunctionTool(name=name, description="", parameters={"type": "object"})
        for name in TOOL_OPERATIONS
    ]
    request = ProviderRequest(
        prompt="看一下有没有人加你",
        func_tool=ToolSet(tools),
    )

    await plugin.select_tools(PrivateAdminSelectionEvent(), request)

    assert request.func_tool.get_tool("qq_friend_request") is not None


@pytest.mark.asyncio
async def test_private_admin_group_request_prompt_exposes_group_request_tool() -> None:
    plugin = object.__new__(QQEnhancePlugin)
    plugin.config = validate_config(None)
    plugin.runtime = object.__new__(QQRuntime)
    plugin.runtime.config = plugin.config
    tools = [
        FunctionTool(name=name, description="", parameters={"type": "object"})
        for name in TOOL_OPERATIONS
    ]
    request = ProviderRequest(
        prompt="查看下是否有进群申请",
        func_tool=ToolSet(tools),
    )

    await plugin.select_tools(PrivateAdminSelectionEvent(), request)

    assert request.func_tool.get_tool("qq_group_request") is not None


@pytest.mark.asyncio
async def test_request_notification_follow_up_exposes_group_request_tool() -> None:
    plugin = object.__new__(QQEnhancePlugin)
    plugin.config = validate_config({"permissions": {"allow_cross_group": True}})
    plugin.runtime = object.__new__(QQRuntime)
    plugin.runtime.config = plugin.config
    tools = [
        FunctionTool(name=name, description="", parameters={"type": "object"})
        for name in TOOL_OPERATIONS
    ]
    request = ProviderRequest(
        prompt="通过",
        contexts=[
            {
                "role": "assistant",
                "content": (
                    "收到一条新申请。\n\n[QQ 入群申请]\n"
                    "申请编号：17\n申请人 QQ：20001\n群号：30001"
                ),
            }
        ],
        func_tool=ToolSet(tools),
    )

    await plugin.select_tools(PrivateAdminSelectionEvent(), request)

    assert request.func_tool.get_tool("qq_group_request") is not None


@pytest.mark.asyncio
async def test_private_admin_nickname_prompt_exposes_account_manage_tool() -> None:
    plugin = object.__new__(QQEnhancePlugin)
    plugin.config = validate_config(None)
    plugin.runtime = object.__new__(QQRuntime)
    plugin.runtime.config = plugin.config
    tools = [
        FunctionTool(name=name, description="", parameters={"type": "object"})
        for name in TOOL_OPERATIONS
    ]
    request = ProviderRequest(
        prompt="把昵称修改为测试机器人",
        func_tool=ToolSet(tools),
    )

    await plugin.select_tools(PrivateAdminProfileSelectionEvent(), request)

    assert request.func_tool.get_tool("qq_account_manage") is not None
    assert request.func_tool.get_tool("qq_status") is not None


@pytest.mark.asyncio
async def test_private_admin_remark_prompt_exposes_friend_manage_tool() -> None:
    plugin = object.__new__(QQEnhancePlugin)
    plugin.config = validate_config(None)
    plugin.runtime = object.__new__(QQRuntime)
    plugin.runtime.config = plugin.config
    tools = [
        FunctionTool(name=name, description="", parameters={"type": "object"})
        for name in TOOL_OPERATIONS
    ]
    request = ProviderRequest(
        prompt="把我的备注修改为测试备注",
        func_tool=ToolSet(tools),
    )

    await plugin.select_tools(PrivateAdminRemarkSelectionEvent(), request)

    assert request.func_tool.get_tool("qq_friend_manage") is not None


@pytest.mark.asyncio
async def test_private_admin_group_nickname_prompt_exposes_member_manage_tool() -> None:
    plugin = object.__new__(QQEnhancePlugin)
    plugin.config = validate_config({"permissions": {"allow_cross_group": True}})
    plugin.runtime = object.__new__(QQRuntime)
    plugin.runtime.config = plugin.config
    tools = [
        FunctionTool(name=name, description="", parameters={"type": "object"})
        for name in TOOL_OPERATIONS
    ]
    request = ProviderRequest(
        prompt="把测试成员的群昵称改为测试群昵称",
        func_tool=ToolSet(tools),
    )

    await plugin.select_tools(PrivateAdminRemarkSelectionEvent(), request)

    assert request.func_tool.get_tool("qq_group_member_manage") is not None


@pytest.mark.asyncio
async def test_private_admin_remove_member_prompt_exposes_member_manage_tool() -> None:
    plugin = object.__new__(QQEnhancePlugin)
    plugin.config = validate_config({"permissions": {"allow_cross_group": True}})
    plugin.runtime = object.__new__(QQRuntime)
    plugin.runtime.config = plugin.config
    tools = [
        FunctionTool(name=name, description="", parameters={"type": "object"})
        for name in TOOL_OPERATIONS
    ]
    request = ProviderRequest(
        prompt="把测试成员移除群聊",
        func_tool=ToolSet(tools),
    )

    await plugin.select_tools(PrivateAdminSelectionEvent(), request)

    assert request.func_tool.get_tool("qq_group_member_manage") is not None


@pytest.mark.asyncio
async def test_private_file_attachment_exposes_private_files_tool() -> None:
    plugin = object.__new__(QQEnhancePlugin)
    plugin.config = validate_config(None)
    plugin.runtime = object.__new__(QQRuntime)
    plugin.runtime.config = plugin.config
    tools = [
        FunctionTool(name=name, description="", parameters={"type": "object"})
        for name in TOOL_OPERATIONS
    ]
    request = ProviderRequest(
        prompt="[ComponentType.File]",
        func_tool=ToolSet(tools),
    )

    await plugin.select_tools(PrivateAdminFileSelectionEvent(), request)

    assert request.func_tool.get_tool("qq_private_files") is not None


@pytest.mark.asyncio
async def test_profile_follow_up_skips_non_routable_retry_context() -> None:
    plugin = object.__new__(QQEnhancePlugin)
    plugin.config = validate_config(None)
    plugin.runtime = object.__new__(QQRuntime)
    plugin.runtime.config = plugin.config
    tools = [
        FunctionTool(name=name, description="", parameters={"type": "object"})
        for name in TOOL_OPERATIONS
    ]
    request = ProviderRequest(
        prompt="改回测试机器人",
        contexts=[
            {"role": "user", "content": "把昵称修改为测试机器人"},
            {"role": "assistant", "content": "修改成功。"},
            {"role": "user", "content": "重试"},
            {"role": "assistant", "content": "已重试。"},
        ],
        func_tool=ToolSet(tools),
    )

    await plugin.select_tools(PrivateAdminProfileFollowUpSelectionEvent(), request)

    assert request.func_tool.get_tool("qq_account_manage") is not None


@pytest.mark.asyncio
async def test_group_sign_prompt_exposes_group_manage_tool() -> None:
    plugin = object.__new__(QQEnhancePlugin)
    plugin.config = validate_config(None)
    plugin.runtime = object.__new__(QQRuntime)
    plugin.runtime.config = plugin.config
    tools = [
        FunctionTool(name=name, description="", parameters={"type": "object"})
        for name in TOOL_OPERATIONS
    ]
    request = ProviderRequest(
        prompt="执行当前群签到",
        func_tool=ToolSet(tools),
    )

    await plugin.select_tools(GroupOwnerSelectionEvent(), request)

    assert request.func_tool.get_tool("qq_group_manage") is not None


@pytest.mark.asyncio
async def test_group_name_prompt_exposes_group_manage_tool() -> None:
    plugin = object.__new__(QQEnhancePlugin)
    plugin.config = validate_config(None)
    plugin.runtime = object.__new__(QQRuntime)
    plugin.runtime.config = plugin.config
    tools = [
        FunctionTool(name=name, description="", parameters={"type": "object"})
        for name in TOOL_OPERATIONS
    ]
    request = ProviderRequest(
        prompt="把当前群名称修改为示例测试群",
        func_tool=ToolSet(tools),
    )

    await plugin.select_tools(GroupOwnerSelectionEvent(), request)

    assert request.func_tool.get_tool("qq_group_manage") is not None


@pytest.mark.asyncio
async def test_group_management_prompt_exposes_group_manage_tool() -> None:
    plugin = object.__new__(QQEnhancePlugin)
    plugin.config = validate_config(None)
    plugin.runtime = object.__new__(QQRuntime)
    plugin.runtime.config = plugin.config
    tools = [
        FunctionTool(name=name, description="", parameters={"type": "object"})
        for name in TOOL_OPERATIONS
    ]
    request = ProviderRequest(
        prompt="看下你的群管理工具",
        func_tool=ToolSet(tools),
    )

    await plugin.select_tools(GroupOwnerSelectionEvent(), request)

    assert request.func_tool.get_tool("qq_group_manage") is not None


@pytest.mark.asyncio
async def test_private_admin_leave_group_prompt_ignores_stale_request_context() -> None:
    plugin = object.__new__(QQEnhancePlugin)
    plugin.config = validate_config({"permissions": {"allow_cross_group": True}})
    plugin.runtime = object.__new__(QQRuntime)
    plugin.runtime.config = plugin.config
    tools = [
        FunctionTool(name=name, description="", parameters={"type": "object"})
        for name in TOOL_OPERATIONS
    ]
    request = ProviderRequest(
        prompt="退出群30001",
        contexts=[
            {
                "role": "user",
                "content": "通过当前群的群邀请，sub_type 为 invite",
            }
        ],
        func_tool=ToolSet(tools),
    )

    await plugin.select_tools(PrivateAdminSelectionEvent(), request)

    assert request.func_tool.get_tool("qq_group_manage") is not None
    assert request.func_tool.get_tool("qq_group_request") is None


@pytest.mark.asyncio
async def test_group_poke_follow_up_uses_previous_user_context() -> None:
    plugin = object.__new__(QQEnhancePlugin)
    plugin.config = validate_config(None)
    plugin.runtime = object.__new__(QQRuntime)
    plugin.runtime.config = plugin.config
    tools = [
        FunctionTool(name=name, description="", parameters={"type": "object"})
        for name in TOOL_OPERATIONS
    ]
    request = ProviderRequest(
        prompt="再试一次",
        contexts=[
            {"role": "user", "content": "戳我一下"},
            {"role": "assistant", "content": "当前尚未执行。"},
        ],
        func_tool=ToolSet(tools),
    )

    await plugin.select_tools(SelectionEvent(), request)

    assert request.func_tool.get_tool("qq_group_member_manage") is not None
    assert request.func_tool.get_tool("qq_friend_interact") is None
