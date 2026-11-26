"""Verify all 8 Firecracker Build-From-Scratch projects:
1. Starter code fails (0/5 stages pass).
2. Reference code passes 5/5 stages cleanly with zero errors.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from orchestrator.build_projects import (
    BUILD_PROJECTS,
    list_build_projects,
    run_project_stage_tests,
    scaffold_project_workspace,
)


def _local_env(root: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["HOME"] = str(root)
    return env


def test_all_8_build_projects_starter_fails_and_reference_passes() -> None:
    projects = list_build_projects()
    assert len(projects) == 8, f"Expected 8 build projects, got {len(projects)}"

    for pid in BUILD_PROJECTS:
        with tempfile.TemporaryDirectory(prefix=f"crucible-proj-{pid}-") as td:
            root = Path(td)
            scaffold_project_workspace(root, pid, use_reference=False)
            res_starter = run_project_stage_tests(root, pid, _local_env, lambda: None)
            assert res_starter["all_passed"] is False, f"[{pid}] starter code unexpectedly passed!"
            assert res_starter["stages_passed"] == 0, f"[{pid}] starter code passed {res_starter['stages_passed']} stages!"

            scaffold_project_workspace(root, pid, use_reference=True)
            res_ref = run_project_stage_tests(root, pid, _local_env, lambda: None)
            assert res_ref["all_passed"] is True, f"[{pid}] reference code failed: {res_ref['stages']}"
            assert res_ref["stages_passed"] == 5
