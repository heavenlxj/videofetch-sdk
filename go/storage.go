package videofetch

import (
	"context"
	"net/url"
)

// StorageConnection is a saved storage connection (GET /v1/storage). Pass ID ("st_…")
// as the job destination with StorageID.
type StorageConnection struct {
	ID              string  `json:"id"`
	Name            string  `json:"name"`
	Provider        string  `json:"provider"` // s3 | r2 | gcs | s3_compatible
	Bucket          string  `json:"bucket"`
	PathPrefix      string  `json:"path_prefix"`
	Endpoint        *string `json:"endpoint"`
	Region          *string `json:"region"`
	AccessKeyMasked *string `json:"access_key_masked"` // the secret is never returned
	IsDefault       bool    `json:"is_default"`
	// Status is "failing" after a permanent delivery error; a successful delivery or
	// test resets it to "active".
	Status          string            `json:"status"`
	LastError       *StorageLastError `json:"last_error"`
	LastUsedAt      *string           `json:"last_used_at"`
	DeliveriesCount int               `json:"deliveries_count"`
	LastTestedAt    *string           `json:"last_tested_at"`
	CreatedAt       string            `json:"created_at"`
	UpdatedAt       *string           `json:"updated_at"`
}

// StorageLastError is the most recent delivery/test failure on a connection.
type StorageLastError struct {
	Code    string  `json:"code"`
	Message *string `json:"message"`
	At      *string `json:"at"`
}

// StorageCreateParams is the POST /v1/storage body. Endpoint is required for r2 and
// s3_compatible; PathPrefix defaults to "youtube/{video_id}/".
type StorageCreateParams struct {
	Provider        string `json:"provider"`
	Bucket          string `json:"bucket"`
	AccessKeyID     string `json:"access_key_id"`
	SecretAccessKey string `json:"secret_access_key"`
	Name            string `json:"name,omitempty"`
	Endpoint        string `json:"endpoint,omitempty"`
	Region          string `json:"region,omitempty"`
	PathPrefix      string `json:"path_prefix,omitempty"`
	IsDefault       bool   `json:"is_default,omitempty"`
}

// StorageUpdateParams is the PUT /v1/storage/{id} body; nil fields are left unchanged.
// Setting both keys rotates the credentials and resets Status.
type StorageUpdateParams struct {
	Name            *string `json:"name,omitempty"`
	Endpoint        *string `json:"endpoint,omitempty"`
	Region          *string `json:"region,omitempty"`
	PathPrefix      *string `json:"path_prefix,omitempty"`
	AccessKeyID     *string `json:"access_key_id,omitempty"`
	SecretAccessKey *string `json:"secret_access_key,omitempty"`
	IsDefault       *bool   `json:"is_default,omitempty"`
}

// StorageTestParams probes unsaved credentials (POST /v1/storage/test).
type StorageTestParams struct {
	Provider        string `json:"provider"`
	Bucket          string `json:"bucket"`
	AccessKeyID     string `json:"access_key_id"`
	SecretAccessKey string `json:"secret_access_key"`
	Endpoint        string `json:"endpoint,omitempty"`
	Region          string `json:"region,omitempty"`
	PathPrefix      string `json:"path_prefix,omitempty"`
}

// StorageTestStep is one probe step: connect, write or cleanup. A cleanup failure is
// only a Warning — delivery needs PutObject alone.
type StorageTestStep struct {
	Name    string  `json:"name"`
	OK      bool    `json:"ok"`
	Warning bool    `json:"warning"`
	Code    *string `json:"code"`
	Message *string `json:"message"`
}

// StorageTestResult is a probe outcome. A failed probe is OK=false with a storage_* Code,
// not an error; only a malformed config returns *StorageError.
type StorageTestResult struct {
	OK           bool              `json:"ok"`
	Code         *string           `json:"code"`
	Message      string            `json:"message"`
	Hint         *string           `json:"hint"`
	ProviderCode *string           `json:"provider_code"`
	ProbeKey     *string           `json:"probe_key"`
	Steps        []StorageTestStep `json:"steps"`
}

// StorageService manages saved storage connections. Access via client.Storage.
type StorageService struct{ client *Client }

func storagePath(id string) string { return "/v1/storage/" + url.PathEscape(id) }

// List returns saved connections, default first.
func (s *StorageService) List(ctx context.Context) ([]StorageConnection, error) {
	var out struct {
		Items []StorageConnection `json:"items"`
	}
	if err := s.client.request(ctx, "GET", "/v1/storage", nil, &out); err != nil {
		return nil, err
	}
	return out.Items, nil
}

// Retrieve fetches one connection by "st_…" id.
func (s *StorageService) Retrieve(ctx context.Context, id string) (*StorageConnection, error) {
	var out StorageConnection
	if err := s.client.request(ctx, "GET", storagePath(id), nil, &out); err != nil {
		return nil, err
	}
	return &out, nil
}

// Create saves a connection. The config is validated (*StorageError) but not probed —
// call Test first to check reachability and write permission.
func (s *StorageService) Create(ctx context.Context, p StorageCreateParams) (*StorageConnection, error) {
	var out StorageConnection
	if err := s.client.request(ctx, "POST", "/v1/storage", p, &out); err != nil {
		return nil, err
	}
	return &out, nil
}

// Update changes the given fields of a connection.
func (s *StorageService) Update(ctx context.Context, id string, p StorageUpdateParams) (*StorageConnection, error) {
	var out StorageConnection
	if err := s.client.request(ctx, "PUT", storagePath(id), p, &out); err != nil {
		return nil, err
	}
	return &out, nil
}

// Delete removes a connection. While queued/processing jobs target it the server returns
// *ConflictError (code "storage_in_use") unless force is true.
func (s *StorageService) Delete(ctx context.Context, id string, force bool) error {
	path := storagePath(id)
	if force {
		path += "?force=true"
	}
	return s.client.request(ctx, "DELETE", path, nil, nil)
}

// Test probes unsaved credentials by writing and removing a small object.
func (s *StorageService) Test(ctx context.Context, p StorageTestParams) (*StorageTestResult, error) {
	var out StorageTestResult
	if err := s.client.request(ctx, "POST", "/v1/storage/test", p, &out); err != nil {
		return nil, err
	}
	return &out, nil
}

// TestSaved probes a saved connection and updates its Status / LastError.
func (s *StorageService) TestSaved(ctx context.Context, id string) (*StorageTestResult, error) {
	var out StorageTestResult
	if err := s.client.request(ctx, "POST", storagePath(id)+"/test", nil, &out); err != nil {
		return nil, err
	}
	return &out, nil
}
