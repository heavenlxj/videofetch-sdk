"""Webhook signature verification.

The server signs the RAW request body with the endpoint secret (HMAC-SHA256)
and sends the digest in the `X-VideoFetch-Signature` header:

    X-VideoFetch-Signature: sha256=<hex digest of raw body>
    (signature_format: "sha256=<hex hmac-sha256 of raw body>")

Verify with the secret shown when you created the webhook endpoint:

    from videofetch.webhooks import verify_webhook_signature
    verify_webhook_signature(await request.body(), request.headers.get("X-VideoFetch-Signature"), secret)

`construct_event()` is a convenience wrapper that verifies AND parses the JSON.

Important: always pass the raw body bytes (or the exact raw string) — never
re-serialize the payload with json.dumps(), because whitespace/key-order changes
would invalidate a valid signature.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Mapping, Optional, Union

from .errors import VideoFetchError

# Idempotency / retry headers sent on every delivery attempt.
DELIVERY_HEADER = "X-VideoFetch-Delivery"
ATTEMPT_HEADER = "X-VideoFetch-Attempt"
TIMESTAMP_HEADER = "X-VideoFetch-Timestamp"

# Full event set (server contract: schemas.WEBHOOK_EVENTS).
WEBHOOK_EVENTS = (
    "download.queued", "download.processing", "download.completed", "download.failed",
    "quota.warning", "quota.exceeded", "balance.low",
)


class SignatureVerificationError(VideoFetchError):
    """The signature header is missing, malformed, or does not match."""


def compute_signature(payload: bytes, secret: str) -> str:
    """sha256=<hex> — mirrors the server implementation."""
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def verify_webhook_signature(raw_body: Union[bytes, str], signature_header: Optional[str],
                             secret: str) -> bool:
    """Verify a webhook signature against the RAW body.

    `raw_body` may be bytes or str (encoded UTF-8). The comparison is
    constant-time. Returns True when valid; raises SignatureVerificationError
    when the header is missing/malformed or the digest does not match.
    """
    payload = raw_body.encode("utf-8") if isinstance(raw_body, str) else raw_body
    if not signature_header:
        raise SignatureVerificationError("No signature header was present.")
    if not signature_header.startswith("sha256="):
        raise SignatureVerificationError("Signature header is malformed (expected sha256=<hex>).")

    expected = compute_signature(payload, secret)
    if not hmac.compare_digest(expected, signature_header):
        raise SignatureVerificationError("Signature does not match the payload and secret.")
    return True


def construct_event(payload: Union[bytes, str], sig_header: Optional[str], secret: str) -> dict:
    """Verify the signature header against the raw body and return the parsed event.

    Raises SignatureVerificationError if the header is missing or does not match.
    """
    verify_webhook_signature(payload, sig_header, secret)
    raw = payload
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise SignatureVerificationError("Payload is not valid JSON.") from None


def _header(headers: Mapping[str, str], name: str) -> Optional[str]:
    """Case-insensitive header lookup (HTTP header names are case-insensitive)."""
    wanted = name.lower()
    for key, value in headers.items():
        if key.lower() == wanted:
            return value
    return None


def delivery_id(headers: Mapping[str, str]) -> Optional[str]:
    """Return the `X-VideoFetch-Delivery` idempotency key from request headers.

    Delivery is **at-least-once**: the same event may be delivered more than once
    (for example after a retry the receiver already processed, or a network error
    on our side). The `X-VideoFetch-Delivery` value is stable across every attempt
    of the same event, so use it to deduplicate — persist it (e.g. in a unique
    index) and skip events you have already handled.

    Returns None when the header is absent.
    """
    return _header(headers, DELIVERY_HEADER)


def attempt_number(headers: Mapping[str, str]) -> Optional[int]:
    """Return the `X-VideoFetch-Attempt` number (1 = first attempt).

    Attempts are retried up to 3 times and ordering is not guaranteed; use
    `delivery_id()` for deduplication and the event body's `seq` to order events.
    Returns None when the header is absent or not an integer.
    """
    raw = _header(headers, ATTEMPT_HEADER)
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None
