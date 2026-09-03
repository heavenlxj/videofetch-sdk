package videofetch

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

func downloadJSON(status string, overrides map[string]any) map[string]any {
	m := map[string]any{
		"id": "dl_abc123", "status": status, "url": "https://youtu.be/x",
		"format": "1080p", "progress": 0, "title": "T", "cost_usd": 0.0, "attempts": 0,
	}
	for k, v := range overrides {
		m[k] = v
	}
	return m
}

func writeJSON(t *testing.T, w http.ResponseWriter, status int, body any) {
	t.Helper()
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	if err := json.NewEncoder(w).Encode(body); err != nil {
		t.Fatal(err)
	}
}

func TestCreateAndWaitToCompleted(t *testing.T) {
	getCalls := 0
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method == "POST" && r.URL.Path == "/v1/downloads" {
			writeJSON(t, w, 202, downloadJSON("queued", nil))
			return
		}
		getCalls++
		if getCalls < 3 {
			writeJSON(t, w, 200, downloadJSON("processing", map[string]any{"progress": 55}))
			return
		}
		writeJSON(t, w, 200, downloadJSON("completed", map[string]any{
			"progress": 100, "download_url": "https://cdn.example/v.mp4",
			"size_bytes": 12345, "cost_usd": 0.0042, "strategy": "direct", "attempts": 1,
		}))
	}))
	defer srv.Close()

	client := NewClient("vf_live_sk_test", &ClientOptions{
		BaseURL: srv.URL, HTTPClient: &http.Client{Timeout: 5 * time.Second},
	})
	result, err := client.Downloads.CreateAndWait(
		context.Background(),
		DownloadCreateParams{URL: "https://youtu.be/x", Format: Format720p},
		10*time.Second,
	)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if result.Status != StatusCompleted {
		t.Fatalf("expected completed, got %s", result.Status)
	}
	if result.DownloadURL == nil || *result.DownloadURL != "https://cdn.example/v.mp4" {
		t.Fatalf("unexpected download_url: %v", result.DownloadURL)
	}
}

func TestWaitRaisesJobFailed(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method == "POST" {
			writeJSON(t, w, 202, downloadJSON("queued", nil))
			return
		}
		writeJSON(t, w, 200, downloadJSON("failed", map[string]any{
			"error_code": "download_failed", "error_message": "blocked by youtube",
		}))
	}))
	defer srv.Close()

	client := NewClient("k", &ClientOptions{
		BaseURL: srv.URL, HTTPClient: &http.Client{Timeout: 5 * time.Second},
	})
	_, err := client.Downloads.CreateAndWait(
		context.Background(),
		DownloadCreateParams{URL: "https://youtu.be/x"},
		10*time.Second,
	)
	jobErr, ok := err.(*JobFailedError)
	if !ok {
		t.Fatalf("expected *JobFailedError, got %T: %v", err, err)
	}
	if jobErr.ErrorCode != "download_failed" {
		t.Fatalf("unexpected code: %s", jobErr.ErrorCode)
	}
}

func TestQuotaExceededMapping(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		writeJSON(t, w, 402, map[string]any{"detail": map[string]any{
			"code": "quota_exceeded", "message": "Free tier exhausted (5 GB)", "remaining_gb": 0,
		}})
	}))
	defer srv.Close()

	client := NewClient("k", &ClientOptions{BaseURL: srv.URL})
	_, err := client.Downloads.Create(context.Background(), DownloadCreateParams{
		URL: "https://youtu.be/x", Format: Format1080p,
	})
	if _, ok := err.(*QuotaExceededError); !ok {
		t.Fatalf("expected *QuotaExceededError, got %T: %v", err, err)
	}
}

func TestInfoLookup(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/v1/info" || r.Method != "POST" {
			t.Fatalf("unexpected %s %s", r.Method, r.URL.Path)
		}
		writeJSON(t, w, 200, map[string]any{
			"id": "abc", "url": "https://youtu.be/x", "title": "Hello", "duration": 120.0,
			"formats": []any{map[string]any{"quality": "720p", "size": 1000}},
		})
	}))
	defer srv.Close()

	client := NewClient("k", &ClientOptions{BaseURL: srv.URL})
	info, err := client.Info.Lookup(context.Background(), "https://youtu.be/x")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if info.Title == nil || *info.Title != "Hello" {
		t.Fatalf("unexpected title: %v", info.Title)
	}
	if len(info.Formats) != 1 || info.Formats[0].Quality != "720p" {
		t.Fatalf("unexpected formats: %+v", info.Formats)
	}
}
