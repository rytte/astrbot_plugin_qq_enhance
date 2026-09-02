from __future__ import annotations

import base64
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from astrbot.core.message.components import File
from astrbot_plugin_qq_extension_tools.catalog import OPERATION_MAP
from astrbot_plugin_qq_extension_tools.runtime import (
    QQRuntime,
    QQToolError,
    validate_config,
)
from astrbot_plugin_qq_extension_tools.storage import Storage


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.roles = {10001: "admin", 20001: "member", 99999: "owner"}

    async def call_action(self, action: str, **params):
        self.calls.append((action, params))
        if action == "get_version_info":
            return {"app_name": "NapCat.Onebot", "app_version": "4.18.19"}
        if action == "get_group_member_info":
            return {"role": self.roles.get(int(params["user_id"]), "member")}
        if action == "get_group_list":
            return [{"group_id": 30001, "group_name": "test"}]
        if action == "get_group_system_msg":
            return {
                "join_requests": [
                    {"group_id": 30001, "requester_uin": 20001},
                    {"group_id": 30002, "requester_uin": 20002},
                ],
                "invited_requests": [],
            }
        if action == "get_friend_list":
            return [{"user_id": 10001}, {"user_id": 20001}]
        if action == "get_login_info":
            return {"user_id": 99999, "nickname": "bot"}
        if action == "get_msg":
            if params["message_id"] == 124:
                return {"message_id": 124, "raw_message": "plain fallback"}
            return {
                "message_id": 123,
                "raw_message": (
                    "[CQ:record,file=voice.amr,path=C:\\Users\\tester\\voice.amr]"
                ),
                "message": [
                    {
                        "type": "record",
                        "data": {
                            "file": "voice.amr",
                            "path": "C:\\Users\\tester\\voice.amr",
                        },
                    }
                ],
            }
        if action == "ocr_image":
            return [{"text": f"line-{index}"} for index in range(33)]
        if action == "get_forward_msg":
            return {"messages": [{"sender": {"nickname": "tester"}, "content": []}]}
        return {"action": action, "params": params}


class FakePlatform:
    def __init__(self, client: FakeClient) -> None:
        self.client = client

    def get_client(self) -> FakeClient:
        return self.client


class FakeContext:
    def __init__(self, client: FakeClient) -> None:
        self.platform = FakePlatform(client)

    def get_platform_inst(self, platform_id: str):
        return self.platform if platform_id == "platform-a" else None


class FakeEvent:
    def __init__(
        self,
        *,
        sender_id: str = "10001",
        group_id: str = "",
        admin: bool = True,
        platform_name: str = "aiocqhttp",
    ) -> None:
        self.sender_id = sender_id
        self.group_id = group_id
        self.admin = admin
        self.platform_name = platform_name
        self.unified_msg_origin = (
            f"platform-a:GroupMessage:{group_id}"
            if group_id
            else f"platform-a:FriendMessage:{sender_id}"
        )
        self.message_obj = SimpleNamespace(raw_message={})

    def get_sender_id(self) -> str:
        return self.sender_id

    def get_group_id(self) -> str:
        return self.group_id

    def get_self_id(self) -> str:
        return "99999"

    def get_platform_id(self) -> str:
        return "platform-a"

    def get_platform_name(self) -> str:
        return self.platform_name

    def is_private_chat(self) -> bool:
        return not self.group_id

    def is_admin(self) -> bool:
        return self.admin


async def make_runtime(tmp_path, config: dict | None = None):
    client = FakeClient()
    storage = Storage(tmp_path / "data.sqlite3")
    await storage.initialize()
    with (
        patch(
            "astrbot_plugin_qq_extension_tools.runtime.get_astrbot_temp_path",
            return_value=str(tmp_path / "astrbot-temp"),
        ),
        patch(
            "astrbot_plugin_qq_extension_tools.runtime.get_astrbot_plugin_data_path",
            return_value=str(tmp_path / "plugin-data"),
        ),
    ):
        runtime = QQRuntime(FakeContext(client), validate_config(config), storage)
    return runtime, client, storage


def test_parameter_contract_rejects_unknown_and_missing() -> None:
    runtime = object.__new__(QQRuntime)
    runtime.config = validate_config(None)
    with pytest.raises(QQToolError, match="缺少必填参数"):
        runtime.validate_parameters("qq_group_info.detail", {})
    with pytest.raises(QQToolError, match="不接受参数"):
        runtime.validate_parameters(
            "qq_group_info.detail", {"group_id": "30001", "unexpected": True}
        )
    assert (
        runtime.validate_parameters("qq_group_info.detail", {"group_id": "30001"})[
            "group_id"
        ]
        == 30001
    )
    assert (
        runtime.validate_parameters(
            "qq_media.ocr",
            {"path": "C:\\image.png", "cursor": "20", "page_size": 20},
        )["cursor"]
        == "20"
    )
    with pytest.raises(QQToolError):
        runtime.validate_parameters(
            "qq_media.ocr",
            {"path": "C:\\image.png", "url": "https://example.com/image.png"},
        )


def test_online_status_uses_napcat_codes_and_protocol_defaults() -> None:
    runtime = object.__new__(QQRuntime)
    runtime.config = validate_config(None)

    assert runtime.validate_parameters(
        "qq_account_manage.set_online_status", {"status": "busy"}
    ) == {"status": 50, "ext_status": 0, "battery_status": 0}
    assert runtime.validate_parameters(
        "qq_account_manage.set_online_status", {"status": "listening"}
    ) == {"status": 10, "ext_status": 1028, "battery_status": 0}
    assert runtime.validate_parameters(
        "qq_account_manage.set_online_status",
        {"status": "busy", "ext_status": 7, "battery_status": 80},
    ) == {"status": 50, "ext_status": 7, "battery_status": 80}


@pytest.mark.asyncio
async def test_online_status_sends_complete_napcat_payload(tmp_path) -> None:
    runtime, client, _ = await make_runtime(tmp_path)

    result = json.loads(
        await runtime.execute(
            FakeEvent(),
            "qq_account_manage",
            "set_online_status",
            {"status": "busy"},
        )
    )

    assert result["ok"] is True
    assert (
        "set_online_status",
        {"status": 50, "ext_status": 0, "battery_status": 0},
    ) in client.calls


@pytest.mark.asyncio
async def test_private_file_url_uses_current_attachment_without_file_id(
    tmp_path,
) -> None:
    runtime, client, _ = await make_runtime(tmp_path)
    event = FakeEvent()
    event.message_obj = SimpleNamespace(
        raw_message={},
        message=[
            File(
                name="list.txt",
                url="https://example.test/download/list.txt?key=temporary",
            )
        ],
    )

    result = json.loads(
        await runtime.execute(event, "qq_private_files", "url", {})
    )

    assert result["ok"] is True
    assert result["data"] == [
        {
            "file_name": "list.txt",
            "url": "https://example.test/download/list.txt?key=temporary",
        }
    ]
    assert all(action != "get_private_file_url" for action, _ in client.calls)


@pytest.mark.asyncio
async def test_forward_existing_messages_uses_message_id_nodes(tmp_path) -> None:
    runtime, _, _ = await make_runtime(tmp_path)

    action, params = await runtime.prepare_forward(
        FakeEvent(),
        {
            "target": {"type": "current"},
            "nodes": [
                {"message_id": 1919757466},
                {"message_id": 840075925},
                {"message_id": 1857149135},
            ],
        },
    )

    assert action == "send_private_forward_msg"
    assert params == {
        "user_id": 10001,
        "messages": [
            {"type": "node", "data": {"id": "1919757466"}},
            {"type": "node", "data": {"id": "840075925"}},
            {"type": "node", "data": {"id": "1857149135"}},
        ],
    }


@pytest.mark.asyncio
async def test_forward_rejects_wrapped_onebot_node_with_schema_guidance(
    tmp_path,
) -> None:
    runtime, _, _ = await make_runtime(tmp_path)

    with pytest.raises(QQToolError, match="节点只能使用 message_id"):
        await runtime.prepare_forward(
            FakeEvent(),
            {
                "target": {"type": "current"},
                "nodes": [
                    {
                        "type": "node",
                        "data": {
                            "uin": "10001",
                            "name": "tester",
                            "content": [],
                        },
                    }
                ],
            },
        )


def test_forward_get_requires_exactly_one_reference() -> None:
    runtime = object.__new__(QQRuntime)
    runtime.config = validate_config(None)

    with pytest.raises(QQToolError, match="必须且只能提供"):
        runtime.validate_parameters("qq_forward_get.get", {"depth": 3})
    with pytest.raises(QQToolError, match="必须且只能提供"):
        runtime.validate_parameters(
            "qq_forward_get.get",
            {"message_id": 317412222, "res_id": "forward-resource"},
        )


@pytest.mark.asyncio
async def test_forward_get_prefers_numeric_message_id(tmp_path) -> None:
    runtime, client, _ = await make_runtime(tmp_path)

    result = json.loads(
        await runtime.execute(
            FakeEvent(),
            "qq_forward_get",
            "get",
            {"message_id": 317412222, "depth": 3},
        )
    )

    assert result["ok"] is True
    assert (
        "get_forward_msg",
        {"message_id": "317412222"},
    ) in client.calls


def test_sanitize_data_removes_credentials_and_contact_fields() -> None:
    runtime = object.__new__(QQRuntime)

    result = runtime.sanitize_data(
        {
            "user_id": 10001,
            "nickname": "tester",
            "phone_num": "13000000000",
            "phoneNum": "130******31",
            "mobilePhone": "13000000000",
            "email": "tester@example.com",
            "token": "secret",
            "richBuffer": {"0": 1},
            "ext_buffer": {"buf": {"0": 2}},
            "musicInfo": {"buf": {"0": 3}, "name": "song"},
            "folder_id": "/QQ_Group/File/test/",
            "folder": "/QQ_Group/File/test/",
            "path": "/srv/astrbot/private.txt",
        }
    )

    assert result == {
        "user_id": 10001,
        "nickname": "tester",
        "musicInfo": {"name": "song"},
        "folder_id": "/QQ_Group/File/test/",
        "folder": "/QQ_Group/File/test/",
        "path": "[local-path]",
    }


def test_history_result_keeps_model_relevant_fields_only() -> None:
    runtime = object.__new__(QQRuntime)
    runtime.config = validate_config(None)

    result = runtime.compact_history_result(
        {
            "messages": [
                {
                    "self_id": 99999,
                    "user_id": 10001,
                    "time": 1234567890,
                    "message_id": 123,
                    "message_seq": 123,
                    "real_id": 123,
                    "font": 14,
                    "sender": {
                        "user_id": 10001,
                        "nickname": "tester",
                        "card": "group card",
                        "role": "owner",
                    },
                    "raw_message": "hello",
                    "message": [{"type": "text", "data": {"text": "hello"}}],
                    "post_type": "message",
                }
            ]
        }
    )

    assert result == [
        {
            "message_id": 123,
            "message_seq": 123,
            "time": 1234567890,
            "user_id": 10001,
            "sender": {
                "user_id": 10001,
                "nickname": "tester",
                "card": "group card",
                "role": "owner",
            },
            "message": [{"type": "text", "data": {"text": "hello"}}],
        }
    ]


@pytest.mark.asyncio
async def test_message_get_omits_raw_message_when_components_exist(tmp_path) -> None:
    runtime, _, _ = await make_runtime(tmp_path)

    structured = json.loads(
        await runtime.execute(FakeEvent(), "qq_message_get", "get", {"message_id": 123})
    )
    fallback = json.loads(
        await runtime.execute(FakeEvent(), "qq_message_get", "get", {"message_id": 124})
    )

    assert "raw_message" not in structured["data"]
    assert structured["data"]["message"] == [
        {
            "type": "record",
            "data": {"file": "voice.amr", "path": "[local-path]"},
        }
    ]
    assert fallback["data"]["raw_message"] == "plain fallback"


@pytest.mark.asyncio
async def test_current_group_admin_and_bot_roles_are_checked(tmp_path) -> None:
    runtime, _, _ = await make_runtime(tmp_path)
    event = FakeEvent(group_id="30001", admin=False)
    target_kind, target_id, cross = await runtime.authorize(
        event,
        OPERATION_MAP["qq_group_member_manage.ban"],
        {"group_id": 30001, "user_id": 20001, "duration": 60},
    )
    assert (target_kind, target_id, cross) == ("group", "30001", False)


@pytest.mark.asyncio
async def test_current_group_poke_uses_group_poke_action(tmp_path) -> None:
    runtime, client, _ = await make_runtime(tmp_path)

    result = json.loads(
        await runtime.execute(
            FakeEvent(group_id="30001", admin=False),
            "qq_group_member_manage",
            "poke",
            {"group_id": 30001, "user_id": 10001},
        )
    )

    assert result["ok"] is True
    assert ("group_poke", {"group_id": 30001, "user_id": 10001}) in client.calls


@pytest.mark.asyncio
async def test_group_file_operations_allow_member_bot_role(tmp_path) -> None:
    runtime, client, _ = await make_runtime(
        tmp_path,
        {"permissions": {"allow_cross_group": True}},
    )
    client.roles[99999] = "member"

    for spec in OPERATION_MAP.values():
        if spec.tool != "qq_group_files":
            continue
        assert spec.bot_role == "member"
        authorized = await runtime.authorize(
            FakeEvent(admin=True),
            spec,
            {"group_id": 30001},
        )
        assert authorized == ("group", "30001", True)
    assert not any(action == "get_group_member_info" for action, _ in client.calls)


@pytest.mark.asyncio
async def test_cross_group_requires_private_admin_switch_and_existing_target(
    tmp_path,
) -> None:
    event = FakeEvent(admin=True)
    runtime, _, _ = await make_runtime(tmp_path)
    with pytest.raises(QQToolError, match="跨群操作"):
        await runtime.authorize(
            event,
            OPERATION_MAP["qq_group_info.detail"],
            {"group_id": 30001},
        )

    runtime, _, _ = await make_runtime(
        tmp_path / "enabled",
        {
            "permissions": {
                "allow_cross_group": True,
            }
        },
    )
    assert await runtime.authorize(
        event,
        OPERATION_MAP["qq_group_info.detail"],
        {"group_id": 30001},
    ) == ("group", "30001", True)


@pytest.mark.asyncio
async def test_cross_private_requires_private_admin_switch_and_existing_target(
    tmp_path,
) -> None:
    event = FakeEvent(admin=True)
    spec = OPERATION_MAP["qq_friend_history.list"]
    runtime, _, _ = await make_runtime(tmp_path)
    with pytest.raises(QQToolError, match="跨好友操作"):
        await runtime.authorize(event, spec, {"user_id": 20001})

    runtime, _, _ = await make_runtime(
        tmp_path / "enabled",
        {"permissions": {"allow_cross_private": True}},
    )
    assert await runtime.authorize(event, spec, {"user_id": 20001}) == (
        "private",
        "20001",
        True,
    )
    with pytest.raises(QQToolError, match="目标用户不在机器人好友列表中"):
        await runtime.authorize(event, spec, {"user_id": 30003})


@pytest.mark.asyncio
async def test_stranger_info_allows_only_admin_private_cross_target(tmp_path) -> None:
    runtime, client, _ = await make_runtime(tmp_path)
    spec = OPERATION_MAP["qq_user_info.stranger"]

    assert await runtime.authorize(
        FakeEvent(admin=True), spec, {"user_id": 30003}
    ) == ("private", "30003", True)
    assert not any(action == "get_friend_list" for action, _ in client.calls)

    with pytest.raises(QQToolError, match="仅允许管理员在私聊中"):
        await runtime.authorize(
            FakeEvent(admin=False), spec, {"user_id": 30003}
        )
    with pytest.raises(QQToolError, match="仅允许管理员在私聊中"):
        await runtime.authorize(
            FakeEvent(group_id="30001", admin=True), spec, {"user_id": 30003}
        )


@pytest.mark.asyncio
async def test_group_request_list_allows_admin_private_without_group_id(
    tmp_path,
) -> None:
    runtime, client, _ = await make_runtime(tmp_path)

    result = json.loads(
        await runtime.execute(
            FakeEvent(admin=True),
            "qq_group_request",
            "list",
            {},
        )
    )
    assert result["ok"] is True
    assert {item["group_id"] for item in result["data"]["join_requests"]} == {
        30001,
        30002,
    }
    assert ("get_group_system_msg", {}) in client.calls

    filtered = json.loads(
        await runtime.execute(
            FakeEvent(admin=True),
            "qq_group_request",
            "list",
            {"group_id": 30001},
        )
    )
    assert [item["group_id"] for item in filtered["data"]["join_requests"]] == [
        30001
    ]

    denied = json.loads(
        await runtime.execute(
            FakeEvent(admin=False),
            "qq_group_request",
            "list",
            {},
        )
    )
    assert denied["error"]["code"] == "permission_denied"


@pytest.mark.asyncio
async def test_cross_group_request_approve_and_reject_skip_confirmation(
    tmp_path,
) -> None:
    runtime, client, _ = await make_runtime(
        tmp_path,
        {"permissions": {"allow_cross_group": True}},
    )
    event = FakeEvent(admin=True)

    approved = json.loads(
        await runtime.execute(
            event,
            "qq_group_request",
            "approve",
            {"group_id": 30001, "flag": "request-1", "sub_type": "add"},
        )
    )
    assert approved["ok"] is True
    assert (
        "set_group_add_request",
        {"flag": "request-1", "sub_type": "add", "approve": True},
    ) in client.calls

    rejected = json.loads(
        await runtime.execute(
            event,
            "qq_group_request",
            "reject",
            {"group_id": 30001, "flag": "request-2", "sub_type": "add"},
        )
    )
    assert rejected["ok"] is True
    assert (
        "set_group_add_request",
        {"flag": "request-2", "sub_type": "add", "approve": False},
    ) in client.calls


@pytest.mark.asyncio
async def test_long_group_ban_skips_confirmation(tmp_path) -> None:
    runtime, client, _ = await make_runtime(tmp_path)

    result = json.loads(
        await runtime.execute(
            FakeEvent(group_id="30001", admin=True),
            "qq_group_member_manage",
            "ban",
            {"group_id": 30001, "user_id": 20001, "duration": 3600},
        )
    )

    assert result["ok"] is True
    assert (
        "set_group_ban",
        {"group_id": 30001, "user_id": 20001, "duration": 3600},
    ) in client.calls


@pytest.mark.asyncio
async def test_notice_delete_uses_napcat_notice_id_parameter(tmp_path) -> None:
    runtime, client, _ = await make_runtime(tmp_path)

    result = json.loads(
        await runtime.execute(
            FakeEvent(group_id="30001", admin=True),
            "qq_notice",
            "delete",
            {"group_id": 30001, "notice_id": "notice-1"},
        )
    )

    assert result["ok"] is True
    assert (
        "_del_group_notice",
        {"group_id": 30001, "notice_id": "notice-1"},
    ) in client.calls


@pytest.mark.asyncio
async def test_cross_session_write_skips_confirmation_unless_configured(
    tmp_path,
) -> None:
    event = FakeEvent(admin=True)
    params = {"user_id": 20001, "remark": "test"}
    runtime, client, _ = await make_runtime(
        tmp_path / "direct",
        {"permissions": {"allow_cross_private": True}},
    )

    direct = json.loads(
        await runtime.execute(event, "qq_friend_manage", "set_remark", params)
    )
    assert direct["ok"] is True
    assert (
        "set_friend_remark",
        {"user_id": 20001, "remark": "test"},
    ) in client.calls

    runtime, client, _ = await make_runtime(
        tmp_path / "configured",
        {
            "permissions": {"allow_cross_private": True},
            "confirmation": {
                "operations": ["qq_friend_manage.set_remark"]
            },
        },
    )
    configured = json.loads(
        await runtime.execute(event, "qq_friend_manage", "set_remark", params)
    )
    assert configured["error"]["code"] == "confirmation_required"
    assert not any(action == "set_friend_remark" for action, _ in client.calls)


@pytest.mark.asyncio
async def test_destructive_operation_requires_real_user_confirmation(tmp_path) -> None:
    runtime, client, _ = await make_runtime(tmp_path)
    event = FakeEvent()
    first = json.loads(
        await runtime.execute(event, "qq_friend_manage", "delete", {"user_id": "10001"})
    )
    assert first["error"]["code"] == "confirmation_required"
    assert not any(action == "delete_friend" for action, _ in client.calls)
    text = await runtime.confirm(event, first["pending_id"])
    assert text.startswith("已确认并执行")
    assert sum(action == "delete_friend" for action, _ in client.calls) == 1
    assert "不存在" in await runtime.confirm(event, first["pending_id"])


@pytest.mark.asyncio
async def test_local_path_and_base64_are_bounded(tmp_path) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    file_path = allowed / "image.bin"
    file_path.write_bytes(b"abc")
    runtime, _, _ = await make_runtime(
        tmp_path / "runtime",
        {"files": {"allowed_roots": [str(allowed)]}},
    )
    event = FakeEvent()
    assert (
        await runtime.resolve_input_file(event, {"path": str(file_path)}) == file_path
    )
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"outside")
    with pytest.raises(QQToolError, match="允许目录"):
        await runtime.resolve_input_file(event, {"path": str(outside)})
    decoded = await runtime.resolve_input_file(
        event, {"base64": base64.b64encode(b"hello").decode()}
    )
    assert decoded.read_bytes() == b"hello"


@pytest.mark.asyncio
async def test_convert_record_reports_generated_file_and_usable_ref(tmp_path) -> None:
    runtime, _, _ = await make_runtime(tmp_path)
    event = FakeEvent()
    output = tmp_path / "voice.amr.mp3"
    output.write_bytes(b"ID3-converted-audio")

    result = await runtime.normalize_media_result(
        event,
        OPERATION_MAP["qq_media.convert_record"],
        {
            "file": str(output),
            "url": str(output),
            "file_name": "voice.amr",
            "file_size": "2070",
        },
    )

    assert result == {
        "file_name": "voice.amr.mp3",
        "file_size": 19,
        "media_ref": result["media_ref"],
    }
    resolved = await runtime.storage.resolve_media_ref(
        result["media_ref"], event.get_sender_id()
    )
    assert resolved == output.resolve()
    action, params = await runtime.prepare_message(
        event,
        {
            "target": {"type": "current"},
            "components": [
                {
                    "type": "file",
                    "media_ref": result["media_ref"],
                    "name": "converted.mp3",
                }
            ],
        },
    )
    assert action == "send_private_msg"
    assert params["message"] == [
        {
            "type": "file",
            "data": {"file": str(output.resolve()), "name": "converted.mp3"},
        }
    ]


@pytest.mark.asyncio
async def test_ocr_result_can_be_read_across_pages(tmp_path) -> None:
    runtime, _, _ = await make_runtime(tmp_path)
    event = FakeEvent()
    encoded = base64.b64encode(b"image").decode()

    first = json.loads(
        await runtime.execute(
            event,
            "qq_media",
            "ocr",
            {"base64": encoded, "page_size": 20},
        )
    )
    second = json.loads(
        await runtime.execute(
            event,
            "qq_media",
            "ocr",
            {"base64": encoded, "cursor": first["next_cursor"], "page_size": 20},
        )
    )

    assert first["summary"] == "已返回 20/33 项"
    assert [item["text"] for item in first["data"]] == [
        f"line-{index}" for index in range(20)
    ]
    assert first["next_cursor"] == "20"
    assert second["summary"] == "已返回 13/33 项"
    assert [item["text"] for item in second["data"]] == [
        f"line-{index}" for index in range(20, 33)
    ]
    assert second["next_cursor"] is None
    with pytest.raises(QQToolError, match="cursor 无效"):
        runtime.paginate([{"text": "line"}], "invalid", 20)


@pytest.mark.asyncio
async def test_url_validator_rejects_private_addresses_by_default(tmp_path) -> None:
    runtime, _, _ = await make_runtime(tmp_path)
    with pytest.raises(QQToolError, match="私网或保留地址"):
        await runtime.validate_url("http://127.0.0.1/resource")


@pytest.mark.asyncio
async def test_structured_message_is_converted_to_onebot_segments(tmp_path) -> None:
    runtime, _, _ = await make_runtime(tmp_path)
    event = FakeEvent()
    action, params = await runtime.prepare_message(
        event,
        {
            "target": {"type": "current"},
            "components": [
                {"type": "text", "text": "hello"},
                {"type": "face", "id": "14"},
                {"type": "dice"},
                {"type": "reply", "id": "123"},
            ],
        },
    )
    assert action == "send_private_msg"
    assert params["user_id"] == 10001
    assert [item["type"] for item in params["message"]] == [
        "text",
        "face",
        "dice",
        "reply",
    ]


@pytest.mark.asyncio
async def test_window_shake_is_not_exposed_as_a_message_component(tmp_path) -> None:
    runtime, _, _ = await make_runtime(tmp_path)

    with pytest.raises(QQToolError, match="type 不受支持"):
        await runtime.prepare_message(
            FakeEvent(),
            {
                "target": {"type": "current"},
                "components": [{"type": "shake"}],
            },
        )


@pytest.mark.asyncio
async def test_share_is_not_exposed_as_a_message_component(tmp_path) -> None:
    runtime, _, _ = await make_runtime(tmp_path)

    with pytest.raises(QQToolError, match="type 不受支持"):
        await runtime.prepare_message(
            FakeEvent(),
            {
                "target": {"type": "current"},
                "components": [
                    {
                        "type": "share",
                        "url": "https://www.qq.com/",
                        "title": "unsupported",
                    }
                ],
            },
        )
