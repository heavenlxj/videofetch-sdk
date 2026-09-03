"""VideoFetch — official Python SDK.

    import videofetch
    client = videofetch.VideoFetch(api_key="vf_live_sk_...")
    job = client.downloads.create(url="https://youtu.be/...", format="1080p")
    result = job.wait()          # polls until completed/failed
    print(result.download_url)   # presigned 7-day link (url destination)

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
    QuotaExceededError,
    RateLimitError,
    ValidationError,
    VideoFetchError,
)
from .models import Download, DownloadAttempt, DownloadList, FormatInfo, TrimSpec, VideoInfo  # noqa: F401
from .resources import DownloadJob  # noqa: F401

__version__ = "0.1.0"
__all__ = [
    "VideoFetch", "AsyncVideoFetch", "DownloadJob",
    "VideoFetchError", "AuthenticationError", "QuotaExceededError", "ValidationError",
    "NotFoundError", "RateLimitError", "ApiError", "JobFailedError",
    "Download", "DownloadList", "DownloadAttempt", "TrimSpec", "FormatInfo", "VideoInfo",
    "__version__",
]
