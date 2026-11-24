"""
SPARTAN COLD DRILL - DAY 04 (Intervals, Prefix Tries, Dynamic Programming & LRU Cache)

Covers the final 3 of 14 core L5/L6 patterns:
  - Pattern 12: Merge Maintenance Windows (Sort + Greedy Intervals)
  - Pattern 13: Prefix Trie (Route / Autocomplete Matcher)
  - Pattern 14: Bottom-Up DP + O(1) LRU Cache

Verify with: uv run pytest drills/python-dsa/test_day04_patterns.py -v
"""
from __future__ import annotations


def merge_maintenance_windows(windows: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """
    Pattern 12 (Intervals, O(N log N)):
    Merge all overlapping or touching [start, end] maintenance windows
    and return sorted disjoint windows.
    """
    raise NotImplementedError("Drill 4A: implement merge_maintenance_windows")


class PrefixTrie:
    """Pattern 13 (Prefix Trie, O(L) insert/search/starts_with)."""

    def __init__(self) -> None:
        raise NotImplementedError("Drill 4B: implement PrefixTrie")

    def insert(self, word: str) -> None:
        raise NotImplementedError

    def search(self, word: str) -> bool:
        raise NotImplementedError

    def starts_with(self, prefix: str) -> bool:
        raise NotImplementedError


def min_shards_for_target(shard_sizes: list[int], target_capacity: int) -> int:
    """
    Pattern 14A (Bottom-Up 1D Dynamic Programming — Coin Change, O(N * target)):
    Return the fewest shards (unlimited copies of each size) needed to hit
    exact `target_capacity`, or -1 if impossible.
    """
    raise NotImplementedError("Drill 4C: implement min_shards_for_target")


class LRUCache:
    """Pattern 14B (HashMap + Doubly-Linked List / OrderedDict, O(1) get & put)."""

    def __init__(self, capacity: int) -> None:
        raise NotImplementedError("Drill 4D: implement LRUCache")

    def get(self, key: str) -> int | None:
        raise NotImplementedError

    def put(self, key: str, value: int) -> None:
        raise NotImplementedError
