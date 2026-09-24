from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiocqhttp import Event

from astrbot.api.message_components import Plain
from astrbot.api.platform import PlatformMetadata
from astrbot.api.provider import ProviderRequest
from astrbot.builtin_stars.astrbot.main import Main
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_platform_adapter import (
    AiocqhttpAdapter,
)
from astrbot_plugin_qq_enhance.main import QQEnhancePlugin
from astrbot_plugin_qq_enhance.runtime import validate_config


@pytest.fixture
def adapter():
    adapter = object.__new__(AiocqhttpAdapter)
    adapter.metadata = PlatformMetadata(
        name="aiocqhttp", description="", id="platform-a"
    )
    adapter.bot = AsyncMock()
    return adapter


@pytest.fixture
def plugin():
    plugin = object.__new__(QQEnhancePlugin)
    plugin.config = validate_config(None)
    return plugin


@pytest.fixture
def core():
    config = {
        "provider_ltm_settings": {
            "group_icl_enable": True,
            "group_message_max_cnt": 10,
            "image_caption": False,
            "active_reply": {
                "enable": False,
                "method": "possibility_reply",
                "possibility_reply": 0.0,
            },
        },
        "provider_settings": {"image_caption_prompt": ""},
    }
    return Main(
        SimpleNamespace(astrbot_config_mgr=None, get_config=lambda **_kwargs: config)
    )


async def make_event(adapter, components, *, group_id=30003, raw=None):
    payload = Event(
        {
            "post_type": "message",
            "message_type": "group" if group_id else "private",
            "message_id": 123,
            "self_id": 20002,
            "user_id": 10001,
            "sender": {"user_id": 10001, "nickname": "sender"},
            "message": components,
        }
    )
    if group_id:
        payload["group_id"] = group_id
    if raw is not None:
        payload["raw"] = raw
    return adapter.create_event(await adapter.convert_message(payload))


@pytest.mark.asyncio
@pytest.mark.parametrize("with_text", [False, True], ids=["pure", "mixed"])
@pytest.mark.parametrize(
    ("component_type", "data", "semantics"),
    [
        ("face", {"id": "14"}, "QQ表情：微笑"),
        ("dice", {"result": "4"}, "QQ骰子：结果 4"),
        ("rps", {"result": "2"}, "QQ猜拳：剪刀"),
        ("mface", {"summary": "[开心]"}, "QQ商城表情：开心"),
        ("video", {"file": "https://example.com/video.mp4"}, "视频消息"),
        (
            "file",
            {"name": "report.pdf", "url": "https://example.com/report.pdf"},
            "文件：report.pdf",
        ),
        ("forward", {"id": "forward-id"}, "QQ合并转发消息"),
        ("music", {"type": "qq", "id": "123"}, "音乐卡片：qq ID 123"),
        ("contact", {"type": "qq", "id": "10001"}, "QQ联系人名片：10001"),
        (
            "location",
            {"lat": "30", "lon": "120", "title": "meeting"},
            "QQ位置：meeting；纬度 30，经度 120",
        ),
        (
            "share",
            {"title": "article", "url": "https://example.com/article"},
            "QQ链接分享：article；https://example.com/article",
        ),
        ("json", {"data": '{"title":"card"}'}, "QQ JSON卡片：标题：card"),
        ("miniapp", {"data": '{"title":"card"}'}, "QQ小程序卡片：标题：card"),
        ("xml", {"data": '<msg brief="card"/>'}, "QQ XML卡片：card"),
        (
            "image",
            {"file": "https://example.com/image.png", "summary": "[开心]"},
            "图片描述：开心",
        ),
    ],
)
async def test_component_semantics_reach_later_group_request(
    adapter, plugin, core, component_type, data, semantics, with_text
):
    components = [{"type": component_type, "data": data}]
    if with_text:
        components.append({"type": "text", "data": {"text": "earlier-text"}})
    earlier = await make_event(adapter, components)
    original_chain = list(earlier.get_messages())

    await plugin.enrich_inbound_qq_components(earlier)
    assert earlier.is_at_or_wake_command is False
    async for _ in core.on_message(earlier):
        pass

    current = await make_event(
        adapter, [{"type": "text", "data": {"text": "what happened?"}}]
    )
    current.is_at_or_wake_command = True
    await plugin.enrich_inbound_qq_components(current)
    async for _ in core.on_message(current):
        pass

    request = ProviderRequest(prompt=current.message_str)
    await core.decorate_llm_req(current, request)
    history = "\n".join(part.text for part in request.extra_user_content_parts)
    expected = f"[QQ component|{semantics}]"
    assert history.count(expected) == 1
    assert history.count("earlier-text") == int(with_text)
    assert "what happened?" not in history
    assert earlier.message_str.count(expected) == 1
    assert earlier.get_messages()[: len(original_chain)] == original_chain


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("components", "raw"),
    [
        ([{"type": "dice", "data": {"result": "4"}}], None),
        ([{"type": "json", "data": {"data": '{"title":"红包"}'}}], None),
        ([{"type": "xml", "data": {"data": '<msg brief="红包"/>'}}], None),
        ([], {"msgType": 10, "elements": [{"walletElement": {}}]}),
    ],
    ids=["dice", "json-red-packet", "xml-red-packet", "wallet-red-packet"],
)
async def test_component_wake_receives_preceding_group_context(
    adapter, plugin, core, components, raw
):
    earlier = await make_event(
        adapter, [{"type": "text", "data": {"text": "earlier-message"}}]
    )
    async for _ in core.on_message(earlier):
        pass

    current = await make_event(adapter, components, raw=raw)
    await plugin.enrich_inbound_qq_components(current)
    if components and components[0]["type"] == "dice":
        assert current.is_at_or_wake_command is False
        current.is_at_or_wake_command = True
    else:
        assert current.is_at_or_wake_command is True
    async for _ in core.on_message(current):
        pass

    request = ProviderRequest(prompt=current.message_str)
    await core.decorate_llm_req(current, request)
    assert "earlier-message" in "\n".join(
        part.text for part in request.extra_user_content_parts
    )


@pytest.mark.asyncio
async def test_private_component_semantics_stay_in_current_prompt(adapter, plugin):
    event = await make_event(
        adapter, [{"type": "face", "data": {"id": "14"}}], group_id=None
    )
    await plugin.enrich_inbound_qq_components(event)

    assert event.message_str == "[QQ component|QQ表情：微笑]"
    assert not any(isinstance(part, Plain) for part in event.get_messages())


@pytest.mark.asyncio
async def test_disabled_semantics_do_not_add_component_history(adapter, plugin, core):
    plugin.config = validate_config(
        {
            "inbound": {
                "semanticize_components": False,
                "component_spoof_protection": {"enabled": False},
            }
        }
    )
    event = await make_event(adapter, [{"type": "face", "data": {"id": "14"}}])
    await plugin.enrich_inbound_qq_components(event)
    async for _ in core.on_message(event):
        pass

    assert not core.group_chat_context.raw_records.get(event.unified_msg_origin)
