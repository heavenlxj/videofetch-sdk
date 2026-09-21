package videofetch

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

func testClient(t *testing.T, srv *httptest.Server) *Client {
	t.Helper()
	return NewClient("vf_live_sk_test", &ClientOptions{
		BaseURL: srv.URL, HTTPClient: &http.Client{Timeout: 5 * time.Second},
	})
}

func TestUsageGet(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/v1/usage" || r.Method != "GET" {
			t.Fatalf("unexpected %s %s", r.Method, r.URL.Path)
		}
		writeJSON(t, w, 200, map[string]any{
			"key_id": "key_1", "plan": "free", "quota_gb": 1.0, "used_bytes": 0,
			"used_gb": 0.0, "remaining_gb": 1.0, "payg_balance_cents": 0,
			"payg_rate_usd_per_gb": 0.5, "account_used_bytes_month": 0,
			"account_used_gb_month": 0.0, "used_pct": 0.0, "month": "2026-09",
			"active_jobs": 0, "concurrency_limit": 5, "alert_level": "ok", "alert_message": "",
		})
	}))
	defer srv.Close()

	u, err := testClient(t, srv).Usage.Get(context.Background())
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if u.QuotaGB == nil || *u.QuotaGB != 1.0 {
		t.Fatalf("quota_gb = %v, want 1.0", u.QuotaGB)
	}
	if u.ConcurrencyLimit != 5 {
		t.Fatalf("concurrency_limit = %d, want 5", u.ConcurrencyLimit)
	}
	if u.RemainingGB == nil || *u.RemainingGB != 1.0 {
		t.Fatalf("remaining_gb = %v, want 1.0", u.RemainingGB)
	}
	if u.AlertLevel != "ok" || u.Month != "2026-09" {
		t.Fatalf("unexpected alert_level/month: %q %q", u.AlertLevel, u.Month)
	}
}

func TestUsageGetWarningLevel(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		writeJSON(t, w, 200, map[string]any{
			"key_id": "k", "plan": "free", "quota_gb": 1.0, "used_bytes": 0, "used_gb": 0.0,
			"remaining_gb": 0.04, "payg_balance_cents": 0, "payg_rate_usd_per_gb": 0.5,
			"account_used_bytes_month": 0, "account_used_gb_month": 0.96, "used_pct": 96.0,
			"month": "2026-09", "active_jobs": 2, "concurrency_limit": 5,
			"alert_level": "critical", "alert_message": "less than 5% left",
		})
	}))
	defer srv.Close()

	u, err := testClient(t, srv).Usage.Get(context.Background())
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if u.AlertLevel != "critical" || u.UsedPct != 96.0 || u.ActiveJobs != 2 {
		t.Fatalf("unexpected usage: %+v", u)
	}
}

func TestUsageAlerts(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/v1/usage/alerts" {
			t.Fatalf("unexpected path %s", r.URL.Path)
		}
		writeJSON(t, w, 200, map[string]any{
			"state": map[string]any{
				"level": "warning", "pct_used": 82.5, "thresholds": []int{80, 95, 100},
				"crossed": []int{80}, "next_threshold_pct": 95, "quota_gb": 1.0,
				"used_gb_month": 0.825, "remaining_gb": 0.175, "month": "2026-09",
				"plan": "free", "payg_balance_cents": 0, "balance_low": false,
				"balance_depleted": true, "balance_hint": "top up", "message": "82.5% used",
				"action": "upgrade",
			},
			"fired": []any{map[string]any{
				"id": "al_1", "kind": "usage_threshold", "level": "warning", "threshold": 80,
				"pct_used": 82.5, "used_gb": 0.825, "quota_gb": 1.0, "balance_cents": 0,
				"message": "80% crossed", "delivered": true, "created_at": "2026-09-21T00:00:00Z",
			}},
			"thresholds":    []int{80, 95, 100},
			"topup_amounts": []int{10, 25, 50, 100},
		})
	}))
	defer srv.Close()

	a, err := testClient(t, srv).Usage.Alerts(context.Background())
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(a.Thresholds) != 3 || a.Thresholds[0] != 80 || a.Thresholds[2] != 100 {
		t.Fatalf("thresholds = %v, want [80 95 100]", a.Thresholds)
	}
	if len(a.TopupAmounts) != 4 || a.TopupAmounts[3] != 100 {
		t.Fatalf("topup_amounts = %v", a.TopupAmounts)
	}
	if a.State.Level != "warning" || len(a.State.Crossed) != 1 || a.State.Crossed[0] != 80 {
		t.Fatalf("state crossed = %v", a.State.Crossed)
	}
	if a.State.NextThresholdPct == nil || *a.State.NextThresholdPct != 95 {
		t.Fatalf("next_threshold_pct = %v", a.State.NextThresholdPct)
	}
	if a.State.Action == nil || *a.State.Action != "upgrade" {
		t.Fatalf("action = %v", a.State.Action)
	}
	if len(a.Fired) != 1 || !a.Fired[0].Delivered {
		t.Fatalf("fired = %+v", a.Fired)
	}
}
