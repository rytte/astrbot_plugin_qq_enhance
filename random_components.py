from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal


_RANDOM_FACE_TYPES: dict[str, Literal["dice", "rps"]] = {
    "358": "dice",
    "359": "rps",
}
_DICE_RESULTS = frozenset({"1", "2", "3", "4", "5", "6"})
_RPS_RESULTS = {"1": "布", "2": "剪刀", "3": "石头"}


@dataclass(frozen=True, slots=True)
class RandomComponent:
    """A recognized random component, with no inferred result when absent."""

    kind: Literal["dice", "rps"]
    result: str | None
    result_provided: bool


def _scalar(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if type(value) is int:
        return str(value)
    return ""


def parse_random_component(component: Any) -> RandomComponent | None:
    """Decode NapCat dice/rps or SnowLuma's native QQ random faces.

    SnowLuma v1.14.22 reports face 358/359 with resultId. Its result values
    are one-based: dice 1–6 and rps 1=布, 2=剪刀, 3=石头. Other animated
    faces may also carry resultId and must remain ordinary face components.
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
    elif component_type in {"dice", "rps"}:
        kind = "dice" if component_type == "dice" else "rps"
        raw_result = data.get("result")
    else:
        return None

    value = _scalar(raw_result)
    if kind == "dice":
        result = value if value in _DICE_RESULTS else None
    else:
        result = _RPS_RESULTS.get(value)
    return RandomComponent(
        kind=kind,
        result=result,
        result_provided=bool(value)
        if isinstance(raw_result, str)
        else raw_result is not None,
    )
