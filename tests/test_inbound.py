from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from astrbot_plugin_qq_extension_tools.inbound import (
    describe_inbound_event,
    is_red_packet_event,
)
from astrbot_plugin_qq_extension_tools.main import QQExtensionToolsPlugin
from astrbot_plugin_qq_extension_tools.runtime import validate_config


def describe(raw_event: dict, *, self_id: str = "20002", max_chars: int = 2000) -> str:
    """Describe a test event with the production defaults.

    Args:
        raw_event: OneBot event fixture.
        self_id: Bot QQ ID.
        max_chars: Output character limit.

    Returns:
        Generated semantic text.
    """

    return describe_inbound_event(
        raw_event,
        self_id,
        semanticize_components=True,
        respond_to_poke=True,
        max_components=30,
        max_chars=max_chars,
    )


def test_face_prefers_napcat_text_then_map_and_keeps_unknown_id() -> None:
    named = describe(
        {
            "post_type": "message",
            "message": [
                {
                    "type": "face",
                    "data": {
                        "id": "14",
                        "raw": {"faceText": "/事件名称"},
                        "chainCount": 3,
                    },
                }
            ],
        }
    )
    mapped = describe(
        {
            "post_type": "message",
            "message": [
                {"type": "face", "data": {"id": "23"}},
                {
                    "type": "face",
                    "data": {"id": "49", "raw": {"faceText": None}},
                },
            ],
        }
    )
    unknown = describe(
        {
            "post_type": "message",
            "message": [{"type": "face", "data": {"id": "999"}}],
        }
    )

    assert named == "[QQ表情：事件名称，连击×3]"
    assert mapped == "[QQ表情：傲慢] [QQ表情：拥抱]"
    assert unknown == "[QQ表情：名称未知，ID 999，不要根据 ID 猜测含义]"


def test_market_face_image_and_common_components_are_described() -> None:
    result = describe(
        {
            "post_type": "message",
            "message": [
                {
                    "type": "image",
                    "data": {
                        "summary": "/拜托拜托",
                        "emoji_id": "abc",
                        "key": "key",
                    },
                },
                {
                    "type": "location",
                    "data": {
                        "lat": 39.9042,
                        "lon": 116.4074,
                        "title": "北京",
                        "content": "位置测试",
                    },
                },
                {
                    "type": "contact",
                    "data": {"type": "group", "id": "30003"},
                },
                {"type": "dice", "data": {"result": "4"}},
                {"type": "forward", "data": {"id": "forward-1"}},
            ],
        }
    )

    assert "[QQ商城表情：拜托拜托]" in result
    assert "[QQ位置：北京；位置测试；纬度 39.9042，经度 116.4074]" in result
    assert "[QQ群名片：30003]" in result
    assert "[QQ骰子：结果 4]" in result
    assert "[QQ合并转发消息]" in result


def test_rps_result_uses_ntqq_gesture_mapping() -> None:
    result = describe(
        {
            "post_type": "message",
            "message": [
                {"type": "rps", "data": {"result": "1"}},
                {"type": "rps", "data": {"result": 2}},
                {"type": "rps", "data": {"result": "3"}},
                {"type": "rps", "data": {"result": "9"}},
            ],
        }
    )

    assert "[QQ猜拳：布]" in result
    assert "[QQ猜拳：剪刀]" in result
    assert "[QQ猜拳：石头]" in result
    assert "[QQ猜拳：结果未知]" in result


def test_json_card_uses_allowlist_and_strips_url_secrets() -> None:
    card = {
        "app": "com.tencent.structmsg",
        "prompt": "[分享] 测试",
        "token": "must-not-leak",
        "meta": {
            "news": {
                "title": "分享标题",
                "desc": "分享内容",
                "jumpUrl": "https://example.com/path?token=secret#fragment",
            }
        },
    }
    result = describe(
        {
            "post_type": "message",
            "message": [{"type": "json", "data": {"data": json.dumps(card)}}],
        }
    )

    assert "QQ JSON卡片" in result
    assert "分享标题" in result
    assert "https://example.com/path" in result
    assert "must-not-leak" not in result
    assert "token=secret" not in result


def test_json_contact_cards_expose_only_validated_identity() -> None:
    group_card = {
        "app": "com.tencent.contact.lua",
        "prompt": "群名片: 示例测试群",
        "view": "contact",
        "meta": {
            "contact": {
                "contact": "30001",
                "nickname": "示例测试群",
                "tag": "群名片",
                "jumpUrl": (
                    "mqqapi://card/show_pslcard?uin=30001&card_type=group"
                    "&source=qrcode"
                ),
            }
        },
    }
    person_card = {
        "app": "com.tencent.contact.lua",
        "view": "contact",
        "meta": {
            "contact": {
                "contact": "20001",
                "nickname": "示例用户",
                "tag": "QQ号",
                "jumpUrl": (
                    "mqqapi://card/show_pslcard?uin=20001&card_type=person"
                ),
            }
        },
    }
    recommended_friend_card = {
        "app": "com.tencent.contact.lua",
        "bizsrc": "cardshare.cardshare",
        "prompt": "推荐联系人：示例联系人",
        "view": "contact",
        "meta": {
            "contact": {
                "contact": "账号：20002",
                "nickname": "示例联系人",
                "tag": "推荐好友",
                "jumpUrl": (
                    "mqqapi://card/show_pslcard?src_type=internal"
                    "&source=sharecard&version=1&uin=20002"
                ),
            }
        },
    }
    generic_card = {
        "app": "com.tencent.test",
        "view": "notification",
        "meta": {
            "contact": {
                "contact": "123456",
                "tag": "群名片",
                "jumpUrl": "mqqapi://card/show_pslcard?uin=123456&card_type=group",
            }
        },
    }

    group_result = describe(
        {
            "post_type": "message",
            "message": [{"type": "json", "data": {"data": group_card}}],
        }
    )
    person_result = describe(
        {
            "post_type": "message",
            "message": [{"type": "json", "data": {"data": person_card}}],
        }
    )
    recommended_friend_result = describe(
        {
            "post_type": "message",
            "message": [{"type": "json", "data": {"data": recommended_friend_card}}],
        }
    )
    generic_result = describe(
        {
            "post_type": "message",
            "message": [{"type": "json", "data": {"data": generic_card}}],
        }
    )

    assert group_result.startswith("[QQ群名片：群号：30001；名称：示例测试群")
    assert "mqqapi" not in group_result
    assert person_result.startswith("[QQ联系人名片：QQ号：20001；名称：示例用户")
    assert recommended_friend_result.startswith(
        "[QQ联系人名片：QQ号：20002；名称：示例联系人"
    )
    assert "mqqapi" not in recommended_friend_result
    assert "123456" not in generic_result


def test_only_targeted_poke_wakes_the_bot() -> None:
    targeted = {
        "post_type": "notice",
        "notice_type": "notify",
        "sub_type": "poke",
        "user_id": 10001,
        "target_id": 20002,
    }
    other_target = {**targeted, "target_id": 30003}
    self_poke = {**targeted, "user_id": 20002}

    assert describe(targeted) == "[QQ互动：用户 10001 戳了你]"
    assert describe(other_target) == ""
    assert describe(self_poke) == ""


def test_wallet_requires_explicit_napcat_debug_raw_marker() -> None:
    wallet = describe(
        {
            "post_type": "message",
            "message": [],
            "raw": {
                "msgType": 10,
                "elements": [{"elementType": 9, "walletElement": {}}],
            },
        }
    )
    empty = describe({"post_type": "message", "message": []})

    assert wallet == "[QQ红包消息（仅识别，不能代领）]"
    assert empty == ""


def test_structured_red_packet_card_is_detected() -> None:
    event = {
        "post_type": "message",
        "message": [
            {
                "type": "json",
                "data": {
                    "data": {
                        "app": "com.tencent.wallet",
                        "meta": {"redpacket": {"title": "恭喜发财"}},
                    }
                },
            }
        ],
    }

    assert is_red_packet_event(event, 30) is True
    assert describe(event).startswith("[QQ红包卡片（仅识别，不能代领）")


def test_output_and_component_count_are_bounded() -> None:
    event = {
        "post_type": "message",
        "message": [
            {"type": "face", "data": {"id": str(index)}} for index in range(50)
        ],
    }
    result = describe_inbound_event(
        event,
        "20002",
        semanticize_components=True,
        respond_to_poke=True,
        max_components=2,
        max_chars=30,
    )

    assert "[QQ表情：惊讶]" in result
    assert "[QQ表情：撇嘴]" in result
    assert "[QQ表情：色]" not in result
    assert len(result) <= 30


class FakeEvent:
    """Minimal AstrBot event used to exercise the plugin handler."""

    def __init__(self, raw_message: dict, message_str: str = "") -> None:
        self.message_str = message_str
        self.is_wake = False
        self.is_at_or_wake_command = False
        self.message_obj = SimpleNamespace(
            raw_message=raw_message,
            message_str=message_str,
        )

    def get_platform_name(self) -> str:
        return "aiocqhttp"

    def get_platform_id(self) -> str:
        return "platform-a"

    def get_self_id(self) -> str:
        return "20002"


@pytest.mark.asyncio
async def test_plugin_handler_updates_both_message_strings() -> None:
    plugin = object.__new__(QQExtensionToolsPlugin)
    plugin.config = validate_config(None)
    event = FakeEvent(
        {
            "post_type": "message",
            "message": [
                {
                    "type": "face",
                    "data": {"id": "14", "raw": {"faceText": "/微笑"}},
                }
            ],
        },
        "你好",
    )

    await plugin.enrich_inbound_qq_components(event)

    assert event.message_str == "你好\n[QQ表情：微笑]"
    assert event.message_obj.message_str == event.message_str
    assert event.is_at_or_wake_command is False


@pytest.mark.asyncio
async def test_plugin_handler_explicitly_wakes_for_targeted_group_poke() -> None:
    plugin = object.__new__(QQExtensionToolsPlugin)
    plugin.config = validate_config(None)
    event = FakeEvent(
        {
            "post_type": "notice",
            "notice_type": "notify",
            "sub_type": "poke",
            "user_id": 10001,
            "target_id": 20002,
            "group_id": 30003,
        }
    )

    await plugin.enrich_inbound_qq_components(event)

    assert event.message_str == "[QQ互动：用户 10001 戳了你]"
    assert event.is_wake is True
    assert event.is_at_or_wake_command is True


@pytest.mark.asyncio
async def test_plugin_handler_explicitly_wakes_for_group_red_packet() -> None:
    plugin = object.__new__(QQExtensionToolsPlugin)
    plugin.config = validate_config(None)
    event = FakeEvent(
        {
            "post_type": "message",
            "message_type": "group",
            "group_id": 30003,
            "message": [],
            "raw": {"msgType": 10, "elements": [{"elementType": 9}]},
        }
    )

    await plugin.enrich_inbound_qq_components(event)

    assert event.message_str == "[QQ红包消息（仅识别，不能代领）]"
    assert event.is_wake is True
    assert event.is_at_or_wake_command is True


@pytest.mark.asyncio
async def test_plugin_handler_honors_platform_and_feature_config() -> None:
    plugin = object.__new__(QQExtensionToolsPlugin)
    plugin.config = validate_config(
        {
            "platform": {"platform_id": "platform-b"},
            "inbound": {
                "semanticize_components": False,
                "respond_to_poke": False,
            },
        }
    )
    event = FakeEvent(
        {
            "post_type": "message",
            "message": [{"type": "face", "data": {"id": "14"}}],
        }
    )

    await plugin.enrich_inbound_qq_components(event)

    assert event.message_str == ""
    assert event.message_obj.message_str == ""
