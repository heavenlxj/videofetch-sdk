"""Webhook signature verification tests (mirror server-side format)."""
import json

import pytest

import videofetch
from videofetch.errors import VideoFetchError
from videofetch.webhooks import (
    SignatureVerificationError,
    attempt_number,
    compute_signature,
    construct_event,
    delivery_id,
)

SECRET = "whsec_test_secret"
EVENT = {"event": "download.completed", "id": "dl_abc", "status": "completed"}


def test_verify_valid_signature():
    payload = json.dumps(EVENT).encode()
    sig = compute_signature(payload, SECRET)
    assert sig.startswith("sha256=")
    out = construct_event(payload, sig, SECRET)
    assert out == EVENT


def test_reject_tampered_payload():
    payload = json.dumps(EVENT).encode()
    sig = compute_signature(payload, SECRET)
    tampered = json.dumps({**EVENT, "id": "dl_evil"}).encode()
    with pytest.raises(SignatureVerificationError):
        construct_event(tampered, sig, SECRET)


def test_reject_wrong_secret():
    payload = json.dumps(EVENT).encode()
    sig = compute_signature(payload, "wrong_secret")
    with pytest.raises(SignatureVerificationError):
        construct_event(payload, sig, SECRET)


def test_reject_missing_malformed_header():
    payload = json.dumps(EVENT).encode()
    with pytest.raises(SignatureVerificationError):
        construct_event(payload, None, SECRET)
    with pytest.raises(SignatureVerificationError):
        construct_event(payload, "not-a-signature", SECRET)


# ── idempotency helpers (v0.3.0) ────────────────────────────────────────────
def test_delivery_id_is_case_insensitive():
    assert delivery_id({"X-VideoFetch-Delivery": "evt_abc"}) == "evt_abc"
    assert delivery_id({"x-videofetch-delivery": "evt_abc"}) == "evt_abc"
    assert delivery_id({"X-VIDEOFETCH-DELIVERY": "evt_abc"}) == "evt_abc"
    # mixed with unrelated headers
    headers = {"Content-Type": "application/json", "X-VideoFetch-Delivery": "evt_1"}
    assert delivery_id(headers) == "evt_1"


def test_delivery_id_missing_returns_none():
    assert delivery_id({}) is None
    assert delivery_id({"X-VideoFetch-Attempt": "1"}) is None


def test_attempt_number_parses_and_defaults():
    assert attempt_number({"X-VideoFetch-Attempt": "1"}) == 1
    assert attempt_number({"x-videofetch-attempt": "3"}) == 3
    assert attempt_number({}) is None
    assert attempt_number({"X-VideoFetch-Attempt": "not-a-number"}) is None


def test_idempotency_helpers_exported():
    assert videofetch.delivery_id is delivery_id
    assert videofetch.attempt_number is attempt_number
    assert videofetch.DELIVERY_HEADER == "X-VideoFetch-Delivery"
    assert videofetch.ATTEMPT_HEADER == "X-VideoFetch-Attempt"
    assert videofetch.TIMESTAMP_HEADER == "X-VideoFetch-Timestamp"
