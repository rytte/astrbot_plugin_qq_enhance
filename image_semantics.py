from __future__ import annotations

import asyncio
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from PIL import Image as PillowImage

from astrbot.api import logger
from astrbot.api.message_components import Image
from astrbot.core.utils.media_utils import file_uri_to_path, is_file_uri

IMAGE_LINKS_EXTRA = "_image_context_links_v1"


def prepared_image_ids(event, raw_event, components, *, max_components):
    """Read the optional v1 association without importing the media plugin."""
    sources = prepared_image_sources(
        raw_event, components, max_components=max_components
    )
    if not sources:
        return {}
    links = event.get_extra(IMAGE_LINKS_EXTRA, {})
    if not isinstance(links, Mapping):
        return {}
    raw_images = [
        index
        for index, component in enumerate(raw_event["message"])
        if isinstance(component, Mapping) and component.get("type") == "image"
    ]
    images = [component for component in components if isinstance(component, Image)]
    result = {}
    for index, component in zip(raw_images, images):
        link = links.get(id(component))
        if (
            index in sources
            and isinstance(link, str)
            and re.fullmatch(r"pic_[0-9a-f]{16}", link)
        ):
            result[index] = link
    return result


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
