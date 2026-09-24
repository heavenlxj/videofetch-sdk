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

func TestUsageKeyUsedFields(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		writeJSON(t, w, 200, map[string]any{
			"key_id": "key_1", "plan": "pro", "quota_gb": 100.0,
			// account-level usage (UsedBytes/UsedGB)
			"used_bytes": 3_000_000_000, "used_gb": 3.0,
			// per-API-key usage
			"key_used_bytes": 1_000_000_000, "key_used_gb": 1.0,
			"remaining_gb": 97.0, "payg_balance_cents": 0, "payg_rate_usd_per_gb": 0.5,
			"account_used_bytes_month": 3_000_000_000, "account_used_gb_month": 3.0,
			"used_pct": 3.0, "month": "2026-09", "active_jobs": 1,
			"concurrency_limit": 10, "alert_level": "ok", "alert_message": "",
		})
	}))
	defer srv.Close()

	u, err := testClient(t, srv).Usage.Get(context.Background())
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if u.UsedBytes != 3_000_000_000 || u.UsedGB != 3.0 {
		t.Fatalf("account-level usage = %d bytes / %v GB", u.UsedBytes, u.UsedGB)
	}
	if u.KeyUsedBytes != 1_000_000_000 || u.KeyUsedGB != 1.0 {
		t.Fatalf("key-level usage = %d bytes / %v GB", u.KeyUsedBytes, u.KeyUsedGB)
	}
}

// The account-level fields added in v0.4.0: the plan/pack split and the billing period.
// key_id is null for dashboard-session responses — Go leaves a string field untouched on
// JSON null, so this also pins that it does not error out.
func TestUsageGetPackSplitAndPeriod(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		writeJSON(t, w, 200, map[string]any{
			"key_id": nil, "plan": "pro", "quota_gb": 100.0, "used_bytes": 0, "used_gb": 0.0,
			"remaining_gb": 60.5, "plan_remaining_gb": 50.5, "pack_gb": 10.0,
			"pack_remaining_gb": 10.0, "period_start": "2026-09-01T00:00:00Z",
			"period_end": "2026-10-01T00:00:00Z", "payg_balance_cents": 0,
			"payg_rate_usd_per_gb": 0.5, "account_used_bytes_month": 0,
			"account_used_gb_month": 0.0, "used_pct": 39.5, "month": "2026-09",
			"active_jobs": 0, "concurrency_limit": 20,
			"alert_level": "ok", "alert_message": "",
		})
	}))
	defer srv.Close()

	u, err := testClient(t, srv).Usage.Get(context.Background())
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if u.KeyID != "" {
		t.Fatalf("key_id = %q, want the empty string for a null key_id", u.KeyID)
	}
	if u.PlanRemainingGB != 50.5 || u.PackGB != 10.0 || u.PackRemainingGB != 10.0 {
		t.Fatalf("pack split = (%v, %v, %v), want (50.5, 10, 10)",
			u.PlanRemainingGB, u.PackGB, u.PackRemainingGB)
	}
	if u.PlanRemainingGB+u.PackRemainingGB != *u.RemainingGB {
		t.Fatalf("plan+pack should add up to remaining: %v + %v != %v",
			u.PlanRemainingGB, u.PackRemainingGB, *u.RemainingGB)
	}
	if u.PeriodStart == nil || *u.PeriodStart != "2026-09-01T00:00:00Z" {
		t.Fatalf("period_start = %v", u.PeriodStart)
	}
	if u.PeriodEnd == nil || *u.PeriodEnd != "2026-10-01T00:00:00Z" {
		t.Fatalf("period_end = %v", u.PeriodEnd)
	}
}

// Absent period fields must stay nil rather than failing the decode (legacy accounts).
func TestUsageGetLegacyAccountWithoutPeriod(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		writeJSON(t, w, 200, map[string]any{"plan": "free", "quota_gb": 1.0, "used_bytes": 0})
	}))
	defer srv.Close()

	u, err := testClient(t, srv).Usage.Get(context.Background())
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if u.PeriodStart != nil || u.PeriodEnd != nil {
		t.Fatalf("period should be nil, got %v / %v", u.PeriodStart, u.PeriodEnd)
	}
	if u.PlanRemainingGB != 0 || u.PackGB != 0 || u.PackRemainingGB != 0 {
		t.Fatalf("pack fields should default to zero: %+v", u)
	}
}
