from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal


_RANDOM_FACE_TYPES: dict[str, Literal["dice", "rps", "basketball"]] = {
    "114": "basketball",
    "358": "dice",
    "359": "rps",
}
_DICE_RESULTS = frozenset({"1", "2", "3", "4", "5", "6"})
_RPS_RESULTS = {"1": "布", "2": "剪刀", "3": "石头"}
# NapCat 4.18.19 captures paired with the user's observations on Oct 16/17:
# 2 scored; 3 (ball stuck on the rim), 4 and 5 missed. The Oct 17 sequence
# 3, 5, 2, 4 confirms both the new variants and the earlier 2/4 mapping.
_BASKETBALL_RESULTS = {
    "2": "进球",
    "3": "未进球（卡篮筐）",
    "4": "未进球",
    "5": "未进球",
}


@dataclass(frozen=True, slots=True)
class RandomComponent:
    """A recognized random component, with no inferred result when absent."""

    kind: Literal["dice", "rps", "basketball"]
    result: str | None
    result_provided: bool


def _scalar(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if type(value) is int:
        return str(value)
    return ""


def parse_random_component(component: Any) -> RandomComponent | None:
    """Decode NapCat dice/rps or native QQ random faces.

    SnowLuma v1.14.22 reports face 358/359 with resultId. Its result values
    are one-based: dice 1–6 and rps 1=布, 2=剪刀, 3=石头. Basketball (114)
    uses only observed scoring results: 2=进球, 3=未进球（卡篮筐）, 4/5=未进球.
    Other identifiers, including zero, remain unknown rather than being assigned
    an outcome.
    Other animated faces may also carry resultId and must remain face components.
    """
    if not isinstance(component, Mapping):
        return None
    data = component.get("data")
    if not isinstance(data, Mapping):
        return None
    component_type = component.get("type")
    if not isinstance(component_type, str):
        return None
    component_type = component_type.strip().lower()
    if component_type == "face":
        kind = _RANDOM_FACE_TYPES.get(_scalar(data.get("id")))
        if kind is None:
            return None
        raw_result = data.get("resultId")
        if kind == "basketball":
            raw = data.get("raw")
            if isinstance(raw, Mapping):
                # An explicitly ordinary basketball has no random outcome.
                if _scalar(raw.get("faceType")) in {"1", "2"}:
                    return None
                if "resultId" not in data:
                    raw_result = raw.get("resultId")
    elif component_type in {"dice", "rps"}:
        kind = "dice" if component_type == "dice" else "rps"
        raw_result = data.get("result")
    else:
        return None

    value = _scalar(raw_result)
    if kind == "dice":
        result = value if value in _DICE_RESULTS else None
    elif kind == "rps":
        result = _RPS_RESULTS.get(value)
    else:
        result = _BASKETBALL_RESULTS.get(value)
    return RandomComponent(
        kind=kind,
        result=result,
        result_provided=bool(value)
        if isinstance(raw_result, str)
        else raw_result is not None,
    )
