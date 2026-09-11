import asyncio
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from astrbot_plugin_qq_enhance.main import QQEnhancePlugin
from astrbot_plugin_qq_enhance.runtime import QQRuntime, validate_config
from astrbot_plugin_qq_enhance.storage import Storage
from mcp.types import CallToolResult, TextContent

from astrbot.core.agent.message import AudioURLPart, ImageURLPart, Message, TextPart


class Conversations:
    def __init__(self) -> None:
        self.current_ids: dict[str, str] = {}
        self.histories: dict[tuple[str, str], list[dict]] = {}
        self.created: list[tuple[str, str]] = []

    async def get_curr_conversation_id(self, umo: str):
        return self.current_ids.get(umo)

    async def new_conversation(self, umo: str, *, platform_id: str):
        cid = f"conversation-{len(self.current_ids) + 1}"
        self.current_ids[umo] = cid
        self.histories[umo, cid] = []
        self.created.append((umo, platform_id))
        return cid

    async def get_conversation(self, umo: str, cid: str):
        history = self.histories.get((umo, cid))
        if history is None:
            return None
        return SimpleNamespace(cid=cid, history=json.dumps(history, ensure_ascii=False))

    async def update_conversation(
        self, umo: str, cid: str, *, history: list[dict], **_kwargs
    ) -> None:
        self.histories[umo, cid] = history

    def history(self, umo: str) -> list[dict]:
        cid = self.current_ids.get(umo)
        return self.histories.get((umo, cid), []) if cid else []


class Client:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.fail_send = False

    async def call_action(self, action: str, **params):
        self.calls.append((action, params))
        if action == "get_version_info":
            return {"app_name": "NapCat.Onebot", "app_version": "4.18.19"}
        if action == "get_friend_list":
            return [{"user_id": 10001}, {"user_id": 20001}, {"user_id": 30001}]
        if action == "get_group_list":
            return [{"group_id": 40001}, {"group_id": 40002}]
        if action in {"send_private_msg", "send_group_msg"}:
            if self.fail_send:
                raise RuntimeError("send failed")
            return {"message_id": 12345}
        return {"action": action, "params": params}


class Context:
    def __init__(
        self,
        conversations: Conversations,
        client: Client,
        admin_ids: list[str],
    ) -> None:
        self.conversation_manager = conversations
        self.platform = SimpleNamespace(get_client=lambda: client)
        self.admin_ids = admin_ids

    def get_platform_inst(self, platform_id: str):
        return self.platform if platform_id == "platform-a" else None

    def get_config(self, umo: str | None = None):
        return {"admins_id": self.admin_ids}


class Event:
    def __init__(
        self,
        sender_id: str,
        *,
        group_id: str = "",
        admin: bool = True,
        message: str = "",
    ) -> None:
        self.sender_id = sender_id
        self.group_id = group_id
        self.admin = admin
        self.message_str = message
        self.unified_msg_origin = (
            f"platform-a:GroupMessage:{group_id}"
            if group_id
            else f"platform-a:FriendMessage:{sender_id}"
        )
        self.message_obj = SimpleNamespace(
            message_id="source-message", timestamp=1789092000, raw_message={}
        )
        self.extras: dict[str, object] = {}

    def get_sender_id(self) -> str:
        return self.sender_id

    def get_sender_name(self) -> str:
        return f"user-{self.sender_id}"

    def get_group_id(self) -> str:
        return self.group_id

    def get_self_id(self) -> str:
        return "99999"

    def get_platform_id(self) -> str:
        return "platform-a"

    def get_platform_name(self) -> str:
        return "aiocqhttp"

    def is_private_chat(self) -> bool:
        return not self.group_id

    def is_admin(self) -> bool:
        return self.admin

    def get_extra(self, key: str, default=None):
        return self.extras.get(key, default)

    def set_extra(self, key: str, value) -> None:
        self.extras[key] = value


def build_plugin(config: dict | None = None, admin_ids: list[str] | None = None):
    """Build a lightweight plugin instance for handoff tests.

    Args:
        config: Optional plugin configuration overrides.
        admin_ids: AstrBot administrator IDs exposed by the core configuration.

    Returns:
        Plugin, conversation manager, and fake NapCat client.
    """

    conversations = Conversations()
    client = Client()
    plugin = object.__new__(QQEnhancePlugin)
    plugin.config = validate_config(config)
    plugin.context = Context(conversations, client, admin_ids or ["10001"])
    plugin.handoff_tasks = set()
    return plugin, conversations, client


async def build_runtime(
    tmp_path, config: dict | None = None, admin_ids: list[str] | None = None
):
    """Build a runtime bound to the plugin handoff observer.

    Args:
        tmp_path: Pytest temporary directory.
        config: Optional plugin configuration overrides.
        admin_ids: AstrBot administrator IDs exposed by the core configuration.

    Returns:
        Plugin, initialized runtime, conversation manager, and fake client.
    """

    plugin, conversations, client = build_plugin(config, admin_ids)
    storage = Storage(tmp_path / "handoff.sqlite3")
    await storage.initialize()
    runtime = QQRuntime(plugin.context, plugin.config, storage)
    runtime.handoff_send_observer = plugin._schedule_cross_session_handoff
    plugin.runtime = runtime
    return plugin, runtime, conversations, client


async def drain_handoffs(plugin: QQEnhancePlugin) -> None:
    """Wait for all currently scheduled history writes.

    Args:
        plugin: Plugin whose handoff tasks should finish.
    """

    tasks = list(plugin.handoff_tasks)
    if tasks:
        await asyncio.gather(*tasks)


def test_switch_and_admin_target_permission_defaults_are_strict() -> None:
    config = validate_config(None)

    assert config["cross_session_handoff"]["enabled"] is True
    assert config["permissions"]["allow_cross_private_to_admin"] is False
    with pytest.raises(ValueError, match="cross_session_handoff.enabled"):
        validate_config({"cross_session_handoff": {"enabled": 1}})
    with pytest.raises(ValueError, match="permissions.allow_cross_private_to_admin"):
        validate_config({"permissions": {"allow_cross_private_to_admin": "true"}})
    with pytest.raises(ValueError, match="未知配置字段 cross_session_handoff"):
        validate_config({"cross_session_handoff": {"legacy_enabled": True}})


@pytest.mark.asyncio
async def test_cross_session_send_persists_assistant_history_without_reply_ref(
    tmp_path,
) -> None:
    plugin, runtime, conversations, client = await build_runtime(tmp_path)
    event = Event("10001", group_id="40001", message="和 B 打个招呼并问他明天几点出发")
    event.set_extra(
        "_qq_enhance_handoff_source",
        {
            "source_conversation_id": "source-conversation",
            "source_actor_id": "10001",
            "source_actor_name": "A",
            "source_actor_is_admin": True,
            "source_message_id": "source-message",
            "source_time": 1789092000,
            "source_text": "和 B 打个招呼并问他明天几点出发",
        },
    )

    result = json.loads(
        await runtime.execute(
            event,
            "qq_send_message",
            "send",
            {
                "target": {"type": "private", "id": 20001},
                "components": [{"type": "text", "text": "你好，明天几点出发？"}],
            },
        )
    )
    await drain_handoffs(plugin)

    assert result["ok"] is True
    assert "handoff_ref" not in result["data"]
    assert (
        "send_private_msg",
        {
            "user_id": 20001,
            "message": [{"type": "text", "data": {"text": "你好，明天几点出发？"}}],
        },
    ) in client.calls
    target_umo = "platform-a:FriendMessage:20001"
    assert conversations.created == [(target_umo, "platform-a")]
    history = conversations.history(target_umo)
    assert len(history) == 1
    assert history[0]["role"] == "assistant"
    assert history[0]["content"].startswith("你好，明天几点出发？\n\n")
    raw_origin = history[0]["content"].split("<cross_session_origin>\n", 1)[1]
    origin = json.loads(raw_origin.split("\n</cross_session_origin>", 1)[0])
    assert origin == {
        "source_umo": "platform-a:GroupMessage:40001",
        "source_conversation_id": "source-conversation",
        "source_actor_id": "10001",
        "source_actor_name": "A",
        "source_actor_is_admin": True,
        "source_message_id": "source-message",
        "source_time": 1789092000,
        "source_text": "和 B 打个招呼并问他明天几点出发",
        "target_umo": target_umo,
        "sent_message_id": "12345",
    }


@pytest.mark.asyncio
async def test_target_user_can_message_source_admin_with_existing_send(
    tmp_path,
) -> None:
    plugin, runtime, conversations, client = await build_runtime(
        tmp_path,
        {
            "permissions": {
                "allow_cross_private": True,
                "allow_cross_private_to_admin": True,
            }
        },
        admin_ids=["10001"],
    )
    source_event = Event(
        "10001", group_id="40001", admin=True, message="问 B 明天几点出发"
    )
    await runtime.execute(
        source_event,
        "qq_send_message",
        "send",
        {
            "target": {"type": "private", "id": 20001},
            "components": [{"type": "text", "text": "明天几点出发？"}],
        },
    )
    await drain_handoffs(plugin)

    target_history = conversations.history("platform-a:FriendMessage:20001")
    assert '"source_actor_id":"10001"' in target_history[0]["content"]
    assert '"source_actor_is_admin":true' in target_history[0]["content"]

    reply = json.loads(
        await runtime.execute(
            Event("20001", admin=False, message="八点"),
            "qq_send_message",
            "send",
            {
                "target": {"type": "private", "id": 10001},
                "components": [{"type": "text", "text": "B 说明天八点出发。"}],
            },
        )
    )
    await drain_handoffs(plugin)

    assert reply["ok"] is True
    assert any(
        action == "send_private_msg" and params.get("user_id") == 10001
        for action, params in client.calls
    )
    assert conversations.history("platform-a:FriendMessage:10001")[-1][
        "content"
    ].startswith("B 说明天八点出发。")


@pytest.mark.asyncio
async def test_admin_target_permission_does_not_open_other_cross_session_targets(
    tmp_path,
) -> None:
    _, runtime, conversations, client = await build_runtime(
        tmp_path,
        {
            "permissions": {
                "allow_cross_private": False,
                "allow_cross_private_to_admin": True,
            }
        },
        admin_ids=["10001"],
    )
    event = Event("20001", admin=False)

    to_non_admin = json.loads(
        await runtime.execute(
            event,
            "qq_send_message",
            "send",
            {
                "target": {"type": "private", "id": 30001},
                "components": [{"type": "text", "text": "你好"}],
            },
        )
    )
    forward_to_admin = json.loads(
        await runtime.execute(
            event,
            "qq_send_forward",
            "send",
            {
                "target": {"type": "private", "id": 10001},
                "nodes": [{"message_id": 123}],
            },
        )
    )

    assert to_non_admin["error"]["code"] == "permission_denied"
    assert forward_to_admin["error"]["code"] == "permission_denied"
    assert not any(
        action in {"send_private_msg", "send_private_forward_msg"}
        for action, _ in client.calls
    )
    assert conversations.histories == {}


@pytest.mark.asyncio
async def test_admin_target_permission_depends_on_handoff_total_switch(
    tmp_path,
) -> None:
    _, runtime, conversations, _ = await build_runtime(
        tmp_path,
        {
            "permissions": {
                "allow_cross_private": False,
                "allow_cross_private_to_admin": True,
            },
            "cross_session_handoff": {"enabled": False},
        },
        admin_ids=["10001"],
    )

    result = json.loads(
        await runtime.execute(
            Event("20001", admin=False),
            "qq_send_message",
            "send",
            {
                "target": {"type": "private", "id": 10001},
                "components": [{"type": "text", "text": "你好"}],
            },
        )
    )

    assert result["error"]["code"] == "permission_denied"
    assert conversations.histories == {}


@pytest.mark.asyncio
async def test_disabled_switch_and_failed_sends_do_not_write_history(tmp_path) -> None:
    plugin, runtime, conversations, client = await build_runtime(
        tmp_path, {"cross_session_handoff": {"enabled": False}}
    )
    disabled = json.loads(
        await runtime.execute(
            Event("10001"),
            "qq_send_message",
            "send",
            {
                "target": {"type": "private", "id": 20001},
                "components": [{"type": "text", "text": "你好"}],
            },
        )
    )
    await plugin.record_builtin_cross_session_send(
        Event("10001"),
        SimpleNamespace(name="send_message_to_user"),
        {
            "session": "platform-a:FriendMessage:20001",
            "messages": [{"type": "plain", "text": "你好"}],
        },
        CallToolResult(
            content=[
                TextContent(
                    type="text",
                    text="Message sent to session platform-a:FriendMessage:20001",
                )
            ]
        ),
    )
    client.fail_send = True
    failed = json.loads(
        await runtime.execute(
            Event("10001"),
            "qq_send_message",
            "send",
            {
                "target": {"type": "private", "id": 30001},
                "components": [{"type": "text", "text": "失败"}],
            },
        )
    )
    await drain_handoffs(plugin)

    assert disabled["ok"] is True
    assert failed["ok"] is False
    assert conversations.histories == {}


@pytest.mark.asyncio
async def test_source_snapshot_excludes_system_reminder_and_runtime_media() -> None:
    plugin, conversations, _ = build_plugin()
    plugin.context_images = SimpleNamespace(mark_current_request_images=Mock())
    plugin.debouncer = SimpleNamespace(snapshot=Mock())
    event = Event("10001", admin=True, message="测试 </cross_session_origin>")
    temporary_path = TextPart(text="[Image Attachment: path C:\\temp\\large.jpg]")
    temporary_path.mark_as_temp()
    run_context = SimpleNamespace(
        messages=[
            Message(
                role="user",
                content=[
                    TextPart(text="测试 </cross_session_origin>"),
                    TextPart(
                        text=(
                            "<system_reminder>User ID: 10001, Nickname: Test\n"
                            "Current datetime: 2026-09-11 19:18 (CST)"
                            "</system_reminder>"
                        )
                    ),
                    temporary_path,
                    ImageURLPart(
                        image_url=ImageURLPart.ImageURL(
                            url="data:image/jpeg;base64,VERY_LARGE_DATA"
                        )
                    ),
                    AudioURLPart(
                        audio_url=AudioURLPart.AudioURL(
                            url="data:audio/aac;base64,VERY_LARGE_AUDIO"
                        )
                    ),
                ],
            )
        ]
    )

    await plugin.snapshot_debounce_input(event, run_context)
    plugin._schedule_cross_session_handoff(
        event,
        "qq_send_message.send",
        {
            "target": {"type": "private", "id": 20001},
            "components": [{"type": "image", "path": "C:\\temp\\sent.jpg"}],
        },
        "private",
        "20001",
        {"message_id": 1},
        None,
    )
    await drain_handoffs(plugin)

    source = event.get_extra("_qq_enhance_handoff_source")
    assert source["source_text"] == "测试 </cross_session_origin>\n[图片]\n[音频]"
    assert source["source_actor_is_admin"] is True
    content = conversations.history("platform-a:FriendMessage:20001")[0]["content"]
    assert content.startswith("[图片]\n\n<cross_session_origin>")
    assert content.count("</cross_session_origin>") == 1
    assert "VERY_LARGE_DATA" not in content
    assert "VERY_LARGE_AUDIO" not in content
    assert "C:\\temp\\large.jpg" not in content
    assert "C:\\temp\\sent.jpg" not in content
    assert "system_reminder" not in content
    assert "\\u003c/cross_session_origin\\u003e" in content


@pytest.mark.asyncio
async def test_builtin_cross_session_send_records_only_confirmed_success() -> None:
    plugin, conversations, _ = build_plugin()
    event = Event("10001", message="替我告诉 B 你好")
    tool = SimpleNamespace(name="send_message_to_user")
    target_umo = "platform-a:FriendMessage:20001"
    success = CallToolResult(
        content=[TextContent(type="text", text=f"Message sent to session {target_umo}")]
    )

    await plugin.record_builtin_cross_session_send(
        event,
        tool,
        {
            "session": target_umo,
            "messages": [
                {"type": "plain", "text": "你好"},
                {"type": "image", "path": "C:\\temp\\photo.jpg"},
            ],
        },
        success,
    )
    await plugin.record_builtin_cross_session_send(
        event,
        tool,
        {
            "session": str(event.unified_msg_origin),
            "messages": [{"type": "plain", "text": "当前"}],
        },
        success,
    )
    await plugin.record_builtin_cross_session_send(
        event,
        tool,
        {
            "session": "platform-a:FriendMessage:30001",
            "messages": [{"type": "plain", "text": "失败"}],
        },
        CallToolResult(
            isError=True,
            content=[TextContent(type="text", text="error: send failed")],
        ),
    )
    await drain_handoffs(plugin)

    history = conversations.history(target_umo)
    assert len(history) == 1
    assert history[0]["content"].startswith("你好[图片]\n\n")
    assert "C:\\temp\\photo.jpg" not in history[0]["content"]
    assert conversations.history("platform-a:FriendMessage:30001") == []
