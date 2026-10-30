from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from astrbot.api.message_components import Plain, Reply
from astrbot.api.provider import ProviderRequest
from astrbot.core.agent.message import Message, TextPart, dump_messages_with_checkpoints
from astrbot_plugin_qq_enhance.debounce_runtime import ResumedMessageEvent
from astrbot_plugin_qq_enhance.main import MESSAGE_ID_SYSTEM_PROMPT, QQEnhancePlugin
from astrbot_plugin_qq_enhance.runtime import validate_config


@pytest.fixture
def plugin():
    plugin = object.__new__(QQEnhancePlugin)
    plugin.config = validate_config(None)
    return plugin


def make_event(message_id=123, *, group=""):
    extras = {}
    return SimpleNamespace(
        message_str="原始正文",
        message_obj=SimpleNamespace(
            message_str="原始正文",
            message=[Plain("原始正文")],
            raw_message={"post_type": "message", "message_id": message_id},
        ),
        get_platform_name=lambda: "aiocqhttp",
        get_platform_id=lambda: "qq",
        get_group_id=lambda: group,
        get_extra=extras.get,
        set_extra=extras.__setitem__,
    )


def test_message_id_tag_config_is_above_voice_and_enabled_by_default():
    schema = json.loads(
        (Path(__file__).parents[1] / "_conf_schema.json").read_text(encoding="utf-8")
    )
    groups = list(schema)
    assert groups[groups.index("voice_recognition") - 1] == "message_id_tag"
    assert schema["message_id_tag"]["items"]["enabled"]["default"] is True
    assert validate_config({})["message_id_tag"]["enabled"] is True
    assert validate_config({"message_id_tag": {"enabled": False}})[
        "message_id_tag"
    ] == {"enabled": False}
    with pytest.raises(ValueError, match="message_id_tag.enabled"):
        validate_config({"message_id_tag": {"enabled": 1}})


@pytest.mark.asyncio
@pytest.mark.parametrize("message_id", [123, -123, "-123"])
@pytest.mark.parametrize("group", ["", "30003"])
async def test_message_id_stays_with_its_own_input_in_saved_history(
    plugin, message_id, group
):
    plugin.config["inbound"]["semanticize_components"] = False
    event = make_event(message_id, group=group)
    quoted = Reply(id=456, chain=[Plain("引用正文")])
    event.message_obj.message.insert(0, quoted)
    reminder = TextPart(text="已有提醒")
    request = ProviderRequest(
        prompt="原始正文",
        system_prompt="已有系统提示词",
        extra_user_content_parts=[reminder],
        contexts=[{"role": "user", "content": "旧历史"}],
    )

    await plugin.record_group_message_id(event)
    await plugin.record_group_message_id(event)
    await plugin.add_message_id_signal(event, request)
    await plugin.add_message_id_signal(event, request)

    tag = f'<qq_message_id value="{int(message_id)}"/>'
    assert event.message_str == event.message_obj.message_str == "原始正文"
    assert event.message_obj.message[0] is quoted
    assert quoted.chain == [Plain("引用正文")]
    assert event.message_obj.message.count(Plain(tag)) == bool(group)
    assert request.prompt == "原始正文"
    assert request.system_prompt == f"已有系统提示词\n\n{MESSAGE_ID_SYSTEM_PROMPT}"
    assert request.extra_user_content_parts == [reminder, TextPart(text=tag)]

    saved = dump_messages_with_checkpoints(
        [Message.model_validate(await request.assemble_context())]
    )
    assert saved[0]["content"] == [
        {"type": "text", "text": "原始正文"},
        {"type": "text", "text": "已有提醒"},
        {"type": "text", "text": tag},
    ]

    plugin.config["message_id_tag"]["enabled"] = False
    next_request = ProviderRequest(prompt="下一条", contexts=saved)
    await plugin.add_message_id_signal(make_event(789), next_request)
    assert next_request.extra_user_content_parts == []
    assert next_request.contexts == saved


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message_id", [None, 0, "0", True, False, 1.5, "abc", "--123", "1\n2", []]
)
async def test_invalid_message_ids_are_not_exposed(plugin, message_id):
    event = make_event(message_id, group="30003")
    request = ProviderRequest(prompt=event.message_str)
    await plugin.record_group_message_id(event)
    await plugin.add_message_id_signal(event, request)
    assert event.message_obj.message == [Plain("原始正文")]
    assert request.extra_user_content_parts == []
    assert request.system_prompt == ""


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reason", ["disabled", "platform", "instance", "notice", "raw"]
)
async def test_message_id_tags_respect_scope_and_skip_notices(plugin, reason):
    event = make_event(group="30003")
    if reason == "disabled":
        plugin.config["message_id_tag"]["enabled"] = False
    elif reason == "platform":
        event.get_platform_name = lambda: "other"
    elif reason == "instance":
        plugin.config["platform"]["platform_id"] = "another-qq"
    elif reason == "notice":
        event.message_obj.raw_message["post_type"] = "notice"
    else:
        event.message_obj.raw_message = None
    request = ProviderRequest(prompt=event.message_str)
    await plugin.record_group_message_id(event)
    await plugin.add_message_id_signal(event, request)
    assert event.message_obj.message == [Plain("原始正文")]
    assert request.extra_user_content_parts == []
    assert request.system_prompt == ""


@pytest.mark.asyncio
async def test_replayed_or_absent_current_input_gets_no_new_tag(plugin):
    request = ProviderRequest(prompt=None)
    await plugin.add_message_id_signal(make_event(), request)
    await plugin.add_message_id_signal(object.__new__(ResumedMessageEvent), request)
    assert request.extra_user_content_parts == []
    assert request.system_prompt == ""
