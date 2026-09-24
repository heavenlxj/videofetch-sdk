package videofetch

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

// The API accepts a saved storage connection as a bare id — the provider, bucket and
// credentials all live on the connection. These tests pin the wire format, because the
// failure mode is silent: an empty `Type` serialises as `"type":""`, which the API rejects
// as an invalid enum member (422), so a caller holding only an id could not use a connection
// at all.

// captureCreateBody runs one Downloads.Create against a stub API and returns the raw JSON
// body that actually went out on the wire.
func captureCreateBody(t *testing.T, p DownloadCreateParams) string {
	t.Helper()
	var raw []byte

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/v1/downloads" || r.Method != "POST" {
			t.Fatalf("unexpected %s %s", r.Method, r.URL.Path)
		}
		b, err := io.ReadAll(r.Body)
		if err != nil {
			t.Fatal(err)
		}
		raw = b
		writeJSON(t, w, 202, downloadJSON("queued", nil))
	}))
	defer srv.Close()

	if _, err := testClient(t, srv).Downloads.Create(context.Background(), p); err != nil {
		t.Fatalf("Create: %v", err)
	}
	return string(raw)
}

// destinationOf decodes the request body and returns its destination object.
func destinationOf(t *testing.T, body string) map[string]any {
	t.Helper()
	var full map[string]json.RawMessage
	if err := json.Unmarshal([]byte(body), &full); err != nil {
		t.Fatalf("unmarshal body: %v (%s)", err, body)
	}
	rawDest, ok := full["destination"]
	if !ok {
		return nil
	}
	var dest map[string]any
	if err := json.Unmarshal(rawDest, &dest); err != nil {
		t.Fatalf("unmarshal destination: %v (%s)", err, rawDest)
	}
	return dest
}

func TestDestinationSavedConnectionSendsIDOnly(t *testing.T) {
	body := captureCreateBody(t, DownloadCreateParams{
		URL:         "https://youtu.be/x",
		Format:      Format1080p,
		Destination: &DestinationSpec{ID: "conn_9f1c2a34"},
	})

	if strings.Contains(body, `"type"`) {
		t.Fatalf("a saved connection must not carry a type (the API rejects an empty enum): %s", body)
	}
	dest := destinationOf(t, body)
	if dest == nil {
		t.Fatalf("destination missing from body: %s", body)
	}
	if dest["id"] != "conn_9f1c2a34" {
		t.Fatalf("id = %v, want conn_9f1c2a34", dest["id"])
	}
	if len(dest) != 1 {
		t.Fatalf("destination should carry exactly the id, got %v", dest)
	}
}

func TestDestinationKeepsProviderWhenGiven(t *testing.T) {
	body := captureCreateBody(t, DownloadCreateParams{
		URL:         "https://youtu.be/x",
		Format:      Format1080p,
		Destination: &DestinationSpec{Type: "r2", ID: "conn_9f1c2a34"},
	})

	dest := destinationOf(t, body)
	if dest["type"] != "r2" || dest["id"] != "conn_9f1c2a34" {
		t.Fatalf("destination = %v, want {type:r2 id:conn_9f1c2a34}", dest)
	}
}

func TestDestinationInlineCredentialsTravelWhole(t *testing.T) {
	body := captureCreateBody(t, DownloadCreateParams{
		URL:    "https://youtu.be/x",
		Format: Format1080p,
		Destination: &DestinationSpec{
			Type:            "s3",
			Bucket:          "my-bucket",
			Region:          "us-east-1",
			AccessKeyID:     "AKIA...",
			SecretAccessKey: "s3cr3t",
			Path:            "videos/",
		},
	})

	dest := destinationOf(t, body)
	for k, want := range map[string]string{
		"type": "s3", "bucket": "my-bucket", "region": "us-east-1",
		"access_key_id": "AKIA...", "secret_access_key": "s3cr3t", "path": "videos/",
	} {
		if dest[k] != want {
			t.Fatalf("destination[%q] = %v, want %q (%v)", k, dest[k], want, dest)
		}
	}
	if _, hasID := dest["id"]; hasID {
		t.Fatalf("inline credentials must not carry an id: %v", dest)
	}
}

func TestDestinationOmittedIsNotSent(t *testing.T) {
	body := captureCreateBody(t, DownloadCreateParams{
		URL: "https://youtu.be/x", Format: Format1080p,
	})

	if strings.Contains(body, `"destination"`) {
		t.Fatalf("destination should be omitted entirely: %s", body)
	}
}
