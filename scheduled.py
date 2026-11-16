from __future__ import annotations

from copy import copy
from typing import Any

from astrbot.core.cron.events import CronMessageEvent
from astrbot.core.platform.astrbot_message import Group, MessageMember
from astrbot.core.platform.message_type import MessageType

from .errors import QQToolError


def bind_scheduled_event(event: Any, context: Any, config: dict[str, Any]) -> Any:
    """Give cron tools a QQ context without changing the shared scheduler event.

    A delivery session selects its exact adapter. Background jobs use the
    configured adapter or the only QQ adapter, and retain their cron history.
    The scheduler's caller role is preserved; a destination never grants it.
    """
    if not isinstance(event, CronMessageEvent) or event.get_platform_name() != "cron":
        return event

    configured_id = config["platform"]["platform_id"]
    platform_id = event.get_platform_id()
    unbound = (
        platform_id == "cron"
        and event.session.message_type == MessageType.OTHER_MESSAGE
    )
    if unbound:
        if not event.is_admin():
            raise QQToolError(
                "permission_denied", "未绑定 QQ 会话的定时任务仅允许 AstrBot 管理员执行"
            )
        if configured_id:
            platform_id = configured_id
        else:
            manager = getattr(context, "platform_manager", None)
            candidates = [
                platform
                for platform in getattr(manager, "platform_insts", ())
                if platform.meta().name == "aiocqhttp"
            ]
            if len(candidates) != 1:
                raise QQToolError(
                    "unsupported_platform",
                    "定时任务未绑定 QQ 会话，且无法确定唯一的 QQ 实例；"
                    "请在未来任务中选择 QQ 会话，或配置 platform.platform_id",
                )
            platform_id = candidates[0].meta().id

    if configured_id and platform_id != configured_id:
        raise QQToolError("unsupported_platform", "当前 aiocqhttp 实例未被插件授权")
    platform = context.get_platform_inst(platform_id)
    if platform is None or platform.meta().name != "aiocqhttp":
        raise QQToolError(
            "unsupported_platform",
            "定时任务未绑定可用的 QQ 实例，请在未来任务中选择 QQ 会话",
        )

    session = event.session
    group_id = ""
    if session.message_type in {MessageType.GROUP_MESSAGE, MessageType.FRIEND_MESSAGE}:
        peer_id = (
            session.session_id.rsplit("_", 1)[-1]
            if session.message_type == MessageType.GROUP_MESSAGE
            else session.session_id
        )
        if not peer_id.isdecimal() or int(peer_id) <= 0:
            raise QQToolError("unsupported_platform", "定时任务绑定的 QQ 会话 ID 无效")
        if session.message_type == MessageType.GROUP_MESSAGE:
            group_id = peer_id

    payload = event.get_extra("cron_payload", {})
    payload = payload if isinstance(payload, dict) else {}
    sender_id = str(payload.get("sender_id") or "")
    if not sender_id:
        sender_id = (
            session.session_id
            if payload.get("origin") == "api"
            and session.message_type == MessageType.FRIEND_MESSAGE
            else f"cron:{session.session_id}"
        )
    if not event.is_admin() and (not sender_id.isdecimal() or int(sender_id) <= 0):
        raise QQToolError("permission_denied", "无法识别定时任务创建者的 QQ 号")

    bound = copy(event)
    bound._extras = dict(event._extras)
    bound.platform_meta = platform.meta()
    bound.platform = bound.platform_meta
    bound.message_obj = copy(event.message_obj)
    bound.message_obj.type = session.message_type
    bound.message_obj.group = Group(group_id=group_id) if group_id else None
    bound.message_obj.sender = MessageMember(user_id=sender_id, nickname="Scheduler")
    # CronMessageEvent.self_id is the scheduler name, not the logged-in QQ.
    bound.message_obj.self_id = ""
    return bound
