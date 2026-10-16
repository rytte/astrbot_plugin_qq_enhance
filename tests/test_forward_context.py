from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from astrbot.api.message_components import Forward, Plain, Reply
from astrbot.api.provider import ProviderRequest
from astrbot.core.utils.quoted_message_parser import extract_quoted_message_text
from astrbot_plugin_qq_enhance.inbound import describe_inbound_event
from astrbot_plugin_qq_enhance.main import QQEnhancePlugin
from astrbot_plugin_qq_enhance.runtime import validate_config

import test_group_component_context as group_context
from test_inbound import FakeEvent

adapter = group_context.adapter
core = group_context.core
make_event = group_context.make_event


def describe(components, *, semanticize=True, max_chars=2000):
    return describe_inbound_event(
        {"post_type": "message", "message": components},
        "20002",
        semanticize_components=semanticize,
        respond_to_poke=False,
        max_components=30,
        max_chars=max_chars,
    )


@pytest.mark.parametrize("semanticize", [False, True])
@pytest.mark.parametrize("key", ["id", "resid", "res_id"])
def test_forward_entry_has_exact_read_parameters_and_no_preview(semanticize, key):
    result = describe(
        [{"type": "forward", "data": {key: "abc123", "summary": "预览内容"}}],
        semanticize=semanticize,
    )
    prefix = "[QQ component|QQ合并转发消息；" if semanticize else "[QQ ForwardRef "
    assert result == (
        f"{prefix}res_id=abc123；如需读取正文，"
        '调用 qq_forward_get(operation="get", params={"res_id":"abc123"})]'
    )
    assert "预览" not in result
    assert "message_id" not in result


@pytest.mark.parametrize("semanticize", [False, True])
@pytest.mark.parametrize(
    "resource_id",
    [None, "", True, 123, {}, "bad\nref", 'bad"ref', "bad]ref", "x" * 513],
)
def test_invalid_resource_id_never_generates_a_read_entry(semanticize, resource_id):
    result = describe(
        [{"type": "forward", "data": {"id": resource_id}}],
        semanticize=semanticize,
    )
    assert result == ("[QQ component|QQ合并转发消息]" if semanticize else "")


@pytest.mark.parametrize("semanticize", [False, True])
def test_duplicate_forward_entries_are_deduplicated_and_kept_complete(semanticize):
    component = {"type": "forward", "data": {"id": "abc123"}}
    result = describe(
        [component, component, {"type": "forward", "data": {"id": "other"}}]
        + [{"type": "face", "data": {"id": "14"}}] * 20,
        semanticize=semanticize,
        max_chars=256,
    )
    assert len(result) <= 256
    assert result.count('params={"res_id":"abc123"})]') == 1
    assert result.count('params={"res_id":"other"})]') == 1
    too_short = describe([component], semanticize=semanticize, max_chars=20)
    assert "res_id" not in too_short


@pytest.mark.parametrize("semanticize", [False, True])
@pytest.mark.parametrize("group", [False, True])
@pytest.mark.asyncio
async def test_forward_read_entry_reaches_current_prompt_without_api_calls(
    semanticize, group
):
    plugin = object.__new__(QQEnhancePlugin)
    plugin.config = validate_config(
        {
            "inbound": {
                "semanticize_components": semanticize,
                "component_spoof_protection": {"enabled": False},
            }
        }
    )
    plugin.runtime = SimpleNamespace(
        verify_platform=AsyncMock(), call_action=AsyncMock()
    )
    forward = Forward(id="abc123")
    event = FakeEvent(
        {
            "post_type": "message",
            "message_id": 123,
            "group_id": 30003 if group else None,
            "message": [{"type": "forward", "data": {"id": "abc123"}}],
        },
        messages=[forward],
    )
    await plugin.enrich_inbound_qq_components(event)

    assert 'params={"res_id":"abc123"}' in event.message_str
    assert event.message_obj.message_str == event.message_str
    assert event.get_messages()[0] is forward
    assert sum(isinstance(part, Plain) for part in event.get_messages()) == int(group)
    assert not event.is_at_or_wake_command
    plugin.runtime.verify_platform.assert_not_awaited()
    plugin.runtime.call_action.assert_not_awaited()


@pytest.mark.parametrize("semanticize", [False, True])
@pytest.mark.asyncio
async def test_forward_entry_survives_until_later_group_request(
    adapter, core, semanticize
):
    plugin = object.__new__(QQEnhancePlugin)
    plugin.config = validate_config(
        {
            "inbound": {
                "semanticize_components": semanticize,
                "component_spoof_protection": {"enabled": False},
            }
        }
    )
    earlier = await make_event(adapter, [{"type": "forward", "data": {"id": "abc123"}}])
    await plugin.enrich_inbound_qq_components(earlier)
    async for _ in core.on_message(earlier):
        pass

    current = await make_event(
        adapter, [{"type": "text", "data": {"text": "总结一下"}}]
    )
    current.is_at_or_wake_command = True
    async for _ in core.on_message(current):
        pass
    request = ProviderRequest(prompt=current.message_str)
    await core.decorate_llm_req(current, request)

    history = "\n".join(part.text for part in request.extra_user_content_parts)
    assert history.count('params={"res_id":"abc123"})]') == 1
    assert "总结一下" not in history


@pytest.mark.parametrize("semanticize", [False, True])
@pytest.mark.asyncio
async def test_quote_keeps_native_forward_expansion_without_adding_an_entry(
    semanticize,
):
    plugin = object.__new__(QQEnhancePlugin)
    plugin.config = validate_config(
        {
            "inbound": {
                "semanticize_components": semanticize,
                "component_spoof_protection": {"enabled": False},
            }
        }
    )
    reply = Reply(id="456", chain=[Forward(id="abc123")])
    event = FakeEvent(
        {"post_type": "message", "message": [{"type": "reply", "data": {"id": "456"}}]},
        message_str="总结一下",
        messages=[reply, Plain("总结一下")],
    )

    async def call_action(action, **params):
        if action == "get_msg":
            return {"message": [{"type": "forward", "data": {"id": "abc123"}}]}
        assert action == "get_forward_msg"
        assert params == {"message_id": "abc123"}
        return {
            "messages": [
                {
                    "sender": {"user_id": "10001", "nickname": "张三"},
                    "content": [{"type": "text", "data": {"text": "转发正文"}}],
                }
            ]
        }

    event.bot = SimpleNamespace(
        api=SimpleNamespace(call_action=AsyncMock(side_effect=call_action))
    )
    await plugin.enrich_inbound_qq_components(event)
    event.bot.api.call_action.assert_not_awaited()
    assert event.message_str == "总结一下"
    assert event.get_messages()[0] is reply
    assert "转发正文" in (await extract_quoted_message_text(event, reply))
    assert event.bot.api.call_action.await_count == 2
