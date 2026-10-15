from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal

from ..catalog import OperationSpec
from ..errors import QQToolError
from .base import Capability, EncodedMedia, LocalMedia, VersionInfo
from .common import HISTORY_OPERATIONS, prepare_common_action


class NapCatProvider:
    id = "napcat"
    display_name = "NapCat"
    contract_version = "4.18.19"
    min_version = (4, 18, 19)
    supported_versions = ">=4.18.19"

    def __init__(self) -> None:
        contract = (
            Path(__file__).resolve().parents[1] / "contracts" / "napcat_v4_18_19.json"
        )
        self.actions = frozenset(
            json.loads(contract.read_text(encoding="utf-8"))["actions"]
        )

    def matches(self, info: VersionInfo) -> bool:
        return "napcat" in info.implementation.lower()

    def validate_version(self, info: VersionInfo) -> None:
        match = re.search(r"(\d+)\.(\d+)\.(\d+)", info.version)
        if not match:
            raise QQToolError("response_invalid", "无法识别 NapCat 版本号")
        version = tuple(int(part) for part in match.groups())
        if version < self.min_version:
            raise QQToolError(
                "unsupported_version",
                f"仅支持 NapCat {self.supported_versions}，当前版本为 {info.version}",
            )

    def capability(self, spec: OperationSpec) -> Capability:
        # Local orchestration and message builders have no single upstream action.
        if spec.action is None or spec.action in self.actions:
            return Capability(True)
        return Capability(
            False, f"NapCat 契约未支持操作 {spec.operation_id}：{spec.action}"
        )

    def validate_parameters(self, spec: OperationSpec, params: dict[str, Any]) -> None:
        if spec.operation_id in HISTORY_OPERATIONS and "message_id" in params:
            raise QQToolError(
                "invalid_parameters",
                "NapCat 历史查询使用 message_seq，不接受 message_id 锚点",
            )
        if spec.operation_id == "qq_media.ocr" and "file_id" in params:
            raise QQToolError(
                "invalid_parameters",
                "NapCat OCR 不接受 file_id，请使用 path、url、base64 或 media_ref",
            )
        if spec.operation_id == "qq_private_files.url" and "file_hash" in params:
            raise QQToolError(
                "invalid_parameters", "NapCat 私聊文件下载不接受 file_hash"
            )

    def media_input(self, spec: OperationSpec) -> Literal["local_file", "remote_image"]:
        return "local_file"

    def prepare_action(
        self,
        spec: OperationSpec,
        params: dict[str, Any],
        *,
        page_size: int,
        resolved_media: str | None = None,
    ) -> tuple[str | None, dict[str, Any]]:
        self.capability(spec).require()
        self.validate_parameters(spec, params)
        result = prepare_common_action(
            spec, params, page_size=page_size, resolved_media=resolved_media
        )
        if spec.operation_id in HISTORY_OPERATIONS:
            # A NapCat sequence is not a SnowLuma message hash.
            result.setdefault("message_seq", 0)
        elif spec.operation_id == "qq_group_request.list":
            result.pop("group_id", None)
        elif spec.operation_id == "qq_private_files.url":
            result.pop("user_id", None)
        return spec.action, result

    def encoded_media(
        self, spec: OperationSpec, data: Any, params: dict[str, Any]
    ) -> EncodedMedia | None:
        return None

    def sent_random_history_action(
        self, send_action: str, send_params: dict[str, Any], message_id: int
    ) -> tuple[str, dict[str, Any]] | None:
        return None

    def local_media(self, spec: OperationSpec, data: Any) -> LocalMedia | None:
        if spec.tool != "qq_media" or not isinstance(data, dict):
            return None
        path = data.get("file") or data.get("path")
        if not path:
            return None
        return LocalMedia(
            str(path),
            ("file", "path"),
            include_metadata=spec.operation_id == "qq_media.convert_record",
        )
