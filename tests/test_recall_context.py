from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from astrbot.core.provider.entities import ProviderRequest
from astrbot_plugin_qq_extension_tools.main import QQExtensionToolsPlugin
from astrbot_plugin_qq_extension_tools.runtime import validate_config


class RecallEvent:
    """Minimal aiocqhttp event used by recall-context tests."""

    def __init__(self, raw_message: dict, *, group: bool = False) -> None:
        self.message_obj = SimpleNamespace(raw_message=raw_message)
        self.unified_msg_origin = (
            "platform-a:GroupMessage:30001"
            if group
            else "platform-a:FriendMessage:10001"
        )
        self.is_wake = False
        self.is_at_or_wake_command = False
        self.extras = {}

    def get_platform_name(self) -> str:
        """Return the adapter type."""

        return "aiocqhttp"

    def get_platform_id(self) -> str:
        """Return the adapter instance ID."""

        return "platform-a"

    def get_group_id(self) -> str:
        """Return the current group ID."""

        return str(self.message_obj.raw_message.get("group_id") or "")

    def get_sender_id(self) -> str:
        """Return the current sender ID."""

        return str(self.message_obj.raw_message.get("user_id") or "")

    def set_extra(self, key: str, value: object) -> None:
        """Store event-local state."""

        self.extras[key] = value

    def get_extra(self, key: str, default: object = None) -> object:
        """Read event-local state."""

        return self.extras.get(key, default)


def make_plugin(history: list[dict]) -> tuple[QQExtensionToolsPlugin, SimpleNamespace]:
    """Create a plugin with an in-memory conversation manager.

    Args:
        history: Current persisted conversation history.

    Returns:
        Plugin and mutable fake conversation objects.
    """

    conversation = SimpleNamespace(
        cid="conversation-a",
        history=json.dumps(history, ensure_ascii=False),
    )
    manager = SimpleNamespace(
        get_conversation=AsyncMock(return_value=conversation),
        update_conversation=AsyncMock(),
    )
    plugin = object.__new__(QQExtensionToolsPlugin)
    plugin.context = SimpleNamespace(conversation_manager=manager)
    plugin.config = validate_config({"inbound": {"mark_recalled_messages": True}})
    plugin.recall_messages = {}
    return plugin, conversation


@pytest.mark.asyncio
async def test_private_recall_appends_elapsed_time_without_waking_model() -> None:
    plugin, conversation = make_plugin([])
    message_event = RecallEvent(
        {
            "post_type": "message",
            "message_type": "private",
            "message_id": 101,
            "user_id": 10001,
            "time": 1000,
        }
    )
    request = ProviderRequest(
        prompt="这条消息稍后撤回",
        conversation=conversation,
    )
    await plugin.track_context_message(message_event, request)
    conversation.history = json.dumps(
        [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "这条消息稍后撤回"},
                    {"type": "text", "text": "<system_reminder>test</system_reminder>"},
                ],
            },
            {"role": "assistant", "content": "收到。"},
        ],
        ensure_ascii=False,
    )
    recall_event = RecallEvent(
        {
            "post_type": "notice",
            "notice_type": "friend_recall",
            "message_id": 101,
            "user_id": 10001,
            "time": 1083,
        }
    )

    await plugin.mark_recalled_message(recall_event)

    updated = plugin.context.conversation_manager.update_conversation.await_args.kwargs[
        "history"
    ]
    assert updated[0]["content"][0]["text"] == (
        "这条消息稍后撤回\n[该 QQ 消息已在发送后 1 分 23 秒被撤回]"
    )
    assert updated[0]["content"][1]["text"] == (
        "<system_reminder>test</system_reminder>"
    )
    assert recall_event.is_wake is False
    assert recall_event.is_at_or_wake_command is False

    await plugin.mark_recalled_message(recall_event)
    assert plugin.context.conversation_manager.update_conversation.await_count == 1


@pytest.mark.asyncio
async def test_group_recall_is_scoped_by_group_id() -> None:
    plugin, conversation = make_plugin([])
    message_event = RecallEvent(
        {
            "post_type": "message",
            "message_type": "group",
            "message_id": 202,
            "user_id": 10001,
            "group_id": 30001,
            "time": 2000,
        },
        group=True,
    )
    request = ProviderRequest(prompt="群消息", conversation=conversation)
    await plugin.track_context_message(message_event, request)
    conversation.history = json.dumps(
        [{"role": "user", "content": "群消息"}], ensure_ascii=False
    )

    wrong_group_event = RecallEvent(
        {
            "post_type": "notice",
            "notice_type": "group_recall",
            "message_id": 202,
            "user_id": 10001,
            "group_id": 30002,
            "time": 2010,
        },
        group=True,
    )
    await plugin.mark_recalled_message(wrong_group_event)
    plugin.context.conversation_manager.update_conversation.assert_not_awaited()

    correct_group_event = RecallEvent(
        {
            "post_type": "notice",
            "notice_type": "group_recall",
            "message_id": 202,
            "user_id": 10001,
            "group_id": 30001,
            "time": 2010,
        },
        group=True,
    )
    await plugin.mark_recalled_message(correct_group_event)

    updated = plugin.context.conversation_manager.update_conversation.await_args.kwargs[
        "history"
    ]
    assert updated[0]["content"] == "群消息\n[该 QQ 消息已在发送后 10 秒被撤回]"


@pytest.mark.asyncio
async def test_group_recall_is_scoped_by_original_sender() -> None:
    plugin, conversation = make_plugin([])
    message_event = RecallEvent(
        {
            "post_type": "message",
            "message_type": "group",
            "message_id": 203,
            "user_id": 10001,
            "group_id": 30001,
            "time": 2000,
        },
        group=True,
    )
    await plugin.track_context_message(
        message_event,
        ProviderRequest(prompt="群成员消息", conversation=conversation),
    )
    conversation.history = json.dumps(
        [{"role": "user", "content": "群成员消息"}], ensure_ascii=False
    )
    recall_event = RecallEvent(
        {
            "post_type": "notice",
            "notice_type": "group_recall",
            "message_id": 203,
            "user_id": 10002,
            "operator_id": 10003,
            "group_id": 30001,
            "time": 2010,
        },
        group=True,
    )

    await plugin.mark_recalled_message(recall_event)

    plugin.context.conversation_manager.update_conversation.assert_not_awaited()


@pytest.mark.asyncio
async def test_recall_before_history_save_is_applied_after_reply() -> None:
    plugin, conversation = make_plugin([])
    message_event = RecallEvent(
        {
            "post_type": "message",
            "message_type": "private",
            "message_id": 303,
            "user_id": 10001,
            "time": 3000,
        }
    )
    request = ProviderRequest(prompt="快速撤回", conversation=conversation)
    await plugin.track_context_message(message_event, request)
    recall_event = RecallEvent(
        {
            "post_type": "notice",
            "notice_type": "friend_recall",
            "message_id": 303,
            "user_id": 10001,
            "time": 3005,
        }
    )

    await plugin.mark_recalled_message(recall_event)
    plugin.context.conversation_manager.update_conversation.assert_not_awaited()

    conversation.history = json.dumps(
        [
            {"role": "user", "content": "快速撤回"},
            {"role": "assistant", "content": "收到。"},
        ],
        ensure_ascii=False,
    )
    await plugin.finish_pending_recall(message_event)

    updated = plugin.context.conversation_manager.update_conversation.await_args.kwargs[
        "history"
    ]
    assert updated[0]["content"] == "快速撤回\n[该 QQ 消息已在发送后 5 秒被撤回]"


@pytest.mark.asyncio
async def test_early_recall_marks_agent_context_before_streaming_history_save() -> None:
    plugin, conversation = make_plugin([])
    message_event = RecallEvent(
        {
            "post_type": "message",
            "message_type": "group",
            "message_id": 304,
            "user_id": 10001,
            "group_id": 30001,
            "time": 3000,
        },
        group=True,
    )
    request = ProviderRequest(prompt="流式回复期间撤回", conversation=conversation)
    await plugin.track_context_message(message_event, request)
    recall_event = RecallEvent(
        {
            "post_type": "notice",
            "notice_type": "group_recall",
            "message_id": 304,
            "user_id": 10001,
            "group_id": 30001,
            "time": 3012,
        },
        group=True,
    )
    await plugin.mark_recalled_message(recall_event)
    message = SimpleNamespace(role="user", content="流式回复期间撤回")

    await plugin.mark_pending_recall_before_history_save(
        message_event,
        SimpleNamespace(messages=[message]),
        None,
    )

    assert message.content == ("流式回复期间撤回\n[该 QQ 消息已在发送后 12 秒被撤回]")


@pytest.mark.asyncio
async def test_expired_or_disabled_mapping_is_ignored() -> None:
    plugin, conversation = make_plugin([])
    message_event = RecallEvent(
        {
            "post_type": "message",
            "message_type": "private",
            "message_id": 404,
            "user_id": 10001,
            "time": 4000,
        }
    )
    request = ProviderRequest(prompt="过期消息", conversation=conversation)
    await plugin.track_context_message(message_event, request)
    next(iter(plugin.recall_messages.values()))["expires_at"] = 0
    recall_event = RecallEvent(
        {
            "post_type": "notice",
            "notice_type": "friend_recall",
            "message_id": 404,
            "user_id": 10001,
            "time": 4001,
        }
    )

    await plugin.mark_recalled_message(recall_event)

    assert plugin.recall_messages == {}
    plugin.context.conversation_manager.update_conversation.assert_not_awaited()

    plugin.config = validate_config(None)
    await plugin.track_context_message(message_event, request)
    assert plugin.recall_messages == {}


@pytest.mark.asyncio
async def test_invalid_notice_time_uses_generic_marker() -> None:
    plugin, conversation = make_plugin([])
    message_event = RecallEvent(
        {
            "post_type": "message",
            "message_type": "private",
            "message_id": 505,
            "user_id": 10001,
            "time": 5000,
        }
    )
    request = ProviderRequest(prompt="时间异常", conversation=conversation)
    await plugin.track_context_message(message_event, request)
    conversation.history = json.dumps(
        [{"role": "user", "content": "时间异常"}], ensure_ascii=False
    )
    recall_event = RecallEvent(
        {
            "post_type": "notice",
            "notice_type": "friend_recall",
            "message_id": 505,
            "user_id": 10001,
            "time": "invalid",
        }
    )

    await plugin.mark_recalled_message(recall_event)

    updated = plugin.context.conversation_manager.update_conversation.await_args.kwargs[
        "history"
    ]
    assert updated[0]["content"] == "时间异常\n[该 QQ 消息已被撤回]"


@pytest.mark.asyncio
async def test_unique_message_is_found_after_history_trimming() -> None:
    plugin, conversation = make_plugin(
        [
            {"role": "user", "content": "旧消息"},
            {"role": "assistant", "content": "旧回复"},
        ]
    )
    message_event = RecallEvent(
        {
            "post_type": "message",
            "message_type": "private",
            "message_id": 606,
            "user_id": 10001,
            "time": 6000,
        }
    )
    await plugin.track_context_message(
        message_event,
        ProviderRequest(prompt="裁剪后仍可定位", conversation=conversation),
    )
    conversation.history = json.dumps(
        [{"role": "user", "content": "裁剪后仍可定位"}], ensure_ascii=False
    )
    recall_event = RecallEvent(
        {
            "post_type": "notice",
            "notice_type": "friend_recall",
            "message_id": 606,
            "user_id": 10001,
            "time": 6008,
        }
    )

    await plugin.mark_recalled_message(recall_event)

    updated = plugin.context.conversation_manager.update_conversation.await_args.kwargs[
        "history"
    ]
    assert updated[0]["content"].endswith("[该 QQ 消息已在发送后 8 秒被撤回]")
