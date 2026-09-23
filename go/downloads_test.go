package videofetch

import (
	"bytes"
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// chdirTemp switches the working directory to a fresh temp dir for the duration
// of the test so default-name downloads do not litter the package directory.
func chdirTemp(t *testing.T) string {
	t.Helper()
	dir := t.TempDir()
	old, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	if err := os.Chdir(dir); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = os.Chdir(old) })
	return dir
}

// completedJob builds a completed GET /v1/downloads/{id} fixture.
func completedJob(downloadURL string) map[string]any {
	return downloadJSON("completed", map[string]any{
		"progress": 100, "download_url": downloadURL, "size_bytes": 123,
	})
}

func TestDownloadToWritesBytesAndReturnsPath(t *testing.T) {
	payload := bytes.Repeat([]byte("videofetch-"), 512) // > a few KB, chunked copy
	var authHeaders []string
	storage := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		authHeaders = append(authHeaders, r.Header.Get("Authorization"))
		_, _ = w.Write(payload)
	}))
	defer storage.Close()

	api := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/v1/downloads/dl_abc123" {
			t.Fatalf("unexpected path %s", r.URL.Path)
		}
		writeJSON(t, w, 200, completedJob(storage.URL+"/artifact.mp4"))
	}))
	defer api.Close()

	dst := filepath.Join(t.TempDir(), "nested", "out.mp4")
	if err := os.MkdirAll(filepath.Dir(dst), 0o755); err != nil {
		t.Fatal(err)
	}
	got, err := testClient(t, api).Downloads.DownloadTo(context.Background(), "dl_abc123", dst)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !filepath.IsAbs(got) {
		t.Fatalf("returned path %q is not absolute", got)
	}
	if got != filepath.Clean(dst) {
		t.Fatalf("returned path = %q, want %q", got, filepath.Clean(dst))
	}
	onDisk, err := os.ReadFile(got)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(onDisk, payload) {
		t.Fatalf("file contents differ: got %d bytes, want %d", len(onDisk), len(payload))
	}
	for _, a := range authHeaders {
		if a != "" {
			t.Fatalf("storage request carried Authorization header %q", a)
		}
	}
}

func TestDownloadToDefaultFilename(t *testing.T) {
	dir := chdirTemp(t)
	payload := []byte("bytes")
	storage := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write(payload)
	}))
	defer storage.Close()

	api := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		job := completedJob(storage.URL + "/v.mp4")
		job["title"] = "  Video / 01: intro. "
		job["format"] = "1080p"
		writeJSON(t, w, 200, job)
	}))
	defer api.Close()

	got, err := testClient(t, api).Downloads.DownloadTo(context.Background(), "dl_abc123", "")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !filepath.IsAbs(got) {
		t.Fatalf("returned path %q is not absolute", got)
	}
	if base := filepath.Base(got); base != "Video  01: intro.mp4" {
		t.Fatalf("default file name = %q, want %q", base, "Video  01: intro.mp4")
	}
	if onDisk, err := os.ReadFile(got); err != nil || !bytes.Equal(onDisk, payload) {
		t.Fatalf("default-named file not written correctly in %s: %v", dir, err)
	}
}

func TestDownloadToDefaultNameMP3AndIDFallback(t *testing.T) {
	chdirTemp(t)
	storage := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte("audio"))
	}))
	defer storage.Close()

	api := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		job := completedJob(storage.URL + "/a.mp3")
		job["title"] = nil // no title → fall back to the job id
		job["format"] = "mp3"
		writeJSON(t, w, 200, job)
	}))
	defer api.Close()

	got, err := testClient(t, api).Downloads.DownloadTo(context.Background(), "dl_abc123", "")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if base := filepath.Base(got); base != "dl_abc123.mp3" {
		t.Fatalf("default file name = %q, want %q", base, "dl_abc123.mp3")
	}
}

func TestDownloadToDirectoryPath(t *testing.T) {
	payload := []byte("in-a-dir")
	storage := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write(payload)
	}))
	defer storage.Close()

	api := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		job := completedJob(storage.URL + "/v.mp4")
		job["title"] = "My Clip"
		writeJSON(t, w, 200, job)
	}))
	defer api.Close()

	dir := t.TempDir()
	client := testClient(t, api)

	// Existing directory (no trailing separator).
	got, err := client.Downloads.DownloadTo(context.Background(), "dl_abc123", dir)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if filepath.Dir(got) != filepath.Clean(dir) || filepath.Base(got) != "My Clip.mp4" {
		t.Fatalf("path = %q, want %q inside %q", got, "My Clip.mp4", dir)
	}
	if onDisk, err := os.ReadFile(got); err != nil || !bytes.Equal(onDisk, payload) {
		t.Fatalf("file inside dir not written: %v", err)
	}

	// Trailing path separator into an existing directory.
	sub := filepath.Join(dir, "sub") + string(os.PathSeparator)
	if err := os.MkdirAll(sub, 0o755); err != nil {
		t.Fatal(err)
	}
	got2, err := client.Downloads.DownloadTo(context.Background(), "dl_abc123", sub)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if filepath.Dir(got2) != filepath.Clean(strings.TrimSuffix(sub, string(os.PathSeparator))) {
		t.Fatalf("path = %q not inside trailing-separator dir %q", got2, sub)
	}
	if filepath.Base(got2) != "My Clip.mp4" {
		t.Fatalf("base = %q, want %q", filepath.Base(got2), "My Clip.mp4")
	}
}

func TestDownloadToJobNotCompleted(t *testing.T) {
	storage := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		t.Fatalf("storage must not be fetched for a non-completed job")
	}))
	defer storage.Close()

	api := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		writeJSON(t, w, 200, downloadJSON("processing", map[string]any{
			"progress": 40, "download_url": storage.URL + "/v.mp4",
		}))
	}))
	defer api.Close()

	_, err := testClient(t, api).Downloads.DownloadTo(
		context.Background(), "dl_abc123", filepath.Join(t.TempDir(), "out.mp4"))
	var notCompleted *JobNotCompletedError
	if !errors.As(err, &notCompleted) {
		t.Fatalf("want *JobNotCompletedError, got %T: %v", err, err)
	}
	if notCompleted.Status != StatusProcessing {
		t.Fatalf("status = %q, want %q", notCompleted.Status, StatusProcessing)
	}
	if !errors.Is(err, ErrJobNotCompleted) {
		t.Fatalf("error %v does not wrap ErrJobNotCompleted", err)
	}
	if !strings.Contains(err.Error(), "wait for completion") || !strings.Contains(err.Error(), "processing") {
		t.Fatalf("message %q must mention the status and waiting for completion", err.Error())
	}
}

func TestDownloadToMissingDownloadURL(t *testing.T) {
	api := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		job := completedJob("")
		job["download_url"] = nil
		writeJSON(t, w, 200, job)
	}))
	defer api.Close()

	_, err := testClient(t, api).Downloads.DownloadTo(
		context.Background(), "dl_abc123", filepath.Join(t.TempDir(), "out.mp4"))
	if err == nil || !strings.Contains(err.Error(), "no download_url") {
		t.Fatalf("want a missing download_url error, got %v", err)
	}
}

func TestDownloadToRefreshesExpiredLinkAndRetries(t *testing.T) {
	payload := []byte("fresh-bytes")
	var storageAuth []string
	storageCalls := 0
	storage := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		storageCalls++
		storageAuth = append(storageAuth, r.Header.Get("Authorization"))
		if storageCalls == 1 {
			w.WriteHeader(http.StatusForbidden) // stale/expired signed link
			return
		}
		_, _ = w.Write(payload)
	}))
	defer storage.Close()

	apiCalls := 0
	api := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		apiCalls++
		// The first job carries the stale link; the refreshed job (after the
		// 403) carries the freshly issued one.
		if apiCalls == 1 {
			writeJSON(t, w, 200, completedJob(storage.URL+"/stale.mp4"))
			return
		}
		writeJSON(t, w, 200, completedJob(storage.URL+"/fresh.mp4"))
	}))
	defer api.Close()

	dst := filepath.Join(t.TempDir(), "out.mp4")
	got, err := testClient(t, api).Downloads.DownloadTo(context.Background(), "dl_abc123", dst)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got != filepath.Clean(dst) {
		t.Fatalf("path = %q, want %q", got, filepath.Clean(dst))
	}
	if onDisk, err := os.ReadFile(got); err != nil || !bytes.Equal(onDisk, payload) {
		t.Fatalf("retried download not written: %v", err)
	}
	if apiCalls != 2 {
		t.Fatalf("API Get calls = %d, want 2 (initial + refresh)", apiCalls)
	}
	if storageCalls != 2 {
		t.Fatalf("storage calls = %d, want 2 (stale then fresh)", storageCalls)
	}
	for _, a := range storageAuth {
		if a != "" {
			t.Fatalf("storage request carried Authorization header %q", a)
		}
	}
}
