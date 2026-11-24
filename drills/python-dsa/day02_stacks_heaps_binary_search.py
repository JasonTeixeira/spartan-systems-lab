"""
SPARTAN COLD DRILL - DAY 02 (Stacks, Heaps, Binary Search on Answer & Sliding Window Max)

Covers 4 core L5/L6 patterns:
  - Pattern 4: Monotonic Stack (Next Greater Element / Latency Spike Span)
  - Pattern 5: Top-K Min-Heap (Streaming Heavy Hitters)
  - Pattern 6: Binary Search on Answer (Minimum Worker Fleet Capacity)
  - Pattern 7: Monotonic Deque (Sliding Window Maximum Telemetry)

Verify with: uv run pytest drills/python-dsa/test_day02_patterns.py -v
"""
from __future__ import annotations


def next_greater_latency(latencies: list[int]) -> list[int]:
    """
    Pattern 4 (Monotonic Decreasing Stack, O(N)):
    For each index i, return the next strictly greater value to the right,
    or -1 if none exists.
    """
    raise NotImplementedError("Drill 2A: implement next_greater_latency")


def top_k_noisy_tenants(tenant_ids: list[str], k: int) -> list[str]:
    """
    Pattern 5 (Hash-Count + Heap, O(N log K)):
    Return the k most frequent tenant_ids sorted by (-count, tenant_id).
    """
    raise NotImplementedError("Drill 2B: implement top_k_noisy_tenants")


def min_worker_capacity(job_weights: list[int], max_days: int) -> int:
    """
    Pattern 6 (Binary Search on Answer, O(N log(sum(weights)))):
    Jobs must be processed in order. Return the minimum daily capacity
    needed to finish all jobs within `max_days`.
    """
    raise NotImplementedError("Drill 2C: implement min_worker_capacity")


def sliding_window_max(values: list[int], window: int) -> list[int]:
    """
    Pattern 7 (Monotonic Deque, O(N)):
    Return the maximum value for every contiguous window of length `window`.
    Raise ValueError if window <= 0 or window > len(values).
    """
    raise NotImplementedError("Drill 2D: implement sliding_window_max")
