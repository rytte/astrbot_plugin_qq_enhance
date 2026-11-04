"""Migrate stored settings before AstrBot fills new schema defaults."""

from __future__ import annotations

import json
import tempfile
from copy import deepcopy
from pathlib import Path

from astrbot.api import logger
from astrbot.core.utils.astrbot_path import (
    get_astrbot_config_path,
    get_astrbot_plugin_path,
)


def migrate_legacy_settings(config: dict, default_dialogue_prompt: str) -> dict:
    config = deepcopy(config)
    legacy_dialogue = {}
    toolsets = config.get("toolsets", {})
    if isinstance(toolsets, dict):
        if "exposure_mode" in toolsets:
            if toolsets.pop("exposure_mode") not in ("compact", "balanced", "full"):
                raise ValueError(
                    "旧版 toolsets.exposure_mode 必须是 compact、balanced 或 full"
                )
        for legacy_key, key in (
            ("inject_dialogue_prompt", "enabled"),
            ("dialogue_prompt", "prompt"),
        ):
            legacy_value = toolsets.pop(legacy_key, None)
            if legacy_value is None or (
                key == "prompt"
                and isinstance(legacy_value, str)
                and not legacy_value.strip()
            ):
                continue
            legacy_dialogue[key] = legacy_value
    dialogue = config.setdefault("dialogue", {})
    if isinstance(dialogue, dict):
        if dialogue.get("enabled", True) is None:
            dialogue.pop("enabled")
            if dialogue.get("prompt") == default_dialogue_prompt:
                dialogue.pop("prompt")
        for key, value in legacy_dialogue.items():
            # Explicit values in the new group always take precedence.
            dialogue.setdefault(key, value)
    interactions = config.get("interaction_response", {})
    if isinstance(interactions, dict):
        legacy_poke = interactions.pop("respond_to_poke", None)
        if legacy_poke is not None and type(legacy_poke) is not bool:
            raise ValueError("interaction_response.respond_to_poke 必须是布尔值")
        notices = config.setdefault("notice_events", {})
        if isinstance(notices, dict):
            poke = notices.get("notify/poke", {})
            if isinstance(poke, dict) and poke.get("mode") is None:
                notices["notify/poke"] = {
                    **poke,
                    "mode": "off" if legacy_poke is False else "respond",
                }
    return config


def migrate_config_file(config_path: Path, default_dialogue_prompt: str) -> bool:
    try:
        original = json.loads(config_path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return False
    if not isinstance(original, dict):
        return False
    groups = {key: value for key, value in original.items() if isinstance(value, dict)}
    dialogue = groups.get("dialogue", {})
    notices = groups.get("notice_events", {})
    poke = notices.get("notify/poke", {})
    legacy_values = (
        groups.get("toolsets", {}).get("inject_dialogue_prompt"),
        groups.get("toolsets", {}).get("dialogue_prompt"),
        groups.get("interaction_response", {}).get("respond_to_poke"),
    )
    if not (
        any(value is not None for value in legacy_values)
        or "exposure_mode" in groups.get("toolsets", {})
        or "enabled" in dialogue
        and dialogue["enabled"] is None
        or isinstance(poke, dict)
        and "mode" in poke
        and poke["mode"] is None
    ):
        return False
    migrated = migrate_legacy_settings(original, default_dialogue_prompt)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=config_path.parent,
            prefix=f".{config_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            json.dump(migrated, temporary, ensure_ascii=False, indent=2)
        temporary_path.replace(config_path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    logger.info("QQ 旧版配置已迁移")
    return True


def migrate_installed_config(plugin_dir: Path, default_dialogue_prompt: str) -> None:
    # Only the installed plugin owns this config; imports from a checkout do not.
    if plugin_dir.resolve().parent != Path(get_astrbot_plugin_path()).resolve():
        return
    config_path = Path(get_astrbot_config_path()) / f"{plugin_dir.name}_config.json"
    migrate_config_file(config_path, default_dialogue_prompt)
