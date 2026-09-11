from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from dataclasses import dataclass, field
from typing import ClassVar

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.provider import ProviderRequest
from astrbot.core.agent.message import Message, dump_messages_with_checkpoints
from astrbot.core.star.session_llm_manager import SessionServiceManager
from astrbot.core.utils.session_lock import session_lock_manager


ARRIVAL_KEY = "_qq_enhance_debounce_arrival"


@dataclass(eq=False)
class Arrival:
    """One pipeline and its independently prepared user input."""

    event: AstrMessageEvent
    task: asyncio.Task
    previous: Arrival | None = None
    ready: asyncio.Event = field(default_factory=asyncio.Event)
    finished: asyncio.Event = field(default_factory=asyncio.Event)
    request: ProviderRequest | None = None
    messages: list[dict] = field(default_factory=list)
    batch: list[Arrival] = field(default_factory=list)
    protected: bool = False
    persisted: bool = False
    persistence: asyncio.Task | None = None
    buffer_bytes: int = 0
    waited_seconds: float = 0.0


class ArrivalFilter(filter.CustomFilter):
    """Record pipeline order before asynchronous media preprocessing.

    The filter only records arrival; eligibility is checked by the handler after
    ordinary QQ enrichment and command processing have completed.
    """

    tails: ClassVar[dict[tuple, Arrival]] = {}

    def filter(self, event, cfg) -> bool:
        """Attach arrival state while AstrBot evaluates adapter filters.

        Args:
            event: Original adapter event.
            cfg: AstrBot session configuration.

        Returns:
            Whether this QQ input needs the later debounce handler.
        """
        if event.get_platform_name() != "aiocqhttp" or not event.get_sender_id():
            return False
        raw = getattr(event.message_obj, "raw_message", {})
        if not isinstance(raw, dict):
            return False
        if raw.get("post_type") != "message" and not (
            raw.get("post_type") == "notice"
            and raw.get("notice_type") == "notify"
            and raw.get("sub_type") == "poke"
            and str(raw.get("target_id")) == str(event.get_self_id())
        ):
            return False
        if event.get_extra(ARRIVAL_KEY) is not None:
            return True
        task = asyncio.current_task()
        if task is None:
            return False
        key = (
            asyncio.get_running_loop(),
            event.unified_msg_origin,
            event.get_sender_id(),
        )
        arrival = Arrival(event, task, self.tails.get(key))
        self.tails[key] = arrival
        event.set_extra(ARRIVAL_KEY, arrival)

        def completed(_task):
            arrival.finished.set()
            arrival.ready.set()
            arrival.previous = None
            if self.tails.get(key) is arrival:
                self.tails.pop(key, None)

        task.add_done_callback(completed)
        return True


def mark_content(content, marker: str):
    """Append a recall marker without replacing attachments or reminders.

    Args:
        content: Persisted content or runtime content parts.
        marker: Verified recall description.

    Returns:
        Content with exactly one copy of the marker.
    """
    if isinstance(content, str):
        return content if content.endswith("\n" + marker) else f"{content}\n{marker}"
    if isinstance(content, list):
        for part in content:
            text = (
                part.get("text")
                if isinstance(part, dict)
                else getattr(part, "text", None)
            )
            if text == marker:
                return content
        return [*content, {"type": "text", "text": marker}]
    return content


class MessageDebouncer:
    """Replace unfinished generations while persisting separate user inputs."""

    def __init__(self, plugin) -> None:
        self.plugin = plugin
        self.jobs: set[asyncio.Task] = set()
        self.pending: dict[tuple, asyncio.Task] = {}
        self.active: dict[tuple, Arrival] = {}
        self.failed: dict[tuple, Arrival] = {}
        self.early_recalls: dict[tuple, tuple[float, object]] = {}
        self.conflict_reported = False
        self.closed = False

    async def capture(self, event) -> None:
        """Wait for preparation, then supersede a cancellable earlier pipeline.

        Args:
            event: An enriched input that is eligible for the default LLM flow.
        """
        config = self.plugin.config["debounce"]
        arrival = event.get_extra(ARRIVAL_KEY)
        if self.closed or not config["enabled"] or arrival is None:
            return
        platform_id = self.plugin.config["platform"]["platform_id"]
        if platform_id and event.get_platform_id() != platform_id:
            return
        if event.is_stopped() or event._has_send_oper or event.call_llm:
            return
        if not event.is_at_or_wake_command:
            return
        cfg = self.plugin.context.get_config(umo=event.unified_msg_origin)
        runner = cfg.get("agent_runner", {})
        if isinstance(runner, dict) and runner.get("runner_type", "local") != "local":
            return
        if not cfg.get("provider_settings", {}).get("enable", True):
            return
        # Match the local Agent's input gate before cancelling anything. QQ
        # adapters may expose newer or adapter-specific components that are not
        # known to this plugin; any component is therefore eligible here and
        # keeps the debounce layer independent from the component registry.
        if not (event.message_str or "").strip() and not event.get_messages():
            return
        prefix = cfg.get("provider_settings", {}).get("wake_prefix", "")
        for wake_prefix in cfg.get("wake_prefix", []):
            if prefix.startswith(wake_prefix):
                prefix = prefix[len(wake_prefix) :]
                break
        if prefix and not event.message_str.startswith(prefix):
            return
        original = str(getattr(event.message_obj, "message_str", "") or "").lstrip()
        if any(
            original.startswith(prefix)
            for prefix in config["ignore_prefixes"]
            if prefix
        ):
            return
        for star in self.plugin.context.get_all_stars():
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
                return
        arrival.batch = [arrival]
        previous = arrival.previous
        # A failed database write remains retryable instead of silently losing
        # an input whose generation has already been cancelled.
        shared_group = config["shared_group"] and bool(event.get_group_id())
        scope = (
            event.unified_msg_origin,
            "group" if shared_group else event.get_sender_id(),
        )
        for (umo, _), job in list(self.pending.items()):
            if umo == event.unified_msg_origin and not job.done():
                await asyncio.shield(job)
        if failed := self.failed.get(scope):
            await self._persist(failed)
            self.failed.pop(scope, None)
        if previous is not None:
            await previous.ready.wait()
        active = self.active.get(scope)
        if active is not None and not active.finished.is_set():
            previous = active
        self.active[scope] = arrival

        def completed(_task):
            if self.active.get(scope) is arrival:
                self.active.pop(scope, None)

        arrival.task.add_done_callback(completed)
        if previous is None:
            window = float(config["initial_window_seconds"])
            maximum = float(config["max_wait_seconds"])
            if maximum > 0:
                window = min(window, maximum)
            if window > 0:
                await asyncio.sleep(window)
                arrival.waited_seconds = window
            return
        if previous.persistence and not previous.persistence.done():
            await asyncio.shield(previous.persistence)
        window = float(config["followup_window_seconds"])
        maximum = float(config["max_wait_seconds"])
        if maximum > 0:
            window = min(window, max(maximum - previous.waited_seconds, 0.0))
        if window > 0:
            await asyncio.sleep(window)
        arrival.waited_seconds = previous.waited_seconds + window
        result = previous.event.get_result()
        streaming = "STREAMING" in str(getattr(result, "result_content_type", ""))
        can_replace = (
            previous.messages
            and not previous.finished.is_set()
            and not previous.protected
            and not previous.event._has_send_oper
            and not previous.event.is_stopped()
            and not streaming
            and len(previous.batch) < config["max_messages"]
            and sum(item.buffer_bytes for item in previous.batch)
            <= config["max_buffer_mb"] * 1024 * 1024
        )
        if can_replace:
            if not await SessionServiceManager.should_process_llm_request(event):
                return
            # Recheck the conversation before cancellation: /new must not move
            # unfinished input from one conversation into another.
            cid = (
                await self.plugin.context.conversation_manager.get_curr_conversation_id(
                    event.unified_msg_origin
                )
            )
            can_replace = (
                cid == previous.request.conversation.cid
                and not previous.protected
                and not previous.event._has_send_oper
                and not previous.event.is_stopped()
                and not previous.finished.is_set()
                and "STREAMING"
                not in str(
                    getattr(previous.event.get_result(), "result_content_type", "")
                )
                and (
                    shared_group
                    or not any(
                        item.event.unified_msg_origin == event.unified_msg_origin
                        and item.event.get_sender_id() != event.get_sender_id()
                        and not item.finished.is_set()
                        for item in ArrivalFilter.tails.values()
                    )
                )
            )
        if can_replace:
            arrival.batch = [*previous.batch, arrival]
            previous.event.stop_event()
            # AstrBot cleans event-owned media in the cancelled pipeline's
            # finally block. Transfer ownership before issuing cancellation.
            paths = getattr(previous.event, "_temporary_local_files", [])
            for path in paths:
                event.track_temporary_local_file(path)
            paths.clear()
            previous.task.cancel()
            job = asyncio.create_task(self._persist_after_finish(previous, scope))
            arrival.persistence = job
            self.jobs.add(job)
            self.pending[scope] = job

            def persisted(done):
                self.jobs.discard(done)
                if self.pending.get(scope) is done:
                    self.pending.pop(scope, None)
                if not done.cancelled():
                    done.exception()  # Retrieve failures if the waiter was cancelled.

            job.add_done_callback(persisted)
            await asyncio.shield(job)
        else:
            # Finish this run before entering AstrBot's native follow-up path;
            # that path only carries text inside a tool result.
            await previous.finished.wait()
        arrival.previous = None

    async def _persist_after_finish(self, arrival: Arrival, scope: tuple) -> None:
        """Persist cancelled input even when its successor is interrupted.

        Args:
            arrival: Superseded pipeline with a normalized input snapshot.
            scope: Sender and conversation scope for retrying failed writes.
        """
        await arrival.finished.wait()
        try:
            await self._persist(arrival)
        except Exception:
            self.failed[scope] = arrival
            logger.exception("Failed to persist an unanswered QQ input")
            raise

    async def _persist(self, arrival: Arrival) -> None:
        """Save an unanswered input under AstrBot's conversation lock.

        Args:
            arrival: Prepared input whose pipeline was cancelled.
        """
        if arrival.persisted:
            return
        event = arrival.event
        cid = arrival.request.conversation.cid
        manager = self.plugin.context.conversation_manager
        async with session_lock_manager.acquire_lock(event.unified_msg_origin):
            conversation = await manager.get_conversation(event.unified_msg_origin, cid)
            if conversation is None:
                raise RuntimeError(
                    "The conversation for the unanswered QQ input was removed"
                )
            history = json.loads(conversation.history or "[]")
            if not isinstance(history, list):
                raise ValueError("Conversation history must be a list")
            messages = deepcopy(arrival.messages)
            recall = self.plugin.recall_messages.get(
                event.get_extra("_qq_enhance_recall_key")
            )
            if recall and recall["recalled"]:
                messages[-1]["content"] = mark_content(
                    messages[-1]["content"], recall["marker"]
                )
            index = len(history) + len(messages) - 1
            await manager.update_conversation(
                event.unified_msg_origin,
                cid,
                history=[*history, *messages],
                token_usage=None,
            )
            arrival.persisted = True
            if recall:
                recall["history_index"] = index
                recall["history_length"] = index
                recall["history_persisted"] = True
                recall["marked"] = recall["recalled"] and (
                    messages[-1]["content"]
                    == mark_content(recall["message_content"], recall["marker"])
                )
                if recall["recalled"] and not recall["marked"]:
                    recall["marked"] = await self.plugin._append_recall_marker(recall)
            # Only the input's size and source event are needed for later batch
            # limits and tool selection; release its full request history.
            arrival.request = None
            arrival.messages.clear()

    def bind_request(self, event, request) -> None:
        """Retain the finalized request without flattening its current input.

        Args:
            event: Current event.
            request: Fully decorated AstrBot provider request.
        """
        arrival = event.get_extra(ARRIVAL_KEY)
        if arrival is not None and arrival.batch:
            arrival.request = request

    def snapshot(self, event, run_context) -> None:
        """Capture normalized user content before generation and compression.

        Args:
            event: Current event.
            run_context: AstrBot's initialized agent context.
        """
        arrival = event.get_extra(ARRIVAL_KEY)
        if arrival is None or not arrival.batch or arrival.request is None:
            return
        request = arrival.request
        if request.conversation is None or not run_context.messages:
            arrival.protected = True
            arrival.ready.set()
            return
        current = run_context.messages[-1]
        if current.role != "user":
            arrival.protected = True
            arrival.ready.set()
            return
        # Include file extraction and other context entries introduced while
        # preparing this input, as well as its final multimodal user message.
        history = json.loads(request.conversation.history or "[]")
        contexts = request.contexts
        offset = len(contexts)
        if contexts[: len(history)] == history:
            offset = len(history)
        extra_count = sum(
            item.get("role") != "_checkpoint" for item in contexts[offset:]
        )
        contribution = run_context.messages[-(extra_count + 1) :]
        arrival.messages = deepcopy(dump_messages_with_checkpoints(contribution))
        arrival.buffer_bytes = len(
            json.dumps(arrival.messages, ensure_ascii=False).encode("utf-8")
        )
        key = event.get_extra("_qq_enhance_recall_key")
        recall = self.plugin.recall_messages.get(key)
        if recall:
            recall["message_content"] = deepcopy(arrival.messages[-1]["content"])
            recall["history_index"] = len(contexts)
            recall["live_message"] = current
        # Rebind previously tracked inputs to the new runtime objects. A recall
        # during generation must not be overwritten by the later history save.
        runtime_messages = (
            run_context.messages[1:] if request.system_prompt else run_context.messages
        )
        for entry in self.plugin.recall_messages.values():
            if (
                entry["conversation_id"] != request.conversation.cid
                or entry["unified_msg_origin"] != event.unified_msg_origin
                or "message_content" not in entry
            ):
                continue
            index = entry.get("history_index", -1)
            runtime_index = sum(
                item.get("role") != "_checkpoint" for item in contexts[:index]
            )
            if 0 <= runtime_index < len(runtime_messages):
                message = runtime_messages[runtime_index]
                content = dump_messages_with_checkpoints([message])[0]["content"]
                original = entry["message_content"]
                if content == original or (
                    entry["recalled"]
                    and content == mark_content(original, entry["marker"])
                ):
                    entry["live_message"] = message
                    if entry["recalled"]:
                        message.content = Message.model_validate(
                            {
                                "role": "user",
                                "content": mark_content(
                                    message.content, entry["marker"]
                                ),
                            }
                        ).content
        arrival.ready.set()

    def protect(self, event) -> None:
        """Make a pipeline non-cancellable once it can have visible effects.

        Args:
            event: Pipeline about to execute a tool or complete generation.
        """
        if arrival := event.get_extra(ARRIVAL_KEY):
            arrival.protected = True

    async def close(self) -> None:
        """Finish outstanding persistence without cancelling ordinary replies."""
        self.closed = True
        if self.jobs:
            await asyncio.gather(*self.jobs, return_exceptions=True)
        for arrival in list(self.failed.values()):
            await self._persist(arrival)
        self.failed.clear()
        self.active.clear()
        self.pending.clear()
        self.early_recalls.clear()
