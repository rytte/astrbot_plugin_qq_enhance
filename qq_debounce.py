"""QQ input selection and message references, outside the batch scheduler."""

from astrbot.api.event import filter

from .debounce import ArrivalRegistry
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
        return ArrivalRegistry.record(event)


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
