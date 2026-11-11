"""Independent verifier: integrity check, recomputation and full replay.

It reads the raw evidence JSON, never reuses runner state, re-executes every recorded
simulator call from the recorded plan and compares results exactly. Verification is
reported separately from the scientific outcome.
"""

from __future__ import annotations

import math
from typing import Any

from pydantic import ValidationError

from .analysis import analyze
from .policy import validate_plan
from .schemas import EvidenceBundle, PairResult, VerificationCheck, VerificationReport
from .simulator import simulate

_REL_TOL = 1e-12


def _close(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=_REL_TOL, abs_tol=1e-12)


def verify_bundle(raw: dict[str, Any]) -> VerificationReport:
    run_id = str(raw.get("run_id", "unknown"))
    checks: list[VerificationCheck] = []

    def add(name: str, ok: bool, detail: str = "") -> None:
        checks.append(VerificationCheck(name=name, passed=bool(ok), detail=detail))

    try:
        bundle = EvidenceBundle.model_validate(raw)
    except ValidationError as exc:
        add("schema_valid", False, f"evidence does not match schema: {exc.error_count()} error(s)")
        return VerificationReport(run_id=run_id, verified=False, status="failed", checks=checks, replayed_calls=0)
    add("schema_valid", True)

    recomputed_hash = bundle.content_hash()
    add("bundle_hash", recomputed_hash == bundle.bundle_sha256,
        f"recorded={bundle.bundle_sha256[:16]}... recomputed={recomputed_hash[:16]}...")

    plan_hash = bundle.plan.plan_hash()
    add("plan_hash", plan_hash == bundle.plan_hash, "recorded plan matches recorded plan hash")
    add("approval_bound", bundle.approval.plan_hash == plan_hash and bundle.approval.plan_id == bundle.plan.plan_id,
        "approval references this exact plan version")
    add("policy_allowed", validate_plan(bundle.plan).allowed, "plan passes the policy gate on re-check")

    expected = {(s, arm) for s in bundle.plan.seeds for arm in ("baseline", "intervention")}
    recorded = {(c.seed, c.arm) for c in bundle.tool_calls}
    add("calls_match_plan", expected == recorded and len(bundle.tool_calls) == len(expected),
        f"expected {len(expected)} calls, recorded {len(bundle.tool_calls)}")

    # Full replay of every recorded call from the recorded request.
    replay_ok, mismatches, replayed = True, [], 0
    replay_values: dict[str, float] = {}
    for call in bundle.tool_calls:
        spec = bundle.plan.baseline if call.arm == "baseline" else bundle.plan.intervention
        if (call.request.workload, call.request.servers, call.request.duration, call.request.seed,
                call.request.sham_label) != (bundle.plan.workload, spec.servers, bundle.plan.duration,
                                             call.seed, spec.sham_label):
            replay_ok = False
            mismatches.append(f"{call.record_id}: request differs from plan")
            continue
        try:
            fresh = simulate(call.request)
        except Exception as exc:  # replay must not crash the verifier
            replay_ok = False
            mismatches.append(f"{call.record_id}: replay error {exc}")
            continue
        replayed += 1
        replay_values[call.record_id] = getattr(fresh, bundle.plan.metric)
        if call.outcome != "ok" or call.result is None or fresh.model_dump() != call.result.model_dump():
            replay_ok = False
            mismatches.append(f"{call.record_id}: recorded result differs from replay")
    add("replay_matches", replay_ok, "; ".join(mismatches[:5]) or f"{replayed} calls replayed exactly")

    # Recompute paired differences from replayed values and compare to recorded pairs.
    pairs_ok, recomputed_pairs = True, []
    for p in bundle.pairs:
        b = replay_values.get(p.baseline_record)
        i = replay_values.get(p.intervention_record)
        if b is None or i is None or not (_close(b, p.baseline_value) and _close(i, p.intervention_value)
                                          and _close(b - i, p.difference)):
            pairs_ok = False
            continue
        recomputed_pairs.append(PairResult(seed=p.seed, baseline_record=p.baseline_record,
                                           intervention_record=p.intervention_record,
                                           baseline_value=b, intervention_value=i, difference=b - i))
    pairs_ok = pairs_ok and len(bundle.pairs) == len(bundle.plan.seeds)
    add("paired_differences", pairs_ok, f"{len(recomputed_pairs)}/{len(bundle.pairs)} pairs recomputed exactly")

    if bundle.analysis and pairs_ok:
        fresh_a = analyze(recomputed_pairs, bundle.plan.metric, bundle.plan.decision_rule)
        rec = bundle.analysis
        same = (fresh_a.outcome == rec.outcome and _close(fresh_a.mean_difference, rec.mean_difference)
                and _close(fresh_a.ci_low, rec.ci_low) and _close(fresh_a.ci_high, rec.ci_high))
        add("analysis_matches", same, f"recorded outcome={rec.outcome}, recomputed outcome={fresh_a.outcome}")
    else:
        add("analysis_matches", False, "no analysis recorded or pairs could not be recomputed")

    ok = all(c.passed for c in checks)
    return VerificationReport(run_id=bundle.run_id, verified=ok, status="verified" if ok else "failed",
                              checks=checks, replayed_calls=replayed)
