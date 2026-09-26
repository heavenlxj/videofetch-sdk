package videofetch

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strings"
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

// DestinationSpec says where the finished file goes. A nil Destination uses the account's
// default storage connection, or the platform (presigned DownloadURL) when none is set.
//
// Saved connection — set ID ("st_…", see StorageID) only. The server reads the provider,
// bucket and credentials from the connection, so Type is ignored whenever ID is set and
// should be left empty. Path or Key override the object key for this job only.
//
// Platform — Type "url" (see PlatformURL) forces platform delivery even when a default
// connection is set.
//
// Inline credentials — set Type ("s3"|"r2"|"gcs"|"s3_compatible") along with Bucket,
// AccessKeyID and SecretAccessKey. They are used for this job only unless Save is true,
// which keeps them as a connection named Name (an identical existing one is reused).
//
// Path is an object key prefix (default "youtube/{video_id}/"); Key is a full key template
// that takes precedence and also accepts {ext}. Variables: {video_id} {job_id} {format} {date}.
type DestinationSpec struct {
	Type            string `json:"type,omitempty"` // omit for a saved ID; required for inline credentials
	ID              string `json:"id,omitempty"`
	Bucket          string `json:"bucket,omitempty"`
	Endpoint        string `json:"endpoint,omitempty"` // required for r2 and s3_compatible
	Region          string `json:"region,omitempty"`
	Path            string `json:"path,omitempty"`
	Key             string `json:"key,omitempty"`
	AccessKeyID     string `json:"access_key_id,omitempty"`
	SecretAccessKey string `json:"secret_access_key,omitempty"`
	Save            bool   `json:"save,omitempty"` // inline only: keep as a saved connection
	Name            string `json:"name,omitempty"` // inline only: name of the saved connection
}

// StorageID targets a saved storage connection by its "st_…" id.
func StorageID(id string) *DestinationSpec { return &DestinationSpec{ID: id} }

// PlatformURL forces platform delivery (presigned DownloadURL) even when a default
// storage connection is configured.
func PlatformURL() *DestinationSpec { return &DestinationSpec{Type: "url"} }

// Delivery says where the finished file went (Download.Delivery).
//
// Type "url": the platform keeps it and DownloadURL is set. Type "storage": it was written
// to your bucket (URI/Bucket/Key). Status "failed" with Redeliverable true means the file is
// held until HoldExpiresAt and Downloads.Redeliver can retry without re-downloading.
type Delivery struct {
	Type          string  `json:"type"`   // url | storage
	Status        string  `json:"status"` // pending | delivered | failed
	DestinationID *string `json:"destination_id"`
	Ephemeral     bool    `json:"ephemeral"`
	Provider      *string `json:"provider"`
	Bucket        *string `json:"bucket"`
	Key           *string `json:"key"`
	URI           *string `json:"uri"` // s3:// · gs:// · r2://
	ETag          *string `json:"etag"`
	SizeBytes     *int64  `json:"size_bytes"`
	Attempts      *int    `json:"attempts"`
	DeliveredAt   *string `json:"delivered_at"`
	Redeliverable bool    `json:"redeliverable"`
	HoldExpiresAt *string `json:"hold_expires_at"`
}

// DownloadError is the structured failure reason (Download.Error).
type DownloadError struct {
	Code         string  `json:"code"`
	Message      *string `json:"message"`
	Stage        *string `json:"stage"` // fetch | process | billing | delivery
	Retryable    *bool   `json:"retryable"`
	ProviderCode *string `json:"provider_code"` // raw storage error, e.g. AccessDenied
	Hint         *string `json:"hint"`
}

// DownloadAttempt is one recorded download attempt (fail-not-charged evidence).
type DownloadAttempt struct {
	AttemptNo int    `json:"attempt_no"`
	Strategy  string `json:"strategy"`
	// Egress is a neutral relay label ("relay") or nil for a direct attempt. Internal
	// egress hosts are never exposed by the API.
	Egress       *string `json:"egress"`
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
	DestinationID        *string           `json:"destination_id"`
	Delivery             *Delivery         `json:"delivery"`
	Error                *DownloadError    `json:"error"`
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
	// Queue telemetry. Only set while Status == StatusQueued; nil in every other
	// state (the API serialises them as null).
	QueuePosition        *int `json:"queue_position"`
	AheadOfYou           *int `json:"ahead_of_you"`
	EstimatedWaitSeconds *int `json:"estimated_wait_seconds"`
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
	Event         string         `json:"event"`
	ID            string         `json:"id"`
	Status        DownloadStatus `json:"status"`
	Format        DownloadFormat `json:"format"`
	FileSize      *int64         `json:"file_size"`
	Duration      *float64       `json:"duration"`
	DownloadURL   *string        `json:"download_url"`
	Destination   string         `json:"destination"`
	DestinationID *string        `json:"destination_id"`
	StorageKey    *string        `json:"storage_key"`
	Delivery      *Delivery      `json:"delivery"`
	Error         *DownloadError `json:"error"`
	CostUSD       float64        `json:"cost_usd"`
	CreatedAt     *string        `json:"created_at"`
	CompletedAt   *string        `json:"completed_at"`
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

// Redeliver retries the upload of a job that failed at delivery, from the held copy.
// Pass nil to reuse the job's original destination. Nothing is downloaded or charged
// again. Returns *ConflictError (code "not_redeliverable") when the job did not fail at
// delivery or the hold (Delivery.HoldExpiresAt) has expired.
func (s *DownloadsService) Redeliver(ctx context.Context, id string, dest *DestinationSpec) (*Job, error) {
	body := struct {
		Destination *DestinationSpec `json:"destination,omitempty"`
	}{dest}
	var dl Download
	if err := s.client.request(ctx, "POST", "/v1/downloads/"+url.PathEscape(id)+"/redeliver", body, &dl); err != nil {
		return nil, err
	}
	return &Job{client: s.client, current: &dl}, nil
}

// CreateAndWait is the L3 one-shot: create + poll until terminal.
func (s *DownloadsService) CreateAndWait(ctx context.Context, p DownloadCreateParams, timeout time.Duration) (*Download, error) {
	job, err := s.Create(ctx, p)
	if err != nil {
		return nil, err
	}
	return job.Wait(ctx, timeout)
}

// DownloadTo streams the finished artifact of a completed job to a local file
// and returns the absolute path it was written to.
//
// The job must already be completed; otherwise a *JobNotCompletedError is
// returned. The file is fetched from the platform-issued, self-authorising
// DownloadURL — no API key is sent to it — and copied to disk in chunks (the
// file is never held in memory).
//
// path selects the destination:
//
//   - "" (or a path that is an existing directory, or ends with a path
//     separator) writes <sanitized Title or id><ext> inside that directory,
//     where ext is .mp3 for FormatMP3 and .mp4 otherwise. path == "" means the
//     current working directory.
//   - anything else is used verbatim as the file path.
//
// If the signed link has expired the download answers 403; the job is then
// re-fetched (the server re-issues the link) and the download is retried once.
// A second failure is returned to the caller.
func (s *DownloadsService) DownloadTo(ctx context.Context, id string, path string) (string, error) {
	dl, err := s.Retrieve(ctx, id)
	if err != nil {
		return "", err
	}
	if dl.Status != StatusCompleted {
		return "", &JobNotCompletedError{JobID: dl.ID, Status: dl.Status}
	}
	if dl.DownloadURL == nil || *dl.DownloadURL == "" {
		return "", fmt.Errorf("videofetch: download job %s is completed but has no download_url to fetch", dl.ID)
	}

	target := downloadTargetPath(path, dl, id)

	err = s.client.fetchToFile(ctx, *dl.DownloadURL, target)
	if errors.Is(err, errLinkExpired) {
		// The link expired; re-fetch the job so the server issues a fresh one.
		refreshed, rerr := s.Retrieve(ctx, id)
		if rerr != nil {
			return "", rerr
		}
		if refreshed.DownloadURL == nil || *refreshed.DownloadURL == "" {
			return "", fmt.Errorf("videofetch: download job %s has no download_url after refresh", id)
		}
		err = s.client.fetchToFile(ctx, *refreshed.DownloadURL, target)
	}
	if err != nil {
		return "", err
	}

	abs, err := filepath.Abs(target)
	if err != nil {
		return target, nil
	}
	return abs, nil
}

// errLinkExpired marks a 403 from a direct download link so DownloadTo can
// refresh the job (and its freshly signed link) and retry once.
var errLinkExpired = errors.New("videofetch: download link rejected (expired)")

// fetchToFile streams link into target in chunks. No Authorization header is
// sent: direct links are self-authorising.
func (c *Client) fetchToFile(ctx context.Context, link, target string) error {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, link, nil)
	if err != nil {
		return err
	}
	req.Header.Set("User-Agent", "videofetch-go/0.5.0")

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return fmt.Errorf("videofetch: network error fetching download link: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode == http.StatusForbidden {
		return errLinkExpired
	}
	if resp.StatusCode >= 400 {
		return fmt.Errorf("videofetch: download link returned HTTP %d", resp.StatusCode)
	}

	f, err := os.Create(target)
	if err != nil {
		return err
	}
	if _, err := io.Copy(f, resp.Body); err != nil {
		f.Close()
		os.Remove(target)
		return err
	}
	if err := f.Close(); err != nil {
		os.Remove(target)
		return err
	}
	return nil
}

// maxFilenameLen caps a derived file name (in runes) to a filesystem-friendly size.
const maxFilenameLen = 80

// downloadTargetPath resolves the destination file for DownloadTo. When path
// names a directory ("", existing dir or a trailing separator) the default name
// <sanitized Title or id><ext> is placed inside it; otherwise path is verbatim.
func downloadTargetPath(path string, dl *Download, id string) string {
	ext := ".mp4"
	if dl.Format == FormatMP3 {
		ext = ".mp3"
	}
	name := ""
	if dl.Title != nil {
		name = sanitizeFilename(*dl.Title)
	}
	if name == "" {
		name = sanitizeFilename(id)
	}
	if name == "" {
		name = "download"
	}
	defaultName := name + ext

	if path == "" {
		return defaultName
	}
	if strings.HasSuffix(path, "/") || strings.HasSuffix(path, string(os.PathSeparator)) {
		return filepath.Join(path, defaultName)
	}
	if info, err := os.Stat(path); err == nil && info.IsDir() {
		return filepath.Join(path, defaultName)
	}
	return path
}

// sanitizeFilename turns a title or id into a single safe path segment: path
// separators and control characters are dropped, leading/trailing whitespace
// and dots are trimmed and the result is capped at maxFilenameLen runes.
func sanitizeFilename(s string) string {
	var b strings.Builder
	for _, r := range s {
		if r == '/' || r == '\\' || r < 0x20 || r == 0x7f {
			continue
		}
		b.WriteRune(r)
	}
	name := strings.Trim(strings.TrimSpace(b.String()), ".")
	name = strings.TrimSpace(name)
	if runes := []rune(name); len(runes) > maxFilenameLen {
		name = strings.TrimRight(strings.TrimSpace(string(runes[:maxFilenameLen])), ".")
	}
	return name
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
//   - A failed job returns *JobFailedError (failed downloads are never charged);
//     errors.Is(err, ErrDeliveryFailed) matches a failed upload to your storage.
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
		e := &JobFailedError{JobID: dl.ID, ErrorCode: code, ErrorMessage: msg, Download: dl}
		if d := dl.Error; d != nil {
			e.Retryable = d.Retryable
			if d.Stage != nil {
				e.Stage = *d.Stage
			}
			if d.Hint != nil {
				e.Hint = *d.Hint
			}
			if d.ProviderCode != nil {
				e.ProviderCode = *d.ProviderCode
			}
		}
		return e
	}
	return nil
}

func pollDelay(attempt int) time.Duration {
	fib := []int{2, 3, 5, 8, 13, 21, 30}
	sec := fib[min(attempt, len(fib)-1)]
	return time.Duration(sec) * time.Second
}

var _ = json.Marshal // keep encoding/json imported for future model helpers
