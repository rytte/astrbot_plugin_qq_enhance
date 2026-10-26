"""Lifetime reply quotas and notifications for non-friend QQ private messages."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from weakref import WeakValueDictionary

from mcp.types import CallToolResult, TextContent

from astrbot.api import logger
from astrbot.api.event import MessageChain
from astrbot.api.message_components import Plain
from astrbot.core.agent.tool import FunctionTool, ToolSet
from astrbot.core.platform.message_session import MessageSession
from astrbot.core.platform.message_type import MessageType

from .errors import QQToolError
from .request_notification import NoticeResponseEvent, PlatformNotificationEvent


TURN_KEY = "_qq_enhance_temporary_turn"
PRIVATE_SEND_ACTIONS = frozenset(
    {"send_private_msg", "send_private_forward_msg", "upload_private_file"}
)


@dataclass
class TemporaryTurn:
    identity: tuple[str, str, str]
    replied: bool = False


class TemporarySendTool(FunctionTool):
    """Keep the built-in sender request-local while sharing the reply quota."""

    def __init__(self, delegate, sessions, event):
        super().__init__(
            name=delegate.name,
            description=delegate.description,
            parameters=delegate.parameters,
        )
        self.delegate = delegate
        self.sessions = sessions
        self.event = event

    async def call(self, context, **kwargs):
        turn = self.event.get_extra(TURN_KEY)
        expected = str(
            MessageSession(
                turn.identity[0], MessageType.FRIEND_MESSAGE, turn.identity[2]
            )
        )
        target = str(kwargs.get("session") or expected)
        if ":" not in target:
            target = str(
                MessageSession(turn.identity[0], MessageType.FRIEND_MESSAGE, target)
            )

        async def deliver():
            return await self.delegate.call(context, **kwargs)

        if target != expected:
            return await deliver()

        def succeeded(result):
            if isinstance(result, CallToolResult):
                if result.isError:
                    return False
                result = "\n".join(
                    part.text
                    for part in result.content
                    if isinstance(part, TextContent)
                )
            return isinstance(result, str) and result.startswith(
                f"Message sent to session {expected}"
            )

        return await self.sessions.send_reply(self.event, deliver, succeeded=succeeded)


class TemporarySessions:
    """Apply the same quota to native replies and QQ-tool deliveries."""

    def __init__(self, context, config, storage, runtime):
        self.context = context
        self.config = config
        self.storage = storage
        self.runtime = runtime
        self.locks: WeakValueDictionary[tuple[str, str, str], asyncio.Lock] = (
            WeakValueDictionary()
        )

    @property
    def reply_limit(self) -> int:
        """Return the active quota, keeping notification settings independent."""
        settings = self.config["temporary_sessions"]
        return settings["max_replies"] if settings["limit_replies"] else -1

    def _lock(self, identity):
        lock = self.locks.get(identity)
        if lock is None:
            lock = asyncio.Lock()
            self.locks[identity] = lock
        return lock

    async def is_friend(self, event, user_id: str) -> bool:
        """Recheck membership for every input; do not cache non-friend results."""
        result = await self.runtime.call_action(
            event, "get_friend_list", {}, skip_contract=True
        )
        if isinstance(result, dict):
            for key in ("data", "items", "friends"):
                if isinstance(result.get(key), list):
                    result = result[key]
                    break
        if not isinstance(result, list):
            raise QQToolError("response_invalid", "无法确认当前 QQ 好友列表")
        return any(
            isinstance(item, dict) and str(item.get("user_id", "")) == user_id
            for item in result
        )

    async def prepare(self, event) -> None:
        """Check private input before message enhancement, debounce and tools."""
        if event.get_platform_name() != "aiocqhttp":
            return
        platform_id = str(event.get_platform_id())
        configured_id = self.config["platform"]["platform_id"]
        if configured_id and platform_id != configured_id:
            return
        if event.get_extra(TURN_KEY) is not None:
            return
        if isinstance(event, NoticeResponseEvent):
            if event.get_group_id():
                return
            user_id = str(event.session.session_id)
            unsolicited_message = False
        else:
            if isinstance(event, PlatformNotificationEvent):
                return
            raw = getattr(event.message_obj, "raw_message", None)
            if (
                not isinstance(raw, dict)
                or raw.get("post_type") != "message"
                or raw.get("message_type") != "private"
            ):
                return
            user_id = str(event.get_sender_id())
            unsolicited_message = True
        self_id = str(event.get_self_id())
        if not user_id.isdecimal() or user_id == self_id:
            return
        identity = (platform_id, self_id, user_id)
        settings = self.config["temporary_sessions"]
        try:
            # A former temporary contact becomes unrestricted as soon as the
            # protocol's current friend list confirms the friendship.
            if await self.is_friend(event, user_id):
                return
            state = await self.storage.get_temporary_session(*identity)
        except Exception:
            logger.exception(
                "QQ 临时会话检查失败：platform=%s user=%s", platform_id, user_id
            )
            if self.reply_limit >= 0:
                event.stop_event()
            return

        turn = TemporaryTurn(identity)
        event.set_extra(TURN_KEY, turn)
        self.bind_transport(event)
        if settings["notify_admins"] and unsolicited_message:
            await self.notify_admins(event, identity)
        maximum = self.reply_limit
        if maximum >= 0 and state["replies"] >= maximum:
            event.stop_event()
            logger.info(
                "QQ 临时会话已拦截：platform=%s user=%s replies=%s limit=%s",
                platform_id,
                user_id,
                state["replies"],
                maximum,
            )

    def bind_transport(self, event) -> None:
        """Rebind copied debounce transports without nesting quota wrappers."""
        original_send = getattr(event, "_qq_enhance_original_send", event.send)
        # copy.copy retains instance-bound methods. Restore the receiver so
        # streaming continuations update their own native delivery state.
        if getattr(original_send, "__self__", event) is not event:
            original_send = original_send.__func__.__get__(event, type(event))
        event._qq_enhance_original_send = original_send

        async def send(message):
            if not any(
                not isinstance(part, Plain) or part.text.strip()
                for part in getattr(message, "chain", ())
            ):
                return await original_send(message)
            return await self.send_reply(event, lambda: original_send(message))

        event.send = send

    def wrap_tools(self, event, request) -> None:
        """Wrap only this request's built-in sender, keeping shared tools intact."""
        if event.get_extra(TURN_KEY) is None or request.func_tool is None:
            return
        tools = []
        for tool in request.func_tool.tools:
            if isinstance(tool, TemporarySendTool):
                tool = tool.delegate
            if tool.name == "send_message_to_user" and tool.handler is None:
                tool = TemporarySendTool(tool, self, event)
            tools.append(tool)
        request.func_tool = ToolSet(tools)

    async def send_reply(self, event, deliver, *, succeeded=None):
        """Count one successful turn, sharing native, streamed and tool sends."""
        turn = event.get_extra(TURN_KEY)
        if turn is None:
            return await deliver()
        async with self._lock(turn.identity):
            if turn.replied:
                return await deliver()
            state = await self.storage.get_temporary_session(*turn.identity)
            maximum = self.reply_limit
            if maximum >= 0 and state["replies"] >= maximum:
                # Another in-flight input may have used the final reply. A new
                # friendship still takes precedence over that exhausted quota.
                if not await self.is_friend(event, turn.identity[2]):
                    event.stop_event()
                    raise QQToolError("permission_denied", "临时会话的回复次数已用尽")
                turn.replied = True
                return await deliver()
            result = await deliver()
            if succeeded is not None and not succeeded(result):
                return result
            await self.storage.record_temporary_reply(*turn.identity)
            turn.replied = True
            return result

    async def send_action(self, event, action, params, deliver):
        """Guard tool replies and remember successful administrator initiations."""
        user_id = str(params.get("user_id") or "")
        turn = event.get_extra(TURN_KEY)
        if (
            action in PRIVATE_SEND_ACTIONS
            and turn is not None
            and user_id == turn.identity[2]
        ):
            return await self.send_reply(event, deliver)
        result = await deliver()
        if (
            action == "send_private_msg"
            and params.get("group_id")
            and user_id.isdecimal()
            and event.is_admin()
        ):
            await self.storage.mark_temporary_outbound(
                str(event.get_platform_id()), str(event.get_self_id()), user_id
            )
        return result

    async def notify_admins(self, event, identity) -> None:
        """Send a fixed reminder once, including contacts denied at zero quota."""
        if not await self.storage.claim_temporary_notification(*identity):
            return
        raw = event.message_obj.raw_message
        nickname = " ".join(str(event.get_sender_name() or "").split())[:80]
        lines = ["收到新的 QQ 临时会话", f"用户：{nickname}（{identity[2]}）"]
        group_id = raw.get("group_id")
        if not group_id and isinstance(raw.get("sender"), dict):
            group_id = raw["sender"].get("group_id")
        if str(group_id or "").isdecimal() and int(group_id) > 0:
            lines.append(f"来源群：{group_id}")
        maximum = self.reply_limit
        lines.append(
            "当前策略：拒绝临时会话"
            if maximum == 0
            else "当前策略：不限回复次数"
            if maximum == -1
            else f"当前策略：累计最多回复 {maximum} 次"
        )
        text = "\n".join(lines)
        delivered = False
        try:
            for admin_id in self.config["temporary_sessions"]["admin_user_ids"]:
                try:
                    session = MessageSession(
                        identity[0], MessageType.FRIEND_MESSAGE, admin_id
                    )
                    sent = await asyncio.wait_for(
                        self.context.send_message(session, MessageChain([Plain(text)])),
                        timeout=self.config["network"]["timeout_seconds"],
                    )
                    if not sent:
                        raise RuntimeError("目标平台不可用")
                    delivered = True
                except Exception:
                    logger.exception(
                        "QQ 临时会话提醒发送失败：admin=%s user=%s",
                        admin_id,
                        identity[2],
                    )
        finally:
            if not delivered:
                await self.storage.release_temporary_notification(*identity)
