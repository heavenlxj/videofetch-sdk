"""VideoFetch — official Python SDK.

    import videofetch
    client = videofetch.VideoFetch(api_key="vf_live_sk_...")
    job = client.downloads.create(url="https://youtu.be/...", format="1080p")
    result = job.wait()          # polls until completed/failed
    print(result.download_url)   # presigned 7-day link (url destination)

Usage & alerts (v0.2.0):
    usage = client.usage.get()               # quota_gb, used_pct, alert_level, ...
    alerts = client.usage.alerts()           # state + fired[] + thresholds

Webhook endpoints (v0.2.0):
    ep = client.webhooks.create("https://acme.dev/hooks/vf")   # ep.secret shown once
    client.webhooks.list(); client.webhooks.test(ep.id); client.webhooks.delete(ep.id)

Async:
    from videofetch.asyncio import AsyncVideoFetch
    async with AsyncVideoFetch(api_key="...") as client:
        result = await (await client.downloads.create(url=..., format="1080p")).wait()

Webhooks (FastAPI example):
    from videofetch.webhooks import construct_event
    payload = await request.body()
    event = construct_event(payload, request.headers.get("X-VideoFetch-Signature"), endpoint_secret)
"""

from .client import AsyncVideoFetch, VideoFetch  # noqa: F401
from .errors import (  # noqa: F401
    ApiError,
    AuthenticationError,
    JobFailedError,
    NotFoundError,
    PermissionDeniedError,
    QuotaExceededError,
    RateLimitError,
    ValidationError,
    VideoFetchError,
)
from .models import (  # noqa: F401
    AlertEvent,
    AlertState,
    Download,
    DownloadAttempt,
    DownloadList,
    FormatInfo,
    TrimSpec,
    Usage,
    UsageAlerts,
    VideoInfo,
    WebhookEndpoint,
    WebhookList,
    WebhookTestResult,
)
from .resources import DownloadJob  # noqa: F401
from .webhooks import (  # noqa: F401
    WEBHOOK_EVENTS,
    SignatureVerificationError,
    compute_signature,
    construct_event,
    verify_webhook_signature,
)

__version__ = "0.2.0"
__all__ = [
    "VideoFetch", "AsyncVideoFetch", "DownloadJob",
    "VideoFetchError", "AuthenticationError", "PermissionDeniedError", "QuotaExceededError",
    "ValidationError", "NotFoundError", "RateLimitError", "ApiError", "JobFailedError",
    "Download", "DownloadList", "DownloadAttempt", "TrimSpec", "FormatInfo", "VideoInfo",
    # v0.2.0
    "Usage", "UsageAlerts", "AlertState", "AlertEvent",
    "WebhookEndpoint", "WebhookList", "WebhookTestResult",
    "WEBHOOK_EVENTS", "SignatureVerificationError",
    "compute_signature", "construct_event", "verify_webhook_signature",
    "__version__",
]
