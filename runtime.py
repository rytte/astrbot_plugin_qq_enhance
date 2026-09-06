from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import ipaddress
import json
import re
import secrets
import socket
import stat
import time
from copy import deepcopy
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

import aiohttp

from astrbot.api import logger
from astrbot.api.message_components import File
from astrbot.core.utils.astrbot_path import (
    get_astrbot_plugin_data_path,
    get_astrbot_temp_path,
)

from .catalog import (
    NAPCAT_MAX_VERSION,
    NAPCAT_MIN_VERSION,
    OPERATION_MAP,
    OPERATION_PARAMETERS,
    OPERATIONS,
    TOOL_OPERATIONS,
    OperationSpec,
)
from .storage import Storage

DEFAULT_CONFIG = {
    "platform": {"platform_id": ""},
    "toolsets": {
        "exposure_mode": "balanced",
        "enabled_packs": [],
        "disabled_operations": [],
    },
    "permissions": {
        "allow_group_admin": True,
        "allow_group_owner": True,
        "allow_cross_group": False,
        "allow_cross_private": False,
    },
    "confirmation": {
        "ttl_seconds": 60,
        "operations": [
            "qq_friend_manage.delete",
            "qq_group_files.rmdir",
            "qq_group_manage.avatar",
            "qq_group_manage.leave",
            "qq_group_manage.name",
            "qq_group_manage.whole_ban",
            "qq_group_member_manage.admin",
            "qq_group_member_manage.kick",
        ],
    },
    "limits": {
        "page_size": 20,
        "max_page_size": 100,
        "max_output_chars": 12000,
        "max_forward_nodes": 30,
        "max_forward_depth": 3,
        "max_components": 30,
    },
    "files": {
        "allowed_roots": [],
        "max_file_size_mb": 100,
        "max_base64_size_mb": 10,
        "temp_ttl_seconds": 21600,
        "cleanup_interval_seconds": 600,
    },
    "network": {
        "allowed_domains": [],
        "blocked_domains": [],
        "allow_private_network": False,
        "timeout_seconds": 30,
        "max_download_size_mb": 100,
    },
    "events": {"enabled_types": [], "retention_days": 30},
    "request_notifications": {
        "enabled": False,
        "admin_user_ids": [],
    },
    "debounce": {
        "enabled": True,
        "initial_window_seconds": 0.0,
        "followup_window_seconds": 0.0,
        "max_wait_seconds": 5.0,
        "max_messages": 8,
        "max_chars": 3000,
        "max_buffer_mb": 32,
        "ignore_prefixes": ["/", "!"],
    },
    "inbound": {
        "semanticize_components": True,
        "enhance_voice_messages": True,
        "component_spoof_protection": {
            "enabled": True,
            "verify_components": True,
            "protected_types": [
                "red_packet",
                "voice",
                "dice",
                "rps",
                "poke",
            ],
        },
        "respond_to_poke": True,
        "respond_to_red_packet": True,
        "mark_recalled_messages": True,
        "max_semantic_chars": 2000,
    },
    "audit": {"retention_days": 90},
}

CONFIG_KEYS = {key: set(value) for key, value in DEFAULT_CONFIG.items()}
PROTECTED_COMPONENT_TYPES = frozenset(
    {
        "red_packet",
        "voice",
        "dice",
        "rps",
        "poke",
        "face",
        "market_face",
        "image",
        "video",
        "file",
        "music",
        "contact",
        "location",
        "share",
        "json_card",
        "miniapp",
        "xml_card",
        "forward",
        "online_file",
        "flash_transfer",
    }
)
PACKS = {item.category for item in OPERATIONS}
STATUS_CODES = {
    "online": 10,
    "leave": 30,
    "busy": 50,
    "dont_disturb": 70,
    "invisible": 40,
    "listening": 10,
    "qme": 60,
    "weather": 10,
    "meet_spring": 10,
}
STATUS_EXT_CODES = {
    "listening": 1028,
    "weather": 1030,
    "meet_spring": 2037,
}
ROLE_RANK = {"member": 1, "admin": 2, "owner": 3}
REDACTED_KEYS = {
    "cookie",
    "cookies",
    "token",
    "csrftoken",
    "accesstoken",
    "authorization",
    "base64",
    "phone",
    "phonenum",
    "phonenumber",
    "telephone",
    "mobile",
    "mobilenum",
    "mobilenumber",
    "mobilephone",
    "email",
    "emailaddress",
    "mail",
    "mailaddress",
    "buf",
    "buffer",
    "richbuf",
    "richbuffer",
    "extbuf",
    "extbuffer",
}
PATH_LIKE_IDENTIFIER_KEYS = {"folder", "folderid"}
ID_KEYS = {"group_id", "user_id", "request_id"}
INTEGER_KEYS = {
    "message_id",
    "message_seq",
    "count",
    "times",
    "duration",
    "ext_status",
    "battery_status",
    "busid",
    "page_size",
    "depth",
}
BOOLEAN_KEYS = {
    "no_cache",
    "approve",
    "enable",
    "reject_add_request",
    "is_dismiss",
    "cache",
}
MEDIA_SOURCE_KEYS = ("path", "url", "base64", "media_ref")
WINDOWS_ABSOLUTE_PATH = re.compile(r"^[A-Za-z]:[\\/]")
REQUEST_DECISION_OPERATIONS = frozenset(
    {
        "qq_friend_request.approve",
        "qq_friend_request.reject",
        "qq_group_request.approve",
        "qq_group_request.reject",
    }
)
GROUP_REQUEST_DECISION_OPERATIONS = frozenset(
    {"qq_group_request.approve", "qq_group_request.reject"}
)


class QQToolError(Exception):
    """Represent a stable error returned by QQ tools.

    Args:
        code: Stable machine-readable error code.
        message: Concise Chinese explanation.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class _ValidatedResolver(aiohttp.abc.AbstractResolver):
    """Resolve connection addresses while rejecting non-global results.

    Args:
        allow_private_network: Whether non-global addresses are explicitly allowed.
    """

    def __init__(self, allow_private_network: bool) -> None:
        self.allow_private_network = allow_private_network

    async def resolve(
        self, host: str, port: int = 0, family: socket.AddressFamily = socket.AF_UNSPEC
    ) -> list[dict[str, Any]]:
        """Resolve and validate every address returned to aiohttp.

        Args:
            host: Requested hostname.
            port: Requested TCP port.
            family: Requested socket address family.

        Returns:
            aiohttp resolver records containing only accepted addresses.

        Raises:
            OSError: If the hostname has no safe connection address.
        """

        addresses = await asyncio.get_running_loop().getaddrinfo(
            host, port, family=family, type=socket.SOCK_STREAM
        )
        result = []
        for address_family, _, protocol, _, address in addresses:
            ip_text = address[0].split("%", 1)[0]
            ip = ipaddress.ip_address(ip_text)
            if not self.allow_private_network and not ip.is_global:
                raise OSError("resolved address is not globally routable")
            result.append(
                {
                    "hostname": host,
                    "host": ip_text,
                    "port": port,
                    "family": address_family,
                    "proto": protocol,
                    "flags": socket.AI_NUMERICHOST,
                }
            )
        if not result:
            raise OSError("hostname has no usable address")
        return result

    async def close(self) -> None:
        """Close the stateless resolver."""


def validate_config(config: dict[str, Any] | None) -> dict[str, Any]:
    """Validate the plugin's only supported configuration format.

    Args:
        config: Configuration supplied by AstrBot.

    Returns:
        A validated copy with documented defaults filled for missing fields.

    Raises:
        ValueError: If any field has an unknown name, type, enum, or range.
    """

    if config is None:
        config = {}
    if not isinstance(config, dict):
        raise ValueError("插件配置必须是对象")
    unknown_top = set(config) - set(DEFAULT_CONFIG)
    if unknown_top:
        raise ValueError(f"未知配置分组: {', '.join(sorted(unknown_top))}")

    result = deepcopy(DEFAULT_CONFIG)
    for group, raw_group in config.items():
        if not isinstance(raw_group, dict):
            raise ValueError(f"配置 {group} 必须是对象")
        unknown = set(raw_group) - CONFIG_KEYS[group]
        if unknown:
            raise ValueError(f"未知配置字段 {group}: {', '.join(sorted(unknown))}")
        copied_group = deepcopy(raw_group)
        if group == "inbound" and "component_spoof_protection" in copied_group:
            spoof_config = copied_group.pop("component_spoof_protection")
            if not isinstance(spoof_config, dict):
                raise ValueError("inbound.component_spoof_protection 必须是对象")
            unknown_spoof_fields = set(spoof_config) - {
                "enabled",
                "verify_components",
                "protected_types",
            }
            if unknown_spoof_fields:
                raise ValueError(
                    "未知配置字段 inbound.component_spoof_protection: "
                    + ", ".join(sorted(unknown_spoof_fields))
                )
            result[group]["component_spoof_protection"].update(spoof_config)
        result[group].update(copied_group)

    if not isinstance(result["platform"]["platform_id"], str):
        raise ValueError("platform.platform_id 必须是字符串")
    if result["toolsets"]["exposure_mode"] not in {"compact", "balanced", "full"}:
        raise ValueError("toolsets.exposure_mode 必须是 compact、balanced 或 full")

    list_fields = (
        ("toolsets", "enabled_packs"),
        ("toolsets", "disabled_operations"),
        ("confirmation", "operations"),
        ("files", "allowed_roots"),
        ("network", "allowed_domains"),
        ("network", "blocked_domains"),
        ("events", "enabled_types"),
        ("request_notifications", "admin_user_ids"),
        ("debounce", "ignore_prefixes"),
    )
    for group, key in list_fields:
        value = result[group][key]
        if not isinstance(value, list) or any(
            not isinstance(item, str) for item in value
        ):
            raise ValueError(f"{group}.{key} 必须是字符串列表")
        if len(value) != len(set(value)):
            raise ValueError(f"{group}.{key} 不允许重复项")

    protected_types = result["inbound"]["component_spoof_protection"]["protected_types"]
    if not isinstance(protected_types, list) or any(
        not isinstance(item, str) for item in protected_types
    ):
        raise ValueError(
            "inbound.component_spoof_protection.protected_types 必须是字符串列表"
        )
    if len(protected_types) != len(set(protected_types)):
        raise ValueError(
            "inbound.component_spoof_protection.protected_types 不允许重复项"
        )
    unknown_protected_types = set(protected_types) - PROTECTED_COMPONENT_TYPES
    if unknown_protected_types:
        raise ValueError(
            "inbound.component_spoof_protection.protected_types 包含未知类型: "
            + ", ".join(sorted(unknown_protected_types))
        )

    unknown_packs = set(result["toolsets"]["enabled_packs"]) - PACKS
    if unknown_packs:
        raise ValueError(f"未知能力包: {', '.join(sorted(unknown_packs))}")
    for group, key in (
        ("toolsets", "disabled_operations"),
        ("confirmation", "operations"),
    ):
        unknown = set(result[group][key]) - set(OPERATION_MAP)
        if unknown:
            raise ValueError(
                f"{group}.{key} 包含未知操作: {', '.join(sorted(unknown))}"
            )

    bool_fields = (
        ("permissions", "allow_group_admin"),
        ("permissions", "allow_group_owner"),
        ("permissions", "allow_cross_group"),
        ("permissions", "allow_cross_private"),
        ("network", "allow_private_network"),
        ("request_notifications", "enabled"),
        ("debounce", "enabled"),
        ("inbound", "semanticize_components"),
        ("inbound", "enhance_voice_messages"),
        ("inbound", "respond_to_poke"),
        ("inbound", "respond_to_red_packet"),
        ("inbound", "mark_recalled_messages"),
    )
    for group, key in bool_fields:
        if type(result[group][key]) is not bool:
            raise ValueError(f"{group}.{key} 必须是布尔值")

    spoof_protection = result["inbound"]["component_spoof_protection"]
    if type(spoof_protection["enabled"]) is not bool:
        raise ValueError("inbound.component_spoof_protection.enabled 必须是布尔值")
    if type(spoof_protection["verify_components"]) is not bool:
        raise ValueError(
            "inbound.component_spoof_protection.verify_components 必须是布尔值"
        )
    if spoof_protection["enabled"] and not protected_types:
        raise ValueError(
            "inbound.component_spoof_protection.enabled=true 时必须填写 protected_types"
        )
    if spoof_protection["enabled"] and not result["inbound"]["semanticize_components"]:
        raise ValueError(
            "inbound.component_spoof_protection.enabled=true 时必须同时开启 "
            "inbound.semanticize_components"
        )

    ranges = {
        ("debounce", "max_messages"): (2, 100),
        ("debounce", "max_chars"): (1, 100000),
        ("debounce", "max_buffer_mb"): (1, 256),
        ("confirmation", "ttl_seconds"): (30, 300),
        ("limits", "page_size"): (1, 100),
        ("limits", "max_page_size"): (1, 200),
        ("limits", "max_output_chars"): (1000, 50000),
        ("limits", "max_forward_nodes"): (1, 100),
        ("limits", "max_forward_depth"): (1, 5),
        ("limits", "max_components"): (1, 100),
        ("files", "max_file_size_mb"): (1, 2048),
        ("files", "max_base64_size_mb"): (1, 100),
        ("files", "temp_ttl_seconds"): (600, 604800),
        ("files", "cleanup_interval_seconds"): (60, 86400),
        ("network", "timeout_seconds"): (3, 180),
        ("network", "max_download_size_mb"): (1, 2048),
        ("events", "retention_days"): (1, 365),
        ("inbound", "max_semantic_chars"): (256, 8000),
        ("audit", "retention_days"): (7, 365),
    }
    float_ranges = {
        ("debounce", "initial_window_seconds"): (0.0, 60.0),
        ("debounce", "followup_window_seconds"): (0.0, 60.0),
        ("debounce", "max_wait_seconds"): (0.0, 300.0),
    }
    for (group, key), (minimum, maximum) in float_ranges.items():
        value = result[group][key]
        if type(value) not in {int, float} or isinstance(value, bool):
            raise ValueError(f"{group}.{key} 必须是 {minimum}～{maximum} 的数字")
        if not minimum <= float(value) <= maximum:
            raise ValueError(f"{group}.{key} 必须是 {minimum}～{maximum} 的数字")
        result[group][key] = float(value)
    for (group, key), (minimum, maximum) in ranges.items():
        value = result[group][key]
        if type(value) is not int or not minimum <= value <= maximum:
            raise ValueError(f"{group}.{key} 必须是 {minimum}～{maximum} 的整数")
    if result["limits"]["page_size"] > result["limits"]["max_page_size"]:
        raise ValueError("limits.page_size 不能大于 limits.max_page_size")

    admin_user_ids = result["request_notifications"]["admin_user_ids"]
    if any(not user_id.isdecimal() or int(user_id) <= 0 for user_id in admin_user_ids):
        raise ValueError(
            "request_notifications.admin_user_ids 只能包含正整数 QQ 号字符串"
        )
    if result["request_notifications"]["enabled"] and not admin_user_ids:
        raise ValueError("request_notifications.enabled=true 时必须填写 admin_user_ids")

    resolved_roots = []
    for raw_path in result["files"]["allowed_roots"]:
        path = Path(raw_path)
        if not path.is_absolute():
            raise ValueError("files.allowed_roots 只接受绝对目录")
        try:
            resolved = path.resolve(strict=True)
        except OSError as exc:
            raise ValueError(f"files.allowed_roots 目录不存在: {raw_path}") from exc
        if not resolved.is_dir():
            raise ValueError(f"files.allowed_roots 不是目录: {raw_path}")
        resolved_roots.append(str(resolved))
    result["files"]["allowed_roots"] = resolved_roots

    for key in ("allowed_domains", "blocked_domains"):
        normalized = []
        for domain in result["network"][key]:
            domain = domain.strip().lower().rstrip(".")
            if not domain or ":" in domain or "/" in domain:
                raise ValueError(f"network.{key} 包含无效域名")
            normalized.append(domain)
        result["network"][key] = normalized
    return result


class QQRuntime:
    """Enforce the protocol, permission, confirmation, and file boundaries.

    Args:
        context: AstrBot plugin context.
        config: Validated plugin configuration.
        storage: Plugin persistence service.
    """

    def __init__(self, context: Any, config: dict[str, Any], storage: Storage) -> None:
        self.context = context
        self.config = config
        self.storage = storage
        self.temp_dir = Path(get_astrbot_temp_path()) / "qq_enhance"
        self.data_dir = (
            Path(get_astrbot_plugin_data_path()) / "astrbot_plugin_qq_enhance"
        )
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._verified_platforms: dict[str, tuple[int, int, int]] = {}

    def operation_enabled(self, operation_id: str) -> bool:
        """Check configuration-only capability availability.

        Args:
            operation_id: Global operation identifier.

        Returns:
            Whether the operation is enabled by the current configuration.
        """

        spec = OPERATION_MAP[operation_id]
        packs = self.config["toolsets"]["enabled_packs"]
        if packs and spec.category not in packs:
            return False
        if operation_id in self.config["toolsets"]["disabled_operations"]:
            return False
        return True

    def enabled_tools(self) -> set[str]:
        """Return tools with at least one enabled operation.

        Returns:
            Enabled model-visible tool names.
        """

        return {
            tool
            for tool, operations in TOOL_OPERATIONS.items()
            if any(
                self.operation_enabled(f"{tool}.{operation}")
                for operation in operations
            )
        }

    async def execute(
        self, event: Any, tool: str, operation: str, params: dict[str, Any] | None
    ) -> str:
        """Validate and execute one model-selected resource operation.

        Args:
            event: Current AstrBot message event.
            tool: Model-visible tool name.
            operation: Whitelisted operation enum value.
            params: Operation-specific parameter object.

        Returns:
            Stable JSON tool result.
        """

        started = time.monotonic()
        operation_id = f"{tool}.{operation}"
        caller_id = str(event.get_sender_id() or "")
        target_kind = "none"
        target_id = ""
        warnings: list[str] = []
        spec = OPERATION_MAP.get(operation_id)
        try:
            if spec is None or operation not in TOOL_OPERATIONS.get(tool, ()):
                raise QQToolError(
                    "invalid_parameters", f"不支持的 operation：{operation}"
                )
            if not self.operation_enabled(operation_id):
                raise QQToolError("capability_unavailable", "该 QQ 操作已被配置禁用")
            await self.verify_platform(event)
            normalized = self.validate_parameters(operation_id, params)
            if (
                operation_id in REQUEST_DECISION_OPERATIONS
                and "request_id" in normalized
            ):
                stored_request = await self.storage.get_pending_request(
                    normalized["request_id"], event.get_platform_id()
                )
                if stored_request is None:
                    raise QQToolError(
                        "target_not_found", "申请编号不存在、已处理或不属于当前平台"
                    )
                expected_type = (
                    "group"
                    if operation_id in GROUP_REQUEST_DECISION_OPERATIONS
                    else "friend"
                )
                if stored_request["request_type"] != expected_type:
                    raise QQToolError(
                        "invalid_parameters", "申请编号与当前操作类型不匹配"
                    )
                flag = str(stored_request["flag"] or "")
                if not flag:
                    raise QQToolError("response_invalid", "保存的申请缺少有效 flag")
                normalized["flag"] = flag
                if expected_type == "group":
                    group_id = str(stored_request["group_id"] or "")
                    sub_type = str(stored_request["sub_type"] or "")
                    if not group_id.isdecimal() or int(group_id) <= 0:
                        raise QQToolError(
                            "response_invalid", "保存的群申请缺少有效群号"
                        )
                    if sub_type not in {"add", "invite"}:
                        raise QQToolError("response_invalid", "保存的群申请类型无效")
                    normalized["group_id"] = int(group_id)
                    normalized["sub_type"] = sub_type
            target_kind, target_id, _ = await self.authorize(event, spec, normalized)
            action, action_params, local_result = await self.prepare_action(
                event, spec, normalized
            )
            confirmation_required = (
                spec.operation_id in self.config["confirmation"]["operations"]
            )
            params_hash = self.hash_params(action_params)
            if confirmation_required:
                pending_id = secrets.token_hex(4)
                now = int(time.time())
                summary = self.pending_summary(
                    spec, target_kind, target_id, action_params
                )
                await self.storage.create_pending(
                    {
                        "pending_id": pending_id,
                        "caller_id": caller_id,
                        "session_id": str(event.unified_msg_origin),
                        "platform_id": event.get_platform_id(),
                        "operation_id": operation_id,
                        "action": action,
                        "params": {
                            "authorization_params": normalized,
                            "action_params": action_params,
                        },
                        "target_kind": target_kind,
                        "target_id": target_id,
                        "summary": summary,
                        "created_at": now,
                        "expires_at": now + self.config["confirmation"]["ttl_seconds"],
                    }
                )
                await self.audit(
                    event,
                    spec,
                    target_kind,
                    target_id,
                    "confirmation_required",
                    "confirmation_required",
                    params_hash,
                    pending_id,
                    int((time.monotonic() - started) * 1000),
                )
                return self.dumps_result(
                    {
                        "ok": False,
                        "operation": operation_id,
                        "error": {
                            "code": "confirmation_required",
                            "message": summary,
                        },
                        "pending_id": pending_id,
                        "confirm_command": f"/qq confirm {pending_id}",
                        "expires_in": self.config["confirmation"]["ttl_seconds"],
                    }
                )

            if spec.risk != "read":
                await self.audit(
                    event,
                    spec,
                    target_kind,
                    target_id,
                    "allowed",
                    "started",
                    params_hash,
                    "",
                    0,
                )
            data = local_result
            if action is not None:
                data = await self.call_action(event, action, action_params)
                if operation_id == "qq_send_message.send" and any(
                    isinstance(component, dict)
                    and component.get("type") in {"dice", "rps"}
                    for component in normalized["components"]
                ):
                    message_id = (
                        data.get("message_id") if isinstance(data, dict) else None
                    )
                    if (
                        isinstance(message_id, (str, int))
                        and not isinstance(message_id, bool)
                        and str(message_id).lstrip("-").isdecimal()
                    ):
                        try:
                            sent_message = await self.call_action(
                                event, "get_msg", {"message_id": message_id}
                            )
                        except QQToolError as exc:
                            warnings.append(f"随机结果自动回查失败：{exc.message}")
                        else:
                            message = (
                                sent_message.get("message")
                                if isinstance(sent_message, dict)
                                else None
                            )
                            random_results = []
                            if isinstance(message, list):
                                for component in message:
                                    if not isinstance(component, dict):
                                        continue
                                    component_type = component.get("type")
                                    component_data = component.get("data")
                                    if component_type not in {
                                        "dice",
                                        "rps",
                                    } or not isinstance(component_data, dict):
                                        continue
                                    raw_result = str(
                                        component_data.get("result") or ""
                                    ).strip()
                                    if component_type == "dice":
                                        resolved_result = (
                                            raw_result
                                            if raw_result
                                            in {"1", "2", "3", "4", "5", "6"}
                                            else "未知"
                                        )
                                    else:
                                        resolved_result = {
                                            "1": "布",
                                            "2": "剪刀",
                                            "3": "石头",
                                        }.get(raw_result, "未知")
                                    random_results.append(
                                        {
                                            "type": component_type,
                                            "result": resolved_result,
                                        }
                                    )
                            if random_results:
                                data = {**data, "random_results": random_results}
                            else:
                                warnings.append(
                                    "消息已发送，但未能读取随机组件的最终结果"
                                )
                    else:
                        warnings.append(
                            "消息已发送，但响应中没有可用于回查的 message_id"
                        )
                if operation_id in {
                    "qq_group_request.list",
                    "qq_group_request.ignored",
                } and normalized.get("group_id"):
                    data = self.filter_group_data(data, int(normalized["group_id"]))
                elif operation_id == "qq_forward_get.get":
                    depth = min(
                        int(
                            normalized.get(
                                "depth", self.config["limits"]["max_forward_depth"]
                            )
                        ),
                        self.config["limits"]["max_forward_depth"],
                    )
                    data = await self.expand_forward(event, data, depth)
                elif operation_id == "qq_notice.detail":
                    data = self.select_notice(data, str(normalized["notice_id"]))
                elif operation_id in {
                    "qq_group_history.list",
                    "qq_friend_history.list",
                }:
                    data = self.compact_history_result(data)
                elif (
                    operation_id == "qq_message_get.get"
                    and isinstance(data, dict)
                    and isinstance(data.get("message"), list)
                ):
                    data = {
                        key: value
                        for key, value in data.items()
                        if key != "raw_message"
                    }
                if operation_id in REQUEST_DECISION_OPERATIONS:
                    await self.storage.update_request(
                        str(normalized["flag"]),
                        "approved" if operation == "approve" else "rejected",
                    )
            data = await self.normalize_media_result(event, spec, data)
            result = self.success_result(operation_id, data, normalized)
            if warnings:
                result["warnings"] = warnings
            await self.audit(
                event,
                spec,
                target_kind,
                target_id,
                "allowed",
                "ok",
                params_hash,
                "",
                int((time.monotonic() - started) * 1000),
            )
            return self.dumps_result(result)
        except QQToolError as exc:
            if spec is not None:
                try:
                    await self.audit(
                        event,
                        spec,
                        target_kind,
                        target_id,
                        "denied" if exc.code == "permission_denied" else "failed",
                        exc.code,
                        self.hash_params(params or {}),
                        "",
                        int((time.monotonic() - started) * 1000),
                    )
                except Exception:
                    logger.exception("Failed to persist QQ tool failure audit")
            return self.dumps_result(
                {
                    "ok": False,
                    "operation": operation_id,
                    "error": {"code": exc.code, "message": exc.message},
                }
            )
        except Exception as exc:
            logger.exception("Unexpected QQ tool failure")
            return self.dumps_result(
                {
                    "ok": False,
                    "operation": operation_id,
                    "error": {
                        "code": "internal_error",
                        "message": f"QQ 工具内部错误：{type(exc).__name__}",
                    },
                }
            )

    async def confirm(self, event: Any, pending_id: str) -> str:
        """Execute an exact pending operation after a real user command.

        Args:
            event: Current real-user message event.
            pending_id: Bound pending operation identifier.

        Returns:
            Human-readable confirmation result.
        """

        if not re.fullmatch(r"[0-9a-f]{8}", pending_id):
            return "确认编号格式无效。"
        record = await self.storage.claim_pending(
            pending_id,
            str(event.get_sender_id() or ""),
            str(event.unified_msg_origin),
            event.get_platform_id(),
        )
        if record is None:
            return "待确认操作不存在、已过期、已使用，或不属于当前用户与会话。"
        spec = OPERATION_MAP.get(record["operation_id"])
        if spec is None:
            await self.storage.finish_pending(pending_id)
            return "待确认操作已失效：插件不再支持该操作。"
        started = time.monotonic()
        try:
            if not self.operation_enabled(spec.operation_id):
                raise QQToolError("capability_unavailable", "该操作已被配置禁用")
            await self.verify_platform(event)
            stored_params = record["params"]
            authorization_params = stored_params.get("authorization_params")
            action_params = stored_params.get("action_params")
            if not isinstance(authorization_params, dict) or not isinstance(
                action_params, dict
            ):
                raise QQToolError("response_invalid", "待确认参数格式无效")
            _, target_id, _ = await self.authorize(event, spec, authorization_params)
            await self.audit(
                event,
                spec,
                record["target_kind"],
                target_id or record["target_id"],
                "confirmed",
                "started",
                record["params_hash"],
                pending_id,
                0,
            )
            if not record["action"]:
                raise QQToolError("response_invalid", "待确认操作缺少协议 action")
            await self.call_action(event, record["action"], action_params)
            await self.audit(
                event,
                spec,
                record["target_kind"],
                record["target_id"],
                "confirmed",
                "ok",
                record["params_hash"],
                pending_id,
                int((time.monotonic() - started) * 1000),
            )
            return f"已确认并执行：{record['summary']}"
        except QQToolError as exc:
            await self.audit(
                event,
                spec,
                record["target_kind"],
                record["target_id"],
                "confirmed",
                exc.code,
                record["params_hash"],
                pending_id,
                int((time.monotonic() - started) * 1000),
            )
            return f"确认后执行失败：{exc.message}"
        except Exception:
            logger.exception("Confirmed QQ operation failed unexpectedly")
            return "确认执行发生内部错误，执行状态不确定；请先核对 QQ 实际状态，不要重复操作。"
        finally:
            await self.storage.finish_pending(pending_id)

    async def verify_platform(self, event: Any) -> None:
        """Validate adapter identity and the supported NapCat version range.

        Args:
            event: Current AstrBot event.

        Raises:
            QQToolError: If platform or NapCat version is unsupported.
        """

        if event.get_platform_name() != "aiocqhttp":
            raise QQToolError("unsupported_platform", "QQ 能力增强仅支持 aiocqhttp")
        configured_id = self.config["platform"]["platform_id"]
        if configured_id and event.get_platform_id() != configured_id:
            raise QQToolError("unsupported_platform", "当前 aiocqhttp 实例未被插件授权")
        platform_id = event.get_platform_id()
        if platform_id in self._verified_platforms:
            return
        result = await self.call_action(
            event, "get_version_info", {}, skip_contract=True
        )
        if not isinstance(result, dict):
            raise QQToolError("response_invalid", "get_version_info 返回格式无效")
        implementation = str(
            result.get("app_name")
            or result.get("implementation")
            or result.get("app_full_name")
            or ""
        )
        if "napcat" not in implementation.lower():
            raise QQToolError("unsupported_version", "当前 OneBot 实现不是 NapCat")
        raw_version = str(result.get("app_version") or result.get("version") or "")
        match = re.search(r"(\d+)\.(\d+)\.(\d+)", raw_version)
        if not match:
            raise QQToolError("response_invalid", "无法识别 NapCat 版本号")
        version = tuple(int(part) for part in match.groups())
        if version < NAPCAT_MIN_VERSION or version >= NAPCAT_MAX_VERSION:
            raise QQToolError(
                "unsupported_version",
                "仅支持 NapCat >=4.18.19,<5.0.0，当前版本为 " + raw_version,
            )
        self._verified_platforms[platform_id] = version

    def validate_parameters(
        self, operation_id: str, params: dict[str, Any] | None
    ) -> dict[str, Any]:
        """Reject missing, unknown, or ill-typed operation parameters.

        Args:
            operation_id: Global operation identifier.
            params: Untrusted model arguments.

        Returns:
            Normalized parameter dictionary.

        Raises:
            QQToolError: If the object does not match the operation contract.
        """

        if params is None:
            params = {}
        if not isinstance(params, dict):
            raise QQToolError("invalid_parameters", "params 必须是对象")
        rule = OPERATION_PARAMETERS[operation_id]
        unknown = set(params) - rule.allowed
        if unknown:
            raise QQToolError(
                "invalid_parameters",
                "当前 operation 不接受参数：" + "、".join(sorted(unknown)),
            )
        missing = [
            key
            for key in rule.required
            if key not in params or params[key] is None or params[key] == ""
        ]
        if missing:
            raise QQToolError(
                "invalid_parameters", "缺少必填参数：" + "、".join(missing)
            )
        normalized = deepcopy(params)
        for key, value in list(normalized.items()):
            if key in ID_KEYS:
                if (
                    isinstance(value, bool)
                    or not str(value).isdigit()
                    or int(value) <= 0
                ):
                    raise QQToolError("invalid_parameters", f"{key} 必须是正整数")
                normalized[key] = int(value)
            elif key in INTEGER_KEYS:
                if isinstance(value, bool):
                    raise QQToolError("invalid_parameters", f"{key} 必须是整数")
                try:
                    normalized[key] = int(value)
                except (TypeError, ValueError, OverflowError) as exc:
                    raise QQToolError(
                        "invalid_parameters", f"{key} 必须是整数"
                    ) from exc
            elif key in BOOLEAN_KEYS and type(value) is not bool:
                raise QQToolError("invalid_parameters", f"{key} 必须是布尔值")
        if (
            "page_size" in normalized
            and not 1
            <= normalized["page_size"]
            <= self.config["limits"]["max_page_size"]
        ):
            raise QQToolError("invalid_parameters", "page_size 超出配置上限")
        if "count" in normalized and not 1 <= normalized["count"] <= 100:
            raise QQToolError("invalid_parameters", "count 必须在 1～100 之间")
        if "times" in normalized and not 1 <= normalized["times"] <= 10:
            raise QQToolError("invalid_parameters", "times 必须在 1～10 之间")
        if "duration" in normalized and not 0 <= normalized["duration"] <= 2592000:
            raise QQToolError("invalid_parameters", "duration 必须在 0～2592000 秒之间")
        if operation_id.endswith("set_online_status"):
            status = normalized["status"]
            if isinstance(status, str):
                if status not in STATUS_CODES:
                    raise QQToolError(
                        "invalid_parameters",
                        "status 必须是 " + "、".join(STATUS_CODES),
                    )
                normalized["status"] = STATUS_CODES[status]
                normalized.setdefault("ext_status", STATUS_EXT_CODES.get(status, 0))
            elif type(status) is not int or status not in STATUS_CODES.values():
                raise QQToolError("invalid_parameters", "status 状态码无效")
            normalized.setdefault("ext_status", 0)
            normalized.setdefault("battery_status", 0)
        if (
            "status" in normalized
            and operation_id
            in {
                "qq_friend_request.list",
                "qq_group_request.list",
            }
            and normalized["status"] not in {"pending", "approved", "rejected"}
        ):
            raise QQToolError(
                "invalid_parameters", "status 必须是 pending、approved 或 rejected"
            )
        if "sub_type" in normalized and normalized["sub_type"] not in {
            "add",
            "invite",
        }:
            raise QQToolError("invalid_parameters", "sub_type 必须是 add 或 invite")
        if operation_id in REQUEST_DECISION_OPERATIONS:
            has_request_id = "request_id" in normalized
            direct_fields = (
                ("group_id", "flag", "sub_type")
                if operation_id in GROUP_REQUEST_DECISION_OPERATIONS
                else ("flag",)
            )
            supplied_direct_fields = [
                key for key in direct_fields if normalized.get(key) not in (None, "")
            ]
            if has_request_id and supplied_direct_fields:
                raise QQToolError(
                    "invalid_parameters", "request_id 不能与底层申请参数混用"
                )
            if not has_request_id:
                missing_direct_fields = [
                    key for key in direct_fields if normalized.get(key) in (None, "")
                ]
                if missing_direct_fields:
                    raise QQToolError(
                        "invalid_parameters",
                        "必须提供 request_id，或完整提供：" + "、".join(direct_fields),
                    )
        if "honor_type" in normalized and normalized["honor_type"] not in {
            "talkative",
            "performer",
            "legend",
            "strong_newbie",
            "emotion",
            "all",
        }:
            raise QQToolError("invalid_parameters", "honor_type 枚举值无效")
        if "out_format" in normalized and normalized["out_format"] not in {
            "mp3",
            "amr",
            "wma",
            "m4a",
            "spx",
            "ogg",
            "wav",
            "flac",
        }:
            raise QQToolError("invalid_parameters", "out_format 枚举值无效")
        if operation_id in {"qq_media.get_record", "qq_media.convert_record"}:
            file_ref = normalized["file"]
            if not isinstance(file_ref, str) or not file_ref.strip():
                raise QQToolError("invalid_parameters", "file 必须是非空字符串")
            file_ref = file_ref.strip()
            normalized["file"] = file_ref
            if Path(file_ref).is_absolute() or WINDOWS_ABSOLUTE_PATH.match(file_ref):
                raise QQToolError(
                    "invalid_parameters",
                    "file 必须是 OneBot/NapCat 原始媒体标识，不能使用 AstrBot "
                    "本地临时路径",
                )
        if any(key in rule.allowed for key in MEDIA_SOURCE_KEYS):
            supplied = [
                key
                for key in MEDIA_SOURCE_KEYS
                if normalized.get(key) not in (None, "")
            ]
            if len(supplied) != 1:
                raise QQToolError(
                    "invalid_parameters",
                    "必须且只能提供 path、url、base64、media_ref 中的一项",
                )
        if operation_id == "qq_send_message.send":
            if not isinstance(normalized["target"], dict) or not isinstance(
                normalized["components"], list
            ):
                raise QQToolError(
                    "invalid_parameters", "target 必须是对象且 components 必须是数组"
                )
        if operation_id == "qq_send_forward.send":
            if not isinstance(normalized["target"], dict) or not isinstance(
                normalized["nodes"], list
            ):
                raise QQToolError(
                    "invalid_parameters", "target 必须是对象且 nodes 必须是数组"
                )
        if operation_id == "qq_forward_get.get":
            references = [
                key
                for key in ("message_id", "res_id")
                if normalized.get(key) not in (None, "")
            ]
            if len(references) != 1:
                raise QQToolError(
                    "invalid_parameters",
                    "必须且只能提供 message_id、res_id 中的一项",
                )
            if "res_id" in normalized and not isinstance(normalized["res_id"], str):
                raise QQToolError("invalid_parameters", "res_id 必须是字符串")
        return normalized

    async def authorize(
        self, event: Any, spec: OperationSpec, params: dict[str, Any]
    ) -> tuple[str, str, bool]:
        """Apply caller, target scope, QQ role, and bot role authorization.

        Args:
            event: Current AstrBot event.
            spec: Whitelisted operation declaration.
            params: Normalized operation parameters.

        Returns:
            Target kind, target ID, and cross-session flag.

        Raises:
            QQToolError: If any authorization boundary cannot be proven.
        """

        caller_id = str(event.get_sender_id() or "")
        if not caller_id:
            raise QQToolError("permission_denied", "无法识别调用者 ID")
        is_admin = event.is_admin()
        current_group = str(event.get_group_id() or "")
        is_private = event.is_private_chat()
        target_kind = spec.target_kind
        target_id = ""
        if spec.tool in {"qq_send_message", "qq_send_forward"}:
            target = params.get("target", {})
            target_type = target.get("type")
            if target_type == "current":
                target_kind = "group" if current_group else "private"
                target_id = current_group or caller_id
            elif target_type in {"group", "private", "temporary"}:
                target_kind = "group" if target_type == "group" else "private"
                target_id = str(target.get("id") or "")
                if not target_id.isdigit() or int(target_id) <= 0:
                    raise QQToolError("invalid_parameters", "target.id 必须是正整数 ID")
            else:
                raise QQToolError(
                    "invalid_parameters",
                    "target.type 必须是 current、group、private 或 temporary",
                )
        elif target_kind == "group":
            target_id = str(params.get("group_id") or current_group)
        elif target_kind == "private":
            target_id = str(params.get("user_id") or (caller_id if is_private else ""))

        cross_session = False
        if target_kind == "group":
            cross_session = not current_group or target_id != current_group
            if cross_session:
                if spec.operation_id == "qq_group_request.list":
                    allowed = is_admin and (
                        is_private or self.config["permissions"]["allow_cross_group"]
                    )
                    if not allowed:
                        raise QQToolError(
                            "permission_denied",
                            "全部群申请查询仅允许 AstrBot 管理员发起；"
                            "从群聊跨群查询时需开启跨群操作",
                        )
                else:
                    allowed = (
                        is_admin and self.config["permissions"]["allow_cross_group"]
                    )
                    if not allowed:
                        raise QQToolError(
                            "permission_denied",
                            "跨群操作仅允许开启该权限的 AstrBot 管理员发起",
                        )
                    group_invite_decision = (
                        spec.operation_id in GROUP_REQUEST_DECISION_OPERATIONS
                        and params.get("sub_type") == "invite"
                    )
                    if not group_invite_decision and not await self.target_exists(
                        event, "group", target_id
                    ):
                        raise QQToolError(
                            "target_not_found", "目标群不在机器人群列表中"
                        )
        elif target_kind == "private":
            cross_session = not is_private or target_id != caller_id
            if cross_session:
                if spec.operation_id == "qq_user_info.stranger":
                    allowed = is_admin and (
                        is_private or self.config["permissions"]["allow_cross_private"]
                    )
                    if not allowed:
                        raise QQToolError(
                            "permission_denied",
                            "非好友公开资料查询仅允许 AstrBot 管理员发起；"
                            "从群聊查询时需开启跨好友操作",
                        )
                else:
                    allowed = (
                        is_admin and self.config["permissions"]["allow_cross_private"]
                    )
                    if not allowed:
                        raise QQToolError(
                            "permission_denied",
                            "跨好友操作仅允许开启该权限的 AstrBot 管理员发起",
                        )
                    if not await self.target_exists(event, "private", target_id):
                        raise QQToolError(
                            "target_not_found", "目标用户不在机器人好友列表中"
                        )

        if spec.permission == "astrbot_admin" and not is_admin:
            raise QQToolError("permission_denied", "该操作仅允许 AstrBot 管理员")
        caller_role = "member"
        if spec.permission in {"group_admin", "group_owner"} and not is_admin:
            if not current_group or target_id != current_group:
                raise QQToolError("permission_denied", "该群管理操作只能作用于当前群")
            caller_role = await self.group_role(
                event, int(current_group), int(caller_id)
            )
            if spec.permission == "group_admin":
                allowed = (
                    caller_role == "admin"
                    and self.config["permissions"]["allow_group_admin"]
                ) or (
                    caller_role == "owner"
                    and self.config["permissions"]["allow_group_owner"]
                )
            else:
                allowed = (
                    caller_role == "owner"
                    and self.config["permissions"]["allow_group_owner"]
                )
            if not allowed:
                raise QQToolError("permission_denied", "调用者的当前群角色不足")

        group_invite_decision = (
            spec.operation_id in GROUP_REQUEST_DECISION_OPERATIONS
            and params.get("sub_type") == "invite"
        )
        if spec.bot_role != "member" and not group_invite_decision:
            if not target_id:
                raise QQToolError("permission_denied", "无法确定目标群")
            self_id = str(event.get_self_id() or "")
            if not self_id.isdigit():
                login = await self.call_action(
                    event, "get_login_info", {}, skip_contract=True
                )
                self_id = str(login.get("user_id") if isinstance(login, dict) else "")
            if not self_id.isdigit():
                raise QQToolError("permission_denied", "无法验证机器人 QQ 角色")
            bot_role = await self.group_role(event, int(target_id), int(self_id))
            if ROLE_RANK.get(bot_role, 0) < ROLE_RANK[spec.bot_role]:
                raise QQToolError("permission_denied", "机器人在目标群中的实际权限不足")

        if (
            not is_admin
            and caller_role in {"admin", "owner"}
            and spec.tool == "qq_group_member_manage"
            and "user_id" in params
        ):
            member_role = await self.group_role(
                event, int(target_id), int(params["user_id"])
            )
            if ROLE_RANK.get(member_role, 0) >= ROLE_RANK[caller_role]:
                raise QQToolError(
                    "permission_denied", "不能操作群角色不低于调用者的成员"
                )
        return target_kind, target_id, cross_session

    async def prepare_action(
        self, event: Any, spec: OperationSpec, params: dict[str, Any]
    ) -> tuple[str | None, dict[str, Any], Any]:
        """Convert validated resource parameters into exact OneBot parameters.

        Args:
            event: Current AstrBot event.
            spec: Whitelisted operation declaration.
            params: Validated operation parameters.

        Returns:
            Action name, exact action parameters, and optional local result.
        """

        operation_id = spec.operation_id
        action = spec.action
        action_params = deepcopy(params)
        if operation_id in REQUEST_DECISION_OPERATIONS:
            action_params.pop("request_id", None)
        local_result: Any = None
        cursor = action_params.pop("cursor", None)
        page_size = action_params.pop("page_size", self.config["limits"]["page_size"])
        if operation_id == "qq_status.capabilities":
            local_result = [
                {
                    "operation": item.operation_id,
                    "action": item.action,
                    "risk": item.risk,
                    "permission": item.permission,
                }
                for item in OPERATIONS
                if self.operation_enabled(item.operation_id)
            ]
        elif operation_id == "qq_friend_request.list":
            local_result = await self.storage.list_requests(
                "friend",
                str(action_params.pop("status", "pending")),
                self.config["limits"]["max_page_size"],
            )
        elif operation_id == "qq_group_request.list":
            action_params.pop("group_id", None)
        elif operation_id == "qq_private_files.url" and not action_params.get(
            "file_id"
        ):
            message_components = getattr(event.message_obj, "message", [])
            attachment = next(
                (
                    component
                    for component in reversed(message_components)
                    if isinstance(component, File) and component.url
                ),
                None,
            )
            if attachment is None:
                raise QQToolError(
                    "target_not_found",
                    "当前私聊没有带 QQ 下载地址的文件附件，请提供 file_id",
                )
            action = None
            action_params = {}
            local_result = [
                {
                    "file_name": attachment.name or "file",
                    "url": attachment.url,
                }
            ]
        elif operation_id == "qq_send_message.send":
            action, action_params = await self.prepare_message(event, action_params)
        elif operation_id == "qq_send_forward.send":
            action, action_params = await self.prepare_forward(event, action_params)
        else:
            if operation_id == "qq_account_manage.set_avatar":
                action_params = {
                    "file": str(await self.resolve_input_file(event, action_params))
                }
            elif operation_id in {
                "qq_group_manage.avatar",
                "qq_group_files.upload",
                "qq_private_files.upload",
                "qq_media.ocr",
            }:
                path = await self.resolve_input_file(event, action_params)
                for key in MEDIA_SOURCE_KEYS:
                    action_params.pop(key, None)
                action_params["image" if operation_id == "qq_media.ocr" else "file"] = (
                    str(path)
                )
            if operation_id == "qq_account_manage.set_online_status":
                pass
            elif operation_id == "qq_group_info.honor":
                action_params["type"] = action_params.pop("honor_type", "all")
            elif operation_id == "qq_friend_request.approve":
                action_params["approve"] = True
            elif operation_id == "qq_friend_request.reject":
                action_params["approve"] = False
            elif operation_id == "qq_group_request.approve":
                action_params.pop("group_id", None)
                action_params["approve"] = True
            elif operation_id == "qq_group_request.reject":
                action_params.pop("group_id", None)
                action_params["approve"] = False
            elif operation_id == "qq_message_manage.reaction_add":
                action_params["set"] = True
            elif operation_id == "qq_message_manage.reaction_remove":
                action_params["set"] = False
            elif operation_id in {"qq_essence.add", "qq_essence.remove"}:
                action_params.pop("group_id", None)
            elif operation_id == "qq_private_files.url":
                action_params.pop("user_id", None)
            elif operation_id == "qq_notice.detail":
                action_params.pop("notice_id", None)
            elif operation_id == "qq_notice.send":
                image = action_params.get("image")
                if image:
                    if not isinstance(image, dict):
                        raise QQToolError(
                            "invalid_parameters", "image 必须是媒体来源对象"
                        )
                    action_params["image"] = str(
                        await self.resolve_input_file(event, image)
                    )
            elif (
                operation_id == "qq_recent_contacts.list"
                and "count" not in action_params
            ):
                action_params["count"] = page_size
            elif operation_id in {
                "qq_group_history.list",
                "qq_friend_history.list",
            }:
                action_params.setdefault("message_seq", 0)
                action_params.setdefault("count", min(page_size, 100))
            elif operation_id == "qq_forward_get.get":
                action_params.pop("depth", None)
                reference = action_params.pop("message_id", None)
                if reference is None:
                    reference = action_params.pop("res_id")
                action_params["message_id"] = str(reference)
            elif operation_id == "qq_group_request.ignored":
                action_params.pop("group_id", None)
        if local_result is not None:
            local_result = self.paginate(local_result, cursor, page_size)
        return action, action_params, local_result

    async def prepare_message(
        self, event: Any, params: dict[str, Any]
    ) -> tuple[str, dict[str, Any]]:
        """Build an explicit OneBot message chain from validated components.

        Args:
            event: Current AstrBot event.
            params: Target and component parameters.

        Returns:
            Send action and exact OneBot parameters.
        """

        target = params["target"]
        components = params["components"]
        if not components or len(components) > self.config["limits"]["max_components"]:
            raise QQToolError("invalid_parameters", "components 数量为空或超过配置上限")
        if len(components) != 1 and any(
            isinstance(component, dict) and component.get("type") == "music"
            for component in components
        ):
            raise QQToolError(
                "invalid_parameters",
                "音乐卡片必须作为唯一组件单独发送",
            )
        if len(components) != 1 and any(
            isinstance(component, dict) and component.get("type") == "share"
            for component in components
        ):
            raise QQToolError(
                "invalid_parameters",
                "分享卡片必须作为唯一组件单独发送",
            )
        message = []
        allowed_fields = {
            "text": {"type", "text"},
            "image": {"type", *MEDIA_SOURCE_KEYS, "summary", "sub_type"},
            "record": {"type", *MEDIA_SOURCE_KEYS},
            "video": {"type", *MEDIA_SOURCE_KEYS},
            "file": {"type", *MEDIA_SOURCE_KEYS, "name"},
            "at": {"type", "id"},
            "reply": {"type", "id"},
            "face": {"type", "id"},
            "dice": {"type"},
            "rps": {"type"},
            "share": {"type", "url", "title", "content", "image"},
            "music": {
                "type",
                "music_type",
                "id",
                "url",
                "audio",
                "title",
                "content",
                "image",
                "query",
                "artist",
            },
            "contact": {"type", "contact_type", "id"},
            "location": {"type", "lat", "lon", "title", "content"},
            "json": {"type", "data"},
        }
        required_fields = {
            "text": {"text"},
            "share": {"url", "title"},
            "music": {"music_type"},
            "at": {"id"},
            "reply": {"id"},
            "face": {"id"},
            "contact": {"contact_type", "id"},
            "location": {"lat", "lon"},
            "json": {"data"},
        }
        for index, component in enumerate(components):
            if not isinstance(component, dict):
                raise QQToolError(
                    "invalid_parameters", f"components[{index}] 必须是对象"
                )
            component_type = component.get("type")
            if component_type not in allowed_fields:
                raise QQToolError(
                    "invalid_parameters", f"components[{index}].type 不受支持"
                )
            unknown = set(component) - allowed_fields[component_type]
            missing = required_fields.get(component_type, set()) - set(component)
            if unknown or missing:
                raise QQToolError(
                    "invalid_parameters",
                    f"components[{index}] 字段无效，unknown={sorted(unknown)}, missing={sorted(missing)}",
                )
            if component_type in {"image", "record", "video", "file"}:
                path = await self.resolve_input_file(event, component)
                data = {"file": str(path)}
                for key in ("summary", "sub_type", "name"):
                    if key in component:
                        data[key] = component[key]
                message.append({"type": component_type, "data": data})
            elif component_type == "text":
                message.append(
                    {"type": "text", "data": {"text": str(component["text"])}}
                )
            elif component_type in {"at", "reply", "face"}:
                data_key = {"at": "qq", "reply": "id", "face": "id"}[component_type]
                message.append(
                    {"type": component_type, "data": {data_key: str(component["id"])}}
                )
            elif component_type in {"dice", "rps"}:
                message.append({"type": component_type, "data": {}})
            elif component_type == "share":
                invalid = [
                    key
                    for key in ("url", "title", "content", "image")
                    if key in component and not isinstance(component[key], str)
                ]
                if invalid:
                    raise QQToolError(
                        "invalid_parameters",
                        "分享卡片字段必须是字符串：" + "、".join(invalid),
                    )
                url = component["url"].strip()
                title = component["title"].strip()
                content = str(component.get("content") or "").strip()
                image = str(component.get("image") or "").strip()
                if not url or not title:
                    raise QQToolError(
                        "invalid_parameters",
                        "分享卡片的 url 和 title 不能为空",
                    )
                if (
                    len(url) > 4096
                    or len(image) > 4096
                    or len(title) > 200
                    or len(content) > 2000
                ):
                    raise QQToolError(
                        "invalid_parameters",
                        "分享卡片字段超过长度上限",
                    )
                await self.validate_url(url, resolve_dns=False)
                if image:
                    await self.validate_url(image, resolve_dns=False)
                news = {
                    "title": title,
                    "desc": content,
                    "jumpUrl": url,
                    "preview": image,
                    "tag": "链接分享",
                }
                encoded = json.dumps(
                    {
                        "app": "com.tencent.structmsg",
                        "config": {"autosize": 1, "forward": 1, "type": "normal"},
                        "desc": "新闻",
                        "meta": {"news": news},
                        "prompt": f"[分享] {title}",
                        "ver": "0.0.0.1",
                        "view": "news",
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                message.append({"type": "json", "data": {"data": encoded}})
            elif component_type == "music":
                music_type = component["music_type"]
                id_types = {"qq", "163", "kugou", "kuwo", "migu"}
                if not isinstance(music_type, str):
                    raise QQToolError(
                        "invalid_parameters",
                        "music.music_type 必须是字符串",
                    )
                if music_type == "qq_search":
                    unexpected = [
                        key
                        for key in (
                            "id",
                            "url",
                            "audio",
                            "title",
                            "content",
                            "image",
                        )
                        if component.get(key) not in (None, "")
                    ]
                    if unexpected:
                        raise QQToolError(
                            "invalid_parameters",
                            "qq_search 音乐组件不能提供解析结果字段："
                            + "、".join(unexpected),
                        )
                    query = component.get("query")
                    artist = component.get("artist")
                    if not isinstance(query, str) or not query.strip():
                        raise QQToolError(
                            "invalid_parameters",
                            "qq_search 音乐组件必须提供有效 query",
                        )
                    if len(query.strip()) > 100:
                        raise QQToolError(
                            "invalid_parameters",
                            "qq_search.query 不能超过 100 个字符",
                        )
                    if artist is not None and (
                        not isinstance(artist, str) or not artist.strip()
                    ):
                        raise QQToolError(
                            "invalid_parameters",
                            "qq_search.artist 必须是非空字符串",
                        )
                    data = await self.resolve_qq_music(
                        query.strip(), artist.strip() if artist else None
                    )
                elif music_type == "custom":
                    if component.get("id") not in (None, ""):
                        raise QQToolError(
                            "invalid_parameters",
                            "custom 音乐组件不能提供 id",
                        )
                    if component.get("query") not in (None, "") or component.get(
                        "artist"
                    ) not in (None, ""):
                        raise QQToolError(
                            "invalid_parameters",
                            "custom 音乐组件不能提供 query 或 artist",
                        )
                    invalid = [
                        key
                        for key in ("url", "audio", "title", "content", "image")
                        if component.get(key) is not None
                        and not isinstance(component[key], str)
                    ]
                    if invalid:
                        raise QQToolError(
                            "invalid_parameters",
                            "custom 音乐组件字段必须是字符串：" + "、".join(invalid),
                        )
                    missing = [
                        key
                        for key in ("url", "image")
                        if not isinstance(component.get(key), str)
                        or not component[key].strip()
                    ]
                    if missing:
                        raise QQToolError(
                            "invalid_parameters",
                            "custom 音乐组件缺少有效字段：" + "、".join(missing),
                        )
                    data = {
                        key: value for key, value in component.items() if key != "type"
                    }
                    data["type"] = data.pop("music_type")
                elif music_type in id_types:
                    music_id = component.get("id")
                    if (
                        isinstance(music_id, bool)
                        or not isinstance(music_id, (str, int))
                        or not str(music_id).strip()
                    ):
                        raise QQToolError(
                            "invalid_parameters",
                            "平台音乐组件必须提供有效 id",
                        )
                    raw_music_id = str(music_id).strip()
                    current_message = str(getattr(event, "message_str", "") or "")
                    if not re.search(
                        rf"(?<![A-Za-z0-9]){re.escape(raw_music_id)}(?![A-Za-z0-9])",
                        current_message,
                    ):
                        raise QQToolError(
                            "invalid_parameters",
                            "平台音乐 ID 必须由用户在当前消息中明确提供；"
                            "按歌名点歌必须使用 qq_search",
                        )
                    unexpected = [
                        key
                        for key in (
                            "url",
                            "audio",
                            "title",
                            "content",
                            "image",
                            "query",
                            "artist",
                        )
                        if component.get(key) not in (None, "")
                    ]
                    if unexpected:
                        raise QQToolError(
                            "invalid_parameters",
                            "平台音乐组件不能提供自定义字段：" + "、".join(unexpected),
                        )
                    data = {
                        key: value for key, value in component.items() if key != "type"
                    }
                    data["type"] = data.pop("music_type")
                else:
                    raise QQToolError(
                        "invalid_parameters",
                        "music.music_type 必须是 qq_search、qq、163、kugou、kuwo、migu 或 custom",
                    )
                for key in ("url", "audio", "image"):
                    if data.get(key):
                        await self.validate_url(str(data[key]))
                message.append({"type": "music", "data": data})
            elif component_type == "contact":
                if component["contact_type"] not in {"qq", "group"}:
                    raise QQToolError(
                        "invalid_parameters", "contact.contact_type 必须是 qq 或 group"
                    )
                message.append(
                    {
                        "type": "contact",
                        "data": {
                            "type": component["contact_type"],
                            "id": str(component["id"]),
                        },
                    }
                )
            elif component_type == "location":
                try:
                    latitude = float(component["lat"])
                    longitude = float(component["lon"])
                except (TypeError, ValueError, OverflowError) as exc:
                    raise QQToolError(
                        "invalid_parameters", "location.lat/lon 必须是数字"
                    ) from exc
                if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
                    raise QQToolError(
                        "invalid_parameters", "location.lat/lon 超出有效范围"
                    )
                message.append(
                    {
                        "type": "location",
                        "data": {
                            **{
                                key: value
                                for key, value in component.items()
                                if key not in {"type", "lat", "lon"}
                            },
                            "lat": latitude,
                            "lon": longitude,
                        },
                    }
                )
            elif component_type == "json":
                encoded = (
                    component["data"]
                    if isinstance(component["data"], str)
                    else json.dumps(component["data"], ensure_ascii=False)
                )
                if len(encoded) > 65536:
                    raise QQToolError("invalid_parameters", "json 组件超过 64 KiB")
                message.append({"type": "json", "data": {"data": encoded}})
            else:
                data = {key: value for key, value in component.items() if key != "type"}
                message.append({"type": component_type, "data": data})
        if len(json.dumps(message, ensure_ascii=False, default=str)) > 262144:
            raise QQToolError("invalid_parameters", "结构化消息超过 256 KiB")
        target_type = target["type"]
        if target_type == "current":
            if event.get_group_id():
                return "send_group_msg", {
                    "group_id": int(event.get_group_id()),
                    "message": message,
                }
            return "send_private_msg", {
                "user_id": int(event.get_sender_id()),
                "message": message,
            }
        if target_type == "group":
            return "send_group_msg", {"group_id": int(target["id"]), "message": message}
        action_params = {"user_id": int(target["id"]), "message": message}
        if target_type == "temporary":
            group_id = str(target.get("group_id") or "")
            if not group_id.isdigit() or int(group_id) <= 0:
                raise QQToolError(
                    "invalid_parameters", "temporary target.group_id 必须是正整数"
                )
            action_params["group_id"] = int(group_id)
        return "send_private_msg", action_params

    async def resolve_qq_music(self, query: str, artist: str | None) -> dict[str, str]:
        """Resolve an exact QQ Music title to a custom music card payload.

        Args:
            query: Exact song title requested by the user.
            artist: Optional artist name used to disambiguate results.

        Returns:
            OneBot custom music data backed by verified QQ Music metadata.

        Raises:
            QQToolError: If the search fails or has no exact matching result.
        """

        search_url = "https://c.y.qq.com/soso/fcgi-bin/client_search_cp"
        await self.validate_url(search_url)
        timeout = aiohttp.ClientTimeout(total=self.config["network"]["timeout_seconds"])
        connector = aiohttp.TCPConnector(resolver=_ValidatedResolver(False))
        try:
            async with aiohttp.ClientSession(
                timeout=timeout, trust_env=False, connector=connector
            ) as session:
                async with session.get(
                    search_url,
                    params={
                        "w": f"{query} {artist or ''}".strip(),
                        "p": 1,
                        "n": 10,
                        "format": "json",
                    },
                    headers={
                        "User-Agent": "Mozilla/5.0",
                        "Referer": "https://y.qq.com/",
                    },
                    allow_redirects=False,
                ) as response:
                    if response.status != 200:
                        raise QQToolError(
                            "network_error",
                            f"QQ 音乐搜索返回 HTTP {response.status}",
                        )
                    body = await response.content.read(1048577)
        except QQToolError:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            raise QQToolError("network_error", "QQ 音乐搜索请求失败") from exc
        if len(body) > 1048576:
            raise QQToolError("response_invalid", "QQ 音乐搜索响应过大")
        try:
            payload = json.loads(body)
            songs = payload["data"]["song"]["list"]
        except (KeyError, TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise QQToolError("response_invalid", "QQ 音乐搜索响应格式无效") from exc
        if not isinstance(songs, list):
            raise QQToolError("response_invalid", "QQ 音乐搜索结果不是列表")

        normalized_query = query.casefold()
        normalized_artist = artist.casefold() if artist else None
        for song in songs:
            if not isinstance(song, dict):
                continue
            title = str(song.get("songname") or "").strip()
            song_mid = str(song.get("songmid") or "").strip()
            album_mid = str(song.get("albummid") or "").strip()
            raw_singers = song.get("singer")
            singer_names = (
                [
                    str(singer.get("name") or "").strip()
                    for singer in raw_singers
                    if isinstance(singer, dict) and singer.get("name")
                ]
                if isinstance(raw_singers, list)
                else []
            )
            if title.casefold() != normalized_query:
                continue
            if normalized_artist and not any(
                normalized_artist == name.casefold() for name in singer_names
            ):
                continue
            if not re.fullmatch(r"[A-Za-z0-9]+", song_mid) or not re.fullmatch(
                r"[A-Za-z0-9]+", album_mid
            ):
                continue
            song_url = f"https://y.qq.com/n/ryqq/songDetail/{song_mid}"
            return {
                "type": "custom",
                "url": song_url,
                "audio": song_url,
                "title": title,
                "content": "/".join(singer_names) or "QQ音乐",
                "image": (
                    "https://y.gtimg.cn/music/photo_new/"
                    f"T002R300x300M000{album_mid}.jpg"
                ),
            }
        detail = f"，歌手为“{artist}”" if artist else ""
        raise QQToolError(
            "target_not_found",
            f"未找到歌名完全匹配“{query}”{detail}的 QQ 音乐；不得改用猜测的歌曲 ID",
        )

    async def prepare_forward(
        self, event: Any, params: dict[str, Any]
    ) -> tuple[str, dict[str, Any]]:
        """Build bounded OneBot forward nodes.

        Args:
            event: Current AstrBot event.
            params: Target and node parameters.

        Returns:
            Forward send action and exact parameters.
        """

        nodes = params["nodes"]
        if not nodes or len(nodes) > self.config["limits"]["max_forward_nodes"]:
            raise QQToolError("invalid_parameters", "nodes 数量为空或超过配置上限")
        built_nodes = []
        for index, node in enumerate(nodes):
            if not isinstance(node, dict):
                raise QQToolError("invalid_parameters", f"nodes[{index}] 必须是对象")
            if set(node) == {"message_id"}:
                built_nodes.append(
                    {"type": "node", "data": {"id": str(node["message_id"])}}
                )
                continue
            unknown_fields = set(node) - {"sender_id", "sender_name", "components"}
            if unknown_fields:
                names = "、".join(sorted(unknown_fields))
                raise QQToolError(
                    "invalid_parameters",
                    f"nodes[{index}] 包含未知字段：{names}；节点只能使用 message_id，"
                    "或 sender_id、sender_name、components",
                )
            if not {"sender_id", "sender_name", "components"} <= set(node):
                raise QQToolError(
                    "invalid_parameters",
                    f'nodes[{index}] 必须是 {{"message_id":正整数}}，或同时提供 '
                    "sender_id、sender_name、components",
                )
            _, prepared = await self.prepare_message(
                event, {"target": {"type": "current"}, "components": node["components"]}
            )
            built_nodes.append(
                {
                    "type": "node",
                    "data": {
                        "uin": str(node["sender_id"]),
                        "name": str(node["sender_name"]),
                        "content": prepared["message"],
                    },
                }
            )
        target = params["target"]
        target_type = target.get("type")
        if target_type == "current":
            if event.get_group_id():
                return "send_group_forward_msg", {
                    "group_id": int(event.get_group_id()),
                    "messages": built_nodes,
                }
            return "send_private_forward_msg", {
                "user_id": int(event.get_sender_id()),
                "messages": built_nodes,
            }
        if target_type == "group":
            return "send_group_forward_msg", {
                "group_id": int(target["id"]),
                "messages": built_nodes,
            }
        if target_type != "private":
            raise QQToolError("invalid_parameters", "合并转发不支持 temporary 目标")
        return "send_private_forward_msg", {
            "user_id": int(target["id"]),
            "messages": built_nodes,
        }

    async def call_action(
        self,
        event: Any,
        action: str,
        params: dict[str, Any],
        *,
        skip_contract: bool = False,
    ) -> Any:
        """Call one explicitly permitted OneBot action with normalized errors.

        Args:
            event: Current AstrBot event.
            action: Exact OneBot action name.
            params: Exact validated parameters.
            skip_contract: Allow internal version and role probes.

        Returns:
            OneBot response data.

        Raises:
            QQToolError: If the action is unavailable, times out, or is rejected.
        """

        contract_actions = {item.action for item in OPERATIONS if item.action}
        internal_actions = {
            "get_version_info",
            "get_login_info",
            "get_group_member_info",
            "get_group_list",
            "get_friend_list",
            "fetch_ptt_text",
        }
        send_actions = {
            "send_group_msg",
            "send_private_msg",
            "send_group_forward_msg",
            "send_private_forward_msg",
        }
        if action not in contract_actions | send_actions and not (
            skip_contract and action in internal_actions
        ):
            raise QQToolError("capability_unavailable", f"action 未登记：{action}")
        platform = self.context.get_platform_inst(event.get_platform_id())
        if platform is None:
            raise QQToolError("unsupported_platform", "找不到当前平台实例")
        client = platform.get_client()
        call_action = getattr(client, "call_action", None)
        if not callable(call_action):
            raise QQToolError(
                "capability_unavailable", "当前平台客户端不支持 call_action"
            )
        try:
            result = await asyncio.wait_for(
                call_action(action, **params),
                timeout=self.config["network"]["timeout_seconds"],
            )
        except asyncio.TimeoutError as exc:
            raise QQToolError("timeout", f"QQ action {action} 调用超时") from exc
        except Exception as exc:
            name = type(exc).__name__
            if name == "ApiNotAvailable":
                code = "capability_unavailable"
            elif name in {"NetworkError", "ClientConnectionError"}:
                code = "network_error"
            else:
                code = "protocol_rejected"
            message = str(exc).strip()
            raise QQToolError(
                code, f"QQ action {action} 失败：{message or name}"
            ) from exc
        if isinstance(result, dict) and "retcode" in result:
            if result.get("retcode") not in (0, None):
                raise QQToolError(
                    "protocol_rejected",
                    f"QQ action {action} 被拒绝：retcode={result.get('retcode')}",
                )
            if "data" in result:
                return result["data"]
        return result

    async def group_role(self, event: Any, group_id: int, user_id: int) -> str:
        """Query and validate a QQ member role.

        Args:
            event: Current AstrBot event.
            group_id: Target group ID.
            user_id: Member QQ ID.

        Returns:
            ``member``, ``admin``, or ``owner``.

        Raises:
            QQToolError: If the role cannot be proven.
        """

        result = await self.call_action(
            event,
            "get_group_member_info",
            {"group_id": group_id, "user_id": user_id, "no_cache": True},
            skip_contract=True,
        )
        role = str(result.get("role") if isinstance(result, dict) else "")
        if role not in ROLE_RANK:
            raise QQToolError("permission_denied", "无法验证 QQ 群角色")
        return role

    async def target_exists(self, event: Any, target_kind: str, target_id: str) -> bool:
        """Verify that a configured cross-session target really exists.

        Args:
            event: Current AstrBot event.
            target_kind: ``group`` or ``private``.
            target_id: Exact target ID.

        Returns:
            Whether the target appears in the bot's current list.
        """

        action = "get_group_list" if target_kind == "group" else "get_friend_list"
        result = await self.call_action(event, action, {}, skip_contract=True)
        if isinstance(result, dict):
            for key in ("data", "items", "groups", "friends"):
                if isinstance(result.get(key), list):
                    result = result[key]
                    break
        if not isinstance(result, list):
            return False
        id_key = "group_id" if target_kind == "group" else "user_id"
        return any(
            isinstance(item, dict) and str(item.get(id_key, "")) == target_id
            for item in result
        )

    async def resolve_input_file(self, event: Any, source: dict[str, Any]) -> Path:
        """Resolve one controlled local, URL, Base64, or media-ref input.

        Args:
            event: Current AstrBot event.
            source: Object containing exactly one media source field.

        Returns:
            Safe local regular file path.

        Raises:
            QQToolError: If the source violates path, network, type, or size limits.
        """

        supplied = [
            key for key in MEDIA_SOURCE_KEYS if source.get(key) not in (None, "")
        ]
        if len(supplied) != 1:
            raise QQToolError(
                "invalid_parameters",
                "必须且只能提供 path、url、base64、media_ref 中的一项",
            )
        key = supplied[0]
        if key == "media_ref":
            path = await self.storage.resolve_media_ref(
                str(source[key]), str(event.get_sender_id() or "")
            )
            if path is None or not path.is_file():
                raise QQToolError(
                    "target_not_found", "media_ref 不存在、已过期或不属于调用者"
                )
            return path.resolve(strict=True)
        if key == "path":
            path = Path(str(source[key]))
            if not path.is_absolute():
                raise QQToolError("invalid_parameters", "path 必须是绝对路径")
            try:
                resolved = path.resolve(strict=True)
            except OSError as exc:
                raise QQToolError("target_not_found", "本地文件不存在") from exc
            roots = [
                Path(get_astrbot_temp_path()).resolve(strict=False),
                self.data_dir.resolve(strict=False),
                *[
                    Path(item).resolve(strict=False)
                    for item in self.config["files"]["allowed_roots"]
                ],
            ]
            if not any(resolved == root or root in resolved.parents for root in roots):
                raise QQToolError("permission_denied", "本地文件不在允许目录内")
            try:
                mode = resolved.stat().st_mode
            except OSError as exc:
                raise QQToolError("target_not_found", "无法读取本地文件") from exc
            if not stat.S_ISREG(mode):
                raise QQToolError("invalid_parameters", "path 必须指向普通文件")
            if (
                resolved.stat().st_size
                > self.config["files"]["max_file_size_mb"] * 1048576
            ):
                raise QQToolError("invalid_parameters", "本地文件超过配置大小上限")
            return resolved
        if key == "url":
            return await self.download_url(
                str(source[key]), str(event.get_sender_id() or "")
            )

        raw = str(source[key])
        if raw.startswith("data:"):
            header, separator, raw = raw.partition(",")
            if not separator or ";base64" not in header:
                raise QQToolError("invalid_parameters", "data URL 必须使用 Base64 编码")
        estimated_size = len(raw) * 3 // 4
        maximum = self.config["files"]["max_base64_size_mb"] * 1048576
        if estimated_size > maximum:
            raise QQToolError("invalid_parameters", "Base64 解码结果超过配置上限")
        try:
            decoded = base64.b64decode(raw, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise QQToolError("invalid_parameters", "Base64 编码无效") from exc
        if len(decoded) > maximum:
            raise QQToolError("invalid_parameters", "Base64 解码结果超过配置上限")
        suffix = ".bin"
        signatures = (
            (b"\x89PNG\r\n\x1a\n", ".png"),
            (b"\xff\xd8\xff", ".jpg"),
            (b"GIF8", ".gif"),
            (b"RIFF", ".wav"),
            (b"OggS", ".ogg"),
            (b"ID3", ".mp3"),
            (b"#!AMR", ".amr"),
        )
        for signature, detected_suffix in signatures:
            if decoded.startswith(signature):
                suffix = detected_suffix
                break
        if len(decoded) >= 12 and decoded[4:8] == b"ftyp":
            suffix = ".mp4"
        if decoded.startswith(b"RIFF") and decoded[8:12] == b"WEBP":
            suffix = ".webp"
        path = self.temp_dir / f"b64_{secrets.token_hex(12)}{suffix}"
        await asyncio.to_thread(path.write_bytes, decoded)
        await self.register_owned_media(event, path, "base64")
        return path

    async def download_url(self, raw_url: str, owner_id: str) -> Path:
        """Download an HTTP(S) URL with DNS, redirect, and size validation.

        Args:
            raw_url: Untrusted remote URL.
            owner_id: Caller ID owning the resulting media reference.

        Returns:
            Plugin-owned downloaded file path.

        Raises:
            QQToolError: If URL or response violates the configured boundary.
        """

        timeout = aiohttp.ClientTimeout(total=self.config["network"]["timeout_seconds"])
        current = raw_url
        connector = aiohttp.TCPConnector(
            resolver=_ValidatedResolver(self.config["network"]["allow_private_network"])
        )
        async with aiohttp.ClientSession(
            timeout=timeout, trust_env=False, connector=connector
        ) as session:
            for _ in range(6):
                await self.validate_url(current)
                try:
                    response = await session.get(current, allow_redirects=False)
                except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                    raise QQToolError("network_error", "下载媒体失败") from exc
                async with response:
                    if response.status in {301, 302, 303, 307, 308}:
                        location = response.headers.get("Location")
                        if not location:
                            raise QQToolError("network_error", "重定向缺少 Location")
                        current = urljoin(current, location)
                        continue
                    if response.status < 200 or response.status >= 300:
                        raise QQToolError(
                            "network_error", f"下载返回 HTTP {response.status}"
                        )
                    maximum = self.config["network"]["max_download_size_mb"] * 1048576
                    content_length = response.headers.get("Content-Length")
                    if content_length:
                        try:
                            declared_size = int(content_length)
                        except ValueError as exc:
                            raise QQToolError(
                                "response_invalid", "下载响应的 Content-Length 无效"
                            ) from exc
                        if declared_size > maximum:
                            raise QQToolError(
                                "invalid_parameters", "下载文件超过配置上限"
                            )
                    suffix = Path(urlsplit(current).path).suffix[:10]
                    if not re.fullmatch(r"\.[A-Za-z0-9]{1,9}", suffix):
                        content_type = response.headers.get("Content-Type", "").split(
                            ";", 1
                        )[0]
                        suffix = {
                            "image/jpeg": ".jpg",
                            "image/png": ".png",
                            "image/gif": ".gif",
                            "image/webp": ".webp",
                            "audio/mpeg": ".mp3",
                            "audio/ogg": ".ogg",
                            "audio/wav": ".wav",
                            "video/mp4": ".mp4",
                        }.get(content_type.lower(), ".bin")
                    path = self.temp_dir / f"url_{secrets.token_hex(12)}{suffix}"
                    size = 0
                    try:
                        with path.open("wb") as output:
                            async for chunk in response.content.iter_chunked(65536):
                                size += len(chunk)
                                if size > maximum:
                                    raise QQToolError(
                                        "invalid_parameters", "下载文件超过配置上限"
                                    )
                                output.write(chunk)
                    except Exception:
                        path.unlink(missing_ok=True)
                        raise
                    await self.storage.add_media_ref(
                        secrets.token_hex(12),
                        owner_id,
                        "download",
                        path,
                        int(time.time()) + self.config["files"]["temp_ttl_seconds"],
                    )
                    return path
            raise QQToolError("network_error", "下载重定向次数超过 5 次")

    async def validate_url(self, raw_url: str, *, resolve_dns: bool = True) -> None:
        """Validate URL scheme, hostname policy, and all DNS answers.

        Args:
            raw_url: Untrusted URL.
            resolve_dns: Whether the plugin will connect to the host and must validate
                every resolved address. Disable only for URLs embedded without a
                server-side request.

        Raises:
            QQToolError: If any URL or resolved address is forbidden.
        """

        parsed = urlsplit(raw_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise QQToolError("invalid_parameters", "只允许带域名的 HTTP(S) URL")
        if parsed.username or parsed.password:
            raise QQToolError("invalid_parameters", "URL 不允许包含用户凭据")
        hostname = parsed.hostname.lower().rstrip(".")
        blocked = self.config["network"]["blocked_domains"]
        allowed = self.config["network"]["allowed_domains"]
        if any(hostname == item or hostname.endswith("." + item) for item in blocked):
            raise QQToolError("permission_denied", "URL 域名位于禁止列表")
        if allowed and not any(
            hostname == item or hostname.endswith("." + item) for item in allowed
        ):
            raise QQToolError("permission_denied", "URL 域名不在允许列表")
        if not resolve_dns:
            try:
                literal_ip = ipaddress.ip_address(hostname)
            except ValueError:
                if "." not in hostname or hostname.endswith(
                    (".local", ".localhost", ".internal", ".lan", ".home.arpa")
                ):
                    raise QQToolError(
                        "permission_denied", "嵌入 URL 不允许使用本地主机名"
                    )
                return
            if self.config["network"]["allow_private_network"] or literal_ip.is_global:
                return
            raise QQToolError("permission_denied", "嵌入 URL 不允许使用私网或保留 IP")
        try:
            addresses = await asyncio.get_running_loop().getaddrinfo(
                hostname,
                parsed.port or (443 if parsed.scheme == "https" else 80),
                type=socket.SOCK_STREAM,
            )
        except socket.gaierror as exc:
            raise QQToolError("network_error", "URL 域名解析失败") from exc
        if not addresses:
            raise QQToolError("network_error", "URL 域名没有可用地址")
        if self.config["network"]["allow_private_network"]:
            return
        for address in addresses:
            ip = ipaddress.ip_address(address[4][0].split("%", 1)[0])
            if not ip.is_global:
                raise QQToolError("permission_denied", "URL 解析到了私网或保留地址")

    async def register_owned_media(self, event: Any, path: Path, source: str) -> str:
        """Register a plugin-owned file and return its opaque reference.

        Args:
            event: Current AstrBot event.
            path: Plugin-owned media path.
            source: Safe source category.

        Returns:
            Opaque media reference.
        """

        media_ref = secrets.token_hex(12)
        await self.storage.add_media_ref(
            media_ref,
            str(event.get_sender_id() or ""),
            source,
            path,
            int(time.time()) + self.config["files"]["temp_ttl_seconds"],
        )
        return media_ref

    async def normalize_media_result(
        self, event: Any, spec: OperationSpec, data: Any
    ) -> Any:
        """Replace provider-generated absolute media paths with opaque refs.

        Args:
            event: Current AstrBot event.
            spec: Executed operation.
            data: Raw OneBot response data.

        Returns:
            Response safe to expose to the model.
        """

        if spec.tool != "qq_media" or not isinstance(data, dict):
            return self.sanitize_data(data)
        result = self.sanitize_data(data)
        raw_path = data.get("file") or data.get("path")
        if (
            raw_path
            and Path(str(raw_path)).is_absolute()
            and Path(str(raw_path)).is_file()
        ):
            resolved_path = Path(str(raw_path)).resolve(strict=True)
            media_ref = secrets.token_hex(12)
            await self.storage.add_media_ref(
                media_ref,
                str(event.get_sender_id() or ""),
                "napcat",
                resolved_path,
                int(time.time()) + self.config["files"]["temp_ttl_seconds"],
            )
            if not isinstance(result, dict):
                result = {}
            result.pop("file", None)
            result.pop("path", None)
            if spec.operation_id == "qq_media.convert_record":
                if result.get("url") == "[local-path]":
                    result.pop("url")
                result["file_name"] = resolved_path.name
                result["file_size"] = resolved_path.stat().st_size
            result["media_ref"] = media_ref
        return result

    def success_result(
        self, operation_id: str, data: Any, params: dict[str, Any]
    ) -> dict[str, Any]:
        """Build a stable successful result and apply local pagination.

        Args:
            operation_id: Global operation identifier.
            data: Sanitized operation data.
            params: Validated operation parameters.

        Returns:
            Stable result object.
        """

        cursor = params.get("cursor")
        page_size = params.get("page_size", self.config["limits"]["page_size"])
        if isinstance(data, list):
            paged = self.paginate(data, cursor, page_size)
            return {
                "ok": True,
                "operation": operation_id,
                "summary": paged["summary"],
                "data": paged["data"],
                "next_cursor": paged["next_cursor"],
                "warnings": [],
            }
        if isinstance(data, dict) and {"data", "next_cursor", "summary"} <= set(data):
            return {
                "ok": True,
                "operation": operation_id,
                "summary": data["summary"],
                "data": data["data"],
                "next_cursor": data["next_cursor"],
                "warnings": [],
            }
        if operation_id in {"qq_send_message.send", "qq_send_forward.send"}:
            summary = "NapCat 已接受发送请求；最终回复不要重复消息正文或卡片"
            if isinstance(data, dict) and data.get("random_results"):
                summary = (
                    "NapCat 已接受发送请求；随机组件最终结果见 data.random_results；"
                    "最终回复不要重复消息正文或卡片"
                )
            return {
                "ok": True,
                "operation": operation_id,
                "summary": summary,
                "data": self.sanitize_data(data),
                "next_cursor": None,
                "warnings": [],
            }
        return {
            "ok": True,
            "operation": operation_id,
            "summary": "操作成功",
            "data": self.sanitize_data(data),
            "next_cursor": None,
            "warnings": [],
        }

    def compact_history_result(self, value: Any) -> list[dict[str, Any]]:
        """Reduce NapCat history messages to model-relevant fields.

        Args:
            value: Raw ``get_group_msg_history`` or ``get_friend_msg_history`` data.

        Returns:
            Bounded messages retaining identity, sender, time, and message components.
        """

        messages = value.get("messages") if isinstance(value, dict) else value
        if not isinstance(messages, list):
            return []
        result = []
        for item in messages[: self.config["limits"]["max_page_size"]]:
            if not isinstance(item, dict):
                continue
            compact = {
                key: item[key]
                for key in ("message_id", "message_seq", "time", "user_id")
                if key in item
            }
            sender = item.get("sender")
            if isinstance(sender, dict):
                compact["sender"] = {
                    key: sender[key]
                    for key in ("user_id", "nickname", "card", "role")
                    if key in sender
                }
            if isinstance(item.get("message"), list):
                compact["message"] = self.sanitize_data(item["message"])
            elif "raw_message" in item:
                compact["raw_message"] = self.sanitize_data(item["raw_message"])
            result.append(compact)
        return result

    def filter_group_data(self, data: Any, group_id: int) -> Any:
        """Restrict global request responses to the authorized group.

        Args:
            data: OneBot request response.
            group_id: Authorized group ID.

        Returns:
            Response containing only entries for the target group.
        """

        if isinstance(data, list):
            return [
                item
                for item in data
                if isinstance(item, dict)
                and str(item.get("group_id", "")) == str(group_id)
            ]
        if isinstance(data, dict):
            result = deepcopy(data)
            for key, value in data.items():
                if isinstance(value, list):
                    result[key] = self.filter_group_data(value, group_id)
            return result
        return data

    async def expand_forward(self, event: Any, value: Any, depth: int) -> Any:
        """Expand nested forward segments within the configured depth boundary.

        Args:
            event: Current AstrBot event.
            value: OneBot forward response or nested message content.
            depth: Remaining expansion depth.

        Returns:
            Forward structure with reachable nested forwards expanded.
        """

        if depth <= 0:
            return self.sanitize_data(value)
        if isinstance(value, list):
            result = []
            for item in value[: self.config["limits"]["max_forward_nodes"]]:
                result.append(await self.expand_forward(event, item, depth))
            return result
        if not isinstance(value, dict):
            return self.sanitize_data(value)
        if value.get("type") == "forward" and isinstance(value.get("data"), dict):
            forward_id = value["data"].get("id") or value["data"].get("resid")
            if forward_id:
                nested = await self.call_action(
                    event, "get_forward_msg", {"message_id": str(forward_id)}
                )
                return {
                    "type": "forward",
                    "id": str(forward_id),
                    "content": await self.expand_forward(event, nested, depth - 1),
                }
        result = {}
        for key, item in value.items():
            result[str(key)] = await self.expand_forward(event, item, depth)
        return result

    def select_notice(self, data: Any, notice_id: str) -> Any:
        """Select one authorized notice from a group notice response.

        Args:
            data: OneBot group notice response.
            notice_id: Requested notice identifier.

        Returns:
            Matching notice object.

        Raises:
            QQToolError: If the notice is not present.
        """

        candidates = data
        if isinstance(data, dict):
            candidates = next(
                (
                    data[key]
                    for key in ("notices", "items", "list", "data")
                    if isinstance(data.get(key), list)
                ),
                [],
            )
        if isinstance(candidates, list):
            for item in candidates:
                if not isinstance(item, dict):
                    continue
                item_id = item.get("notice_id") or item.get("fid") or item.get("id")
                if str(item_id or "") == notice_id:
                    return item
        raise QQToolError("target_not_found", "未找到指定群公告")

    def paginate(self, items: list[Any], cursor: Any, page_size: int) -> dict[str, Any]:
        """Apply stable offset pagination to one bounded list.

        Args:
            items: Complete bounded item list.
            cursor: Opaque offset cursor from a prior response.
            page_size: Requested page size.

        Returns:
            Page data, summary, and next cursor.

        Raises:
            QQToolError: If the cursor is invalid.
        """

        try:
            offset = int(cursor or 0)
        except (TypeError, ValueError, OverflowError) as exc:
            raise QQToolError("invalid_parameters", "cursor 无效") from exc
        if offset < 0:
            raise QQToolError("invalid_parameters", "cursor 无效")
        page_size = min(page_size, self.config["limits"]["max_page_size"])
        page = [self.sanitize_data(item) for item in items[offset : offset + page_size]]
        next_offset = offset + len(page)
        return {
            "summary": f"已返回 {len(page)}/{len(items)} 项",
            "data": page,
            "next_cursor": str(next_offset) if next_offset < len(items) else None,
        }

    def sanitize_data(self, value: Any, depth: int = 0) -> Any:
        """Remove secrets, controls, and absolute local paths from responses.

        Args:
            value: Untrusted protocol response value.
            depth: Current recursion depth.

        Returns:
            Bounded sanitized data.
        """

        if depth >= 8:
            return "[max-depth]"
        if isinstance(value, dict):
            sanitized = {}
            for key, item in value.items():
                key_text = str(key)
                normalized_key = re.sub(r"[^a-z0-9]", "", key_text.lower())
                if normalized_key in REDACTED_KEYS:
                    continue
                if normalized_key in PATH_LIKE_IDENTIFIER_KEYS and isinstance(
                    item, str
                ):
                    sanitized[key_text] = "".join(
                        char for char in item if char >= " " or char in "\n\t"
                    )[:8000]
                else:
                    sanitized[key_text] = self.sanitize_data(item, depth + 1)
            return sanitized
        if isinstance(value, list):
            return [self.sanitize_data(item, depth + 1) for item in value[:200]]
        if isinstance(value, str):
            if WINDOWS_ABSOLUTE_PATH.match(value) or value.startswith("/"):
                return "[local-path]"
            return "".join(char for char in value if char >= " " or char in "\n\t")[
                :8000
            ]
        if value is None or isinstance(value, bool | int | float):
            return value
        return str(value)[:1000]

    def dumps_result(self, result: dict[str, Any]) -> str:
        """Serialize and shrink a result to the configured context limit.

        Args:
            result: Stable tool result.

        Returns:
            JSON string within the configured character budget.
        """

        maximum = self.config["limits"]["max_output_chars"]
        text = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
        data = result.get("data")
        while len(text) > maximum and isinstance(data, list) and len(data) > 1:
            del data[(len(data) + 1) // 2 :]
            result["warnings"] = ["输出因上下文上限被裁剪，请使用游标继续查询"]
            result["next_cursor"] = str(len(data))
            text = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
        if len(text) > maximum:
            result["data"] = "[output-truncated]"
            result["warnings"] = ["输出超过配置字符上限"]
            text = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
        return text

    async def audit(
        self,
        event: Any,
        spec: OperationSpec,
        target_kind: str,
        target_id: str,
        decision: str,
        result_code: str,
        params_hash: str,
        pending_id: str,
        duration_ms: int,
    ) -> None:
        """Persist an audit record without bodies, Base64, or file paths.

        Args:
            event: Current AstrBot event.
            spec: Operation declaration.
            target_kind: Authorized target kind.
            target_id: Authorized target ID.
            decision: Authorization or confirmation decision.
            result_code: Stable result code.
            params_hash: Hash of exact action parameters.
            pending_id: Optional confirmation identifier.
            duration_ms: Execution duration.
        """

        await self.storage.add_audit(
            {
                "created_at": int(time.time()),
                "operation_id": spec.operation_id,
                "caller_id": str(event.get_sender_id() or ""),
                "session_id": hashlib.sha256(
                    str(event.unified_msg_origin).encode()
                ).hexdigest()[:16],
                "platform_id": event.get_platform_id(),
                "target_kind": target_kind,
                "target_id": target_id,
                "risk": spec.risk,
                "decision": decision,
                "result_code": result_code,
                "pending_id": pending_id,
                "params_hash": params_hash,
                "duration_ms": duration_ms,
            }
        )

    @staticmethod
    def hash_params(params: Any) -> str:
        """Hash exact parameters without logging their content.

        Args:
            params: Exact normalized parameters.

        Returns:
            SHA-256 hexadecimal digest.
        """

        encoded = json.dumps(
            params,
            sort_keys=True,
            ensure_ascii=False,
            default=str,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def pending_summary(
        spec: OperationSpec,
        target_kind: str,
        target_id: str,
        params: dict[str, Any],
    ) -> str:
        """Build a confirmation summary without message bodies or paths.

        Args:
            spec: Operation declaration.
            target_kind: Target category.
            target_id: Exact target ID.
            params: Exact action parameters.

        Returns:
            Safe human-readable confirmation summary.
        """

        target = f"{target_kind}:{target_id}" if target_id else target_kind
        count = len(params.get("message", params.get("messages", [])))
        detail = f"，内容项数 {count}" if count else ""
        return f"待确认：执行 {spec.operation_id}，目标 {target}{detail}。"

    async def cleanup(self) -> None:
        """Remove expired plugin-owned files and retained metadata."""

        paths = await self.storage.cleanup(
            self.config["events"]["retention_days"],
            self.config["audit"]["retention_days"],
        )
        root = self.temp_dir.resolve(strict=False)
        for path in paths:
            try:
                resolved = path.resolve(strict=False)
                if root in resolved.parents and resolved.is_file():
                    resolved.unlink()
            except OSError:
                logger.warning("Failed to remove expired QQ plugin media")
