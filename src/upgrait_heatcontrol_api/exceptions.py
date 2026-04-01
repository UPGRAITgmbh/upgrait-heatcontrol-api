"""Exception hierarchy for the HeatControl API package."""


class HeatControlApiError(RuntimeError):
    """Base API error."""


class HeatControlApiConnectionError(HeatControlApiError):
    """Raised when the device cannot be reached."""


class HeatControlApiAuthError(HeatControlApiError):
    """Raised when pairing or websocket binding is rejected."""


class HeatControlApiInvalidPinError(HeatControlApiAuthError):
    """Raised when the pairing pin is invalid."""


class HeatControlApiProtocolError(HeatControlApiError):
    """Raised when the connector speaks an unexpected protocol."""
