"""Trusted runner: the only component that dispatches simulator calls.

It re-validates the plan, requires an approval bound to the exact plan hash, enforces
the budget and records every tool outcome. The agent never reaches this code path
directly; it only produces plans and reads the resulting evidence.
"""

from __future__ import annotations

import platform
import time
from typing import Callable, Optional

from pydantic import ValidationError

from . import SIMULATOR_VERSION, __version__, catalog
from .analysis import analyze
from .policy import ApprovalError, approval_matches, validate_plan
from .schemas import (
    Approval,
    EvidenceBundle,
    ExperimentPlan,
    PairResult,
    SimulateRequest,
    SimulateResult,
    ToolCallRecord,
    utc_now,
)
from .simulator import SimulationError
from .store import EvidenceStore, new_id

ToolTable = dict[str, Callable[[SimulateRequest], SimulateResult]]


class PolicyRejected(PermissionError):
    def __init__(self, decision):
        super().__init__(f"plan {decision.plan_id} rejected: {decision.reasons}")
        self.decision = decision


def versions() -> dict[str, str]:
    return {
        "app": __version__,
        "simulator": SIMULATOR_VERSION,
        "python": platform.python_version(),
    }


def record_id(run_id: str, seed: int, arm: str) -> str:
    return f"{run_id}/seed-{seed}/{arm}"


def _request(plan: ExperimentPlan, arm: str, seed: int) -> SimulateRequest:
    spec = plan.baseline if arm == "baseline" else plan.intervention
    return SimulateRequest(workload=plan.workload, servers=spec.servers, duration=plan.duration,
                           seed=seed, sham_label=spec.sham_label)


def run_plan(
    plan: ExperimentPlan,
    approval: Optional[Approval],
    store: Optional[EvidenceStore] = None,
    tools: Optional[ToolTable] = None,
) -> EvidenceBundle:
    tools = tools if tools is not None else catalog.TOOL_CATALOG
    decision = validate_plan(plan)
    if store:
        store.save_policy_decision(decision)
    if not decision.allowed:
        raise PolicyRejected(decision)  # no simulator call is made
    if not approval_matches(plan, approval):
        raise ApprovalError("no approval bound to this exact plan version; edits invalidate prior approval")

    run_id = new_id("run")
    started = utc_now()
    calls: list[ToolCallRecord] = []
    errors: list[str] = []
    tool_name = "queue.simulate"
    budget = catalog.MAX_SIM_CALLS_PER_PLAN

    for seed in plan.seeds:
        for arm in ("baseline", "intervention"):
            if len(calls) >= budget:
                errors.append(f"budget exhausted after {len(calls)} calls")
                break
            req = _request(plan, arm, seed)
            rid = record_id(run_id, seed, arm)
            t0 = time.perf_counter()
            try:
                result = tools[tool_name](req)
                calls.append(ToolCallRecord(record_id=rid, tool=tool_name, arm=arm, seed=seed, request=req,
                                            outcome="ok", result=result,
                                            elapsed_ms=round((time.perf_counter() - t0) * 1000, 3)))
            except (SimulationError, ValidationError, KeyError) as exc:
                msg = f"{rid}: {type(exc).__name__}: {exc}"
                errors.append(msg)
                calls.append(ToolCallRecord(record_id=rid, tool=tool_name, arm=arm, seed=seed, request=req,
                                            outcome="error", error=str(exc),
                                            elapsed_ms=round((time.perf_counter() - t0) * 1000, 3)))

    by_id = {c.record_id: c for c in calls}
    pairs: list[PairResult] = []
    for seed in plan.seeds:
        b = by_id.get(record_id(run_id, seed, "baseline"))
        i = by_id.get(record_id(run_id, seed, "intervention"))
        if not (b and i and b.result and i.result):
            continue
        bv = getattr(b.result, plan.metric)
        iv = getattr(i.result, plan.metric)
        pairs.append(PairResult(seed=seed, baseline_record=b.record_id, intervention_record=i.record_id,
                                baseline_value=bv, intervention_value=iv, difference=bv - iv))

    analysis = None
    if not errors and len(pairs) == len(plan.seeds):
        analysis = analyze(pairs, plan.metric, plan.decision_rule)

    bundle = EvidenceBundle(
        run_id=run_id,
        plan=plan,
        plan_hash=plan.plan_hash(),
        approval=approval,
        policy_decision=decision,
        tool_calls=calls,
        pairs=pairs,
        analysis=analysis,
        status="completed" if analysis else "failed",
        errors=errors,
        mode=plan.proposer.mode,
        versions=versions(),
        started_at=started,
        finished_at=utc_now(),
    )
    bundle.bundle_sha256 = bundle.content_hash()
    if store:
        store.save_bundle(bundle)
    return bundle
