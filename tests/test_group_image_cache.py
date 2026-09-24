from __future__ import annotations

import asyncio
import base64
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from mcp.types import ImageContent

from astrbot.api.message_components import Image
from astrbot.api.provider import ProviderRequest
from astrbot.core.agent.message import Message, dump_messages_with_checkpoints
from astrbot.core.pipeline.preprocess_stage import stage as preprocess_stage
from astrbot.core.pipeline.preprocess_stage.stage import PreProcessStage
from astrbot.core.utils import media_utils
from astrbot_plugin_qq_enhance.context_images import ContextImageError
from astrbot_plugin_qq_enhance.group_image_cache import (
    GROUP_IMAGES_EXTRA,
    GroupImageCache,
)
from astrbot_plugin_qq_enhance.main import QQEnhancePlugin
from astrbot_plugin_qq_enhance.runtime import validate_config

from test_context_images import build_manager, save_image
from test_group_component_context import adapter as adapter, core as core, make_event


@pytest_asyncio.fixture
async def environment(tmp_path, core):
    manager, storage, _ = await build_manager(tmp_path)
    plugin = object.__new__(QQEnhancePlugin)
    plugin.config = validate_config(None)
    plugin.context = SimpleNamespace(
        get_config=core.context.get_config,
        conversation_manager=SimpleNamespace(
            get_curr_conversation_id=AsyncMock(return_value=None)
        ),
    )
    plugin.context_images = manager
    return plugin, manager, storage


@pytest.mark.asyncio
async def test_group_image_survives_event_cleanup_and_reaches_later_request(
    tmp_path, monkeypatch, adapter, core, environment
):
    plugin, manager, storage = environment
    original = tmp_path / "source.png"
    payload = save_image(original, "PNG", (7, 9))
    temp = tmp_path / "astrbot-temp"
    monkeypatch.setattr(media_utils, "get_astrbot_temp_path", lambda: str(temp))
    monkeypatch.setattr(preprocess_stage, "get_astrbot_temp_path", lambda: str(temp))
    event = await make_event(
        adapter,
        [
            {
                "type": "image",
                "data": {
                    "file": "data:image/png;base64,"
                    + base64.b64encode(payload).decode()
                },
            }
        ],
    )
    stage = PreProcessStage()
    stage.config = {}
    stage.platform_settings = {}
    stage.stt_settings = {"enable": False}
    await stage.process(event)
    downloaded = Path(event.get_messages()[0].path)
    assert downloaded.is_file()
    prepared_payload = downloaded.read_bytes()
    await plugin.enrich_inbound_qq_components(event)
    await plugin.cache_group_context_images(event)
    assert event.is_at_or_wake_command is False
    async for _ in core.on_message(event):
        pass
    image_ref = event.get_extra(GROUP_IMAGES_EXTRA)[0]["image_ref"]
    event.cleanup_temporary_local_files()
    assert not downloaded.exists()

    current = await make_event(
        adapter, [{"type": "text", "data": {"text": "explain that image"}}]
    )
    current.is_at_or_wake_command = True
    async for _ in core.on_message(current):
        pass
    request = ProviderRequest(
        prompt=current.message_str, conversation=SimpleNamespace(cid="c1")
    )
    await core.decorate_llm_req(current, request)
    await plugin.virtualize_context_images(current, request)
    assert any(image_ref in part.text for part in request.extra_user_content_parts)
    assert request.image_urls == []
    result = await manager.inspect(current, image_ref)
    content = next(part for part in result.content if isinstance(part, ImageContent))
    assert base64.b64decode(content.data) == prepared_payload
    assert await storage.list_context_images() == []
    assert len(list(manager.group_cache.root.glob("blob_*"))) == 1


@pytest.mark.asyncio
async def test_current_group_images_reuse_cache_without_second_archive(
    tmp_path, adapter, environment
):
    plugin, manager, storage = environment
    original = tmp_path / "source.png"
    save_image(original, "PNG", (7, 9))
    event = await make_event(
        adapter, [{"type": "image", "data": {"file": str(original)}}] * 2
    )
    event.is_at_or_wake_command = True
    await plugin.cache_group_context_images(event)
    await plugin.cache_group_context_images(event)
    assert event.message_str.count("[QQ ImageRef") == 1
    request = ProviderRequest(
        prompt="look at this",
        conversation=SimpleNamespace(cid="c1"),
        image_urls=[str(original)],
    )
    await plugin.virtualize_context_images(event, request)
    assert await storage.list_context_images() == []
    assert len(list(manager.group_cache.root.glob("blob_*"))) == 1
    assert (
        sum("[QQ ImageRef" in part.text for part in request.extra_user_content_parts)
        == 1
    )
    assembled = Message.model_validate(await request.assemble_context())
    manager.mark_current_request_images(event, SimpleNamespace(messages=[assembled]))
    persisted = str(dump_messages_with_checkpoints([assembled]))
    assert "data:image" not in persisted
    assert "gimg_" in persisted


@pytest.mark.asyncio
async def test_cache_deduplicates_bytes_but_isolates_platform_group_and_conversation(
    tmp_path,
):
    cache = GroupImageCache(tmp_path / "cache", 256, 24, 10)
    path = tmp_path / "image.png"
    save_image(path, "PNG", (3, 3))
    first = await cache.put(str(path), "p", "group-a", "c1")
    again = await cache.put(str(path), "p", "group-a", "c1")
    other = await cache.put(str(path), "p", "group-b", "c1")
    assert first == again
    assert other["image_ref"] != first["image_ref"]
    assert len(list(cache.root.glob("blob_*"))) == 1
    for platform, origin, cid in [
        ("q", "group-a", "c1"),
        ("p", "group-b", "c1"),
        ("p", "group-a", "c2"),
    ]:
        assert await cache.read(first["image_ref"], platform, origin, cid) is None
    await cache.bind([first["image_ref"]], "p", "group-a", "c2")
    assert await cache.read(first["image_ref"], "p", "group-a", "c2") is None
    restored = GroupImageCache(cache.root, 256, 24, 10)
    assert await restored.read(first["image_ref"], "p", "group-a", "c1") is not None


@pytest.mark.asyncio
async def test_cache_expires_after_24_hours_even_when_inspected(tmp_path):
    cache = GroupImageCache(tmp_path / "cache", 256, 24, 10)
    path = tmp_path / "image.png"
    save_image(path, "PNG", (3, 3))
    with patch(
        "astrbot_plugin_qq_enhance.group_image_cache.time.time", return_value=100
    ):
        record = await cache.put(str(path), "p", "g", "c")
    with patch(
        "astrbot_plugin_qq_enhance.group_image_cache.time.time", return_value=86499
    ):
        assert await cache.read(record["image_ref"], "p", "g", "c") is not None
    with patch(
        "astrbot_plugin_qq_enhance.group_image_cache.time.time", return_value=86500
    ):
        assert await cache.read(record["image_ref"], "p", "g", "c") is None
    assert not list(cache.root.glob("blob_*"))


@pytest.mark.asyncio
async def test_shared_file_survives_until_all_references_expire(tmp_path):
    cache = GroupImageCache(tmp_path / "cache", 256, 24, 10)
    path = tmp_path / "image.png"
    save_image(path, "PNG", (3, 3))
    with patch(
        "astrbot_plugin_qq_enhance.group_image_cache.time.time", return_value=100
    ):
        first = await cache.put(str(path), "p", "g1", "c")
    with patch(
        "astrbot_plugin_qq_enhance.group_image_cache.time.time", return_value=200
    ):
        second = await cache.put(str(path), "p", "g2", "c")
    with patch(
        "astrbot_plugin_qq_enhance.group_image_cache.time.time", return_value=86500
    ):
        assert await cache.read(first["image_ref"], "p", "g1", "c") is None
        assert await cache.read(second["image_ref"], "p", "g2", "c") is not None
        assert len(list(cache.root.glob("blob_*"))) == 1
    with patch(
        "astrbot_plugin_qq_enhance.group_image_cache.time.time", return_value=86600
    ):
        await cache.cleanup()
        assert not list(cache.root.glob("blob_*"))


@pytest.mark.asyncio
async def test_oversized_or_invalid_image_does_not_evict_existing_cache(tmp_path):
    cache = GroupImageCache(tmp_path / "cache", 256, 24, 10)
    path = tmp_path / "image.png"
    payload = save_image(path, "PNG", (3, 3))
    record = await cache.put(str(path), "p", "g", "c")
    cache.max_bytes = len(payload)
    bad_path = tmp_path / "bad.bin"
    for contents in (b"not an image", payload + b"larger"):
        bad_path.write_bytes(contents)
        with pytest.raises((OSError, ValueError)):
            await cache.put(str(bad_path), "p", "g", "c")
        assert await cache.read(record["image_ref"], "p", "g", "c") is not None


@pytest.mark.asyncio
async def test_restart_removes_unindexed_files_before_capacity_check(tmp_path):
    cache = GroupImageCache(tmp_path / "cache", 256, 24, 10)
    orphan = cache.root / "blob_interrupted.partial"
    orphan.write_bytes(b"interrupted write")
    path = tmp_path / "image.png"
    payload = save_image(path, "PNG", (3, 3))
    cache.max_bytes = len(payload)
    await cache.put(str(path), "p", "g", "c")
    assert not orphan.exists()
    assert sum(item.stat().st_size for item in cache.root.glob("blob_*")) == len(
        payload
    )


@pytest.mark.asyncio
async def test_global_capacity_evicts_oldest_unique_image(tmp_path):
    cache = GroupImageCache(tmp_path / "cache", 256, 24, 10)
    first_path, second_path = tmp_path / "first.png", tmp_path / "second.png"
    first_bytes = save_image(first_path, "PNG", (3, 3))
    second_bytes = save_image(second_path, "PNG", (4, 4))
    cache.max_bytes = max(len(first_bytes), len(second_bytes))
    first = await cache.put(str(first_path), "p", "g1", "c")
    second = await cache.put(str(second_path), "p", "g2", "c")
    assert await cache.read(first["image_ref"], "p", "g1", "c") is None
    assert await cache.read(second["image_ref"], "p", "g2", "c") is not None
    assert (
        sum(path.stat().st_size for path in cache.root.glob("blob_*"))
        <= cache.max_bytes
    )


@pytest.mark.asyncio
async def test_parallel_duplicate_captures_share_file_and_reference(tmp_path):
    cache = GroupImageCache(tmp_path / "cache", 256, 24, 10)
    path = tmp_path / "image.png"
    save_image(path, "PNG", (3, 3))
    records = await asyncio.gather(
        *(cache.put(str(path), "p", "g", "c") for _ in range(8))
    )
    assert len({record["image_ref"] for record in records}) == 1
    assert len(list(cache.root.glob("blob_*"))) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("setting", ["enabled", "group_cache_enabled"])
async def test_disabled_cache_leaves_images_unmodified(
    tmp_path, adapter, environment, setting
):
    plugin, manager, _ = environment
    plugin.config["context_images"][setting] = False
    path = tmp_path / "image.png"
    save_image(path, "PNG", (3, 3))
    event = await make_event(adapter, [{"type": "image", "data": {"file": str(path)}}])
    await plugin.cache_group_context_images(event)
    assert event.get_extra(GROUP_IMAGES_EXTRA) is None
    assert len(event.get_messages()) == 1
    assert not list(manager.group_cache.root.glob("blob_*"))


@pytest.mark.asyncio
async def test_failed_preprocessing_does_not_trigger_another_download(
    adapter, environment
):
    plugin, manager, _ = environment
    event = await make_event(
        adapter, [{"type": "image", "data": {"file": "https://example.com/image.png"}}]
    )
    with patch.object(
        Image, "convert_to_file_path", AsyncMock(side_effect=AssertionError("network"))
    ):
        await plugin.cache_group_context_images(event)
    assert event.get_extra(GROUP_IMAGES_EXTRA) is None
    assert not list(manager.group_cache.root.glob("blob_*"))


@pytest.mark.asyncio
async def test_evicted_reference_reports_clear_error(tmp_path, adapter, environment):
    plugin, manager, _ = environment
    path = tmp_path / "image.png"
    save_image(path, "PNG", (3, 3))
    event = await make_event(adapter, [{"type": "image", "data": {"file": str(path)}}])
    await plugin.cache_group_context_images(event)
    request = ProviderRequest(
        prompt=event.message_str, conversation=SimpleNamespace(cid="c1")
    )
    await plugin.virtualize_context_images(event, request)
    manager.group_cache.max_bytes = 0
    await manager.group_cache.cleanup()
    with pytest.raises(ContextImageError, match="过期、被淘汰"):
        await manager.inspect(
            event, event.get_extra(GROUP_IMAGES_EXTRA)[0]["image_ref"]
        )


@pytest.mark.parametrize(
    "config",
    [
        {"group_cache_enabled": 1},
        {"group_cache_max_mb": 0},
        {"group_cache_max_mb": True},
        {"group_cache_ttl_hours": 0},
        {"group_cache_ttl_hours": 169},
        {"group_cache_ttl_hours": "24"},
    ],
)
def test_group_cache_config_is_strict(config):
    with pytest.raises(ValueError):
        validate_config({"context_images": config})
