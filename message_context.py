"""Attach QQ message IDs only to AstrBot's formatted group context."""

from functools import wraps

from astrbot.builtin_stars.astrbot.group_chat_context import GroupChatContext


class GroupMessageIdHook:
    """Keep history metadata outside the shared inbound message chain."""

    def __init__(self, plugin):
        self.plugin = plugin
        self.active = False
        self.original = None
        self.wrapper = None

    def install(self):
        if self.active:
            return
        original = GroupChatContext._format_message

        @wraps(original)
        async def format_message(context, event, cfg):
            text = await original(context, event, cfg)
            if (
                self.active
                and self.wrapper is format_message
                and event.get_group_id()
                and any(
                    handler.handler == self.plugin.enrich_inbound_qq_components
                    for handler in event.get_extra("activated_handlers", [])
                )
                and (tag := self.plugin._message_id_tag(event))
            ):
                # Native handler selection already applied profile and session
                # plugin settings. Only the recorder's private text gets a tag.
                text = f"{text} {tag}"
            return text

        self.original = original
        self.wrapper = format_message
        self.active = True
        GroupChatContext._format_message = format_message

    def close(self):
        self.active = False
        if (
            self.wrapper is not None
            and GroupChatContext._format_message is self.wrapper
        ):
            GroupChatContext._format_message = self.original
