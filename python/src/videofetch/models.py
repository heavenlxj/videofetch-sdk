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


def _as_str(v: Any) -> Optional[str]:
    return None if v is None else str(v)


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
    strategy: Optional[str] = None          # direct | relay | relay_secondary
    egress: Optional[str] = None        # "relay" or None (direct); real egress hosts are never returned
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
            egress=d.get("egress"), result=d.get("result"),
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
    # Queue position hints — only populated while status == "queued"; null otherwise.
    queue_position: Optional[int] = None        # 1 == next to be claimed
    ahead_of_you: Optional[int] = None
    estimated_wait_seconds: Optional[int] = None

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
            queue_position=_as_int(d.get("queue_position")),
            ahead_of_you=_as_int(d.get("ahead_of_you")),
            estimated_wait_seconds=_as_int(d.get("estimated_wait_seconds")),
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


# ────────────────────────── Usage / Alerts (v0.2.0) ──────────────────────────
@dataclass
class Usage:
    """GET /v1/usage — account quota snapshot + live alert level + concurrency.

    `used_bytes`/`used_gb` are the ACCOUNT-WIDE current-month billable usage (the
    quota is account-level and shared by every key). `key_used_bytes`/`key_used_gb`
    are this key's own accumulated usage, for per-key attribution.
    `account_used_*_month` mirror the account-level current-month figures.

    `quota_gb`/`remaining_gb` are the subscription quota; `plan_remaining_gb` excludes
    top-up packs, `pack_gb`/`pack_remaining_gb` cover the packs bought for this period.
    `key_id` is `None` when the figures were produced from a dashboard session rather
    than an API key.
    """
    key_id: Optional[str] = None
    plan: str = "free"
    quota_gb: Optional[float] = None
    used_bytes: int = 0
    used_gb: float = 0.0
    key_used_bytes: int = 0
    key_used_gb: float = 0.0
    remaining_gb: Optional[float] = None
    plan_remaining_gb: float = 0.0
    pack_gb: float = 0.0
    pack_remaining_gb: float = 0.0
    period_start: Optional[str] = None
    period_end: Optional[str] = None
    payg_balance_cents: int = 0
    payg_rate_usd_per_gb: float = 0.5
    account_used_bytes_month: int = 0
    account_used_gb_month: float = 0.0
    used_pct: float = 0.0
    month: str = ""
    active_jobs: int = 0
    concurrency_limit: int = 0
    alert_level: str = "ok"          # ok | warning | critical | exceeded
    alert_message: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "Usage":
        return cls(
            # 注意: key 存在但值为 null 时不能走 str() —— str(None) 会变成字符串 "None"
            key_id=d.get("key_id") or None, plan=d.get("plan", "free"),
            quota_gb=_as_float(d.get("quota_gb")),
            used_bytes=int(d.get("used_bytes") or 0),
            used_gb=float(d.get("used_gb") or 0.0),
            key_used_bytes=int(d.get("key_used_bytes") or 0),
            key_used_gb=float(d.get("key_used_gb") or 0.0),
            remaining_gb=_as_float(d.get("remaining_gb")),
            plan_remaining_gb=float(d.get("plan_remaining_gb") or 0.0),
            pack_gb=float(d.get("pack_gb") or 0.0),
            pack_remaining_gb=float(d.get("pack_remaining_gb") or 0.0),
            period_start=d.get("period_start") or None,
            period_end=d.get("period_end") or None,
            payg_balance_cents=int(d.get("payg_balance_cents") or 0),
            payg_rate_usd_per_gb=float(d.get("payg_rate_usd_per_gb") or 0.0),
            account_used_bytes_month=int(d.get("account_used_bytes_month") or 0),
            account_used_gb_month=float(d.get("account_used_gb_month") or 0.0),
            used_pct=float(d.get("used_pct") or 0.0),
            month=d.get("month", ""), active_jobs=int(d.get("active_jobs") or 0),
            concurrency_limit=int(d.get("concurrency_limit") or 0),
            alert_level=d.get("alert_level", "ok"), alert_message=d.get("alert_message", ""),
        )


@dataclass
class AlertState:
    """Real-time alert state (GET /v1/usage/alerts → `state`)."""
    level: str = "ok"                # ok | warning | critical | exceeded
    pct_used: float = 0.0
    thresholds: list[int] = field(default_factory=list)
    crossed: list[int] = field(default_factory=list)
    next_threshold_pct: Optional[int] = None
    quota_gb: float = 0.0
    used_gb_month: float = 0.0
    remaining_gb: Optional[float] = None
    month: str = ""
    plan: str = "free"
    payg_balance_cents: int = 0
    balance_low: bool = False
    balance_depleted: bool = False
    balance_hint: Optional[str] = None
    message: str = ""
    action: Optional[str] = None     # topup | upgrade | None

    @classmethod
    def from_dict(cls, d: Optional[dict]) -> "AlertState":
        d = d or {}
        return cls(
            level=d.get("level", "ok"), pct_used=float(d.get("pct_used") or 0.0),
            thresholds=[int(t) for t in (d.get("thresholds") or [])],
            crossed=[int(t) for t in (d.get("crossed") or [])],
            next_threshold_pct=_as_int(d.get("next_threshold_pct")),
            quota_gb=float(d.get("quota_gb") or 0.0),
            used_gb_month=float(d.get("used_gb_month") or 0.0),
            remaining_gb=_as_float(d.get("remaining_gb")), month=d.get("month", ""),
            plan=d.get("plan", "free"),
            payg_balance_cents=int(d.get("payg_balance_cents") or 0),
            balance_low=bool(d.get("balance_low")), balance_depleted=bool(d.get("balance_depleted")),
            balance_hint=d.get("balance_hint"), message=d.get("message", ""),
            action=d.get("action"),
        )


@dataclass
class AlertEvent:
    """A fired alert record (deduped per month/threshold/kind)."""
    id: str = ""
    kind: str = ""
    level: str = "warning"
    threshold: int = 0
    pct_used: float = 0.0
    used_gb: float = 0.0
    quota_gb: float = 0.0
    balance_cents: int = 0
    message: str = ""
    delivered: bool = False
    created_at: Optional[str] = None

    @classmethod
    def from_dict(cls, d: dict) -> "AlertEvent":
        return cls(
            id=str(d.get("id", "")), kind=d.get("kind", ""), level=d.get("level", "warning"),
            threshold=int(d.get("threshold") or 0), pct_used=float(d.get("pct_used") or 0.0),
            used_gb=float(d.get("used_gb") or 0.0), quota_gb=float(d.get("quota_gb") or 0.0),
            balance_cents=int(d.get("balance_cents") or 0), message=d.get("message", ""),
            delivered=bool(d.get("delivered")),
            created_at=_as_str(d.get("created_at")),
        )


@dataclass
class UsageAlerts:
    """GET /v1/usage/alerts result."""
    state: AlertState = field(default_factory=AlertState)
    fired: list[AlertEvent] = field(default_factory=list)
    thresholds: list[int] = field(default_factory=list)
    topup_amounts: list[int] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "UsageAlerts":
        return cls(
            state=AlertState.from_dict(d.get("state")),
            fired=[AlertEvent.from_dict(e) for e in (d.get("fired") or [])],
            thresholds=[int(t) for t in (d.get("thresholds") or [])],
            topup_amounts=[int(a) for a in (d.get("topup_amounts") or [])],
        )


# ────────────────────────── Webhook endpoints (v0.2.0) ───────────────────────
@dataclass
class WebhookEndpoint:
    """A registered webhook endpoint.

    `secret` is the FULL plaintext signing secret returned by create() — it is
    shown only once. list() returns masked secrets (e.g. `whsec_abc****abcd`).
    """
    id: str = ""
    url: str = ""
    secret: str = ""
    events: list[str] = field(default_factory=list)
    active: bool = True
    last_delivery_at: Optional[str] = None
    last_status: Optional[int] = None
    failure_count: int = 0
    created_at: Optional[str] = None

    @classmethod
    def from_dict(cls, d: dict) -> "WebhookEndpoint":
        return cls(
            id=str(d.get("id", "")), url=d.get("url", ""), secret=d.get("secret", ""),
            events=list(d.get("events") or []), active=bool(d.get("active", True)),
            last_delivery_at=_as_str(d.get("last_delivery_at")),
            last_status=_as_int(d.get("last_status")),
            failure_count=int(d.get("failure_count") or 0),
            created_at=_as_str(d.get("created_at")),
        )


@dataclass
class WebhookList:
    items: list[WebhookEndpoint] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "WebhookList":
        return cls(items=[WebhookEndpoint.from_dict(w) for w in (d.get("items") or [])])


@dataclass
class WebhookTestResult:
    """POST /v1/webhooks/{id}/test — one-shot ping delivery result."""
    delivered: bool = False
    url: str = ""
    last_status: Optional[int] = None
    signature_header: str = ""
    signature_format: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "WebhookTestResult":
        return cls(
            delivered=bool(d.get("delivered")), url=d.get("url", ""),
            last_status=_as_int(d.get("last_status")),
            signature_header=d.get("signature_header", ""),
            signature_format=d.get("signature_format", ""),
        )


# ──────────────────── Webhook deliveries + replay (v0.3.0) ───────────────────
@dataclass
class WebhookDeliveryHealth:
    """Aggregate delivery health for one endpoint (GET /v1/webhooks/{id}/deliveries)."""
    total: int = 0
    succeeded: int = 0
    dead: int = 0
    pending: int = 0
    success_rate: Optional[float] = None

    @classmethod
    def from_dict(cls, d: Optional[dict]) -> "WebhookDeliveryHealth":
        d = d or {}
        return cls(
            total=int(d.get("total") or 0), succeeded=int(d.get("succeeded") or 0),
            dead=int(d.get("dead") or 0), pending=int(d.get("pending") or 0),
            success_rate=_as_float(d.get("success_rate")),
        )


@dataclass
class WebhookDelivery:
    """A single webhook delivery attempt (or its final state).

    Deliveries are at-least-once: retried up to `max_attempts` (3) with backoff
    on transient errors; 4xx responses other than 408/429 are permanent failures
    that are not retried. Ordering is NOT guaranteed — sort by `seq`.
    """
    event_id: str = ""                 # idempotency key (X-VideoFetch-Delivery)
    event: str = ""
    seq: int = 0
    status: str = "pending"            # pending | succeeded | dead
    attempts: int = 0
    max_attempts: int = 3
    last_status_code: Optional[int] = None
    last_error: Optional[str] = None
    next_attempt_at: Optional[str] = None
    created_at: Optional[str] = None
    delivered_at: Optional[str] = None
    download_id: Optional[str] = None

    @classmethod
    def from_dict(cls, d: dict) -> "WebhookDelivery":
        return cls(
            event_id=str(d.get("event_id", "")), event=d.get("event", ""),
            seq=int(d.get("seq") or 0), status=d.get("status", "pending"),
            attempts=int(d.get("attempts") or 0),
            max_attempts=int(d.get("max_attempts") or 0),
            last_status_code=_as_int(d.get("last_status_code")),
            last_error=_as_str(d.get("last_error")),
            next_attempt_at=_as_str(d.get("next_attempt_at")),
            created_at=_as_str(d.get("created_at")),
            delivered_at=_as_str(d.get("delivered_at")),
            download_id=_as_str(d.get("download_id")),
        )


@dataclass
class WebhookDeliveriesResult:
    """GET /v1/webhooks/{endpoint_id}/deliveries — endpoint state + recent deliveries."""
    endpoint_id: str = ""
    active: bool = True
    auto_disabled_at: Optional[str] = None
    consecutive_failures: int = 0
    max_attempts: int = 3
    retry_schedule_seconds: str = ""   # e.g. "30,300"
    health: WebhookDeliveryHealth = field(default_factory=WebhookDeliveryHealth)
    items: list[WebhookDelivery] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "WebhookDeliveriesResult":
        return cls(
            endpoint_id=str(d.get("endpoint_id", "")), active=bool(d.get("active", True)),
            auto_disabled_at=_as_str(d.get("auto_disabled_at")),
            consecutive_failures=int(d.get("consecutive_failures") or 0),
            max_attempts=int(d.get("max_attempts") or 0),
            retry_schedule_seconds=_as_str(d.get("retry_schedule_seconds")) or "",
            health=WebhookDeliveryHealth.from_dict(d.get("health")),
            items=[WebhookDelivery.from_dict(i) for i in (d.get("items") or [])],
        )


@dataclass
class ReplayResult:
    """POST /v1/webhooks/deliveries/{event_id}/replay result.

    A 404 means the delivery is not visible to this account.
    """
    queued: bool = False
    event_id: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "ReplayResult":
        return cls(queued=bool(d.get("queued")), event_id=str(d.get("event_id", "")))
