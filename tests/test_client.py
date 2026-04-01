import asyncio

import pytest

from upgrait_heatcontrol_api import DiscoveryAdvertisement, ZeroconfDiscoveryInfo
from upgrait_heatcontrol_api.crypto import (
    box_decrypt_json,
    box_encrypt_json,
    generate_keypair,
    load_private_key,
    load_public_key,
)
from upgrait_heatcontrol_api.client import HeatControlApiClient
from upgrait_heatcontrol_api.connection import HeatControlConnection
from upgrait_heatcontrol_api.exceptions import (
    HeatControlApiConnectionError,
    HeatControlApiProtocolError,
)
from upgrait_heatcontrol_api.models import DeviceInfo, PairingConfirmResult, PairingStartResult


def test_base_url_uses_default_port() -> None:
    client = HeatControlApiClient(host="192.0.2.10")
    assert client.base_url == "http://192.0.2.10:8001"


def test_base_url_wraps_ipv6_host() -> None:
    client = HeatControlApiClient(host="2001:db8::1")
    assert client.base_url == "http://[2001:db8::1]:8001"
    assert client.ws_url == "ws://[2001:db8::1]:8001/ws"


def test_device_info_from_ping_payload() -> None:
    device = DeviceInfo.from_ping_payload(
        {
            "ok": True,
            "protocol": {"server_public_key": "Zm9vYmFyYmF6cXV4Zm9vYmFyYmF6cXV4Zm9vYmFyYg=="},
            "device": {
                "serial": "UHC123456",
                "version": "2026.03",
                "manufacturer": "UPGRAIT GmbH",
                "model": "HeatControl",
            },
        }
    )
    assert device.serial == "UHC123456"
    assert device.version == "2026.03"
    assert device.server_public_key


def test_pairing_models_from_payloads() -> None:
    start = PairingStartResult.from_payload(
        {
            "ok": True,
            "result": {
                "pairing_active": True,
                "expires_at": 123,
                "replaces_existing_binding": False,
                "server_public_key": "server_key",
            },
        }
    )
    confirm = PairingConfirmResult.from_payload(
        {
            "ok": True,
            "result": {
                "ha_instance_id": "ha-id",
                "display_name": "Home Assistant",
                "integration_version": "0.1.0-dev",
                "revision": 2,
                "confirmed_at": 456,
                "server_public_key": "server_key",
            },
        }
    )
    assert start.pairing_active is True
    assert confirm.revision == 2


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
                    "integration_version": "0.1.0-dev",
                    "revision": 2,
                    "confirmed_at": 456,
                    "server_public_key": " ",
                },
            }
        )


def test_discovery_helpers_parse_payloads() -> None:
    advertisement = DiscoveryAdvertisement.from_payload(
        {
            "service_type": "_upgrait-hc._tcp.local.",
            "advertised": True,
            "ip": "192.0.2.10",
            "service_name": "UPGRAIT HeatControl UHC123._upgrait-hc._tcp.local.",
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


@pytest.mark.asyncio
async def test_client_closes_only_owned_session() -> None:
    external_session = object()
    client = HeatControlApiClient(host="192.0.2.10", session=external_session)  # type: ignore[arg-type]
    await client.close()
    assert client._session is external_session


@pytest.mark.asyncio
async def test_client_close_releases_owned_session() -> None:
    client = HeatControlApiClient(host="192.0.2.10")
    session = await client._get_session()
    await client.close()
    assert session.closed is True
    assert client._session is None


class _FakeWebSocket:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True

    async def send_json(self, _payload: object) -> None:
        return None


@pytest.mark.asyncio
async def test_connection_request_raises_reader_failure_immediately() -> None:
    connection = HeatControlConnection(
        session=object(),  # type: ignore[arg-type]
        ws=_FakeWebSocket(),  # type: ignore[arg-type]
        ha_instance_id="ha-id",
        ha_private_key=generate_keypair()[0],
        server_public_key=generate_keypair()[1],
    )
    connection._reader_exception = HeatControlApiConnectionError("reader failed")
    with pytest.raises(HeatControlApiConnectionError, match="reader failed"):
        await connection.request("cfg_get")


@pytest.mark.asyncio
async def test_connection_request_requires_started_connection() -> None:
    private_key, _public_key = generate_keypair()
    _server_private_key, server_public_key = generate_keypair()
    connection = HeatControlConnection(
        session=object(),  # type: ignore[arg-type]
        ws=_FakeWebSocket(),  # type: ignore[arg-type]
        ha_instance_id="ha-id",
        ha_private_key=private_key,
        server_public_key=server_public_key,
    )
    with pytest.raises(HeatControlApiProtocolError, match="has not been started"):
        await connection.request("cfg_get")


@pytest.mark.asyncio
async def test_connection_request_raises_if_reader_task_stopped() -> None:
    private_key, _public_key = generate_keypair()
    _server_private_key, server_public_key = generate_keypair()
    connection = HeatControlConnection(
        session=object(),  # type: ignore[arg-type]
        ws=_FakeWebSocket(),  # type: ignore[arg-type]
        ha_instance_id="ha-id",
        ha_private_key=private_key,
        server_public_key=server_public_key,
    )
    connection._reader_task = asyncio.create_task(asyncio.sleep(0))
    await connection._reader_task
    with pytest.raises(HeatControlApiConnectionError, match="reader is not running"):
        await connection.request("cfg_get")
