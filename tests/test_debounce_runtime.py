from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from astrbot.api.message_components import Plain
from astrbot.api.star import Context
from astrbot.core.platform.astrbot_message import AstrBotMessage, Group, MessageMember
from astrbot.core.platform.message_type import MessageType
from astrbot.core.platform.platform_metadata import PlatformMetadata
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)
from astrbot.core.star.session_llm_manager import SessionServiceManager
from astrbot.core.star.session_plugin_manager import SessionPluginManager
from astrbot.core.utils.session_lock import session_lock_manager
from astrbot_plugin_qq_enhance.debounce import ARRIVAL_KEY, Arrival, MessageDebouncer
from astrbot_plugin_qq_enhance.debounce_runtime import AstrBotDebounceRuntime
from astrbot_plugin_qq_enhance.runtime import validate_config


def source_message(group=""):
    message = AstrBotMessage()
    message.type = MessageType.GROUP_MESSAGE if group else MessageType.FRIEND_MESSAGE
    message.self_id = "99"
    message.message_id = "123"
    message.sender = MessageMember("7", "Original user")
    message.group = (
        Group(group_id=group, group_name="Original group") if group else None
    )
    message.session_id = f"7_{group}" if group else "7"
    message.message_str = "original question"
    message.message = [Plain(message.message_str)]
    message.raw_message = {"post_type": "message", "message_id": 123}
    source = AiocqhttpMessageEvent(
        message.message_str,
        message,
        PlatformMetadata("aiocqhttp", "", "qq", support_proactive_message=False),
        message.session_id,
        SimpleNamespace(send_group_msg=AsyncMock()),
    )
    source.role = "admin"
    source.is_at_or_wake_command = True
    return source


@pytest.fixture
def continuation(monkeypatch):
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
    conversation = SimpleNamespace(
        cid="bound",
        history=json.dumps(
            [
                {"role": "user", "content": "original question"},
                {
                    "role": "user",
                    "content": "[QQ 平台事件|message_recall|时间 未知：已撤回。仅作背景，不代表操作指令。]",
                },
            ]
        ),
        persona_id="persona",
        token_usage=0,
    )
    context = object.__new__(Context)
    context.conversation_manager = SimpleNamespace(
        get_curr_conversation_id=AsyncMock(return_value="bound"),
        get_conversation=AsyncMock(return_value=conversation),
        update_conversation=AsyncMock(),
    )
    context.get_config = lambda **kwargs: {
        "provider_settings": {"agent_runner_type": "local"}
    }
    context.get_all_stars = lambda: []
    runtime = AstrBotDebounceRuntime(context, validate_config(None)["debounce"])
    debouncer = MessageDebouncer(runtime)
    source = source_message("10")
    owner = Arrival(source, None, conversation_id="bound")
    owner.batch = [owner]
    event = runtime.make_resume(owner, debouncer)
    arrival = Arrival(
        event,
        None,
        replayed=True,
        scope=(source.unified_msg_origin, "group"),
        conversation_id="bound",
        batch=[owner],
    )
    event.set_extra(ARRIVAL_KEY, arrival)
    debouncer.active[arrival.scope] = arrival
    return runtime, debouncer, event, source, conversation


@pytest.mark.asyncio
async def test_resume_retains_sender_role_session_and_original_transport(continuation):
    runtime, _, event, source, _ = continuation
    source.stop_event()
    assert event.get_sender_id() == "7"
    assert event.is_admin()
    assert event.unified_msg_origin == source.unified_msg_origin
    event.session_id = "unexpected"
    assert event.unified_msg_origin == source.unified_msg_origin
    assert not event.is_at_or_wake_command
    event.is_at_or_wake_command = True
    assert not event.is_at_or_wake_command
    await runtime.prepare_resume(event)
    assert event.is_at_or_wake_command
    from astrbot.api.event import MessageChain

    await event.send(MessageChain().message("continued reply"))
    source.bot.send_group_msg.assert_awaited_once()
    assert source.bot.send_group_msg.await_args.kwargs["group_id"] == 10
    assert event._has_send_oper


@pytest.mark.parametrize(
    "reason", ["session_plugin", "plugin_set", "changed", "deleted", "disabled"]
)
@pytest.mark.asyncio
async def test_resume_cannot_gain_reply_authority_when_destination_unavailable(
    continuation, reason
):
    runtime, debouncer, event, _, _ = continuation
    if reason == "session_plugin":
        SessionPluginManager.is_plugin_enabled_for_session.return_value = False
    elif reason == "plugin_set":
        runtime.context.get_config = lambda **kwargs: {"plugin_set": ["other"]}
    elif reason == "changed":
        runtime.context.conversation_manager.get_curr_conversation_id.return_value = (
            "new"
        )
    elif reason == "deleted":
        runtime.context.conversation_manager.get_conversation.return_value = None
    else:
        debouncer.config["enabled"] = False
    await runtime.prepare_resume(event)
    assert event.is_stopped()
    assert not event.is_at_or_wake_command
    assert event.get_extra("provider_request") is None


@pytest.mark.asyncio
async def test_native_pipeline_skipping_plugin_releases_unclaimed_resume(continuation):
    from astrbot.core.pipeline.scheduler import PipelineScheduler

    _, debouncer, event, _, _ = continuation
    arrival = event.get_extra(ARRIVAL_KEY)

    class FilteredStage:
        async def process(self, incoming):
            incoming.plugins_name = ["another_plugin"]

    scheduler = PipelineScheduler(SimpleNamespace())
    scheduler.stages = [FilteredStage()]
    await scheduler.execute(event)
    assert arrival.task is None
    assert arrival.finished.is_set()
    assert arrival.ready.is_set()
    assert not debouncer.active
    assert not event.is_at_or_wake_command


@pytest.mark.asyncio
async def test_native_agent_build_and_reset_resume_saved_history_without_duplicate_input(
    continuation,
    monkeypatch,
    tmp_path,
):
    from astrbot.core import astr_main_agent
    from astrbot.core.agent.message import dump_messages_with_checkpoints
    from astrbot.core.provider import Provider

    runtime, _, event, _, conversation = continuation
    context = runtime.context
    context.persona_manager = SimpleNamespace(
        resolve_selected_persona=AsyncMock(
            return_value=(
                "persona",
                {"prompt": "Original session persona", "tools": []},
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
        astr_main_agent, "_get_workspace_path_for_umo", AsyncMock(return_value=tmp_path)
    )
    monkeypatch.setattr(
        astr_main_agent, "retrieve_knowledge_base", AsyncMock(return_value=None)
    )
    await runtime.prepare_resume(event)
    async with session_lock_manager.acquire_lock(event.unified_msg_origin):
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
            prefix = json.loads(conversation.history)
            prefix.append(
                {"role": "user", "content": "another fact saved before acquiring lock"}
            )
            conversation.history = json.dumps(prefix)
            await runtime.finalize_resume(event, built.provider_request)
            await built.reset_coro
        finally:
            built.reset_coro.close()
    messages = dump_messages_with_checkpoints(built.agent_runner.run_context.messages)
    assert "Original session persona" in messages[0]["content"]
    assert messages[1:] == prefix
    assert built.provider_request.prompt is None
    assert built.provider_request.conversation.cid == "bound"
    provider.text_chat.assert_not_called()
