from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image as PillowImage

from astrbot.api import logger
from astrbot.api.message_components import Image, Plain
from astrbot.core.agent.message import TextPart
from astrbot.core.utils.media_utils import file_uri_to_path, is_file_uri

IMAGE_SEMANTICS_EXTRA = "_qq_enhance_image_semantics"


@dataclass
class ImageSemantics:
    """Bind verified component semantics after real image references exist."""

    text: str
    sources: dict[int, str]
    render: Callable[[dict[int, Mapping[str, Any]]], str]
    part: Plain | None = None
    records: dict[int, Mapping[str, Any]] = field(default_factory=dict)


def prepared_image_sources(
    raw_event: Any, components: Sequence[Any], *, max_components: int
) -> dict[int, str]:
    """Pair top-level raw segments with prepared images without guessing."""

    if not isinstance(raw_event, Mapping):
        return {}
    if raw_event.get("post_type") not in {None, "message"}:
        return {}
    raw_components = raw_event.get("message")
    if not isinstance(raw_components, list):
        return {}
    raw_images = [
        index
        for index, component in enumerate(raw_components)
        if isinstance(component, Mapping) and component.get("type") == "image"
    ]
    prepared_images = [part for part in components if isinstance(part, Image)]
    if len(prepared_images) != len(raw_images):
        return {}
    return {
        index: str(component.path or component.url or component.file or "")
        for index, component in zip(raw_images, prepared_images)
        if index < max_components
    }


def bind_image_references(
    event: Any, source_records: Mapping[str, Mapping[str, Any]], request: Any = None
) -> set[str]:
    """Merge saved references into this event's annotation and return merged IDs."""

    state = event.get_extra(IMAGE_SEMANTICS_EXTRA)
    if not isinstance(state, ImageSemantics):
        return set()
    state.records.update(
        (index, source_records[source])
        for index, source in state.sources.items()
        if source in source_records
    )
    if not state.records:
        return set()
    previous = state.text
    current = state.render(state.records)
    # The semantic budget may have fallen back to a plain type label. Keep a
    # standalone reference for any image whose complete entry did not fit.
    merged = {
        record["image_ref"]
        for record in state.records.values()
        if f'；image_ref={record["image_ref"]}；' in current
    }
    if current != previous:
        # The generated block is appended after user input; replace its last
        # occurrence so user-written copies of component text remain untouched.
        prefix, found, suffix = event.message_str.rpartition(previous)
        if found:
            event.message_str = prefix + current + suffix
            event.message_obj.message_str = event.message_str
        if state.part is not None:
            state.part.text = current
        state.text = current
    if request is not None:
        prefix, found, suffix = (request.prompt or "").rpartition(previous)
        if found:
            request.prompt = prefix + current + suffix
        # Extra parts may contain earlier group messages with identical labels.
        # Never bind those annotations to this event's newly archived image.
        found_annotation = bool(found) or any(
            isinstance(part, TextPart) and current in part.text
            for part in request.extra_user_content_parts
        )
        if not found_annotation and merged:
            request.extra_user_content_parts.append(TextPart(text=current))
    return merged


def has_image_animation(path: str | Path) -> bool:
    """Inspect actual animation frames without counting or decoding every frame."""

    with PillowImage.open(path) as image:
        if image.format not in {"GIF", "WEBP", "PNG"}:
            return False
        # APNG's optional default image is a poster, not an animation frame.
        next_frame = 2 if image.info.get("default_image") else 1
        try:
            image.seek(next_frame)
        except EOFError:
            return False
        return True


async def inspect_inbound_image_animations(
    raw_event: Any, components: Sequence[Any], *, max_components: int
) -> dict[int, bool]:
    """Match raw image segments to prepared files and inspect each file once.

    Only top-level images participate: quoted images belong to another message.
    AstrBot has already downloaded media and preserved animated files at this
    point. Unavailable files remain unknown instead of causing another download.
    """

    sources = {
        index: source
        for index, source in prepared_image_sources(
            raw_event, components, max_components=max_components
        ).items()
        if source
        and not source.startswith(("http://", "https://", "base64://", "data:"))
    }

    async def inspect(source: str) -> bool | None:
        try:
            path = file_uri_to_path(source) if is_file_uri(source) else source
            return await asyncio.to_thread(has_image_animation, path)
        except Exception as exc:
            logger.debug("Unable to inspect QQ image animation: %s", type(exc).__name__)
            return None

    unique_sources = list(dict.fromkeys(sources.values()))
    results = dict(
        zip(
            unique_sources,
            await asyncio.gather(*(inspect(source) for source in unique_sources)),
        )
    )
    return {
        index: result
        for index, source in sources.items()
        if (result := results[source]) is not None
    }
