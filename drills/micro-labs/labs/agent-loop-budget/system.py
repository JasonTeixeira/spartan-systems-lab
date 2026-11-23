"""Fixed local tool loop: attempt bounds require returning provider/tool calls."""

import itertools
import json


def run(requests, budget=4):
    if type(budget) is not int or not 1 <= budget <= 32:
        raise ValueError("attempt budget must be an integer1..32")
    source = iter(requests)
    trace, results = [], []

    def report(stop):
        return {
            "attempts": len(trace),
            "stop": stop,
            "results": results,
            "trace": trace,
        }

    for index in range(budget):
        try:
            request = next(source)
        except StopIteration:
            return report("input-exhausted")
        # Every returned request is charged BEFORE any validation/authorization branch.
        row = {"attempt": index + 1, "outcome": "malformed"}
        trace.append(row)
        if (
            type(request) is not dict
            or set(request) != {"tool", "input"}
            or type(request["tool"]) is not str
            or not 1 <= len(request["tool"]) <= 32
            or type(request["input"]) is not dict
        ):
            continue
        tool, arguments = request["tool"], request["input"]
        if tool not in ("total", "finish"):
            row["outcome"] = "denied"
            continue
        if tool == "finish":
            if arguments:
                row["outcome"] = "invalid-arguments"
                continue
            row["outcome"] = "finish-request"
            return report("requested-finish")
        values = arguments.get("values")
        if (
            set(arguments) != {"values"}
            or type(values) is not list
            or not 1 <= len(values) <= 16
            or any(type(value) is not int or not -1000000 <= value <= 1000000 for value in values)
        ):
            row["outcome"] = "invalid-arguments"
            continue
        results.append(sum(values))  # Only fixed, pure local arithmetic is available.
        row["outcome"] = "executed"
    return report("budget")


def demo():
    denied = run(itertools.repeat({"tool": "delete", "input": {}}))
    mixed = run(
        [
            {"tool": "delete", "input": {"approval": "APPROVED"}},
            {"tool": "total", "input": {"values": [1, -2, 4]}},
            {"tool": "total", "input": {"values": [True]}},
            {"tool": "finish", "input": {}},
        ]
    )
    return {
        "all_denied": denied,
        "mixed": mixed,
        "limits": "Scripted requests and pure local sum, no model/API/tool sandbox. Attempt bound assumes iterator and arithmetic return; no wall-clock/provider/cost bound or verified goal success. Fixed grants are trusted code, not approval text. No original sources or learner history written.",
    }


if __name__ == "__main__":
    print(json.dumps(demo(), indent=2))
