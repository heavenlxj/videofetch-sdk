"""Typed models mirroring the VideoFetch API contract (openapi/openapi.json).

Implemented as lightweight dataclasses with from_dict() so the SDK has zero
runtime deps beyond httpx (no pydantic required by consumers).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


def _as_float(v: Any) -> Optional[float]:
    return float(v) if v is not None else None


def _as_int(v: Any) -> Optional[int]:
    return int(v) if v is not None else None


@dataclass
class TrimSpec:
    """Requested clip window in seconds (float). end must be > start."""
    start: Optional[float] = None
    end: Optional[float] = None

    @classmethod
    def from_dict(cls, d: Optional[dict]) -> Optional["TrimSpec"]:
        if not d:
            return None
        return cls(start=_as_float(d.get("start")), end=_as_float(d.get("end")))

    def to_dict(self) -> Optional[dict]:
        if self.start is None and self.end is None:
            return None
        return {"start": self.start, "end": self.end}


@dataclass
class DownloadAttempt:
    attempt_no: Optional[int] = None
    strategy: Optional[str] = None          # direct | decodo_isp | decodo_dc
    proxy_host: Optional[str] = None
    result: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    latency_ms: Optional[int] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None

    @classmethod
    def from_dict(cls, d: Optional[dict]) -> Optional["DownloadAttempt"]:
        if not d:
            return None
        return cls(
            attempt_no=_as_int(d.get("attempt_no")), strategy=d.get("strategy"),
            proxy_host=d.get("proxy_host"), result=d.get("result"),
            error_code=d.get("error_code"), error_message=d.get("error_message"),
            latency_ms=_as_int(d.get("latency_ms")), started_at=d.get("started_at"),
            finished_at=d.get("finished_at"),
        )


@dataclass
class Download:
    """A download job (dl_xxx). Mirrors GET /v1/downloads/{id}."""
    id: str
    status: str                                # queued|processing|completed|failed|deleted
    url: str
    format: str                                # 144p..2160p|mp3
    progress: int = 0
    title: Optional[str] = None
    video_id: Optional[str] = None
    channel: Optional[str] = None
    upload_date: Optional[str] = None
    thumbnail: Optional[str] = None
    duration_seconds: Optional[float] = None
    size_bytes: Optional[int] = None
    trim: Optional[TrimSpec] = None
    destination_type: Optional[str] = None     # url|s3|r2|gcs|s3_compatible
    download_url: Optional[str] = None         # presigned link (url destination only)
    download_url_expires_at: Optional[str] = None
    storage_key: Optional[str] = None          # user://<bucket>/<key> when destination used
    processing_time_ms: Optional[int] = None
    cost_usd: float = 0.0
    attempts: int = 0
    strategy: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    created_at: Optional[str] = None
    completed_at: Optional[str] = None
    estimated_bytes: Optional[int] = None
    attempt_details: list[DownloadAttempt] = field(default_factory=list)

    @property
    def is_terminal(self) -> bool:
        return self.status in ("completed", "failed", "deleted")

    @property
    def failed_not_charged(self) -> bool:
        return self.status == "failed"

    @classmethod
    def from_dict(cls, d: dict) -> "Download":
        return cls(
            id=d.get("id", ""), status=d.get("status", "queued"), url=d.get("url", ""),
            format=d.get("format", "mp4"), progress=int(d.get("progress") or 0),
            title=d.get("title"), video_id=d.get("video_id"), channel=d.get("channel"),
            upload_date=d.get("upload_date"), thumbnail=d.get("thumbnail"),
            duration_seconds=_as_float(d.get("duration_seconds")),
            size_bytes=_as_int(d.get("size_bytes")),
            trim=TrimSpec.from_dict(d.get("trim")),
            destination_type=d.get("destination_type"), download_url=d.get("download_url"),
            download_url_expires_at=d.get("download_url_expires_at"),
            storage_key=d.get("storage_key"),
            processing_time_ms=_as_int(d.get("processing_time_ms")),
            cost_usd=float(d.get("cost_usd") or 0.0),
            attempts=int(d.get("attempts") or 0), strategy=d.get("strategy"),
            error_code=d.get("error_code"), error_message=d.get("error_message"),
            created_at=d.get("created_at"), completed_at=d.get("completed_at"),
            estimated_bytes=_as_int(d.get("estimated_bytes")),
            attempt_details=[DownloadAttempt.from_dict(a) or DownloadAttempt()
                             for a in (d.get("attempt_details") or [])],
        )


@dataclass
class DownloadList:
    items: list[Download] = field(default_factory=list)
    total: int = 0
    has_more: bool = False

    @classmethod
    def from_dict(cls, d: dict) -> "DownloadList":
        return cls(
            items=[Download.from_dict(i) for i in (d.get("items") or [])],
            total=int(d.get("total") or 0), has_more=bool(d.get("has_more")),
        )


@dataclass
class FormatInfo:
    quality: str
    size: Optional[int] = None
    container: str = "MP4"
    note: Optional[str] = None


@dataclass
class VideoInfo:
    """POST /v1/info result (free metadata lookup)."""
    id: Optional[str] = None
    url: str = ""
    title: Optional[str] = None
    duration: Optional[float] = None
    thumbnail: Optional[str] = None
    channel: Optional[str] = None
    upload_date: Optional[str] = None
    view_count: Optional[int] = None
    formats: list[FormatInfo] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "VideoInfo":
        return cls(
            id=d.get("id"), url=d.get("url", ""), title=d.get("title"),
            duration=_as_float(d.get("duration")), thumbnail=d.get("thumbnail"),
            channel=d.get("channel"), upload_date=d.get("upload_date"),
            view_count=_as_int(d.get("view_count")),
            formats=[FormatInfo(
                quality=f.get("quality", ""), size=_as_int(f.get("size")),
                container=f.get("container", "MP4"), note=f.get("note"),
            ) for f in (d.get("formats") or [])],
        )
