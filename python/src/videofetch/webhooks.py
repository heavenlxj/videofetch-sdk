"""Webhook signature verification.

The server signs the raw request body with the endpoint secret (HMAC-SHA256)
and sends the digest in the `X-VideoFetch-Signature` header:

    X-VideoFetch-Signature: sha256=<hex digest of raw body>

Verify with the secret shown when you created the webhook endpoint:

    from videofetch.webhooks import construct_event
    event = construct_event(await request.body(), request.headers.get("X-VideoFetch-Signature"), secret)
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Optional

from .errors import VideoFetchError

# Event names (docs/Design contract)
WEBHOOK_EVENTS = (
    "download.queued", "download.processing", "download.completed", "download.failed",
)


class SignatureVerificationError(VideoFetchError):
    """The signature header is missing, malformed, or does not match."""


def compute_signature(payload: bytes, secret: str) -> str:
    """sha256=<hex> — mirrors the server implementation."""
    digest = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def construct_event(payload: bytes, sig_header: Optional[str], secret: str) -> dict:
    """Verify the signature header against the raw body and return the parsed event.

    Raises SignatureVerificationError if the header is missing or does not match.
    """
    if not sig_header:
        raise SignatureVerificationError("No signature header was present.")
    if not sig_header.startswith("sha256="):
        raise SignatureVerificationError("Signature header is malformed (expected sha256=<hex>).")

    expected = compute_signature(payload, secret)
    if not hmac.compare_digest(expected, sig_header):
        raise SignatureVerificationError("Signature does not match the payload and secret.")

    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise SignatureVerificationError("Payload is not valid JSON.") from None
