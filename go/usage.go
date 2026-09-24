package videofetch

import "context"

// Usage is the GET /v1/usage response: account-level quota snapshot + the live
// alert level and concurrency window.
//
// QuotaGB/RemainingGB are the subscription quota. PlanRemainingGB excludes top-up
// packs, while PackGB/PackRemainingGB cover the packs bought for the current period.
// KeyID is empty when the figures were produced from a dashboard session rather than
// an API key.
type Usage struct {
	KeyID            string   `json:"key_id"`
	Plan             string   `json:"plan"`
	QuotaGB          *float64 `json:"quota_gb"`
	UsedBytes        int64    `json:"used_bytes"`     // account-level bytes used this month
	UsedGB           float64  `json:"used_gb"`        // account-level GB used this month
	KeyUsedBytes     int64    `json:"key_used_bytes"` // bytes used by this API key this month
	KeyUsedGB        float64  `json:"key_used_gb"`    // GB used by this API key this month
	RemainingGB      *float64 `json:"remaining_gb"`
	PlanRemainingGB  float64  `json:"plan_remaining_gb"`  // quota left, excluding top-up packs
	PackGB           float64  `json:"pack_gb"`            // GB bought as top-up packs this period
	PackRemainingGB  float64  `json:"pack_remaining_gb"`  // GB left across those packs
	PeriodStart      *string  `json:"period_start"`       // ISO 8601; nil on legacy accounts
	PeriodEnd        *string  `json:"period_end"`         // ISO 8601; nil on legacy accounts
	PaygBalanceCents int      `json:"payg_balance_cents"`
	PaygRateUSDPerGB float64  `json:"payg_rate_usd_per_gb"`
	// Month-to-date account usage (matches GET /v1/stats/overview).
	AccountUsedBytesMonth int64   `json:"account_used_bytes_month"`
	AccountUsedGBMonth    float64 `json:"account_used_gb_month"`
	UsedPct               float64 `json:"used_pct"`
	Month                 string  `json:"month"`
	ActiveJobs            int     `json:"active_jobs"`       // queued + processing
	ConcurrencyLimit      int     `json:"concurrency_limit"` // account cap
	AlertLevel            string  `json:"alert_level"`       // ok|warning|critical|exceeded
	AlertMessage          string  `json:"alert_message"`
}

// AlertState is the live alert state returned inside GET /v1/usage/alerts.
type AlertState struct {
	Level            string   `json:"level"`
	PctUsed          float64  `json:"pct_used"`
	Thresholds       []int    `json:"thresholds"`
	Crossed          []int    `json:"crossed"`
	NextThresholdPct *int     `json:"next_threshold_pct"`
	QuotaGB          float64  `json:"quota_gb"`
	UsedGBMonth      float64  `json:"used_gb_month"`
	RemainingGB      *float64 `json:"remaining_gb"`
	Month            string   `json:"month"`
	Plan             string   `json:"plan"`
	PaygBalanceCents int      `json:"payg_balance_cents"`
	BalanceLow       bool     `json:"balance_low"`
	BalanceDepleted  bool     `json:"balance_depleted"`
	BalanceHint      *string  `json:"balance_hint"`
	Message          string   `json:"message"`
	Action           *string  `json:"action"` // topup | upgrade | nil
}

// AlertEvent is one fired alert record (deduped: one per threshold per month).
type AlertEvent struct {
	ID           string  `json:"id"`
	Kind         string  `json:"kind"`
	Level        string  `json:"level"`
	Threshold    int     `json:"threshold"`
	PctUsed      float64 `json:"pct_used"`
	UsedGB       float64 `json:"used_gb"`
	QuotaGB      float64 `json:"quota_gb"`
	BalanceCents int     `json:"balance_cents"`
	Message      string  `json:"message"`
	Delivered    bool    `json:"delivered"`
	CreatedAt    string  `json:"created_at"`
}

// UsageAlerts is the GET /v1/usage/alerts response.
type UsageAlerts struct {
	State        AlertState   `json:"state"`
	Fired        []AlertEvent `json:"fired"`
	Thresholds   []int        `json:"thresholds"`    // e.g. [80, 95, 100]
	TopupAmounts []int        `json:"topup_amounts"` // e.g. [10, 25, 50, 100]
}

// UsageService provides quota/usage and alert state. Access via client.Usage.
type UsageService struct{ client *Client }

// Get returns the account-level quota snapshot (plan, quota, month-to-date
// usage, remaining credit, concurrency window and alert level).
func (s *UsageService) Get(ctx context.Context) (*Usage, error) {
	var u Usage
	if err := s.client.request(ctx, "GET", "/v1/usage", nil, &u); err != nil {
		return nil, err
	}
	return &u, nil
}

// Alerts returns the live alert state, the fired alert history and the
// configured thresholds / top-up presets.
func (s *UsageService) Alerts(ctx context.Context) (*UsageAlerts, error) {
	var a UsageAlerts
	if err := s.client.request(ctx, "GET", "/v1/usage/alerts", nil, &a); err != nil {
		return nil, err
	}
	return &a, nil
}
