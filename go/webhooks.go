package videofetch

import (
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"net/http"
	"net/url"
	"strconv"
	"strings"
)

// ErrBadSignature is returned when a webhook signature does not verify.
var ErrBadSignature = errors.New("videofetch: signature does not match the payload and secret")

// Additional account-level webhook event names (see WEBHOOK_EVENTS on the server).
const (
	EventQuotaWarning  = "quota.warning"
	EventQuotaExceeded = "quota.exceeded"
	EventBalanceLow    = "balance.low"
	// EventStorageConnectionFailed fires once when a saved connection starts failing
	// with a non-retryable error (auth, permission, missing bucket, …).
	EventStorageConnectionFailed = "storage.connection_failed"
)

// WebhookEvents lists every event an account-level endpoint can subscribe to.
var WebhookEvents = []string{
	EventQueued, EventProcessing, EventCompleted, EventFailed,
	EventQuotaWarning, EventQuotaExceeded, EventBalanceLow, EventStorageConnectionFailed,
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

// WebhookDeliveryHealth aggregates delivery outcomes for an endpoint.
type WebhookDeliveryHealth struct {
	Total       int     `json:"total"`
	Succeeded   int     `json:"succeeded"`
	Dead        int     `json:"dead"`
	Pending     int     `json:"pending"`
	SuccessRate float64 `json:"success_rate"`
}

// WebhookDelivery is one recorded delivery attempt of an event to an endpoint.
// Deliveries are at-least-once and are not ordered: order by Seq, not CreatedAt.
type WebhookDelivery struct {
	EventID        string  `json:"event_id"`
	Event          string  `json:"event"`
	Seq            int64   `json:"seq"`
	Status         string  `json:"status"` // pending|succeeded|dead
	Attempts       int     `json:"attempts"`
	MaxAttempts    int     `json:"max_attempts"`
	LastStatusCode *int    `json:"last_status_code"`
	LastError      *string `json:"last_error"`
	NextAttemptAt  *string `json:"next_attempt_at"`
	CreatedAt      *string `json:"created_at"`
	DeliveredAt    *string `json:"delivered_at"`
	DownloadID     *string `json:"download_id"`
}

// WebhookDeliveriesResult is the GET /v1/webhooks/{id}/deliveries response.
type WebhookDeliveriesResult struct {
	EndpointID           string                `json:"endpoint_id"`
	Active               bool                  `json:"active"`
	AutoDisabledAt       *string               `json:"auto_disabled_at"`
	ConsecutiveFailures  int                   `json:"consecutive_failures"`
	MaxAttempts          int                   `json:"max_attempts"`
	RetryScheduleSeconds string                `json:"retry_schedule_seconds"`
	Health               WebhookDeliveryHealth `json:"health"`
	Items                []WebhookDelivery     `json:"items"`
}

// ReplayResult is the POST /v1/webhooks/deliveries/{event_id}/replay response.
type ReplayResult struct {
	Queued  bool   `json:"queued"`
	EventID string `json:"event_id"`
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

// Deliveries returns the recent delivery history plus aggregate health for an
// endpoint. limit caps the number of items; when limit <= 0 the server default
// (50) is used and no limit parameter is sent.
func (s *WebhooksService) Deliveries(ctx context.Context, endpointID string, limit int) (*WebhookDeliveriesResult, error) {
	q := url.Values{}
	if limit > 0 {
		q.Set("limit", strconv.Itoa(limit))
	}
	var out WebhookDeliveriesResult
	if err := s.client.request(ctx, "GET", "/v1/webhooks/"+url.PathEscape(endpointID)+"/deliveries"+queryParams(q), nil, &out); err != nil {
		return nil, err
	}
	return &out, nil
}

// Replay re-queues a delivery by its event id (e.g. after fixing a receiver).
// The event is delivered again to every endpoint subscribed to it.
func (s *WebhooksService) Replay(ctx context.Context, eventID string) (*ReplayResult, error) {
	var out ReplayResult
	if err := s.client.request(ctx, "POST", "/v1/webhooks/deliveries/"+url.PathEscape(eventID)+"/replay", nil, &out); err != nil {
		return nil, err
	}
	return &out, nil
}

// Delete removes an endpoint (HTTP 204).
func (s *WebhooksService) Delete(ctx context.Context, id string) error {
	return s.client.request(ctx, "DELETE", "/v1/webhooks/"+url.PathEscape(id), nil, nil)
}

// DeliveryID returns the value of the X-VideoFetch-Delivery header, the stable
// idempotency key for a webhook delivery (it equals the event id). Deliveries
// are at-least-once, so the same delivery id can arrive more than once — record
// it and skip work you already did before processing the event. The lookup is
// case-insensitive; it returns "" when the header is absent.
func DeliveryID(headers http.Header) string {
	return headers.Get("X-VideoFetch-Delivery")
}

// AttemptNumber returns the 1-based delivery attempt from the
// X-VideoFetch-Attempt header (1..3, the first try is 1). It returns 0 when the
// header is absent or not a valid non-negative integer. Deliveries are
// at-least-once and not ordered, so use this only for diagnostics/logging, never
// as an ordering or exactly-once guarantee (order by the seq field instead).
func AttemptNumber(headers http.Header) int {
	n, err := strconv.Atoi(strings.TrimSpace(headers.Get("X-VideoFetch-Attempt")))
	if err != nil || n < 0 {
		return 0
	}
	return n
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
