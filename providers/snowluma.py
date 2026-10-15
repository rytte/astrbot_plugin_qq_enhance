from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Literal

from ..catalog import OperationSpec
from ..errors import QQToolError
from .base import Capability, EncodedMedia, LocalMedia, VersionInfo
from .common import HISTORY_OPERATIONS, prepare_common_action


class SnowLumaProvider:
    id = "snowluma"
    display_name = "SnowLuma"
    contract_version = "1.14.22"
    supported_versions = "1.14.22"
    unsupported_operations = {
        "qq_recent_contacts.list": "SnowLuma v1.14.22 的最近联系人接口是固定空数组占位，无法查询最近联系人",
        "qq_group_info.detail_ex": "SnowLuma v1.14.22 不提供 NapCat 扩展群资料，请使用 qq_group_info.detail",
    }
    unsupported_fields = {
        "qq_account_manage.set_profile": ("company", "email", "college"),
        "qq_friend_request.approve": ("remark",),
        "qq_group_member_manage.title": ("duration",),
        "qq_notice.send": ("title",),
    }
    limitations = {
        "qq_status.clients": (
            "仅返回本次 QQ 会话已观察到的设备快照，不支持强制刷新；尚无快照时查询会失败",
        ),
        "qq_friend_list.friends": ("不支持 no_cache=true 强制刷新",),
        "qq_user_info.stranger": (
            "不支持 no_cache=true；缺少可靠来源的资料字段可能省略或为空",
        ),
        "qq_group_history.list": (
            "历史锚点使用 message_id（允许负数），不接受 message_seq",
        ),
        "qq_friend_history.list": (
            "历史锚点使用 message_id（允许负数），不接受 message_seq",
        ),
        "qq_media.ocr": (
            "只接受 HTTP(S) URL 或 SnowLuma 图片缓存 file_id；本地路径、Base64 和 media_ref 不受支持",
        ),
        "qq_account_manage.set_profile": ("不支持 company、email、college",),
        "qq_friend_request.approve": (
            "不支持同时设置 remark；可在通过后调用修改好友备注",
        ),
        "qq_group_member_manage.title": ("不支持指定 duration",),
        "qq_group_manage.leave": ("仅支持退群，不支持 is_dismiss=true 解散群",),
        "qq_group_manage.avatar": ("不支持 cache=true",),
        "qq_notice.send": ("不支持独立 title 字段，请将标题放入 content",),
        "qq_group_info.mute_list": ("禁言状态来源于成员列表，可能有约 60 秒延迟",),
        "qq_group_members.detail": (
            "部分 QQ NT 未提供的资料字段使用固定值，不能视为真实成员属性",
        ),
        "qq_user_info.group_member": (
            "部分 QQ NT 未提供的资料字段使用固定值，不能视为真实成员属性",
        ),
        "qq_group_members.list": (
            "部分 QQ NT 未提供的资料字段使用固定值，不能视为真实成员属性",
        ),
    }

    def __init__(self) -> None:
        contract = (
            Path(__file__).resolve().parents[1] / "contracts" / "snowluma_v1_14_22.json"
        )
        self.actions = frozenset(
            json.loads(contract.read_text(encoding="utf-8"))["actions"]
        )

    def matches(self, info: VersionInfo) -> bool:
        return info.implementation.casefold() == "snowluma"

    def validate_version(self, info: VersionInfo) -> None:
        match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:-node)?", info.version)
        if not match:
            raise QQToolError("response_invalid", "无法识别 SnowLuma 版本号")
        if tuple(int(part) for part in match.groups()) != (1, 14, 22):
            raise QQToolError(
                "unsupported_version",
                f"仅支持 SnowLuma v1.14.22，当前版本为 {info.version}",
            )
        if info.protocol_version != "v11":
            raise QQToolError(
                "unsupported_version",
                "SnowLuma 必须使用 OneBot v11（protocol_version=v11）",
            )

    def capability(self, spec: OperationSpec) -> Capability:
        reason = self.unsupported_operations.get(spec.operation_id)
        if reason:
            return Capability(False, reason)
        if spec.action is not None and spec.action not in self.actions:
            return Capability(False, f"SnowLuma v1.14.22 未登记 action：{spec.action}")
        return Capability(True, limitations=self.limitations.get(spec.operation_id, ()))

    def validate_parameters(self, spec: OperationSpec, params: dict[str, Any]) -> None:
        self.capability(spec).require()
        operation_id = spec.operation_id
        rejected = [
            key
            for key in self.unsupported_fields.get(operation_id, ())
            if key in params
        ]
        if operation_id in HISTORY_OPERATIONS and "message_seq" in params:
            raise QQToolError(
                "invalid_parameters",
                "SnowLuma 历史查询使用 message_id，不接受 message_seq；两者语义不同，不能直接改名",
            )
        if operation_id in HISTORY_OPERATIONS and "message_id" in params:
            anchor = params["message_id"]
            if type(anchor) is not int or not -(2**31) <= anchor < 2**31:
                raise QQToolError(
                    "invalid_parameters",
                    "SnowLuma 历史锚点 message_id 必须是有符号 32 位整数",
                )
        if operation_id in {
            "qq_status.clients",
            "qq_friend_list.friends",
            "qq_user_info.stranger",
        } and params.get("no_cache"):
            rejected.append("no_cache=true")
        if operation_id == "qq_group_manage.leave" and params.get("is_dismiss"):
            rejected.append("is_dismiss=true")
        if operation_id == "qq_group_manage.avatar" and params.get("cache"):
            rejected.append("cache=true")
        if operation_id == "qq_media.ocr":
            rejected.extend(
                key for key in ("path", "base64", "media_ref") if key in params
            )
            file_id = params.get("file_id")
            if file_id is not None and (
                not isinstance(file_id, str)
                or not file_id.strip()
                or len(file_id) > 4096
                or PurePosixPath(file_id).is_absolute()
                or PureWindowsPath(file_id).is_absolute()
                or re.match(r"(?:https?|file|base64|data):", file_id, re.I)
            ):
                raise QQToolError(
                    "invalid_parameters", "file_id 必须是 SnowLuma 提供的图片缓存标识"
                )
        if rejected:
            raise QQToolError(
                "invalid_parameters",
                f"SnowLuma v1.14.22 的 {operation_id} 不支持：{'、'.join(rejected)}",
            )

    def media_input(self, spec: OperationSpec) -> Literal["local_file", "remote_image"]:
        return "remote_image" if spec.operation_id == "qq_media.ocr" else "local_file"

    def prepare_action(
        self,
        spec: OperationSpec,
        params: dict[str, Any],
        *,
        page_size: int,
        resolved_media: str | None = None,
    ) -> tuple[str | None, dict[str, Any]]:
        self.validate_parameters(spec, params)
        result = prepare_common_action(
            spec, params, page_size=page_size, resolved_media=resolved_media
        )
        operation_id = spec.operation_id
        if operation_id in HISTORY_OPERATIONS:
            result.setdefault("message_id", 0)
        elif operation_id == "qq_group_files.move":
            result["parent_directory"] = result.pop("current_parent_directory")
            result["target_directory"] = result.pop("target_parent_directory")
        elif operation_id in {"qq_friend_list.friends", "qq_user_info.stranger"}:
            result.pop("no_cache", None)
        elif operation_id == "qq_group_manage.leave":
            result.pop("is_dismiss", None)
        elif operation_id == "qq_group_manage.avatar":
            result.pop("cache", None)
        elif operation_id == "qq_group_files.delete":
            result.pop("busid", None)
        return spec.action, result

    def local_media(self, spec: OperationSpec, data: Any) -> LocalMedia | None:
        # SnowLuma exposes cache URLs and inline converted bytes, never local paths.
        return None

    def encoded_media(
        self, spec: OperationSpec, data: Any, params: dict[str, Any]
    ) -> EncodedMedia | None:
        if (
            spec.operation_id not in {"qq_media.get_record", "qq_media.convert_record"}
            or "out_format" not in params
        ):
            return None
        if (
            not isinstance(data, dict)
            or not isinstance(data.get("base64"), str)
            or not data["base64"]
        ):
            raise QQToolError(
                "response_invalid", "SnowLuma 语音转码响应缺少有效 Base64 数据"
            )
        if data.get("out_format") != params["out_format"]:
            raise QQToolError("response_invalid", "SnowLuma 语音转码格式与请求不一致")
        return EncodedMedia(data["base64"], params["out_format"])
