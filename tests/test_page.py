from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from astrbot_plugin_qq_enhance.catalog import OPERATIONS, TOOL_OPERATIONS
from astrbot_plugin_qq_enhance.errors import QQToolError
from astrbot_plugin_qq_enhance.main import (
    PLUGIN_NAME,
    QQEnhancePlugin,
)
from astrbot_plugin_qq_enhance.providers.napcat import NapCatProvider
from astrbot_plugin_qq_enhance.runtime import QQRuntime, validate_config


class PageClient:
    """Provide deterministic read-only OneBot diagnostics for Page tests."""

    def __init__(self) -> None:
        self.version_info = {"app_name": "NapCat.OneBot", "app_version": "4.18.19"}

    async def call_action(self, action: str, **params) -> dict:
        """Return a fixture response for one diagnostic action.

        Args:
            action: OneBot action name.

        Returns:
            Fixture action result.

        Raises:
            AssertionError: If the Page calls an unexpected action.
        """

        responses = {
            "get_version_info": self.version_info,
            "get_status": {"online": True, "good": True},
            "get_login_info": {"user_id": 20002, "nickname": "Test Bot"},
        }
        if action not in responses:
            raise AssertionError(f"Unexpected diagnostic action: {action}")
        return responses[action]


class PagePlatform:
    """Expose the minimum platform interface required by the Page endpoint."""

    def __init__(self, platform_id: str, name: str = "aiocqhttp") -> None:
        self.platform_id = platform_id
        self.name = name
        self.client = PageClient()

    def meta(self) -> SimpleNamespace:
        """Return platform metadata.

        Returns:
            Platform ID and adapter name.
        """

        return SimpleNamespace(id=self.platform_id, name=self.name)

    def get_client(self) -> PageClient:
        """Return the fake OneBot client.

        Returns:
            Deterministic Page test client.
        """

        return self.client


def test_plugin_registers_read_only_diagnostics_api(tmp_path) -> None:
    context = SimpleNamespace(register_web_api=Mock())

    with (
        patch(
            "astrbot_plugin_qq_enhance.main.get_astrbot_plugin_data_path",
            return_value=str(tmp_path),
        ),
        patch("astrbot_plugin_qq_enhance.main.QQRuntime") as runtime_factory,
    ):
        runtime_factory.return_value.config = validate_config(None)
        plugin = QQEnhancePlugin(context)

    context.register_web_api.assert_called_once()
    route, handler, methods, description = context.register_web_api.call_args.args
    assert route == f"/{PLUGIN_NAME}/diagnostics"
    assert handler.__self__ is plugin
    assert methods == ["GET"]
    assert "Read-only" in description


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("persist_verification_in_history", [False, True])
async def test_diagnostics_page_api_returns_sanitized_read_only_state(
    enabled,
    persist_verification_in_history,
) -> None:
    plugin = object.__new__(QQEnhancePlugin)
    plugin.config = validate_config(
        {
            "inbound": {
                "component_spoof_protection": {
                    "enabled": enabled,
                    "persist_verification_in_history": persist_verification_in_history,
                }
            }
        }
    )
    plugin.context = SimpleNamespace(
        platform_manager=SimpleNamespace(
            platform_insts=[
                PagePlatform("platform-a"),
                PagePlatform("unrelated", name="webchat"),
            ]
        )
    )
    plugin.runtime = SimpleNamespace(
        operation_enabled=lambda _operation_id: True,
        enabled_tools=lambda: set(TOOL_OPERATIONS),
    )
    plugin.storage = SimpleNamespace(
        list_audit=AsyncMock(
            return_value=[
                {
                    "audit_id": 1,
                    "created_at": 100,
                    "operation_id": "qq_status.runtime",
                    "caller_id": "10001",
                    "session_id": "private-session",
                    "platform_id": "platform-a",
                    "target_kind": "none",
                    "target_id": "",
                    "risk": "read",
                    "decision": "allowed",
                    "result_code": "ok",
                    "pending_id": "",
                    "params_hash": "secret-hash",
                    "duration_ms": 3,
                }
            ]
        ),
        list_live_pending=AsyncMock(
            return_value=[
                {
                    "pending_id": "a1b2c3d4",
                    "caller_id": "10001",
                    "session_id": "private-session",
                    "platform_id": "platform-a",
                    "operation_id": "qq_friend_manage.delete",
                    "action": "delete_friend",
                    "params_json": "secret-params",
                    "target_kind": "private",
                    "target_id": "10002",
                    "summary": "Delete one friend",
                    "created_at": 100,
                    "expires_at": 4_000_000_000,
                }
            ]
        ),
    )

    response = await plugin.page_diagnostics()
    payload = json.loads(response.body)

    assert payload["configuration"]["component_spoof_protection_enabled"] is enabled
    assert (
        payload["configuration"]["persist_verification_in_history"]
        is persist_verification_in_history
    )
    assert "component_spoof_mode" not in payload["configuration"]
    assert payload["summary"]["platforms"] == 1
    assert payload["summary"]["reachable_platforms"] == 1
    assert payload["summary"]["compatible_platforms"] == 1
    assert payload["summary"]["tools_total"] == len(TOOL_OPERATIONS)
    assert payload["summary"]["operations_total"] == len(OPERATIONS)
    assert {
        row["provider_id"]: row["supported_versions"] for row in payload["contracts"]
    } == {"napcat": ">=4.18.19", "snowluma": ">=1.14.22"}
    assert payload["platforms"][0] == {
        "platform_id": "platform-a",
        "selected": True,
        "reachable": True,
        "online": True,
        "good": True,
        "implementation": "NapCat.OneBot",
        "provider_id": "napcat",
        "version": "4.18.19",
        "compatible": True,
        "account_id": "20002",
        "nickname": "Test Bot",
        "errors": [],
    }
    assert [item["category"] for item in payload["capabilities"]] == sorted(
        item.category for item in OPERATIONS
    )
    runtime_capability = next(
        item
        for item in payload["capabilities"]
        if item["operation_id"] == "qq_status.runtime"
    )
    assert runtime_capability["display_name"] == "获取运行状态"
    assert runtime_capability["configured"] is True
    assert runtime_capability["supported"] is True
    assert runtime_capability["platforms"] == [
        {
            "platform_id": "platform-a",
            "supported": True,
            "reason": "",
            "limitations": [],
        }
    ]
    assert "session_id" not in payload["audits"][0]
    assert "params_hash" not in payload["audits"][0]
    assert "session_id" not in payload["pending_confirmations"][0]
    assert "action" not in payload["pending_confirmations"][0]
    assert "params_json" not in payload["pending_confirmations"][0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("version_info", "error_code"),
    [
        ({"app_name": "NapCat.OneBot", "app_version": "4.18.19"}, None),
        ({"app_name": "NapCat.OneBot", "app_version": "v4.99.0"}, None),
        (
            {"app_name": "NapCat.OneBot", "app_version": "4.18.18"},
            "unsupported_version",
        ),
        ({"app_name": "NapCat.OneBot", "app_version": "5.0.0"}, None),
        ({"app_name": "NapCat.OneBot", "app_version": "unknown"}, "response_invalid"),
        (
            {"app_name": "SnowLuma", "app_version": "1.14.22-node"},
            "unsupported_version",
        ),
        (
            {
                "app_name": "SnowLuma",
                "app_version": "1.14.22-node",
                "protocol_version": "v11",
            },
            None,
        ),
        (
            {
                "app_name": "SnowLuma",
                "app_version": "1.14.23-node",
                "protocol_version": "v11",
            },
            None,
        ),
        (
            {
                "app_name": "SnowLuma",
                "app_version": "2.0.0",
                "protocol_version": "v11",
            },
            None,
        ),
        (
            {
                "app_name": "SnowLuma",
                "app_version": "1.14.21-node",
                "protocol_version": "v11",
            },
            "unsupported_version",
        ),
        (
            {
                "app_name": "SnowLuma",
                "app_version": "1.14.22-node",
                "protocol_version": "v12",
            },
            "unsupported_version",
        ),
        ({"app_name": "Other", "app_version": "4.18.19"}, "unsupported_version"),
        ([], "response_invalid"),
    ],
)
async def test_diagnostics_and_execution_share_provider_validation(
    version_info, error_code
) -> None:
    platform = PagePlatform("platform-a")
    platform.client.version_info = version_info
    plugin = object.__new__(QQEnhancePlugin)
    plugin.config = validate_config(None)
    plugin.context = SimpleNamespace(
        platform_manager=SimpleNamespace(platform_insts=[platform]),
        get_platform_inst=lambda _platform_id: platform,
    )
    plugin.storage = SimpleNamespace(
        list_audit=AsyncMock(return_value=[]),
        list_live_pending=AsyncMock(return_value=[]),
    )
    runtime = object.__new__(QQRuntime)
    runtime.config = plugin.config
    runtime.context = plugin.context
    runtime._verified_platforms = {}
    event = SimpleNamespace(
        get_platform_name=lambda: "aiocqhttp", get_platform_id=lambda: "platform-a"
    )
    if error_code:
        with pytest.raises(QQToolError) as caught:
            await runtime.verify_platform(event)
        assert caught.value.code == error_code
    else:
        await runtime.verify_platform(event)
    payload = json.loads((await plugin.page_diagnostics()).body)
    assert payload["platforms"][0]["compatible"] is (error_code is None)
    capability = next(
        item
        for item in payload["capabilities"]
        if item["operation_id"] == "qq_status.runtime"
    )
    assert capability["configured"] is True
    assert capability["supported"] is (error_code is None)
    assert capability["enabled"] is (error_code is None)
    if error_code:
        assert caught.value.message in payload["platforms"][0]["errors"][0]
        assert capability["disabled_reason"] == "provider_unsupported"
    web = next(
        item
        for item in payload["capabilities"]
        if item["operation_id"] == "read_url.read"
    )
    assert web["supported"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("platform_id", ["", "platform-b"])
async def test_diagnostics_reports_capabilities_per_selected_platform(
    monkeypatch, platform_id
) -> None:
    provider = NapCatProvider()
    provider.actions -= {"get_recent_contact"}
    monkeypatch.setattr("astrbot_plugin_qq_enhance.providers.PROVIDERS", (provider,))
    first = PagePlatform("platform-a")
    second = PagePlatform("platform-b")
    second.client.version_info = {"app_name": "SnowLuma", "app_version": "1.14.22-node"}
    plugin = object.__new__(QQEnhancePlugin)
    plugin.config = validate_config({"platform": {"platform_id": platform_id}})
    plugin.context = SimpleNamespace(
        platform_manager=SimpleNamespace(platform_insts=[first, second])
    )
    plugin.storage = SimpleNamespace(
        list_audit=AsyncMock(return_value=[]),
        list_live_pending=AsyncMock(return_value=[]),
    )
    payload = json.loads((await plugin.page_diagnostics()).body)
    recent = next(
        item
        for item in payload["capabilities"]
        if item["operation_id"] == "qq_recent_contacts.list"
    )
    status = next(
        item
        for item in payload["capabilities"]
        if item["operation_id"] == "qq_status.runtime"
    )
    assert recent["configured"] is True
    assert recent["supported"] is False
    assert recent["enabled"] is False
    assert status["supported"] is (not platform_id)
    expected = [{"platform_id": "platform-b", "supported": False}]
    if not platform_id:
        expected.insert(0, {"platform_id": "platform-a", "supported": False})
    assert [
        {"platform_id": row["platform_id"], "supported": row["supported"]}
        for row in recent["platforms"]
    ] == expected
    assert all("reason" in row and "limitations" in row for row in recent["platforms"])


def test_diagnostics_page_assets_and_titles_exist() -> None:
    plugin_root = Path(__file__).resolve().parents[1]
    page_root = plugin_root / "pages" / "diagnostics"
    for filename in ("index.html", "app.js", "style.css"):
        assert (page_root / filename).is_file()

    for locale in ("zh-CN", "en-US"):
        i18n_path = plugin_root / ".astrbot-plugin" / "i18n" / f"{locale}.json"
        translations = json.loads(i18n_path.read_text(encoding="utf-8"))
        assert translations["pages"]["diagnostics"]["title"]


@pytest.mark.asyncio
async def test_diagnostics_explains_snowluma_limits_alongside_napcat():
    first, second = PagePlatform("platform-a"), PagePlatform("platform-b")
    second.client.version_info = {
        "app_name": "SnowLuma",
        "app_version": "1.14.22-node",
        "protocol_version": "v11",
    }
    plugin = object.__new__(QQEnhancePlugin)
    plugin.config = validate_config(None)
    plugin.context = SimpleNamespace(
        platform_manager=SimpleNamespace(platform_insts=[first, second])
    )
    plugin.storage = SimpleNamespace(
        list_audit=AsyncMock(return_value=[]),
        list_live_pending=AsyncMock(return_value=[]),
    )
    payload = json.loads((await plugin.page_diagnostics()).body)
    assert [row["provider_id"] for row in payload["platforms"]] == [
        "napcat",
        "snowluma",
    ]
    capabilities = {row["operation_id"]: row for row in payload["capabilities"]}
    for operation in ("qq_recent_contacts.list", "qq_group_info.detail_ex"):
        row = capabilities[operation]
        assert row["supported"] is True
        assert [platform["supported"] for platform in row["platforms"]] == [True, False]
        assert row["platforms"][1]["reason"]
    ocr = capabilities["qq_media.ocr"]["platforms"]
    assert not ocr[0]["limitations"]
    assert any("file_id" in item for item in ocr[1]["limitations"])
