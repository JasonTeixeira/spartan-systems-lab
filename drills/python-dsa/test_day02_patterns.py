"""Unit & performance-bound tests for Day 02 DSA patterns."""
from __future__ import annotations

import pytest
from day02_stacks_heaps_binary_search import (
    min_worker_capacity,
    next_greater_latency,
    sliding_window_max,
    top_k_noisy_tenants,
)


def test_next_greater_latency() -> None:
    assert next_greater_latency([2, 1, 2, 4, 3]) == [4, 2, 4, -1, -1]
    assert next_greater_latency([5, 4, 3]) == [-1, -1, -1]


def test_top_k_noisy_tenants() -> None:
    events = ["t1", "t2", "t1", "t3", "t2", "t1", "t4"]
    assert top_k_noisy_tenants(events, 2) == ["t1", "t2"]


def test_min_worker_capacity() -> None:
    assert min_worker_capacity([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5) == 15
    assert min_worker_capacity([3, 2, 2, 4, 1, 4], 3) == 6


def test_sliding_window_max() -> None:
    assert sliding_window_max([1, 3, -1, -3, 5, 3, 6, 7], 3) == [3, 3, 5, 5, 6, 7]
    with pytest.raises(ValueError):
        sliding_window_max([1, 2], 0)
