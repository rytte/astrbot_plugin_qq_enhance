from __future__ import annotations

import json
from pathlib import Path

import pytest

from astrbot_plugin_qq_extension_tools.catalog import (
    NAPCAT_MAX_VERSION,
    NAPCAT_MIN_VERSION,
    OPERATION_MAP,
    OPERATION_PARAMETERS,
    OPERATIONS,
    TOOL_OPERATIONS,
)
from astrbot_plugin_qq_extension_tools.runtime import validate_config


def test_catalog_is_complete_and_matches_contract() -> None:
    contract_path = (
        Path(__file__).resolve().parents[1] / "contracts" / "napcat_v4_18_19.json"
    )
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    actions = set(contract["actions"])
    assert len(OPERATION_MAP) == len(OPERATIONS)
    assert set(OPERATION_PARAMETERS) == set(OPERATION_MAP)
    assert set(TOOL_OPERATIONS) == {item.tool for item in OPERATIONS}
    assert all(item.action is None or item.action in actions for item in OPERATIONS)
    assert len(TOOL_OPERATIONS) == 26


def test_version_range_is_explicit() -> None:
    assert NAPCAT_MIN_VERSION == (4, 18, 19)
    assert NAPCAT_MAX_VERSION == (5, 0, 0)


def test_default_confirmation_operations_are_explicit() -> None:
    operations = validate_config(None)["confirmation"]["operations"]
    assert set(operations) == {
        "qq_friend_manage.delete",
        "qq_group_files.rmdir",
        "qq_group_manage.avatar",
        "qq_group_manage.leave",
        "qq_group_manage.name",
        "qq_group_manage.whole_ban",
        "qq_group_member_manage.admin",
        "qq_group_member_manage.kick",
    }
    schema_path = Path(__file__).resolve().parents[1] / "_conf_schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert schema["confirmation"]["items"]["operations"]["default"] == operations


def test_inbound_schema_defaults_match_runtime_config() -> None:
    defaults = validate_config(None)["inbound"]
    schema_path = Path(__file__).resolve().parents[1] / "_conf_schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    assert {
        key: item["default"] for key, item in schema["inbound"]["items"].items()
    } == defaults


def test_request_notification_schema_defaults_match_runtime_config() -> None:
    defaults = validate_config(None)["request_notifications"]
    schema_path = Path(__file__).resolve().parents[1] / "_conf_schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    assert {
        key: item["default"]
        for key, item in schema["request_notifications"]["items"].items()
    } == defaults


@pytest.mark.parametrize(
    "config",
    [
        {"legacy_admin_list": []},
        {"confirmation": {"enabled": True}},
        {"confirmation": {"extra_operations": []}},
        {"events": {"trigger_llm": True}},
        {"request_notifications": {"enabled": True}},
        {"request_notifications": {"admin_user_ids": ["not-a-qq-id"]}},
        {"request_notifications": {"admin_user_ids": ["0"]}},
        {"request_notifications": {"enabled": 1}},
        {"platform": {"minimum_napcat_version": "4.18.19"}},
        {"toolsets": {"exposure_mode": "everything"}},
        {"permissions": {"admin_users": []}},
        {"permissions": {"allow_cross_group": "true"}},
        {"permissions": {"cross_group_allowlist": ["30001"]}},
        {"permissions": {"cross_private_allowlist": ["10001"]}},
        {"inbound": {"semanticize_components": "true"}},
        {"inbound": {"enhance_voice_messages": 1}},
        {"inbound": {"prefer_napcat_stt": True}},
        {"inbound": {"respond_to_poke": 1}},
        {"inbound": {"respond_to_red_packet": "true"}},
        {"inbound": {"mark_recalled_messages": 1}},
        {"inbound": {"max_semantic_chars": 255}},
        {"limits": {"page_size": 0}},
        {
            "permissions": {
                "per_operation_rules": {"qq_status.login": {"disabled": False}}
            }
        },
    ],
)
def test_invalid_config_fails_fast(config: dict) -> None:
    with pytest.raises(ValueError):
        validate_config(config)


def test_valid_config_preserves_explicit_values() -> None:
    result = validate_config(
        {
            "toolsets": {"exposure_mode": "compact", "enabled_packs": ["group"]},
            "confirmation": {"ttl_seconds": 120},
            "request_notifications": {
                "enabled": True,
                "admin_user_ids": ["10001"],
            },
        }
    )
    assert result["toolsets"]["exposure_mode"] == "compact"
    assert "admin_users" not in result["permissions"]
    assert result["confirmation"]["ttl_seconds"] == 120
    assert result["confirmation"]["operations"]
    assert result["request_notifications"] == {
        "enabled": True,
        "admin_user_ids": ["10001"],
    }
    assert result["inbound"] == {
        "semanticize_components": True,
        "enhance_voice_messages": False,
        "respond_to_poke": True,
        "respond_to_red_packet": True,
        "mark_recalled_messages": False,
        "max_semantic_chars": 2000,
    }

    disabled = validate_config({"confirmation": {"operations": []}})
    assert disabled["confirmation"]["operations"] == []
