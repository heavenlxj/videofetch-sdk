package videofetch

import (
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"net/url"
	"strings"
)

// ErrBadSignature is returned when a webhook signature does not verify.
var ErrBadSignature = errors.New("videofetch: signature does not match the payload and secret")

// Additional account-level webhook event names (see WEBHOOK_EVENTS on the server).
const (
	EventQuotaWarning  = "quota.warning"
	EventQuotaExceeded = "quota.exceeded"
	EventBalanceLow    = "balance.low"
)

// WebhookEvents lists every event an account-level endpoint can subscribe to.
var WebhookEvents = []string{
	EventQueued, EventProcessing, EventCompleted, EventFailed,
	EventQuotaWarning, EventQuotaExceeded, EventBalanceLow,
}

// WebhookEndpoint is a registered account-level webhook endpoint.
// Secret is the full plaintext value only right after Create; List returns it masked.
type WebhookEndpoint struct {
	ID             string   `json:"id"`
	URL            string   `json:"url"`
	Secret         string   `json:"secret"`
	Events         []string `json:"events"`
	Active         bool     `json:"active"`
	LastDeliveryAt *string  `json:"last_delivery_at"`
	LastStatus     *int     `json:"last_status"`
	FailureCount   int      `json:"failure_count"`
	CreatedAt      *string  `json:"created_at"`
}

// WebhookList is the GET /v1/webhooks response (secrets are masked).
type WebhookList struct {
	Items []WebhookEndpoint `json:"items"`
}

// WebhookTestResult is the POST /v1/webhooks/{id}/test response.
type WebhookTestResult struct {
	Delivered       bool   `json:"delivered"`
	URL             string `json:"url"`
	LastStatus      *int   `json:"last_status"`
	SignatureHeader string `json:"signature_header"`
	SignatureFormat string `json:"signature_format"`
}

// WebhooksService manages account-level webhook endpoints. Authentication is by
// API key (no JWT needed), so a backend integration can self-provision callbacks.
// Access via client.Webhooks.
type WebhooksService struct{ client *Client }

// Create registers a new endpoint. With no events it subscribes to every event.
// The returned Secret is the FULL plaintext value — this is the only time the
// server ever returns it, so store it securely.
func (s *WebhooksService) Create(ctx context.Context, hookURL string, events ...string) (*WebhookEndpoint, error) {
	body := map[string]any{"url": hookURL}
	if len(events) > 0 {
		body["events"] = events
	}
	var w WebhookEndpoint
	if err := s.client.request(ctx, "POST", "/v1/webhooks", body, &w); err != nil {
		return nil, err
	}
	return &w, nil
}

// List returns the account's endpoints (each Secret is masked).
func (s *WebhooksService) List(ctx context.Context) (*WebhookList, error) {
	var out WebhookList
	if err := s.client.request(ctx, "GET", "/v1/webhooks", nil, &out); err != nil {
		return nil, err
	}
	return &out, nil
}

// Test sends a webhook.test ping to an endpoint and reports the delivery result.
func (s *WebhooksService) Test(ctx context.Context, id string) (*WebhookTestResult, error) {
	var out WebhookTestResult
	if err := s.client.request(ctx, "POST", "/v1/webhooks/"+url.PathEscape(id)+"/test", nil, &out); err != nil {
		return nil, err
	}
	return &out, nil
}

// Delete removes an endpoint (HTTP 204).
func (s *WebhooksService) Delete(ctx context.Context, id string) error {
	return s.client.request(ctx, "DELETE", "/v1/webhooks/"+url.PathEscape(id), nil, nil)
}

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
