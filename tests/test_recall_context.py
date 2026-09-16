from __future__ import annotations

import asyncio
import json
import time
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from astrbot.core.provider.entities import ProviderRequest
from astrbot.core.utils.session_lock import session_lock_manager
from astrbot_plugin_qq_enhance.main import QQEnhancePlugin, RECALL_EXCERPT_MAX_CHARS
from astrbot_plugin_qq_enhance.runtime import validate_config


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

    def get_extra(self, key: str, default: object = None) -> object:
        """Read event-local state."""
        return self.extras.get(key, default)


def make_plugin(history: list[dict]) -> tuple[QQEnhancePlugin, SimpleNamespace]:
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

    async def update(_umo, _cid, *, history, **_kwargs):
        conversation.history = json.dumps(history, ensure_ascii=False)

    manager = SimpleNamespace(
        get_conversation=AsyncMock(return_value=conversation),
        get_curr_conversation_id=AsyncMock(return_value="conversation-b"),
        update_conversation=AsyncMock(side_effect=update),
    )
    plugin = object.__new__(QQEnhancePlugin)
    plugin.context = SimpleNamespace(conversation_manager=manager)
    plugin.config = validate_config({"inbound": {"mark_recalled_messages": True}})
    plugin.recall_messages = {}
    plugin.recall_tasks = set()
    return plugin, conversation


async def track_message(
    plugin,
    conversation,
    prompt="这条消息稍后撤回",
    *,
    message_id=101,
    group=False,
    sent_at=1000,
):
    """Track a source message and build its matching recall event.

    Args:
        plugin: Plugin under test.
        conversation: Original conversation object.
        prompt: Source text prepared for the model.
        message_id: QQ message identifier.
        group: Whether to create group events.
        sent_at: Timestamp supplied by the original QQ message.

    Returns:
        Source message event and matching recall event.
    """
    source = RecallEvent(
        {
            "post_type": "message",
            "message_type": "group" if group else "private",
            "message_id": message_id,
            "user_id": 10001,
            "group_id": 30001 if group else None,
            "time": sent_at,
        },
        group=group,
    )
    await plugin.track_context_message(
        source, ProviderRequest(prompt=prompt, conversation=conversation)
    )
    notice = RecallEvent(
        {
            "post_type": "notice",
            "notice_type": "group_recall" if group else "friend_recall",
            "message_id": message_id,
            "user_id": 10001,
            "group_id": 30001 if group else None,
            "time": 1083,
        },
        group=group,
    )
    return source, notice


async def drain_recalls(plugin):
    """Wait for scheduled history appends.

    Args:
        plugin: Plugin whose background recall tasks should finish.
    """
    tasks = list(plugin.recall_tasks)
    if tasks:
        await asyncio.wait_for(asyncio.gather(*tasks), 3)


@pytest.mark.asyncio
async def test_private_recall_appends_once_without_changing_history_or_waking_model():
    original = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "这条消息稍后撤回"},
                {"type": "text", "text": "<system_reminder>test</system_reminder>"},
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/png;base64,abc"},
                },
            ],
        },
        {"role": "assistant", "content": "收到。"},
    ]
    plugin, conversation = make_plugin(original)
    _, notice = await track_message(plugin, conversation)
    await plugin.mark_recalled_message(notice)
    await plugin.mark_recalled_message(notice)
    await drain_recalls(plugin)
    await plugin.mark_recalled_message(notice)
    await drain_recalls(plugin)

    history = json.loads(conversation.history)
    assert history[:-1] == original
    assert history[-1]["role"] == "user"
    sent_time = time.strftime("%H:%M:%S", time.localtime(1000))
    assert history[-1]["content"] == (
        f"[QQ 撤回事件: 用户 10001 于 {sent_time} 发送的消息已在发送后 "
        '83 秒被撤回。原消息摘录（仅用于定位）："这条消息稍后撤回"]'
    )
    assert notice.is_wake is False
    assert notice.is_at_or_wake_command is False
    plugin.context.conversation_manager.update_conversation.assert_awaited_once()
    assert next(iter(plugin.recall_messages.values()))["notified"] is True


@pytest.mark.parametrize("field,value", [("group_id", 30002), ("user_id", 10002)])
@pytest.mark.asyncio
async def test_group_recall_rejects_wrong_scope_or_sender(field, value):
    plugin, conversation = make_plugin([])
    _, notice = await track_message(plugin, conversation, group=True)
    notice.message_obj.raw_message[field] = value
    await plugin.mark_recalled_message(notice)
    assert not plugin.recall_tasks
    plugin.context.conversation_manager.update_conversation.assert_not_awaited()


@pytest.mark.asyncio
async def test_group_recall_describes_original_sender_without_operator_details():
    original = [{"role": "user", "content": "群消息"}]
    plugin, conversation = make_plugin(original)
    _, notice = await track_message(plugin, conversation, "群消息", group=True)
    notice.message_obj.raw_message["operator_id"] = 10002
    await plugin.mark_recalled_message(notice)
    await drain_recalls(plugin)
    history = json.loads(conversation.history)
    assert history[:-1] == original
    assert history[-1]["content"].startswith("[QQ 撤回事件: 用户 10001 于 ")
    assert "10002" not in history[-1]["content"]
    assert "发送的消息已在发送后 83 秒被撤回。" in history[-1]["content"]


@pytest.mark.asyncio
async def test_recall_waits_for_session_lock_and_reads_latest_history():
    original = [{"role": "user", "content": "生成中撤回"}]
    plugin, conversation = make_plugin(original)
    source, notice = await track_message(plugin, conversation, "生成中撤回")
    runtime_messages = deepcopy(original)
    async with session_lock_manager.acquire_lock(source.unified_msg_origin):
        await plugin.mark_recalled_message(notice)
        await asyncio.sleep(0)
        plugin.context.conversation_manager.get_conversation.assert_not_awaited()
        assert runtime_messages == original
        runtime_messages.append({"role": "assistant", "content": "本轮回复"})
        conversation.history = json.dumps(runtime_messages, ensure_ascii=False)
    await drain_recalls(plugin)
    history = json.loads(conversation.history)
    assert history[:-1] == runtime_messages
    assert history[-1]["role"] == "user"
    assert len(history) == 3


@pytest.mark.asyncio
async def test_recall_stays_bound_to_original_conversation_after_switch():
    plugin, conversation = make_plugin([])
    source, notice = await track_message(plugin, conversation)
    await plugin.mark_recalled_message(notice)
    await drain_recalls(plugin)
    manager = plugin.context.conversation_manager
    manager.get_curr_conversation_id.assert_not_awaited()
    manager.get_conversation.assert_awaited_once_with(
        source.unified_msg_origin, "conversation-a"
    )
    assert manager.update_conversation.await_args.args == (
        source.unified_msg_origin,
        "conversation-a",
    )


@pytest.mark.asyncio
async def test_concurrent_recalls_append_without_overwriting_each_other():
    original = [{"role": "user", "content": "相同文字"}] * 2
    plugin, conversation = make_plugin(original)
    update = plugin.context.conversation_manager.update_conversation.side_effect

    async def yielding_update(*args, **kwargs):
        await asyncio.sleep(0)
        await update(*args, **kwargs)

    plugin.context.conversation_manager.update_conversation.side_effect = (
        yielding_update
    )
    _, first = await track_message(plugin, conversation, "相同文字", message_id=1)
    _, second = await track_message(plugin, conversation, "相同文字", message_id=2)
    await asyncio.gather(
        plugin.mark_recalled_message(first), plugin.mark_recalled_message(second)
    )
    await drain_recalls(plugin)
    history = json.loads(conversation.history)
    assert history[:2] == original
    assert len(history) == 4
    assert history[2] == history[3]
    assert all(entry["notified"] for entry in plugin.recall_messages.values())
    assert plugin.context.conversation_manager.update_conversation.await_count == 2


@pytest.mark.asyncio
async def test_recall_appends_after_history_trimming_without_matching_old_content():
    plugin, conversation = make_plugin([])
    _, notice = await track_message(plugin, conversation, "已经被摘要替换的原消息")
    compacted = [{"role": "assistant", "content": "历史摘要"}]
    conversation.history = json.dumps(compacted, ensure_ascii=False)
    await plugin.mark_recalled_message(notice)
    await drain_recalls(plugin)
    history = json.loads(conversation.history)
    assert history[:-1] == compacted
    assert "已经被摘要替换的原消息" in history[-1]["content"]


@pytest.mark.asyncio
async def test_expired_or_disabled_mapping_is_ignored():
    plugin, conversation = make_plugin([])
    source, notice = await track_message(plugin, conversation)
    next(iter(plugin.recall_messages.values()))["expires_at"] = 0
    await plugin.mark_recalled_message(notice)
    assert not plugin.recall_messages
    assert not plugin.recall_tasks
    plugin.context.conversation_manager.update_conversation.assert_not_awaited()
    plugin.config["inbound"]["mark_recalled_messages"] = False
    await plugin.track_context_message(
        source, ProviderRequest(prompt="已关闭", conversation=conversation)
    )
    assert not plugin.recall_messages


@pytest.mark.asyncio
async def test_accepted_recall_survives_index_expiry_while_waiting_for_lock():
    plugin, conversation = make_plugin([])
    source, notice = await track_message(plugin, conversation)
    async with session_lock_manager.acquire_lock(source.unified_msg_origin):
        await plugin.mark_recalled_message(notice)
        await asyncio.sleep(0)
        next(iter(plugin.recall_messages.values()))["expires_at"] = 0
        plugin._cleanup_recall_messages()
        assert not plugin.recall_messages
    await drain_recalls(plugin)
    assert len(json.loads(conversation.history)) == 1


@pytest.mark.parametrize("timestamp", ["invalid", None, True, -1, 10**30])
@pytest.mark.asyncio
async def test_invalid_notice_time_omits_elapsed_seconds(timestamp):
    plugin, conversation = make_plugin([])
    _, notice = await track_message(plugin, conversation)
    notice.message_obj.raw_message["time"] = timestamp
    await plugin.mark_recalled_message(notice)
    await drain_recalls(plugin)
    content = json.loads(conversation.history)[-1]["content"]
    assert "发送的消息已被撤回。" in content
    assert "发送后" not in content


@pytest.mark.parametrize("timestamp", ["invalid", None, True, -1, 10**30])
@pytest.mark.asyncio
async def test_invalid_source_time_is_explicitly_unknown(timestamp):
    plugin, conversation = make_plugin([])
    _, notice = await track_message(plugin, conversation, sent_at=timestamp)
    await plugin.mark_recalled_message(notice)
    await drain_recalls(plugin)
    content = json.loads(conversation.history)[-1]["content"]
    assert "用户 10001 于 未知时间 发送的消息已被撤回。" in content
    assert "发送后" not in content


@pytest.mark.asyncio
async def test_removed_conversation_is_not_recreated():
    plugin, conversation = make_plugin([])
    _, notice = await track_message(plugin, conversation)
    plugin.context.conversation_manager.get_conversation.return_value = None
    await plugin.mark_recalled_message(notice)
    await drain_recalls(plugin)
    plugin.context.conversation_manager.update_conversation.assert_not_awaited()
    assert next(iter(plugin.recall_messages.values()))["notified"] is False


@pytest.mark.parametrize("history", ["{", "{}", "null"])
@pytest.mark.asyncio
async def test_invalid_history_is_not_replaced_with_default(history):
    plugin, conversation = make_plugin([])
    _, notice = await track_message(plugin, conversation)
    conversation.history = history
    await plugin.mark_recalled_message(notice)
    await drain_recalls(plugin)
    plugin.context.conversation_manager.update_conversation.assert_not_awaited()
    assert conversation.history == history
    entry = next(iter(plugin.recall_messages.values()))
    assert entry["pending"] is False
    assert entry["notified"] is False


@pytest.mark.asyncio
async def test_failed_append_can_retry_without_marking_delivered():
    original = [{"role": "user", "content": "原文"}]
    plugin, conversation = make_plugin(original)
    _, notice = await track_message(plugin, conversation, "原文")
    manager = plugin.context.conversation_manager
    update = manager.update_conversation.side_effect
    manager.update_conversation.side_effect = RuntimeError("database unavailable")
    await plugin.mark_recalled_message(notice)
    await drain_recalls(plugin)
    entry = next(iter(plugin.recall_messages.values()))
    assert entry["notified"] is False
    assert entry["pending"] is False
    assert json.loads(conversation.history) == original
    manager.update_conversation.side_effect = update
    await plugin.mark_recalled_message(notice)
    await drain_recalls(plugin)
    assert entry["notified"] is True
    assert len(json.loads(conversation.history)) == 2


@pytest.mark.asyncio
async def test_tracking_keeps_only_bounded_excerpt_and_no_history_positions():
    plugin, conversation = make_plugin([])
    prompt = "原文\n带换行" * 100
    _, notice = await track_message(plugin, conversation, prompt)
    entry = next(iter(plugin.recall_messages.values()))
    assert entry["excerpt"] == prompt[:RECALL_EXCERPT_MAX_CHARS] + "…"
    assert not {
        "history_length",
        "history_index",
        "history_persisted",
        "live_message",
        "message_content",
        "prompt",
    }.intersection(entry)
    await plugin.mark_recalled_message(notice)
    await drain_recalls(plugin)
    content = json.loads(conversation.history)[-1]["content"]
    assert content.endswith("]")
    excerpt = content.split("原消息摘录（仅用于定位）：", 1)[1][:-1]
    assert json.loads(excerpt) == entry["excerpt"]
    assert "\n" not in content


@pytest.mark.asyncio
async def test_duplicate_tracking_does_not_reset_delivery_state():
    plugin, conversation = make_plugin([])
    source, notice = await track_message(plugin, conversation)
    await plugin.mark_recalled_message(notice)
    await drain_recalls(plugin)
    await plugin.track_context_message(
        source, ProviderRequest(prompt="重复处理", conversation=conversation)
    )
    await plugin.mark_recalled_message(notice)
    await drain_recalls(plugin)
    plugin.context.conversation_manager.update_conversation.assert_awaited_once()


@pytest.mark.parametrize("started", [False, True])
@pytest.mark.asyncio
async def test_cancelled_append_does_not_mark_notice_delivered(started):
    plugin, conversation = make_plugin([])
    source, notice = await track_message(plugin, conversation)
    async with session_lock_manager.acquire_lock(source.unified_msg_origin):
        await plugin.mark_recalled_message(notice)
        if started:
            await asyncio.sleep(0)
        tasks = list(plugin.recall_tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    entry = next(iter(plugin.recall_messages.values()))
    assert entry["pending"] is False
    assert entry["notified"] is False
    assert not plugin.recall_tasks
    plugin.context.conversation_manager.update_conversation.assert_not_awaited()


@pytest.mark.asyncio
async def test_termination_cancels_pending_recall_writes():
    plugin, conversation = make_plugin([])
    plugin.notification_tasks = set()
    plugin.notification_events = set()
    plugin.handoff_tasks = set()
    plugin.cleanup_task = None
    plugin.web_reader = SimpleNamespace(close=AsyncMock())
    source, notice = await track_message(plugin, conversation)
    async with session_lock_manager.acquire_lock(source.unified_msg_origin):
        await plugin.mark_recalled_message(notice)
        await asyncio.sleep(0)
        tasks = list(plugin.recall_tasks)
        await asyncio.wait_for(plugin.terminate(), 3)
    assert all(task.cancelled() for task in tasks)
    assert not plugin.recall_tasks
    assert not plugin.recall_messages
    plugin.context.conversation_manager.update_conversation.assert_not_awaited()
