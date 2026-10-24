"""Optional two-repository integration: the QQ-only suite needs no media plugin."""

# ruff: noqa: E402
from __future__ import annotations

import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

media_module = pytest.importorskip("astrbot_plugin_media_manager.main")

from astrbot.api.message_components import Image, Reply
from astrbot.api.provider import ProviderRequest
from astrbot.core.agent.message import (
    ImageURLPart,
    Message,
    TextPart,
    dump_messages_with_checkpoints,
)
from astrbot.core.pipeline import context_utils
from astrbot.core.star.star import star_map
from astrbot.core.star.star_handler import (
    EventType,
    StarHandlerRegistry,
    star_handlers_registry,
)
from astrbot_plugin_media_manager.config import validate_config as media_config
from astrbot_plugin_media_manager.context_images import ContextImageManager
from astrbot_plugin_media_manager.group_image_cache import (
    GROUP_IMAGES_EXTRA,
    GroupImageCache,
)
from astrbot_plugin_media_manager.image_links import IMAGE_LINKS_EXTRA
from astrbot_plugin_media_manager.storage import Storage
from astrbot_plugin_qq_enhance.debounce import ARRIVAL_KEY
from astrbot_plugin_qq_enhance.debounce_runtime import (
    AstrBotDebounceRuntime,
    ResumedMessageEvent,
)
from astrbot_plugin_qq_enhance.main import QQEnhancePlugin
from astrbot_plugin_qq_enhance.runtime import validate_config
from test_debounce import Event, Harness, enabled_session as enabled_session, wait
from test_group_component_context import adapter as adapter, core as core, make_event
from test_image_semantics import make_image


async def build_media(tmp_path, conversations=None, config=None):
    plugin = object.__new__(media_module.MediaManagerPlugin)
    plugin.config = media_config(config)
    plugin.storage = Storage(tmp_path / "media.sqlite3")
    await plugin.storage.initialize()
    plugin.context = SimpleNamespace(
        conversation_manager=conversations
        or SimpleNamespace(get_curr_conversation_id=AsyncMock(return_value="c1")),
        get_config=lambda **kwargs: {
            "provider_ltm_settings": {"group_icl_enable": True}
        },
    )
    plugin.images = ContextImageManager(
        plugin.context,
        plugin.storage,
        tmp_path / "images",
        3,
        30,
        64,
        10,
        GroupImageCache(tmp_path / "cache", 256, 24, 10),
    )
    plugin.ready = True
    return plugin


def install_dispatch(monkeypatch, instances):
    """Bind real decorated metadata and use AstrBot's sorting and hook dispatcher."""
    registry = StarHandlerRegistry()
    methods = []
    for instance, names in instances:
        for name in names:
            bound = getattr(instance, name)
            original = next(
                md
                for md in star_handlers_registry._handlers
                if md.handler_module_path == bound.__module__
                and md.handler_name == name
            )
            metadata = copy.copy(original)
            metadata.handler = bound
            methods.append(metadata)
            monkeypatch.setitem(
                star_map,
                bound.__module__,
                SimpleNamespace(
                    name="astrbot_plugin_media_manager"
                    if isinstance(instance, media_module.MediaManagerPlugin)
                    else "astrbot_plugin_qq_enhance",
                    activated=True,
                    reserved=False,
                ),
            )
    # Deliberately reverse insertion: ordering must come from declared priorities.
    for metadata in reversed(methods):
        registry.append(metadata)
    monkeypatch.setattr(context_utils, "star_handlers_registry", registry)

    async def dispatch(event_type, event, *args):
        if not hasattr(event, "plugins_name"):
            event.plugins_name = None
        return await context_utils.call_event_hook(event, event_type, *args)

    return dispatch


@pytest.mark.asyncio
async def test_separate_labels_share_ids_for_multiple_and_quoted_images(
    tmp_path, adapter, monkeypatch
):
    media = await build_media(tmp_path / "media", config={"max_components": 1})
    qq = object.__new__(QQEnhancePlugin)
    qq.config = validate_config(None)
    first = make_image(tmp_path / "first.gif", frames=2)
    second = make_image(tmp_path / "second.png", image_format="PNG")
    event = await make_event(
        adapter,
        [
            {
                "type": "image",
                "data": {"file": str(first), "sub_type": 1, "summary": "[出发啦]"},
            },
            {"type": "image", "data": {"file": str(second)}},
        ],
        group_id=0,
    )
    quoted = Image(file=str(second))
    event.message_obj.message.insert(0, Reply(id="old", chain=[quoted]))
    quoted = event.message_obj.message[0].chain[0]
    dispatch = install_dispatch(
        monkeypatch,
        [(media, ["assign_image_ids"]), (qq, ["enrich_inbound_qq_components"])],
    )
    await dispatch(EventType.AdapterMessageEvent, event)
    links = event.get_extra(IMAGE_LINKS_EXTRA)
    assert len(set(links.values())) == 3
    assert links[id(quoted)] not in event.message_str
    assert "QQ动态表情包：出发啦" in event.message_str
    assert "image_ref=" not in event.message_str
    before = event.message_str
    request = ProviderRequest(
        prompt=before,
        conversation=SimpleNamespace(cid="c1"),
        image_urls=[str(second), str(first), str(second)],
    )
    await media.prepare_images(event, request)
    assert event.message_str == before  # The media plugin never rewrites QQ text.
    references = [
        part.text
        for part in request.extra_user_content_parts
        if isinstance(part, TextPart)
    ]
    assert len(references) == 3
    for link in links.values():
        assert sum(link in text for text in references) == 1
    assert request.image_urls == [str(second), str(first), str(second)]
    current = Message.model_validate(await request.assemble_context())
    await media.bind_image_refs(event, SimpleNamespace(messages=[current]))
    assert all(
        part.image_url.id for part in current.content if isinstance(part, ImageURLPart)
    )
    assert "data:image" in str(dump_messages_with_checkpoints([current]))


@pytest.mark.asyncio
async def test_group_reference_survives_event_cleanup_and_later_wakeup(
    tmp_path, adapter, core, monkeypatch
):
    media = await build_media(tmp_path / "media")
    media.context.get_config = core.context.get_config
    media.context.conversation_manager.get_curr_conversation_id.return_value = None
    qq = object.__new__(QQEnhancePlugin)
    qq.config = validate_config(None)
    path = make_image(tmp_path / "group.gif", frames=2)
    event = await make_event(
        adapter, [{"type": "image", "data": {"file": str(path), "sub_type": 1}}]
    )
    dispatch = install_dispatch(
        monkeypatch,
        [
            (qq, ["enrich_inbound_qq_components"]),
            (media, ["cache_group_images", "assign_image_ids"]),
        ],
    )
    await dispatch(EventType.AdapterMessageEvent, event)
    async for _ in core.on_message(event):
        pass
    cached = event.get_extra(GROUP_IMAGES_EXTRA)[0]
    event.track_temporary_local_file(str(path))
    event.cleanup_temporary_local_files()
    assert not path.exists()
    current = await make_event(
        adapter, [{"type": "text", "data": {"text": "看看刚才那张图"}}]
    )
    current.is_at_or_wake_command = True
    async for _ in core.on_message(current):
        pass
    request = ProviderRequest(
        prompt=current.message_str, conversation=SimpleNamespace(cid="c1")
    )
    await core.decorate_llm_req(current, request)
    await media.prepare_images(current, request)
    texts = "\n".join(
        part.text
        for part in request.extra_user_content_parts
        if isinstance(part, TextPart)
    )
    assert cached["image_id"] in texts
    assert cached["image_ref"] in texts
    assert "QQ动态表情包" in texts and "[Media ImageRef" in texts
    assert await media.images.group_cache.read(
        cached["image_ref"], current.get_platform_id(), current.unified_msg_origin, "c1"
    )
    assert request.image_urls == []
    assert await media.storage.list_context_images() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("second_image", [False, True])
async def test_real_hook_order_keeps_images_through_debounce_then_lightens(
    tmp_path, monkeypatch, second_image
):
    harness = Harness()
    media = await build_media(tmp_path / "media", harness.manager)
    dispatch = install_dispatch(
        monkeypatch,
        [
            (harness.plugin, ["snapshot_debounce_input"]),
            (media, ["bind_image_refs", "lighten_history"]),
        ],
    )

    async def request_hook(event, request):
        request.image_urls = [
            component.file
            for component in event.get_messages()
            if isinstance(component, Image)
        ]
        await media.prepare_images(event, request)

    harness.request_hook = request_hook
    harness.agent_begin_hook = lambda event, ctx: dispatch(
        EventType.OnAgentBeginEvent, event, ctx
    )
    harness.agent_done_hook = lambda event, ctx, response: dispatch(
        EventType.OnAgentDoneEvent, event, ctx, response
    )
    first, second = Event("看看这张图", 1), Event("重点看右下角", 2)
    for index, event in enumerate([first, second] if second_image else [first]):
        path = make_image(tmp_path / f"image-{index}.png", image_format="PNG")
        event.message_obj.message = [Image(file=str(path))]
    try:
        first_task = harness.start(first)
        await wait(first.prepared)
        image_ref = (await media.storage.list_context_images())[0]["image_ref"]
        snapshot = first.get_extra(ARRIVAL_KEY).messages[-1]
        assert any(
            part.get("image_url", {}).get("id") == image_ref
            for part in snapshot["content"]
        )
        second_task = harness.start(second)
        await wait(second.prepared)
        assert first_task.cancelled()
        assert "data:image" in json.dumps(harness.manager.history(first))
        assert image_ref in json.dumps(harness.requests[-1])
        assert "data:image" in json.dumps(harness.requests[-1])
        second.allow_reply.set()
        await second_task
        history = json.dumps(harness.manager.history(second))
        assert "data:image" not in history
        assert image_ref in history
        assert len(await media.storage.list_context_images()) == (
            2 if second_image else 1
        )
    finally:
        await harness.finish()


@pytest.mark.asyncio
async def test_resume_rebuild_happens_before_media_request_preparation(
    tmp_path, adapter, monkeypatch
):
    source = await make_event(
        adapter, [{"type": "text", "data": {"text": "原始输入"}}], group_id=0
    )
    debouncer = SimpleNamespace(closed=False, config={"enabled": True})
    event = ResumedMessageEvent(source, debouncer)
    event.authorize_resume()
    event.set_extra(ARRIVAL_KEY, SimpleNamespace(conversation_id="c1"))
    manager = SimpleNamespace(
        get_conversation=AsyncMock(
            return_value=SimpleNamespace(cid="c1", history="[]")
        ),
        get_curr_conversation_id=AsyncMock(return_value="c1"),
    )
    runtime = object.__new__(AstrBotDebounceRuntime)
    runtime.context = SimpleNamespace(conversation_manager=manager)
    runtime.can_resume = AsyncMock(return_value=True)
    debouncer.runtime = runtime
    qq = object.__new__(QQEnhancePlugin)
    qq.debouncer = debouncer
    media = await build_media(tmp_path / "media", manager)
    dispatch = install_dispatch(
        monkeypatch, [(media, ["prepare_images"]), (qq, ["finalize_debounce_resume"])]
    )
    request = ProviderRequest(
        prompt="占位请求", extra_user_content_parts=[TextPart(text="待清空")]
    )
    await dispatch(EventType.OnLLMRequestEvent, event, request)
    assert request.prompt is None
    assert request.extra_user_content_parts == []
    assert event.get_extra("_media_manager_conversation_id") == "c1"
    assert "Media 管理" in request.system_prompt
