"""Unit tests for Day 04 Intervals, Trie, DP & LRU Cache patterns."""
from __future__ import annotations

from day04_dp_intervals_tries import (
    LRUCache,
    PrefixTrie,
    merge_maintenance_windows,
    min_shards_for_target,
)


def test_merge_maintenance_windows() -> None:
    assert merge_maintenance_windows([(1, 3), (2, 6), (8, 10), (10, 12)]) == [(1, 6), (8, 12)]
    assert merge_maintenance_windows([]) == []


def test_prefix_trie() -> None:
    trie = PrefixTrie()
    trie.insert("payments")
    trie.insert("payout")
    assert trie.search("payments") is True
    assert trie.search("pay") is False
    assert trie.starts_with("pay") is True


def test_min_shards_for_target() -> None:
    assert min_shards_for_target([1, 3, 4], 6) == 2
    assert min_shards_for_target([2], 3) == -1


def test_lru_cache() -> None:
    cache = LRUCache(2)
    cache.put("a", 1)
    cache.put("b", 2)
    assert cache.get("a") == 1
    cache.put("c", 3)
    assert cache.get("b") is None
    assert cache.get("c") == 3
