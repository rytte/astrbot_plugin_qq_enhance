from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from astrbot.core.agent.tool import FunctionTool, ToolSet
from astrbot.core.message.components import File
from astrbot.core.provider.entities import ProviderRequest
from astrbot.core.provider.func_tool_manager import FunctionToolManager
from astrbot_plugin_qq_extension_tools.catalog import TOOL_OPERATIONS
from astrbot_plugin_qq_extension_tools.main import QQExtensionToolsPlugin
from astrbot_plugin_qq_extension_tools.runtime import QQRuntime, validate_config


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
    message_str = "把昵称修改为 Airi-QQ扩展测试"


class PrivateAdminRemarkSelectionEvent(PrivateAdminSelectionEvent):
    message_str = "把我的备注修改为 QQ扩展测试"


class PrivateAdminFileSelectionEvent(PrivateAdminSelectionEvent):
    message_str = "[ComponentType.File]"
    message_obj = SimpleNamespace(
        raw_message={"sender": {"role": "member"}},
        message=[File(name="list.txt", url="https://example.test/list.txt")],
    )


class PrivateAdminProfileFollowUpSelectionEvent(PrivateAdminSelectionEvent):
    message_str = "改回Airi"


class GroupOwnerSelectionEvent(SelectionEvent):
    message_str = "执行当前群签到"
    message_obj = SimpleNamespace(raw_message={"sender": {"role": "owner"}})


@pytest.mark.asyncio
async def test_initialize_uses_registered_tool_manager_api() -> None:
    plugin = object.__new__(QQExtensionToolsPlugin)
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
    plugin.config = validate_config(None)
    plugin.storage = SimpleNamespace(initialize=AsyncMock())
    plugin.runtime = SimpleNamespace(
        operation_enabled=lambda _operation_id: True,
        cleanup=AsyncMock(),
    )
    plugin.cleanup_task = None

    await plugin.initialize()

    plugin.storage.initialize.assert_awaited_once()
    assert all(manager.get_func(tool_name) is not None for tool_name in TOOL_OPERATIONS)
    send_tool = manager.get_func("qq_send_message")
    params_description = send_tool.parameters["properties"]["params"]["description"]
    assert "不得使用 data 包装" in params_description
    forward_tool = manager.get_func("qq_send_forward")
    forward_description = forward_tool.parameters["properties"]["params"][
        "description"
    ]
    assert '{"message_id":正整数}' in forward_description
    assert "不得使用 type、data、name、uin 或 content 包装" in forward_description
    await plugin.terminate()


@pytest.mark.asyncio
async def test_request_local_tool_pruning_keeps_global_tools_untouched() -> None:
    plugin = object.__new__(QQExtensionToolsPlugin)
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
async def test_private_admin_group_list_prompt_exposes_group_list_tool() -> None:
    plugin = object.__new__(QQExtensionToolsPlugin)
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
    plugin = object.__new__(QQExtensionToolsPlugin)
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
    plugin = object.__new__(QQExtensionToolsPlugin)
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
async def test_private_admin_nickname_prompt_exposes_account_manage_tool() -> None:
    plugin = object.__new__(QQExtensionToolsPlugin)
    plugin.config = validate_config(None)
    plugin.runtime = object.__new__(QQRuntime)
    plugin.runtime.config = plugin.config
    tools = [
        FunctionTool(name=name, description="", parameters={"type": "object"})
        for name in TOOL_OPERATIONS
    ]
    request = ProviderRequest(
        prompt="把昵称修改为 Airi-QQ扩展测试",
        func_tool=ToolSet(tools),
    )

    await plugin.select_tools(PrivateAdminProfileSelectionEvent(), request)

    assert request.func_tool.get_tool("qq_account_manage") is not None
    assert request.func_tool.get_tool("qq_status") is not None


@pytest.mark.asyncio
async def test_private_admin_remark_prompt_exposes_friend_manage_tool() -> None:
    plugin = object.__new__(QQExtensionToolsPlugin)
    plugin.config = validate_config(None)
    plugin.runtime = object.__new__(QQRuntime)
    plugin.runtime.config = plugin.config
    tools = [
        FunctionTool(name=name, description="", parameters={"type": "object"})
        for name in TOOL_OPERATIONS
    ]
    request = ProviderRequest(
        prompt="把我的备注修改为 QQ扩展测试",
        func_tool=ToolSet(tools),
    )

    await plugin.select_tools(PrivateAdminRemarkSelectionEvent(), request)

    assert request.func_tool.get_tool("qq_friend_manage") is not None


@pytest.mark.asyncio
async def test_private_admin_group_nickname_prompt_exposes_member_manage_tool() -> None:
    plugin = object.__new__(QQExtensionToolsPlugin)
    plugin.config = validate_config(
        {"permissions": {"allow_cross_group": True}}
    )
    plugin.runtime = object.__new__(QQRuntime)
    plugin.runtime.config = plugin.config
    tools = [
        FunctionTool(name=name, description="", parameters={"type": "object"})
        for name in TOOL_OPERATIONS
    ]
    request = ProviderRequest(
        prompt="把 Milika 的群昵称改为 QQ扩展测试",
        func_tool=ToolSet(tools),
    )

    await plugin.select_tools(PrivateAdminRemarkSelectionEvent(), request)

    assert request.func_tool.get_tool("qq_group_member_manage") is not None


@pytest.mark.asyncio
async def test_private_admin_remove_member_prompt_exposes_member_manage_tool() -> None:
    plugin = object.__new__(QQExtensionToolsPlugin)
    plugin.config = validate_config(
        {"permissions": {"allow_cross_group": True}}
    )
    plugin.runtime = object.__new__(QQRuntime)
    plugin.runtime.config = plugin.config
    tools = [
        FunctionTool(name=name, description="", parameters={"type": "object"})
        for name in TOOL_OPERATIONS
    ]
    request = ProviderRequest(
        prompt="把 Milika 移除群聊",
        func_tool=ToolSet(tools),
    )

    await plugin.select_tools(PrivateAdminSelectionEvent(), request)

    assert request.func_tool.get_tool("qq_group_member_manage") is not None


@pytest.mark.asyncio
async def test_private_file_attachment_exposes_private_files_tool() -> None:
    plugin = object.__new__(QQExtensionToolsPlugin)
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
    plugin = object.__new__(QQExtensionToolsPlugin)
    plugin.config = validate_config(None)
    plugin.runtime = object.__new__(QQRuntime)
    plugin.runtime.config = plugin.config
    tools = [
        FunctionTool(name=name, description="", parameters={"type": "object"})
        for name in TOOL_OPERATIONS
    ]
    request = ProviderRequest(
        prompt="改回Airi",
        contexts=[
            {"role": "user", "content": "把昵称修改为 Airi-QQ扩展测试"},
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
    plugin = object.__new__(QQExtensionToolsPlugin)
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
    plugin = object.__new__(QQExtensionToolsPlugin)
    plugin.config = validate_config(None)
    plugin.runtime = object.__new__(QQRuntime)
    plugin.runtime.config = plugin.config
    tools = [
        FunctionTool(name=name, description="", parameters={"type": "object"})
        for name in TOOL_OPERATIONS
    ]
    request = ProviderRequest(
        prompt="把当前群名称修改为 QQ扩展确认测试",
        func_tool=ToolSet(tools),
    )

    await plugin.select_tools(GroupOwnerSelectionEvent(), request)

    assert request.func_tool.get_tool("qq_group_manage") is not None


@pytest.mark.asyncio
async def test_private_admin_leave_group_prompt_ignores_stale_request_context() -> None:
    plugin = object.__new__(QQExtensionToolsPlugin)
    plugin.config = validate_config(
        {"permissions": {"allow_cross_group": True}}
    )
    plugin.runtime = object.__new__(QQRuntime)
    plugin.runtime.config = plugin.config
    tools = [
        FunctionTool(name=name, description="", parameters={"type": "object"})
        for name in TOOL_OPERATIONS
    ]
    request = ProviderRequest(
        prompt="退出群965582257",
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
    plugin = object.__new__(QQExtensionToolsPlugin)
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
