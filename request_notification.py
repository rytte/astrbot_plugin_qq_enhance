from __future__ import annotations

import json
from copy import deepcopy
from uuid import uuid4

from mcp.types import CallToolResult, TextContent

from astrbot.api.event import AstrMessageEvent, MessageChain
from astrbot.api.message_components import At, Plain, Reply
from astrbot.core.agent.tool import FunctionTool
from astrbot.core.platform.astrbot_message import AstrBotMessage, MessageMember
from astrbot.core.platform.message_session import MessageSession
from astrbot.core.platform.message_type import MessageType
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)


class PlatformNotificationEvent(AiocqhttpMessageEvent):
    """Deliver trusted platform facts through an explicitly bound conversation.

    Args:
        context: Plugin context used to route outgoing messages.
        platform: Originating OneBot platform instance.
        session: Destination session, including group user-isolation when enabled.
        notification_id: Internal sender identity, distinct from actual users.
        self_id: Bot account associated with the source event.
        text: Platform facts presented as the current user input.
        group: Group metadata of the source conversation, if applicable.
    """

    def __init__(
        self, context, platform, session, notification_id, self_id, text, group=None
    ):
        message = AstrBotMessage()
        message.type = session.message_type
        message.self_id = self_id
        message.session_id = session.session_id
        message.message_id = f"{notification_id}:{session.session_id}"
        message.sender = MessageMember(user_id=notification_id, nickname="QQ 平台事件")
        message.group = deepcopy(group)
        message.message = [Plain(text)]
        message.message_str = text
        message.raw_message = {
            "post_type": "notice",
            "notice_type": "qq_enhance_notification",
        }
        super().__init__(
            text, message, platform.meta(), session.session_id, platform.get_client()
        )
        self.context = context
        self.reply_target: tuple[str, str, str] | None = None
        self.is_wake = True
        self.is_at_or_wake_command = True

    @AstrMessageEvent.session_id.setter
    def session_id(self, value: str) -> None:
        """Keep the bound destination when waking recalculates group isolation.

        Args:
            value: Pipeline-computed identifier based on the synthetic sender.
        """

        if value == self.session.session_id:
            self.session.session_id = value

    def is_admin(self) -> bool:
        """Never inherit administrator privileges from the destination session."""

        return False

    def is_stopped(self) -> bool:
        """Stop when the destination disables the plugin and its safety hooks."""

        return super().is_stopped() or (
            self.plugins_name is not None
            and "astrbot_plugin_qq_enhance" not in self.plugins_name
        )

    async def send(self, message: MessageChain) -> None:
        """Send to the administrator session rather than the internal sender.

        Args:
            message: Pipeline response to deliver.
        """

        if self.is_stopped():
            return
        message = deepcopy(message)
        routed_components = []
        for component in message.chain:
            if isinstance(component, At) and str(component.qq) == self.get_sender_id():
                if self.reply_target is None:
                    continue
                component.qq, component.name = self.reply_target[:2]
            elif (
                isinstance(component, Reply)
                and str(component.id) == self.message_obj.message_id
            ):
                if self.reply_target is None:
                    continue
                component.id = self.reply_target[2]
            routed_components.append(component)
        message.chain = routed_components
        if not await self.context.send_message(self.session, message):
            raise RuntimeError("QQ 平台通知发送失败：目标平台不可用")
        await AstrMessageEvent.send(self, message)


class RequestNotificationEvent(PlatformNotificationEvent):
    """Notify a private administrator session about a stored platform request."""

    def __init__(self, context, platform, admin_user_id, request_id, self_id, text):
        super().__init__(
            context,
            platform,
            MessageSession(
                platform.meta().id, MessageType.FRIEND_MESSAGE, admin_user_id
            ),
            f"qq_request_notification:{request_id}",
            self_id,
            text,
        )
        self.request_id = request_id


class ConfirmationResultEvent(PlatformNotificationEvent):
    """Keep the command's transport role while denying notification tool authority."""

    def __init__(self, context, platform, source, pending_id, result):
        text = (
            "[QQ 平台事件：操作确认结果。仅说明本次确认的处理结果，不是新的操作指令。]\n"
            + json.dumps(
                {
                    "确认编号": pending_id,
                    "确认用户 QQ": source.get_sender_id(),
                    "处理结果": result,
                },
                ensure_ascii=False,
            )
        )
        super().__init__(
            context,
            platform,
            source.session,
            f"qq_confirmation_result:{uuid4().hex}",
            source.get_self_id(),
            text,
            group=source.message_obj.group,
        )
        self.reply_target = (
            source.get_sender_id(),
            source.get_sender_name(),
            str(source.message_obj.message_id),
        )
        self.role = source.role


class NotificationOnlyTool(FunctionTool):
    """Keep a request-local tool schema without granting execution authority."""

    async def call(self, context, **kwargs) -> CallToolResult:
        """Reject calls originating from a notification rather than user intent.

        Args:
            context: Current agent execution context.
            **kwargs: Untrusted model-generated arguments, never executed.
        """

        return CallToolResult(
            isError=True,
            content=[
                TextContent(
                    type="text",
                    text="本轮仅用于说明平台事件或操作结果，不授权执行工具。本次工具调用未执行，不要再次执行已处理的操作。",
                )
            ],
        )
