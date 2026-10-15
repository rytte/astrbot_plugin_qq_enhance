from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ..catalog import OperationSpec
from ..errors import QQToolError


@dataclass(frozen=True, slots=True)
class VersionInfo:
    implementation: str
    version: str

    @classmethod
    def from_response(cls, data: Any) -> VersionInfo:
        """Read the identity fields used by execution and diagnostics."""
        if not isinstance(data, dict):
            raise QQToolError("response_invalid", "get_version_info 返回格式无效")
        return cls(
            implementation=str(
                data.get("app_name")
                or data.get("implementation")
                or data.get("app_full_name")
                or ""
            ),
            version=str(data.get("app_version") or data.get("version") or ""),
        )


@dataclass(frozen=True, slots=True)
class Capability:
    supported: bool
    reason: str = ""

    def require(self) -> None:
        if not self.supported:
            raise QQToolError("capability_unavailable", self.reason)


@dataclass(frozen=True, slots=True)
class LocalMedia:
    """Describe an upstream media file; the runtime owns validation and refs."""

    path: str
    path_fields: tuple[str, ...]
    include_metadata: bool = False


class OneBotProvider(Protocol):
    """Pure protocol conversion, without authorization, I/O or persistence."""

    id: str
    display_name: str
    contract_version: str
    supported_versions: str

    def matches(self, info: VersionInfo) -> bool: ...

    def validate_version(self, info: VersionInfo) -> None: ...

    def capability(self, spec: OperationSpec) -> Capability: ...

    def prepare_action(
        self,
        spec: OperationSpec,
        params: dict[str, Any],
        *,
        page_size: int,
        resolved_file: str | None = None,
    ) -> tuple[str | None, dict[str, Any]]: ...

    def local_media(self, spec: OperationSpec, data: Any) -> LocalMedia | None: ...


@dataclass(frozen=True, slots=True)
class ProviderBinding:
    info: VersionInfo
    provider: OneBotProvider
