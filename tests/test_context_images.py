from __future__ import annotations

import base64
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from mcp.types import CallToolResult, ImageContent
from PIL import Image as PillowImage

from astrbot.api.message_components import Image
from astrbot.core.agent.message import (
    ImageURLPart,
    Message,
    TextPart,
    dump_messages_with_checkpoints,
)
from astrbot.core.provider.entities import ProviderRequest
from astrbot_plugin_qq_enhance.context_images import (
    CONVERSATION_ID_EXTRA,
    ContextImageError,
    ContextImageManager,
)
from astrbot_plugin_qq_enhance.main import QQEnhancePlugin
from astrbot_plugin_qq_enhance.storage import Storage


class Conversations:
    def __init__(self) -> None:
        self.histories: dict[tuple[str, str], list[dict] | None] = {}

    async def get_conversation(self, unified_msg_origin: str, conversation_id: str):
        history = self.histories.get((unified_msg_origin, conversation_id))
        if history is None:
            return None
        return SimpleNamespace(history=json.dumps(history, ensure_ascii=False))


class Event:
    def __init__(
        self,
        image_path: Path | None = None,
        *,
        platform_id: str = "platform-a",
        unified_msg_origin: str = "platform-a:FriendMessage:10001",
    ) -> None:
        self.platform_id = platform_id
        self.unified_msg_origin = unified_msg_origin
        self.extras: dict[str, object] = {}
        self.message_obj = SimpleNamespace(
            message_id="456",
            message=[Image(file=str(image_path))] if image_path else [],
        )

    def get_platform_id(self) -> str:
        return self.platform_id

    def get_extra(self, key: str, default=None):
        return self.extras.get(key, default)

    def set_extra(self, key: str, value) -> None:
        self.extras[key] = value


async def build_manager(
    tmp_path: Path,
) -> tuple[ContextImageManager, Storage, Conversations]:
    storage = Storage(tmp_path / "context-images.sqlite3")
    await storage.initialize()
    conversations = Conversations()
    manager = ContextImageManager(
        SimpleNamespace(conversation_manager=conversations),
        storage,
        tmp_path / "images",
        orphan_grace_days=3,
        retention_days=30,
        max_storage_mb=64,
        max_inspect_mb=10,
    )
    return manager, storage, conversations


def save_image(path: Path, image_format: str, size: tuple[int, int]) -> bytes:
    PillowImage.new("RGB", size, (20, 40, 60)).save(path, format=image_format)
    return path.read_bytes()


@pytest.mark.asyncio
async def test_disabled_switch_skips_all_context_image_hooks() -> None:
    plugin = object.__new__(QQEnhancePlugin)
    plugin.config = {"context_images": {"enabled": False}}
    plugin.context_images = SimpleNamespace(
        prepare_request=AsyncMock(),
        mark_current_request_images=Mock(),
        clean_runtime_images=Mock(),
    )
    plugin.debouncer = SimpleNamespace(snapshot=Mock())
    event = SimpleNamespace()
    request = ProviderRequest(image_urls=["original-image"])
    run_context = SimpleNamespace(messages=[])

    await plugin.virtualize_context_images(event, request)
    await plugin.snapshot_debounce_input(event, run_context)
    await plugin.remove_inspected_images_before_history_save(event, run_context, None)

    plugin.context_images.prepare_request.assert_not_awaited()
    plugin.context_images.mark_current_request_images.assert_not_called()
    plugin.context_images.clean_runtime_images.assert_not_called()
    plugin.debouncer.snapshot.assert_called_once_with(event, run_context)
    assert request.image_urls == ["original-image"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("image_format", "expected_suffix"), [("PNG", ".png"), ("JPEG", ".jpg")]
)
async def test_original_copy_uses_detected_image_extension(
    tmp_path: Path,
    image_format: str,
    expected_suffix: str,
) -> None:
    manager, storage, _ = await build_manager(tmp_path)
    original = tmp_path / "misleading.bin"
    original_bytes = save_image(original, image_format, (9, 7))
    request = ProviderRequest(
        conversation=SimpleNamespace(cid="conversation-a", history="[]"),
        image_urls=[str(original)],
    )

    await manager.prepare_request(Event(original), request)

    record = (await storage.list_context_images())[0]
    stored_path = Path(record["path"])
    assert stored_path.suffix == expected_suffix
    assert stored_path.read_bytes() == original_bytes


@pytest.mark.asyncio
async def test_request_keeps_inference_image_but_persists_only_image_ref(
    tmp_path: Path,
) -> None:
    manager, storage, _ = await build_manager(tmp_path)
    original = tmp_path / "original.png"
    original_bytes = save_image(original, "PNG", (17, 11))
    inference = tmp_path / "inference.jpg"
    save_image(inference, "JPEG", (8, 8))
    event = Event(original)
    conversation = SimpleNamespace(cid="conversation-a", history="[]")
    request = ProviderRequest(
        prompt="",
        conversation=conversation,
        image_urls=[str(inference)],
        extra_user_content_parts=[
            TextPart(text=f"[Image Attachment: path {inference}]")
        ],
    )

    await manager.prepare_request(event, request)

    assert request.image_urls == [str(inference)]
    assert len(request.extra_user_content_parts) == 2
    attachment = request.extra_user_content_parts[0]
    assert attachment.text == f"[Image Attachment: path {inference}]"
    assert attachment._no_save is True
    placeholder = request.extra_user_content_parts[1].text
    assert "[QQ ImageRef image_ref=img_" in placeholder
    assert ", 17x11" in placeholder
    assert "source_message" not in placeholder
    assert 'qq_media(operation="inspect"' in placeholder
    current = Message.model_validate(await request.assemble_context())
    assert any(
        isinstance(part, TextPart) and part.text == attachment.text
        for part in current.content
    )
    assert any(
        isinstance(part, ImageURLPart)
        and part.image_url.url.startswith("data:image/jpeg;base64,")
        for part in current.content
    )

    run_context = SimpleNamespace(messages=[current])
    manager.mark_current_request_images(event, run_context)
    dumped = dump_messages_with_checkpoints(run_context.messages)
    serialized = json.dumps(dumped, ensure_ascii=False)
    assert "data:image" not in serialized
    assert str(inference) not in serialized
    assert "[QQ ImageRef image_ref=img_" in serialized

    records = await storage.list_context_images()
    assert len(records) == 1
    assert Path(records[0]["path"]).read_bytes() == original_bytes
    assert records[0]["mime_type"] == "image/png"
    assert (records[0]["width"], records[0]["height"]) == (17, 11)
    assert "source_message_id" not in records[0]
    assert "source_kind" not in records[0]


@pytest.mark.asyncio
async def test_inspect_returns_original_only_inside_exact_conversation_scope(
    tmp_path: Path,
) -> None:
    manager, storage, _ = await build_manager(tmp_path)
    original = tmp_path / "original.png"
    original_bytes = save_image(original, "PNG", (12, 9))
    event = Event(original)
    request = ProviderRequest(
        conversation=SimpleNamespace(cid="conversation-a", history="[]"),
        image_urls=[str(original)],
    )
    await manager.prepare_request(event, request)
    image_ref = (await storage.list_context_images())[0]["image_ref"]

    result = await manager.inspect(event, image_ref)

    assert isinstance(result, CallToolResult)
    image_content = next(
        item for item in result.content if isinstance(item, ImageContent)
    )
    assert image_content.mimeType == "image/png"
    assert base64.b64decode(image_content.data) == original_bytes

    for wrong_event in (
        Event(platform_id="platform-b"),
        Event(unified_msg_origin="platform-a:FriendMessage:20002"),
    ):
        wrong_event.set_extra(CONVERSATION_ID_EXTRA, "conversation-a")
        with pytest.raises(ContextImageError, match="不属于当前会话"):
            await manager.inspect(wrong_event, image_ref)
    event.set_extra(CONVERSATION_ID_EXTRA, "conversation-b")
    with pytest.raises(ContextImageError, match="不属于当前会话"):
        await manager.inspect(event, image_ref)
    with pytest.raises(ContextImageError, match="格式无效"):
        await manager.inspect(event, "../original.png")


def test_inspect_tool_images_and_cache_paths_are_not_persisted(tmp_path: Path) -> None:
    manager = ContextImageManager(
        SimpleNamespace(),
        SimpleNamespace(),
        tmp_path / "images",
        orphan_grace_days=7,
        retention_days=30,
        max_storage_mb=64,
        max_inspect_mb=10,
    )
    image_ref = "img_0123456789abcdef01234567"
    assistant = Message(
        role="assistant",
        content=None,
        tool_calls=[
            {
                "type": "function",
                "id": "call-1",
                "function": {
                    "name": "qq_media",
                    "arguments": json.dumps(
                        {
                            "operation": "inspect",
                            "params": {"image_ref": image_ref},
                        }
                    ),
                },
            }
        ],
    )
    tool = Message(
        role="tool",
        tool_call_id="call-1",
        content=(
            f"已加载 image_ref={image_ref}，图片仅供本轮视觉检查。\n\n"
            "Image returned and cached at path='C:\\temp\\tool.png'. Review the image below."
        ),
    )
    tool_image = Message(
        role="user",
        content=[
            TextPart(text="[Image from tool 'qq_media', path='C:\\temp\\tool.png']"),
            ImageURLPart(
                image_url=ImageURLPart.ImageURL(
                    url="data:image/png;base64,cGljdHVyZQ=="
                )
            ),
        ],
    )
    messages = [assistant, tool, tool_image]

    manager.clean_runtime_images(SimpleNamespace(messages=messages))

    assert tool.content == (
        f"已加载 image_ref={image_ref}，图片已在当时的推理轮次中提供。"
    )
    assert tool_image._no_save is True
    persisted = [
        message
        for message in messages
        if not (message.role in {"assistant", "user"} and message._no_save)
    ]
    serialized = json.dumps(
        dump_messages_with_checkpoints(persisted), ensure_ascii=False
    )
    assert "data:image" not in serialized
    assert "C:\\temp\\tool.png" not in serialized


@pytest.mark.asyncio
async def test_reconcile_keeps_live_refs_then_deletes_expired_orphans(
    tmp_path: Path,
) -> None:
    manager, storage, conversations = await build_manager(tmp_path)
    original = tmp_path / "original.png"
    save_image(original, "PNG", (10, 10))
    event = Event(original)
    request = ProviderRequest(
        conversation=SimpleNamespace(cid="conversation-a", history="[]"),
        image_urls=[str(original)],
    )
    await manager.prepare_request(event, request)
    placeholder = request.extra_user_content_parts[0].text
    record = (await storage.list_context_images())[0]
    stored_path = Path(record["path"])
    scope = (event.unified_msg_origin, "conversation-a")
    conversations.histories[scope] = [
        {"role": "user", "content": [{"type": "text", "text": placeholder}]}
    ]

    live_at = int(datetime(2026, 9, 10, 12).timestamp())
    orphaned_at = int(datetime(2026, 9, 10, 23, 59).timestamp())
    before_expiry = int(datetime(2026, 9, 12, 23, 59).timestamp())
    expiry_day = int(datetime(2026, 9, 13, 0, 1).timestamp())

    with patch(
        "astrbot_plugin_qq_enhance.context_images.time.time", return_value=live_at
    ):
        await manager.reconcile()
    assert (await storage.list_context_images())[0]["orphaned_at"] is None

    conversations.histories[scope] = []
    with patch(
        "astrbot_plugin_qq_enhance.context_images.time.time",
        return_value=orphaned_at,
    ):
        await manager.reconcile()
    assert (await storage.list_context_images())[0]["orphaned_at"] == orphaned_at
    assert stored_path.is_file()

    with patch(
        "astrbot_plugin_qq_enhance.context_images.time.time",
        return_value=before_expiry,
    ):
        await manager.reconcile()
    assert len(await storage.list_context_images()) == 1
    assert stored_path.is_file()

    original_get_conversation = conversations.get_conversation

    async def unavailable_conversation(_unified_msg_origin, _conversation_id):
        raise RuntimeError("database unavailable")

    conversations.get_conversation = unavailable_conversation
    with patch(
        "astrbot_plugin_qq_enhance.context_images.time.time",
        return_value=expiry_day,
    ):
        await manager.reconcile()
    assert len(await storage.list_context_images()) == 1
    assert stored_path.is_file()

    conversations.get_conversation = original_get_conversation
    with patch(
        "astrbot_plugin_qq_enhance.context_images.time.time",
        return_value=expiry_day,
    ):
        await manager.reconcile()
    assert await storage.list_context_images() == []
    assert not stored_path.exists()


@pytest.mark.asyncio
async def test_retention_deletes_live_image_on_natural_expiry_day(
    tmp_path: Path,
) -> None:
    manager, storage, conversations = await build_manager(tmp_path)
    original = tmp_path / "retained.png"
    save_image(original, "PNG", (10, 10))
    event = Event(original)
    request = ProviderRequest(
        conversation=SimpleNamespace(cid="conversation-a", history="[]"),
        image_urls=[str(original)],
    )
    with patch(
        "astrbot_plugin_qq_enhance.context_images.time.time",
        return_value=int(datetime(2026, 9, 10, 23, 59).timestamp()),
    ):
        await manager.prepare_request(event, request)
    record = (await storage.list_context_images())[0]
    stored_path = Path(record["path"])
    conversations.histories[(event.unified_msg_origin, "conversation-a")] = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": request.extra_user_content_parts[0].text}
            ],
        }
    ]

    with patch(
        "astrbot_plugin_qq_enhance.context_images.time.time",
        return_value=int(datetime(2026, 10, 9, 23, 59).timestamp()),
    ):
        await manager.reconcile()
    assert len(await storage.list_context_images()) == 1

    with patch(
        "astrbot_plugin_qq_enhance.context_images.time.time",
        return_value=int(datetime(2026, 10, 10, 0, 1).timestamp()),
    ):
        await manager.reconcile()
    assert await storage.list_context_images() == []
    assert not stored_path.exists()


@pytest.mark.asyncio
async def test_zero_retention_disables_absolute_expiry(tmp_path: Path) -> None:
    manager, storage, conversations = await build_manager(tmp_path)
    manager.retention_days = 0
    original = tmp_path / "no-expiry.png"
    save_image(original, "PNG", (10, 10))
    event = Event(original)
    request = ProviderRequest(
        conversation=SimpleNamespace(cid="conversation-a", history="[]"),
        image_urls=[str(original)],
    )
    with patch(
        "astrbot_plugin_qq_enhance.context_images.time.time",
        return_value=int(datetime(2020, 1, 1, 12).timestamp()),
    ):
        await manager.prepare_request(event, request)
    conversations.histories[(event.unified_msg_origin, "conversation-a")] = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": request.extra_user_content_parts[0].text}
            ],
        }
    ]

    with patch(
        "astrbot_plugin_qq_enhance.context_images.time.time",
        return_value=int(datetime(2030, 1, 1, 12).timestamp()),
    ):
        await manager.reconcile()

    records = await storage.list_context_images()
    assert len(records) == 1
    assert Path(records[0]["path"]).is_file()


@pytest.mark.asyncio
async def test_storage_full_evicts_every_image_from_oldest_local_day(
    tmp_path: Path,
) -> None:
    manager, storage, conversations = await build_manager(tmp_path)
    archived: list[tuple[dict, ProviderRequest]] = []
    for name, size, created_at in (
        ("first", (10, 10), datetime(2026, 9, 8, 1)),
        ("second", (11, 11), datetime(2026, 9, 8, 23, 59)),
        ("third", (12, 12), datetime(2026, 9, 9, 12)),
    ):
        image = tmp_path / f"{name}.png"
        save_image(image, "PNG", size)
        request = ProviderRequest(
            conversation=SimpleNamespace(cid="conversation-a", history="[]"),
            image_urls=[str(image)],
        )
        with patch(
            "astrbot_plugin_qq_enhance.context_images.time.time",
            return_value=int(created_at.timestamp()),
        ):
            await manager.prepare_request(Event(image), request)
        archived.append(((await storage.list_context_images())[-1], request))

    conversations.histories[(Event().unified_msg_origin, "conversation-a")] = [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": archived[0][1].extra_user_content_parts[0].text,
                },
                {
                    "type": "text",
                    "text": archived[1][1].extra_user_content_parts[0].text,
                },
            ],
        }
    ]
    original_records = await storage.list_context_images()
    manager.max_storage_bytes = sum(
        int(record["size_bytes"]) for record in original_records
    )
    fourth = tmp_path / "fourth.png"
    save_image(fourth, "PNG", (13, 13))
    fourth_request = ProviderRequest(
        conversation=SimpleNamespace(cid="conversation-a", history="[]"),
        image_urls=[str(fourth)],
    )

    with patch(
        "astrbot_plugin_qq_enhance.context_images.time.time",
        return_value=int(datetime(2026, 9, 10, 12).timestamp()),
    ):
        await manager.prepare_request(Event(fourth), fourth_request)

    records = await storage.list_context_images()
    remaining_refs = {record["image_ref"] for record in records}
    assert archived[0][0]["image_ref"] not in remaining_refs
    assert archived[1][0]["image_ref"] not in remaining_refs
    assert archived[2][0]["image_ref"] in remaining_refs
    assert not Path(archived[0][0]["path"]).exists()
    assert not Path(archived[1][0]["path"]).exists()
    assert Path(archived[2][0]["path"]).is_file()
    assert sum(int(record["size_bytes"]) for record in records) <= (
        manager.max_storage_bytes
    )


@pytest.mark.asyncio
async def test_oversized_batch_is_rejected_without_evicting_existing_images(
    tmp_path: Path,
) -> None:
    manager, storage, _ = await build_manager(tmp_path)
    existing = tmp_path / "existing.png"
    save_image(existing, "PNG", (10, 10))
    await manager.prepare_request(
        Event(existing),
        ProviderRequest(
            conversation=SimpleNamespace(cid="conversation-a", history="[]"),
            image_urls=[str(existing)],
        ),
    )
    existing_record = (await storage.list_context_images())[0]
    oversized = tmp_path / "oversized.png"
    save_image(oversized, "PNG", (11, 11))
    manager.max_storage_bytes = oversized.stat().st_size - 1

    with pytest.raises(ContextImageError) as error:
        await manager.prepare_request(
            Event(oversized),
            ProviderRequest(
                conversation=SimpleNamespace(cid="conversation-a", history="[]"),
                image_urls=[str(oversized)],
            ),
        )

    assert error.value.code == "storage_full"
    assert (await storage.list_context_images())[0]["image_ref"] == (
        existing_record["image_ref"]
    )
    assert Path(existing_record["path"]).is_file()
