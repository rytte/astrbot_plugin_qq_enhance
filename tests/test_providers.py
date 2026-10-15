from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

import pytest

from astrbot_plugin_qq_enhance.capabilities import operation_availability
from astrbot_plugin_qq_enhance.catalog import OPERATION_MAP, OPERATIONS
from astrbot_plugin_qq_enhance.errors import QQToolError
from astrbot_plugin_qq_enhance.providers import NAPCAT
from astrbot_plugin_qq_enhance.runtime import validate_config


def test_napcat_contract_covers_every_declared_operation() -> None:
    assert all(NAPCAT.capability(spec).supported for spec in OPERATIONS)


@pytest.mark.parametrize(
    ("operation_id", "params", "page_size", "expected"),
    [
        (
            "qq_group_info.honor",
            {"group_id": 30001, "honor_type": "talkative"},
            20,
            {"group_id": 30001, "type": "talkative"},
        ),
        (
            "qq_group_request.approve",
            {"group_id": 30001, "flag": "request", "sub_type": "add"},
            20,
            {"flag": "request", "sub_type": "add", "approve": True},
        ),
        ("qq_group_request.ignored", {"group_id": 30001}, 20, {}),
        (
            "qq_message_manage.reaction_remove",
            {"message_id": -123, "emoji_id": "1"},
            20,
            {"message_id": -123, "emoji_id": "1", "set": False},
        ),
        (
            "qq_essence.add",
            {"group_id": 30001, "message_id": -123},
            20,
            {"message_id": -123},
        ),
        (
            "qq_private_files.url",
            {"user_id": 20001, "file_id": "file-1"},
            20,
            {"file_id": "file-1"},
        ),
        (
            "qq_notice.detail",
            {"group_id": 30001, "notice_id": "notice-1"},
            20,
            {"group_id": 30001},
        ),
        ("qq_recent_contacts.list", {}, 30, {"count": 30}),
        (
            "qq_group_history.list",
            {"group_id": 30001},
            200,
            {"group_id": 30001, "message_seq": 0, "count": 100},
        ),
        (
            "qq_friend_history.list",
            {"user_id": 20001, "message_seq": 42, "count": 5},
            20,
            {"user_id": 20001, "message_seq": 42, "count": 5},
        ),
        (
            "qq_forward_get.get",
            {"message_id": -123, "depth": 2},
            20,
            {"message_id": "-123"},
        ),
        (
            "qq_forward_get.get",
            {"res_id": "forward-1", "depth": 2},
            20,
            {"message_id": "forward-1"},
        ),
    ],
)
def test_napcat_parameters_preserve_the_wire_contract(
    operation_id, params, page_size, expected
) -> None:
    original = deepcopy(params)
    spec = OPERATION_MAP[operation_id]
    action, result = NAPCAT.prepare_action(spec, params, page_size=page_size)
    assert action == spec.action
    assert result == expected
    assert params == original


def test_capability_support_is_independent_of_configuration() -> None:
    spec = OPERATION_MAP["qq_media.get_image"]
    config = validate_config({"toolsets": {"disabled_operations": [spec.operation_id]}})
    state = operation_availability(config, spec, NAPCAT)
    assert not state.configured
    assert state.supported is True
    assert not state.enabled
    assert state.disabled_reason == "disabled_by_config"

    unsupported = replace(spec, action="unregistered_action")
    state = operation_availability(validate_config(None), unsupported, NAPCAT)
    assert state.configured
    assert state.supported is False
    assert not state.enabled
    assert state.disabled_reason == "provider_unsupported"
    with pytest.raises(QQToolError, match="契约未支持"):
        NAPCAT.prepare_action(unsupported, {"file": "image"}, page_size=20)


def test_unknown_upstream_is_reported_without_claiming_support() -> None:
    state = operation_availability(
        validate_config(None), OPERATION_MAP["qq_media.get_image"]
    )
    assert state.configured
    assert state.supported is None


@pytest.mark.parametrize(
    ("operation_id", "config", "reason"),
    [
        (
            "qq_media.inspect",
            {"context_images": {"enabled": False}},
            "context_images_disabled",
        ),
        ("read_url.read", {"web_reader": {"enabled": False}}, "web_reader_disabled"),
        (
            "qq_media.get_image",
            {"toolsets": {"enabled_packs": ["group"]}},
            "pack_not_enabled",
        ),
    ],
)
def test_feature_switches_have_explicit_disabled_reasons(
    operation_id, config, reason
) -> None:
    state = operation_availability(
        validate_config(config), OPERATION_MAP[operation_id], NAPCAT
    )
    assert not state.enabled
    assert state.disabled_reason == reason
