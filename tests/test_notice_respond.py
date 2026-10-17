from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from weakref import WeakSet

import pytest

from test_debounce import Event, Harness, context_notice, texts, wait
from test_notice_context import NoticeEvent, payload

from astrbot.core.agent.tool import FunctionTool, ToolSet
from astrbot.core.platform.message_session import MessageSession
from astrbot.core.platform.platform_metadata import PlatformMetadata
from astrbot.core.provider.entities import ProviderRequest
from astrbot.core.star.session_llm_manager import SessionServiceManager
from astrbot.core.star.session_plugin_manager import SessionPluginManager
from astrbot_plugin_qq_enhance.debounce_runtime import AstrBotDebounceRuntime
from astrbot_plugin_qq_enhance.notice_context import DEFAULT_NOTICE_POLICIES
from astrbot_plugin_qq_enhance.request_notification import (
    NoticeResponseEvent,
    NotificationOnlyTool,
)
from astrbot_plugin_qq_enhance.runtime import validate_config


@pytest.fixture
def harness(monkeypatch):
    monkeypatch.setattr(
        SessionServiceManager,
        "should_process_llm_request",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        SessionPluginManager,
        "is_plugin_enabled_for_session",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr("astrbot.core.utils.metrics.Metric.upload", AsyncMock())
    harness = Harness()
    harness.plugin.config["notice_events"]["group_card"]["mode"] = "respond"
    harness.plugin.notification_events = WeakSet()
    harness.queue = asyncio.Queue()
    harness.platform = SimpleNamespace(
        meta=lambda: PlatformMetadata(name="aiocqhttp", id="qq", description=""),
        get_client=lambda: SimpleNamespace(),
    )
    harness.plugin.context.get_platform_inst = lambda _: harness.platform
    harness.plugin.context.get_event_queue = lambda: harness.queue
    harness.plugin.context.send_message = AsyncMock(return_value=True)
    return harness


async def queued(harness):
    return await asyncio.wait_for(harness.queue.get(), 3)


async def drain_responses(harness):
    jobs = list(harness.plugin.notice_context.response_jobs)
    if jobs:
        await asyncio.wait_for(asyncio.gather(*jobs), 3)


def start_response(harness, event, **kwargs):
    # Let the shared native-message harness exercise the real event class.
    event.sender = event.get_sender_id()
    event.group = event.get_group_id()
    event.prepared = asyncio.Event()
    event.entered = asyncio.Event()
    event.allow_reply = asyncio.Event()
    event.cleaned_files = []
    return harness.start(event, **kwargs)


def test_schema_and_runtime_allow_respond_except_bot_offline():
    schema = json.loads(
        (Path(__file__).parents[1] / "_conf_schema.json").read_text(encoding="utf-8")
    )
    for kind in ("message_recall", *DEFAULT_NOTICE_POLICIES):
        options = schema["notice_events"]["items"][kind]["items"]["mode"]["options"]
        if kind == "bot_offline":
            assert options == ["off", "context"]
            with pytest.raises(ValueError, match="bot_offline.mode"):
                validate_config({"notice_events": {kind: {"mode": "respond"}}})
        else:
            assert options == ["off", "context", "respond"]
            assert (
                validate_config({"notice_events": {kind: {"mode": "respond"}}})[
                    "notice_events"
                ][kind]["mode"]
                == "respond"
            )


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [True, False])
async def test_respond_without_batch_uses_saved_fact_once(harness, enabled):
    harness.plugin.config["debounce"]["enabled"] = enabled
    try:
        await harness.plugin.capture_notice_context(context_notice())
        event = await queued(harness)
        assert isinstance(event, NoticeResponseEvent)
        assert event.unified_msg_origin == "qq:GroupMessage:300"
        assert event.get_sender_id().startswith("qq_notice_response:")
        assert event.debounce_sender_id == "7"
        assert not event.is_admin()
        task = start_response(harness, event)
        await wait(event.prepared)
        assert not harness.manager.history(event)
        assert len(harness.requests[-1]) == 1
        assert "group_card" in texts(harness.requests[-1])[0]
        event.allow_reply.set()
        await task
        assert len(harness.manager.history(event)) == 2
        assert harness.queue.empty()
        event.cleanup_temporary_local_files()
        await harness.drain_notices()
        assert not harness.plugin.notice_context.pending
    finally:
        await harness.finish()


@pytest.mark.asyncio
async def test_respond_restarts_original_batch_without_second_reply(harness):
    first = Event("前一条消息", 1, group=300)
    try:
        task = harness.start(first)
        await wait(first.prepared)
        await harness.plugin.capture_notice_context(context_notice())
        resumed = await harness.wait_resumed()
        assert task.cancelled()
        assert resumed.get_sender_id() == first.get_sender_id()
        assert not getattr(resumed, "notification_only", False)
        assert len(harness.requests[-1]) == 2
        resumed.allow_reply.set()
        await harness.tasks[-1]
        await drain_responses(harness)
        assert harness.queue.empty()
        await harness.drain_notices()
        assert not harness.plugin.notice_context.pending
        assert len(harness.manager.history(resumed)) == 3
    finally:
        await harness.finish()


@pytest.mark.asyncio
@pytest.mark.parametrize("protected", ["tool", "streaming", "capacity"])
async def test_respond_falls_back_after_nonreplaceable_generation(harness, protected):
    if protected == "capacity":
        harness.plugin.config["debounce"]["max_messages"] = 1
    first = Event("已经开始处理", 1, group=300)
    try:
        first_task = harness.start(
            first, tool=protected == "tool", streaming=protected == "streaming"
        )
        await wait(first.prepared)
        await harness.plugin.capture_notice_context(context_notice())
        assert harness.queue.empty()
        assert not first_task.done()
        first.allow_reply.set()
        await first_task
        event = await queued(harness)
        task = start_response(harness, event)
        await wait(event.prepared)
        assert texts(harness.requests[-1])[:2] == ["已经开始处理", "reply"]
        assert "group_card" in texts(harness.requests[-1])[2]
        event.allow_reply.set()
        await task
        assert len(harness.manager.history(event)) == 4
        assert harness.queue.empty()
    finally:
        await harness.finish()


@pytest.mark.asyncio
async def test_ordinary_followup_merges_with_standalone_notice_by_subject(harness):
    harness.plugin.config["debounce"]["shared_group"] = False
    try:
        await harness.plugin.capture_notice_context(context_notice())
        notice = await queued(harness)
        notice_task = start_response(harness, notice)
        await wait(notice.prepared)
        followup = Event("欢迎一下这位朋友", 2, group=300)
        task = harness.start(followup)
        await wait(followup.prepared)
        assert notice_task.cancelled()
        inputs = texts(harness.requests[-1])
        assert len(inputs) == 2
        assert "group_card" in inputs[0]
        assert inputs[1] == "欢迎一下这位朋友"
        followup.allow_reply.set()
        await task
        assert len(harness.manager.history(followup)) == 3
    finally:
        await harness.finish()


@pytest.mark.asyncio
async def test_repeated_respond_and_multiple_queued_notices_reply_once(harness):
    try:
        notice = context_notice()
        await harness.plugin.capture_notice_context(notice)
        await harness.plugin.capture_notice_context(notice)
        second = context_notice()
        second.message_obj.raw_message.update(card_new="又一个新群名片", time=1002)
        await harness.plugin.capture_notice_context(second)
        one, two = await queued(harness), await queued(harness)
        first_task = start_response(harness, one)
        await wait(one.prepared)
        assert len(harness.requests[-1]) == 2
        one.allow_reply.set()
        await first_task
        task = start_response(harness, two)
        await task
        assert two.is_stopped()
        assert len(harness.requests) == 1
        assert len(harness.manager.history(one)) == 3
        assert harness.queue.empty()
    finally:
        await harness.finish()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reason",
    [
        "switched",
        "cleared",
        "deleted",
        "ai_disabled",
        "plugin_disabled",
        "remote_runner",
    ],
)
async def test_respond_does_not_wake_unavailable_destination(harness, reason):
    try:
        if reason in {"switched", "cleared"}:
            harness.manager.histories["qq:GroupMessage:300", "conversation"] = [
                {"role": "user", "content": "旧历史"}
            ]
            await harness.plugin.capture_notice_context(context_notice())
            event = await queued(harness)
            if reason == "switched":
                harness.manager.current_id = "new-conversation"
            else:
                harness.manager.histories.clear()
            req = ProviderRequest(prompt="temporary")
            await harness.plugin.prepare_platform_notification(event, req)
            assert event.is_stopped()
            return
        if reason == "deleted":
            harness.manager.get_conversation = AsyncMock(return_value=None)
        elif reason == "save_failed":
            harness.manager.update_conversation = AsyncMock(
                side_effect=RuntimeError("database failed")
            )
        elif reason == "ai_disabled":
            harness.plugin.context.get_config = lambda **_: {
                "provider_settings": {"enable": False}
            }
        elif reason == "plugin_disabled":
            SessionPluginManager.is_plugin_enabled_for_session.return_value = False
        elif reason == "remote_runner":
            harness.plugin.context.get_config = lambda **_: {
                "provider_settings": {"agent_runner_type": "dify"}
            }
        await harness.plugin.capture_notice_context(context_notice())
        await drain_responses(harness)
        assert harness.queue.empty()
        await harness.drain_notices()
        assert not harness.plugin.notice_context.pending
    finally:
        await harness.finish()


@pytest.mark.asyncio
async def test_standalone_notice_restricts_tools_including_after_resume(harness):
    try:
        await harness.plugin.capture_notice_context(context_notice())
        event = await queued(harness)
        conversation = await harness.manager.get_conversation(
            event.unified_msg_origin, "conversation"
        )
        for source in (
            event,
            AstrBotDebounceRuntime.make_resume(
                harness.runtime, SimpleNamespace(event=event), harness.plugin.debouncer
            ),
        ):
            req = ProviderRequest(
                prompt="temporary",
                conversation=conversation,
                func_tool=ToolSet(
                    [FunctionTool(name="action", description="action", parameters={})]
                ),
            )
            await harness.plugin.prepare_platform_notification(source, req)
            assert isinstance(req.func_tool.tools[0], NotificationOnlyTool)
        assert (
            req.prompt == "temporary"
        )  # Continuations are prepared by the debounce runtime.
    finally:
        await harness.finish()


@pytest.mark.asyncio
@pytest.mark.parametrize("persist", [False, True])
async def test_respond_recall_reuses_original_conversation_and_no_duplicate(
    harness, persist
):
    harness.plugin.config["notice_events"]["message_recall"]["mode"] = "respond"
    harness.plugin.config["inbound"]["component_spoof_protection"][
        "persist_verification_in_history"
    ] = persist
    tag = '<qq_verified_components types="notice"/>'
    first = Event("撤回这条消息", 1, group=300)
    try:
        task = harness.start(first)
        await wait(first.prepared)
        first.allow_reply.set()
        await task
        recall = Event(
            "",
            None,
            group=300,
            raw={
                "post_type": "notice",
                "notice_type": "group_recall",
                "message_id": 1,
                "user_id": 7,
                "operator_id": 7,
                "group_id": 300,
                "self_id": 99,
                "time": 1002,
            },
        )
        recall.is_at_or_wake_command = False
        await harness.plugin.capture_notice_context(recall)
        event = await queued(harness)
        assert event.delivery.notice.kind == "message_recall"
        task = start_response(harness, event)
        await wait(event.prepared)
        assert len(harness.requests[-1]) == 3
        assert tag in str(event.runtime.messages[-1])
        assert (tag in str(harness.requests[-1][-1])) is persist
        event.allow_reply.set()
        await task
        assert len(harness.manager.history(event)) == 4
        assert (tag in str(harness.manager.history(event)[-2])) is persist
    finally:
        await harness.finish()


@pytest.mark.asyncio
async def test_respond_routes_private_and_isolated_group_sessions(harness):
    harness.plugin.config["notice_events"]["friend_add"]["mode"] = "respond"
    try:
        source = NoticeEvent(payload("friend_add"))
        source.get_platform_id = lambda: "qq"
        await harness.plugin.capture_notice_context(source)
        private = await queued(harness)
        assert private.session == MessageSession.from_str("qq:FriendMessage:7")
        harness.plugin.context.get_config = lambda **_: {
            "platform_settings": {"unique_session": True}
        }
        await harness.plugin.capture_notice_context(context_notice())
        group = await queued(harness)
        assert group.unified_msg_origin == "qq:GroupMessage:7_300"
        group.session_id = "internal-sender_300"
        assert group.unified_msg_origin == "qq:GroupMessage:7_300"
    finally:
        await harness.finish()


@pytest.mark.asyncio
async def test_unload_cancels_pending_respond_and_stops_queued_event(harness):
    try:
        await harness.plugin.capture_notice_context(context_notice())
        event = await queued(harness)
        await harness.plugin.notice_context.close()
        assert event.is_stopped()
        await harness.drain_notices()
        assert not harness.plugin.notice_context.pending
        assert not harness.plugin.notice_context.response_jobs
    finally:
        await harness.finish()


@pytest.mark.asyncio
async def test_respond_updates_initial_waiting_window(harness):
    harness.plugin.config["debounce"]["initial_window_seconds"] = 0.03
    first = Event("尚在等待的消息", 1, group=300)
    try:
        task = harness.start(first)
        await wait(first.entered)
        await harness.plugin.capture_notice_context(context_notice())
        resumed = first
        await wait(first.prepared)
        assert not task.done()
        resumed.allow_reply.set()
        await harness.tasks[-1]
        await drain_responses(harness)
        assert harness.queue.empty()
        assert len(harness.manager.history(first)) == 3
    finally:
        await harness.finish()


@pytest.mark.asyncio
async def test_second_notice_continues_standalone_response(harness):
    harness.plugin.config["debounce"]["max_messages"] = 2
    try:
        await harness.plugin.capture_notice_context(context_notice())
        event = await queued(harness)
        first = start_response(harness, event)
        await wait(event.prepared)
        second = context_notice()
        second.message_obj.raw_message.update(card_new="另一个名字", time=1002)
        await harness.plugin.capture_notice_context(second)
        resumed = await harness.wait_resumed()
        assert first.cancelled()
        assert resumed.notification_only
        assert resumed.debounce_sender_id == "7"
        assert len(harness.requests[-1]) == 2
        resumed.allow_reply.set()
        await harness.tasks[-1]
        await drain_responses(harness)
        assert harness.queue.empty()
        assert len(harness.manager.history(resumed)) == 3
    finally:
        await harness.finish()


@pytest.mark.asyncio
async def test_group_wide_notice_saves_all_isolated_histories_but_queues_one_reply(
    harness,
):
    harness.plugin.context.get_config = lambda **_: {
        "platform_settings": {"unique_session": True}
    }
    harness.plugin.config["notice_events"]["notify/group_name"]["mode"] = "respond"
    harness.manager.sessions = {"qq:GroupMessage:7_300", "qq:GroupMessage:8_300"}
    try:
        raw = payload("notify/group_name", name_new="新群名")
        source = Event("", None, group=300, raw=raw)
        source.is_at_or_wake_command = False
        await harness.plugin.capture_notice_context(source)
        event = await queued(harness)
        await drain_responses(harness)
        assert event.unified_msg_origin == "qq:GroupMessage:7_300"
        assert harness.queue.empty()
        task = start_response(harness, event)
        await wait(event.prepared)
        event.allow_reply.set()
        await task
        await harness.drain_notices()
        for umo in harness.manager.sessions:
            expected = 2 if umo == event.unified_msg_origin else 1
            assert len(harness.manager.histories[umo, "conversation"]) == expected
    finally:
        await harness.finish()


@pytest.mark.asyncio
async def test_other_member_notice_does_not_take_over_sender_batch(harness):
    harness.plugin.config["debounce"]["shared_group"] = False
    original = Event("成员八的消息", 1, sender=8, group=300)
    try:
        task = harness.start(original)
        await wait(original.prepared)
        await harness.plugin.capture_notice_context(context_notice())
        assert not task.cancelled()
        original.allow_reply.set()
        await task
        response = await queued(harness)
        assert response.debounce_sender_id == "7"
        assert not harness.resumed
    finally:
        await harness.finish()


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [True, False])
async def test_normal_request_reading_queued_fact_suppresses_duplicate_notice(
    harness, enabled
):
    harness.plugin.config["debounce"]["enabled"] = enabled
    try:
        await harness.plugin.capture_notice_context(context_notice())
        notice = await queued(harness)
        ordinary = Event("我看见改名了", 1, group=300)
        task = harness.start(ordinary)
        await wait(ordinary.prepared)
        ordinary.allow_reply.set()
        await task
        notice_task = start_response(harness, notice)
        if enabled:
            await notice_task
            assert notice.is_stopped()
            assert len(harness.requests) == 1
        else:
            await wait(notice.prepared)
            notice.allow_reply.set()
            await notice_task
            assert not notice.is_stopped()
            assert len(harness.requests) == 2
        assert len(harness.manager.history(ordinary)) == (3 if enabled else 4)
    finally:
        await harness.finish()


@pytest.mark.asyncio
async def test_queued_notice_stays_deduplicated_after_seen_cache_expires(harness):
    try:
        notice = context_notice()
        await harness.plugin.capture_notice_context(notice)
        await queued(harness)
        harness.plugin.notice_context.seen.clear()
        await harness.plugin.capture_notice_context(notice)
        await drain_responses(harness)
        assert harness.queue.empty()
        assert not harness.manager.histories
        assert len(harness.plugin.notice_context.pending) == 1
    finally:
        await harness.finish()


@pytest.mark.asyncio
async def test_native_agent_build_preserves_persona_and_saved_event_without_duplicate(
    harness, monkeypatch, tmp_path
):
    from astrbot.api.star import Context
    from astrbot.core import astr_main_agent
    from astrbot.core.agent.message import dump_messages_with_checkpoints
    from astrbot.core.provider import Provider

    try:
        await harness.plugin.capture_notice_context(context_notice())
        event = await queued(harness)
        context = object.__new__(Context)
        context.get_config = harness.plugin.context.get_config
        context.conversation_manager = harness.manager
        # AstrBot reads these conversation attributes while selecting persona.
        conversation = await harness.manager.get_conversation(
            event.unified_msg_origin, "conversation"
        )
        conversation.persona_id = "persona"
        context.conversation_manager.get_conversation = AsyncMock(
            return_value=conversation
        )
        context.persona_manager = SimpleNamespace(
            resolve_selected_persona=AsyncMock(
                return_value=(
                    "persona",
                    {"prompt": "当前会话人格", "tools": []},
                    None,
                    False,
                )
            )
        )
        context.subagent_orchestrator = None
        context.get_llm_tool_manager = lambda: SimpleNamespace(
            get_builtin_tool=lambda tool: tool()
        )
        provider = MagicMock(spec=Provider)
        provider.provider_config = {
            "id": "provider",
            "max_context_tokens": 10000,
            "modalities": [],
        }
        provider.get_model.return_value = "test-model"
        context.get_using_provider_async = AsyncMock(return_value=provider)
        monkeypatch.setattr(
            astr_main_agent.SkillManager, "list_skills", lambda *args, **kwargs: []
        )
        monkeypatch.setattr(
            astr_main_agent,
            "_get_workspace_path_for_umo",
            AsyncMock(return_value=tmp_path),
        )
        monkeypatch.setattr(
            astr_main_agent, "retrieve_knowledge_base", AsyncMock(return_value=None)
        )
        built = await astr_main_agent.build_main_agent(
            event=event,
            plugin_context=context,
            config=astr_main_agent.MainAgentBuildConfig(
                tool_call_timeout=5,
                computer_use_runtime="none",
                add_cron_tools=False,
                provider_settings={"computer_use_runtime": "none"},
            ),
            apply_reset=False,
        )
        assert built is not None
        try:
            await harness.plugin.prepare_platform_notification(
                event, built.provider_request
            )
            assert not event.is_stopped()
            await built.reset_coro
        finally:
            built.reset_coro.close()
        from astrbot_plugin_qq_enhance.qq_debounce import ArrivalFilter

        ArrivalFilter().filter(event, {})
        harness.plugin.notice_context.bind_response(event)
        await harness.plugin.bind_debounce_request(event, built.provider_request)
        await harness.plugin.snapshot_debounce_input(
            event, built.agent_runner.run_context
        )
        messages = dump_messages_with_checkpoints(
            built.agent_runner.run_context.messages
        )
        assert "当前会话人格" in messages[0]["content"]
        assert len(messages[1:]) == 1
        assert "group_card" in messages[1]["content"]
        assert not json.loads(conversation.history)
        assert built.provider_request.prompt is None
        provider.text_chat.assert_not_called()
    finally:
        await harness.finish()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["context", "respond"])
@pytest.mark.parametrize("outcome", ["reply", "empty", "error"])
async def test_batch_events_use_native_save_with_unsaved_completion_fallback(
    harness, mode, outcome
):
    harness.plugin.config["notice_events"]["group_card"]["mode"] = mode
    harness.plugin.config["debounce"]["initial_window_seconds"] = 0.02
    original = Event("当前输入", 1, group=300)
    update = AsyncMock(wraps=harness.manager.update_conversation)
    harness.manager.update_conversation = update
    try:
        task = harness.start(
            original, fail=outcome == "error", empty=outcome == "empty"
        )
        await wait(original.entered)
        await harness.plugin.capture_notice_context(context_notice())
        await wait(original.prepared)
        assert not harness.manager.history(original)
        assert len(harness.requests[-1]) == 2
        assert not harness.resumed
        update.assert_not_awaited()
        original.allow_reply.set()
        if outcome == "error":
            with pytest.raises(RuntimeError, match="provider failed"):
                await task
        else:
            await task
        await harness.drain_notices()
        history = texts(harness.manager.history(original))
        assert sum("QQ 平台事件|group_card|" in text for text in history) == 1
        assert (
            sum('<qq_verified_components types="notice"/>' in text for text in history)
            == 1
        )
        assert len(history) == (3 if outcome == "reply" else 1)
        update.assert_awaited_once()
        assert harness.queue.empty()
    finally:
        await harness.finish()


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [True, False])
@pytest.mark.parametrize("outcome", ["reply", "empty", "error"])
async def test_standalone_events_have_no_presave_and_keep_unsaved_input(
    harness, enabled, outcome
):
    harness.plugin.config["debounce"]["enabled"] = enabled
    update = AsyncMock(wraps=harness.manager.update_conversation)
    harness.manager.update_conversation = update
    try:
        await harness.plugin.capture_notice_context(context_notice())
        event = await queued(harness)
        task = start_response(
            harness, event, fail=outcome == "error", empty=outcome == "empty"
        )
        await wait(event.prepared)
        update.assert_not_awaited()
        assert not harness.manager.history(event)
        event.allow_reply.set()
        if outcome == "error":
            with pytest.raises(RuntimeError, match="provider failed"):
                await task
        else:
            await task
        await harness.drain_notices()
        history = texts(harness.manager.history(event))
        assert len(history) == (2 if outcome == "reply" else 1)
        assert sum("QQ 平台事件|group_card|" in text for text in history) == 1
        assert (
            sum('<qq_verified_components types="notice"/>' in text for text in history)
            == 1
        )
        update.assert_awaited_once()
    finally:
        await harness.finish()


@pytest.mark.asyncio
async def test_cancelled_event_input_retries_failed_save_before_next_batch(harness):
    harness.plugin.config["notice_events"]["group_card"]["mode"] = "context"
    harness.plugin.config["debounce"]["initial_window_seconds"] = 0.02
    first, second, third = (
        Event(text, i, group=300)
        for i, text in enumerate(("原输入", "取消续接", "继续"), 1)
    )
    update = harness.manager.update_conversation
    try:
        first_task = harness.start(first)
        await wait(first.entered)
        await harness.plugin.capture_notice_context(context_notice())
        await wait(first.prepared)
        harness.manager.update_conversation = AsyncMock(
            side_effect=RuntimeError("database failed")
        )
        second_task = harness.start(second)
        with pytest.raises(RuntimeError, match="database failed"):
            await second_task
        assert first_task.cancelled()
        assert harness.plugin.debouncer.failed
        harness.manager.update_conversation = update
        task = harness.start(third)
        await wait(third.prepared)
        request = texts(harness.requests[-1])
        assert request[0] == "原输入"
        assert "QQ 平台事件|group_card|" in request[1]
        assert request[2] == "继续"
        third.allow_reply.set()
        await task
        await harness.drain_notices()
        assert len(harness.manager.history(third)) == 4
    finally:
        harness.manager.update_conversation = update
        await harness.finish()


@pytest.mark.asyncio
async def test_standalone_event_with_empty_initial_agent_context_can_be_replaced(
    harness,
):
    harness.plugin.config["inbound"]["component_spoof_protection"]["enabled"] = False
    try:
        await harness.plugin.capture_notice_context(context_notice())
        event = await queued(harness)
        task = start_response(harness, event)
        await wait(event.prepared)
        assert len(event.runtime.messages) == 1
        followup = Event("补充消息", 2, group=300)
        next_task = harness.start(followup)
        await wait(followup.prepared)
        assert task.cancelled()
        assert "group_card" in texts(harness.requests[-1])[0]
        followup.allow_reply.set()
        await next_task
        await harness.drain_notices()
        assert len(harness.manager.history(followup)) == 3
    finally:
        await harness.finish()


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", ["sender", "capacity", "not_woken"])
async def test_queued_event_cannot_bypass_batch_ownership_or_capacity(
    harness, boundary
):
    harness.plugin.config["debounce"]["shared_group"] = False
    if boundary == "capacity":
        harness.plugin.config["debounce"]["max_messages"] = 1
    try:
        await harness.plugin.capture_notice_context(context_notice())
        notice = await queued(harness)
        ordinary = Event(
            "随后消息", 1, sender=8 if boundary == "sender" else 7, group=300
        )
        if boundary == "not_woken":
            ordinary.is_at_or_wake_command = False
        task = harness.start(ordinary)
        await wait(ordinary.prepared)
        assert len(harness.requests[-1]) == 1
        ordinary.allow_reply.set()
        await task
        notice_task = start_response(harness, notice)
        await wait(notice.prepared)
        assert not notice.is_stopped()
        assert "group_card" in texts(harness.requests[-1])[-1]
        notice.allow_reply.set()
        await notice_task
        await harness.drain_notices()
        assert len(harness.manager.history(ordinary)) == 4
    finally:
        await harness.finish()
