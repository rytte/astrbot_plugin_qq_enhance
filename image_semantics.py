from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from PIL import Image as PillowImage

from astrbot.api import logger
from astrbot.api.message_components import Image
from astrbot.core.utils.media_utils import file_uri_to_path, is_file_uri


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
    if not raw_images:
        return {}
    prepared_images = [
        component for component in components if isinstance(component, Image)
    ]
    # If conversion dropped an image, positional pairing would label another file.
    if len(prepared_images) != len(raw_images):
        return {}

    sources: dict[int, str] = {}
    for index, component in zip(raw_images, prepared_images):
        if index >= max_components:
            break
        source = str(component.path or component.url or component.file or "")
        if not source or source.startswith(
            ("http://", "https://", "base64://", "data:")
        ):
            continue
        sources[index] = source

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
