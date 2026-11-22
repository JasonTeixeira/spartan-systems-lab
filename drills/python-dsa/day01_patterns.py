"""
SPARTAN COLD DRILL - DAY 01 (Python Production Patterns & DSA Fundamentals)

RULES:
  1. Close AI autocomplete. Open ONLY your PDF field manual if needed.
  2. Set a 15-minute timer.
  3. Implement all 3 functions below, then verify with: make drill-py
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from typing import TypeVar

T = TypeVar("T")


def deduplicate_events_keep_latest(
    events: list[dict[str, object]],
) -> dict[str, dict[str, object]]:
    """
    Concept #1 (Hash-Map Lookup, O(N)):
    Given a list of event dicts each having keys:
      - 'idempotency_key': str
      - 'timestamp': int (unix epoch seconds)
    Return a dict mapping each unique idempotency_key to the event dict
    with the HIGHEST timestamp (ties keep the latest seen in input).
    Must run in O(N) time.
    """
    raise NotImplementedError("Spartan Drill 1A: implement deduplicate_events_keep_latest")


def stream_in_batches(records: Iterable[T], batch_size: int) -> Iterator[list[T]]:
    """
    Concept #2 (Lazy Streaming Generator, O(batch_size) RAM):
    Yield consecutive lists of up to `batch_size` items from any iterable/generator
    WITHOUT converting the entire input into a list in memory.
    Raise ValueError if batch_size <= 0.
    """
    raise NotImplementedError("Spartan Drill 1B: implement stream_in_batches")


def retry_with_backoff(
    fn: Callable[[], T],
    *,
    max_attempts: int = 3,
    base_delay: float = 0.1,
    sleep_fn: Callable[[float], None],
) -> T:
    """
    Concept #7 (Exponential Backoff Retry):
    Call `fn()`. If it raises an Exception, retry up to `max_attempts` total attempts.
    Before attempt k (1-indexed failure), call `sleep_fn(base_delay * (2 ** (attempt - 1)))`.
    Do NOT sleep after the final failed attempt; re-raise the last exception.
    Raise ValueError if max_attempts < 1.
    """
    raise NotImplementedError("Spartan Drill 1C: implement retry_with_backoff")
