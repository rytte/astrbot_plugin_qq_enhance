from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

from ..catalog import OperationSpec
from ..errors import QQToolError
from .base import Capability, LocalMedia, VersionInfo


class NapCatProvider:
    id = "napcat"
    display_name = "NapCat"
    contract_version = "4.18.19"
    min_version = (4, 18, 19)
    max_version = (5, 0, 0)
    supported_versions = ">=4.18.19,<5.0.0"

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
        if not self.min_version <= version < self.max_version:
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

    def prepare_action(
        self,
        spec: OperationSpec,
        params: dict[str, Any],
        *,
        page_size: int,
        resolved_file: str | None = None,
    ) -> tuple[str | None, dict[str, Any]]:
        """Map business parameters to the pinned NapCat action contract."""
        self.capability(spec).require()
        operation_id = spec.operation_id
        result = deepcopy(params)
        if resolved_file is not None:
            if operation_id == "qq_account_manage.set_avatar":
                result = {"file": resolved_file}
            else:
                result["image" if operation_id == "qq_media.ocr" else "file"] = (
                    resolved_file
                )
        if operation_id == "qq_group_info.honor":
            result["type"] = result.pop("honor_type", "all")
        elif operation_id in {"qq_friend_request.approve", "qq_friend_request.reject"}:
            result["approve"] = spec.operation == "approve"
        elif operation_id in {"qq_group_request.approve", "qq_group_request.reject"}:
            result.pop("group_id", None)
            result["approve"] = spec.operation == "approve"
        elif operation_id in {
            "qq_message_manage.reaction_add",
            "qq_message_manage.reaction_remove",
        }:
            result["set"] = spec.operation == "reaction_add"
        elif operation_id in {
            "qq_essence.add",
            "qq_essence.remove",
            "qq_group_request.list",
            "qq_group_request.ignored",
        }:
            result.pop("group_id", None)
        elif operation_id == "qq_private_files.url":
            result.pop("user_id", None)
        elif operation_id == "qq_notice.detail":
            result.pop("notice_id", None)
        elif operation_id == "qq_recent_contacts.list":
            result.setdefault("count", page_size)
        elif operation_id in {"qq_group_history.list", "qq_friend_history.list"}:
            # message_seq is a NapCat sequence anchor, not a message_id alias.
            result.setdefault("message_seq", 0)
            result.setdefault("count", min(page_size, 100))
        elif operation_id == "qq_forward_get.get":
            result.pop("depth", None)
            reference = result.pop("message_id", None)
            if reference is None:
                reference = result.pop("res_id")
            result["message_id"] = str(reference)
        return spec.action, result

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
