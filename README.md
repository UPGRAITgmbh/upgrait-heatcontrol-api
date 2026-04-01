# upgrait-heatcontrol-api

Async Python API package for the UPGRAIT HeatControl 3rd-party connector.

The package is intended to be the external dependency consumed by the Home Assistant integration and by other 3rd-party clients.

Current feature set:

- HTTP probing via `/api/ping`
- device metadata parsing
- pairing start via `/api/pair/start`
- pairing confirmation via `/api/pair/confirm`
- websocket bind/session transport
- encrypted request/response handling over the websocket session
- initial snapshot handling and live event subscription
- Zeroconf service constants and discovery metadata parsing helpers

Installation:

```bash
pip install upgrait-heatcontrol-api
```

Example:

```python
import asyncio

from upgrait_heatcontrol_api import HeatControlApiClient, generate_keypair


async def main() -> None:
    async with HeatControlApiClient(host="192.168.2.116", port=8001) as client:
        device = await client.async_get_device_info()
        print(device.serial, device.version)

        private_key, public_key = generate_keypair()

        pairing = await client.async_start_pairing(
            ha_instance_id="example-ha-instance",
            display_name="Example Client",
            integration_version="0.1.0.dev0",
        )
        print(pairing.expires_at)

        # The 6-digit PIN must be entered by the user after it is shown on the UHC. (Only available in new local interface, version >1610)
        # confirm = await client.async_confirm_pairing(...)
        # connection = await client.async_connect_and_bind(...)


asyncio.run(main())
```

Notes:

- `HeatControlApiClient` can manage its own `aiohttp` session. In that case, either use `async with HeatControlApiClient(...)` or call `await client.close()`.
- `HeatControlConnection.subscribe()` registers callbacks for live websocket events and returns an unsubscribe function.
- Discovery helpers cover both the `/api/ping` `discovery` payload and Zeroconf TXT-record property normalization.
