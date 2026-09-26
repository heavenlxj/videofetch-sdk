// Package videofetch is the official Go SDK for the VideoFetch video ingestion
// API: give us a video URL, we deliver the MP4/MP3 to your storage.
//
// Quick start:
//
//	client := videofetch.NewClient("vf_live_sk_...", nil)
//	job, err := client.Downloads.Create(ctx, videofetch.DownloadCreateParams{
//	    URL: "https://www.youtube.com/watch?v=...", Format: "1080p",
//	})
//	if err != nil { log.Fatal(err) }
//	result, err := job.Wait(ctx) // polls until completed/failed
package videofetch

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"strconv"
	"strings"
	"time"
)

const (
	DefaultBaseURL   = "https://api.vidfetch.dev"
	DefaultTimeout   = 30 * time.Second
	DefaultMaxRetry  = 2
	DefaultJobTimout = 2 * time.Minute
)

// Client talks to the VideoFetch API. Create with NewClient.
type Client struct {
	apiKey     string
	baseURL    string
	httpClient *http.Client
	maxRetries int

	Downloads *DownloadsService
	Info      *InfoService
	Usage     *UsageService
	Webhooks  *WebhooksService
	Storage   *StorageService
}

// ClientOptions tune the client. Zero values fall back to defaults.
type ClientOptions struct {
	BaseURL    string
	HTTPClient *http.Client
	Timeout    time.Duration
	MaxRetries int
}

// NewClient creates a VideoFetch API client. apiKey is required (vf_live_sk_...).
func NewClient(apiKey string, opts *ClientOptions) *Client {
	if apiKey == "" {
		apiKey = os.Getenv("VIDEOFETCH_API_KEY")
	}
	if apiKey == "" {
		panic("videofetch: no API key provided (pass apiKey or set VIDEOFETCH_API_KEY)")
	}
	o := ClientOptions{}
	if opts != nil {
		o = *opts
	}
	base := o.BaseURL
	if base == "" {
		base = os.Getenv("VIDEOFETCH_BASE_URL")
	}
	if base == "" {
		base = DefaultBaseURL
	}
	timeout := o.Timeout
	if timeout == 0 {
		timeout = DefaultTimeout
	}
	hc := o.HTTPClient
	if hc == nil {
		hc = &http.Client{Timeout: timeout}
	}
	retries := o.MaxRetries
	if retries == 0 {
		retries = DefaultMaxRetry
	}
	c := &Client{apiKey: apiKey, baseURL: base, httpClient: hc, maxRetries: retries}
	c.Downloads = &DownloadsService{client: c}
	c.Info = &InfoService{client: c}
	c.Usage = &UsageService{client: c}
	c.Webhooks = &WebhooksService{client: c}
	c.Storage = &StorageService{client: c}
	return c
}

// APIError mirrors the server error contract {detail: {code, message, param}}.
type APIError struct {
	StatusCode int
	Code       string `json:"code"`
	Message    string `json:"message"`
	Param      string `json:"param"`
	Hint       string `json:"hint"`
	RawBody    string
}

func (e *APIError) Error() string {
	if e.Code != "" || e.Param != "" {
		return fmt.Sprintf("videofetch: %s (code=%s param=%s)", e.Message, e.Code, e.Param)
	}
	return fmt.Sprintf("videofetch: HTTP %d: %s", e.StatusCode, e.Message)
}

// PermissionDeniedError is returned for HTTP 403. Inspect Code to distinguish a
// plain permission error from an administrative suspension
// (code "account_suspended").
type PermissionDeniedError struct{ APIError }

// Unwrap exposes the embedded *APIError so errors.As(err, &apiErr) works too.
func (e *PermissionDeniedError) Unwrap() error { return &e.APIError }

// RateLimitError is returned for HTTP 429 — the account/platform concurrency
// guard. Code is one of "concurrency_limit_exceeded", "queue_limit_exceeded" or
// "platform_at_capacity"; Limit/Active/Scope describe the cap that was hit and
// RetryAfter is the server's Retry-After hint in seconds (0 if absent).
type RateLimitError struct {
	APIError
	Limit      int
	Active     int
	Scope      string
	RetryAfter int
}

func (e *RateLimitError) Error() string {
	return fmt.Sprintf("videofetch: rate limited: %s (code=%s limit=%d active=%d scope=%s retry_after=%ds)",
		e.Message, e.Code, e.Limit, e.Active, e.Scope, e.RetryAfter)
}

// Unwrap exposes the embedded *APIError so errors.As(err, &apiErr) works too.
func (e *RateLimitError) Unwrap() error { return &e.APIError }

// QuotaExceededError is returned when the monthly quota is exhausted (HTTP 402).
// RemainingGB mirrors the "remaining_gb" field the server includes (nil if absent).
type QuotaExceededError struct {
	APIError
	RemainingGB *float64
}

// Unwrap exposes the embedded *APIError so errors.As(err, &apiErr) works too.
func (e *QuotaExceededError) Unwrap() error { return &e.APIError }

// StorageError is returned for HTTP 422 when a storage destination is rejected at
// create time. Code is one of "storage_not_found", "storage_config_invalid",
// "storage_endpoint_blocked" or "storage_unreachable"; Param names the field
// (e.g. "destination.endpoint") and Hint says how to fix it.
type StorageError struct{ APIError }

// Unwrap exposes the embedded *APIError so errors.As(err, &apiErr) works too.
func (e *StorageError) Unwrap() error { return &e.APIError }

// ConflictError is returned for HTTP 409. Code is "storage_in_use" (delete with
// force) or "not_redeliverable".
type ConflictError struct{ APIError }

// Unwrap exposes the embedded *APIError so errors.As(err, &apiErr) works too.
func (e *ConflictError) Unwrap() error { return &e.APIError }

// ErrDeliveryFailed is wrapped by a *JobFailedError whose Stage is "delivery": the file
// was downloaded but could not be written to your storage.
var ErrDeliveryFailed = errors.New("videofetch: delivery to storage failed")

// JobFailedError is returned by Wait when the job reached a failed terminal
// state. Failed downloads are never charged.
//
// Stage is fetch | process | billing | delivery. For delivery failures ErrorCode is a
// storage_* code, errors.Is(err, ErrDeliveryFailed) is true, and when Redeliverable()
// the file is held so Downloads.Redeliver can retry without re-downloading.
type JobFailedError struct {
	JobID        string
	ErrorCode    string
	ErrorMessage string
	Stage        string
	Retryable    *bool
	Hint         string
	ProviderCode string
	Download     *Download
}

func (e *JobFailedError) Error() string {
	return fmt.Sprintf("videofetch: download job %s failed [%s]: %s",
		e.JobID, e.ErrorCode, e.ErrorMessage)
}

// Unwrap exposes ErrDeliveryFailed for delivery-stage failures.
func (e *JobFailedError) Unwrap() error {
	if e.Stage == "delivery" {
		return ErrDeliveryFailed
	}
	return nil
}

// Redeliverable reports whether the file is still held and Downloads.Redeliver can run.
func (e *JobFailedError) Redeliverable() bool {
	return e.Download != nil && e.Download.Delivery != nil && e.Download.Delivery.Redeliverable
}

// ErrJobNotCompleted is wrapped by *JobNotCompletedError so callers can match
// the "artifact is not ready yet" case with errors.Is.
var ErrJobNotCompleted = errors.New("videofetch: download job is not completed yet")

// JobNotCompletedError is returned by Downloads.DownloadTo when the job has not
// reached status "completed" yet, so there is nothing to save. Poll with Wait
// (or the download.completed webhook) first.
type JobNotCompletedError struct {
	JobID  string
	Status DownloadStatus
}

func (e *JobNotCompletedError) Error() string {
	return fmt.Sprintf("videofetch: download job %s is %q — wait for completion before downloading",
		e.JobID, e.Status)
}

// Unwrap exposes the ErrJobNotCompleted sentinel.
func (e *JobNotCompletedError) Unwrap() error { return ErrJobNotCompleted }

// request performs an HTTP call with retry on 429/5xx/network errors.
func (c *Client) request(ctx context.Context, method, path string, body any, out any) error {
	var raw []byte
	var err error
	if body != nil {
		raw, err = json.Marshal(body)
		if err != nil {
			return err
		}
	}

	var lastErr error
	for attempt := 0; attempt <= c.maxRetries; attempt++ {
		var req *http.Request
		if raw != nil {
			req, err = http.NewRequestWithContext(ctx, method, c.baseURL+path, bytes.NewReader(raw))
		} else {
			req, err = http.NewRequestWithContext(ctx, method, c.baseURL+path, nil)
		}
		if err != nil {
			return err
		}
		req.Header.Set("Authorization", "Bearer "+c.apiKey)
		req.Header.Set("Content-Type", "application/json")
		req.Header.Set("User-Agent", "videofetch-go/0.5.0")

		resp, err := c.httpClient.Do(req)
		if err != nil {
			lastErr = err
			if attempt < c.maxRetries {
				time.Sleep(retryDelay(attempt))
				continue
			}
			return fmt.Errorf("videofetch: network error calling %s %s: %w", method, path, err)
		}
		bodyBytes, readErr := io.ReadAll(resp.Body)
		resp.Body.Close()
		if readErr != nil {
			return readErr
		}

		if resp.StatusCode == http.StatusTooManyRequests || resp.StatusCode >= 500 {
			if attempt < c.maxRetries {
				if d, ok := retryAfterDelay(resp.Header); ok {
					time.Sleep(d)
				} else {
					time.Sleep(retryDelay(attempt))
				}
				continue
			}
		}

		if resp.StatusCode >= 400 {
			return mapError(resp.StatusCode, bodyBytes, resp.Header)
		}
		if len(bodyBytes) == 0 || out == nil {
			return nil
		}
		return json.Unmarshal(bodyBytes, out)
	}
	return lastErr
}

type errorDetail struct {
	Code        string   `json:"code"`
	Type        string   `json:"type"`
	Message     string   `json:"message"`
	Msg         string   `json:"msg"`
	Param       string   `json:"param"`
	RemainingGB *float64 `json:"remaining_gb"`
	Limit       int      `json:"limit"`
	Active      int      `json:"active"`
	Scope       string   `json:"scope"`
	Hint        string   `json:"hint"`
}

func mapError(status int, body []byte, hdr http.Header) error {
	apiErr := &APIError{StatusCode: status, RawBody: string(body)}
	var d errorDetail
	// Server wraps business errors in {"detail": {...}} (or {"detail": "..."}).
	var wrapped struct {
		Detail json.RawMessage `json:"detail"`
	}
	if json.Unmarshal(body, &wrapped) == nil && len(wrapped.Detail) > 0 {
		if wrapped.Detail[0] == '"' {
			var msg string
			if json.Unmarshal(wrapped.Detail, &msg) == nil {
				apiErr.Message = msg
			}
		} else {
			_ = json.Unmarshal(wrapped.Detail, &d)
		}
	} else {
		_ = json.Unmarshal(body, &d)
	}
	apiErr.Code = d.Code
	if apiErr.Code == "" {
		apiErr.Code = d.Type
	}
	if apiErr.Message == "" {
		apiErr.Message = d.Message
	}
	if apiErr.Message == "" {
		apiErr.Message = d.Msg
	}
	apiErr.Param = d.Param
	apiErr.Hint = d.Hint
	if apiErr.Message == "" {
		apiErr.Message = fmt.Sprintf("unexpected HTTP %d", status)
	}

	switch status {
	case http.StatusUnprocessableEntity, http.StatusBadRequest:
		if strings.HasPrefix(apiErr.Code, "storage_") {
			return &StorageError{APIError: *apiErr}
		}
	case http.StatusConflict:
		return &ConflictError{APIError: *apiErr}
	case http.StatusPaymentRequired:
		return &QuotaExceededError{APIError: *apiErr, RemainingGB: d.RemainingGB}
	case http.StatusForbidden:
		// e.g. code "account_suspended" — inspect .Code.
		return &PermissionDeniedError{APIError: *apiErr}
	case http.StatusTooManyRequests:
		limit, active := d.Limit, d.Active
		if v := atoi(hdr.Get("X-Concurrency-Limit")); v != 0 && limit == 0 {
			limit = v
		}
		if v := atoi(hdr.Get("X-Concurrency-Active")); v != 0 && active == 0 {
			active = v
		}
		return &RateLimitError{
			APIError: *apiErr, Limit: limit, Active: active,
			Scope: d.Scope, RetryAfter: atoi(hdr.Get("Retry-After")),
		}
	}
	return apiErr
}

// retryAfterDelay returns the Retry-After hint as a Duration, capped at 30s.
// Returns ok=false when the header is absent/invalid so callers fall back to backoff.
func retryAfterDelay(hdr http.Header) (time.Duration, bool) {
	raw := hdr.Get("Retry-After")
	if raw == "" {
		return 0, false
	}
	n, err := strconv.Atoi(raw)
	if err != nil || n < 0 {
		return 0, false
	}
	d := time.Duration(n) * time.Second
	if d > 30*time.Second {
		d = 30 * time.Second
	}
	return d, true
}

func retryDelay(attempt int) time.Duration {
	// Fibonacci-ish: 2s, 3s, 5s, 8s, 13s, cap 30s + 20% jitter
	fib := []int{2, 3, 5, 8, 13, 21, 30}
	sec := fib[min(attempt, len(fib)-1)]
	return time.Duration(sec) * time.Second
}

func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}

func queryParams(v url.Values) string {
	if len(v) == 0 {
		return ""
	}
	return "?" + v.Encode()
}

func atoi(s string) int {
	n, _ := strconv.Atoi(s)
	return n
}
