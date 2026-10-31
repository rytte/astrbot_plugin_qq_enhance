"""QQ input selection and message references, outside the batch scheduler."""

from astrbot.api.event import filter

from .debounce import ARRIVAL_KEY, ArrivalRegistry
from .debounce_runtime import ResumedMessageEvent


class ArrivalFilter(filter.CustomFilter):
    def filter(self, event, cfg) -> bool:
        if isinstance(event, ResumedMessageEvent):
            return event.debouncer.claim_resume(event)
        if event.get_platform_name() != "aiocqhttp" or not event.get_sender_id():
            return False
        raw = getattr(event.message_obj, "raw_message", {})
        if not isinstance(raw, dict):
            return False
        if (
            not getattr(event, "notice_response", False)
            and raw.get("post_type") != "message"
        ):
            return False
        if not ArrivalRegistry.record(event):
            return False
        if (
            not event.is_at_or_wake_command
            and event.get_group_id()
            and raw.get("post_type") == "message"
        ):
            arrival = event.get_extra(ARRIVAL_KEY)
            for owner in tuple(ArrivalRegistry.wake_windows):
                if owner.debouncer is not None and owner.debouncer.offer_wake(
                    arrival, owner
                ):
                    break
            if arrival.wake_source is None:
                source = arrival.previous
                # A rapid continuation may precede both a plugin's wake hook
                # and the debounce handler. Qualification still requires the
                # earlier input to open a real window.
                if (
                    source is not None
                    and not source.wake_checked.is_set()
                    and not source.event.is_stopped()
                    and not source.event._has_send_oper
                ):
                    arrival.wake_pending = source
                    source.wake_followups.add(arrival)
        return True


def message_reference(event) -> tuple | None:
    raw = getattr(event.message_obj, "raw_message", None)
    if not isinstance(raw, dict) or raw.get("post_type") != "message":
        return None
    kind = raw.get("message_type")
    if kind not in {"group", "private"}:
        return None
    scope = raw.get("group_id") if kind == "group" else raw.get("user_id")
    return (str(event.get_platform_id()), kind, str(scope), str(raw.get("message_id")))


def find_message_arrival(reference):
    return next(
        (
            arrival
            for arrival in ArrivalRegistry.predecessors()
            if message_reference(arrival.event) == reference
        ),
        None,
    )
