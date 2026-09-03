package videofetch

import "context"

// InfoService provides free metadata lookups. Access via client.Info.
type InfoService struct{ client *Client }

// Lookup resolves video metadata (title, duration, available formats) without
// consuming quota. Accepts a full URL or bare video ID.
func (s *InfoService) Lookup(ctx context.Context, url string) (*VideoInfo, error) {
	var info VideoInfo
	if err := s.client.request(ctx, "POST", "/v1/info", map[string]string{"url": url}, &info); err != nil {
		return nil, err
	}
	return &info, nil
}
