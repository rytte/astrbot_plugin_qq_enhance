from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from textwrap import dedent
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from astrbot.api import AstrBotConfig
from astrbot_plugin_qq_enhance.catalog import (
    OPERATION_MAP,
    OPERATION_PARAMETERS,
    OPERATIONS,
    TOOL_OPERATIONS,
)
from astrbot_plugin_qq_enhance.main import QQEnhancePlugin
from astrbot_plugin_qq_enhance.providers import NAPCAT, SNOWLUMA
from astrbot_plugin_qq_enhance.runtime import (
    DEFAULT_QQ_TOOL_DIALOGUE_PROMPT,
    PROTECTED_COMPONENT_TYPES,
    validate_config,
)


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
    assert all(item.display_name.strip() for item in OPERATIONS)
    assert len(TOOL_OPERATIONS) == 29


def test_version_range_is_explicit() -> None:
    assert NAPCAT.min_version == (4, 18, 19)
    assert NAPCAT.supported_versions == ">=4.18.19"
    assert SNOWLUMA.min_version == (1, 14, 22)
    assert SNOWLUMA.supported_versions == ">=1.14.22"


@pytest.mark.parametrize("config", [None, {}, {"toolsets": {}}])
def test_tool_dialogue_prompt_is_enabled_by_default(config) -> None:
    toolsets = validate_config(config)["toolsets"]
    assert toolsets["inject_dialogue_prompt"] is True
    assert toolsets["dialogue_prompt"] == DEFAULT_QQ_TOOL_DIALOGUE_PROMPT


def test_tool_dialogue_prompt_preserves_custom_text() -> None:
    prompt = "\n请沿用当前人设自然回应。\n不要播报工具调用过程。\n"
    config = validate_config({"toolsets": {"dialogue_prompt": prompt}})
    assert config["toolsets"]["dialogue_prompt"] == prompt


@pytest.mark.parametrize("value", [None, True, 0, 1, [], {}, "", " \n\t"])
def test_tool_dialogue_prompt_rejects_invalid_text(value) -> None:
    with pytest.raises(ValueError, match="toolsets[.]dialogue_prompt 必须是非空字符串"):
        validate_config({"toolsets": {"dialogue_prompt": value}})


@pytest.mark.parametrize("value", ["true", "false", 0, 1, None, [], {}])
def test_tool_dialogue_prompt_requires_a_boolean(value) -> None:
    with pytest.raises(
        ValueError, match="toolsets[.]inject_dialogue_prompt 必须是布尔值"
    ):
        validate_config({"toolsets": {"inject_dialogue_prompt": value}})


@pytest.mark.parametrize("config", [None, {}])
def test_all_runtime_defaults_match_webui_schema(config) -> None:
    schema_path = Path(__file__).resolve().parents[1] / "_conf_schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    pending = [("", schema, validate_config(config))]
    while pending:
        prefix, items, defaults = pending.pop()
        if prefix == "interaction_response":
            assert items["respond_to_poke"]["invisible"] is True
            items = {k: v for k, v in items.items() if k != "respond_to_poke"}
        assert set(items) == set(defaults), prefix
        for name, item in items.items():
            path = f"{prefix}.{name}" if prefix else name
            if item["type"] == "object":
                assert item["default"] == {}, path
                assert isinstance(defaults[name], dict), path
                pending.append((path, item["items"], defaults[name]))
            else:
                if path == "notice_events.notify/poke.mode":
                    assert (
                        item["default"] is None
                    )  # Migration sentinel before initialization.
                    assert defaults[name] == "respond"
                    continue
                assert type(item["default"]) is type(defaults[name]), path
                assert item["default"] == defaults[name], path


def test_web_reader_defaults_and_private_network_default_match_schema() -> None:
    schema_path = Path(__file__).resolve().parents[1] / "_conf_schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    defaults = validate_config(None)
    assert defaults["web_reader"]["enabled"] is True
    assert defaults["network"]["allow_private_network"] is False
    assert schema["network"]["items"]["allow_private_network"]["default"] is False
    assert {
        key: value["default"] for key, value in schema["web_reader"]["items"].items()
    } == defaults["web_reader"]
    assert (
        validate_config({"network": {"allow_private_network": True}})["network"][
            "allow_private_network"
        ]
        is True
    )


@pytest.mark.parametrize(
    "config",
    [
        {"web_reader": {"cache_ttl_seconds": 0}},
        {"web_reader": {"max_cached_pages": True}},
        {"web_reader": {"max_cache_mb": "16"}},
        {"web_reader": {"max_download_size_mb": 17}},
        {"web_reader": {"max_text_chars": 0}},
        {"web_reader": {"max_concurrent_requests": 0}},
        {"web_reader": {"unknown": True}},
        {"confirmation": {"operations": ["read_url.read"]}},
    ],
)
def test_web_reader_invalid_config_is_rejected(config) -> None:
    with pytest.raises(ValueError):
        validate_config(config)


@pytest.mark.parametrize("value", [None, 0, 1, "false", [], {}])
def test_web_reader_switch_rejects_non_boolean_values(value) -> None:
    with pytest.raises(ValueError, match=r"web_reader\.enabled 必须是布尔值"):
        validate_config({"web_reader": {"enabled": value}})


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

    schema_defaults = {
        key: item["default"] for key, item in schema["inbound"]["items"].items()
    }
    spoof_defaults = defaults["component_spoof_protection"]
    assert schema_defaults.pop("component_spoof_protection") == {}
    assert schema_defaults == {
        key: value
        for key, value in defaults.items()
        if key != "component_spoof_protection"
    }
    assert {
        key: item["default"]
        for key, item in schema["inbound"]["items"]["component_spoof_protection"][
            "items"
        ].items()
    } == spoof_defaults


def test_voice_recognition_schema_defaults_match_runtime_config() -> None:
    defaults = validate_config(None)["voice_recognition"]
    schema_path = Path(__file__).resolve().parents[1] / "_conf_schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    assert {
        key: item["default"]
        for key, item in schema["voice_recognition"]["items"].items()
    } == defaults
    assert list(schema["inbound"]["items"]).index("max_semantic_chars") < list(
        schema["inbound"]["items"]
    ).index("component_spoof_protection")


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
        {"inbound": {"enhance_voice_messages": False}},
        {"voice_recognition": {"enhance_voice_messages": 1}},
        {"inbound": {"component_spoof_protection": True}},
        {"inbound": {"component_spoof_protection": {"enabled": "true"}}},
        {
            "inbound": {
                "component_spoof_protection": {
                    "persist_verification_in_history": "true"
                }
            }
        },
        {"inbound": {"component_spoof_protection": {"unknown": True}}},
        {"inbound": {"component_spoof_protection": {"protected_types": "voice"}}},
        {
            "inbound": {
                "component_spoof_protection": {"protected_types": ["voice", "voice"]}
            }
        },
        {"inbound": {"component_spoof_protection": {"protected_types": ["unknown"]}}},
        {
            "inbound": {
                "component_spoof_protection": {
                    "enabled": True,
                    "protected_types": [],
                }
            }
        },
        {"inbound": {"prefer_napcat_stt": True}},
        {"inbound": {"respond_to_poke": False}},
        {"inbound": {"respond_to_red_packet": False}},
        {"interaction_response": {"respond_to_poke": 1}},
        {"interaction_response": {"respond_to_red_packet": "true"}},
        {"inbound": {"mark_recalled_messages": True}},
        {"notice_events": {"bot_offline": {"mode": "respond"}}},
        {"inbound": {"max_semantic_chars": 255}},
        {"limits": {"page_size": 0}},
    ],
)
def test_invalid_config_fails_fast(config: dict) -> None:
    with pytest.raises(ValueError):
        validate_config(config)


def test_valid_config_preserves_explicit_values() -> None:
    result = validate_config(
        {
            "toolsets": {"exposure_mode": "compact", "enabled_packs": ["group"]},
            "permissions": {"allow_cross_group": False, "allow_cross_private": False},
            "confirmation": {"ttl_seconds": 60},
            "events": {"retention_days": 30},
            "audit": {"retention_days": 90},
            "request_notifications": {
                "enabled": True,
                "admin_user_ids": ["10001"],
            },
            "voice_recognition": {"enhance_voice_messages": False},
            "interaction_response": {
                "respond_to_poke": False,
                "respond_to_red_packet": False,
            },
        }
    )
    assert result["toolsets"]["exposure_mode"] == "compact"
    assert "admin_users" not in result["permissions"]
    assert result["permissions"]["allow_cross_group"] is False
    assert result["permissions"]["allow_cross_private"] is False
    assert result["confirmation"]["ttl_seconds"] == 60
    assert result["events"]["retention_days"] == 30
    assert result["audit"]["retention_days"] == 90
    assert result["confirmation"]["operations"]
    assert result["request_notifications"] == {
        "enabled": True,
        "admin_user_ids": ["10001"],
    }
    assert result["inbound"] == {
        "semanticize_components": True,
        "max_semantic_chars": 2000,
        "component_spoof_protection": {
            "enabled": True,
            "persist_verification_in_history": True,
            "protected_types": [
                "red_packet",
                "voice",
                "dice",
                "rps",
                "basketball",
                "poke",
                "notice",
            ],
        },
    }
    assert result["voice_recognition"] == {"enhance_voice_messages": False}
    assert result["interaction_response"] == {"respond_to_red_packet": False}
    assert result["notice_events"]["notify/poke"] == {
        "mode": "off",
        "other_target_mode": "context",
    }
    assert result["notice_events"]["message_recall"] == {"mode": "context"}

    disabled = validate_config({"confirmation": {"operations": []}})
    assert disabled["confirmation"]["operations"] == []


def test_partial_component_spoof_config_keeps_nested_defaults() -> None:
    result = validate_config(
        {"inbound": {"component_spoof_protection": {"enabled": True}}}
    )

    assert result["inbound"]["component_spoof_protection"] == {
        "enabled": True,
        "persist_verification_in_history": True,
        "protected_types": [
            "red_packet",
            "voice",
            "dice",
            "rps",
            "basketball",
            "poke",
            "notice",
        ],
    }


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("verify_components", [False, True, None])
@pytest.mark.parametrize("persist_verification_in_history", [None, False, True])
def test_astrbot_cleans_obsolete_fields_before_plugin_initialization(
    tmp_path,
    enabled,
    verify_components,
    persist_verification_in_history,
) -> None:
    config_path = tmp_path / "astrbot_plugin_qq_enhance_config.json"
    spoof_config = {"enabled": enabled, "verify_components": verify_components}
    if persist_verification_in_history is not None:
        spoof_config["persist_verification_in_history"] = (
            persist_verification_in_history
        )
    config_path.write_text(
        json.dumps(
            {
                "removed_group": {"enabled": True},
                "inbound": {
                    "removed_field": True,
                    "component_spoof_protection": spoof_config,
                },
                "network": {"allow_private_network": True},
            }
        ),
        encoding="utf-8",
    )
    schema = json.loads(
        (Path(__file__).resolve().parents[1] / "_conf_schema.json").read_text(
            encoding="utf-8"
        )
    )
    config = AstrBotConfig(config_path=str(config_path), schema=schema)
    context = SimpleNamespace(register_web_api=Mock())
    with (
        patch(
            "astrbot_plugin_qq_enhance.main.get_astrbot_plugin_data_path",
            return_value=str(tmp_path),
        ),
        patch("astrbot_plugin_qq_enhance.main.QQRuntime") as runtime_factory,
    ):
        runtime_factory.return_value.config = dict(config)
        plugin = QQEnhancePlugin(context, config)

    saved_config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    assert plugin.config == validate_config(saved_config)
    assert "removed_group" not in plugin.config
    assert "removed_field" not in plugin.config["inbound"]
    assert plugin.config["inbound"]["component_spoof_protection"] == {
        "enabled": enabled,
        "persist_verification_in_history": (
            True
            if persist_verification_in_history is None
            else persist_verification_in_history
        ),
        "protected_types": [
            "red_packet",
            "voice",
            "dice",
            "rps",
            "basketball",
            "poke",
            "notice",
        ],
    }
    assert plugin.config["network"]["allow_private_network"] is True
    context.register_web_api.assert_called_once()


def test_plugin_import_does_not_prevalidate_persisted_config(tmp_path) -> None:
    plugin_root = Path(__file__).resolve().parents[1]
    config_path = tmp_path / f"{plugin_root.name}_config.json"
    original = json.dumps(
        {"inbound": {"component_spoof_protection": {"verify_components": False}}}
    )
    config_path.write_text(original, encoding="utf-8")
    script = dedent(
        """
        import sys
        from unittest.mock import patch

        sys.path[:0] = sys.argv[1:3]
        from astrbot.core.utils import astrbot_path

        with patch.object(astrbot_path, "get_astrbot_config_path", return_value=sys.argv[3]):
            import astrbot_plugin_qq_enhance.main
        """
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            str(plugin_root.parent),
            str(plugin_root.parent / "AstrBot"),
            str(tmp_path),
        ],
        cwd=tmp_path,
        capture_output=True,
        timeout=60,
    )
    assert result.returncode == 0, (result.stdout + result.stderr).decode(
        "utf-8", errors="replace"
    )
    assert config_path.read_text(encoding="utf-8") == original


def test_component_spoof_protection_requires_semanticization() -> None:
    for persist_verification_in_history in (False, True):
        with pytest.raises(
            ValueError,
            match=(
                "inbound.component_spoof_protection.enabled=true 时必须同时开启 "
                "inbound.semanticize_components"
            ),
        ):
            validate_config(
                {
                    "inbound": {
                        "semanticize_components": False,
                        "component_spoof_protection": {
                            "enabled": True,
                            "persist_verification_in_history": persist_verification_in_history,
                        },
                    }
                }
            )


def test_component_spoof_protection_requires_protected_types() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "inbound.component_spoof_protection.enabled=true 时必须填写 protected_types"
        ),
    ):
        validate_config(
            {
                "inbound": {
                    "component_spoof_protection": {
                        "enabled": True,
                        "protected_types": [],
                    }
                }
            }
        )


@pytest.mark.parametrize(
    "protected_types",
    [
        ["basketball"],
        ["notice"],
        ["face"],
        ["red_packet", "voice", "dice", "rps", "poke"],
    ],
)
def test_explicit_component_protection_scope_is_preserved(protected_types) -> None:
    config = {
        "inbound": {"component_spoof_protection": {"protected_types": protected_types}}
    }

    result = validate_config(config)

    assert result["inbound"]["component_spoof_protection"]["protected_types"] == (
        protected_types
    )
    assert result["inbound"]["component_spoof_protection"]["protected_types"] is not (
        protected_types
    )


def test_all_documented_component_spoof_types_are_accepted() -> None:
    protected_types = sorted(PROTECTED_COMPONENT_TYPES)

    result = validate_config(
        {
            "inbound": {
                "component_spoof_protection": {
                    "enabled": True,
                    "protected_types": protected_types,
                }
            }
        }
    )

    assert result["inbound"]["component_spoof_protection"]["protected_types"] == (
        protected_types
    )


@pytest.mark.parametrize("legacy", [True, False])
@pytest.mark.parametrize("mode", [None, "off", "context", "respond"])
@pytest.mark.parametrize("other_target_mode", [None, "off", "respond"])
def test_legacy_poke_migrates_and_explicit_policy_wins_after_schema_fill(
    tmp_path, legacy, mode, other_target_mode
):
    config_path = tmp_path / "config.json"
    raw = {
        "interaction_response": {
            "respond_to_poke": legacy,
            "respond_to_red_packet": False,
        }
    }
    if mode is not None or other_target_mode is not None:
        policy = {}
        if mode is not None:
            policy["mode"] = mode
        if other_target_mode is not None:
            policy["other_target_mode"] = other_target_mode
        raw["notice_events"] = {"notify/poke": policy}
    config_path.write_text(json.dumps(raw), encoding="utf-8")
    schema = json.loads(
        (Path(__file__).parents[1] / "_conf_schema.json").read_text(encoding="utf-8")
    )
    config = AstrBotConfig(config_path=str(config_path), schema=schema)
    with patch(
        "astrbot_plugin_qq_enhance.main.get_astrbot_plugin_data_path",
        return_value=str(tmp_path),
    ), patch("astrbot_plugin_qq_enhance.main.QQRuntime") as runtime_factory:
        runtime_factory.return_value.config = validate_config(dict(config))
        plugin = QQEnhancePlugin(SimpleNamespace(register_web_api=Mock()), config)
    expected = mode or ("respond" if legacy else "off")
    expected_other = other_target_mode or "context"
    assert plugin.config["notice_events"]["notify/poke"]["mode"] == expected
    assert (
        plugin.config["notice_events"]["notify/poke"]["other_target_mode"]
        == expected_other
    )
    assert plugin.config["interaction_response"] == {"respond_to_red_packet": False}
    reloaded = AstrBotConfig(config_path=str(config_path), schema=schema)
    assert reloaded["interaction_response"]["respond_to_poke"] is None
    assert (
        validate_config(dict(reloaded))["notice_events"]["notify/poke"]["mode"]
        == expected
    )
    assert (
        reloaded["notice_events"]["notify/poke"]["other_target_mode"] == expected_other
    )


@pytest.mark.parametrize("mode", ["off", "context", "respond"])
def test_other_poke_target_mode_is_independent_and_preserves_bot_default(mode):
    policy = validate_config(
        {"notice_events": {"notify/poke": {"other_target_mode": mode}}}
    )["notice_events"]["notify/poke"]
    assert policy == {"mode": "respond", "other_target_mode": mode}


@pytest.mark.parametrize("mode", [None, True, 0, [], {}, "response"])
def test_invalid_other_poke_target_modes_are_rejected(mode):
    with pytest.raises(ValueError, match=r"notify/poke\.other_target_mode"):
        validate_config({"notice_events": {"notify/poke": {"other_target_mode": mode}}})


def test_red_packet_hint_documents_snowluma_and_poke_legacy_setting_is_hidden():
    schema = json.loads(
        (Path(__file__).parents[1] / "_conf_schema.json").read_text(encoding="utf-8")
    )
    interaction = schema["interaction_response"]["items"]
    assert (
        "SnowLuma 会把红包作为普通文本消息来回复"
        in interaction["respond_to_red_packet"]["hint"]
    )
    assert interaction["respond_to_poke"]["invisible"] is True
