"""Unit tests for Day 03 Graph, Union-Find & Tree patterns."""
from __future__ import annotations

import pytest
from day03_graphs_trees_union_find import (
    count_network_islands,
    resolve_build_order,
    shortest_service_latency,
    tree_level_order,
)


def test_resolve_build_order() -> None:
    order = resolve_build_order(["api", "db", "edge"], [("db", "api"), ("api", "edge")])
    assert order == ["db", "api", "edge"]
    with pytest.raises(ValueError):
        resolve_build_order(["a", "b"], [("a", "b"), ("b", "a")])


def test_shortest_service_latency() -> None:
    edges = [("edge", "gw", 2), ("gw", "api", 5), ("edge", "api", 10), ("api", "db", 3)]
    assert shortest_service_latency(edges, "edge", "db") == 10
    assert shortest_service_latency(edges, "db", "edge") == -1


def test_count_network_islands() -> None:
    assert count_network_islands(5, [(0, 1), (1, 2), (3, 4)]) == 2


def test_tree_level_order() -> None:
    tree: dict[str, object] = {
        "val": 1,
        "left": {"val": 2, "left": None, "right": None},
        "right": {"val": 3, "left": {"val": 4, "left": None, "right": None}, "right": None},
    }
    assert tree_level_order(tree) == [[1], [2, 3], [4]]
    assert tree_level_order(None) == []
