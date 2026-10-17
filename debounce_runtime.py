"""AstrBot eligibility, persistence and native-pipeline continuation."""

import json
from copy import copy, deepcopy

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent
from astrbot.api.message_components import Plain
from astrbot.api.provider import ProviderRequest
from astrbot.core.star.session_llm_manager import SessionServiceManager
from astrbot.core.star.session_plugin_manager import SessionPluginManager
from astrbot.core.utils.session_lock import session_lock_manager

from .debounce import ARRIVAL_KEY


class ResumedMessageEvent(AstrMessageEvent):
    """Resume an existing reply using its original identity and transport."""

    def __init__(self, source, debouncer):
        self._resume_authorized = False
        self.transport = copy(source)
        self.transport._temporary_local_files = []
        message = deepcopy(source.message_obj)
        message.message = [Plain("继续处理已有的待回复批次")]
        message.message_str = "继续处理已有的待回复批次"
        message.raw_message = {"post_type": "notice", "notice_type": "debounce_resume"}
        super().__init__(
            message.message_str, message, source.platform_meta, source.session_id
        )
        self.session = deepcopy(source.session)
        self.role = source.role
        self.is_wake = True
        self.debouncer = debouncer
        self.debounce_sender_id = getattr(source, "debounce_sender_id", None)
        self.notification_only = getattr(source, "notification_only", False)

    @property
    def is_at_or_wake_command(self):
        return self._resume_authorized

    @is_at_or_wake_command.setter
    def is_at_or_wake_command(self, value):
        # Waking checks alone cannot grant a continuation a new reply.
        pass

    def authorize_resume(self):
        self._resume_authorized = True

    @AstrMessageEvent.session_id.setter
    def session_id(self, value):
        # Waking-stage group isolation must retain the original destination.
        if value == self.session.session_id:
            self.session.session_id = value

    def is_stopped(self):
        return (
            super().is_stopped()
            or self.debouncer.closed
            or not self.debouncer.config["enabled"]
            or (
                self.plugins_name is not None
                and "astrbot_plugin_qq_enhance" not in self.plugins_name
            )
        )

    def cleanup_temporary_local_files(self):
        super().cleanup_temporary_local_files()
        self.debouncer.release_unclaimed_resume(self)

    async def send(self, message):
        if self.is_stopped():
            return
        await self.transport.send(message)
        await super().send(message)

    async def send_streaming(self, generator, use_fallback=False):
        if self.is_stopped():
            return
        await self.transport.send_streaming(generator, use_fallback=use_fallback)
        self._has_send_oper = self.transport._has_send_oper


class AstrBotDebounceRuntime:
    def __init__(self, context, config):
        self.context = context
        self.config = config
        self.conflict_reported = False

    def eligible(self, event):
        if event.is_stopped() or event._has_send_oper or event.call_llm:
            return False
        if not event.is_at_or_wake_command:
            return False
        cfg = self.context.get_config(umo=event.unified_msg_origin)
        if (
            cfg.get("provider_settings", {}).get("agent_runner_type", "local")
            != "local"
        ):
            return False
        if not cfg.get("provider_settings", {}).get("enable", True):
            return False
        if not (event.message_str or "").strip() and not event.get_messages():
            return False
        prefix = cfg.get("provider_settings", {}).get("wake_prefix", "")
        for wake_prefix in cfg.get("wake_prefix", []):
            if prefix.startswith(wake_prefix):
                prefix = prefix[len(wake_prefix) :]
                break
        if prefix and not event.message_str.startswith(prefix):
            return False
        original = str(getattr(event.message_obj, "message_str", "") or "").lstrip()
        if any(original.startswith(p) for p in self.config["ignore_prefixes"] if p):
            return False
        for star in self.context.get_all_stars():
            if (
                star.name == "astrbot_plugin_message_merger"
                and star.activated
                and (star.config is None or star.config.get("enabled", True))
            ):
                if not self.conflict_reported:
                    logger.warning(
                        "QQ debounce is inactive while message_merger is enabled"
                    )
                    self.conflict_reported = True
                return False
        return True

    async def can_resume(self, arrival):
        event = arrival.event
        if not await self.request_allowed(event):
            return False
        cfg = self.context.get_config(umo=event.unified_msg_origin)
        plugin_set = cfg.get("plugin_set", ["*"])
        return (
            self.config["enabled"]
            and (plugin_set == ["*"] or "astrbot_plugin_qq_enhance" in plugin_set)
            and await SessionPluginManager.is_plugin_enabled_for_session(
                event.unified_msg_origin, "astrbot_plugin_qq_enhance"
            )
            and cfg.get("provider_settings", {}).get("enable", True)
            and cfg.get("provider_settings", {}).get("agent_runner_type", "local")
            == "local"
            and await self.context.conversation_manager.get_curr_conversation_id(
                event.unified_msg_origin
            )
            == arrival.conversation_id
        )

    async def request_allowed(self, event):
        return await SessionServiceManager.should_process_llm_request(event)

    async def persist(self, arrival):
        if not arrival.messages:
            return
        manager = self.context.conversation_manager
        umo = arrival.event.unified_msg_origin
        async with session_lock_manager.acquire_lock(umo):
            conversation = await manager.get_conversation(umo, arrival.conversation_id)
            if conversation is None:
                raise RuntimeError(
                    "The conversation for the unanswered input was removed"
                )
            history = json.loads(conversation.history or "[]")
            if not isinstance(history, list):
                raise ValueError("Conversation history must be a list")
            await manager.update_conversation(
                umo,
                arrival.conversation_id,
                history=[*history, *deepcopy(arrival.messages)],
                token_usage=None,
            )
            for item in arrival.context_inputs:
                if item.key in arrival.seen_context and not item.saved.done():
                    item.saved.set_result(True)

    def make_resume(self, arrival, debouncer):
        return ResumedMessageEvent(arrival.event, debouncer)

    async def enqueue_resume(self, arrival):
        await self.context.get_event_queue().put(arrival.event)

    @staticmethod
    def discard_resume(event):
        event.stop_event()
        event.cleanup_temporary_local_files()

    async def prepare_resume(self, event):
        arrival = event.get_extra(ARRIVAL_KEY)
        if event.is_stopped() or not await self.can_resume(arrival):
            event.stop_event()
            return
        conversation = await self.context.conversation_manager.get_conversation(
            event.unified_msg_origin, arrival.conversation_id
        )
        if conversation is None:
            event.stop_event()
            return
        event.set_extra(
            "provider_request",
            ProviderRequest(
                prompt=event.message_str,
                conversation=conversation,
            ),
        )
        event.authorize_resume()

    async def finalize_resume(self, event, request):
        """Run under AstrBot's lock; use saved inputs without appending a fake one."""
        arrival = event.get_extra(ARRIVAL_KEY)
        if not await self.can_resume(arrival):
            event.stop_event()
            return
        conversation = await self.context.conversation_manager.get_conversation(
            event.unified_msg_origin, arrival.conversation_id
        )
        if conversation is None:
            event.stop_event()
            return
        request.conversation = conversation
        request.contexts = json.loads(conversation.history or "[]")
        request.prompt = None
        request.image_urls = []
        request.audio_urls = []
        request.extra_user_content_parts = []
