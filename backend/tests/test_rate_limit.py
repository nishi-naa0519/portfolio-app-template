from datetime import UTC, datetime

import pytest

from app.config import RateLimits
from app.services.contact_store import write_contact
from app.services.rate_limit import (
    ExceededCounterCache,
    RateLimitExceeded,
    build_counters,
    check_counters,
    hash_client_ip,
)
from tests.fakes import FakeRef, FakeTransaction

KEY = b"test-key"
NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


def test_hash_is_keyed_and_does_not_contain_the_ip() -> None:
    hashed = hash_client_ip("192.0.2.1", KEY)

    assert hashed == hash_client_ip("192.0.2.1", KEY)
    assert hashed != hash_client_ip("192.0.2.1", b"other-key")
    assert hashed != hash_client_ip("192.0.2.2", KEY)
    assert "192.0.2.1" not in hashed
    assert len(hashed) == 64


def test_ipv6_addresses_in_the_same_64_prefix_share_a_hash() -> None:
    a = hash_client_ip("2001:db8:1:2::1", KEY)

    assert a == hash_client_ip("2001:db8:1:2:ffff:ffff:ffff:ffff", KEY)
    assert a == hash_client_ip("2001:0db8:0001:0002:0000:0000:0000:0001", KEY)
    assert a != hash_client_ip("2001:db8:1:3::1", KEY)


def test_unparsable_ip_is_still_hashed() -> None:
    assert len(hash_client_ip("unknown", KEY)) == 64


def test_counters_use_utc_hour_and_day_windows() -> None:
    counters = build_counters("h", NOW, RateLimits(ip_per_hour=1, ip_per_day=2, site_per_day=3))

    assert [(c.scope, c.doc_id, c.limit, c.expires_at) for c in counters] == [
        ("ip_hour", "ip-hour-2026010203-h", 1, datetime(2026, 1, 2, 4, tzinfo=UTC)),
        ("ip_day", "ip-day-20260102-h", 2, datetime(2026, 1, 3, tzinfo=UTC)),
        ("site_day", "site-day-20260102", 3, datetime(2026, 1, 3, tzinfo=UTC)),
    ]


def test_check_counters_allows_requests_below_the_limits() -> None:
    counters = build_counters("h", NOW, RateLimits())

    check_counters(counters, [2, 4, 19], NOW)


def test_check_counters_reports_every_exceeded_scope_and_latest_reset() -> None:
    counters = build_counters("h", NOW, RateLimits())

    with pytest.raises(RateLimitExceeded) as exc_info:
        check_counters(counters, [3, 4, 20], NOW)

    assert exc_info.value.scopes == ["ip_hour", "site_day"]
    # Until 2026-01-03 00:00 UTC.
    assert exc_info.value.retry_after_seconds == 20 * 3600 + 55 * 60 + 55


def test_retry_after_is_at_least_one_second() -> None:
    now = NOW.replace(minute=59, second=59, microsecond=999_999)
    counters = build_counters("h", now, RateLimits())

    with pytest.raises(RateLimitExceeded) as exc_info:
        check_counters(counters, [3, 0, 0], now)

    assert exc_info.value.retry_after_seconds == 1


def test_write_contact_reads_three_counters_and_writes_four_documents() -> None:
    docs: dict = {}
    counters = build_counters("h", NOW, RateLimits())
    refs = [FakeRef("rl", c.doc_id) for c in counters]
    transaction = FakeTransaction(docs)

    write_contact(transaction, refs, counters, FakeRef("contacts", "c1"), {"x": 1}, NOW)

    assert transaction.read_count == 3
    assert transaction.write_count == 4


def test_write_contact_writes_nothing_when_limited() -> None:
    counters = build_counters("h", NOW, RateLimits(site_per_day=1))
    docs = {("rl", counters[2].doc_id): {"count": 1}}
    refs = [FakeRef("rl", c.doc_id) for c in counters]
    transaction = FakeTransaction(docs)

    with pytest.raises(RateLimitExceeded):
        write_contact(transaction, refs, counters, FakeRef("contacts", "c1"), {"x": 1}, NOW)

    assert transaction.write_count == 0


def test_exceeded_cache_rejects_known_full_counters_until_their_window_ends() -> None:
    cache = ExceededCounterCache()
    counters = build_counters("h", NOW, RateLimits())
    cache.check(counters, NOW)

    cache.add([counters[0]], NOW)

    with pytest.raises(RateLimitExceeded) as exc_info:
        cache.check(counters, NOW)
    assert exc_info.value.scopes == ["ip_hour"]
    assert exc_info.value.retry_after_seconds == 55 * 60 + 55
    # Another client, and the same client in the next hour, use other counters.
    cache.check(build_counters("other", NOW, RateLimits()), NOW)
    next_hour = NOW.replace(hour=4, minute=0, second=0)
    cache.check(build_counters("h", next_hour, RateLimits()), next_hour)


def test_exceeded_cache_keeps_its_size_bounded() -> None:
    cache = ExceededCounterCache(max_entries=2)
    a, b, c = (build_counters(ip, NOW, RateLimits())[0] for ip in ("a", "b", "c"))

    cache.add([a], NOW)
    cache.add([b], NOW)
    cache.add([c], NOW)

    # The oldest entry was dropped; the newer ones are still known.
    cache.check([a], NOW)
    for counter in (b, c):
        with pytest.raises(RateLimitExceeded):
            cache.check([counter], NOW)


def test_exceeded_cache_drops_expired_entries_first() -> None:
    cache = ExceededCounterCache(max_entries=2)
    old = build_counters("a", NOW, RateLimits())[0]
    later = NOW.replace(hour=5)
    current = build_counters("b", later, RateLimits())[0]
    newest = build_counters("c", later, RateLimits())[0]

    cache.add([old], NOW)
    cache.add([current], later)
    cache.add([newest], later)

    for counter in (current, newest):
        with pytest.raises(RateLimitExceeded):
            cache.check([counter], later)
