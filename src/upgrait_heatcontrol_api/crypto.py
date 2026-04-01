"""PyNaCl helpers shared by the API client connection stack."""

from __future__ import annotations

import base64
import json
import uuid
from typing import Any

import nacl.utils
from nacl.public import Box, PrivateKey, PublicKey


def b64e(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def b64d(value: str) -> bytes:
    padded = (value or "").strip()
    padded += "=" * ((-len(padded)) % 4)
    return base64.b64decode(padded.encode("ascii"), validate=True)


def generate_keypair() -> tuple[str, str]:
    private_key = PrivateKey.generate()
    return b64e(bytes(private_key)), b64e(bytes(private_key.public_key))


def load_private_key(value: str) -> PrivateKey:
    return PrivateKey(b64d(value))


def load_public_key(value: str) -> PublicKey:
    return PublicKey(b64d(value))


def uuid4_hex() -> str:
    return uuid.uuid4().hex


def box_encrypt_json(
    sender_private_key: PrivateKey,
    recipient_public_key: PublicKey,
    payload: dict[str, Any],
) -> str:
    nonce = nacl.utils.random(Box.NONCE_SIZE)
    plaintext = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )
    ciphertext = Box(sender_private_key, recipient_public_key).encrypt(
        plaintext, nonce
    ).ciphertext
    return b64e(nonce + ciphertext)


def box_decrypt_json(
    sender_public_key: PublicKey,
    recipient_private_key: PrivateKey,
    payload_b64: str,
) -> dict[str, Any]:
    raw = b64d(payload_b64)
    if len(raw) <= Box.NONCE_SIZE:
        raise ValueError("payload too short")
    nonce = raw[: Box.NONCE_SIZE]
    ciphertext = raw[Box.NONCE_SIZE :]
    plaintext = Box(recipient_private_key, sender_public_key).decrypt(
        ciphertext, nonce
    )
    decoded = json.loads(plaintext.decode("utf-8"))
    if not isinstance(decoded, dict):
        raise ValueError("payload must decode to object")
    return decoded
