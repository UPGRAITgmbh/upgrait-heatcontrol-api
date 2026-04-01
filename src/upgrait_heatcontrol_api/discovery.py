"""Discovery constants and metadata helpers shared by the API package and integrations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from zeroconf import ServiceInfo

DEFAULT_PORT = 8001
SERVICE_TYPE = "_upgrait-hc._tcp.local."
MANUFACTURER = "UPGRAIT GmbH"
MODEL = "HeatControl"


def _decode_discovery_value(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        decoded = value.decode("utf-8", errors="strict").strip()
        return decoded or None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    raise ValueError(f"unsupported discovery value type: {type(value).__name__}")


@dataclass(slots=True, frozen=True)
class DiscoveryAdvertisement:
    """Metadata returned by the connector ping endpoint for discovery state."""

    service_type: str
    advertised: bool
    ip: str | None = None
    service_name: str | None = None
    last_error: str | None = None

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "DiscoveryAdvertisement":
        if not isinstance(payload, dict):
            raise ValueError("discovery payload must be an object")
        advertised = payload.get("advertised")
        if not isinstance(advertised, bool):
            raise ValueError("discovery advertised must be a boolean")
        service_type = payload.get("service_type")
        if not isinstance(service_type, str) or not service_type.strip():
            raise ValueError("discovery service_type must be a non-empty string")
        return cls(
            service_type=service_type.strip(),
            advertised=advertised,
            ip=_decode_discovery_value(payload.get("ip")),
            service_name=_decode_discovery_value(payload.get("service_name")),
            last_error=_decode_discovery_value(payload.get("last_error")),
        )


@dataclass(slots=True, frozen=True)
class ZeroconfDiscoveryInfo:
    """Normalized Zeroconf TXT-record properties for HeatControl discovery."""

    name: str | None = None
    serial: str | None = None
    vendor: str | None = None
    model: str | None = None
    version: str | None = None

    @classmethod
    def from_properties(
        cls, properties: dict[str | bytes, str | bytes]
    ) -> "ZeroconfDiscoveryInfo":
        normalized: dict[str, str | None] = {}
        for key, value in properties.items():
            normalized_key = _decode_discovery_value(key)
            if normalized_key is None:
                continue
            normalized[normalized_key.lower()] = _decode_discovery_value(value)
        return cls(
            name=normalized.get("name"),
            serial=normalized.get("serial"),
            vendor=normalized.get("vendor"),
            model=normalized.get("model"),
            version=normalized.get("version"),
        )

    @classmethod
    def from_service_info(cls, service_info: ServiceInfo) -> "ZeroconfDiscoveryInfo":
        return cls.from_properties(service_info.properties)
