"""Value objects used by the HeatControl API package."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .discovery import MANUFACTURER, MODEL


def _require_object(payload: dict[str, Any], field: str) -> dict[str, Any]:
    value = payload.get(field)
    if not isinstance(value, dict):
        raise ValueError(f"{field} payload missing object")
    return value


def _require_str(payload: dict[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{field} must not be empty")
    return stripped


def _optional_str(payload: dict[str, Any], field: str) -> str | None:
    value = payload.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string when provided")
    stripped = value.strip()
    return stripped or None


def _require_int(payload: dict[str, Any], field: str) -> int:
    value = payload.get(field)
    if isinstance(value, bool):
        raise ValueError(f"{field} must be an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if stripped:
            try:
                return int(stripped, 10)
            except ValueError as exc:
                raise ValueError(f"{field} must be an integer") from exc
    raise ValueError(f"{field} must be an integer")


def _require_bool(payload: dict[str, Any], field: str) -> bool:
    value = payload.get(field)
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1"}:
            return True
        if normalized in {"false", "0"}:
            return False
    raise ValueError(f"{field} must be a boolean")


@dataclass(slots=True, frozen=True)
class DeviceInfo:
    """Device information returned by the connector ping endpoint."""

    serial: str
    version: str
    server_public_key: str
    manufacturer: str = MANUFACTURER
    model: str = MODEL
    name: str | None = None

    @classmethod
    def from_ping_payload(cls, payload: dict[str, Any]) -> "DeviceInfo":
        device = _require_object(payload, "device")
        protocol = _require_object(payload, "protocol")
        serial = _require_str(device, "serial")
        version = _require_str(device, "version")
        server_public_key = _require_str(protocol, "server_public_key")
        manufacturer = _optional_str(device, "manufacturer") or MANUFACTURER
        model = _optional_str(device, "model") or MODEL
        name = _optional_str(device, "name")
        return cls(
            serial=serial,
            version=version,
            server_public_key=server_public_key,
            manufacturer=manufacturer,
            model=model,
            name=name,
        )


@dataclass(slots=True, frozen=True)
class PairingStartResult:
    """Metadata returned after starting pairing."""

    expires_at: int
    pairing_active: bool
    replaces_existing_binding: bool
    existing_binding_display_name: str | None = None
    server_public_key: str | None = None

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "PairingStartResult":
        result = _require_object(payload, "result")
        return cls(
            expires_at=_require_int(result, "expires_at"),
            pairing_active=_require_bool(result, "pairing_active"),
            replaces_existing_binding=_require_bool(result, "replaces_existing_binding"),
            existing_binding_display_name=_optional_str(
                result, "existing_binding_display_name"
            ),
            server_public_key=_optional_str(result, "server_public_key"),
        )


@dataclass(slots=True, frozen=True)
class PairingConfirmResult:
    """Metadata returned after confirming pairing."""

    ha_instance_id: str
    display_name: str
    integration_version: str
    revision: int
    confirmed_at: int
    server_public_key: str

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "PairingConfirmResult":
        result = _require_object(payload, "result")
        return cls(
            ha_instance_id=_require_str(result, "ha_instance_id"),
            display_name=_require_str(result, "display_name"),
            integration_version=_require_str(result, "integration_version"),
            revision=_require_int(result, "revision"),
            confirmed_at=_require_int(result, "confirmed_at"),
            server_public_key=_require_str(result, "server_public_key"),
        )
