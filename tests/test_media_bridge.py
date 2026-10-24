from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from astrbot_plugin_qq_enhance.errors import QQToolError
from astrbot_plugin_qq_enhance.media_bridge import inspect_legacy_reference


@pytest.mark.asyncio
async def test_missing_media_plugin_reports_unavailable_without_importing_it():
    context = SimpleNamespace(get_registered_star=lambda _name: None)
    with pytest.raises(QQToolError, match="Media 管理"):
        await inspect_legacy_reference(context, object(), "img_" + "a" * 24, "inspect")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation", "view"), [("inspect", "original"), ("inspect_animation", "animation")]
)
async def test_legacy_tools_forward_to_public_service(operation, view):
    plugin = SimpleNamespace(
        media_manager_api_version=1,
        ready=True,
        inspect_reference=AsyncMock(return_value="result"),
    )
    context = SimpleNamespace(
        get_registered_star=lambda _name: SimpleNamespace(
            activated=True, star_cls=plugin
        )
    )
    event = object()
    image_ref = "img_" + "a" * 24
    assert (
        await inspect_legacy_reference(context, event, image_ref, operation) == "result"
    )
    plugin.inspect_reference.assert_awaited_once_with(event, image_ref, view)
