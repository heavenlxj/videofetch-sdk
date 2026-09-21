//go:build integration

package videofetch

import "errors"

func asAPIError(err error, target **APIError) bool {
	return errors.As(err, target)
}
