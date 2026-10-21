from __future__ import annotations

import asyncio
import base64
import json
import re
import secrets
import shutil
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from mcp.types import CallToolResult, ImageContent, TextContent
from PIL import Image as PillowImage

from astrbot.api import logger
from astrbot.api.message_components import Image, Reply
from astrbot.core.agent.message import ImageURLPart, TextPart
from astrbot.core.utils.media_utils import MediaResolver

from .animation_preview import AnimationPreviewError, render_animation_preview
from .image_semantics import bind_image_references
from .storage import Storage
from .group_image_cache import (
    GROUP_IMAGES_EXTRA,
    GROUP_IMAGE_REF_PATTERN,
    GroupImageCache,
)

CONVERSATION_ID_EXTRA = "_qq_enhance_conversation_id"
REQUEST_IMAGE_REFS_EXTRA = "_qq_enhance_request_image_refs"
IMAGE_REF_PATTERN = re.compile(r"(?:img|gimg)_[0-9a-f]{24}")
HISTORY_IMAGE_REF_PATTERN = re.compile(
    r"(?:\[QQ ImageRef image_ref=|；image_ref=)(img_[0-9a-f]{24})(?=[,；])"
)
CORE_IMAGE_ATTACHMENT_PREFIXES = (
    "[Image Attachment: path ",
    "[Image Attachment in quoted message: path ",
)
TOOL_IMAGE_PREFIX = "[Image from tool 'qq_media', path='"
TOOL_IMAGE_ATTACHMENT_PATTERN = re.compile(
    r"\[Image from tool '(?P<tool>[^']+)', path='(?P<path>.*)'\]", re.DOTALL
)
TOOL_IMAGE_RESULT_PATTERN = re.compile(
    r"Image returned and cached at path='(?P<path>.*?)'\. "
    r"Review the image below\. Use send_message_to_user to send it to the user "
    r"if satisfied, with type='image' and path='(?P=path)'\.",
    re.DOTALL,
)


class ContextImageError(Exception):
    """Represent a safe conversation-image failure.

    Args:
        code: Stable machine-readable error code.
        message: Concise Chinese explanation.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ContextImageManager:
    """Persist original QQ images while keeping model history lightweight.

    Args:
        context: AstrBot plugin context used to inspect conversation history.
        storage: Plugin persistence service.
        root: Plugin-owned directory for immutable image copies.
        orphan_grace_days: Local calendar days to retain an orphaned image.
        retention_days: Maximum local calendar days to retain every image, or zero.
        max_storage_mb: Total storage budget for persistent context images.
        max_inspect_mb: Largest image that may be loaded into one tool result.
        group_cache: Bounded cache for images collected from group messages.
    """

    def __init__(
        self,
        context: Any,
        storage: Storage,
        root: Path,
        orphan_grace_days: int,
        retention_days: int,
        max_storage_mb: int,
        max_inspect_mb: int,
        group_cache: GroupImageCache,
    ) -> None:
        self.context = context
        self.storage = storage
        self.root = root
        self.orphan_grace_days = orphan_grace_days
        self.retention_days = retention_days
        self.max_storage_bytes = max_storage_mb * 1024 * 1024
        self.max_inspect_bytes = max_inspect_mb * 1024 * 1024
        self.group_cache = group_cache
        self.root.mkdir(parents=True, exist_ok=True)

    async def prepare_request(self, event: Any, request: Any) -> None:
        """Archive current QQ images and add persistent reference text.

        Args:
            event: Current QQ message event.
            request: Fully assembled AstrBot provider request.

        Raises:
            ContextImageError: If images cannot be safely archived.
        """

        conversation = getattr(request, "conversation", None)
        conversation_id = str(getattr(conversation, "cid", "") or "")
        if conversation_id:
            event.set_extra(CONVERSATION_ID_EXTRA, conversation_id)

        inference_sources = list(getattr(request, "image_urls", None) or [])
        event.set_extra(REQUEST_IMAGE_REFS_EXTRA, [])
        cached_images = event.get_extra(GROUP_IMAGES_EXTRA, [])
        cached_sources = {item["source"] for item in cached_images}
        # Bind only references present in this request; do not claim other pending
        # group images when a new conversation is created.
        reference_text = "\n".join(
            [request.prompt or ""]
            + [
                part.text
                for part in request.extra_user_content_parts
                if isinstance(part, TextPart)
            ]
        )
        refs = set(GROUP_IMAGE_REF_PATTERN.findall(reference_text))
        refs.update(item["image_ref"] for item in cached_images)
        await self.group_cache.bind(
            refs,
            str(event.get_platform_id()),
            str(event.unified_msg_origin),
            conversation_id,
        )
        merged = bind_image_references(
            event, {item["source"]: item for item in cached_images}, request
        )
        for item in cached_images:
            if (
                item["text"]
                and item["image_ref"] not in merged
                and item["image_ref"] not in reference_text
            ):
                request.extra_user_content_parts.append(TextPart(text=item["text"]))
                reference_text += item["text"]
        sources: list[str] = []
        components = list(
            getattr(getattr(event, "message_obj", None), "message", []) or []
        )
        for component in components:
            if isinstance(component, Image):
                source = str(component.path or component.url or component.file or "")
                sources.append(source)
            elif isinstance(component, Reply):
                for image in component.chain or []:
                    if isinstance(image, Image):
                        source = str(image.path or image.url or image.file or "")
                        sources.append(source)

        original_sources = list(sources)
        remaining_count = max(0, len(inference_sources) - len(sources))
        if remaining_count:
            sources.extend(
                str(source) for source in inference_sources[-remaining_count:]
            )

        sources = list(
            dict.fromkeys(source for source in sources if source not in cached_sources)
        )

        source_records = await self._archive_sources(event, conversation_id, sources)
        records_by_source = {
            **{item["source"]: item for item in cached_images},
            **source_records,
        }
        paired_sources = (
            original_sources
            if len(original_sources) == len(inference_sources)
            else inference_sources
        )
        request_refs = []
        for inference, source in zip(inference_sources, paired_sources):
            record = records_by_source.get(inference) or records_by_source.get(source)
            request_refs.append(record["image_ref"] if record else None)
        event.set_extra(REQUEST_IMAGE_REFS_EXTRA, request_refs)

        for part in getattr(request, "extra_user_content_parts", None) or []:
            if isinstance(part, TextPart) and part.text.startswith(
                CORE_IMAGE_ATTACHMENT_PREFIXES
            ):
                part.mark_as_temp()
        merged = bind_image_references(event, source_records, request)
        request.extra_user_content_parts.extend(
            TextPart(text=self._reference_text(record))
            for record in source_records.values()
            if record["image_ref"] not in merged
        )

    @staticmethod
    def _reference_text(record: dict[str, Any]) -> str:
        return (
            f"[QQ ImageRef image_ref={record['image_ref']}, "
            f"{record['width']}x{record['height']}；"
            "如需重新查看原图，调用 "
            'qq_media(operation="inspect", '
            f'params={{"image_ref":"{record["image_ref"]}"}})]'
        )

    async def _archive_sources(
        self, event: Any, conversation_id: str, sources: list[str]
    ) -> dict[str, dict[str, Any]]:
        """Validate and atomically archive one batch without modifying messages."""
        if not sources:
            return {}
        if not conversation_id:
            raise ContextImageError(
                "conversation_unavailable",
                "无法确定当前 AstrBot 会话，无法保存图片引用",
            )

        now = int(time.time())
        records: list[dict[str, Any]] = []
        source_records: dict[str, dict[str, Any]] = {}
        created_paths: list[Path] = []
        try:
            for source in sources:
                if not source:
                    raise ContextImageError(
                        "image_unavailable", "图片缺少可读取的原始媒体地址"
                    )
                image_ref = f"img_{secrets.token_hex(12)}"
                async with MediaResolver(
                    source, media_type="image"
                ).as_path() as resolved:
                    source_path = resolved.path

                    def validate_image() -> tuple[str, int, int, str]:
                        """Validate an image and detect its canonical extension.

                        Returns:
                            MIME type, width, height, and trusted file extension.

                        Raises:
                            OSError: If the source image cannot be read.
                            ValueError: If Pillow cannot identify a supported image.
                        """

                        with PillowImage.open(source_path) as image:
                            width, height = image.size
                            image_format = str(image.format or "").upper()
                            mime_type = PillowImage.MIME.get(image_format, "")
                            image.verify()
                        registered_extensions = PillowImage.registered_extensions()
                        preferred_extension = (
                            ".jpg"
                            if image_format == "JPEG"
                            else f".{image_format.lower()}"
                        )
                        if (
                            registered_extensions.get(preferred_extension)
                            != image_format
                        ):
                            preferred_extension = next(
                                (
                                    extension
                                    for extension, registered_format in (
                                        registered_extensions.items()
                                    )
                                    if registered_format == image_format
                                ),
                                "",
                            )
                        if (
                            not mime_type.startswith("image/")
                            or width <= 0
                            or height <= 0
                            or not preferred_extension
                        ):
                            raise ValueError("unsupported image format")
                        return mime_type, width, height, preferred_extension

                    mime_type, width, height, extension = await asyncio.to_thread(
                        validate_image
                    )
                    destination = self.root / f"{image_ref}{extension}"
                    created_paths.append(destination)
                    await asyncio.to_thread(shutil.copyfile, source_path, destination)
                    size_bytes = destination.stat().st_size
                records.append(
                    {
                        "image_ref": image_ref,
                        "platform_id": str(event.get_platform_id()),
                        "unified_msg_origin": str(event.unified_msg_origin),
                        "conversation_id": conversation_id,
                        "path": destination,
                        "mime_type": mime_type,
                        "width": width,
                        "height": height,
                        "size_bytes": size_bytes,
                        "created_at": now,
                        "last_accessed_at": now,
                    }
                )
                source_records[source] = records[-1]
            evicted_paths = await self.storage.add_context_images(
                records, self.max_storage_bytes
            )
            if evicted_paths is None:
                raise ContextImageError(
                    "storage_full",
                    "当前批次图片超过会话图片存储总容量",
                )
            self.remove_owned_files(evicted_paths)
        except ContextImageError:
            self.remove_owned_files(created_paths)
            raise
        except Exception as exc:
            self.remove_owned_files(created_paths)
            raise ContextImageError(
                "image_archive_failed", "图片原图无法验证或保存"
            ) from exc

        return source_records

    def bind_current_request_images(self, event: Any, run_context: Any) -> None:
        """Bind original references while retaining image bytes for debounce saves."""
        refs = event.get_extra(REQUEST_IMAGE_REFS_EXTRA, [])
        messages = getattr(run_context, "messages", [])
        if not refs or not messages:
            return
        current = messages[-1]
        if getattr(current, "role", None) != "user" or not isinstance(
            getattr(current, "content", None), list
        ):
            return
        images = [part for part in current.content if isinstance(part, ImageURLPart)]
        if len(images) < len(refs):
            return
        for part, image_ref in zip(images[-len(refs) :], refs):
            if image_ref:
                part.image_url.id = image_ref

    async def inspect(self, event: Any, image_ref: str) -> CallToolResult:
        """Load a scoped original image for the current model run.

        Args:
            event: Current QQ tool event.
            image_ref: Opaque image reference from conversation history.

        Returns:
            A multimodal tool result containing stable text and image bytes.

        Raises:
            ContextImageError: If the reference is invalid, unavailable, or out of scope.
        """

        payload, mime_type = await self._read_scoped_image(event, image_ref)
        return CallToolResult(
            content=[
                TextContent(
                    type="text",
                    text=f"已加载 image_ref={image_ref}，图片仅供本轮视觉检查。",
                ),
                ImageContent(
                    type="image",
                    data=base64.b64encode(payload).decode(),
                    mimeType=mime_type,
                ),
            ]
        )

    async def inspect_animation(self, event: Any, image_ref: str) -> CallToolResult:
        """Return an on-demand animation contact sheet without altering its source."""

        payload, _ = await self._read_scoped_image(event, image_ref)
        try:
            preview = await asyncio.to_thread(render_animation_preview, payload)
        except AnimationPreviewError as exc:
            raise ContextImageError("animation_preview_unavailable", str(exc)) from exc
        except (
            OSError,
            ValueError,
            EOFError,
            PillowImage.DecompressionBombError,
        ) as exc:
            raise ContextImageError(
                "image_decode_failed", "动图无法解码，无法生成动画预览"
            ) from exc
        if len(preview.png) > self.max_inspect_bytes:
            raise ContextImageError(
                "file_too_large", "动画预览超过单次视觉检查大小上限"
            )
        text = (
            f"已加载 image_ref={image_ref} 的动画预览。\n"
            f"单次播放时长 {preview.duration_ms / 1000:.3f} 秒，"
            f"共 {preview.frame_count} 帧，采样 {len(preview.sampled_indices)} 帧；"
            "按从左到右、从上到下排列，每格标注序号和时间。\n"
            "所有画面来自同一张动图，这是抽帧预览，并非完整动画；原图保持不变。"
        )
        if len(preview.sampled_indices) < 9:
            text += "不足九帧，其余格留空。"
        if preview.estimated_duration:
            text += "部分帧缺少有效时长，按每帧 0.1 秒估算。"
        return CallToolResult(
            content=[
                TextContent(type="text", text=text),
                ImageContent(
                    type="image",
                    data=base64.b64encode(preview.png).decode(),
                    mimeType="image/png",
                ),
            ]
        )

    async def _read_scoped_image(self, event: Any, image_ref: str) -> tuple[bytes, str]:
        """Share original-image loading and conversation isolation for both views."""

        if IMAGE_REF_PATTERN.fullmatch(image_ref) is None:
            raise ContextImageError("invalid_parameters", "image_ref 格式无效")
        conversation_id = event.get_extra(CONVERSATION_ID_EXTRA)
        if not isinstance(conversation_id, str) or not conversation_id:
            raise ContextImageError(
                "conversation_unavailable", "无法确定当前 AstrBot 会话"
            )
        if GROUP_IMAGE_REF_PATTERN.fullmatch(image_ref):
            try:
                cached = await self.group_cache.read(
                    image_ref,
                    str(event.get_platform_id()),
                    str(event.unified_msg_origin),
                    conversation_id,
                )
            except ValueError as exc:
                raise ContextImageError(
                    "file_too_large", "图片超过单次视觉检查大小上限"
                ) from exc
            if cached is None:
                raise ContextImageError(
                    "target_not_found", "群聊图片缓存已过期、被淘汰或不属于当前会话"
                )
            return cached
        record = await self.storage.resolve_context_image(
            image_ref,
            str(event.get_platform_id()),
            str(event.unified_msg_origin),
            conversation_id,
        )
        if record is None:
            raise ContextImageError(
                "target_not_found", "图片引用已过期、不存在或不属于当前会话"
            )
        path = Path(record["path"]).resolve(strict=False)
        root = self.root.resolve(strict=False)
        if root not in path.parents or not path.is_file():
            raise ContextImageError("target_not_found", "图片原图已不可用")
        size_bytes = path.stat().st_size
        if size_bytes > self.max_inspect_bytes:
            raise ContextImageError(
                "file_too_large", "图片原图超过单次视觉检查大小上限"
            )
        return await asyncio.to_thread(path.read_bytes), str(record["mime_type"])

    async def finalize_images(self, event: Any, run_context: Any) -> None:
        """Replace all persistent image payloads only after the agent has finished.

        References attached to inbound images survive debounce serialization in
        ``image_url.id``. Other images, including results from arbitrary tools,
        are archived as one batch before any of those payloads are filtered.
        Archive failures leave the unarchived images intact and raise an error.
        """
        self.clean_runtime_images(run_context)
        messages = getattr(run_context, "messages", [])
        images: list[tuple[ImageURLPart, TextPart | None, str | None]] = []
        sources: list[str] = []
        for message in messages:
            if getattr(message, "_no_save", False) or not isinstance(
                getattr(message, "content", None), list
            ):
                continue
            text = "\n".join(
                part.text for part in message.content if isinstance(part, TextPart)
            )
            pending_marker = None
            for part in message.content:
                if isinstance(part, ImageURLPart) and not part._no_save:
                    image_ref = part.image_url.id
                    if not (
                        image_ref
                        and IMAGE_REF_PATTERN.fullmatch(image_ref)
                        and image_ref in text
                    ):
                        image_ref = None
                        sources.append(part.image_url.url)
                    images.append((part, pending_marker, image_ref))
                pending_marker = (
                    part
                    if isinstance(part, TextPart)
                    and TOOL_IMAGE_ATTACHMENT_PATTERN.fullmatch(part.text)
                    else None
                )

        records = await self._archive_sources(
            event,
            event.get_extra(CONVERSATION_ID_EXTRA, ""),
            list(dict.fromkeys(sources)),
        )
        cache_refs: dict[str, str] = {}
        replacements: dict[int, TextPart] = {}
        for part, marker, image_ref in images:
            if image_ref is None:
                record = records[part.image_url.url]
                image_ref = record["image_ref"]
                replacements[id(part)] = TextPart(text=self._reference_text(record))
            part.mark_as_temp()
            if marker is not None:
                match = TOOL_IMAGE_ATTACHMENT_PATTERN.fullmatch(marker.text)
                assert match is not None
                cache_refs[match["path"]] = image_ref
                marker.mark_as_temp()

        for message in messages:
            content = getattr(message, "content", None)
            if isinstance(content, list):
                expanded = []
                for part in content:
                    if replacement := replacements.get(id(part)):
                        expanded.append(replacement)
                    expanded.append(part)
                message.content = expanded
            elif getattr(message, "role", None) == "tool" and isinstance(content, str):

                def replace_cache_path(match: re.Match[str]) -> str:
                    image_ref = cache_refs.get(match["path"])
                    if image_ref is None:
                        return match[0]
                    return f"图片已在当时的推理轮次中提供，历史引用为 {image_ref}。"

                message.content = TOOL_IMAGE_RESULT_PATTERN.sub(
                    replace_cache_path, content
                )

    def clean_runtime_images(self, run_context: Any) -> None:
        """Prevent inspect-tool image bytes and cache paths from persistence.

        Args:
            run_context: Completed AstrBot agent context awaiting history save.
        """

        inspect_calls: dict[str, tuple[str, str]] = {}
        messages = getattr(run_context, "messages", [])
        for message in messages:
            if getattr(message, "role", None) != "assistant":
                continue
            for tool_call in getattr(message, "tool_calls", None) or []:
                if isinstance(tool_call, dict):
                    tool_call_id = tool_call.get("id")
                    function = tool_call.get("function", {})
                    name = function.get("name") if isinstance(function, dict) else None
                    arguments = (
                        function.get("arguments")
                        if isinstance(function, dict)
                        else None
                    )
                else:
                    tool_call_id = getattr(tool_call, "id", None)
                    function = getattr(tool_call, "function", None)
                    name = getattr(function, "name", None)
                    arguments = getattr(function, "arguments", None)
                if name != "qq_media" or not isinstance(tool_call_id, str):
                    continue
                try:
                    parsed = (
                        json.loads(arguments)
                        if isinstance(arguments, str)
                        else arguments
                    )
                except json.JSONDecodeError:
                    continue
                if not isinstance(parsed, dict) or parsed.get("operation") not in {
                    "inspect",
                    "inspect_animation",
                }:
                    continue
                params = parsed.get("params")
                image_ref = (
                    params.get("image_ref") if isinstance(params, dict) else None
                )
                if isinstance(image_ref, str) and IMAGE_REF_PATTERN.fullmatch(
                    image_ref
                ):
                    inspect_calls[tool_call_id] = (image_ref, parsed["operation"])

        for message in messages:
            if getattr(message, "role", None) == "tool":
                inspected = inspect_calls.get(getattr(message, "tool_call_id", None))
                content = getattr(message, "content", None)
                if (
                    inspected
                    and isinstance(content, str)
                    and ("Image returned and cached at path=" in content)
                ):
                    image_ref, operation = inspected
                    if operation == "inspect_animation":
                        # Keep objective sampling details, strip only AstrBot's
                        # temporary attachment/cache-path suffix.
                        message.content = content.split(
                            "Image returned and cached at path=", 1
                        )[0].rstrip()
                    else:
                        message.content = f"已加载 image_ref={image_ref}，图片已在当时的推理轮次中提供。"
                continue
            if getattr(message, "role", None) != "user" or not isinstance(
                getattr(message, "content", None), list
            ):
                continue
            pending_tool_image = False
            for part in message.content:
                if isinstance(part, TextPart) and part.text.startswith(
                    TOOL_IMAGE_PREFIX
                ):
                    part.mark_as_temp()
                    pending_tool_image = True
                elif pending_tool_image and isinstance(part, ImageURLPart):
                    part.mark_as_temp()
                    pending_tool_image = False
                else:
                    pending_tool_image = False
            if message.content and all(
                getattr(part, "_no_save", False) for part in message.content
            ):
                message._no_save = True

    async def reconcile(self) -> None:
        """Reconcile stored images against current AstrBot conversation histories."""

        records = await self.storage.list_context_images()
        grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for record in records:
            scope = (record["unified_msg_origin"], record["conversation_id"])
            grouped.setdefault(scope, []).append(record)

        liveness: dict[str, bool] = {}
        manager = self.context.conversation_manager
        for (unified_msg_origin, conversation_id), scoped_records in grouped.items():
            try:
                conversation = await manager.get_conversation(
                    unified_msg_origin, conversation_id
                )
                if conversation is None:
                    referenced: set[str] = set()
                else:
                    history = getattr(conversation, "history", "[]")
                    if isinstance(history, str):
                        history = json.loads(history or "[]")
                    if not isinstance(history, list):
                        raise ValueError("conversation history must be a list")
                    serialized = json.dumps(history, ensure_ascii=False)
                    referenced = set(HISTORY_IMAGE_REF_PATTERN.findall(serialized))
            except Exception:
                logger.exception(
                    "Failed to reconcile QQ context images for one conversation"
                )
                continue
            for record in scoped_records:
                liveness[record["image_ref"]] = record["image_ref"] in referenced

        now = int(time.time())
        today = datetime.fromtimestamp(now).date()
        orphan_boundary = today - timedelta(days=self.orphan_grace_days - 1)
        orphan_cutoff_exclusive = int(
            datetime.combine(orphan_boundary, datetime.min.time()).timestamp()
        )
        retention_cutoff_exclusive = None
        if self.retention_days > 0:
            if self.retention_days >= today.toordinal():
                retention_cutoff_exclusive = 0
            else:
                retention_boundary = today - timedelta(days=self.retention_days - 1)
                retention_cutoff_exclusive = int(
                    datetime.combine(
                        retention_boundary, datetime.min.time()
                    ).timestamp()
                )
        expired_paths = await self.storage.reconcile_context_images(
            liveness,
            now,
            orphan_cutoff_exclusive,
            retention_cutoff_exclusive,
        )
        self.remove_owned_files(expired_paths)

    def remove_owned_files(self, paths: list[Path]) -> None:
        """Remove files only when they are inside the context-image root.

        Args:
            paths: Candidate plugin-owned paths.
        """

        root = self.root.resolve(strict=False)
        for path in paths:
            try:
                resolved = path.resolve(strict=False)
                if root in resolved.parents and resolved.is_file():
                    resolved.unlink()
            except OSError:
                logger.warning("Failed to remove expired QQ context image")
