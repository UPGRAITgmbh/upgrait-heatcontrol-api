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
    async with HeatControlApiClient(host="<device-ip>") as client:
        # Step 1: read device metadata
        device = await client.async_get_device_info()
        print(device.serial, device.version)

        # Step 2: generate a keypair once and persist it for subsequent connections
        private_key, public_key = generate_keypair()

        # Step 3: start pairing — the device will display a 6-digit PIN
        # (requires new local interface, firmware version > 1610)
        pairing = await client.async_start_pairing(
            ha_instance_id="example-ha-instance",
            display_name="Example Client",
            integration_version="0.1.0",
        )
        print(f"PIN expires at: {pairing.expires_at}")

        # Step 4: confirm with the PIN shown on the device
        pin = input("Enter PIN: ")
        confirm = await client.async_confirm_pairing(
            pin=pin,
            ha_instance_id="example-ha-instance",
            display_name="Example Client",
            integration_version="0.1.0",
            ha_public_key=public_key,
        )

        # Step 5: open the persistent websocket connection
        connection = await client.async_connect_and_bind(
            ha_instance_id="example-ha-instance",
            ha_private_key=private_key,
            server_public_key=confirm.server_public_key,
        )
        print("Connected. Snapshot:", connection.snapshot)


asyncio.run(main())
```

Notes:

- `HeatControlApiClient` can manage its own `aiohttp` session. In that case, either use `async with HeatControlApiClient(...)` or call `await client.close()`.
- `HeatControlConnection.subscribe()` registers callbacks for live websocket events and returns an unsubscribe function.
- Discovery helpers cover both the `/api/ping` `discovery` payload and Zeroconf TXT-record property normalization.
