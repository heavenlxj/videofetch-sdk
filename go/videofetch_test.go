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

func TestDownloadQueueFields(t *testing.T) {
	queued := downloadJSON("queued", map[string]any{
		"queue_position": 4, "ahead_of_you": 3, "estimated_wait_seconds": 90,
	})

	_, err := json.Marshal(queued) // sanity: the fixture is valid JSON
	if err != nil {
		t.Fatal(err)
	}
	var dl Download
	if err := json.Unmarshal(mustJSON(t, queued), &dl); err != nil {
		t.Fatalf("unmarshal queued: %v", err)
	}
	if dl.QueuePosition == nil || *dl.QueuePosition != 4 {
		t.Fatalf("queue_position = %v, want 4", dl.QueuePosition)
	}
	if dl.AheadOfYou == nil || *dl.AheadOfYou != 3 {
		t.Fatalf("ahead_of_you = %v, want 3", dl.AheadOfYou)
	}
	if dl.EstimatedWaitSeconds == nil || *dl.EstimatedWaitSeconds != 90 {
		t.Fatalf("estimated_wait_seconds = %v, want 90", dl.EstimatedWaitSeconds)
	}

	// Non-queued states serialise these fields as null → nil pointers.
	var done Download
	if err := json.Unmarshal(mustJSON(t, downloadJSON("completed", map[string]any{
		"queue_position": nil, "ahead_of_you": nil, "estimated_wait_seconds": nil,
	})), &done); err != nil {
		t.Fatalf("unmarshal completed: %v", err)
	}
	if done.QueuePosition != nil || done.AheadOfYou != nil || done.EstimatedWaitSeconds != nil {
		t.Fatalf("queue fields must be nil when null: %+v", done)
	}
}

func mustJSON(t *testing.T, v any) []byte {
	t.Helper()
	b, err := json.Marshal(v)
	if err != nil {
		t.Fatal(err)
	}
	return b
}
