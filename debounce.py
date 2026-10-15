from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from dataclasses import dataclass, field
from itertools import count
from typing import ClassVar

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent
from astrbot.api.provider import ProviderRequest
from astrbot.core.agent.message import dump_messages_with_checkpoints


ARRIVAL_KEY = "_qq_enhance_debounce_arrival"
_ARRIVAL_ORDER = count()


@dataclass(eq=False)
class ContextInput:
    """An input without wake authority, saved by its owning source."""

    key: tuple
    saved: asyncio.Future[bool]
    content: str = ""
    wait_applied: bool = False
    conversation_id: str | None = None


@dataclass(eq=False)
class Arrival:
    """One pipeline and its independently prepared user input."""

    event: AstrMessageEvent
    task: asyncio.Task | None
    previous: Arrival | None = None
    ready: asyncio.Event = field(default_factory=asyncio.Event)
    finished: asyncio.Event = field(default_factory=asyncio.Event)
    history_ready: asyncio.Event = field(default_factory=asyncio.Event)
    request: ProviderRequest | None = None
    messages: list[dict] = field(default_factory=list)
    batch: list[Arrival] = field(default_factory=list)
    protected: bool = False
    persisted: bool = False
    superseded: bool = False
    persistence: asyncio.Task | None = None
    buffer_bytes: int = 0
    waited_seconds: float = 0.0
    conversation_id: str | None = None
    context_inputs: list[ContextInput] = field(default_factory=list)
    waiting: bool = False
    wait_changed: asyncio.Event = field(default_factory=asyncio.Event)
    replayed: bool = False
    scope: tuple | None = None
    seen_context: set[tuple] = field(default_factory=set)
    order: int = field(default_factory=lambda: next(_ARRIVAL_ORDER))


class ArrivalRegistry:
    """Platform-independent arrival order before asynchronous preparation."""

    tails: ClassVar[dict[tuple, Arrival]] = {}

    @classmethod
    def record(cls, event) -> bool:
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
        arrival = Arrival(event, task, cls.tails.get(key))
        cls.tails[key] = arrival
        event.set_extra(ARRIVAL_KEY, arrival)

        cls.bind_completion(arrival, key)
        return True

    @classmethod
    def bind_completion(cls, arrival, key=None):

        def completed(_task):
            arrival.finished.set()
            arrival.ready.set()
            if not arrival.superseded:
                arrival.history_ready.set()
            arrival.previous = None
            if cls.tails.get(key) is arrival:
                cls.tails.pop(key, None)

        arrival.task.add_done_callback(completed)

    @classmethod
    def predecessors(cls, umo=None):
        found = set()
        for arrival in list(cls.tails.values()):
            while arrival is not None and arrival not in found:
                found.add(arrival)
                if umo is None or arrival.event.unified_msg_origin == umo:
                    yield arrival
                arrival = arrival.previous


class MessageDebouncer:
    """Replace unfinished generations while persisting separate user inputs."""

    def __init__(self, runtime) -> None:
        self.runtime = runtime
        self.config = runtime.config
        self.jobs: set[asyncio.Task] = set()
        self.pending: dict[tuple, asyncio.Task] = {}
        self.active: dict[tuple, Arrival] = {}
        self.failed: dict[tuple, Arrival] = {}
        self.context_jobs: dict[tuple, asyncio.Task] = {}
        self.context_targets: dict[tuple, Arrival] = {}
        self.closed = False

    async def capture(self, event) -> None:
        """Wait for preparation, then supersede a cancellable earlier pipeline.

        Args:
            event: An enriched input that is eligible for the default LLM flow.
        """
        config = self.config
        arrival = event.get_extra(ARRIVAL_KEY)
        if self.closed or not config["enabled"] or arrival is None:
            return
        if arrival.replayed:
            await self.runtime.prepare_resume(event)
            return
        if not self.runtime.eligible(event) or not await self.runtime.request_allowed(
            event
        ):
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
        arrival.scope = scope
        if (
            job := self.context_jobs.get(scope)
        ) and arrival.order > self.context_targets[scope].order:
            await asyncio.shield(job)
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
            await previous.ready.wait()
        self.active[scope] = arrival

        self._bind_active(arrival)
        if previous is None:
            window = float(config["initial_window_seconds"])
            await self._wait(arrival, window)
            return
        if previous.persistence and not previous.persistence.done():
            await asyncio.shield(previous.persistence)
        window = float(config["followup_window_seconds"])
        await self._wait(arrival, window, previous.waited_seconds)
        can_replace = (
            self._replaceable(previous)
            and len(previous.batch) + len(previous.context_inputs)
            < config["max_messages"]
            and sum(item.buffer_bytes for item in previous.batch)
            + sum(len(i.content.encode("utf-8")) for i in previous.context_inputs)
            <= config["max_buffer_mb"] * 1024 * 1024
        )
        if can_replace:
            # Recheck the conversation before cancellation: /new must not move
            # unfinished input from one conversation into another.
            can_replace = await self.runtime.can_resume(previous) and self._replaceable(
                previous
            )
        if can_replace:
            arrival.batch = [*previous.batch, arrival]
            arrival.context_inputs = [*previous.context_inputs, *arrival.context_inputs]
            job = self._replace(previous, arrival)
            await asyncio.shield(job)
        else:
            # Finish this run before entering AstrBot's native follow-up path;
            # that path only carries text inside a tool result.
            await previous.finished.wait()
        arrival.previous = None

    def _bind_active(self, arrival):
        def completed(_task):
            if self.active.get(arrival.scope) is arrival:
                self.active.pop(arrival.scope, None)

        arrival.task.add_done_callback(completed)

    async def _wait(self, arrival, seconds, already_waited=0.0):
        """Restart a live window on updates, with one cumulative time budget."""
        loop = asyncio.get_running_loop()
        start = loop.time()
        maximum = float(self.config["max_wait_seconds"])
        limit = (
            start + max(maximum - already_waited, 0.0) if maximum > 0 else float("inf")
        )
        deadline = min(start + seconds, limit)
        arrival.waiting = True
        try:
            while deadline > loop.time():
                arrival.wait_changed.clear()
                try:
                    await asyncio.wait_for(
                        arrival.wait_changed.wait(), deadline - loop.time()
                    )
                except TimeoutError:
                    # Event-loop timers can fire slightly before their deadline.
                    # Also retain an update racing with timeout delivery.
                    if not arrival.wait_changed.is_set():
                        continue
                deadline = min(
                    loop.time() + float(self.config["followup_window_seconds"]), limit
                )
        finally:
            arrival.waiting = False
            arrival.waited_seconds = already_waited + min(
                loop.time() - start, max(deadline - start, 0.0)
            )
            if maximum > 0:
                arrival.waited_seconds = min(arrival.waited_seconds, maximum)

    def _replace(self, previous, successor):
        previous.event.stop_event()
        paths = getattr(previous.event, "_temporary_local_files", [])
        for path in paths:
            successor.event.track_temporary_local_file(path)
        paths.clear()
        previous.superseded = True
        previous.task.cancel()
        scope = successor.scope
        job = asyncio.create_task(self._persist_after_finish(previous, scope))
        successor.persistence = job
        self.jobs.add(job)
        self.pending[scope] = job

        def persisted(done):
            self.jobs.discard(done)
            if self.pending.get(scope) is done:
                self.pending.pop(scope, None)
            if not done.cancelled():
                done.exception()

        job.add_done_callback(persisted)
        return job

    def submit_context(self, related: Arrival, item: ContextInput) -> bool:
        """Join an existing input without granting a source wake authority."""
        if (
            self.closed
            or not self.config["enabled"]
            or related.finished.is_set()
            and not related.superseded
        ):
            return False
        scope = (
            related.event.unified_msg_origin,
            "group"
            if self.config["shared_group"] and related.event.get_group_id()
            else related.event.get_sender_id(),
        )
        owner = self.active.get(scope) or related
        if related.order > owner.order:
            # An earlier pipeline must be allowed to finish preparing before
            # the latest input can inherit its batch and this context update.
            owner = related
        if owner is not related and related not in owner.batch:
            # A later pipeline may still be preparing its inherited batch.
            if owner.previous is not related and not any(
                related in a.batch for a in owner.batch
            ):
                return False
        if (
            owner.finished.is_set()
            or owner.protected
            or owner.event._has_send_oper
            or owner.event.is_stopped()
        ):
            return False
        if any(existing.key == item.key for existing in owner.context_inputs):
            return False
        if len(owner.batch) + len(owner.context_inputs) >= self.config["max_messages"]:
            return False
        if (
            sum(a.buffer_bytes for a in owner.batch)
            + sum(len(i.content.encode("utf-8")) for i in owner.context_inputs)
            + len(item.content.encode("utf-8"))
            > self.config["max_buffer_mb"] * 1024 * 1024
        ):
            return False
        owner.context_inputs.append(item)
        if owner.waiting:
            item.wait_applied = True
            owner.wait_changed.set()
        previous_job = self.context_jobs.get(scope)
        if (
            previous_job is None
            or previous_job.done()
            or owner.order > self.context_targets[scope].order
        ):
            self.context_targets[scope] = owner
            job = asyncio.create_task(
                self._continue_context(
                    scope,
                    owner,
                    previous_job if previous_job and not previous_job.done() else None,
                )
            )
            self.context_jobs[scope] = job

            def completed(done):
                if self.context_jobs.get(scope) is done:
                    self.context_jobs.pop(scope, None)
                    self.context_targets.pop(scope, None)
                if not done.cancelled():
                    done.exception()

            job.add_done_callback(completed)
        return True

    def arrivals(self, umo=None):
        """Snapshot inputs including queued continuations and media preparation."""
        return tuple(
            dict.fromkeys(
                arrival
                for arrival in (
                    *ArrivalRegistry.predecessors(umo),
                    *self.active.values(),
                )
                if umo is None or arrival.event.unified_msg_origin == umo
            )
        )

    def context_arrivals(self, arrivals, umo, cid, *, sender_id=None):
        """Select the latest existing input per scope for a pinned context fact."""
        selected = {}
        for arrival in arrivals:
            event = arrival.event
            if (
                event.unified_msg_origin != umo
                or arrival.finished.is_set()
                or arrival.conversation_id not in (None, cid)
                or not (arrival.batch or self.runtime.eligible(event))
            ):
                continue
            shared = self.config["shared_group"] and bool(event.get_group_id())
            if (
                sender_id is not None
                and not shared
                and event.get_sender_id() != sender_id
            ):
                continue
            scope = (umo, "group" if shared else event.get_sender_id())
            if scope not in selected or arrival.order > selected[scope].order:
                selected[scope] = arrival
        return tuple(selected.values())

    def context_barriers(self, related):
        """Keep a source's history entry behind the live batch's current input."""
        if related is None:
            return ()
        for owner in self.active.values():
            # A continuation adds no new user input. Its original batch has
            # its own persistence barriers; waiting for this run would make
            # event delivery and the restart wait on each other.
            if (
                (
                    owner is related
                    or related in owner.batch
                    or owner.previous is related
                )
                and not owner.replayed
                and not owner.history_ready.is_set()
            ):
                return (owner,)
        return ()

    def _replaceable(self, arrival):
        return bool(
            (arrival.messages or arrival.replayed)
            and not arrival.finished.is_set()
            and not arrival.protected
            and not arrival.event._has_send_oper
            and not arrival.event.is_stopped()
            and "STREAMING"
            not in str(getattr(arrival.event.get_result(), "result_content_type", ""))
            and (
                self.config["shared_group"]
                or not any(
                    item.event.unified_msg_origin == arrival.event.unified_msg_origin
                    and item.event.get_sender_id() != arrival.event.get_sender_id()
                    and not item.finished.is_set()
                    for item in ArrivalRegistry.predecessors()
                )
            )
        )

    def _within_budget(self, arrival):
        return (
            len(arrival.batch) + len(arrival.context_inputs)
            <= self.config["max_messages"]
            and sum(a.buffer_bytes for a in arrival.batch)
            + sum(len(i.content.encode("utf-8")) for i in arrival.context_inputs)
            <= self.config["max_buffer_mb"] * 1024 * 1024
        )

    async def _continue_context(self, scope, related, previous_job=None):
        try:
            if previous_job is not None:
                await previous_job
            await related.ready.wait()
            owner = self.active.get(scope)
            if owner is None or owner.finished.is_set():
                return
            await owner.ready.wait()
            owner.context_inputs[:] = [
                item
                for item in owner.context_inputs
                if not item.saved.done()
                or not item.saved.cancelled()
                and item.saved.result()
            ]
            unseen = [
                item
                for item in owner.context_inputs
                if item.key not in owner.seen_context
                and item.conversation_id in (None, owner.conversation_id)
            ]
            if not unseen or not self._replaceable(owner):
                return
            if owner.persistence:
                await asyncio.shield(owner.persistence)
            if not all(item.wait_applied for item in unseen):
                await self._wait(
                    owner,
                    float(self.config["followup_window_seconds"]),
                    owner.waited_seconds,
                )
            if (
                not self._replaceable(owner)
                or not self._within_budget(owner)
                or not await self.runtime.can_resume(owner)
            ):
                return
            # Recheck after eligibility awaits; the batch may have completed.
            if self.active.get(scope) is not owner or not self._replaceable(owner):
                return
            event = self.runtime.make_resume(owner, self)
            successor = Arrival(
                event, None, replayed=True, scope=scope, order=owner.order
            )
            successor.batch = list(owner.batch)
            successor.context_inputs = list(owner.context_inputs)
            successor.conversation_id = owner.conversation_id
            successor.waited_seconds = owner.waited_seconds
            event.set_extra(ARRIVAL_KEY, successor)
            self.active[scope] = successor
            await asyncio.shield(self._replace(owner, successor))
            for item in successor.context_inputs:
                if not await asyncio.shield(item.saved):
                    raise RuntimeError(
                        "Background input was not saved; reply restart aborted"
                    )
            if self.closed or not await self.runtime.can_resume(successor):
                self.runtime.discard_resume(event)
                self.active.pop(scope, None)
                return
            await self.runtime.enqueue_resume(successor)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Failed to continue a debounced reply with background input"
            )
            active = self.active.get(scope)
            if active is not None and active.replayed and active.task is None:
                self.runtime.discard_resume(active.event)
                self.active.pop(scope, None)

    def claim_resume(self, event):
        arrival = event.get_extra(ARRIVAL_KEY)
        if (
            self.closed
            or self.active.get(arrival.scope) is not arrival
            or event.is_stopped()
        ):
            event.stop_event()
            return False
        if arrival.task is not None:
            return False
        arrival.task = asyncio.current_task()
        ArrivalRegistry.bind_completion(arrival)
        self._bind_active(arrival)
        return True

    def release_unclaimed_resume(self, event):
        """Release queued work skipped before the adapter hook can claim it."""
        arrival = event.get_extra(ARRIVAL_KEY)
        if arrival is None or arrival.task is not None:
            return
        arrival.finished.set()
        arrival.ready.set()
        arrival.history_ready.set()
        if self.active.get(arrival.scope) is arrival:
            self.active.pop(arrival.scope, None)

    @staticmethod
    def batch_text(event):
        arrival = event.get_extra(ARRIVAL_KEY)
        if arrival is not None and arrival.batch:
            return "\n".join(item.event.message_str or "" for item in arrival.batch)
        return event.message_str or ""

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
            logger.exception("Failed to persist an unanswered input")
            raise

    async def _persist(self, arrival: Arrival) -> None:
        """Save an unanswered input under AstrBot's conversation lock.

        Args:
            arrival: Prepared input whose pipeline was cancelled.
        """
        if arrival.persisted:
            return
        await self.runtime.persist(arrival)
        arrival.persisted = True
        arrival.history_ready.set()
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
            if request.conversation is not None:
                arrival.conversation_id = request.conversation.cid

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
        arrival.seen_context = {
            item.key
            for item in arrival.context_inputs
            if item.saved.done() and not item.saved.cancelled() and item.saved.result()
        }
        if arrival.replayed:
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
        context_jobs = list(self.context_jobs.values())
        for job in context_jobs:
            job.cancel()
        if context_jobs:
            await asyncio.gather(*context_jobs, return_exceptions=True)
        resumed_tasks = []
        for arrival in list(self.active.values()):
            if arrival.replayed:
                arrival.event.stop_event()
                if arrival.task is not None and not arrival.task.done():
                    arrival.task.cancel()
                    resumed_tasks.append(arrival.task)
                elif arrival.task is None:
                    self.runtime.discard_resume(arrival.event)
        if resumed_tasks:
            await asyncio.gather(*resumed_tasks, return_exceptions=True)
        if self.jobs:
            await asyncio.gather(*self.jobs, return_exceptions=True)
        for arrival in list(self.failed.values()):
            await self._persist(arrival)
        self.failed.clear()
        self.active.clear()
        self.pending.clear()
        self.context_jobs.clear()
        self.context_targets.clear()
