from __future__ import annotations

from mcp.types import CallToolResult, TextContent

from astrbot.api.event import AstrMessageEvent, MessageChain
from astrbot.api.message_components import Plain
from astrbot.core.agent.tool import FunctionTool
from astrbot.core.platform.astrbot_message import AstrBotMessage, MessageMember
from astrbot.core.platform.message_type import MessageType
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)


class RequestNotificationEvent(AiocqhttpMessageEvent):
    """Deliver a platform event through the target private conversation.

    Args:
        context: Plugin context used to route outgoing messages.
        platform: Originating OneBot platform instance.
        admin_user_id: Notification recipient, not the event sender.
        request_id: Trusted locally stored request identifier.
        self_id: Bot account associated with the original platform event.
        text: Platform facts presented as the current user input.
    """

    def __init__(self, context, platform, admin_user_id, request_id, self_id, text):
        message = AstrBotMessage()
        message.type = MessageType.FRIEND_MESSAGE
        message.self_id = self_id
        message.session_id = admin_user_id
        message.message_id = f"qq_request_notification:{request_id}:{admin_user_id}"
        message.sender = MessageMember(
            user_id=f"qq_request_notification:{request_id}", nickname="QQ 平台事件"
        )
        message.message = [Plain(text)]
        message.message_str = text
        message.raw_message = {
            "post_type": "notice",
            "notice_type": "qq_enhance_request_notification",
        }
        super().__init__(
            text, message, platform.meta(), admin_user_id, platform.get_client()
        )
        self.context = context
        self.request_id = request_id
        self.is_wake = True
        self.is_at_or_wake_command = True

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
        if not await self.context.send_message(self.session, message):
            raise RuntimeError("QQ 申请通知发送失败：目标平台不可用")
        await AstrMessageEvent.send(self, message)


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
                    text="本轮是平台申请通知，不是管理员指令。未执行任何工具，请等待管理员明确操作。",
                )
            ],
        )
