from __future__ import annotations

import asyncio
import json
from copy import copy, deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from astrbot.api.message_components import Plain
from astrbot.core.agent.message import (
    Message,
    bind_checkpoint_messages,
    dump_messages_with_checkpoints,
)
from astrbot.core.config.default import DEFAULT_CONFIG
from astrbot.core.pipeline.preprocess_stage.stage import PreProcessStage
from astrbot.core.pipeline.process_stage.stage import ProcessStage, StarRequestSubStage
from astrbot.core.pipeline.scheduler import PipelineScheduler
from astrbot.core.pipeline.waking_check import stage as waking
from astrbot.core.provider.entities import ProviderRequest
from astrbot.core.star.session_plugin_manager import SessionPluginManager
from astrbot.core.star.star import StarMetadata
from astrbot.core.star.star_handler import StarHandlerRegistry, star_handlers_registry
from astrbot.core.utils.session_lock import session_lock_manager
from astrbot_plugin_qq_enhance.debounce import ARRIVAL_KEY
from test_debounce import Harness, enabled_session as enabled_session, texts, wait
from test_debounce_runtime import source_message

group_module = pytest.importorskip("astrbot_plugin_qq_group_enhance.main")


@pytest_asyncio.fixture
async def integration(monkeypatch):
    harness = Harness({"initial_window_seconds": 0.1, "followup_window_seconds": 0.05})
    config = deepcopy(DEFAULT_CONFIG)
    config["provider_settings"]["wake_prefix"] = ""
    context = harness.plugin.context
    context.get_config = lambda **kwargs: config
    group = group_module.QQGroupEnhancePlugin(
        context,
        {"keyword_wake": {"keywords": ["小爱"]}, "semantic": {"enabled": False}},
    )
    gates = {}
    preprocess_gates = {}
    preprocessing = asyncio.Event()
    observed = asyncio.Event()
    window = asyncio.Event()
    original_wait = harness.plugin.debouncer._wait

    async def observe_wait(arrival, *args):
        window.set()
        await original_wait(arrival, *args)

    monkeypatch.setattr(harness.plugin.debouncer, "_wait", observe_wait)
    monkeypatch.setattr(
        SessionPluginManager,
        "filter_handlers_by_session",
        AsyncMock(side_effect=lambda event, handlers: handlers),
    )
    monkeypatch.setattr("astrbot.core.utils.metrics.Metric.upload", AsyncMock())
    registry = StarHandlerRegistry()
    for instance, names in (
        (group, ("observe_message", "collect_message")),
        (harness.plugin, ("inherit_debounce_wake", "debounce_inbound_message")),
    ):
        module = type(instance).__module__
        monkeypatch.setitem(
            waking.star_map,
            module,
            StarMetadata(
                name="astrbot_plugin_qq_group_enhance"
                if instance is group
                else "astrbot_plugin_qq_enhance"
            ),
        )
        for name in names:
            metadata = copy(
                next(
                    item
                    for item in star_handlers_registry._handlers
                    if item.handler_module_path == module and item.handler_name == name
                )
            )
            metadata.handler = getattr(instance, name)
            if name == "observe_message":
                original = metadata.handler

                async def observe(event):
                    await original(event)
                    observed.set()
                    if gate := gates.get(event.message_obj.message_id):
                        await gate.wait()

                metadata.handler = observe
            registry.append(metadata)
    monkeypatch.setattr(waking, "star_handlers_registry", registry)
    ctx = SimpleNamespace(astrbot_config=config, plugin_manager=SimpleNamespace())
    wake_stage = waking.WakingCheckStage()
    await wake_stage.initialize(ctx)
    process = ProcessStage()
    process.ctx = ctx
    process.star_request_sub_stage = StarRequestSubStage()
    await process.star_request_sub_stage.initialize(ctx)

    async def model(event):
        async with session_lock_manager.acquire_lock(event.unified_msg_origin):
            conversation = await harness.manager.get_conversation(
                event.unified_msg_origin, harness.manager.current_id
            )
            request = ProviderRequest(
                prompt=event.message_str,
                contexts=json.loads(conversation.history),
                conversation=conversation,
            )
            await harness.plugin.bind_debounce_request(event, request)
            messages = bind_checkpoint_messages(request.contexts)
            messages.append(Message.model_validate(await request.assemble_context()))
            run_context = SimpleNamespace(messages=messages)
            await harness.plugin.snapshot_debounce_input(event, run_context)
            harness.requests.append(deepcopy(dump_messages_with_checkpoints(messages)))
            event.prepared.set()
            await event.allow_reply.wait()
            messages.append(Message(role="assistant", content="reply"))
            await harness.manager.update_conversation(
                event.unified_msg_origin,
                conversation.cid,
                history=dump_messages_with_checkpoints(messages),
            )
        yield

    process.agent_sub_stage = SimpleNamespace(process=model)
    preprocess = PreProcessStage()
    await preprocess.initialize(ctx)
    group_preprocess = group.observer._preprocess(PreProcessStage.process)

    async def prepare(event):
        if gate := preprocess_gates.get(event.message_obj.message_id):
            preprocessing.set()
            await gate.wait()
        await group_preprocess(preprocess, event)

    scheduler = PipelineScheduler(ctx)
    scheduler.stages = [wake_stage, SimpleNamespace(process=prepare), process]

    def start(text, message_id):
        event = source_message("10")
        event.role = "member"
        event.session_id = "10"
        event.is_at_or_wake_command = False
        event.message_str = event.message_obj.message_str = text
        event.message_obj.message = [Plain(text)]
        event.message_obj.message_id = str(message_id)
        event.message_obj.raw_message["message_id"] = message_id
        event.bot = AsyncMock()
        event.prepared = asyncio.Event()
        event.allow_reply = asyncio.Event()
        task = asyncio.create_task(scheduler.execute(event))
        harness.tasks.append(task)
        return event, task

    try:
        yield SimpleNamespace(
            harness=harness,
            start=start,
            gates=gates,
            preprocess_gates=preprocess_gates,
            preprocessing=preprocessing,
            observed=observed,
            window=window,
        )
    finally:
        for gate in (*gates.values(), *preprocess_gates.values()):
            gate.set()
        await harness.finish()
        await group.terminate()


@pytest.mark.asyncio
async def test_group_plugin_keyword_opens_inheritance_window(integration):
    first, first_task = integration.start("小爱", 1)
    await wait(integration.window)
    assert first.is_at_or_wake_command
    second, second_task = integration.start("请帮我看看这件事", 2)
    await wait(second.prepared)
    assert second.is_at_or_wake_command
    assert texts(integration.harness.requests[-1]) == ["小爱", "请帮我看看这件事"]
    assert first_task.cancelled()
    second.allow_reply.set()
    await second_task


@pytest.mark.asyncio
async def test_keyword_followup_arriving_before_window_registration_is_retained(
    integration,
):
    gate = integration.gates["1"] = asyncio.Event()
    first, _ = integration.start("小爱", 1)
    await wait(integration.observed)
    assert first.is_at_or_wake_command
    assert first.get_extra(ARRIVAL_KEY).debouncer is None
    second, second_task = integration.start("请帮我看看这件事", 2)
    await asyncio.sleep(0)
    gate.set()
    await wait(second.prepared)
    assert second.is_at_or_wake_command
    assert texts(integration.harness.requests[-1]) == ["小爱", "请帮我看看这件事"]
    second.allow_reply.set()
    await second_task


@pytest.mark.asyncio
async def test_followup_can_arrive_before_group_plugin_marks_keyword_wake(integration):
    gate = integration.preprocess_gates["1"] = asyncio.Event()
    first, _ = integration.start("小爱", 1)
    await wait(integration.preprocessing)
    assert not first.is_at_or_wake_command
    second, second_task = integration.start("紧接着发的正文", 2)
    await asyncio.sleep(0)
    gate.set()
    await wait(second.prepared)
    assert second.is_at_or_wake_command
    assert texts(integration.harness.requests[-1]) == ["小爱", "紧接着发的正文"]
    second.allow_reply.set()
    await second_task


@pytest.mark.asyncio
async def test_pending_keyword_inheritance_keeps_slow_preparation_and_several_inputs(
    integration,
):
    first_gate = integration.gates["1"] = asyncio.Event()
    slow_gate = integration.preprocess_gates["3"] = asyncio.Event()
    first, _ = integration.start("小爱", 1)
    await wait(integration.observed)
    second, _ = integration.start("第一条补充", 2)
    third, third_task = integration.start("语音转写后的第二条补充", 3)
    await wait(integration.preprocessing)
    first_gate.set()
    await wait(first.get_extra(ARRIVAL_KEY).wake_checked)
    assert second.get_extra(ARRIVAL_KEY).wake_source is not None
    assert third.get_extra(ARRIVAL_KEY).wake_source is not None
    await wait(second.prepared)
    slow_gate.set()
    await wait(third.prepared)
    assert texts(integration.harness.requests[-1]) == [
        "小爱",
        "第一条补充",
        "语音转写后的第二条补充",
    ]
    third.allow_reply.set()
    await third_task


@pytest.mark.asyncio
async def test_stopped_keyword_source_does_not_wake_pending_followup(integration):
    gate = integration.gates["1"] = asyncio.Event()
    first, first_task = integration.start("小爱", 1)
    await wait(integration.observed)
    second, second_task = integration.start("不应进入模型的正文", 2)
    await asyncio.sleep(0)
    first.stop_event()
    gate.set()
    await first_task
    await second_task
    assert not second.is_at_or_wake_command
    assert not second.prepared.is_set()
    assert not integration.harness.requests


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reason", ["inherit_off", "debounce_off", "zero", "old_source"]
)
async def test_pending_keyword_wake_respects_switches_and_window_bounds(
    integration, reason
):
    gate = integration.gates["1"] = asyncio.Event()
    first, _ = integration.start("小爱", 1)
    await wait(integration.observed)
    config = integration.harness.runtime.config
    if reason == "inherit_off":
        config["inherit_group_wake"] = False
    elif reason == "debounce_off":
        config["enabled"] = False
    elif reason == "zero":
        config.update(initial_window_seconds=0, followup_window_seconds=0)
    else:
        first.get_extra(ARRIVAL_KEY).received_at -= 10
    second, second_task = integration.start("不应自动继承的消息", 2)
    await asyncio.sleep(0)
    gate.set()
    await second_task
    assert not second.is_at_or_wake_command
    assert not second.prepared.is_set()


@pytest.mark.asyncio
async def test_slow_keyword_source_does_not_hold_followup_indefinitely(integration):
    integration.gates["1"] = asyncio.Event()
    integration.start("小爱", 1)
    await wait(integration.observed)
    second, second_task = integration.start("等待上限内尚未建立窗口", 2)
    await asyncio.wait_for(second_task, 0.5)
    assert not second.is_at_or_wake_command
    assert second.get_extra(ARRIVAL_KEY).wake_pending is None
