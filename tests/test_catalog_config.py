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


@pytest.mark.parametrize(
    "config",
    [
        {"legacy_admin_list": []},
        {"confirmation": {"enabled": True}},
        {"events": {"trigger_llm": True}},
        {"platform": {"minimum_napcat_version": "4.18.19"}},
        {"toolsets": {"exposure_mode": "everything"}},
        {"permissions": {"allow_cross_group": "true"}},
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
            "permissions": {"admin_users": ["123456"]},
            "confirmation": {"ttl_seconds": 120},
        }
    )
    assert result["toolsets"]["exposure_mode"] == "compact"
    assert result["permissions"]["admin_users"] == ["123456"]
    assert result["confirmation"]["ttl_seconds"] == 120
