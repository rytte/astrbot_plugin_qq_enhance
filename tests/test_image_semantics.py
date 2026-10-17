from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from aiocqhttp import Event
from PIL import Image as PillowImage

from astrbot.api.message_components import Image, Plain, Reply
from astrbot.api.platform import PlatformMetadata
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_platform_adapter import (
    AiocqhttpAdapter,
)
from astrbot_plugin_qq_enhance.image_semantics import (
    has_image_animation,
    inspect_inbound_image_animations,
)
from astrbot_plugin_qq_enhance.inbound import (
    describe_inbound_event,
    get_inbound_component_type,
)
from astrbot_plugin_qq_enhance.main import QQEnhancePlugin
from astrbot_plugin_qq_enhance.runtime import validate_config


def make_image(
    path: Path, *, image_format="GIF", frames=1, default_image=False
) -> Path:
    images = [
        PillowImage.new("RGB", (8, 8), color)
        for color in ("red", "blue", "green")[:frames]
    ]
    options = {}
    if frames > 1:
        options = {"save_all": True, "append_images": images[1:], "duration": 100}
        if default_image:
            options["default_image"] = True
    images[0].save(path, format=image_format, **options)
    return path


def describe_image(data, *, animated=None, component_type="image"):
    return describe_inbound_event(
        {"message": [{"type": component_type, "data": data}]},
        "20002",
        semanticize_components=True,
        respond_to_poke=False,
        max_components=30,
        max_chars=2000,
        image_animations={0: animated} if animated is not None else None,
    )


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ({"sub_type": 0}, "QQ图片"),
        ({"sub_type": 1}, "QQ表情包"),
        ({"sub_type": "1"}, "QQ表情包"),
        ({"subType": 1}, "QQ表情包"),
        ({"sub_type": True}, "QQ图片"),
        ({"sub_type": 1.0}, "QQ图片"),
        ({"sub_type": 99}, "QQ图片"),
        ({}, "QQ图片"),
        ({"summary": "[动画表情]", "file": "animation.gif"}, "QQ图片"),
        ({"sub_type": 1, "summary": "[收藏表情]"}, "QQ表情包"),
        ({"summary": "[开心]"}, "QQ图片：开心"),
        ({"sub_type": 1, "summary": "[开心]"}, "QQ表情包：开心"),
        ({"sub_type": 0, "emoji_id": "abc"}, "QQ商城表情：名称未知"),
        ({"sub_type": 1, "emoji_package_id": 123}, "QQ商城表情：名称未知"),
        ({"sub_type": 1, "key": "abc", "summary": "[开心]"}, "QQ商城表情：开心"),
        ({"is_animated": True, "n_frames": 99}, "QQ图片"),
    ],
)
def test_image_type_uses_protocol_fields_without_guessing_animation(data, expected):
    assert describe_image(data) == f"[QQ component|{expected}]"


@pytest.mark.parametrize(
    ("data", "animated", "expected"),
    [
        ({"sub_type": 0}, True, "QQ动图"),
        ({"sub_type": 1}, True, "QQ动态表情包"),
        ({"sub_type": 1, "summary": "[开心]"}, True, "QQ动态表情包：开心"),
        ({"emoji_id": "abc", "summary": "[开心]"}, True, "QQ商城表情：开心；动态"),
        ({"emoji_id": "abc", "summary": "[开心]"}, False, "QQ商城表情：开心"),
        ({"sub_type": 1, "summary": "[动画表情]"}, False, "QQ表情包"),
    ],
)
def test_dynamic_labels_require_verified_frames(data, animated, expected):
    assert describe_image(data, animated=animated) == f"[QQ component|{expected}]"


def test_animation_guidance_is_not_truncated_when_semantic_budget_is_small():
    kwargs = dict(
        self_id="20002",
        semanticize_components=True,
        respond_to_poke=False,
        max_components=30,
        image_animations={0: True},
        image_records={
            0: {"image_ref": "img_" + "a" * 24, "width": 8, "height": 8}
        },
    )
    raw = {"message": [{"type": "image", "data": {"summary": "长名称" * 100}}]}
    text = describe_inbound_event(raw, max_chars=256, **kwargs)
    assert "QQ动图" in text
    assert "inspect_animation" not in text
    full = describe_inbound_event(raw, max_chars=2000, **kwargs)
    assert 'operation="inspect_animation"' in full
    assert full.endswith('"})]')


def test_mface_keeps_market_type_and_image_verification_covers_stickers():
    assert describe_image({"summary": "[开心]"}, component_type="mface") == (
        "[QQ component|QQ商城表情：开心]"
    )
    assert get_inbound_component_type({"type": "image", "data": {"sub_type": 1}}) == (
        "image"
    )


@pytest.mark.parametrize(
    ("image_format", "frames", "default_image", "expected"),
    [
        ("JPEG", 1, False, False),
        ("GIF", 1, False, False),
        ("GIF", 2, False, True),
        ("WEBP", 1, False, False),
        ("WEBP", 2, False, True),
        ("PNG", 1, False, False),
        ("PNG", 2, False, True),
        ("PNG", 2, True, False),
        ("PNG", 3, True, True),
        ("TIFF", 2, False, False),
    ],
)
def test_reads_real_frames_independently_of_suffix(
    tmp_path, image_format, frames, default_image, expected
):
    path = make_image(
        tmp_path / "misleading.jpg",
        image_format=image_format,
        frames=frames,
        default_image=default_image,
    )
    assert has_image_animation(path) is expected


@pytest.mark.asyncio
async def test_raw_indices_ignore_quoted_images_and_respect_component_limit(tmp_path):
    still = make_image(tmp_path / "still.gif")
    moving = make_image(tmp_path / "moving.gif", frames=2)
    raw = {
        "message": [
            {"type": "text", "data": {"text": "caption"}},
            {"type": "image", "data": {"file": "first.gif"}},
            {"type": "reply", "data": {"id": "123"}},
            {"type": "mface", "data": {"summary": "[开心]"}},
            {"type": "image", "data": {"file": "second.gif"}},
        ]
    }
    components = [
        Plain("caption"),
        Reply(id="123", chain=[Image.fromFileSystem(moving)]),
        Image.fromFileSystem(still),
        Image.fromFileSystem(moving),
    ]
    assert await inspect_inbound_image_animations(
        raw, components, max_components=30
    ) == {
        1: False,
        4: True,
    }
    assert await inspect_inbound_image_animations(
        raw, components, max_components=4
    ) == {
        1: False,
    }


@pytest.mark.asyncio
async def test_same_prepared_file_is_inspected_once(tmp_path):
    path = make_image(tmp_path / "shared.gif", frames=2)
    raw = {"message": [{"type": "image", "data": {}}] * 2}
    components = [Image.fromFileSystem(path), Image.fromFileSystem(path)]
    with patch(
        "astrbot_plugin_qq_enhance.image_semantics.has_image_animation",
        wraps=has_image_animation,
    ) as inspect:
        result = await inspect_inbound_image_animations(
            raw, components, max_components=30
        )
    assert result == {0: True, 1: True}
    inspect.assert_called_once_with(str(path))


@pytest.mark.asyncio
async def test_file_uri_is_resolved_without_a_prepared_path(tmp_path):
    path = make_image(tmp_path / "animation with spaces.gif", frames=2)
    raw = {"message": [{"type": "image", "data": {}}]}
    assert await inspect_inbound_image_animations(
        raw, [Image(file=path.as_uri())], max_components=30
    ) == {0: True}


@pytest.mark.asyncio
async def test_dropped_image_does_not_shift_labels_even_past_component_limit(tmp_path):
    path = make_image(tmp_path / "moving.gif", frames=2)
    raw = {"message": [{"type": "image", "data": {}}] * 2}
    result = await inspect_inbound_image_animations(
        raw, [Image.fromFileSystem(path)], max_components=1
    )
    assert result == {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw",
    [
        None,
        {},
        {"message": "CQ:image"},
        {"post_type": "notice", "message": [{"type": "image", "data": {}}]},
    ],
)
async def test_missing_raw_segments_remain_unknown(raw):
    assert await inspect_inbound_image_animations(raw, [], max_components=30) == {}


@pytest.mark.asyncio
async def test_remote_sources_are_not_downloaded_for_animation_inspection():
    raw = {"message": [{"type": "image", "data": {}}]}
    with patch(
        "astrbot_plugin_qq_enhance.image_semantics.has_image_animation"
    ) as inspect:
        result = await inspect_inbound_image_animations(
            raw, [Image.fromURL("https://example.com/moving.gif")], max_components=30
        )
    assert result == {}
    inspect.assert_not_called()


async def make_event(data, path, *, group_id=None):
    adapter = object.__new__(AiocqhttpAdapter)
    adapter.metadata = PlatformMetadata(
        name="aiocqhttp", description="", id="platform-a"
    )
    adapter.bot = AsyncMock()
    payload = Event(
        {
            "post_type": "message",
            "message_type": "group" if group_id else "private",
            "message_id": 123,
            "self_id": 20002,
            "user_id": 10001,
            "sender": {"user_id": 10001, "nickname": "sender"},
            "message": [{"type": "image", "data": data}],
        }
    )
    if group_id:
        payload["group_id"] = group_id
    event = adapter.create_event(await adapter.convert_message(payload))
    event.get_messages()[0].path = str(path)
    return event


@pytest.mark.asyncio
@pytest.mark.parametrize("group_id", [None, 30003], ids=["private", "group"])
@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ({"sub_type": 0}, "QQ动图"),
        ({"sub_type": 1}, "QQ动态表情包"),
        (
            {"sub_type": 0, "emoji_id": "abc", "summary": "[开心]"},
            "QQ商城表情：开心；动态",
        ),
    ],
)
async def test_plugin_uses_prepared_files_and_keeps_visual_input(
    tmp_path, group_id, data, expected
):
    path = make_image(tmp_path / "moving.gif", frames=2)
    data = {"file": "opaque.png", "url": "https://example.com/image", **data}
    event = await make_event(data, path, group_id=group_id)
    raw_before = deepcopy(event.message_obj.raw_message)
    image = event.get_messages()[0]
    plugin = object.__new__(QQEnhancePlugin)
    plugin.config = validate_config(None)
    with patch.object(
        Image, "convert_to_file_path", new_callable=AsyncMock
    ) as download:
        await plugin.enrich_inbound_qq_components(event)
    expected_text = f"[QQ component|{expected}]"
    assert event.message_str == expected_text
    assert event.message_obj.message_str == expected_text
    assert event.get_messages()[0] is image
    assert event.message_obj.raw_message == raw_before
    assert len(event.get_messages()) == (2 if group_id else 1)
    if group_id:
        assert event.get_messages()[1] == Plain(expected_text)
    download.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", [False, True], ids=["corrupt", "missing"])
async def test_unreadable_image_keeps_sticker_type_without_claiming_static(
    tmp_path, missing
):
    path = tmp_path / "broken.gif"
    if not missing:
        path.write_bytes(b"not an image")
    event = await make_event({"file": "broken.gif", "sub_type": 1}, path)
    plugin = object.__new__(QQEnhancePlugin)
    plugin.config = validate_config(None)
    await plugin.enrich_inbound_qq_components(event)
    assert event.message_str == "[QQ component|QQ表情包]"


@pytest.mark.asyncio
async def test_disabling_semanticization_skips_image_inspection(tmp_path):
    path = make_image(tmp_path / "moving.gif", frames=2)
    event = await make_event(
        {"file": "moving.gif", "sub_type": 1}, path, group_id=30003
    )
    original_chain = list(event.get_messages())
    original_text = event.message_str
    plugin = object.__new__(QQEnhancePlugin)
    plugin.config = validate_config(
        {
            "inbound": {
                "semanticize_components": False,
                "component_spoof_protection": {"enabled": False},
            }
        }
    )
    with patch(
        "astrbot_plugin_qq_enhance.main.inspect_inbound_image_animations",
        new_callable=AsyncMock,
    ) as inspect:
        await plugin.enrich_inbound_qq_components(event)
    assert event.get_messages() == original_chain
    assert event.message_str == original_text
    inspect.assert_not_awaited()
