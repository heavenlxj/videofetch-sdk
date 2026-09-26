"""VideoFetch — official Python SDK.

    import videofetch
    client = videofetch.VideoFetch(api_key="vf_live_sk_...")
    job = client.downloads.create(url="https://youtu.be/...", format="1080p")
    result = job.wait()          # polls until completed/failed
    print(result.download_url)   # presigned 7-day link (url destination)
    path = client.downloads.download_to(result.id)   # save the file locally → abs path

Usage & alerts (v0.2.0):
    usage = client.usage.get()               # quota_gb, used_pct, alert_level, ...
    alerts = client.usage.alerts()           # state + fired[] + thresholds

Webhook endpoints (v0.2.0):
    ep = client.webhooks.create("https://acme.dev/hooks/vf")   # ep.secret shown once
    client.webhooks.list(); client.webhooks.test(ep.id); client.webhooks.delete(ep.id)

Storage (v0.5.0):
    conn = client.storage.create(provider="s3", bucket="my-bucket", region="us-east-1",
                                 access_key_id="AKIA...", secret_access_key="...")
    job = client.downloads.create(url=..., destination=conn.id)   # "st_…"
    print(job.wait().delivery.uri)          # s3://my-bucket/youtube/<id>/…
    # failed upload → DeliveryFailedError; fix the bucket, then client.downloads.redeliver(job.id)

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
    ConflictError,
    DeliveryFailedError,
    DownloadNotCompletedError,
    DownloadURLUnavailableError,
    JobFailedError,
    NotFoundError,
    PermissionDeniedError,
    QuotaExceededError,
    RateLimitError,
    StorageError,
    ValidationError,
    VideoFetchError,
)
from .models import (  # noqa: F401
    AlertEvent,
    AlertState,
    Delivery,
    Download,
    DownloadAttempt,
    DownloadError,
    DownloadList,
    FormatInfo,
    ReplayResult,
    StorageConnection,
    StorageTestResult,
    StorageTestStep,
    TrimSpec,
    Usage,
    UsageAlerts,
    VideoInfo,
    WebhookDeliveriesResult,
    WebhookDelivery,
    WebhookDeliveryHealth,
    WebhookEndpoint,
    WebhookList,
    WebhookTestResult,
)
from .resources import DownloadJob  # noqa: F401
from .webhooks import (  # noqa: F401
    ATTEMPT_HEADER,
    DELIVERY_HEADER,
    TIMESTAMP_HEADER,
    WEBHOOK_EVENTS,
    SignatureVerificationError,
    attempt_number,
    compute_signature,
    construct_event,
    delivery_id,
    verify_webhook_signature,
)

__version__ = "0.5.0"
__all__ = [
    "VideoFetch", "AsyncVideoFetch", "DownloadJob",
    "VideoFetchError", "AuthenticationError", "PermissionDeniedError", "QuotaExceededError",
    "ValidationError", "NotFoundError", "RateLimitError", "ApiError", "JobFailedError",
    "DownloadNotCompletedError", "DownloadURLUnavailableError",
    "Download", "DownloadList", "DownloadAttempt", "TrimSpec", "FormatInfo", "VideoInfo",
    # v0.2.0
    "Usage", "UsageAlerts", "AlertState", "AlertEvent",
    "WebhookEndpoint", "WebhookList", "WebhookTestResult",
    "WEBHOOK_EVENTS", "SignatureVerificationError",
    "compute_signature", "construct_event", "verify_webhook_signature",
    # v0.3.0
    "WebhookDelivery", "WebhookDeliveriesResult", "WebhookDeliveryHealth", "ReplayResult",
    "delivery_id", "attempt_number",
    "DELIVERY_HEADER", "ATTEMPT_HEADER", "TIMESTAMP_HEADER",
    # v0.5.0
    "StorageError", "ConflictError", "DeliveryFailedError",
    "Delivery", "DownloadError", "StorageConnection", "StorageTestResult", "StorageTestStep",
    "__version__",
]
