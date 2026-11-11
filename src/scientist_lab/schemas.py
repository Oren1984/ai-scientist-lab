"""Typed contracts shared by the proposer, policy gate, runner, verifier and UI."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

WorkloadName = Literal["light", "moderate", "heavy"]
InterventionKind = Literal["capacity", "sham"]
MetricName = Literal["mean_wait", "p95_wait"]
DecisionKind = Literal["paired_mean_reduction", "paired_null"]
Outcome = Literal["supported", "contradicted", "inconclusive"]
ProposerMode = Literal["scripted", "ollama"]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_of(data: Any) -> str:
    return hashlib.sha256(canonical_json(data).encode("utf-8")).hexdigest()


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ArmSpec(Strict):
    """One arm of the paired comparison. Only `servers` may differ between arms."""

    label: str = Field(min_length=1, max_length=40)
    servers: int
    sham_label: Optional[str] = Field(default=None, max_length=40)


class DecisionRule(Strict):
    kind: DecisionKind
    min_effect: float = 0.0
    confidence: float = 0.95
    tolerance: float = 1e-9


class ProposerInfo(Strict):
    mode: ProposerMode
    model: Optional[str] = None
    note: str = ""


class ExperimentPlan(Strict):
    """Pre-registered plan. Everything here is fixed before any simulator call."""

    plan_id: str
    parent_plan_id: Optional[str] = None
    question: str = Field(min_length=3, max_length=500)
    hypothesis: str = Field(min_length=3, max_length=500)
    workload: str
    duration: float
    baseline: ArmSpec
    intervention: ArmSpec
    intervention_kind: str
    metric: str
    seeds: list[int]
    comparison: str = "paired difference d_i = metric(baseline, seed_i) - metric(intervention, seed_i)"
    decision_rule: DecisionRule
    tools: list[str] = Field(default_factory=lambda: ["queue.simulate"])
    proposer: ProposerInfo
    created_at: str = Field(default_factory=utc_now)

    def plan_hash(self) -> str:
        return sha256_of(self.model_dump(mode="json"))


class PolicyCheck(Strict):
    name: str
    passed: bool
    detail: str = ""


class PolicyDecision(Strict):
    decision_id: str
    plan_id: str
    plan_hash: str
    allowed: bool
    reasons: list[str]
    checks: list[PolicyCheck]
    decided_at: str = Field(default_factory=utc_now)


class Approval(Strict):
    plan_id: str
    plan_hash: str
    approved_by: str
    approved_at: str = Field(default_factory=utc_now)


class SimulateRequest(Strict):
    """Typed input for the only tool in the catalog: `queue.simulate`."""

    workload: str
    servers: int
    duration: float
    seed: int
    sham_label: Optional[str] = None


class SimulateResult(Strict):
    n_customers: int
    mean_wait: float
    p95_wait: float
    max_wait: float
    utilization: float
    trace_sha256: str


class ToolCallRecord(Strict):
    record_id: str
    tool: str
    arm: Literal["baseline", "intervention"]
    seed: int
    request: SimulateRequest
    outcome: Literal["ok", "error"]
    error: Optional[str] = None
    result: Optional[SimulateResult] = None
    elapsed_ms: float = 0.0


class PairResult(Strict):
    seed: int
    baseline_record: str
    intervention_record: str
    baseline_value: float
    intervention_value: float
    difference: float


class Analysis(Strict):
    metric: str
    n_pairs: int
    mean_difference: float
    sd_difference: float
    ci_low: float
    ci_high: float
    min_difference: float
    max_difference: float
    max_abs_difference: float
    decision_kind: str
    outcome: Outcome
    rationale: str


class EvidenceBundle(Strict):
    schema_version: str = "evidence/1.0"
    run_id: str
    plan: ExperimentPlan
    plan_hash: str
    approval: Approval
    policy_decision: PolicyDecision
    tool_calls: list[ToolCallRecord]
    pairs: list[PairResult]
    analysis: Optional[Analysis]
    status: Literal["completed", "failed"]
    errors: list[str] = Field(default_factory=list)
    mode: ProposerMode
    versions: dict[str, str]
    started_at: str
    finished_at: str
    bundle_sha256: str = ""

    def content_hash(self) -> str:
        data = self.model_dump(mode="json")
        data.pop("bundle_sha256", None)
        return sha256_of(data)

    def evidence_fingerprint(self) -> str:
        """Hash of the scientific content only (no IDs or timestamps).

        The same approved plan must always produce the same fingerprint.
        """
        return sha256_of(
            {
                "plan_hash": self.plan_hash,
                "results": [
                    [c.arm, c.seed, c.request.model_dump(mode="json"),
                     c.result.model_dump(mode="json") if c.result else None]
                    for c in self.tool_calls
                ],
                "pairs": [[p.seed, p.baseline_value, p.intervention_value, p.difference] for p in self.pairs],
                "analysis": self.analysis.model_dump(mode="json") if self.analysis else None,
            }
        )


class VerificationCheck(Strict):
    name: str
    passed: bool
    detail: str = ""


class VerificationReport(Strict):
    run_id: str
    verified: bool
    status: Literal["verified", "failed"]
    checks: list[VerificationCheck]
    replayed_calls: int
    verified_at: str = Field(default_factory=utc_now)
