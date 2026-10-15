from ..errors import QQToolError
from .base import OneBotProvider, ProviderBinding, VersionInfo
from .napcat import NapCatProvider

NAPCAT = NapCatProvider()
PROVIDERS: tuple[OneBotProvider, ...] = (NAPCAT,)


def resolve_provider(info: VersionInfo) -> ProviderBinding:
    """Select and validate an explicitly supported OneBot implementation."""
    for provider in PROVIDERS:
        if provider.matches(info):
            provider.validate_version(info)
            return ProviderBinding(info, provider)
    raise QQToolError("unsupported_version", "当前 OneBot 实现不是 NapCat")
