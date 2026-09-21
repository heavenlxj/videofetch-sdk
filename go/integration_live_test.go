//go:build integration

// Live integration test for the official Go SDK (v0.2.0).
//
// 用法:
//
//	VF_BASE=http://127.0.0.1:8301 VF_KEY=vf_live_sk_... \
//	  go test -tags integration -run Live -v -timeout 15m ./...
//
// 未设 VF_KEY 时自动跳过 (CI 无凭据也安全)。
package videofetch

import (
	"bytes"
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"os"
	"testing"
	"time"
)

func liveClient(t *testing.T) *Client {
	t.Helper()
	key := os.Getenv("VF_KEY")
	if key == "" {
		t.Skip("VF_KEY not set — skipping live integration test")
	}
	base := os.Getenv("VF_BASE")
	if base == "" {
		base = "http://127.0.0.1:8301"
	}
	return NewClient(key, &ClientOptions{BaseURL: base})
}

func TestLiveUsageAndAlerts(t *testing.T) {
	c := liveClient(t)
	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()

	u, err := c.Usage.Get(ctx)
	if err != nil {
		t.Fatalf("usage.Get: %v", err)
	}
	if u.QuotaGB == nil || *u.QuotaGB != 1.0 {
		t.Errorf("quota_gb = %v, want 1.0 (free tier)", u.QuotaGB)
	}
	if u.ConcurrencyLimit <= 0 {
		t.Errorf("concurrency_limit = %d, want > 0", u.ConcurrencyLimit)
	}
	if u.Month == "" {
		t.Error("month is empty")
	}
	switch u.AlertLevel {
	case "ok", "warning", "critical", "exceeded":
	default:
		t.Errorf("alert_level = %q not in the documented set", u.AlertLevel)
	}
	t.Logf("usage: plan=%s quota=%v remaining=%v pct=%v month=%s limit=%d active=%d alert=%s",
		u.Plan, *u.QuotaGB, u.RemainingGB, u.UsedPct, u.Month, u.ConcurrencyLimit, u.ActiveJobs, u.AlertLevel)

	al, err := c.Usage.Alerts(ctx)
	if err != nil {
		t.Fatalf("usage.Alerts: %v", err)
	}
	if len(al.Thresholds) != 3 || al.Thresholds[0] != 80 || al.Thresholds[2] != 100 {
		t.Errorf("thresholds = %v, want [80 95 100]", al.Thresholds)
	}
	if len(al.TopupAmounts) == 0 {
		t.Error("topup_amounts is empty")
	}
	if al.State.RemainingGB == nil {
		t.Error("state.remaining_gb is nil")
	}
	t.Logf("alerts: level=%s pct=%v remaining=%v thresholds=%v topup=%v fired=%d",
		al.State.Level, al.State.PctUsed, al.State.RemainingGB, al.Thresholds, al.TopupAmounts, len(al.Fired))
}

func TestLiveWebhooksAndSignature(t *testing.T) {
	c := liveClient(t)
	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()

	wh, err := c.Webhooks.Create(ctx, "http://127.0.0.1:9/not-listening",
		EventCompleted, EventQuotaWarning)
	if err != nil {
		t.Fatalf("webhooks.Create: %v", err)
	}
	if len(wh.Secret) < 20 {
		t.Errorf("secret on create should be the full plaintext value, got %q", wh.Secret)
	}
	t.Logf("webhook created: id=%s secret_len=%d events=%v", wh.ID, len(wh.Secret), wh.Events)

	lst, err := c.Webhooks.List(ctx)
	if err != nil {
		t.Fatalf("webhooks.List: %v", err)
	}
	var masked string
	for _, w := range lst.Items {
		if w.ID == wh.ID {
			masked = w.Secret
		}
	}
	if masked == "" {
		t.Fatal("created webhook missing from List")
	}
	if masked == wh.Secret {
		t.Error("List returned the full secret — it must be masked")
	}

	body := []byte(`{"event":"download.completed","id":"dl_test"}`)
	mac := hmac.New(sha256.New, []byte(wh.Secret))
	mac.Write(body)
	sig := "sha256=" + hex.EncodeToString(mac.Sum(nil))
	ev, err := VerifyWebhookSignature(body, sig, wh.Secret)
	if err != nil {
		t.Errorf("valid signature rejected: %v", err)
	} else if ev.Event != "download.completed" {
		t.Errorf("parsed event = %q", ev.Event)
	}
	if _, err := VerifyWebhookSignature(append(bytes.Clone(body), ' '), sig, wh.Secret); err == nil {
		t.Error("tampered body accepted — verification is not doing its job")
	} else if !errors.Is(err, ErrBadSignature) {
		t.Errorf("tampered body error = %v, want ErrBadSignature", err)
	}

	if err := c.Webhooks.Delete(ctx, wh.ID); err != nil {
		t.Fatalf("webhooks.Delete: %v", err)
	}
}

func TestLiveDownloadWithTrim(t *testing.T) {
	c := liveClient(t)
	ctx, cancel := context.WithTimeout(context.Background(), 6*time.Minute)
	defer cancel()

	start, end := 0.0, 20.0
	job, err := c.Downloads.Create(ctx, DownloadCreateParams{
		URL:    "https://www.youtube.com/watch?v=aqz-KE-bpKQ",
		Format: FormatMP3,
		Trim:   &TrimSpec{Start: &start, End: &end},
	})
	if err != nil {
		t.Fatalf("downloads.Create: %v", err)
	}
	t.Logf("job created: id=%s status=%s", job.ID(), job.Status())

	res, err := job.Wait(ctx, 5*time.Minute)
	if err != nil {
		t.Fatalf("job.Wait: %v", err)
	}
	if res.Status != StatusCompleted {
		msg := ""
		if res.ErrorMessage != nil {
			msg = *res.ErrorMessage
		}
		t.Fatalf("status = %s, want completed (%s)", res.Status, msg)
	}
	if res.SizeBytes == nil || *res.SizeBytes <= 0 {
		t.Errorf("completed job has no artifact size: %v", res.SizeBytes)
	}
	if res.DownloadURL == nil || *res.DownloadURL == "" {
		t.Errorf("completed job has no download_url: %v", res.DownloadURL)
	}
	t.Logf("completed: size=%v cost=%.6f strategy=%v", *res.SizeBytes, res.CostUSD, res.Strategy)
}

func TestLiveInvalidKey(t *testing.T) {
	base := os.Getenv("VF_BASE")
	if base == "" {
		base = "http://127.0.0.1:8301"
	}
	c := NewClient("vf_live_sk_deadbeef", &ClientOptions{BaseURL: base})
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	_, err := c.Usage.Get(ctx)
	if err == nil {
		t.Fatal("invalid key was accepted")
	}
	var apiErr *APIError
	if !errors.As(err, &apiErr) {
		t.Fatalf("want *APIError, got %T: %v", err, err)
	}
	if apiErr.StatusCode != 401 {
		t.Fatalf("status = %d, want 401 (code=%s)", apiErr.StatusCode, apiErr.Code)
	}
	t.Logf("invalid key → status=%d code=%s", apiErr.StatusCode, apiErr.Code)
}
