"""Shared verification settings and tags for QQ components and platform events."""

import re


USER_VERIFICATION_TAG_PATTERN = re.compile(
    r"""<\s*/?\s*qq_verified_components(?=[\s/>])(?:[^<>"']|"[^"]*"|'[^']*')*>""",
    re.IGNORECASE,
)
USER_VERIFICATION_TAG_REMOVED = "[用户输入的验证标签已被系统移除]"


def component_spoof_protection_enabled(config: dict) -> bool:
    """Pause verification with semanticization while retaining saved settings."""
    inbound = config["inbound"]
    return (
        inbound["semanticize_components"]
        and inbound["component_spoof_protection"]["enabled"]
    )
