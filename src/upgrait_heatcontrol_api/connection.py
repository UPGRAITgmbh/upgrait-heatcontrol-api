"""WebSocket connection handling for the UHC 3rd-party connector."""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import json
import time
from collections.abc import Awaitable, Callable
from typing import Any

import aiohttp
from nacl.public import PrivateKey, PublicKey

from .crypto import (
    box_decrypt_json,
    box_encrypt_json,
    load_private_key,
    load_public_key,
    uuid4_hex,
)
from .exceptions import (
    HeatControlApiAuthError,
    HeatControlApiConnectionError,
    HeatControlApiProtocolError,
)


EventCallback = Callable[[dict[str, Any]], Awaitable[None] | None]


class HeatControlConnection:
    """Bound websocket connection to a HeatControl device."""

    def __init__(
        self,
        *,
        session: aiohttp.ClientSession,
        ws: aiohttp.ClientWebSocketResponse,
        ha_instance_id: str,
        ha_private_key: str,
        server_public_key: str,
    ) -> None:
        self._session = session
        self._ws = ws
        self._ha_instance_id = ha_instance_id
        self._ha_private_key = ha_private_key
        self._server_public_key = server_public_key
        self._ha_private_key_obj: PrivateKey = load_private_key(ha_private_key)
        self._server_public_key_obj: PublicKey = load_public_key(server_public_key)
        self._event_callbacks: list[EventCallback] = []
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._reader_task: asyncio.Task[Any] | None = None
        self._initial_snapshot: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._closed = False
        self._reader_exception: Exception | None = None
        self.snapshot: dict[str, Any] = {}

    async def start(self) -> None:
        bind_payload = box_encrypt_json(
            self._ha_private_key_obj,
            self._server_public_key_obj,
            {
                "ha_instance_id": self._ha_instance_id,
                "ts_ms": int(time.time() * 1000),
                "nonce": uuid4_hex(),
            },
        )
        try:
            await self._ws.send_json({"type": "bind", "payload": bind_payload})
            ack = await asyncio.wait_for(self._ws.receive(), timeout=15)
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            raise HeatControlApiConnectionError(f"websocket bind failed: {exc}") from exc
        if ack.type in {
            aiohttp.WSMsgType.CLOSE,
            aiohttp.WSMsgType.CLOSED,
            aiohttp.WSMsgType.CLOSING,
        }:
            raise HeatControlApiConnectionError("websocket closed during bind")
        if ack.type != aiohttp.WSMsgType.TEXT:
            raise HeatControlApiAuthError("websocket bind failed")
        try:
            payload = json.loads(ack.data)
        except json.JSONDecodeError as exc:
            raise HeatControlApiProtocolError("bind acknowledgement was not valid JSON") from exc
        if not isinstance(payload, dict):
            raise HeatControlApiProtocolError("bind acknowledgement was not a JSON object")
        if payload.get("type") == "error":
            raise HeatControlApiAuthError(str(payload.get("error") or "websocket bind failed"))
        if payload.get("type") != "bind_ack":
            raise HeatControlApiAuthError(f"unexpected bind response: {payload}")
        self._reader_task = asyncio.create_task(self._reader())
        self.snapshot = await asyncio.wait_for(self._initial_snapshot, timeout=10)

    def subscribe(self, callback: EventCallback) -> Callable[[], None]:
        self._event_callbacks.append(callback)

        def _unsubscribe() -> None:
            with contextlib.suppress(ValueError):
                self._event_callbacks.remove(callback)

        return _unsubscribe

    async def request(self, method: str, params: dict[str, Any] | None = None) -> Any:
        self._raise_if_unavailable()
        request_id = uuid4_hex()
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        try:
            await self._send_encrypted(
                {
                    "type": "req",
                    "request_id": request_id,
                    "method": method,
                    "params": params or {},
                }
            )
            response = await asyncio.wait_for(future, timeout=10)
        finally:
            self._pending.pop(request_id, None)

        if response.get("ok") is not True:
            error = response.get("error")
            raise HeatControlApiProtocolError(str(error))
        return response.get("result")

    async def close(self) -> None:
        self._closed = True
        close_exc = HeatControlApiConnectionError("connection closed")
        if not self._initial_snapshot.done():
            self._initial_snapshot.set_exception(close_exc)
        for future in list(self._pending.values()):
            if not future.done():
                future.set_exception(close_exc)
        if self._reader_task is not None:
            self._reader_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._reader_task
        await self._ws.close()

    async def _reader(self) -> None:
        try:
            async for msg in self._ws:
                if msg.type != aiohttp.WSMsgType.TEXT:
                    continue
                outer = json.loads(msg.data)
                msg_type = outer.get("type")
                if msg_type == "close":
                    raise HeatControlApiAuthError(str(outer.get("reason") or "connection closed"))
                if msg_type != "msg":
                    continue
                payload_b64 = outer.get("payload")
                if not isinstance(payload_b64, str):
                    continue
                inner = box_decrypt_json(
                    self._server_public_key_obj,
                    self._ha_private_key_obj,
                    payload_b64,
                )
                inner_type = inner.get("type")
                if inner_type == "res":
                    request_id = str(inner.get("request_id") or "")
                    future = self._pending.get(request_id)
                    if future is not None and not future.done():
                        future.set_result(inner)
                elif inner_type == "evt":
                    if isinstance(inner.get("topics"), dict):
                        self.snapshot = dict(inner["topics"])
                        if not self._initial_snapshot.done():
                            self._initial_snapshot.set_result(dict(self.snapshot))
                    elif isinstance(inner.get("topic"), str):
                        self.snapshot[inner["topic"]] = inner.get("value")
                    for callback in list(self._event_callbacks):
                        result = callback(inner)
                        if inspect.isawaitable(result):
                            await result
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._set_reader_exception(self._normalize_reader_exception(exc))
        else:
            if not self._closed:
                self._set_reader_exception(
                    HeatControlApiConnectionError("websocket connection closed")
                )

    async def _send_encrypted(self, payload: dict[str, Any]) -> None:
        self._raise_if_unavailable()
        encrypted = box_encrypt_json(
            self._ha_private_key_obj,
            self._server_public_key_obj,
            payload,
        )
        await self._ws.send_json({"type": "msg", "payload": encrypted})

    def _normalize_reader_exception(self, exc: Exception) -> Exception:
        if isinstance(
            exc,
            (
                HeatControlApiAuthError,
                HeatControlApiConnectionError,
                HeatControlApiProtocolError,
            ),
        ):
            return exc
        return HeatControlApiConnectionError(f"websocket reader failed: {exc}")

    def _raise_if_unavailable(self) -> None:
        if self._reader_exception is not None:
            raise self._reader_exception
        if self._closed or self._ws.closed:
            raise HeatControlApiConnectionError("websocket connection is closed")
        if self._reader_task is None:
            raise HeatControlApiProtocolError("connection has not been started")
        if self._reader_task.done():
            raise HeatControlApiConnectionError("websocket reader is not running")

    def _set_reader_exception(self, exc: Exception) -> None:
        if self._reader_exception is None:
            self._reader_exception = exc
        if not self._initial_snapshot.done():
            self._initial_snapshot.set_exception(self._reader_exception)
        for future in list(self._pending.values()):
            if not future.done():
                future.set_exception(self._reader_exception)
