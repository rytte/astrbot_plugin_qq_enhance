from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from astrbot_plugin_qq_extension_tools.catalog import OPERATIONS, TOOL_OPERATIONS
from astrbot_plugin_qq_extension_tools.main import (
    PLUGIN_NAME,
    QQExtensionToolsPlugin,
)
from astrbot_plugin_qq_extension_tools.runtime import validate_config


class PageClient:
    """Provide deterministic read-only OneBot diagnostics for Page tests."""

    async def call_action(self, action: str) -> dict:
        """Return a fixture response for one diagnostic action.

        Args:
            action: OneBot action name.

        Returns:
            Fixture action result.

        Raises:
            AssertionError: If the Page calls an unexpected action.
        """

        responses = {
            "get_version_info": {
                "app_name": "NapCat.OneBot",
                "app_version": "4.18.19",
            },
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
            "astrbot_plugin_qq_extension_tools.main.get_astrbot_plugin_data_path",
            return_value=str(tmp_path),
        ),
        patch("astrbot_plugin_qq_extension_tools.main.QQRuntime"),
    ):
        plugin = QQExtensionToolsPlugin(context)

    context.register_web_api.assert_called_once()
    route, handler, methods, description = context.register_web_api.call_args.args
    assert route == f"/{PLUGIN_NAME}/diagnostics"
    assert handler.__self__ is plugin
    assert methods == ["GET"]
    assert "Read-only" in description


@pytest.mark.asyncio
async def test_diagnostics_page_api_returns_sanitized_read_only_state() -> None:
    plugin = object.__new__(QQExtensionToolsPlugin)
    plugin.config = validate_config(None)
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

    assert payload["summary"]["platforms"] == 1
    assert payload["summary"]["reachable_platforms"] == 1
    assert payload["summary"]["compatible_platforms"] == 1
    assert payload["summary"]["tools_total"] == len(TOOL_OPERATIONS)
    assert payload["summary"]["operations_total"] == len(OPERATIONS)
    assert payload["contract"]["supported_versions"] == ">=4.18.19,<5.0.0"
    assert payload["platforms"][0] == {
        "platform_id": "platform-a",
        "selected": True,
        "reachable": True,
        "online": True,
        "good": True,
        "implementation": "NapCat.OneBot",
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
    assert "session_id" not in payload["audits"][0]
    assert "params_hash" not in payload["audits"][0]
    assert "session_id" not in payload["pending_confirmations"][0]
    assert "action" not in payload["pending_confirmations"][0]
    assert "params_json" not in payload["pending_confirmations"][0]


def test_diagnostics_page_assets_and_titles_exist() -> None:
    plugin_root = Path(__file__).resolve().parents[1]
    page_root = plugin_root / "pages" / "diagnostics"
    for filename in ("index.html", "app.js", "style.css"):
        assert (page_root / filename).is_file()

    for locale in ("zh-CN", "en-US"):
        i18n_path = plugin_root / ".astrbot-plugin" / "i18n" / f"{locale}.json"
        translations = json.loads(i18n_path.read_text(encoding="utf-8"))
        assert translations["pages"]["diagnostics"]["title"]
