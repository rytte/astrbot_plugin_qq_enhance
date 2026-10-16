from __future__ import annotations

import io

import pytest
from PIL import Image, ImageDraw

from astrbot_plugin_qq_enhance.animation_preview import (
    CELL_SIZE,
    LABEL_HEIGHT,
    AnimationPreviewError,
    render_animation_preview,
)


def animation_bytes(*, image_format="GIF", count=12, durations=None, poster=False):
    frames = [
        Image.new("RGB", (32, 24), (i * 19 % 256, i * 31 % 256, i * 47 % 256))
        for i in range(count)
    ]
    output = io.BytesIO()
    frames[0].save(
        output,
        format=image_format,
        save_all=True,
        append_images=frames[1:],
        duration=durations if durations is not None else 100,
        default_image=poster,
        lossless=True,
    )
    return output.getvalue()


def cell_pixel(sheet, slot, x=0.5, y=0.5):
    return sheet.getpixel(
        (
            int(slot % 3 * CELL_SIZE + CELL_SIZE * x),
            int(slot // 3 * (CELL_SIZE + LABEL_HEIGHT) + LABEL_HEIGHT + CELL_SIZE * y),
        )
    )


@pytest.mark.parametrize("image_format", ["GIF", "WEBP", "PNG"])
@pytest.mark.parametrize("count", [2, 9, 18])
def test_time_sampling_keeps_order_first_last_and_leaves_unused_cells_blank(
    image_format, count
):
    preview = render_animation_preview(
        animation_bytes(image_format=image_format, count=count)
    )
    assert preview.frame_count == count
    assert preview.duration_ms == count * 100
    assert not preview.estimated_duration
    assert len(preview.sampled_indices) == min(9, count)
    assert preview.sampled_indices[0] == 0
    assert preview.sampled_indices[-1] == count - 1
    assert len(set(preview.sampled_indices)) == len(preview.sampled_indices)
    if count == 18:
        assert preview.sampled_indices == (0, 2, 4, 6, 9, 11, 13, 15, 17)
    with Image.open(io.BytesIO(preview.png)) as sheet:
        assert sheet.format == "PNG"
        assert sheet.size == (CELL_SIZE * 3, (CELL_SIZE + LABEL_HEIGHT) * 3)
        for slot, index in enumerate(preview.sampled_indices):
            assert cell_pixel(sheet, slot) == (
                index * 19 % 256,
                index * 31 % 256,
                index * 47 % 256,
            )
        for slot in range(min(9, count), 9):
            assert cell_pixel(sheet, slot) == (255, 255, 255)


def test_uneven_duration_uses_playback_time_and_does_not_repeat_long_hold():
    preview = render_animation_preview(
        animation_bytes(count=18, durations=[1000] + [100] * 17)
    )
    assert preview.duration_ms == 2700
    assert preview.sampled_indices == (0, 1, 2, 3, 4, 7, 11, 14, 17)
    assert preview.timestamps_ms == (0, 1000, 1100, 1200, 1300, 1600, 2000, 2300, 2600)


def test_apng_poster_is_excluded_from_frames_duration_and_sampling():
    preview = render_animation_preview(
        animation_bytes(image_format="PNG", count=4, poster=True)
    )
    assert preview.frame_count == 3
    assert preview.duration_ms == 300
    assert preview.sampled_indices == (0, 1, 2)
    with Image.open(io.BytesIO(preview.png)) as sheet:
        assert cell_pixel(sheet, 0) == (19, 31, 47)
        assert cell_pixel(sheet, 2) == (57, 93, 141)


@pytest.mark.parametrize("disposal", [2, 3])
def test_gif_partial_frames_restore_background_and_previous_canvas(disposal):
    frames = [Image.new("RGB", (32, 32), "white") for _ in range(3)]
    for frame in frames:
        ImageDraw.Draw(frame).rectangle((0, 0, 15, 31), fill="red")
    ImageDraw.Draw(frames[1]).rectangle((16, 0, 31, 15), fill="blue")
    ImageDraw.Draw(frames[2]).rectangle((16, 16, 31, 31), fill="green")
    output = io.BytesIO()
    frames[0].save(
        output,
        format="GIF",
        save_all=True,
        append_images=frames[1:],
        duration=100,
        disposal=disposal,
        optimize=True,
    )
    preview = render_animation_preview(output.getvalue())
    with Image.open(io.BytesIO(preview.png)) as sheet:
        assert cell_pixel(sheet, 1, 0.75, 0.25) == (0, 0, 255)
        assert cell_pixel(sheet, 2, 0.25, 0.5) == (255, 0, 0)
        assert cell_pixel(sheet, 2, 0.75, 0.25) == (255, 255, 255)
        assert cell_pixel(sheet, 2, 0.75, 0.75) == (0, 128, 0)


def test_apng_transparent_over_blending_preserves_previous_frame():
    first = Image.new("RGBA", (32, 32), "red")
    second = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    ImageDraw.Draw(second).rectangle((16, 0, 31, 31), fill="blue")
    output = io.BytesIO()
    first.save(
        output,
        format="PNG",
        save_all=True,
        append_images=[second],
        duration=100,
        blend=[0, 1],
        disposal=[0, 0],
    )
    preview = render_animation_preview(output.getvalue())
    with Image.open(io.BytesIO(preview.png)) as sheet:
        assert cell_pixel(sheet, 1, 0.25) == (255, 0, 0)
        assert cell_pixel(sheet, 1, 0.75) == (0, 0, 255)


def test_missing_duration_is_reported_as_estimated():
    preview = render_animation_preview(animation_bytes(count=2, durations=0))
    assert preview.duration_ms == 200
    assert preview.estimated_duration


@pytest.mark.parametrize(
    ("image_format", "count", "poster"),
    [("GIF", 1, False), ("PNG", 2, True), ("TIFF", 2, False)],
)
def test_static_images_and_multipage_documents_are_not_animations(
    image_format, count, poster
):
    with pytest.raises(AnimationPreviewError, match="inspect"):
        render_animation_preview(
            animation_bytes(image_format=image_format, count=count, poster=poster)
        )


@pytest.mark.parametrize(
    ("setting", "value"),
    [("MAX_ANIMATION_FRAMES", 2), ("MAX_DECODED_PIXELS", 32 * 24 * 2)],
)
def test_decoding_work_is_bounded(monkeypatch, setting, value):
    monkeypatch.setattr(f"astrbot_plugin_qq_enhance.animation_preview.{setting}", value)
    with pytest.raises(AnimationPreviewError, match="处理上限"):
        render_animation_preview(animation_bytes(count=3))
