package videofetch

import (
	"context"
	"encoding/json"
	"fmt"
	"net/url"
	"time"
)

// Types mirroring the VideoFetch API contract (openapi/openapi.json).

type DownloadFormat string

const (
	Format144p  DownloadFormat = "144p"
	Format240p  DownloadFormat = "240p"
	Format360p  DownloadFormat = "360p"
	Format480p  DownloadFormat = "480p"
	Format720p  DownloadFormat = "720p"
	Format1080p DownloadFormat = "1080p"
	Format1440p DownloadFormat = "1440p"
	Format2160p DownloadFormat = "2160p"
	FormatMP3   DownloadFormat = "mp3"
)

type DownloadStatus string

const (
	StatusQueued     DownloadStatus = "queued"
	StatusProcessing DownloadStatus = "processing"
	StatusCompleted  DownloadStatus = "completed"
	StatusFailed     DownloadStatus = "failed"
	StatusDeleted    DownloadStatus = "deleted"
)

func (s DownloadStatus) terminal() bool {
	return s == StatusCompleted || s == StatusFailed || s == StatusDeleted
}

// TrimSpec is an optional clip window in seconds (float ok).
type TrimSpec struct {
	Start *float64 `json:"start,omitempty"`
	End   *float64 `json:"end,omitempty"`
}

// DestinationSpec references a saved storage connection or inline credentials.
type DestinationSpec struct {
	Type            string `json:"type"` // url|s3|r2|gcs|s3_compatible
	ID              string `json:"id,omitempty"`
	Bucket          string `json:"bucket,omitempty"`
	Endpoint        string `json:"endpoint,omitempty"`
	Region          string `json:"region,omitempty"`
	Path            string `json:"path,omitempty"`
	AccessKeyID     string `json:"access_key_id,omitempty"`
	SecretAccessKey string `json:"secret_access_key,omitempty"`
}

// DownloadAttempt is one recorded download attempt (fail-not-charged evidence).
type DownloadAttempt struct {
	AttemptNo    int     `json:"attempt_no"`
	Strategy     string  `json:"strategy"`
	ProxyHost    *string `json:"proxy_host"`
	Result       string  `json:"result"`
	ErrorCode    *string `json:"error_code"`
	ErrorMessage *string `json:"error_message"`
	LatencyMS    *int    `json:"latency_ms"`
	StartedAt    *string `json:"started_at"`
	FinishedAt   *string `json:"finished_at"`
}

// Download is a download job (dl_xxx). Mirrors GET /v1/downloads/{id}.
type Download struct {
	ID                   string            `json:"id"`
	Status               DownloadStatus    `json:"status"`
	URL                  string            `json:"url"`
	Format               DownloadFormat    `json:"format"`
	Progress             int               `json:"progress"`
	Title                *string           `json:"title"`
	VideoID              *string           `json:"video_id"`
	Channel              *string           `json:"channel"`
	UploadDate           *string           `json:"upload_date"`
	Thumbnail            *string           `json:"thumbnail"`
	DurationSeconds      *float64          `json:"duration_seconds"`
	SizeBytes            *int64            `json:"size_bytes"`
	Trim                 *TrimSpec         `json:"trim"`
	DestinationType      *string           `json:"destination_type"`
	DownloadURL          *string           `json:"download_url"`
	DownloadURLExpiresAt *string           `json:"download_url_expires_at"`
	StorageKey           *string           `json:"storage_key"`
	ProcessingTimeMS     *int64            `json:"processing_time_ms"`
	CostUSD              float64           `json:"cost_usd"`
	Attempts             int               `json:"attempts"`
	Strategy             *string           `json:"strategy"`
	ErrorCode            *string           `json:"error_code"`
	ErrorMessage         *string           `json:"error_message"`
	CreatedAt            *string           `json:"created_at"`
	CompletedAt          *string           `json:"completed_at"`
	EstimatedBytes       *int64            `json:"estimated_bytes"`
	AttemptDetails       []DownloadAttempt `json:"attempt_details"`
}

// DownloadCreateParams is the POST /v1/downloads body.
type DownloadCreateParams struct {
	URL         string           `json:"url"`
	Format      DownloadFormat   `json:"format"`
	Trim        *TrimSpec        `json:"trim,omitempty"`
	Destination *DestinationSpec `json:"destination,omitempty"`
	WebhookURL  string           `json:"webhook_url,omitempty"`
}

// DownloadList is the GET /v1/downloads response.
type DownloadList struct {
	Items   []Download `json:"items"`
	Total   int        `json:"total"`
	HasMore bool       `json:"has_more"`
}

// DownloadListParams filters GET /v1/downloads.
type DownloadListParams struct {
	Status string
	Q      string
	Limit  int
	Offset int
}

// FormatInfo describes one deliverable quality tier.
type FormatInfo struct {
	Quality   string  `json:"quality"`
	Size      *int64  `json:"size"`
	Container string  `json:"container"`
	Note      *string `json:"note"`
}

// VideoInfo is the POST /v1/info result (free metadata lookup).
type VideoInfo struct {
	ID         *string      `json:"id"`
	URL        string       `json:"url"`
	Title      *string      `json:"title"`
	Duration   *float64     `json:"duration"`
	Thumbnail  *string      `json:"thumbnail"`
	Channel    *string      `json:"channel"`
	UploadDate *string      `json:"upload_date"`
	ViewCount  *int64       `json:"view_count"`
	Formats    []FormatInfo `json:"formats"`
}

// WebhookEvent names (docs/Design contract).
const (
	EventQueued     = "download.queued"
	EventProcessing = "download.processing"
	EventCompleted  = "download.completed"
	EventFailed     = "download.failed"
)

// WebhookPayload is a delivered download.* event.
type WebhookPayload struct {
	Event       string         `json:"event"`
	ID          string         `json:"id"`
	Status      DownloadStatus `json:"status"`
	Format      DownloadFormat `json:"format"`
	FileSize    *int64         `json:"file_size"`
	Duration    *float64       `json:"duration"`
	DownloadURL *string        `json:"download_url"`
	Destination string         `json:"destination"`
	CostUSD     float64        `json:"cost_usd"`
	CreatedAt   *string        `json:"created_at"`
	CompletedAt *string        `json:"completed_at"`
}

// ────────────────────────── Service ──────────────────────────

// DownloadsService provides download job operations. Access via client.Downloads.
type DownloadsService struct{ client *Client }

// Create submits a download job. Returns immediately (status queued).
func (s *DownloadsService) Create(ctx context.Context, p DownloadCreateParams) (*Job, error) {
	if p.Format == "" {
		p.Format = Format720p
	}
	var dl Download
	if err := s.client.request(ctx, "POST", "/v1/downloads", p, &dl); err != nil {
		return nil, err
	}
	return &Job{client: s.client, current: &dl}, nil
}

// Retrieve fetches the current state of a job.
func (s *DownloadsService) Retrieve(ctx context.Context, id string) (*Download, error) {
	var dl Download
	if err := s.client.request(ctx, "GET", "/v1/downloads/"+url.PathEscape(id), nil, &dl); err != nil {
		return nil, err
	}
	return &dl, nil
}

// List returns recent jobs (newest first).
func (s *DownloadsService) List(ctx context.Context, p DownloadListParams) (*DownloadList, error) {
	q := url.Values{}
	if p.Status != "" {
		q.Set("status", p.Status)
	}
	if p.Q != "" {
		q.Set("q", p.Q)
	}
	if p.Limit > 0 {
		q.Set("limit", fmt.Sprintf("%d", p.Limit))
	}
	if p.Offset > 0 {
		q.Set("offset", fmt.Sprintf("%d", p.Offset))
	}
	var out DownloadList
	if err := s.client.request(ctx, "GET", "/v1/downloads"+queryParams(q), nil, &out); err != nil {
		return nil, err
	}
	return &out, nil
}

// Cancel deletes/cancels a job (queued/processing). Safe on any state.
func (s *DownloadsService) Cancel(ctx context.Context, id string) error {
	return s.client.request(ctx, "DELETE", "/v1/downloads/"+url.PathEscape(id), nil, nil)
}

// CreateAndWait is the L3 one-shot: create + poll until terminal.
func (s *DownloadsService) CreateAndWait(ctx context.Context, p DownloadCreateParams, timeout time.Duration) (*Download, error) {
	job, err := s.Create(ctx, p)
	if err != nil {
		return nil, err
	}
	return job.Wait(ctx, timeout)
}

// Job is a polling handle around a queued/processing download.
type Job struct {
	client  *Client
	current *Download
}

// ID returns the dl_xxx job id.
func (j *Job) ID() string { return j.current.ID }

// Status returns the current known status.
func (j *Job) Status() DownloadStatus { return j.current.Status }

// Download returns the latest fetched state.
func (j *Job) Download() *Download { return j.current }

// Refresh fetches the latest state from the API.
func (j *Job) Refresh(ctx context.Context) (*Download, error) {
	dl, err := j.client.Downloads.Retrieve(ctx, j.current.ID)
	if err != nil {
		return nil, err
	}
	j.current = dl
	return dl, nil
}

// Wait polls until the job reaches a terminal state.
//
//   - Network errors never abort; polling continues until ctx is cancelled.
//   - A failed job returns *JobFailedError (failed downloads are never charged).
//   - timeout <= 0 waits forever (until ctx cancellation).
//   - Cancelling ctx only stops local waiting — the server-side job keeps
//     running unless you call Cancel.
//
// Serverless warning: do not call Wait in a Vercel/Cloudflare/Lambda function —
// use webhooks instead.
func (j *Job) Wait(ctx context.Context, timeout time.Duration) (*Download, error) {
	if j.current.Status.terminal() {
		return j.current, raiseIfFailed(j.current)
	}
	var timer *time.Timer
	var timerC <-chan time.Time
	if timeout > 0 {
		timer = time.NewTimer(timeout)
		timerC = timer.C
		defer timer.Stop()
	}

	interval := 2 * time.Second
	attempt := 0
	for {
		select {
		case <-ctx.Done():
			return nil, ctx.Err()
		case <-timerC:
			return nil, fmt.Errorf(
				"videofetch: timed out after %s waiting for job %s (still running server-side; Retrieve it later)",
				timeout, j.current.ID)
		case <-time.After(interval):
		}
		dl, err := j.client.Downloads.Retrieve(ctx, j.current.ID)
		if err != nil {
			attempt++
			interval = pollDelay(attempt)
			continue
		}
		j.current = dl
		if dl.Status.terminal() {
			return dl, raiseIfFailed(dl)
		}
		// successful poll keeps a steady cadence; only errors back off
		interval = 2 * time.Second
		attempt = 0
	}
}

func raiseIfFailed(dl *Download) error {
	if dl.Status == StatusFailed {
		code, msg := "", ""
		if dl.ErrorCode != nil {
			code = *dl.ErrorCode
		}
		if dl.ErrorMessage != nil {
			msg = *dl.ErrorMessage
		}
		return &JobFailedError{JobID: dl.ID, ErrorCode: code, ErrorMessage: msg}
	}
	return nil
}

func pollDelay(attempt int) time.Duration {
	fib := []int{2, 3, 5, 8, 13, 21, 30}
	sec := fib[min(attempt, len(fib)-1)]
	return time.Duration(sec) * time.Second
}

var _ = json.Marshal // keep encoding/json imported for future model helpers
