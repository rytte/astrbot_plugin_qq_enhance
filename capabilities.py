from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .catalog import OperationSpec
from .providers.base import OneBotProvider


@dataclass(frozen=True, slots=True)
class OperationAvailability:
    configured: bool
    supported: bool | None
    disabled_reason: str = ""

    @property
    def enabled(self) -> bool:
        # Before platform detection, tool schemas are configuration candidates.
        # Execution always requires a verified provider and supported capability.
        return self.configured and self.supported is not False


def operation_availability(
    config: dict[str, Any],
    spec: OperationSpec,
    provider: OneBotProvider | None = None,
) -> OperationAvailability:
    """Keep configuration switches separate from upstream contract support."""
    reason = ""
    if spec.category == "web" and not config["web_reader"]["enabled"]:
        reason = "web_reader_disabled"
    elif (
        spec.operation_id == "qq_media.inspect"
        and not config["context_images"]["enabled"]
    ):
        reason = "context_images_disabled"
    elif (
        config["toolsets"]["enabled_packs"]
        and spec.category not in config["toolsets"]["enabled_packs"]
    ):
        reason = "pack_not_enabled"
    elif spec.operation_id in config["toolsets"]["disabled_operations"]:
        reason = "disabled_by_config"
    configured = not reason
    # Web reading is local and independent of the OneBot implementation.
    capability = (
        provider.capability(spec) if provider and spec.category != "web" else None
    )
    supported = (
        True if spec.category == "web" else capability.supported if capability else None
    )
    if configured and capability and not capability.supported:
        reason = "provider_unsupported"
    return OperationAvailability(configured, supported, reason)
