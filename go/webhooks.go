package videofetch

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"strings"
)

// ErrBadSignature is returned when a webhook signature does not verify.
var ErrBadSignature = errors.New("videofetch: signature does not match the payload and secret")

// VerifyWebhookSignature checks the X-VideoFetch-Signature header
// (format: "sha256=<hex digest of raw body>") against the raw request body,
// then parses and returns the event.
func VerifyWebhookSignature(rawBody []byte, sigHeader, secret string) (*WebhookPayload, error) {
	if sigHeader == "" {
		return nil, errors.New("videofetch: no signature header was present")
	}
	if !strings.HasPrefix(sigHeader, "sha256=") {
		return nil, errors.New("videofetch: signature header is malformed (expected sha256=<hex>)")
	}

	mac := hmac.New(sha256.New, []byte(secret))
	mac.Write(rawBody)
	expected := "sha256=" + hex.EncodeToString(mac.Sum(nil))
	if !hmac.Equal([]byte(expected), []byte(sigHeader)) {
		return nil, ErrBadSignature
	}

	var ev WebhookPayload
	if err := json.Unmarshal(rawBody, &ev); err != nil {
		return nil, errors.New("videofetch: payload is not valid JSON")
	}
	return &ev, nil
}
