"""Temporary legacy QQ tool forwarding; no import of the media plugin."""

from __future__ import annotations

from .errors import QQToolError

MEDIA_PLUGIN_NAME = "astrbot_plugin_media_manager"


async def inspect_legacy_reference(context, event, image_ref, operation):
    getter = getattr(context, "get_registered_star", None)
    star = getter(MEDIA_PLUGIN_NAME) if callable(getter) else None
    plugin = getattr(star, "star_cls", None) if star and star.activated else None
    if (
        plugin is None
        or getattr(plugin, "media_manager_api_version", 0) != 1
        or not getattr(plugin, "ready", False)
    ):
        raise QQToolError(
            "capability_unavailable",
            "图片查看已迁移至独立插件“Media 管理”，请安装并启用该插件",
        )
    view = "animation" if operation == "inspect_animation" else "original"
    try:
        return await plugin.inspect_reference(event, image_ref, view)
    except Exception as exc:
        code = getattr(exc, "code", None)
        message = getattr(exc, "message", None)
        if isinstance(code, str) and isinstance(message, str):
            raise QQToolError(code, message) from exc
        raise
