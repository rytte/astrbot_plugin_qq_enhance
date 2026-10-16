from __future__ import annotations

import io
import math
from bisect import bisect_right
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFont, ImageOps

MAX_ANIMATION_FRAMES = 10_000
MAX_DECODED_PIXELS = 256 * 1024 * 1024
CELL_SIZE = 384
LABEL_HEIGHT = 32


class AnimationPreviewError(ValueError):
    """An animation cannot be safely rendered as a preview."""


@dataclass(frozen=True)
class AnimationPreview:
    png: bytes
    duration_ms: float
    frame_count: int
    sampled_indices: tuple[int, ...]
    timestamps_ms: tuple[float, ...]
    estimated_duration: bool


def render_animation_preview(payload: bytes) -> AnimationPreview:
    """Sample at most nine composited frames from one playback into a 3x3 PNG.

    Decode sequentially so Pillow applies GIF/APNG disposal and blending. Only
    selected, resized frames survive the second pass; never retain every frame.
    """

    with Image.open(io.BytesIO(payload)) as image:
        if image.format not in {"GIF", "WEBP", "PNG"}:
            raise AnimationPreviewError("该图片不是支持的动图，请使用 inspect 查看原图")
        first = 1 if image.info.get("default_image") else 0
        starts: list[float] = []
        elapsed = 0.0
        decoded_pixels = 0
        estimated = False
        for index in range(MAX_ANIMATION_FRAMES + first + 1):
            try:
                image.seek(index)
            except EOFError:
                break
            if index < first:
                continue
            if len(starts) >= MAX_ANIMATION_FRAMES:
                raise AnimationPreviewError("动图帧数超过预览处理上限")
            decoded_pixels += image.width * image.height
            if decoded_pixels > MAX_DECODED_PIXELS:
                raise AnimationPreviewError("动图解码总像素超过预览处理上限")
            image.load()  # WebP exposes the current frame duration only after load.
            duration = image.info.get("duration")
            if (
                not isinstance(duration, (int, float))
                or isinstance(duration, bool)
                or not math.isfinite(duration)
                or duration <= 0
            ):
                duration = 100.0
                estimated = True
            starts.append(elapsed)
            elapsed += duration
        count = len(starts)
        if count < 2:
            raise AnimationPreviewError(
                "该图片未包含多个动画帧，请使用 inspect 查看原图"
            )

        sample_count = min(9, count)
        selected: list[int] = []
        for slot in range(sample_count):
            target = elapsed * slot / (sample_count - 1)
            candidate = bisect_right(starts, target) - 1
            # Enforce distinct chronological frames, including the first/last,
            # even if an unusually long hold attracts several sampling points.
            lower = selected[-1] + 1 if selected else 0
            upper = count - (sample_count - slot)
            selected.append(min(max(candidate, lower), upper))

        sheet = Image.new(
            "RGB", (CELL_SIZE * 3, (CELL_SIZE + LABEL_HEIGHT) * 3), "white"
        )
        draw = ImageDraw.Draw(sheet)
        font = ImageFont.load_default(size=18)
        selected_slots = {frame: slot for slot, frame in enumerate(selected)}
        # Reopen rather than rewind: reset all decoder/disposal state explicitly.
        with Image.open(io.BytesIO(payload)) as frames:
            for index in range(first + count):
                frames.seek(index)
                slot = selected_slots.get(index - first)
                if slot is None:
                    continue
                frame = ImageOps.contain(
                    frames.convert("RGBA"),
                    (CELL_SIZE - 16, CELL_SIZE - 16),
                    Image.Resampling.LANCZOS,
                )
                x = slot % 3 * CELL_SIZE
                y = slot // 3 * (CELL_SIZE + LABEL_HEIGHT)
                draw.text(
                    (x + 8, y + 6),
                    f"#{slot + 1}  {starts[index - first] / 1000:.3f}s",
                    fill="black",
                    font=font,
                )
                position = (
                    x + (CELL_SIZE - frame.width) // 2,
                    y + LABEL_HEIGHT + (CELL_SIZE - frame.height) // 2,
                )
                sheet.paste(frame, position, frame)
        for slot in range(9):
            x = slot % 3 * CELL_SIZE
            y = slot // 3 * (CELL_SIZE + LABEL_HEIGHT)
            draw.rectangle(
                (x, y, x + CELL_SIZE - 1, y + CELL_SIZE + LABEL_HEIGHT - 1),
                outline="#cccccc",
            )
        output = io.BytesIO()
        sheet.save(output, format="PNG")
        return AnimationPreview(
            png=output.getvalue(),
            duration_ms=elapsed,
            frame_count=count,
            sampled_indices=tuple(selected),
            timestamps_ms=tuple(starts[index] for index in selected),
            estimated_duration=estimated,
        )
