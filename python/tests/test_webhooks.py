"""Webhook signature verification tests (mirror server-side format)."""
import json

import pytest

from videofetch.errors import VideoFetchError
from videofetch.webhooks import (
    SignatureVerificationError,
    compute_signature,
    construct_event,
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
