from __future__ import annotations

import pytest

from astrbot_plugin_qq_enhance.catalog import OPERATION_MAP
from astrbot_plugin_qq_enhance.errors import QQToolError
from astrbot_plugin_qq_enhance.providers import NAPCAT, SNOWLUMA, resolve_provider
from astrbot_plugin_qq_enhance.providers.base import VersionInfo


@pytest.mark.parametrize(
    "version",
    ["1.14.22", "1.14.22-node", "1.14.23", "1.14.23-node", "1.15.0-node", "2.0.0"],
)
def test_snowluma_accepts_versions_at_or_above_minimum(version):
    binding = resolve_provider(VersionInfo("SnowLuma", version, "v11"))
    assert binding.provider is SNOWLUMA


@pytest.mark.parametrize(
    "info,code",
    [
        (VersionInfo("SnowLuma", "1.14.21-node", "v11"), "unsupported_version"),
        (VersionInfo("SnowLuma", "1.13.99", "v11"), "unsupported_version"),
        (VersionInfo("SnowLuma", "0.99.99", "v11"), "unsupported_version"),
        (VersionInfo("SnowLuma", "unknown", "v11"), "response_invalid"),
        (VersionInfo("SnowLuma", "1.14.22-node-dev", "v11"), "response_invalid"),
        (VersionInfo("SnowLuma", "1.14.22-node", "v12"), "unsupported_version"),
        (VersionInfo("SnowLuma", "1.14.22-node"), "unsupported_version"),
        (VersionInfo("Other", "1.14.22", "v11"), "unsupported_version"),
    ],
)
def test_unsupported_implementations_versions_and_protocols_are_rejected(info, code):
    with pytest.raises(QQToolError) as caught:
        resolve_provider(info)
    assert caught.value.code == code


@pytest.mark.parametrize(
    "operation,params,expected",
    [
        (
            "qq_group_files.move",
            {
                "group_id": 30001,
                "file_id": "file",
                "current_parent_directory": "/",
                "target_parent_directory": "/folder",
            },
            {
                "group_id": 30001,
                "file_id": "file",
                "parent_directory": "/",
                "target_directory": "/folder",
            },
        ),
        (
            "qq_group_files.delete",
            {"group_id": 30001, "file_id": "file", "busid": 102},
            {"group_id": 30001, "file_id": "file"},
        ),
        (
            "qq_private_files.url",
            {"user_id": 10001, "file_id": "file", "file_hash": "hash"},
            {"user_id": 10001, "file_id": "file", "file_hash": "hash"},
        ),
        ("qq_group_request.list", {"group_id": 30001}, {"group_id": 30001}),
        ("qq_friend_list.friends", {"no_cache": False}, {}),
        (
            "qq_group_manage.leave",
            {"group_id": 30001, "is_dismiss": False},
            {"group_id": 30001},
        ),
    ],
)
def test_snowluma_wire_parameters(operation, params, expected):
    spec = OPERATION_MAP[operation]
    action, wire = SNOWLUMA.prepare_action(spec, params, page_size=20)
    assert action == spec.action
    assert wire == expected


@pytest.mark.parametrize(
    "operation,params",
    [
        ("qq_group_history.list", {"message_seq": 0}),
        ("qq_friend_history.list", {"message_seq": 123}),
        ("qq_group_history.list", {"message_id": 2**31}),
        ("qq_friend_history.list", {"message_id": -(2**31) - 1}),
        ("qq_status.clients", {"no_cache": True}),
        ("qq_friend_list.friends", {"no_cache": True}),
        ("qq_user_info.stranger", {"no_cache": True}),
        ("qq_account_manage.set_profile", {"company": "test"}),
        ("qq_account_manage.set_profile", {"email": "test@example.test"}),
        ("qq_account_manage.set_profile", {"college": "test"}),
        ("qq_friend_request.approve", {"remark": "test"}),
        ("qq_group_member_manage.title", {"duration": 0}),
        ("qq_notice.send", {"title": "test"}),
        ("qq_group_manage.leave", {"is_dismiss": True}),
        ("qq_group_manage.avatar", {"cache": True}),
        ("qq_media.ocr", {"path": "image.png"}),
        ("qq_media.ocr", {"base64": "aGVsbG8="}),
        ("qq_media.ocr", {"media_ref": "ref"}),
        ("qq_media.ocr", {"file_id": "file:///tmp/image.png"}),
        ("qq_media.ocr", {"file_id": "https://example.test/image.png"}),
        ("qq_media.ocr", {"file_id": "C:\\images\\test.png"}),
        ("qq_media.ocr", {"file_id": "/tmp/image.png"}),
        ("qq_media.ocr", {"file_id": ""}),
    ],
)
def test_snowluma_rejects_parameters_it_cannot_honor(operation, params):
    with pytest.raises(QQToolError) as caught:
        SNOWLUMA.validate_parameters(OPERATION_MAP[operation], params)
    assert caught.value.code == "invalid_parameters"


@pytest.mark.parametrize(
    "operation,params",
    [
        ("qq_group_history.list", {"message_id": -123}),
        ("qq_media.ocr", {"file_id": "image-id"}),
        ("qq_private_files.url", {"file_hash": "hash"}),
    ],
)
def test_napcat_rejects_snowluma_only_parameters(operation, params):
    with pytest.raises(QQToolError) as caught:
        NAPCAT.validate_parameters(OPERATION_MAP[operation], params)
    assert caught.value.code == "invalid_parameters"
