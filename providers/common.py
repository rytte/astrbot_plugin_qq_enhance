from __future__ import annotations

from copy import deepcopy
from typing import Any

from ..catalog import OperationSpec


HISTORY_OPERATIONS = frozenset({"qq_group_history.list", "qq_friend_history.list"})


def prepare_common_action(
    spec: OperationSpec,
    params: dict[str, Any],
    *,
    page_size: int,
    resolved_media: str | None,
) -> dict[str, Any]:
    """Map parameter conventions shared by the supported OneBot implementations."""
    operation_id = spec.operation_id
    result = deepcopy(params)
    if resolved_media is not None:
        if operation_id == "qq_account_manage.set_avatar":
            result = {"file": resolved_media}
        else:
            result["image" if operation_id == "qq_media.ocr" else "file"] = (
                resolved_media
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
        "qq_group_request.ignored",
    }:
        result.pop("group_id", None)
    elif operation_id == "qq_notice.detail":
        result.pop("notice_id", None)
    elif operation_id == "qq_recent_contacts.list":
        result.setdefault("count", page_size)
    elif operation_id in HISTORY_OPERATIONS:
        result.setdefault("count", min(page_size, 100))
    elif operation_id == "qq_forward_get.get":
        result.pop("depth", None)
        reference = result.pop("message_id", None)
        if reference is None:
            reference = result.pop("res_id")
        result["message_id"] = str(reference)
    return result
