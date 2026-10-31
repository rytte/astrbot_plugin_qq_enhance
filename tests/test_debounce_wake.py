from __future__ import annotations

import asyncio
from copy import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from astrbot.api.message_components import At, AtAll, Plain, Reply
from astrbot.core.pipeline.waking_check.stage import WakingCheckStage
from astrbot.core.star.session_llm_manager import SessionServiceManager
from astrbot.core.star.session_plugin_manager import SessionPluginManager
from astrbot_plugin_qq_enhance.debounce import ARRIVAL_KEY
from astrbot_plugin_qq_enhance.qq_debounce import ArrivalFilter, DebounceWakeHook
from test_debounce import (
    Event,
    Harness,
    enabled_session as enabled_session,
    texts,
    wait,
)
from test_debounce_runtime import source_message


@pytest.fixture
def harness():
    return Harness({"initial_window_seconds": 0.1, "followup_window_seconds": 0.05})


def followup(text="补充内容", message_id=2, *, sender=7, group="10"):
    event = Event(text, message_id, sender=sender, group=group)
    event.is_at_or_wake_command = False
    event.is_wake = False
    return event


@pytest.mark.parametrize("another_wrapper", [False, True])
@pytest.mark.asyncio
async def test_early_wake_hook_unload_restores_only_its_own_wrapper(
    monkeypatch, another_wrapper
):
    original = AsyncMock()
    monkeypatch.setattr(WakingCheckStage, "process", original)
    plugin = SimpleNamespace(inherit_debounce_wake=AsyncMock())
    hook = DebounceWakeHook(plugin)
    hook.install()
    wrapped = WakingCheckStage.process
    try:
        hook.install()
        assert WakingCheckStage.process is wrapped
        if another_wrapper:

            async def outer(stage, event):
                return await wrapped(stage, event)

            WakingCheckStage.process = outer
        hook.close()
        hook.close()
        assert WakingCheckStage.process is (outer if another_wrapper else original)
        # An enclosing plugin may retain the wrapper after unload; it must
        # then forward native checks without invoking the unloaded plugin.
        event = followup()
        event.set_extra(
            ARRIVAL_KEY, SimpleNamespace(wake_source=object(), wake_pending=None)
        )
        event.set_extra(
            "activated_handlers",
            [SimpleNamespace(handler=plugin.inherit_debounce_wake)],
        )
        stage = SimpleNamespace()
        await WakingCheckStage.process(stage, event)
        original.assert_awaited_once_with(stage, event)
        plugin.inherit_debounce_wake.assert_not_awaited()
        hook.install()
        await WakingCheckStage.process(stage, event)
        plugin.inherit_debounce_wake.assert_awaited_once_with(event)
    finally:
        hook.close()


async def accept(harness, event):
    async def pipeline():
        assert ArrivalFilter().filter(event, {})
        await harness.plugin.inherit_debounce_wake(event)

    await asyncio.create_task(pipeline())


@pytest.mark.asyncio
async def test_followup_enters_model_and_keeps_its_own_message_and_identity(harness):
    first = Event("先提出问题", 1, group="10")
    second = followup()
    try:
        harness.start(first)
        await wait(first.entered)
        first_task = harness.tasks[0]
        harness.start(second)
        await wait(second.prepared)
        assert second.is_at_or_wake_command
        assert second.is_wake
        assert first_task.cancelled()
        assert texts(harness.requests[-1]) == ["先提出问题", "补充内容"]
        assert all(
            "User ID: 7" in str(message["content"]) for message in harness.requests[-1]
        )
        second.allow_reply.set()
        await harness.tasks[-1]
        assert texts(harness.manager.history(second)) == [
            "先提出问题",
            "补充内容",
            "reply",
        ]
    finally:
        await harness.finish()


@pytest.mark.asyncio
async def test_followup_before_wake_source_finishes_preparation(harness):
    first, second = Event("先唤醒", 1, group="10"), followup()
    gate = asyncio.Event()
    try:
        first_task = harness.start(first, preprocess=gate)
        await wait(first.entered)
        second_task = harness.start(second)
        await wait(second.entered)
        assert second.get_extra(ARRIVAL_KEY).wake_pending is first.get_extra(
            ARRIVAL_KEY
        )
        gate.set()
        await wait(second.prepared)
        assert second.is_at_or_wake_command
        assert first_task.cancelled()
        assert texts(harness.requests[-1]) == ["先唤醒", "补充内容"]
        second.allow_reply.set()
        await second_task
    finally:
        gate.set()
        await harness.finish()


@pytest.mark.asyncio
async def test_cancelled_source_releases_followup_waiting_for_window(harness):
    first, second = Event("先唤醒", 1, group="10"), followup()
    gate = asyncio.Event()
    try:
        task = harness.start(first, preprocess=gate)
        await wait(first.entered)
        followup_task = asyncio.create_task(accept(harness, second))
        await asyncio.sleep(0)
        task.cancel()
        await followup_task
        assert not second.is_at_or_wake_command
        assert second.get_extra(ARRIVAL_KEY).wake_pending is None
        assert not first.get_extra(ARRIVAL_KEY).wake_followups
    finally:
        await harness.finish()


@pytest.mark.asyncio
async def test_only_members_who_woke_the_bot_join_the_shared_window(harness):
    first = Event("A 的问题", 1, group="10")
    other = followup(sender=8)
    second = Event("B 也提问", 3, sender=8, group="10")
    try:
        harness.start(first)
        await wait(first.entered)
        await accept(harness, other)
        assert not other.is_at_or_wake_command
        harness.start(second)
        await wait(second.entered)
        for sender in (7, 8):
            current = followup(message_id=sender + 10, sender=sender)
            await accept(harness, current)
            assert current.is_at_or_wake_command
            assert current.get_sender_id() == str(sender)
        stranger = followup(sender=9)
        await accept(harness, stranger)
        assert not stranger.is_at_or_wake_command
    finally:
        await harness.finish()


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["inherit_off", "debounce_off", "closed"])
async def test_switches_stop_new_inheritance(harness, reason):
    first = Event("问题", 1, group="10")
    try:
        harness.start(first)
        await wait(first.entered)
        if reason == "closed":
            await harness.plugin.debouncer.close()
        else:
            key = "inherit_group_wake" if reason == "inherit_off" else "enabled"
            harness.runtime.config[key] = False
        second = followup()
        await accept(harness, second)
        assert not second.is_at_or_wake_command
        assert second.get_extra(ARRIVAL_KEY).wake_source is None
    finally:
        await harness.finish()


@pytest.mark.asyncio
async def test_switch_off_retains_explicitly_woken_debounce():
    harness = Harness({"inherit_group_wake": False, "initial_window_seconds": 0.05})
    first, second = Event("问题", 1, group="10"), Event("补充", 2, group="10")
    try:
        harness.start(first)
        await wait(first.entered)
        harness.start(second)
        await wait(second.prepared)
        assert texts(harness.requests[-1]) == ["问题", "补充"]
    finally:
        await harness.finish()


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["generating", "deadline", "finished"])
async def test_expired_window_cannot_grant_wake(harness, reason):
    first = Event("问题", 1, group="10")
    try:
        harness.start(first)
        await wait(first.entered)
        if reason == "deadline":
            # Test the boundary even if the timer callback has not run yet.
            first.get_extra(ARRIVAL_KEY).wait_deadline = (
                asyncio.get_running_loop().time() - 1
            )
        else:
            await wait(first.prepared)
            if reason == "finished":
                first.allow_reply.set()
                await harness.tasks[0]
        second = followup()
        await accept(harness, second)
        assert not second.is_at_or_wake_command
    finally:
        await harness.finish()


@pytest.mark.asyncio
async def test_slow_preparation_uses_arrival_time_even_after_switch_is_turned_off(
    harness,
):
    first, second = Event("问题", 1, group="10"), followup("语音转写")
    gate = asyncio.Event()
    try:
        harness.start(first)
        await wait(first.entered)
        harness.start(second, preprocess=gate)
        await wait(second.entered)
        assert second.get_extra(ARRIVAL_KEY).wake_source is not None
        assert not second.is_at_or_wake_command
        harness.runtime.config["inherit_group_wake"] = False
        await wait(first.prepared)
        gate.set()
        await wait(second.prepared)
        assert second.is_at_or_wake_command
        assert texts(harness.requests[-1]) == ["问题", "语音转写"]
        third = followup(message_id=3)
        await accept(harness, third)
        assert not third.is_at_or_wake_command
    finally:
        gate.set()
        await harness.finish()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reason",
    [
        "slash_command",
        "bang_command",
        "other_at",
        "at_all",
        "other_reply",
        "empty",
        "handled",
        "stopped",
        "provider_prefix",
        "llm_disabled",
        "plugin_disabled",
        "plugin_set",
        "conversation_changed",
    ],
)
async def test_inheritance_retains_message_and_session_exclusions(harness, reason):
    first = Event("问题", 1, group="10")
    second = followup()
    try:
        harness.start(first)
        await wait(first.entered)
        if reason.endswith("command"):
            second.message_str = "/help" if reason == "slash_command" else "!help"
            second.message_obj.message_str = second.message_str
        elif reason == "other_at":
            second.message_obj.message = [At(qq="8")]
        elif reason == "at_all":
            second.message_obj.message = [AtAll()]
        elif reason == "other_reply":
            second.message_obj.message = [Reply(id="123", sender_id="8")]
        elif reason == "empty":
            second.message_str = ""
        elif reason == "handled":
            second.call_llm = True
        elif reason == "stopped":
            second.stop_event()
        elif reason == "provider_prefix":
            harness.plugin.context.get_config = lambda **kwargs: {
                "provider_settings": {"wake_prefix": "."}
            }
        elif reason == "llm_disabled":
            SessionServiceManager.should_process_llm_request.return_value = False
        elif reason == "plugin_disabled":
            SessionPluginManager.is_plugin_enabled_for_session.return_value = False
        elif reason == "plugin_set":
            harness.plugin.context.get_config = lambda **kwargs: {
                "plugin_set": ["other"]
            }
        elif reason == "conversation_changed":
            harness.manager.current_id = "new"
        await accept(harness, second)
        assert not second.is_at_or_wake_command
    finally:
        await harness.finish()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scope", ["other_group", "other_platform", "private", "isolated"]
)
async def test_wake_is_not_shared_across_session_boundaries(harness, scope):
    first = Event("问题", 1, group="10")
    second = followup()
    if scope == "isolated":
        harness.runtime.config["shared_group"] = False
        second.sender = "8"
    elif scope == "other_group":
        second = followup(group="20")
    elif scope == "other_platform":
        second.unified_msg_origin = "other:GroupMessage:10"
    else:
        first, second = Event("私聊问题", 1), followup(group="")
    try:
        harness.start(first)
        await wait(first.entered)
        await accept(harness, second)
        assert not second.is_at_or_wake_command
    finally:
        await harness.finish()


@pytest.mark.asyncio
async def test_isolated_group_keeps_same_member_continuation():
    harness = Harness({"shared_group": False, "initial_window_seconds": 0.1})
    first, second = Event("问题", 1, group="10"), followup()
    try:
        harness.start(first)
        await wait(first.entered)
        await accept(harness, second)
        assert second.is_at_or_wake_command
    finally:
        await harness.finish()


@pytest.mark.asyncio
async def test_inherited_members_survive_successive_wait_windows(harness):
    first = Event("A 的问题", 1, group="10")
    second = Event("B 的问题", 2, sender=8, group="10")
    third = followup("A 再补充", 3)
    try:
        harness.start(first)
        await wait(first.entered)
        harness.start(second)
        await wait(second.entered)
        harness.start(third)
        await wait(third.entered)
        assert third.get_extra(ARRIVAL_KEY).wake_source is not None
        await wait(first.prepared)
        # B's follow-up window is now active; A and B both retain eligibility.
        for sender in (7, 8):
            current = followup(message_id=sender + 10, sender=sender)
            await accept(harness, current)
            assert current.is_at_or_wake_command
        await wait(third.prepared)
        assert texts(harness.requests[-1]) == ["A 的问题", "B 的问题", "A 再补充"]
    finally:
        await harness.finish()


@pytest.mark.asyncio
async def test_a_new_explicit_wake_does_not_revive_expired_members(harness):
    first = Event("A 的问题", 1, group="10")
    second = Event("B 的新问题", 2, sender=8, group="10")
    try:
        harness.start(first)
        await wait(first.prepared)
        harness.start(second)
        await wait(second.entered)
        current = followup()
        await accept(harness, current)
        assert not current.is_at_or_wake_command
        current = followup(sender=8)
        await accept(harness, current)
        assert current.is_at_or_wake_command
    finally:
        await harness.finish()


@pytest.mark.asyncio
async def test_context_only_wait_does_not_revive_expired_wake(harness):
    first = Event("问题", 1, group="10")
    try:
        harness.start(first)
        await wait(first.prepared)
        arrival = first.get_extra(ARRIVAL_KEY)
        assert not arrival.wake_senders
        context_wait = asyncio.create_task(
            harness.plugin.debouncer._wait(arrival, 0.05)
        )
        harness.tasks.append(context_wait)
        await asyncio.sleep(0)
        current = followup()
        await accept(harness, current)
        assert not current.is_at_or_wake_command
    finally:
        await harness.finish()


@pytest.mark.asyncio
async def test_cumulative_wait_limit_ends_inheritance():
    harness = Harness(
        {
            "initial_window_seconds": 0.05,
            "followup_window_seconds": 0.05,
            "max_wait_seconds": 0.05,
        }
    )
    first, second = Event("问题", 1, group="10"), followup()
    try:
        harness.start(first)
        await wait(first.entered)
        harness.start(second)
        await wait(second.prepared)
        assert second.is_at_or_wake_command
        arrival = second.get_extra(ARRIVAL_KEY)
        assert arrival.waited_seconds == pytest.approx(0.05)
        current = followup(message_id=3)
        await accept(harness, current)
        assert not current.is_at_or_wake_command
    finally:
        await harness.finish()


@pytest.mark.asyncio
async def test_platform_response_does_not_grant_member_wake(harness):
    first = Event("平台事件", 1, group="10", raw={"post_type": "notice"})
    first.notice_response = True
    try:
        harness.start(first)
        await wait(first.entered)
        current = followup()
        await accept(harness, current)
        assert not current.is_at_or_wake_command
    finally:
        await harness.finish()


@pytest.mark.asyncio
async def test_native_waking_and_pure_at_open_a_window_without_an_empty_model_call(
    harness, monkeypatch
):
    from astrbot.core.pipeline.process_stage.method.agent_sub_stages.internal import (
        InternalAgentSubStage,
    )
    from astrbot.core.pipeline.waking_check import stage as waking
    from astrbot.core.star.star import StarMetadata
    from astrbot.core.star.star_handler import (
        EventType,
        StarHandlerRegistry,
        star_handlers_registry,
    )

    registry = StarHandlerRegistry()
    for name in ("inherit_debounce_wake", "debounce_inbound_message"):
        metadata = copy(
            next(
                item
                for item in star_handlers_registry._handlers
                if item.handler_module_path == type(harness.plugin).__module__
                and item.handler_name == name
            )
        )
        metadata.handler = getattr(harness.plugin, name)
        registry.append(metadata)
    monkeypatch.setattr(waking, "star_handlers_registry", registry)
    monkeypatch.setitem(
        waking.star_map,
        type(harness.plugin).__module__,
        StarMetadata(name="astrbot_plugin_qq_enhance"),
    )
    monkeypatch.setattr(
        SessionPluginManager,
        "filter_handlers_by_session",
        AsyncMock(side_effect=lambda event, handlers: handlers),
    )
    stage = waking.WakingCheckStage()
    await stage.initialize(
        SimpleNamespace(
            astrbot_config={
                "admins_id": [],
                "wake_prefix": ["/"],
                "platform_settings": {},
                "plugin_set": ["*"],
            }
        )
    )
    first = source_message("10")
    first.message_str = first.message_obj.message_str = ""
    first.message_obj.message = [At(qq="99")]
    first.is_at_or_wake_command = False
    second = source_message("10")
    second.message_str = second.message_obj.message_str = "随后发送的正文"
    second.message_obj.message = [Plain(second.message_str)]
    second.message_obj.message_id = "124"
    second.is_at_or_wake_command = False
    second.role = "member"
    waiting = asyncio.Event()
    original_wait = harness.plugin.debouncer._wait

    async def observe_wait(arrival, *args):
        waiting.set()
        await original_wait(arrival, *args)

    monkeypatch.setattr(harness.plugin.debouncer, "_wait", observe_wait)

    async def initial_pipeline():
        await stage.process(first)
        for metadata in first.get_extra("activated_handlers"):
            await metadata.handler(first)
        # Exercise AstrBot's real empty-input gate; no initialized runner is needed.
        agent = InternalAgentSubStage()
        agent.streaming_response = False
        async for _ in agent.process(first, ""):
            pytest.fail("A pure mention must not produce a model response")

    task = asyncio.create_task(initial_pipeline())
    harness.tasks.append(task)
    hook = DebounceWakeHook(harness.plugin)
    hook.install()
    try:
        await wait(waiting)
        assert first.is_at_or_wake_command
        await stage.process(second)
        assert not second.is_stopped()
        assert second.is_at_or_wake_command
        assert second.get_extra(ARRIVAL_KEY).wake_source is not None
        activated = second.get_extra("activated_handlers")
        assert activated[0].handler_name == "inherit_debounce_wake"
        assert all(
            item.event_type == EventType.AdapterMessageEvent for item in activated
        )
        await activated[0].handler(second)
        assert second.is_at_or_wake_command
        assert not second.is_admin()
        assert first.is_admin()
        await activated[1].handler(second)
        assert second.get_extra(ARRIVAL_KEY).batch
        await task
    finally:
        hook.close()
        await harness.finish()
