from ..errors import QQToolError
from .base import OneBotProvider, ProviderBinding, VersionInfo
from .napcat import NapCatProvider
from .snowluma import SnowLumaProvider

NAPCAT = NapCatProvider()
SNOWLUMA = SnowLumaProvider()
PROVIDERS: tuple[OneBotProvider, ...] = (NAPCAT, SNOWLUMA)


def resolve_provider(info: VersionInfo) -> ProviderBinding:
    """Select and validate an explicitly supported OneBot implementation."""
    for provider in PROVIDERS:
        if provider.matches(info):
            provider.validate_version(info)
            return ProviderBinding(info, provider)
    raise QQToolError(
        "unsupported_version", "当前 OneBot 实现不受支持，仅支持 NapCat 和 SnowLuma"
    )


def provider_contracts() -> list[dict[str, str]]:
    return [
        {
            "provider_id": provider.id,
            "implementation": provider.display_name,
            "version": provider.contract_version,
            "supported_versions": provider.supported_versions,
        }
        for provider in PROVIDERS
    ]
