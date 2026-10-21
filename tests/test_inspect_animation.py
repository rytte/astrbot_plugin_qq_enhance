from __future__ import annotations

import base64
import io
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from mcp.types import CallToolResult, ImageContent, TextContent
from PIL import Image as PillowImage

from astrbot.api.message_components import Image, Reply
from astrbot.api.provider import ProviderRequest
from astrbot.core.agent.message import (
    ImageURLPart,
    Message,
    TextPart,
    dump_messages_with_checkpoints,
)
from astrbot_plugin_qq_enhance.context_images import (
    CONVERSATION_ID_EXTRA,
    ContextImageError,
)
from astrbot_plugin_qq_enhance.group_image_cache import GROUP_IMAGES_EXTRA
from astrbot_plugin_qq_enhance.runtime import validate_config

from test_animation_preview import animation_bytes
from test_context_images import Event, build_manager
from test_group_component_context import adapter as adapter, core as core, make_event
from test_group_image_cache import environment as environment
from test_runtime import FakeEvent, make_runtime


@pytest.mark.asyncio
@pytest.mark.parametrize("prefix", ["img", "gimg"])
@pytest.mark.parametrize("count", [2, 12])
async def test_animation_preview_keeps_original_and_scopes_both_reference_types(
    tmp_path, prefix, count
):
    manager, storage, _ = await build_manager(tmp_path)
    path = tmp_path / "original.gif"
    payload = animation_bytes(count=count)
    path.write_bytes(payload)
    event = Event(path)
    event.set_extra(CONVERSATION_ID_EXTRA, "c1")
    if prefix == "img":
        await manager.prepare_request(
            event,
            ProviderRequest(
                conversation=SimpleNamespace(cid="c1"), image_urls=[str(path)]
            ),
        )
        image_ref = (await storage.list_context_images())[0]["image_ref"]
    else:
        record = await manager.group_cache.put(
            str(path), event.platform_id, event.unified_msg_origin, "c1"
        )
        image_ref = record["image_ref"]
    result = await manager.inspect_animation(event, image_ref)
    assert len(result.content) == 2
    text, image = result.content
    assert isinstance(text, TextContent)
    assert isinstance(image, ImageContent)
    assert image.mimeType == "image/png"
    assert f"共 {count} 帧，采样 {min(9, count)} 帧" in text.text
    assert "从左到右、从上到下" in text.text
    assert "同一张动图" in text.text
    assert ("其余格留空" in text.text) == (count < 9)
    with PillowImage.open(io.BytesIO(base64.b64decode(image.data))) as sheet:
        assert sheet.n_frames == 1
        assert sheet.size == (1152, 1248)
    original = await manager.inspect(event, image_ref)
    assert base64.b64decode(original.content[1].data) == payload
    assert path.read_bytes() == payload
    for wrong in (
        Event(platform_id="platform-b"),
        Event(unified_msg_origin="platform-a:FriendMessage:other"),
        Event(),
    ):
        wrong.set_extra(
            CONVERSATION_ID_EXTRA,
            "c2"
            if wrong.platform_id == event.platform_id
            and wrong.unified_msg_origin == event.unified_msg_origin
            else "c1",
        )
        with pytest.raises(ContextImageError, match="不属于当前会话"):
            await manager.inspect_animation(wrong, image_ref)


@pytest.mark.asyncio
async def test_static_corrupt_and_expired_references_return_safe_errors(tmp_path):
    manager, storage, _ = await build_manager(tmp_path)
    path = tmp_path / "static.gif"
    path.write_bytes(animation_bytes(count=1))
    event = Event(path)
    await manager.prepare_request(
        event,
        ProviderRequest(conversation=SimpleNamespace(cid="c1"), image_urls=[str(path)]),
    )
    record = (await storage.list_context_images())[0]
    with pytest.raises(ContextImageError, match="inspect") as error:
        await manager.inspect_animation(event, record["image_ref"])
    assert error.value.code == "animation_preview_unavailable"
    stored_path = Path(record["path"])
    stored_path.write_bytes(b"corrupt")
    with pytest.raises(ContextImageError, match="无法解码"):
        await manager.inspect_animation(event, record["image_ref"])
    stored_path.unlink()
    with pytest.raises(ContextImageError, match="不可用"):
        await manager.inspect_animation(event, record["image_ref"])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("data", "count", "label"),
    [
        ({}, 1, "QQ图片"),
        ({"summary": "[开心]"}, 1, "QQ图片：开心"),
        ({"sub_type": 1, "summary": "[开心]"}, 1, "QQ表情包：开心"),
        ({"emoji_id": "e1", "summary": "[开心]"}, 1, "QQ商城表情：开心"),
        ({}, 3, "QQ动图"),
        ({"sub_type": 1}, 3, "QQ动态表情包"),
        ({"emoji_id": "e1", "summary": "[开心]"}, 3, "QQ商城表情：开心；动态"),
    ],
)
async def test_private_semantics_binds_real_archive_reference_without_preprocessing(
    tmp_path, adapter, environment, data, count, label
):
    plugin, manager, storage = environment
    path = tmp_path / "source.gif"
    payload = animation_bytes(count=count)
    path.write_bytes(payload)
    event = await make_event(
        adapter, [{"type": "image", "data": {"file": str(path), **data}}], group_id=None
    )
    with patch(
        "astrbot_plugin_qq_enhance.context_images.render_animation_preview"
    ) as render:
        await plugin.enrich_inbound_qq_components(event)
        request = ProviderRequest(
            prompt=event.message_str,
            conversation=SimpleNamespace(cid="c1"),
            image_urls=[str(path)],
        )
        await plugin.virtualize_context_images(event, request)
    render.assert_not_called()
    record = (await storage.list_context_images())[0]
    image_ref = record["image_ref"]
    expected = (
        f"[QQ component|{label}；image_ref={image_ref}；32x24；"
        '如需查看原图，调用 qq_media(operation="inspect", '
        f'params={{"image_ref":"{image_ref}"}})'
    )
    if count > 1:
        expected += (
            '；如需查看动画，调用 qq_media(operation="inspect_animation", '
            f'params={{"image_ref":"{image_ref}"}})'
        )
    assert request.prompt == expected + "]"
    assert request.image_urls == [str(path)]
    assert request.extra_user_content_parts == []
    result = await manager.inspect(event, image_ref)
    assert base64.b64decode(result.content[1].data) == payload


@pytest.mark.asyncio
async def test_current_reference_does_not_rewrite_identical_labels_in_earlier_context(
    tmp_path, adapter, environment
):
    plugin, _, _ = environment
    path = tmp_path / "current.gif"
    path.write_bytes(animation_bytes())
    event = await make_event(
        adapter,
        [
            {"type": "text", "data": {"text": "[QQ component|QQ动图]"}},
            {"type": "image", "data": {"file": str(path)}},
        ],
        group_id=None,
    )
    await plugin.enrich_inbound_qq_components(event)
    earlier = TextPart(text="[之前的群消息]: [QQ component|QQ动图]")
    request = ProviderRequest(
        prompt=event.message_str,
        conversation=SimpleNamespace(cid="c1"),
        image_urls=[str(path)],
        extra_user_content_parts=[earlier],
    )
    await plugin.virtualize_context_images(event, request)
    assert earlier.text == "[之前的群消息]: [QQ component|QQ动图]"
    assert "inspect_animation" in request.prompt
    assert request.prompt.startswith("[QQ component|QQ动图]\n")


@pytest.mark.asyncio
@pytest.mark.parametrize("group", [False, True])
async def test_merged_reference_reaches_requests_without_current_annotation(
    tmp_path, adapter, environment, group
):
    plugin, _, storage = environment
    path = tmp_path / "still.gif"
    path.write_bytes(animation_bytes(count=1))
    event = await make_event(
        adapter,
        [{"type": "image", "data": {"file": str(path)}}] * 2,
        group_id=30003 if group else None,
    )
    await plugin.enrich_inbound_qq_components(event)
    if group:
        await plugin.cache_group_context_images(event)
    earlier = TextPart(text="[之前的群消息]: [QQ component|QQ图片]")
    request = ProviderRequest(
        prompt="看看这张图",
        conversation=SimpleNamespace(cid="c1"),
        image_urls=[str(path)],
        extra_user_content_parts=[earlier],
    )
    await plugin.virtualize_context_images(event, request)
    assert earlier.text == "[之前的群消息]: [QQ component|QQ图片]"
    assert request.prompt == "看看这张图"
    assert len(request.extra_user_content_parts) == 2
    merged = request.extra_user_content_parts[-1].text
    assert merged.startswith("[QQ component|QQ图片；image_ref=")
    assert merged.count('operation="inspect"') == 1
    assert "ImageRef" not in merged
    assert "inspect_animation" not in merged
    assert len(await storage.list_context_images()) == (0 if group else 1)


@pytest.mark.asyncio
async def test_semantic_budget_fallback_keeps_complete_archive_reference(
    tmp_path, adapter, environment
):
    plugin, manager, storage = environment
    plugin.config["inbound"]["max_semantic_chars"] = 256
    path = tmp_path / "moving.gif"
    payload = animation_bytes()
    path.write_bytes(payload)
    event = await make_event(
        adapter,
        [{"type": "image", "data": {"file": str(path), "summary": "长名称" * 100}}],
        group_id=None,
    )
    await plugin.enrich_inbound_qq_components(event)
    request = ProviderRequest(
        prompt=event.message_str,
        conversation=SimpleNamespace(cid="c1"),
        image_urls=[str(path)],
    )
    await plugin.virtualize_context_images(event, request)
    image_ref = (await storage.list_context_images())[0]["image_ref"]
    assert "image_ref=" not in request.prompt
    assert len(request.extra_user_content_parts) == 1
    assert request.extra_user_content_parts[0].text.startswith(
        f"[QQ ImageRef image_ref={image_ref}, "
    )
    assert request.extra_user_content_parts[0].text.endswith(f'"{image_ref}"}})]')
    result = await manager.inspect(event, image_ref)
    assert base64.b64decode(result.content[1].data) == payload


@pytest.mark.asyncio
@pytest.mark.parametrize("group", [False, True])
async def test_mixed_images_bind_each_image_to_its_own_reference(
    tmp_path, adapter, environment, group
):
    plugin, _, storage = environment
    paths = [tmp_path / name for name in ("first.gif", "still.gif", "second.gif")]
    for path, count in zip(paths, (2, 1, 3)):
        path.write_bytes(animation_bytes(count=count))
    event = await make_event(
        adapter,
        [{"type": "image", "data": {"file": str(path)}} for path in paths],
        group_id=30003 if group else None,
    )
    await plugin.enrich_inbound_qq_components(event)
    if group:
        await plugin.cache_group_context_images(event)
    request = ProviderRequest(
        prompt=event.message_str,
        conversation=SimpleNamespace(cid="c1"),
        image_urls=[str(path) for path in paths],
    )
    await plugin.virtualize_context_images(event, request)
    records = (
        event.get_extra(GROUP_IMAGES_EXTRA)
        if group
        else await storage.list_context_images()
    )
    assert len(records) == 3
    assert request.prompt.count("inspect_animation") == 2
    assert "[QQ component|QQ图片；image_ref=" in request.prompt
    assert records[0]["image_ref"] in request.prompt
    assert records[1]["image_ref"] in request.prompt
    assert records[2]["image_ref"] in request.prompt
    assert request.extra_user_content_parts == []


@pytest.mark.asyncio
async def test_quoted_image_keeps_its_reference_separate_from_current_image(
    tmp_path, adapter, environment
):
    plugin, _, storage = environment
    current, quoted = tmp_path / "current.gif", tmp_path / "quoted.gif"
    current.write_bytes(animation_bytes())
    quoted.write_bytes(animation_bytes(count=1))
    event = await make_event(
        adapter, [{"type": "image", "data": {"file": str(current)}}], group_id=None
    )
    event.message_obj.message.insert(
        0, Reply(id="previous", chain=[Image.fromFileSystem(quoted)])
    )
    await plugin.enrich_inbound_qq_components(event)
    request = ProviderRequest(
        prompt=event.message_str,
        conversation=SimpleNamespace(cid="c1"),
        image_urls=[str(quoted), str(current)],
    )
    await plugin.virtualize_context_images(event, request)
    quoted_record, current_record = await storage.list_context_images()
    assert current_record["image_ref"] in request.prompt
    assert quoted_record["image_ref"] not in request.prompt
    assert len(request.extra_user_content_parts) == 1
    assert request.extra_user_content_parts[0].text.startswith(
        f"[QQ ImageRef image_ref={quoted_record['image_ref']}, "
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "settings",
    [
        {
            "inbound": {
                "semanticize_components": False,
                "component_spoof_protection": {"enabled": False},
            }
        },
        {"context_images": {"enabled": False}},
        {"toolsets": {"disabled_operations": ["qq_media.inspect_animation"]}},
    ],
)
async def test_disabled_features_do_not_advertise_animation_operation(
    tmp_path, adapter, environment, settings
):
    plugin, _, _ = environment
    plugin.config = validate_config(settings)
    path = tmp_path / "source.gif"
    path.write_bytes(animation_bytes())
    event = await make_event(
        adapter, [{"type": "image", "data": {"file": str(path)}}], group_id=None
    )
    await plugin.enrich_inbound_qq_components(event)
    request = ProviderRequest(
        prompt=event.message_str,
        conversation=SimpleNamespace(cid="c1"),
        image_urls=[str(path)],
    )
    await plugin.virtualize_context_images(event, request)
    assert "inspect_animation" not in request.prompt
    assert all(
        "inspect_animation" not in part.text
        for part in request.extra_user_content_parts
    )
    if not plugin.config["inbound"]["semanticize_components"]:
        assert "[QQ component|" not in request.prompt
        assert request.extra_user_content_parts[0].text.startswith("[QQ ImageRef ")
    elif not plugin.config["context_images"]["enabled"]:
        assert request.prompt == "[QQ component|QQ动图]"
        assert request.extra_user_content_parts == []
    else:
        assert request.prompt.startswith("[QQ component|QQ动图；image_ref=")
        assert 'operation="inspect"' in request.prompt
        assert request.extra_user_content_parts == []


@pytest.mark.asyncio
async def test_group_animation_guide_survives_cleanup_and_later_context_injection(
    tmp_path, adapter, core, environment
):
    plugin, manager, storage = environment
    path = tmp_path / "group.gif"
    payload = animation_bytes(count=3)
    path.write_bytes(payload)
    event = await make_event(
        adapter, [{"type": "image", "data": {"file": str(path), "sub_type": 1}}] * 2
    )
    await plugin.enrich_inbound_qq_components(event)
    await plugin.cache_group_context_images(event)
    image_ref = event.get_extra(GROUP_IMAGES_EXTRA)[0]["image_ref"]
    assert event.message_str.count("inspect_animation") == 1
    assert event.message_str.count("[QQ component|QQ动态表情包") == 1
    assert "[QQ ImageRef" not in event.message_str
    assert '如需查看原图，调用 qq_media(operation="inspect"' in event.message_str
    assert f"；image_ref={image_ref}；32x24；群聊短期缓存" in event.message_str
    async for _ in core.on_message(event):
        pass
    path.unlink()
    current = await make_event(
        adapter, [{"type": "text", "data": {"text": "看看之前的动图"}}]
    )
    current.is_at_or_wake_command = True
    async for _ in core.on_message(current):
        pass
    request = ProviderRequest(
        prompt=current.message_str, conversation=SimpleNamespace(cid="c1")
    )
    await core.decorate_llm_req(current, request)
    await plugin.virtualize_context_images(current, request)
    parts = "\n".join(part.text for part in request.extra_user_content_parts)
    assert (
        f'qq_media(operation="inspect_animation", params={{"image_ref":"{image_ref}"}})'
        in parts
    )
    assert await storage.list_context_images() == []
    result = await manager.inspect_animation(current, image_ref)
    assert "采样 3 帧" in result.content[0].text
    original = await manager.inspect(current, image_ref)
    assert base64.b64decode(original.content[1].data) == payload


@pytest.mark.asyncio
async def test_runtime_dispatches_animation_preview_without_upstream_media_call(
    tmp_path,
):
    runtime, client, _ = await make_runtime(tmp_path)
    path = tmp_path / "source.gif"
    path.write_bytes(animation_bytes())
    event = FakeEvent()
    event.message_obj = SimpleNamespace(raw_message={}, message_id="456", message=[])
    request = ProviderRequest(
        conversation=SimpleNamespace(cid="c1"), image_urls=[str(path)]
    )
    await runtime.context_images.prepare_request(event, request)
    image_ref = (await runtime.storage.list_context_images())[0]["image_ref"]
    result = await runtime.execute(
        event, "qq_media", "inspect_animation", {"image_ref": image_ref}
    )
    assert isinstance(result, CallToolResult)
    assert "动画预览" in result.content[0].text
    assert all(action != "get_image" for action, _ in client.calls)

    assistant = Message(
        role="assistant",
        content=None,
        tool_calls=[
            {
                "type": "function",
                "id": "call-animation",
                "function": {
                    "name": "qq_media",
                    "arguments": '{"operation":"inspect_animation","params":{"image_ref":"'
                    + image_ref
                    + '"}}',
                },
            }
        ],
    )
    tool = Message(
        role="tool",
        tool_call_id="call-animation",
        content=result.content[0].text
        + "\n\nImage returned and cached at path='temporary.png'. Review the image below.",
    )
    attachment = Message(
        role="user",
        content=[
            TextPart(text="[Image from tool 'qq_media', path='temporary.png']"),
            ImageURLPart(
                image_url=ImageURLPart.ImageURL(
                    url="data:image/png;base64," + result.content[1].data
                )
            ),
        ],
    )
    await runtime.context_images.finalize_images(
        event, SimpleNamespace(messages=[assistant, tool, attachment])
    )
    assert tool.content == result.content[0].text
    assert attachment._no_save is True
    assert "采样 9 帧" in str(dump_messages_with_checkpoints([assistant, tool]))
    assert "temporary.png" not in str(dump_messages_with_checkpoints([assistant, tool]))
