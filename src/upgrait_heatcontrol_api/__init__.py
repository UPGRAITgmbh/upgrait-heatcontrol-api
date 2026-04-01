"""Public exports for the UPGRAIT HeatControl API package."""

from .client import HeatControlApiClient
from .connection import EventCallback, HeatControlConnection
from .crypto import generate_keypair
from .discovery import (
    DEFAULT_PORT,
    MANUFACTURER,
    MODEL,
    SERVICE_TYPE,
    DiscoveryAdvertisement,
    ZeroconfDiscoveryInfo,
)
from .exceptions import (
    HeatControlApiAuthError,
    HeatControlApiConnectionError,
    HeatControlApiError,
    HeatControlApiInvalidPinError,
    HeatControlApiProtocolError,
)
from .models import DeviceInfo, PairingConfirmResult, PairingStartResult

__all__ = [
    "DEFAULT_PORT",
    "DeviceInfo",
    "DiscoveryAdvertisement",
    "EventCallback",
    "HeatControlApiClient",
    "HeatControlApiAuthError",
    "HeatControlApiConnectionError",
    "HeatControlApiError",
    "HeatControlApiInvalidPinError",
    "HeatControlApiProtocolError",
    "HeatControlConnection",
    "MANUFACTURER",
    "MODEL",
    "PairingConfirmResult",
    "PairingStartResult",
    "SERVICE_TYPE",
    "ZeroconfDiscoveryInfo",
    "generate_keypair",
]
