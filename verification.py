"""Reserved verification tags shared by QQ components and platform events."""

import re


USER_VERIFICATION_TAG_PATTERN = re.compile(
    r"""<\s*/?\s*qq_verified_components(?=[\s/>])(?:[^<>"']|"[^"]*"|'[^']*')*>""",
    re.IGNORECASE,
)
USER_VERIFICATION_TAG_REMOVED = "[用户输入的验证标签已被系统移除]"
