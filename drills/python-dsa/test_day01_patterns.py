import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from day01_patterns import (  # noqa: E402
    deduplicate_events_keep_latest,
    retry_with_backoff,
    stream_in_batches,
)


def test_deduplicate_events_keep_latest() -> None:
    events: list[dict[str, object]] = [
        {"idempotency_key": "k1", "timestamp": 100, "val": "old"},
        {"idempotency_key": "k2", "timestamp": 50, "val": "only"},
        {"idempotency_key": "k1", "timestamp": 200, "val": "newest"},
        {"idempotency_key": "k1", "timestamp": 150, "val": "stale"},
    ]
    out = deduplicate_events_keep_latest(events)
    assert set(out.keys()) == {"k1", "k2"}
    assert out["k1"]["val"] == "newest"
    assert out["k2"]["val"] == "only"


def test_stream_in_batches_is_lazy_and_exact() -> None:
    seen = 0

    def infinite_source():
        nonlocal seen
        i = 0
        while True:
            seen += 1
            yield i
            i += 1

    gen = stream_in_batches(infinite_source(), batch_size=3)
    first = next(gen)
    assert first == [0, 1, 2]
    # Must NOT eagerly consume the whole stream
    assert seen <= 4

    assert list(stream_in_batches(range(7), batch_size=3)) == [[0, 1, 2], [3, 4, 5], [6]]
    assert list(stream_in_batches([], batch_size=3)) == []
    with pytest.raises(ValueError):
        list(stream_in_batches([1, 2], batch_size=0))


def test_retry_with_backoff_succeeds_and_records_delays() -> None:
    delays: list[float] = []
    attempts = {"count": 0}

    def flaky() -> str:
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise ConnectionError("transient")
        return "ok"

    result = retry_with_backoff(flaky, max_attempts=3, base_delay=0.5, sleep_fn=delays.append)
    assert result == "ok"
    assert delays == [0.5, 1.0]


def test_retry_with_backoff_exhausts_without_trailing_sleep() -> None:
    delays: list[float] = []

    def always_fail() -> None:
        raise TimeoutError("down")

    with pytest.raises(TimeoutError):
        retry_with_backoff(always_fail, max_attempts=3, base_delay=0.25, sleep_fn=delays.append)
    assert delays == [0.25, 0.5]
