// Package videofetch is the official Go SDK for the VideoFetch video ingestion
// API: give us a video URL, we deliver the MP4/MP3 to your storage.
//
// Quick start:
//
//	client := videofetch.NewClient("vf_live_sk_...", nil)
//	job, err := client.Downloads.Create(ctx, videofetch.DownloadCreateParams{
//	    URL: "https://www.youtube.com/watch?v=...", Format: "1080p",
//	})
//	if err != nil { log.Fatal(err) }
//	result, err := job.Wait(ctx) // polls until completed/failed
package videofetch

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"strconv"
	"time"
)

const (
	DefaultBaseURL   = "https://api.vidfetch.dev"
	DefaultTimeout   = 30 * time.Second
	DefaultMaxRetry  = 2
	DefaultJobTimout = 2 * time.Minute
)

// Client talks to the VideoFetch API. Create with NewClient.
type Client struct {
	apiKey     string
	baseURL    string
	httpClient *http.Client
	maxRetries int

	Downloads *DownloadsService
	Info      *InfoService
}

// ClientOptions tune the client. Zero values fall back to defaults.
type ClientOptions struct {
	BaseURL    string
	HTTPClient *http.Client
	Timeout    time.Duration
	MaxRetries int
}

// NewClient creates a VideoFetch API client. apiKey is required (vf_live_sk_...).
func NewClient(apiKey string, opts *ClientOptions) *Client {
	if apiKey == "" {
		apiKey = os.Getenv("VIDEOFETCH_API_KEY")
	}
	if apiKey == "" {
		panic("videofetch: no API key provided (pass apiKey or set VIDEOFETCH_API_KEY)")
	}
	o := ClientOptions{}
	if opts != nil {
		o = *opts
	}
	base := o.BaseURL
	if base == "" {
		base = os.Getenv("VIDEOFETCH_BASE_URL")
	}
	if base == "" {
		base = DefaultBaseURL
	}
	timeout := o.Timeout
	if timeout == 0 {
		timeout = DefaultTimeout
	}
	hc := o.HTTPClient
	if hc == nil {
		hc = &http.Client{Timeout: timeout}
	}
	retries := o.MaxRetries
	if retries == 0 {
		retries = DefaultMaxRetry
	}
	c := &Client{apiKey: apiKey, baseURL: base, httpClient: hc, maxRetries: retries}
	c.Downloads = &DownloadsService{client: c}
	c.Info = &InfoService{client: c}
	return c
}

// APIError mirrors the server error contract {detail: {code, message, param}}.
type APIError struct {
	StatusCode int
	Code       string `json:"code"`
	Message    string `json:"message"`
	Param      string `json:"param"`
	RawBody    string
}

func (e *APIError) Error() string {
	if e.Code != "" || e.Param != "" {
		return fmt.Sprintf("videofetch: %s (code=%s param=%s)", e.Message, e.Code, e.Param)
	}
	return fmt.Sprintf("videofetch: HTTP %d: %s", e.StatusCode, e.Message)
}

// QuotaExceededError is returned when the monthly quota is exhausted (HTTP 402).
type QuotaExceededError struct{ APIError }

// JobFailedError is returned by Wait when the job reached a failed terminal
// state. Failed downloads are never charged.
type JobFailedError struct {
	JobID        string
	ErrorCode    string
	ErrorMessage string
}

func (e *JobFailedError) Error() string {
	return fmt.Sprintf("videofetch: download job %s failed [%s]: %s",
		e.JobID, e.ErrorCode, e.ErrorMessage)
}

// request performs an HTTP call with retry on 429/5xx/network errors.
func (c *Client) request(ctx context.Context, method, path string, body any, out any) error {
	var raw []byte
	var err error
	if body != nil {
		raw, err = json.Marshal(body)
		if err != nil {
			return err
		}
	}

	var lastErr error
	for attempt := 0; attempt <= c.maxRetries; attempt++ {
		var req *http.Request
		if raw != nil {
			req, err = http.NewRequestWithContext(ctx, method, c.baseURL+path, bytes.NewReader(raw))
		} else {
			req, err = http.NewRequestWithContext(ctx, method, c.baseURL+path, nil)
		}
		if err != nil {
			return err
		}
		req.Header.Set("Authorization", "Bearer "+c.apiKey)
		req.Header.Set("Content-Type", "application/json")
		req.Header.Set("User-Agent", "videofetch-go/0.1.0")

		resp, err := c.httpClient.Do(req)
		if err != nil {
			lastErr = err
			if attempt < c.maxRetries {
				time.Sleep(retryDelay(attempt))
				continue
			}
			return fmt.Errorf("videofetch: network error calling %s %s: %w", method, path, err)
		}
		bodyBytes, readErr := io.ReadAll(resp.Body)
		resp.Body.Close()
		if readErr != nil {
			return readErr
		}

		if resp.StatusCode == http.StatusTooManyRequests || resp.StatusCode >= 500 {
			if attempt < c.maxRetries {
				time.Sleep(retryDelay(attempt))
				continue
			}
		}

		if resp.StatusCode >= 400 {
			return mapError(resp.StatusCode, bodyBytes)
		}
		if len(bodyBytes) == 0 || out == nil {
			return nil
		}
		return json.Unmarshal(bodyBytes, out)
	}
	return lastErr
}

func mapError(status int, body []byte) error {
	apiErr := &APIError{StatusCode: status, RawBody: string(body)}
	// Server wraps business errors in {"detail": {...}}
	var wrapped struct {
		Detail json.RawMessage `json:"detail"`
	}
	if json.Unmarshal(body, &wrapped) == nil && len(wrapped.Detail) > 0 && wrapped.Detail[0] != '"' {
		var d struct {
			Code    string `json:"code"`
			Message string `json:"message"`
			Param   string `json:"param"`
		}
		if json.Unmarshal(wrapped.Detail, &d) == nil {
			apiErr.Code, apiErr.Message, apiErr.Param = d.Code, d.Message, d.Param
		}
	} else {
		var plain struct {
			Code    string `json:"code"`
			Message string `json:"message"`
		}
		if json.Unmarshal(body, &plain) == nil && plain.Message != "" {
			apiErr.Code, apiErr.Message = plain.Code, plain.Message
		}
	}
	if apiErr.Message == "" {
		apiErr.Message = fmt.Sprintf("unexpected HTTP %d", status)
	}
	if status == http.StatusPaymentRequired {
		return &QuotaExceededError{APIError: *apiErr}
	}
	return apiErr
}

func retryDelay(attempt int) time.Duration {
	// Fibonacci-ish: 2s, 3s, 5s, 8s, 13s, cap 30s + 20% jitter
	fib := []int{2, 3, 5, 8, 13, 21, 30}
	sec := fib[min(attempt, len(fib)-1)]
	return time.Duration(sec) * time.Second
}

func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}

func queryParams(v url.Values) string {
	if len(v) == 0 {
		return ""
	}
	return "?" + v.Encode()
}

func atoi(s string) int {
	n, _ := strconv.Atoi(s)
	return n
}
