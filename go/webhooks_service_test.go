package videofetch

import (
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

const fullSecret = "whsec_0123456789abcdef0123456789abcdef0123456789abcdef"

// mirrors the server: "sha256=" + hex(hmac-sha256(secret, rawBody))
func testSign(payload []byte, secret string) string {
	mac := hmac.New(sha256.New, []byte(secret))
	mac.Write(payload)
	return "sha256=" + hex.EncodeToString(mac.Sum(nil))
}

func TestWebhooksCRUDAndTest(t *testing.T) {
	var createdBody map[string]any
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.Method == "POST" && r.URL.Path == "/v1/webhooks":
			if err := json.NewDecoder(r.Body).Decode(&createdBody); err != nil {
				t.Fatal(err)
			}
			writeJSON(t, w, 201, map[string]any{
				"id": "wh_1", "url": createdBody["url"], "secret": fullSecret,
				"events": createdBody["events"], "active": true,
				"last_delivery_at": nil, "last_status": nil, "failure_count": 0,
				"created_at": "2026-09-21T00:00:00Z",
			})
		case r.Method == "GET" && r.URL.Path == "/v1/webhooks":
			masked := fullSecret[:11] + strings.Repeat("*", 8) + fullSecret[len(fullSecret)-4:]
			writeJSON(t, w, 200, map[string]any{"items": []any{map[string]any{
				"id": "wh_1", "url": "https://example.com/hook", "secret": masked,
				"events": WebhookEvents, "active": true,
			}}})
		case r.Method == "POST" && r.URL.Path == "/v1/webhooks/wh_1/test":
			writeJSON(t, w, 200, map[string]any{
				"delivered": true, "url": "https://example.com/hook", "last_status": 200,
				"signature_header": "X-VideoFetch-Signature",
				"signature_format": "sha256=<hex hmac-sha256 of raw body>",
			})
		case r.Method == "DELETE" && r.URL.Path == "/v1/webhooks/wh_1":
			w.WriteHeader(204)
		default:
			t.Fatalf("unexpected %s %s", r.Method, r.URL.Path)
		}
	}))
	defer srv.Close()

	c := testClient(t, srv)
	ctx := context.Background()

	wh, err := c.Webhooks.Create(ctx, "https://example.com/hook", EventCompleted, EventQuotaExceeded)
	if err != nil {
		t.Fatalf("create: %v", err)
	}
	if wh.ID != "wh_1" {
		t.Fatalf("id = %q", wh.ID)
	}
	if wh.Secret != fullSecret {
		t.Fatalf("create should return the full plaintext secret, got %q", wh.Secret)
	}
	gotEvents, _ := createdBody["events"].([]any)
	if len(gotEvents) != 2 || gotEvents[1] != EventQuotaExceeded {
		t.Fatalf("events filter not sent: %v", createdBody["events"])
	}

	list, err := c.Webhooks.List(ctx)
	if err != nil {
		t.Fatalf("list: %v", err)
	}
	if len(list.Items) != 1 {
		t.Fatalf("want 1 item, got %d", len(list.Items))
	}
	if list.Items[0].Secret == fullSecret || !strings.Contains(list.Items[0].Secret, "*") {
		t.Fatalf("list secret should be masked, got %q", list.Items[0].Secret)
	}

	res, err := c.Webhooks.Test(ctx, "wh_1")
	if err != nil {
		t.Fatalf("test: %v", err)
	}
	if !res.Delivered || res.SignatureHeader != "X-VideoFetch-Signature" {
		t.Fatalf("unexpected test result: %+v", res)
	}
	if !strings.Contains(res.SignatureFormat, "sha256=") {
		t.Fatalf("unexpected signature_format: %q", res.SignatureFormat)
	}

	if err := c.Webhooks.Delete(ctx, "wh_1"); err != nil {
		t.Fatalf("delete (204) should not error: %v", err)
	}
}

func TestWebhookEventsCatalogue(t *testing.T) {
	want := []string{
		"download.queued", "download.processing", "download.completed", "download.failed",
		"quota.warning", "quota.exceeded", "balance.low",
	}
	if len(WebhookEvents) != len(want) {
		t.Fatalf("WebhookEvents = %v", WebhookEvents)
	}
	for i := range want {
		if WebhookEvents[i] != want[i] {
			t.Fatalf("WebhookEvents[%d] = %q, want %q", i, WebhookEvents[i], want[i])
		}
	}
}

func TestWebhooksCreateWithoutEvents(t *testing.T) {
	var body map[string]any
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewDecoder(r.Body).Decode(&body)
		writeJSON(t, w, 201, map[string]any{"id": "wh_2", "url": body["url"], "secret": fullSecret, "events": WebhookEvents, "active": true})
	}))
	defer srv.Close()

	if _, err := testClient(t, srv).Webhooks.Create(context.Background(), "https://example.com/x"); err != nil {
		t.Fatalf("create: %v", err)
	}
	if _, ok := body["events"]; ok {
		t.Fatalf("events should be omitted when none are supplied: %v", body)
	}
}

func TestVerifyWebhookSignature(t *testing.T) {
	secret := "whsec_test"
	raw := []byte(`{"event":"download.completed","id":"dl_abc","status":"completed"}`)
	sig := testSign(raw, secret)

	ev, err := VerifyWebhookSignature(raw, sig, secret)
	if err != nil {
		t.Fatalf("valid signature rejected: %v", err)
	}
	if string(ev.Event) != "download.completed" || ev.ID != "dl_abc" {
		t.Fatalf("unexpected event: %+v", ev)
	}

	tampered := []byte(strings.Replace(string(raw), "dl_abc", "dl_evil", 1))
	if _, err := VerifyWebhookSignature(tampered, sig, secret); err != ErrBadSignature {
		t.Fatalf("tampered payload: want ErrBadSignature, got %v", err)
	}
	wrongSig := testSign(raw, "other_secret")
	if _, err := VerifyWebhookSignature(raw, wrongSig, secret); err != ErrBadSignature {
		t.Fatalf("wrong secret: want ErrBadSignature, got %v", err)
	}
	if _, err := VerifyWebhookSignature(raw, "", secret); err == nil {
		t.Fatal("missing header should error")
	}
	if _, err := VerifyWebhookSignature(raw, "nope", secret); err == nil {
		t.Fatal("malformed header should error")
	}
}

func TestWebhooksDeliveries(t *testing.T) {
	var gotQuery string
	var gotPath string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotQuery = r.URL.RawQuery
		gotPath = r.URL.Path
		if r.Method != "GET" {
			t.Fatalf("method = %s, want GET", r.Method)
		}
		writeJSON(t, w, 200, map[string]any{
			"endpoint_id": "wh_1", "active": true, "auto_disabled_at": nil,
			"consecutive_failures": 2, "max_attempts": 3, "retry_schedule_seconds": "30,300",
			"health": map[string]any{
				"total": 5, "succeeded": 3, "dead": 1, "pending": 1, "success_rate": 0.6,
			},
			"items": []any{
				map[string]any{
					"event_id": "evt_1", "event": "download.completed", "seq": 7,
					"status": "pending", "attempts": 2, "max_attempts": 3,
					"last_status_code": 500, "last_error": "receiver returned 500",
					"next_attempt_at": "2026-09-23T00:00:30Z",
					"created_at":      "2026-09-23T00:00:00Z", "delivered_at": nil,
					"download_id": "dl_1",
				},
				map[string]any{
					"event_id": "evt_2", "event": "download.failed", "seq": 8,
					"status": "succeeded", "attempts": 1, "max_attempts": 3,
					"last_status_code": 200, "last_error": nil,
					"next_attempt_at": nil, "created_at": "2026-09-23T00:01:00Z",
					"delivered_at": "2026-09-23T00:01:01Z", "download_id": nil,
				},
			},
		})
	}))
	defer srv.Close()

	res, err := testClient(t, srv).Webhooks.Deliveries(context.Background(), "wh_1", 10)
	if err != nil {
		t.Fatalf("deliveries: %v", err)
	}
	if gotPath != "/v1/webhooks/wh_1/deliveries" {
		t.Fatalf("path = %q", gotPath)
	}
	if gotQuery != "limit=10" {
		t.Fatalf("query = %q, want limit=10", gotQuery)
	}
	if res.EndpointID != "wh_1" || !res.Active || res.ConsecutiveFailures != 2 {
		t.Fatalf("unexpected envelope: %+v", res)
	}
	if res.AutoDisabledAt != nil {
		t.Fatalf("auto_disabled_at = %v, want nil", res.AutoDisabledAt)
	}
	if res.MaxAttempts != 3 || res.RetryScheduleSeconds != "30,300" {
		t.Fatalf("unexpected retry metadata: %+v", res)
	}
	if res.Health.Total != 5 || res.Health.Dead != 1 || res.Health.SuccessRate != 0.6 {
		t.Fatalf("unexpected health: %+v", res.Health)
	}
	if len(res.Items) != 2 {
		t.Fatalf("items = %d, want 2", len(res.Items))
	}
	it := res.Items[0]
	if it.EventID != "evt_1" || it.Seq != 7 || it.Attempts != 2 || it.MaxAttempts != 3 {
		t.Fatalf("unexpected item: %+v", it)
	}
	if it.LastStatusCode == nil || *it.LastStatusCode != 500 {
		t.Fatalf("last_status_code = %v, want 500", it.LastStatusCode)
	}
	if it.LastError == nil || *it.LastError != "receiver returned 500" {
		t.Fatalf("last_error = %v", it.LastError)
	}
	if it.DeliveredAt != nil {
		t.Fatalf("delivered_at = %v, want nil", it.DeliveredAt)
	}
	if it.DownloadID == nil || *it.DownloadID != "dl_1" {
		t.Fatalf("download_id = %v", it.DownloadID)
	}
}

func TestWebhooksDeliveriesOmitsLimit(t *testing.T) {
	var gotRawQuery string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotRawQuery = r.URL.RawQuery
		writeJSON(t, w, 200, map[string]any{
			"endpoint_id": "wh_1", "active": true, "max_attempts": 3,
			"health": map[string]any{"total": 0, "succeeded": 0, "dead": 0, "pending": 0, "success_rate": 0},
			"items":  []any{},
		})
	}))
	defer srv.Close()

	if _, err := testClient(t, srv).Webhooks.Deliveries(context.Background(), "wh_1", 0); err != nil {
		t.Fatalf("deliveries: %v", err)
	}
	if gotRawQuery != "" {
		t.Fatalf("query = %q, want empty (server default)", gotRawQuery)
	}
}

func TestWebhooksReplay(t *testing.T) {
	var method, path string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		method, path = r.Method, r.URL.Path
		writeJSON(t, w, 200, map[string]any{"queued": true, "event_id": "evt_123"})
	}))
	defer srv.Close()

	res, err := testClient(t, srv).Webhooks.Replay(context.Background(), "evt_123")
	if err != nil {
		t.Fatalf("replay: %v", err)
	}
	if method != "POST" || path != "/v1/webhooks/deliveries/evt_123/replay" {
		t.Fatalf("unexpected request %s %s", method, path)
	}
	if !res.Queued || res.EventID != "evt_123" {
		t.Fatalf("unexpected replay result: %+v", res)
	}
}

func TestDeliveryHeaders(t *testing.T) {
	// http.Header canonicalises key casing, so a differently-cased Set/Get pair
	// must still match (the "VideoFetch" spelling is not significant).
	h := http.Header{}
	h.Set("x-videofetch-delivery", "evt_abc")
	h.Set("x-videofetch-attempt", "2")
	if got := DeliveryID(h); got != "evt_abc" {
		t.Fatalf("DeliveryID = %q, want evt_abc", got)
	}
	if got := AttemptNumber(h); got != 2 {
		t.Fatalf("AttemptNumber = %q, want 2", got)
	}

	// Missing headers.
	if got := DeliveryID(http.Header{}); got != "" {
		t.Fatalf("DeliveryID(missing) = %q, want empty", got)
	}
	if got := AttemptNumber(http.Header{}); got != 0 {
		t.Fatalf("AttemptNumber(missing) = %d, want 0", got)
	}

	// Malformed / negative attempt values degrade to 0.
	for _, raw := range []string{"not-a-number", "", "-1", "1.5"} {
		bh := http.Header{}
		bh.Set("X-VideoFetch-Attempt", raw)
		if got := AttemptNumber(bh); got != 0 {
			t.Fatalf("AttemptNumber(%q) = %d, want 0", raw, got)
		}
	}
}
