"""Fixed-window rate limits for the contact form.

Counters are stored per window (UTC hour / UTC day) so that each document is only
written while its window is open and can be removed by a TTL policy afterwards.
"""

import hashlib
import hmac
import ipaddress
import math
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.config import RateLimits

# IPv6 clients usually control a whole /64, so addresses are grouped by that prefix.
IPV6_PREFIX_LENGTH = 64

# Bounds the memory used by ExceededCounterCache (one short string and a datetime each).
EXCEEDED_CACHE_MAX_ENTRIES = 1000


@dataclass(frozen=True)
class Counter:
    scope: str
    doc_id: str
    limit: int
    expires_at: datetime


class RateLimitExceeded(Exception):
    def __init__(self, scopes: list[str], retry_after_seconds: int) -> None:
        super().__init__(f"rate limit exceeded: {', '.join(scopes)}")
        self.scopes = scopes
        self.retry_after_seconds = retry_after_seconds


def hash_client_ip(ip: str, key: bytes) -> str:
    """Return a keyed hash so that raw IP addresses are never stored."""
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        normalized = ip
    else:
        if address.version == 6:
            network = ipaddress.ip_network(f"{address}/{IPV6_PREFIX_LENGTH}", strict=False)
            normalized = str(network)
        else:
            normalized = str(address)
    return hmac.new(key, normalized.encode(), hashlib.sha256).hexdigest()


def build_counters(ip_hash: str, now: datetime, limits: RateLimits) -> list[Counter]:
    hour_start = now.replace(minute=0, second=0, microsecond=0)
    day_start = hour_start.replace(hour=0)
    hour_end = hour_start + timedelta(hours=1)
    day_end = day_start + timedelta(days=1)
    hour_key = hour_start.strftime("%Y%m%d%H")
    day_key = day_start.strftime("%Y%m%d")
    return [
        Counter("ip_hour", f"ip-hour-{hour_key}-{ip_hash}", limits.ip_per_hour, hour_end),
        Counter("ip_day", f"ip-day-{day_key}-{ip_hash}", limits.ip_per_day, day_end),
        Counter("site_day", f"site-day-{day_key}", limits.site_per_day, day_end),
    ]


def check_counters(counters: list[Counter], counts: list[int], now: datetime) -> None:
    """Raise RateLimitExceeded if accepting one more request would exceed any limit."""
    exceeded = [c for c, count in zip(counters, counts, strict=True) if count >= c.limit]
    if exceeded:
        raise _exceeded_error(exceeded, now)


def _exceeded_error(exceeded: list[Counter], now: datetime) -> RateLimitExceeded:
    latest_reset = max(c.expires_at for c in exceeded)
    retry_after = max(1, math.ceil((latest_reset - now).total_seconds()))
    return RateLimitExceeded([c.scope for c in exceeded], retry_after)


class ExceededCounterCache:
    """Remembers counters that reached their limit until their window ends.

    A counter only grows within its window, so later requests in the same window can be
    rejected without reading Firestore again. The cache lives in one instance's memory;
    losing it (e.g. a new instance) only means the counters are read once more.
    """

    def __init__(self, max_entries: int = EXCEEDED_CACHE_MAX_ENTRIES) -> None:
        self._max_entries = max_entries
        self._expires_at: dict[str, datetime] = {}
        self._lock = threading.Lock()

    def check(self, counters: list[Counter], now: datetime) -> None:
        """Raise RateLimitExceeded if any counter is known to be full."""
        # Document IDs include the window, so an entry never matches a later window.
        with self._lock:
            exceeded = [c for c in counters if c.doc_id in self._expires_at]
        if exceeded:
            raise _exceeded_error(exceeded, now)

    def add(self, counters: list[Counter], now: datetime) -> None:
        with self._lock:
            if len(self._expires_at) + len(counters) > self._max_entries:
                self._expires_at = {k: v for k, v in self._expires_at.items() if v > now}
            for counter in counters:
                while len(self._expires_at) >= self._max_entries:
                    # Drop the oldest entry; it costs at most one more Firestore read.
                    del self._expires_at[next(iter(self._expires_at))]
                self._expires_at[counter.doc_id] = counter.expires_at
