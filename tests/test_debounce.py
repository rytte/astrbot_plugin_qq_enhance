from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from astrbot.core.agent.message import (
    Message,
    TextPart,
    bind_checkpoint_messages,
    dump_messages_with_checkpoints,
)
from astrbot.core.provider.entities import ProviderRequest
from astrbot.core.star.session_llm_manager import SessionServiceManager
from astrbot.core.utils.session_lock import session_lock_manager
from astrbot_plugin_qq_enhance.debounce import (
    ARRIVAL_KEY,
    ArrivalFilter,
    MessageDebouncer,
)
from astrbot_plugin_qq_enhance.main import QQEnhancePlugin
from astrbot_plugin_qq_enhance.runtime import validate_config


@pytest.fixture(autouse=True)
def enabled_session(monkeypatch):
    monkeypatch.setattr(
        SessionServiceManager,
        "should_process_llm_request",
        AsyncMock(return_value=True),
    )


class Event:
    def __init__(self, text, message_id, *, sender=7, group="", raw=None):
        self.message_str = text
        self.message_obj = SimpleNamespace(
            message_str=text,
            message=[],
            raw_message=raw
            or {
                "post_type": "message",
                "message_type": "group" if group else "private",
                "message_id": message_id,
                "user_id": sender,
                "time": 1000,
                "group_id": group,
            },
        )
        self.sender = str(sender)
        self.group = str(group)
        self.unified_msg_origin = (
            f"qq:{'GroupMessage' if group else 'FriendMessage'}:{group or sender}"
        )
        self._has_send_oper = False
        self.call_llm = False
        self.is_at_or_wake_command = True
        self.extras = {}
        self.stopped = False
        self.result = None
        self._temporary_local_files = []
        self.cleaned_files = []
        self.prepared = asyncio.Event()
        self.entered = asyncio.Event()
        self.allow_reply = asyncio.Event()
        self.runtime = None

    def get_platform_name(self):
        return "aiocqhttp"

    def get_platform_id(self):
        return "qq"

    def get_sender_id(self):
        return self.sender

    def get_self_id(self):
        return "99"

    def get_group_id(self):
        return self.group

    def get_messages(self):
        return self.message_obj.message

    def get_extra(self, key, default=None):
        return self.extras.get(key, default)

    def set_extra(self, key, value):
        self.extras[key] = value

    def is_stopped(self):
        return self.stopped

    def stop_event(self):
        self.stopped = True

    def get_result(self):
        return self.result

    def track_temporary_local_file(self, path):
        self._temporary_local_files.append(path)


class Conversations:
    def __init__(self):
        self.histories = {}
        self.current_id = "conversation"

    async def get_curr_conversation_id(self, umo):
        return self.current_id

    async def get_conversation(self, umo, cid):
        return SimpleNamespace(
            cid=cid,
            history=json.dumps(self.histories.get((umo, cid), [])),
            token_usage=0,
        )

    async def update_conversation(self, umo, cid, *, history, **kwargs):
        self.histories[umo, cid] = deepcopy(history)

    def history(self, event):
        return self.histories.get((event.unified_msg_origin, "conversation"), [])


class Harness:
    def __init__(self, config=None):
        self.manager = Conversations()
        self.plugin = object.__new__(QQEnhancePlugin)
        self.plugin.config = validate_config(
            {"debounce": {"enabled": True, **(config or {})}}
        )
        self.plugin.recall_messages = {}
        self.plugin.context = SimpleNamespace(
            conversation_manager=self.manager,
            get_config=lambda **kwargs: {"agent_runner": {"runner_type": "local"}},
            get_all_stars=lambda: [],
        )
        self.plugin.debouncer = MessageDebouncer(self.plugin)
        self.tasks = []
        self.requests = []

    def start(
        self,
        event,
        *,
        preprocess=None,
        parts=None,
        added_contexts=None,
        fail=False,
        streaming=False,
        tool=False,
        enrich=False,
    ):
        async def pipeline():
            ArrivalFilter().filter(event, {})
            event.entered.set()
            try:
                if preprocess:
                    await preprocess.wait()
                if enrich:
                    await self.plugin.enrich_inbound_qq_components(event)
                await self.plugin.debounce_inbound_message(event)
                async with session_lock_manager.acquire_lock(event.unified_msg_origin):
                    conversation = await self.manager.get_conversation(
                        event.unified_msg_origin, self.manager.current_id
                    )
                    req = ProviderRequest(
                        prompt=event.message_str,
                        contexts=json.loads(conversation.history),
                        conversation=conversation,
                        extra_user_content_parts=[
                            TextPart(
                                text=f"<system_reminder>User ID: {event.sender}, Nickname: Test\nCurrent datetime: 2026-09-06 01:55 (CST), Weekday: Sunday</system_reminder>"
                            )
                        ],
                    )
                    if added_contexts:
                        req.contexts.extend(deepcopy(added_contexts))
                    # Use AstrBot's real message assembly and history serialization.
                    req.extra_user_content_parts.append(
                        TextPart(
                            text='<qq_verified_components types="voice"/>'
                        ).mark_as_temp()
                    )
                    await self.plugin.track_context_message(event, req)
                    await self.plugin.bind_debounce_request(event, req)
                    current = await req.assemble_context()
                    if parts:
                        current["content"].extend(deepcopy(parts))
                    messages = bind_checkpoint_messages(req.contexts) + [
                        Message.model_validate(current)
                    ]
                    event.runtime = SimpleNamespace(messages=messages)
                    if streaming:
                        event.result = SimpleNamespace(
                            result_content_type="STREAMING_RESULT"
                        )
                    await self.plugin.snapshot_debounce_input(event, event.runtime)
                    self.requests.append(
                        deepcopy(dump_messages_with_checkpoints(messages))
                    )
                    if tool:
                        await self.plugin.protect_debounce_tool(event, None, {})
                    event.prepared.set()
                    await event.allow_reply.wait()
                    if fail:
                        raise RuntimeError("provider failed")
                    await self.plugin.protect_debounce_response(event, None)
                    messages.append(Message(role="assistant", content="reply"))
                    await self.plugin.mark_pending_recall_before_history_save(
                        event, event.runtime, None
                    )
                    await self.manager.update_conversation(
                        event.unified_msg_origin,
                        conversation.cid,
                        history=dump_messages_with_checkpoints(messages),
                    )
            finally:
                event.cleaned_files.extend(event._temporary_local_files)
                event._temporary_local_files.clear()

        task = asyncio.create_task(pipeline())
        self.tasks.append(task)
        return task

    async def finish(self):
        for task in self.tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        await self.plugin.debouncer.close()


async def wait(event):
    await asyncio.wait_for(event.wait(), 3)


def texts(history):
    return [
        item["content"][0]["text"]
        if isinstance(item["content"], list)
        else item["content"]
        for item in history
    ]


@pytest.mark.asyncio
async def test_three_inputs_remain_separate_and_unanswered_until_final_reply():
    harness = Harness()
    try:
        events = [
            Event(text, i)
            for i, text in enumerate(["去杭州", "周六出发", "我上一条发了什么？"], 101)
        ]
        for event in events:
            harness.start(event)
            await wait(event.prepared)
        assert texts(harness.manager.history(events[-1])) == ["去杭州", "周六出发"]
        assert texts(harness.requests[-1]) == [
            "去杭州",
            "周六出发",
            "我上一条发了什么？",
        ]
        assert [m["role"] for m in harness.requests[-1]] == ["user", "user", "user"]
        for message in harness.requests[-1]:
            assert (
                sum(
                    "<system_reminder>" in p.get("text", "") for p in message["content"]
                )
                == 1
            )
        events[-1].allow_reply.set()
        await harness.tasks[-1]
        assert texts(harness.manager.history(events[-1])) == [
            "去杭州",
            "周六出发",
            "我上一条发了什么？",
            "reply",
        ]
        assert all(task.cancelled() for task in harness.tasks[:-1])
        assert "qq_verified_components" not in json.dumps(
            harness.manager.history(events[-1])
        )
    finally:
        await harness.finish()


@pytest.mark.asyncio
async def test_slow_preprocessing_does_not_reverse_input_order():
    harness = Harness()
    gate = asyncio.Event()
    first, second = Event("语音转写", 1), Event("文字补充", 2)
    try:
        harness.start(first, preprocess=gate)
        await wait(first.entered)
        harness.start(second)
        await wait(second.entered)
        assert not second.prepared.is_set()
        gate.set()
        await wait(second.prepared)
        assert texts(harness.requests[-1]) == ["语音转写", "文字补充"]
    finally:
        await harness.finish()


@pytest.mark.parametrize(
    "kind",
    [
        "image",
        "record",
        "video",
        "file",
        "reply",
        "forward",
        "json",
        "xml",
        "wallet",
        "face",
        "mface",
        "dice",
        "rps",
        "share",
        "music",
        "contact",
        "location",
        "unknown_future_component",
    ],
)
@pytest.mark.asyncio
async def test_component_type_does_not_exclude_prepared_input(kind):
    harness = Harness()
    first, second = Event(f"prepared {kind}", 1), Event("再看看这个", 2)
    first.message_obj.raw_message["message"] = [{"type": kind, "data": {}}]
    first.message_obj.message = [SimpleNamespace(type=kind)]
    parts = [
        {"type": "text", "text": f"prepared {kind}"},
        {
            "type": "image_url",
            "image_url": {"url": "data:image/png;base64,cGljdHVyZQ=="},
        },
        {"type": "audio_url", "audio_url": {"url": "data:audio/wav;base64,YXVkaW8="}},
    ]
    try:
        harness.start(first, parts=parts)
        await wait(first.prepared)
        harness.start(second)
        await wait(second.prepared)
        retained = harness.requests[-1][0]["content"]
        assert {"type": "text", "text": f"prepared {kind}"} in retained
        assert (
            next(
                part["image_url"]["url"]
                for part in retained
                if part["type"] == "image_url"
            )
            == parts[1]["image_url"]["url"]
        )
        assert (
            next(
                part["audio_url"]["url"]
                for part in retained
                if part["type"] == "audio_url"
            )
            == parts[2]["audio_url"]["url"]
        )
        assert harness.requests[-1][1]["role"] == "user"
    finally:
        await harness.finish()


@pytest.mark.asyncio
async def test_targeted_poke_can_follow_message_without_a_message_id():
    harness = Harness()
    first = Event("你好", 1)
    poke = Event(
        "[QQ component|QQ互动：7 戳了你]",
        None,
        raw={
            "post_type": "notice",
            "notice_type": "notify",
            "sub_type": "poke",
            "user_id": 7,
            "target_id": 99,
        },
    )
    try:
        harness.start(first)
        await wait(first.prepared)
        harness.start(poke)
        await wait(poke.prepared)
        assert texts(harness.requests[-1]) == [first.message_str, poke.message_str]
        assert poke.get_extra("_qq_enhance_recall_key") is None
    finally:
        await harness.finish()


@pytest.mark.parametrize("boundary", ["tool", "streaming", "limit", "chars", "sent"])
@pytest.mark.asyncio
async def test_effects_and_limits_preserve_old_reply_and_serialize_next(boundary):
    harness = Harness({"max_chars": 1} if boundary == "chars" else None)
    first, second = Event("first", 1), Event("second", 2)
    try:
        harness.start(first, tool=boundary == "tool", streaming=boundary == "streaming")
        await wait(first.prepared)
        if boundary == "limit":
            arrival = first.get_extra(ARRIVAL_KEY)
            arrival.batch = [arrival] * 8
        if boundary == "sent":
            first._has_send_oper = True
        harness.start(second)
        await wait(second.entered)
        first.allow_reply.set()
        await wait(second.prepared)
        assert not harness.tasks[0].cancelled()
        assert texts(harness.requests[-1]) == ["first", "reply", "second"]
    finally:
        await harness.finish()


@pytest.mark.asyncio
async def test_cancelled_input_survives_latest_provider_failure_and_keeps_file_extraction():
    harness = Harness()
    first, second = Event("总结文件", 1), Event("请继续", 2)
    extraction = {"role": "user", "content": "File Extract Results: complete contents"}
    try:
        harness.start(first, added_contexts=[extraction])
        await wait(first.prepared)
        harness.start(second, fail=True)
        await wait(second.prepared)
        second.allow_reply.set()
        with pytest.raises(RuntimeError, match="provider failed"):
            await harness.tasks[-1]
        assert texts(harness.manager.history(first)) == [
            extraction["content"],
            first.message_str,
        ]
    finally:
        await harness.finish()


@pytest.mark.asyncio
async def test_media_cleanup_ownership_moves_to_successor():
    harness = Harness()
    first, second = Event("图片", 1), Event("解释", 2)
    first.track_temporary_local_file("prepared-image.png")
    try:
        harness.start(first)
        await wait(first.prepared)
        harness.start(second)
        await wait(second.prepared)
        assert first.cleaned_files == []
        assert second._temporary_local_files == ["prepared-image.png"]
        second.allow_reply.set()
        await harness.tasks[-1]
        assert second.cleaned_files == ["prepared-image.png"]
    finally:
        await harness.finish()


@pytest.mark.parametrize("target", [1, 2])
@pytest.mark.asyncio
async def test_recall_marks_only_one_identical_input_and_survives_history_save(target):
    harness = Harness()
    first, second = Event("同样的文字", 1), Event("同样的文字", 2)
    try:
        harness.start(first)
        await wait(first.prepared)
        harness.start(second)
        await wait(second.prepared)
        notice = Event(
            "",
            None,
            raw={
                "post_type": "notice",
                "notice_type": "friend_recall",
                "user_id": 7,
                "message_id": target,
                "time": 1005,
            },
        )
        await harness.plugin.mark_recalled_message(notice)
        second.allow_reply.set()
        await harness.tasks[-1]
        history = harness.manager.history(second)
        assert "撤回" in json.dumps(history[target - 1], ensure_ascii=False)
        assert "撤回" not in json.dumps(history[2 - target], ensure_ascii=False)
        assert json.dumps(history, ensure_ascii=False).count("被撤回") == 1
    finally:
        await harness.finish()


@pytest.mark.asyncio
async def test_early_recall_is_retained_when_generation_is_superseded():
    harness = Harness()
    first, second = Event("将撤回", 1), Event("新的输入", 2)
    try:
        harness.start(first)
        await wait(first.prepared)
        notice = Event(
            "",
            None,
            raw={
                "post_type": "notice",
                "notice_type": "friend_recall",
                "user_id": 7,
                "message_id": 1,
                "time": 1005,
            },
        )
        await harness.plugin.mark_recalled_message(notice)
        harness.start(second)
        await wait(second.prepared)
        assert "被撤回" in json.dumps(harness.requests[-1][0], ensure_ascii=False)
    finally:
        await harness.finish()


@pytest.mark.asyncio
async def test_different_senders_are_never_cancelled_together():
    harness = Harness()
    first, second = (
        Event("sender 7", 1, group="10"),
        Event("sender 8", 2, sender=8, group="10"),
    )
    try:
        harness.start(first)
        await wait(first.prepared)
        harness.start(second)
        await wait(second.entered)
        first.allow_reply.set()
        await wait(second.prepared)
        assert not harness.tasks[0].cancelled()
        assert texts(harness.requests[-1]) == ["sender 7", "reply", "sender 8"]
    finally:
        await harness.finish()


@pytest.mark.asyncio
async def test_conversation_switch_does_not_move_old_input():
    harness = Harness()
    first, second = Event("old conversation", 1), Event("new conversation", 2)
    try:
        harness.start(first)
        await wait(first.prepared)
        harness.manager.current_id = "new"
        harness.start(second)
        await wait(second.entered)
        first.allow_reply.set()
        await wait(second.prepared)
        assert texts(harness.requests[-1]) == ["new conversation"]
        assert texts(harness.manager.history(first)) == ["old conversation", "reply"]
    finally:
        await harness.finish()


@pytest.mark.parametrize(
    "config",
    [
        {"enabled": 1},
        {"max_messages": 1},
        {"max_messages": True},
        {"max_chars": 0},
        {"max_buffer_mb": 257},
        {"ignore_prefixes": "/"},
    ],
)
def test_invalid_debounce_config_is_rejected(config):
    with pytest.raises(ValueError):
        validate_config({"debounce": config})


def test_debounce_schema_matches_defaults():
    schema = json.loads(
        (Path(__file__).resolve().parents[1] / "_conf_schema.json").read_text(
            encoding="utf-8"
        )
    )
    assert {
        key: field["default"] for key, field in schema["debounce"]["items"].items()
    } == validate_config(None)["debounce"]


@pytest.mark.parametrize(
    "raw",
    [
        {"post_type": "notice", "notice_type": "friend_recall", "message_id": 1},
        {"post_type": "request", "request_type": "friend", "flag": "request"},
        {
            "post_type": "notice",
            "notice_type": "notify",
            "sub_type": "poke",
            "target_id": 42,
        },
    ],
)
@pytest.mark.asyncio
async def test_passive_notices_and_requests_do_not_enter_arrival_queue(raw):
    event = Event("", None, raw=raw)
    assert not ArrivalFilter().filter(event, {})
    assert event.get_extra(ARRIVAL_KEY) is None


@pytest.mark.parametrize(
    "excluded", ["disabled", "untriggered", "command", "other_plugin", "conflict"]
)
@pytest.mark.asyncio
async def test_ineligible_inputs_keep_their_original_flow(excluded):
    harness = Harness({"enabled": False} if excluded == "disabled" else None)
    event = Event("/command" if excluded == "command" else "hello", 1)
    if excluded == "untriggered":
        event.is_at_or_wake_command = False
    if excluded == "other_plugin":
        event.call_llm = True
    if excluded == "conflict":
        harness.plugin.context.get_all_stars = lambda: [
            SimpleNamespace(
                name="astrbot_plugin_message_merger",
                activated=True,
                config={"enabled": True},
            )
        ]
    try:
        harness.start(event)
        await wait(event.prepared)
        assert event.get_extra(ARRIVAL_KEY).batch == []
    finally:
        await harness.finish()


@pytest.mark.asyncio
async def test_recall_during_persistence_is_not_lost():
    harness = Harness()
    first, second = Event("early recall", 1), Event("next", 2)
    saving, release = asyncio.Event(), asyncio.Event()
    original_update = harness.manager.update_conversation

    async def update(umo, cid, **kwargs):
        if not saving.is_set():
            saving.set()
            await release.wait()
        await original_update(umo, cid, **kwargs)

    harness.manager.update_conversation = update
    try:
        harness.start(first)
        await wait(first.prepared)
        harness.start(second)
        await wait(saving)
        notice = Event(
            "",
            None,
            raw={
                "post_type": "notice",
                "notice_type": "friend_recall",
                "user_id": 7,
                "message_id": 1,
                "time": 1005,
            },
        )
        await harness.plugin.mark_recalled_message(notice)
        release.set()
        await wait(second.prepared)
        assert "被撤回" in json.dumps(harness.requests[-1][0], ensure_ascii=False)
    finally:
        release.set()
        await harness.finish()


@pytest.mark.asyncio
async def test_real_agent_cancellation_and_native_follow_up_boundary():
    from astrbot.core.agent.hooks import BaseAgentRunHooks
    from astrbot.core.agent.run_context import ContextWrapper
    from astrbot.core.agent.runners.tool_loop_agent_runner import ToolLoopAgentRunner
    from astrbot.core.pipeline.process_stage.follow_up import (
        register_active_runner,
        unregister_active_runner,
        try_capture_follow_up,
    )
    from astrbot.core.provider.entities import LLMResponse

    harness = Harness()
    calls, cancelled = [], []

    class Hooks(BaseAgentRunHooks):
        async def on_agent_begin(self, context):
            await harness.plugin.snapshot_debounce_input(context.context.event, context)

        async def on_agent_done(self, context, response):
            await harness.plugin.protect_debounce_response(
                context.context.event, response
            )
            await harness.plugin.mark_pending_recall_before_history_save(
                context.context.event, context, response
            )

    async def pipeline(event):
        ArrivalFilter().filter(event, {})
        await harness.plugin.debounce_inbound_message(event)
        assert try_capture_follow_up(event) is None
        async with session_lock_manager.acquire_lock(event.unified_msg_origin):
            conversation = await harness.manager.get_conversation(
                event.unified_msg_origin, "conversation"
            )
            req = ProviderRequest(
                prompt=event.message_str,
                contexts=json.loads(conversation.history),
                conversation=conversation,
            )
            await harness.plugin.track_context_message(event, req)
            await harness.plugin.bind_debounce_request(event, req)

            async def text_chat(**kwargs):
                calls.append(
                    deepcopy(dump_messages_with_checkpoints(kwargs["contexts"]))
                )
                event.prepared.set()
                try:
                    await event.allow_reply.wait()
                except asyncio.CancelledError:
                    cancelled.append(event.message_str)
                    raise
                return LLMResponse(role="assistant", completion_text="reply")

            runner = ToolLoopAgentRunner()
            await runner.reset(
                provider=SimpleNamespace(provider_config={}, text_chat=text_chat),
                request=req,
                run_context=ContextWrapper(context=SimpleNamespace(event=event)),
                tool_executor=None,
                agent_hooks=Hooks(),
                streaming=False,
            )
            register_active_runner(event.unified_msg_origin, runner)
            try:
                async for _ in runner.step_until_done(2):
                    pass
                await harness.manager.update_conversation(
                    event.unified_msg_origin,
                    "conversation",
                    history=dump_messages_with_checkpoints(runner.run_context.messages),
                )
            finally:
                unregister_active_runner(event.unified_msg_origin, runner)

    first, second = Event("first input", 1), Event("latest input", 2)
    try:
        harness.tasks.append(asyncio.create_task(pipeline(first)))
        await wait(first.prepared)
        harness.tasks.append(asyncio.create_task(pipeline(second)))
        await wait(second.prepared)
        assert cancelled == ["first input"]
        assert texts(calls[-1]) == ["first input", "latest input"]
        second.allow_reply.set()
        await harness.tasks[-1]
        assert texts(harness.manager.history(second)) == [
            "first input",
            "latest input",
            "reply",
        ]
    finally:
        await harness.finish()


@pytest.mark.asyncio
async def test_recall_before_preprocessing_finishes_is_applied_to_original_input():
    harness = Harness()
    gate = asyncio.Event()
    first, second = Event("slow voice", 1), Event("next", 2)
    try:
        harness.start(first, preprocess=gate)
        await wait(first.entered)
        notice = Event(
            "",
            None,
            raw={
                "post_type": "notice",
                "notice_type": "friend_recall",
                "user_id": 7,
                "message_id": 1,
                "time": 1005,
            },
        )
        await harness.plugin.mark_recalled_message(notice)
        assert harness.plugin.debouncer.early_recalls
        harness.start(second)
        gate.set()
        await wait(second.prepared)
        assert "被撤回" in json.dumps(harness.requests[-1][0], ensure_ascii=False)
        assert not harness.plugin.debouncer.early_recalls
    finally:
        gate.set()
        await harness.finish()


@pytest.mark.parametrize("kind", ["card", "red_packet", "poke"])
@pytest.mark.asyncio
async def test_real_qq_enrichment_feeds_special_inputs_into_debounce(kind):
    harness = Harness()
    first, second = Event("", 1), Event("补充", 2)
    raw = first.message_obj.raw_message
    raw["message"] = []
    if kind == "card":
        raw["message"] = [
            {
                "type": "json",
                "data": {
                    "data": {
                        "app": "example",
                        "meta": {"detail": {"title": "卡片标题"}},
                    }
                },
            }
        ]
    elif kind == "red_packet":
        raw["raw"] = {
            "msgType": 10,
            "elements": [{"elementType": 9, "walletElement": {}}],
        }
        first.is_at_or_wake_command = False
    else:
        raw.update(
            {
                "post_type": "notice",
                "notice_type": "notify",
                "sub_type": "poke",
                "target_id": 99,
            }
        )
        first.is_at_or_wake_command = False
    try:
        harness.start(first, enrich=True)
        await wait(first.prepared)
        harness.start(second)
        await wait(second.prepared)
        content = texts(harness.requests[-1])[0]
        assert {"card": "QQ JSON卡片", "red_packet": "QQ红包消息", "poke": "戳了你"}[
            kind
        ] in content
        assert harness.tasks[0].cancelled()
    finally:
        await harness.finish()


@pytest.mark.asyncio
async def test_persistence_survives_successor_cancellation():
    harness = Harness()
    first, second, third = (
        Event("first", 1),
        Event("cancelled successor", 2),
        Event("third", 3),
    )
    saving, release = asyncio.Event(), asyncio.Event()
    original_update = harness.manager.update_conversation

    async def update(umo, cid, **kwargs):
        if not saving.is_set():
            saving.set()
            await release.wait()
        await original_update(umo, cid, **kwargs)

    harness.manager.update_conversation = update
    try:
        harness.start(first)
        await wait(first.prepared)
        second_task = harness.start(second)
        await wait(saving)
        second_task.cancel()
        await asyncio.gather(second_task, return_exceptions=True)
        harness.start(third)
        await wait(third.entered)
        assert not third.prepared.is_set()
        release.set()
        await wait(third.prepared)
        assert texts(harness.requests[-1]) == ["first", "third"]
    finally:
        release.set()
        await harness.finish()


@pytest.mark.asyncio
async def test_failed_persistence_is_retried_before_next_generation():
    harness = Harness()
    first, second, third = (
        Event("first", 1),
        Event("failed successor", 2),
        Event("third", 3),
    )
    original_update = harness.manager.update_conversation
    failures = []

    async def update(umo, cid, **kwargs):
        if not failures:
            failures.append(True)
            raise RuntimeError("database unavailable")
        await original_update(umo, cid, **kwargs)

    harness.manager.update_conversation = update
    try:
        harness.start(first)
        await wait(first.prepared)
        second_task = harness.start(second)
        with pytest.raises(RuntimeError, match="database unavailable"):
            await second_task
        assert harness.plugin.debouncer.failed
        harness.start(third)
        await wait(third.prepared)
        assert texts(harness.requests[-1]) == ["first", "third"]
        assert not harness.plugin.debouncer.failed
    finally:
        await harness.finish()


@pytest.mark.asyncio
async def test_other_sender_between_inputs_keeps_shared_history_order():
    harness = Harness()
    first = Event("A first", 1, group="10")
    other = Event("B intervenes", 2, sender=8, group="10")
    last = Event("A second", 3, group="10")
    try:
        harness.start(first)
        await wait(first.prepared)
        harness.start(other)
        await wait(other.entered)
        harness.start(last)
        await wait(last.entered)
        first.allow_reply.set()
        await wait(other.prepared)
        other.allow_reply.set()
        await wait(last.prepared)
        assert texts(harness.requests[-1]) == [
            "A first",
            "reply",
            "B intervenes",
            "reply",
            "A second",
        ]
        assert not harness.tasks[0].cancelled()
    finally:
        await harness.finish()


@pytest.mark.asyncio
async def test_pure_image_without_prompt_is_retained_and_recallable():
    from astrbot.api.message_components import Image

    harness = Harness()
    first, second = Event("", 1), Event("看这张图", 2)
    first.message_obj.message = [Image(file="test.png")]
    image = {
        "type": "image_url",
        "image_url": {"url": "data:image/png;base64,cGljdHVyZQ=="},
    }
    try:
        harness.start(first, parts=[image])
        await wait(first.prepared)
        harness.start(second)
        await wait(second.prepared)
        notice = Event(
            "",
            None,
            raw={
                "post_type": "notice",
                "notice_type": "friend_recall",
                "user_id": 7,
                "message_id": 1,
                "time": 1005,
            },
        )
        await harness.plugin.mark_recalled_message(notice)
        second.allow_reply.set()
        await harness.tasks[-1]
        history = harness.manager.history(second)
        assert "被撤回" in json.dumps(history[0], ensure_ascii=False)
        assert any(
            part.get("image_url", {}).get("url") == image["image_url"]["url"]
            for part in history[0]["content"]
        )
    finally:
        await harness.finish()


@pytest.mark.parametrize("reason", ["empty", "prefix", "session_disabled"])
@pytest.mark.asyncio
async def test_non_llm_follow_up_does_not_cancel_active_generation(reason):
    harness = Harness()
    first, second = Event("first", 1), Event("" if reason == "empty" else "second", 2)
    try:
        harness.start(first)
        await wait(first.prepared)
        if reason == "prefix":
            harness.plugin.context.get_config = lambda **kwargs: {
                "provider_settings": {"wake_prefix": "."}
            }
        if reason == "session_disabled":
            SessionServiceManager.should_process_llm_request.return_value = False
        second_task = harness.start(second)
        await wait(second.entered)
        first.allow_reply.set()
        await wait(second.prepared)
        assert not harness.tasks[0].cancelled()
        assert "reply" in texts(harness.requests[-1])
        second.allow_reply.set()
        await second_task
    finally:
        await harness.finish()


@pytest.mark.asyncio
async def test_initial_window_delays_first_request_only_when_configured():
    harness = Harness({"initial_window_seconds": 0.03})
    event = Event("delayed first", 1)
    started = asyncio.get_running_loop().time()
    try:
        harness.start(event)
        await wait(event.prepared)
        assert asyncio.get_running_loop().time() - started >= 0.02
    finally:
        await harness.finish()


@pytest.mark.asyncio
async def test_followup_window_delays_cancellation_and_is_capped_by_cumulative_max():
    harness = Harness(
        {
            "initial_window_seconds": 0.03,
            "followup_window_seconds": 0.03,
            "max_wait_seconds": 0.04,
        }
    )
    first, second = Event("first", 1), Event("second", 2)
    try:
        harness.start(first)
        await wait(first.prepared)
        started = asyncio.get_running_loop().time()
        harness.start(second)
        await wait(second.prepared)
        elapsed = asyncio.get_running_loop().time() - started
        assert elapsed >= 0.005
        assert elapsed < 0.08
    finally:
        await harness.finish()


def test_debounce_window_defaults_are_zero_and_max_wait_is_five_seconds():
    config = validate_config(None)["debounce"]
    assert config["initial_window_seconds"] == 0.0
    assert config["followup_window_seconds"] == 0.0
    assert config["max_wait_seconds"] == 5.0
