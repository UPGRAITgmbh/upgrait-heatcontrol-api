"""Tests for the UPGRAIT HeatControl API package."""

from __future__ import annotations

import asyncio

import aiohttp
import pytest
from aioresponses import aioresponses as aioresponses_ctx

from upgrait_heatcontrol_api import DiscoveryAdvertisement, ZeroconfDiscoveryInfo
from upgrait_heatcontrol_api.client import HeatControlApiClient
from upgrait_heatcontrol_api.connection import HeatControlConnection
from upgrait_heatcontrol_api.crypto import (
    box_decrypt_json,
    box_encrypt_json,
    generate_keypair,
    load_private_key,
    load_public_key,
)
from upgrait_heatcontrol_api.exceptions import (
    HeatControlApiAuthError,
    HeatControlApiConnectionError,
    HeatControlApiError,
    HeatControlApiInvalidPinError,
    HeatControlApiProtocolError,
)
from upgrait_heatcontrol_api.models import DeviceInfo, PairingConfirmResult, PairingStartResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_HOST = "192.0.2.1"
_BASE = f"http://{_HOST}:8001"

_PING_PAYLOAD: dict = {
    "ok": True,
    "device": {"serial": "UHC123456", "version": "2026.03"},
    "protocol": {"server_public_key": "Zm9vYmFyYmF6cXV4Zm9vYmFyYmF6cXV4Zm9vYmFyYg=="},
}

_PAIR_START_PAYLOAD: dict = {
    "ok": True,
    "result": {
        "pairing_active": True,
        "expires_at": 9999,
        "replaces_existing_binding": False,
        "server_public_key": "Zm9vYmFyYmF6cXV4Zm9vYmFyYmF6cXV4Zm9vYmFyYg==",
    },
}

_PAIR_CONFIRM_PAYLOAD: dict = {
    "ok": True,
    "result": {
        "ha_instance_id": "my-instance",
        "display_name": "Test Client",
        "integration_version": "0.1.0",
        "revision": 1,
        "confirmed_at": 1000,
        "server_public_key": "Zm9vYmFyYmF6cXV4Zm9vYmFyYmF6cXV4Zm9vYmFyYg==",
    },
}


class _FakeWebSocket:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True

    async def send_json(self, _payload: object) -> None:
        return None


def _make_connection() -> HeatControlConnection:
    private_key, _ = generate_keypair()
    _, server_public_key = generate_keypair()
    return HeatControlConnection(
        session=object(),  # type: ignore[arg-type]
        ws=_FakeWebSocket(),  # type: ignore[arg-type]
        ha_instance_id="ha-id",
        ha_private_key=private_key,
        server_public_key=server_public_key,
    )


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------


def test_base_url_uses_default_port() -> None:
    client = HeatControlApiClient(host=_HOST)
    assert client.base_url == f"http://{_HOST}:8001"


def test_base_url_wraps_ipv6_host() -> None:
    client = HeatControlApiClient(host="2001:db8::1")
    assert client.base_url == "http://[2001:db8::1]:8001"
    assert client.ws_url == "ws://[2001:db8::1]:8001/ws"


# ---------------------------------------------------------------------------
# Model parsing
# ---------------------------------------------------------------------------


def test_device_info_from_ping_payload() -> None:
    device = DeviceInfo.from_ping_payload(_PING_PAYLOAD)
    assert device.serial == "UHC123456"
    assert device.version == "2026.03"
    assert device.server_public_key


def test_pairing_models_from_payloads() -> None:
    start = PairingStartResult.from_payload(_PAIR_START_PAYLOAD)
    confirm = PairingConfirmResult.from_payload(_PAIR_CONFIRM_PAYLOAD)
    assert start.pairing_active is True
    assert confirm.revision == 1


def test_pairing_start_model_rejects_invalid_boolean_strings() -> None:
    with pytest.raises(ValueError, match="pairing_active must be a boolean"):
        PairingStartResult.from_payload(
            {
                "ok": True,
                "result": {
                    "pairing_active": "yes",
                    "expires_at": 123,
                    "replaces_existing_binding": False,
                },
            }
        )


def test_pairing_confirm_model_requires_non_empty_strings() -> None:
    with pytest.raises(ValueError, match="server_public_key must not be empty"):
        PairingConfirmResult.from_payload(
            {
                "ok": True,
                "result": {
                    "ha_instance_id": "ha-id",
                    "display_name": "Home Assistant",
                    "integration_version": "0.1.0",
                    "revision": 2,
                    "confirmed_at": 456,
                    "server_public_key": " ",
                },
            }
        )


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def test_discovery_helpers_parse_payloads() -> None:
    advertisement = DiscoveryAdvertisement.from_payload(
        {
            "service_type": "_upgrait-hc._tcp.local.",
            "advertised": True,
            "ip": _HOST,
            "service_name": f"UPGRAIT HeatControl UHC123._upgrait-hc._tcp.local.",
            "last_error": None,
        }
    )
    zeroconf_info = ZeroconfDiscoveryInfo.from_properties(
        {
            b"name": b"UPGRAIT HeatControl",
            b"serial": b"UHC123456",
            b"vendor": b"UPGRAIT GmbH",
            b"model": b"HeatControl",
            b"version": b"2026.03",
        }
    )
    assert advertisement.advertised is True
    assert zeroconf_info.serial == "UHC123456"


# ---------------------------------------------------------------------------
# Crypto
# ---------------------------------------------------------------------------


def test_crypto_roundtrip() -> None:
    sender_private_b64, sender_public_b64 = generate_keypair()
    recipient_private_b64, recipient_public_b64 = generate_keypair()
    payload = {"type": "req", "method": "ping"}
    encrypted = box_encrypt_json(
        load_private_key(sender_private_b64),
        load_public_key(recipient_public_b64),
        payload,
    )
    decrypted = box_decrypt_json(
        load_public_key(sender_public_b64),
        load_private_key(recipient_private_b64),
        encrypted,
    )
    assert decrypted == payload


# ---------------------------------------------------------------------------
# HTTP client: session lifecycle
# ---------------------------------------------------------------------------


async def test_client_closes_only_owned_session() -> None:
    external_session = object()
    client = HeatControlApiClient(host=_HOST, session=external_session)  # type: ignore[arg-type]
    await client.close()
    assert client._session is external_session


async def test_client_close_releases_owned_session() -> None:
    client = HeatControlApiClient(host=_HOST)
    session = await client._get_session()
    await client.close()
    assert session.closed is True
    assert client._session is None


# ---------------------------------------------------------------------------
# HTTP client: successful requests
# ---------------------------------------------------------------------------


async def test_async_ping_returns_payload() -> None:
    with aioresponses_ctx() as mocked:
        mocked.get(f"{_BASE}/api/ping", payload=_PING_PAYLOAD)
        async with HeatControlApiClient(host=_HOST) as client:
            result = await client.async_ping()
    assert result["ok"] is True


async def test_async_get_device_info_parses_response() -> None:
    with aioresponses_ctx() as mocked:
        mocked.get(f"{_BASE}/api/ping", payload=_PING_PAYLOAD)
        async with HeatControlApiClient(host=_HOST) as client:
            device = await client.async_get_device_info()
    assert device.serial == "UHC123456"
    assert device.version == "2026.03"


async def test_async_start_pairing_returns_result() -> None:
    with aioresponses_ctx() as mocked:
        mocked.post(f"{_BASE}/api/pair/start", payload=_PAIR_START_PAYLOAD)
        async with HeatControlApiClient(host=_HOST) as client:
            result = await client.async_start_pairing(
                ha_instance_id="my-instance",
                display_name="Test Client",
                integration_version="0.1.0",
            )
    assert result.pairing_active is True
    assert result.expires_at == 9999


async def test_async_confirm_pairing_returns_result() -> None:
    _, public_key = generate_keypair()
    with aioresponses_ctx() as mocked:
        mocked.post(f"{_BASE}/api/pair/confirm", payload=_PAIR_CONFIRM_PAYLOAD)
        async with HeatControlApiClient(host=_HOST) as client:
            result = await client.async_confirm_pairing(
                pin="123456",
                ha_instance_id="my-instance",
                display_name="Test Client",
                integration_version="0.1.0",
                ha_public_key=public_key,
            )
    assert result.ha_instance_id == "my-instance"
    assert result.revision == 1


# ---------------------------------------------------------------------------
# HTTP client: error mapping
# ---------------------------------------------------------------------------


async def test_async_request_raises_connection_error_on_network_failure() -> None:
    with aioresponses_ctx() as mocked:
        mocked.get(f"{_BASE}/api/ping", exception=aiohttp.ClientConnectionError("refused"))
        async with HeatControlApiClient(host=_HOST) as client:
            with pytest.raises(HeatControlApiConnectionError, match="failed to reach"):
                await client.async_ping()


async def test_async_request_maps_invalid_pin_to_error() -> None:
    _, public_key = generate_keypair()
    with aioresponses_ctx() as mocked:
        mocked.post(
            f"{_BASE}/api/pair/confirm",
            payload={"ok": False, "error": {"code": "invalid_pin", "message": "wrong PIN"}},
        )
        async with HeatControlApiClient(host=_HOST) as client:
            with pytest.raises(HeatControlApiInvalidPinError, match="wrong PIN"):
                await client.async_confirm_pairing(
                    pin="000000",
                    ha_instance_id="my-instance",
                    display_name="Test Client",
                    integration_version="0.1.0",
                    ha_public_key=public_key,
                )


async def test_async_request_maps_pairing_not_active_to_auth_error() -> None:
    _, public_key = generate_keypair()
    with aioresponses_ctx() as mocked:
        mocked.post(
            f"{_BASE}/api/pair/confirm",
            payload={
                "ok": False,
                "error": {"code": "pairing_not_active", "message": "no active pairing"},
            },
        )
        async with HeatControlApiClient(host=_HOST) as client:
            with pytest.raises(HeatControlApiAuthError):
                await client.async_confirm_pairing(
                    pin="123456",
                    ha_instance_id="my-instance",
                    display_name="Test Client",
                    integration_version="0.1.0",
                    ha_public_key=public_key,
                )


async def test_async_request_raises_api_error_on_http_error_status() -> None:
    with aioresponses_ctx() as mocked:
        mocked.get(f"{_BASE}/api/ping", status=404, payload={"ok": False, "error": None})
        async with HeatControlApiClient(host=_HOST) as client:
            with pytest.raises(HeatControlApiError):
                await client.async_ping()


# ---------------------------------------------------------------------------
# Connection: available property
# ---------------------------------------------------------------------------


async def test_connection_available_false_before_start() -> None:
    conn = _make_connection()
    assert conn.available is False  # _reader_task is None


async def test_connection_available_false_with_reader_exception() -> None:
    conn = _make_connection()
    conn._reader_exception = HeatControlApiConnectionError("reader failed")
    assert conn.available is False


async def test_connection_available_false_when_closed() -> None:
    conn = _make_connection()
    conn._closed = True
    assert conn.available is False


async def test_connection_available_false_when_ws_closed() -> None:
    conn = _make_connection()
    conn._ws.closed = True  # type: ignore[union-attr]
    assert conn.available is False


async def test_connection_available_false_when_reader_done() -> None:
    conn = _make_connection()
    conn._reader_task = asyncio.create_task(asyncio.sleep(0))
    await conn._reader_task
    assert conn.available is False


# ---------------------------------------------------------------------------
# Connection: request guards
# ---------------------------------------------------------------------------


async def test_connection_request_raises_reader_failure_immediately() -> None:
    connection = _make_connection()
    connection._reader_exception = HeatControlApiConnectionError("reader failed")
    with pytest.raises(HeatControlApiConnectionError, match="reader failed"):
        await connection.request("cfg_get")


async def test_connection_request_requires_started_connection() -> None:
    connection = _make_connection()
    with pytest.raises(HeatControlApiProtocolError, match="has not been started"):
        await connection.request("cfg_get")


async def test_connection_request_raises_if_reader_task_stopped() -> None:
    connection = _make_connection()
    connection._reader_task = asyncio.create_task(asyncio.sleep(0))
    await connection._reader_task
    with pytest.raises(HeatControlApiConnectionError, match="reader is not running"):
        await connection.request("cfg_get")
