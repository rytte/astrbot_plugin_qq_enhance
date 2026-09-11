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

from .storage import Storage

CONVERSATION_ID_EXTRA = "_qq_enhance_conversation_id"
REQUEST_IMAGE_COUNT_EXTRA = "_qq_enhance_request_image_count"
IMAGE_REF_PATTERN = re.compile(r"img_[0-9a-f]{24}")
HISTORY_IMAGE_REF_PATTERN = re.compile(r"\[QQ ImageRef image_ref=(img_[0-9a-f]{24}),")
CORE_IMAGE_ATTACHMENT_PREFIXES = (
    "[Image Attachment: path ",
    "[Image Attachment in quoted message: path ",
)
TOOL_IMAGE_PREFIX = "[Image from tool 'qq_media', path='"


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
    ) -> None:
        self.context = context
        self.storage = storage
        self.root = root
        self.orphan_grace_days = orphan_grace_days
        self.retention_days = retention_days
        self.max_storage_bytes = max_storage_mb * 1024 * 1024
        self.max_inspect_bytes = max_inspect_mb * 1024 * 1024
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
        event.set_extra(REQUEST_IMAGE_COUNT_EXTRA, len(inference_sources))
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

        remaining_count = max(0, len(inference_sources) - len(sources))
        if remaining_count:
            sources.extend(
                str(source) for source in inference_sources[-remaining_count:]
            )

        if not sources:
            return
        if not conversation_id:
            raise ContextImageError(
                "conversation_unavailable", "当前会话尚未建立，无法安全保存图片引用"
            )

        now = int(time.time())
        records: list[dict[str, Any]] = []
        created_paths: list[Path] = []
        try:
            for source in sources:
                if not source:
                    raise ContextImageError(
                        "image_unavailable", "QQ 图片缺少可读取的原始媒体地址"
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
                "image_archive_failed", "QQ 图片原图无法验证或保存"
            ) from exc

        for part in getattr(request, "extra_user_content_parts", None) or []:
            if isinstance(part, TextPart) and part.text.startswith(
                CORE_IMAGE_ATTACHMENT_PREFIXES
            ):
                part.mark_as_temp()
        request.extra_user_content_parts.extend(
            TextPart(
                text=(
                    f"[QQ ImageRef image_ref={record['image_ref']}, "
                    f"{record['width']}x{record['height']}；"
                    "如需重新查看原图，调用 "
                    'qq_media(operation="inspect", '
                    f'params={{"image_ref":"{record["image_ref"]}"}})]'
                )
            )
            for record in records
        )

    def mark_current_request_images(self, event: Any, run_context: Any) -> None:
        """Mark only the current request images as provider-only content.

        Args:
            event: Current QQ event carrying the expected image count.
            run_context: Initialized AstrBot agent context.
        """

        remaining = event.get_extra(REQUEST_IMAGE_COUNT_EXTRA, 0)
        if type(remaining) is not int or remaining <= 0:
            return
        messages = getattr(run_context, "messages", [])
        if not messages:
            return
        current = messages[-1]
        if getattr(current, "role", None) != "user" or not isinstance(
            getattr(current, "content", None), list
        ):
            return
        for part in reversed(current.content):
            if remaining <= 0:
                break
            if isinstance(part, ImageURLPart):
                part.mark_as_temp()
                remaining -= 1

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

        if IMAGE_REF_PATTERN.fullmatch(image_ref) is None:
            raise ContextImageError("invalid_parameters", "image_ref 格式无效")
        conversation_id = event.get_extra(CONVERSATION_ID_EXTRA)
        if not isinstance(conversation_id, str) or not conversation_id:
            raise ContextImageError(
                "conversation_unavailable", "无法确定当前 AstrBot 会话"
            )
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
        image_data = base64.b64encode(await asyncio.to_thread(path.read_bytes)).decode()
        return CallToolResult(
            content=[
                TextContent(
                    type="text",
                    text=f"已加载 image_ref={image_ref}，图片仅供本轮视觉检查。",
                ),
                ImageContent(
                    type="image",
                    data=image_data,
                    mimeType=str(record["mime_type"]),
                ),
            ]
        )

    def clean_runtime_images(self, run_context: Any) -> None:
        """Prevent inspect-tool image bytes and cache paths from persistence.

        Args:
            run_context: Completed AstrBot agent context awaiting history save.
        """

        inspect_calls: dict[str, str] = {}
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
                if not isinstance(parsed, dict) or parsed.get("operation") != "inspect":
                    continue
                params = parsed.get("params")
                image_ref = (
                    params.get("image_ref") if isinstance(params, dict) else None
                )
                if isinstance(image_ref, str) and IMAGE_REF_PATTERN.fullmatch(
                    image_ref
                ):
                    inspect_calls[tool_call_id] = image_ref

        for message in messages:
            if getattr(message, "role", None) == "tool":
                image_ref = inspect_calls.get(getattr(message, "tool_call_id", None))
                content = getattr(message, "content", None)
                if (
                    image_ref
                    and isinstance(content, str)
                    and ("Image returned and cached at path=" in content)
                ):
                    message.content = (
                        f"已加载 image_ref={image_ref}，图片已在当时的推理轮次中提供。"
                    )
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
