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
