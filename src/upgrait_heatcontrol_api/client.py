"""Async client for the UHC 3rd-party connector."""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp

from .connection import HeatControlConnection
from .discovery import DEFAULT_PORT
from .exceptions import (
    HeatControlApiAuthError,
    HeatControlApiConnectionError,
    HeatControlApiError,
    HeatControlApiInvalidPinError,
)
from .models import DeviceInfo, PairingConfirmResult, PairingStartResult


class HeatControlApiClient:
    """Async HTTP + websocket client for UPGRAIT HeatControl."""

    def __init__(
        self,
        *,
        host: str,
        port: int = DEFAULT_PORT,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self._session = session
        self._owns_session = session is None

    async def __aenter__(self) -> "HeatControlApiClient":
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        await self.close()

    @property
    def base_url(self) -> str:
        return f"http://{self._network_location}"

    @property
    def ws_url(self) -> str:
        return f"ws://{self._network_location}/ws"

    @property
    def _network_location(self) -> str:
        host = self.host.strip()
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        return f"{host}:{self.port}"

    async def async_ping(self) -> dict[str, Any]:
        return await self._async_request("GET", "/api/ping")

    async def async_get_device_info(self) -> DeviceInfo:
        payload = await self.async_ping()
        return DeviceInfo.from_ping_payload(payload)

    async def async_start_pairing(
        self,
        *,
        ha_instance_id: str,
        display_name: str,
        integration_version: str,
    ) -> PairingStartResult:
        payload = await self._async_request(
            "POST",
            "/api/pair/start",
            json={
                "ha_instance_id": ha_instance_id,
                "display_name": display_name,
                "integration_version": integration_version,
            },
        )
        return PairingStartResult.from_payload(payload)

    async def async_confirm_pairing(
        self,
        *,
        pin: str,
        ha_instance_id: str,
        display_name: str,
        integration_version: str,
        ha_public_key: str,
    ) -> PairingConfirmResult:
        payload = await self._async_request(
            "POST",
            "/api/pair/confirm",
            json={
                "pin": pin,
                "ha_instance_id": ha_instance_id,
                "display_name": display_name,
                "integration_version": integration_version,
                "ha_public_key": ha_public_key,
            },
        )
        return PairingConfirmResult.from_payload(payload)

    async def async_connect_and_bind(
        self,
        *,
        ha_instance_id: str,
        ha_private_key: str,
        server_public_key: str,
    ) -> HeatControlConnection:
        session = await self._get_session()
        try:
            ws = await session.ws_connect(self.ws_url, heartbeat=30)
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            raise HeatControlApiConnectionError(
                f"failed to open websocket at {self.ws_url}: {exc}"
            ) from exc

        connection = HeatControlConnection(
            session=session,
            ws=ws,
            ha_instance_id=ha_instance_id,
            ha_private_key=ha_private_key,
            server_public_key=server_public_key,
        )
        try:
            await connection.start()
        except Exception:
            await connection.close()
            raise
        return connection

    async def close(self) -> None:
        if not self._owns_session or self._session is None:
            return
        if not self._session.closed:
            await self._session.close()
        self._session = None

    async def _async_request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        session = await self._get_session()
        try:
            async with session.request(method, f"{self.base_url}{path}", json=json) as resp:
                payload = await resp.json()
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            raise HeatControlApiConnectionError(
                f"failed to reach HeatControl at {self.base_url}: {exc}"
            ) from exc
        except Exception as exc:
            raise HeatControlApiError(f"{method} {path} returned invalid JSON: {exc}") from exc

        if not isinstance(payload, dict):
            raise HeatControlApiError(f"{method} {path} returned invalid JSON")

        if resp.status >= 400 or payload.get("ok") is False:
            error = payload.get("error")
            code = str(error.get("code") if isinstance(error, dict) else f"http_{resp.status}")
            message = str(
                error.get("message") if isinstance(error, dict) else f"{method} {path} failed"
            )
            if code == "invalid_pin":
                raise HeatControlApiInvalidPinError(message)
            if code in {"pairing_not_active", "pairing_mismatch"}:
                raise HeatControlApiAuthError(message)
            raise HeatControlApiError(f"{code}: {message}")
        return payload

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is not None:
            if not self._session.closed:
                return self._session
            if not self._owns_session:
                raise HeatControlApiConnectionError("provided aiohttp session is closed")
            self._session = None
        self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10))
        self._owns_session = True
        return self._session
