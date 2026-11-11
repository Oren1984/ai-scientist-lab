"""Independent policy gate and approval binding.

The gate never trusts the proposer: it re-checks every field against the allowed
parameter space, the fixed tool catalog and the run budgets.
"""

from __future__ import annotations

import uuid

from . import catalog, simulator
from .schemas import Approval, ExperimentPlan, PolicyCheck, PolicyDecision


class ApprovalError(PermissionError):
    """Raised when execution is attempted without a valid approval for the exact plan."""


def validate_plan(plan: ExperimentPlan) -> PolicyDecision:
    checks: list[PolicyCheck] = []

    def check(name: str, ok: bool, detail: str) -> None:
        checks.append(PolicyCheck(name=name, passed=bool(ok), detail=detail))

    check("workload_allowed", plan.workload in simulator.WORKLOADS,
          f"workload={plan.workload!r}; allowed={sorted(simulator.WORKLOADS)}")
    for arm in (plan.baseline, plan.intervention):
        check(f"{arm.label}_servers_in_range",
              simulator.MIN_SERVERS <= arm.servers <= simulator.MAX_SERVERS,
              f"servers={arm.servers}; allowed=[{simulator.MIN_SERVERS}, {simulator.MAX_SERVERS}]")
    check("duration_in_range", simulator.MIN_DURATION <= plan.duration <= simulator.MAX_DURATION,
          f"duration={plan.duration}; allowed=[{simulator.MIN_DURATION}, {simulator.MAX_DURATION}]")
    check("metric_allowed", plan.metric in catalog.ALLOWED_METRICS,
          f"metric={plan.metric!r}; allowed={list(catalog.ALLOWED_METRICS)}")
    check("tools_in_catalog", bool(plan.tools) and all(t in catalog.TOOL_CATALOG for t in plan.tools),
          f"tools={plan.tools}; catalog={sorted(catalog.TOOL_CATALOG)}")

    n = len(plan.seeds)
    check("seed_count", catalog.MIN_SEEDS <= n <= catalog.MAX_SEEDS,
          f"n_seeds={n}; allowed=[{catalog.MIN_SEEDS}, {catalog.MAX_SEEDS}]")
    check("seeds_unique", len(set(plan.seeds)) == n, "each pair needs a distinct seed")
    check("seeds_in_range", all(0 <= s <= simulator.MAX_SEED for s in plan.seeds),
          f"seeds must be in [0, {simulator.MAX_SEED}]")

    kind = plan.intervention_kind
    check("intervention_kind_allowed", kind in catalog.ALLOWED_INTERVENTIONS,
          f"intervention_kind={kind!r}; allowed={list(catalog.ALLOWED_INTERVENTIONS)}")
    if kind == "capacity":
        check("capacity_changes_only_servers",
              plan.baseline.servers != plan.intervention.servers
              and plan.baseline.sham_label is None and plan.intervention.sham_label is None,
              "capacity intervention must change server count and nothing else")
        check("decision_rule_matches", plan.decision_rule.kind == "paired_mean_reduction",
              f"capacity requires paired_mean_reduction, got {plan.decision_rule.kind}")
        check("min_effect_positive", plan.decision_rule.min_effect > 0,
              f"min_effect={plan.decision_rule.min_effect} must be > 0")
    elif kind == "sham":
        check("sham_changes_nothing", plan.baseline.servers == plan.intervention.servers,
              "sham arm must use the same server count as baseline")
        check("decision_rule_matches", plan.decision_rule.kind == "paired_null",
              f"sham requires paired_null, got {plan.decision_rule.kind}")
    check("confidence_allowed", plan.decision_rule.confidence == 0.95,
          f"confidence={plan.decision_rule.confidence}; only 0.95 is supported")

    calls = 2 * n
    sim_time = calls * plan.duration
    check("budget_calls", calls <= catalog.MAX_SIM_CALLS_PER_PLAN,
          f"calls={calls}; budget={catalog.MAX_SIM_CALLS_PER_PLAN}")
    check("budget_sim_time", sim_time <= catalog.MAX_SIM_TIME_PER_PLAN,
          f"simulated_time={sim_time}; budget={catalog.MAX_SIM_TIME_PER_PLAN}")

    reasons = [f"{c.name}: {c.detail}" for c in checks if not c.passed]
    return PolicyDecision(
        decision_id=f"pol-{uuid.uuid4().hex[:12]}",
        plan_id=plan.plan_id,
        plan_hash=plan.plan_hash(),
        allowed=not reasons,
        reasons=reasons,
        checks=checks,
    )


def approve(plan: ExperimentPlan, decision: PolicyDecision, approved_by: str) -> Approval:
    """Bind an operator approval to the exact validated plan (by hash)."""
    if not decision.allowed:
        raise ApprovalError(f"plan {plan.plan_id} was rejected by policy: {decision.reasons}")
    if decision.plan_hash != plan.plan_hash():
        raise ApprovalError("policy decision does not match this plan version; re-validate")
    if not approved_by.strip():
        raise ApprovalError("approver identity is required")
    return Approval(plan_id=plan.plan_id, plan_hash=plan.plan_hash(), approved_by=approved_by.strip())


def approval_matches(plan: ExperimentPlan, approval: Approval | None) -> bool:
    return approval is not None and approval.plan_id == plan.plan_id and approval.plan_hash == plan.plan_hash()
