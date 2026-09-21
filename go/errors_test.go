package videofetch

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestRateLimitErrorMapping(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Retry-After", "0") // keep the retry loop instant
		w.Header().Set("X-Concurrency-Limit", "5")
		w.Header().Set("X-Concurrency-Active", "5")
		writeJSON(t, w, 429, map[string]any{"detail": map[string]any{
			"code": "concurrency_limit_exceeded", "message": "Too many in-flight jobs: 5/5.",
			"param": "url", "limit": 5, "active": 5, "scope": "account",
		}})
	}))
	defer srv.Close()

	_, err := testClient(t, srv).Downloads.Create(context.Background(), DownloadCreateParams{
		URL: "https://youtu.be/x", Format: Format720p,
	})

	var rle *RateLimitError
	if !errors.As(err, &rle) {
		t.Fatalf("want *RateLimitError via errors.As, got %T: %v", err, err)
	}
	if rle.Code != "concurrency_limit_exceeded" {
		t.Fatalf("code = %q", rle.Code)
	}
	if rle.Limit != 5 || rle.Active != 5 || rle.Scope != "account" {
		t.Fatalf("unexpected limit/active/scope: %+v", rle)
	}
	if rle.StatusCode != 429 {
		t.Fatalf("status = %d", rle.StatusCode)
	}
	// embedded APIError must also be reachable via errors.As
	var apiErr *APIError
	if !errors.As(err, &apiErr) {
		t.Fatalf("embedded *APIError not reachable via errors.As")
	}
}

func TestRateLimitPlatformScope(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Retry-After", "0")
		writeJSON(t, w, 429, map[string]any{"detail": map[string]any{
			"code": "platform_at_capacity", "message": "Platform is at capacity.",
			"limit": 100, "active": 100, "scope": "platform",
		}})
	}))
	defer srv.Close()

	_, err := testClient(t, srv).Downloads.Create(context.Background(), DownloadCreateParams{URL: "https://youtu.be/x"})
	var rle *RateLimitError
	if !errors.As(err, &rle) {
		t.Fatalf("want *RateLimitError, got %T", err)
	}
	if rle.Code != "platform_at_capacity" || rle.Scope != "platform" || rle.RetryAfter != 0 {
		t.Fatalf("unexpected: %+v", rle)
	}
}

func TestAccountSuspendedMapping(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		writeJSON(t, w, 403, map[string]any{"detail": map[string]any{
			"code": "account_suspended", "message": "This account is suspended. Contact support.",
		}})
	}))
	defer srv.Close()

	_, err := testClient(t, srv).Usage.Get(context.Background())
	var pde *PermissionDeniedError
	if !errors.As(err, &pde) {
		t.Fatalf("want *PermissionDeniedError via errors.As, got %T: %v", err, err)
	}
	if pde.Code != "account_suspended" || pde.StatusCode != 403 {
		t.Fatalf("unexpected: %+v", pde)
	}
}

func TestQuotaRemainingGB(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		writeJSON(t, w, 402, map[string]any{"detail": map[string]any{
			"code": "quota_exceeded", "message": "Free tier exhausted", "remaining_gb": 0.25,
		}})
	}))
	defer srv.Close()

	_, err := testClient(t, srv).Downloads.Create(context.Background(), DownloadCreateParams{URL: "https://youtu.be/x"})
	var qee *QuotaExceededError
	if !errors.As(err, &qee) {
		t.Fatalf("want *QuotaExceededError via errors.As, got %T: %v", err, err)
	}
	if qee.RemainingGB == nil || *qee.RemainingGB != 0.25 {
		t.Fatalf("remaining_gb = %v, want 0.25", qee.RemainingGB)
	}
}

func TestMapErrorDirectly(t *testing.T) {
	hdr := http.Header{}
	hdr.Set("Retry-After", "10")
	hdr.Set("X-Concurrency-Limit", "5")
	hdr.Set("X-Concurrency-Active", "5")
	err := mapError(429, []byte(`{"detail":{"code":"queue_limit_exceeded","message":"queue full"}}`), hdr)
	var rle *RateLimitError
	if !errors.As(err, &rle) {
		t.Fatalf("want *RateLimitError, got %T", err)
	}
	if rle.Code != "queue_limit_exceeded" || rle.Limit != 5 || rle.Active != 5 || rle.RetryAfter != 10 {
		t.Fatalf("unexpected: %+v", rle)
	}
}
