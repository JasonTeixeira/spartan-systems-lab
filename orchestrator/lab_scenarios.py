"""Compatibility shim re-exporting immutable Crucible Lab Engine & SLA Grader."""
from __future__ import annotations

from orchestrator.grader import (
    LAB_FAULTS,
    RealLabFault,
    arm_scenario_fault,
    collect_live_daemons,
    provision_workspace,
    verify_workspace_sla,
)

__all__ = [
    "LAB_FAULTS",
    "RealLabFault",
    "arm_scenario_fault",
    "collect_live_daemons",
    "provision_workspace",
    "verify_workspace_sla",
]
