from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from astrbot.api.message_components import Plain, Reply
from astrbot.api.provider import ProviderRequest
from astrbot.builtin_stars.astrbot.group_chat_context import GroupChatContext
from astrbot.core.agent.message import Message, TextPart, dump_messages_with_checkpoints
from astrbot_plugin_qq_enhance.debounce_runtime import ResumedMessageEvent
from astrbot_plugin_qq_enhance.main import MESSAGE_ID_SYSTEM_PROMPT, QQEnhancePlugin
from astrbot_plugin_qq_enhance.message_context import GroupMessageIdHook
from astrbot_plugin_qq_enhance.runtime import validate_config


@pytest.fixture
def plugin():
    plugin = object.__new__(QQEnhancePlugin)
    plugin.config = validate_config(None)
    return plugin


def make_event(message_id=123, *, group=""):
    extras = {}
    message = SimpleNamespace(
        message_str="原始正文",
        message=[Plain("原始正文")],
        sender=SimpleNamespace(nickname="sender"),
        raw_message={"post_type": "message", "message_id": message_id},
    )
    return SimpleNamespace(
        message_str="原始正文",
        message_obj=message,
        get_messages=lambda: message.message,
        get_self_id=lambda: "99",
        get_platform_name=lambda: "aiocqhttp",
        get_platform_id=lambda: "qq",
        get_group_id=lambda: group,
        get_extra=extras.get,
        set_extra=extras.__setitem__,
    )


@pytest.fixture
def group_message_ids(plugin):
    hook = GroupMessageIdHook(plugin)
    hook.install()
    try:
        yield hook
    finally:
        hook.close()


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

    await plugin.add_message_id_signal(event, request)
    await plugin.add_message_id_signal(event, request)

    tag = f'<qq_message_id value="{int(message_id)}"/>'
    assert event.message_str == event.message_obj.message_str == "原始正文"
    assert event.message_obj.message[0] is quoted
    assert quoted.chain == [Plain("引用正文")]
    assert event.message_obj.message == [quoted, Plain("原始正文")]
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


@pytest.mark.asyncio
@pytest.mark.parametrize("message_id", [123, -123])
async def test_group_history_tags_preserve_meme_command_input(
    plugin, group_message_ids, message_id
):
    event = make_event(message_id, group="30003")
    event.message_str = event.message_obj.message_str = "摸头"
    quoted = Reply(id=456, chain=[Plain("引用正文")])
    event.message_obj.message = [quoted, Plain("摸"), Plain("头")]
    event.set_extra(
        "activated_handlers",
        [SimpleNamespace(handler=plugin.enrich_inbound_qq_components)],
    )

    history = await GroupChatContext._format_message(
        object.__new__(GroupChatContext), event, {"image_caption": False}
    )
    request = ProviderRequest(prompt=event.message_str)
    await plugin.add_message_id_signal(event, request)

    # meme_api_python concatenates Plain segments and treats the keyword's
    # remaining text as arguments. A zero-text template must keep an empty tail.
    meme_text = "".join(
        component.text
        for component in event.get_messages()
        if isinstance(component, Plain)
    )
    match = re.match("^摸头", meme_text)
    assert match is not None
    assert meme_text[match.end() :].strip() == ""
    assert event.message_str == event.message_obj.message_str == "摸头"
    assert event.get_messages() == [quoted, Plain("摸"), Plain("头")]
    assert quoted.chain == [Plain("引用正文")]
    tag = f'<qq_message_id value="{message_id}"/>'
    assert history.count(tag) == 1
    assert request.extra_user_content_parts == [TextPart(text=tag)]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reason",
    [
        "disabled",
        "platform",
        "instance",
        "notice",
        "invalid_id",
        "private",
        "filtered_plugin",
    ],
)
async def test_group_history_id_tags_respect_scope(plugin, group_message_ids, reason):
    event = make_event(group="30003")
    event.set_extra(
        "activated_handlers",
        [SimpleNamespace(handler=plugin.enrich_inbound_qq_components)],
    )
    if reason == "disabled":
        plugin.config["message_id_tag"]["enabled"] = False
    elif reason == "platform":
        event.get_platform_name = lambda: "other"
    elif reason == "instance":
        plugin.config["platform"]["platform_id"] = "another-qq"
    elif reason == "notice":
        event.message_obj.raw_message["post_type"] = "notice"
    elif reason == "invalid_id":
        event.message_obj.raw_message["message_id"] = 0
    elif reason == "private":
        event.get_group_id = lambda: ""
    else:
        event.set_extra("activated_handlers", [])

    history = await GroupChatContext._format_message(
        object.__new__(GroupChatContext), event, {"image_caption": False}
    )
    assert "qq_message_id" not in history
    assert event.get_messages() == [Plain("原始正文")]


@pytest.mark.asyncio
async def test_group_history_formatting_keeps_concurrent_messages_separate(
    plugin, group_message_ids, monkeypatch
):
    entered = asyncio.Event()
    release = asyncio.Event()

    async def format_message(context, event, cfg):
        if event.message_obj.raw_message["message_id"] == 123:
            entered.set()
            await release.wait()
        return event.message_str

    group_message_ids.close()
    monkeypatch.setattr(GroupChatContext, "_format_message", format_message)
    group_message_ids.install()
    first = make_event(123, group="30003")
    second = make_event(456, group="30003")
    for event in (first, second):
        event.set_extra(
            "activated_handlers",
            [SimpleNamespace(handler=plugin.enrich_inbound_qq_components)],
        )
    first_task = asyncio.create_task(GroupChatContext._format_message(None, first, {}))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        second_history = await GroupChatContext._format_message(None, second, {})
    finally:
        release.set()
        first_history = await first_task
    assert first_history == '原始正文 <qq_message_id value="123"/>'
    assert second_history == '原始正文 <qq_message_id value="456"/>'
    assert first.get_messages() == second.get_messages() == [Plain("原始正文")]


@pytest.mark.asyncio
async def test_group_message_id_hook_lifecycle_preserves_other_wrappers(
    plugin, monkeypatch
):
    original = GroupChatContext._format_message
    hook = GroupMessageIdHook(plugin)
    hook.install()
    wrapper = GroupChatContext._format_message
    hook.install()
    assert GroupChatContext._format_message is wrapper
    hook.close()
    assert GroupChatContext._format_message is original

    hook.install()
    wrapper = GroupChatContext._format_message

    async def other_wrapper(context, event, cfg):
        return await wrapper(context, event, cfg)

    monkeypatch.setattr(GroupChatContext, "_format_message", other_wrapper)
    hook.close()
    assert GroupChatContext._format_message is other_wrapper
    event = make_event(group="30003")
    event.set_extra(
        "activated_handlers",
        [SimpleNamespace(handler=plugin.enrich_inbound_qq_components)],
    )
    history = await GroupChatContext._format_message(
        object.__new__(GroupChatContext), event, {"image_caption": False}
    )
    assert "qq_message_id" not in history
