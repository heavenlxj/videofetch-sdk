package videofetch

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"testing"
)

type seenReq struct {
	Method, Path, Query string
	Body                map[string]any
}

func recordingServer(t *testing.T, respond func(r seenReq) (int, any)) (*httptest.Server, *[]seenReq) {
	t.Helper()
	var seen []seenReq
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		b, _ := io.ReadAll(r.Body)
		req := seenReq{Method: r.Method, Path: r.URL.Path, Query: r.URL.RawQuery}
		if len(b) > 0 {
			if err := json.Unmarshal(b, &req.Body); err != nil {
				t.Fatalf("bad body %s: %v", b, err)
			}
		}
		seen = append(seen, req)
		status, body := respond(req)
		if body == nil {
			w.WriteHeader(status)
			return
		}
		writeJSON(t, w, status, body)
	}))
	t.Cleanup(srv.Close)
	return srv, &seen
}

var connJSON = map[string]any{
	"id": "st_9f1c2a34b5d6e7f8", "name": "Prod", "provider": "s3", "bucket": "acme-media",
	"path_prefix": "youtube/{video_id}/", "is_default": true, "status": "failing",
	"deliveries_count": 4, "created_at": "2026-09-01T00:00:00Z",
	"last_error": map[string]any{"code": "storage_permission_denied", "message": "denied"},
}

func TestStorageIDAndPlatformURLHelpers(t *testing.T) {
	body := captureCreateBody(t, DownloadCreateParams{URL: "https://youtu.be/x", Destination: StorageID("st_abc")})
	if d := destinationOf(t, body); len(d) != 1 || d["id"] != "st_abc" {
		t.Fatalf("StorageID sent %v", d)
	}
	body = captureCreateBody(t, DownloadCreateParams{URL: "https://youtu.be/x", Destination: PlatformURL()})
	if d := destinationOf(t, body); len(d) != 1 || d["type"] != "url" {
		t.Fatalf("PlatformURL sent %v", d)
	}
}

func TestDestinationKeyOverrideAndSave(t *testing.T) {
	body := captureCreateBody(t, DownloadCreateParams{URL: "https://youtu.be/x", Destination: &DestinationSpec{
		ID: "st_abc", Key: "clips/{video_id}.{ext}",
	}})
	if d := destinationOf(t, body); d["key"] != "clips/{video_id}.{ext}" || d["save"] != nil {
		t.Fatalf("key override sent %v", d)
	}
	body = captureCreateBody(t, DownloadCreateParams{URL: "https://youtu.be/x", Destination: &DestinationSpec{
		Type: "r2", Bucket: "b", Endpoint: "https://a.r2.cloudflarestorage.com",
		AccessKeyID: "k", SecretAccessKey: "s", Save: true, Name: "R2",
	}})
	if d := destinationOf(t, body); d["save"] != true || d["name"] != "R2" {
		t.Fatalf("inline save sent %v", d)
	}
}

func TestStorage422MapsToStorageError(t *testing.T) {
	srv, _ := recordingServer(t, func(seenReq) (int, any) {
		return 422, map[string]any{"detail": map[string]any{
			"code": "storage_not_found", "message": "no such connection",
			"hint": "List connections with GET /v1/storage", "param": "destination.id"}}
	})
	_, err := testClient(t, srv).Downloads.Create(context.Background(),
		DownloadCreateParams{URL: "https://youtu.be/x", Destination: StorageID("st_nope")})
	var se *StorageError
	if !errors.As(err, &se) {
		t.Fatalf("want *StorageError, got %T %v", err, err)
	}
	if se.Code != "storage_not_found" || se.Param != "destination.id" || se.Hint == "" {
		t.Fatalf("bad StorageError %+v", se)
	}
	var api *APIError
	if !errors.As(err, &api) {
		t.Fatal("StorageError must unwrap to *APIError")
	}
}

func TestPlain422StaysAPIError(t *testing.T) {
	srv, _ := recordingServer(t, func(seenReq) (int, any) {
		return 422, map[string]any{"detail": map[string]any{"code": "invalid_format", "message": "bad"}}
	})
	_, err := testClient(t, srv).Downloads.Create(context.Background(), DownloadCreateParams{URL: "https://youtu.be/x"})
	var se *StorageError
	if errors.As(err, &se) {
		t.Fatal("invalid_format must not be a StorageError")
	}
}

func TestDeliveryFailureIsJobFailedWithStage(t *testing.T) {
	failed := downloadJSON("failed", map[string]any{
		"error_code": "storage_permission_denied", "error_message": "denied",
		"error": map[string]any{"code": "storage_permission_denied", "stage": "delivery",
			"retryable": false, "provider_code": "AccessDenied", "hint": "Grant s3:PutObject"},
		"delivery": map[string]any{"type": "storage", "status": "failed", "redeliverable": true,
			"hold_expires_at": "2026-09-27T10:00:00Z"},
	})
	srv, _ := recordingServer(t, func(seenReq) (int, any) { return 202, failed })
	_, err := testClient(t, srv).Downloads.CreateAndWait(context.Background(),
		DownloadCreateParams{URL: "https://youtu.be/x", Destination: StorageID("st_x")}, 0)
	if !errors.Is(err, ErrDeliveryFailed) {
		t.Fatalf("want ErrDeliveryFailed, got %v", err)
	}
	var jf *JobFailedError
	if !errors.As(err, &jf) {
		t.Fatalf("want *JobFailedError, got %T", err)
	}
	if jf.Stage != "delivery" || jf.ProviderCode != "AccessDenied" || jf.Hint == "" ||
		jf.Retryable == nil || *jf.Retryable || !jf.Redeliverable() {
		t.Fatalf("bad JobFailedError %+v", jf)
	}
	if *jf.Download.Delivery.HoldExpiresAt != "2026-09-27T10:00:00Z" {
		t.Fatal("hold_expires_at not decoded")
	}
}

func TestFetchFailureIsNotDeliveryFailure(t *testing.T) {
	failed := downloadJSON("failed", map[string]any{
		"error_code": "download_failed", "error": map[string]any{"code": "download_failed", "stage": "fetch"},
	})
	srv, _ := recordingServer(t, func(seenReq) (int, any) { return 202, failed })
	_, err := testClient(t, srv).Downloads.CreateAndWait(context.Background(), DownloadCreateParams{URL: "https://youtu.be/x"}, 0)
	var jf *JobFailedError
	if !errors.As(err, &jf) || errors.Is(err, ErrDeliveryFailed) || jf.Redeliverable() {
		t.Fatalf("fetch failure misclassified: %v", err)
	}
}

func TestCompletedDeliveryDecoded(t *testing.T) {
	done := downloadJSON("completed", map[string]any{
		"destination_id": "st_x",
		"delivery": map[string]any{"type": "storage", "status": "delivered", "uri": "s3://b/k.mp4",
			"bucket": "b", "key": "k.mp4", "attempts": 2},
	})
	srv, _ := recordingServer(t, func(seenReq) (int, any) { return 200, done })
	dl, err := testClient(t, srv).Downloads.Retrieve(context.Background(), "dl_abc123")
	if err != nil {
		t.Fatal(err)
	}
	if *dl.DestinationID != "st_x" || *dl.Delivery.URI != "s3://b/k.mp4" || *dl.Delivery.Attempts != 2 || dl.Error != nil {
		t.Fatalf("bad delivery %+v", dl.Delivery)
	}
}

func TestRedeliver(t *testing.T) {
	srv, seen := recordingServer(t, func(r seenReq) (int, any) {
		if r.Body != nil && r.Body["destination"] == "x" {
			return 409, map[string]any{"detail": map[string]any{"code": "not_redeliverable", "message": "expired"}}
		}
		return 202, downloadJSON("queued", nil)
	})
	c := testClient(t, srv)
	job, err := c.Downloads.Redeliver(context.Background(), "dl_abc123", nil)
	if err != nil || job.Status() != StatusQueued {
		t.Fatalf("Redeliver: %v", err)
	}
	if _, err := c.Downloads.Redeliver(context.Background(), "dl_abc123", StorageID("st_other")); err != nil {
		t.Fatal(err)
	}
	s := *seen
	if s[0].Path != "/v1/downloads/dl_abc123/redeliver" || s[0].Method != "POST" || len(s[0].Body) != 0 {
		t.Fatalf("bad first redeliver %+v", s[0])
	}
	if d, _ := s[1].Body["destination"].(map[string]any); d["id"] != "st_other" {
		t.Fatalf("bad second redeliver %+v", s[1])
	}
}

func TestRedeliverConflict(t *testing.T) {
	srv, _ := recordingServer(t, func(seenReq) (int, any) {
		return 409, map[string]any{"detail": map[string]any{"code": "not_redeliverable", "message": "expired"}}
	})
	_, err := testClient(t, srv).Downloads.Redeliver(context.Background(), "dl_abc123", nil)
	var ce *ConflictError
	if !errors.As(err, &ce) || ce.Code != "not_redeliverable" {
		t.Fatalf("want *ConflictError, got %T %v", err, err)
	}
}

func TestStorageService(t *testing.T) {
	testResult := map[string]any{"ok": false, "code": "storage_unreachable", "message": "no route",
		"steps": []map[string]any{{"name": "connect", "ok": false, "code": "storage_unreachable"}}}
	srv, seen := recordingServer(t, func(r seenReq) (int, any) {
		switch {
		case r.Method == "GET" && r.Path == "/v1/storage":
			return 200, map[string]any{"items": []any{connJSON}}
		case r.Method == "DELETE":
			return 204, nil
		case r.Path == "/v1/storage/test" || r.Path == "/v1/storage/st_x/test":
			return 200, testResult
		}
		return 200, connJSON
	})
	c, ctx := testClient(t, srv), context.Background()

	items, err := c.Storage.List(ctx)
	if err != nil || len(items) != 1 || items[0].ID != "st_9f1c2a34b5d6e7f8" || !items[0].IsDefault ||
		items[0].Status != "failing" || items[0].LastError.Code != "storage_permission_denied" {
		t.Fatalf("List: %v %+v", err, items)
	}
	if _, err := c.Storage.Retrieve(ctx, "st_x"); err != nil {
		t.Fatal(err)
	}
	if _, err := c.Storage.Create(ctx, StorageCreateParams{Provider: "s3", Bucket: "b", AccessKeyID: "k",
		SecretAccessKey: "s", IsDefault: true}); err != nil {
		t.Fatal(err)
	}
	name := "Renamed"
	if _, err := c.Storage.Update(ctx, "st_x", StorageUpdateParams{Name: &name}); err != nil {
		t.Fatal(err)
	}
	if err := c.Storage.Delete(ctx, "st_x", false); err != nil {
		t.Fatal(err)
	}
	if err := c.Storage.Delete(ctx, "st_x", true); err != nil {
		t.Fatal(err)
	}
	r, err := c.Storage.Test(ctx, StorageTestParams{Provider: "gcs", Bucket: "b", AccessKeyID: "k", SecretAccessKey: "s"})
	if err != nil || r.OK || *r.Code != "storage_unreachable" || r.Steps[0].Name != "connect" {
		t.Fatalf("Test: %v %+v", err, r)
	}
	if _, err := c.Storage.TestSaved(ctx, "st_x"); err != nil {
		t.Fatal(err)
	}

	s := *seen
	want := []string{"GET /v1/storage", "GET /v1/storage/st_x", "POST /v1/storage", "PUT /v1/storage/st_x",
		"DELETE /v1/storage/st_x", "DELETE /v1/storage/st_x", "POST /v1/storage/test", "POST /v1/storage/st_x/test"}
	for i, w := range want {
		if got := s[i].Method + " " + s[i].Path; got != w {
			t.Fatalf("call %d = %s, want %s", i, got, w)
		}
	}
	if s[2].Body["is_default"] != true || s[2].Body["name"] != nil {
		t.Fatalf("create body %v", s[2].Body)
	}
	if len(s[3].Body) != 1 || s[3].Body["name"] != "Renamed" {
		t.Fatalf("update body %v", s[3].Body)
	}
	if s[4].Query != "" || s[5].Query != "force=true" {
		t.Fatalf("delete queries %q %q", s[4].Query, s[5].Query)
	}
}

func TestStorageDeleteInUse(t *testing.T) {
	srv, _ := recordingServer(t, func(seenReq) (int, any) {
		return 409, map[string]any{"detail": map[string]any{"code": "storage_in_use", "message": "2 jobs"}}
	})
	err := testClient(t, srv).Storage.Delete(context.Background(), "st_x", false)
	var ce *ConflictError
	if !errors.As(err, &ce) || ce.Code != "storage_in_use" {
		t.Fatalf("want storage_in_use conflict, got %v", err)
	}
}

func TestWebhookEventsIncludeStorageConnectionFailed(t *testing.T) {
	for _, e := range WebhookEvents {
		if e == EventStorageConnectionFailed {
			return
		}
	}
	t.Fatal("storage.connection_failed missing from WebhookEvents")
}
