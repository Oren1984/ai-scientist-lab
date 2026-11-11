import json

import pytest

from scientist_lab import catalog
from scientist_lab.analysis import analyze, t_crit_975
from scientist_lab.policy import ApprovalError, approval_matches, approve, validate_plan
from scientist_lab.proposer import ScriptedProposer, follow_up
from scientist_lab.report import render_markdown
from scientist_lab.runner import PolicyRejected, run_plan
from scientist_lab.schemas import DecisionRule, PairResult
from scientist_lab.store import atomic_write_text
from scientist_lab.verifier import verify_bundle


class SpyTools(dict):
    def __init__(self):
        super().__init__()
        self.calls = 0

        def spy(req):
            self.calls += 1
            return catalog.TOOL_CATALOG["queue.simulate"](req)

        self["queue.simulate"] = spy


# ---------------------------------------------------------------- scenarios
def test_supported_scenario(approved, store):
    bundle = run_plan(*approved("capacity"), store=store)
    assert bundle.status == "completed"
    assert bundle.analysis.outcome == "supported"
    assert bundle.analysis.ci_low > 0


def test_sham_scenario_yields_exact_zero(approved, store):
    bundle = run_plan(*approved("sham"), store=store)
    assert all(p.difference == 0.0 for p in bundle.pairs)
    assert bundle.analysis.max_abs_difference == 0.0
    assert bundle.analysis.outcome == "supported"  # the null hypothesis of "no change" holds


def test_low_benefit_scenario_is_not_supported(approved, store):
    bundle = run_plan(*approved("low_benefit"), store=store)
    assert bundle.analysis.outcome == "contradicted"
    assert bundle.analysis.ci_high < bundle.plan.decision_rule.min_effect


def test_few_seeds_can_be_inconclusive():
    pairs = [PairResult(seed=i, baseline_record="b", intervention_record="i", baseline_value=1.0,
                        intervention_value=1.0 - d, difference=d) for i, d in enumerate([0.5, -0.2, 0.05])]
    a = analyze(pairs, "mean_wait", DecisionRule(kind="paired_mean_reduction", min_effect=0.1))
    assert a.outcome == "inconclusive"


def test_t_critical_values():
    assert t_crit_975(1) == 12.706 and t_crit_975(19) == 2.093
    assert abs(t_crit_975(49) - 2.0096) < 2e-3


# ---------------------------------------------------------------- reproducibility
def test_same_approved_plan_same_evidence(approved, store):
    plan, approval = approved("capacity")
    first = run_plan(plan, approval, store=store)
    second = run_plan(plan, approval, store=store)
    assert first.run_id != second.run_id
    assert first.evidence_fingerprint() == second.evidence_fingerprint()


# ---------------------------------------------------------------- policy and approval
def test_rejected_plan_makes_no_simulator_call(approved, store):
    plan = ScriptedProposer().propose("capacity").model_copy(update={"workload": "extreme"})
    decision = validate_plan(plan)
    assert not decision.allowed and any("workload_allowed" in r for r in decision.reasons)
    spy = SpyTools()
    with pytest.raises(PolicyRejected):
        run_plan(plan, None, store=store, tools=spy)
    assert spy.calls == 0
    assert any(not d.allowed for d in store.list_policy_decisions())  # rejection recorded with reason


@pytest.mark.parametrize("update, reason", [
    ({"seeds": [1, 2]}, "seed_count"),
    ({"seeds": [5, 5, 5]}, "seeds_unique"),
    ({"seeds": list(range(51))}, "seed_count"),
    ({"duration": 5000.0}, "duration_in_range"),
    ({"metric": "throughput"}, "metric_allowed"),
    ({"tools": ["shell.exec"]}, "tools_in_catalog"),
    ({"intervention_kind": "teleport"}, "intervention_kind_allowed"),
])
def test_out_of_scope_plans_rejected(update, reason):
    plan = ScriptedProposer().propose("capacity").model_copy(update=update)
    decision = validate_plan(plan)
    assert not decision.allowed
    assert any(r.startswith(reason) for r in decision.reasons), decision.reasons


def test_budget_enforced():
    plan = ScriptedProposer().propose("capacity").model_copy(
        update={"seeds": list(range(50)), "duration": 2000.0})
    reasons = validate_plan(plan).reasons
    assert any(r.startswith("budget_sim_time") for r in reasons)


def test_sham_must_not_change_servers():
    plan = ScriptedProposer().propose("sham")
    bad = plan.model_copy(update={"intervention": plan.intervention.model_copy(update={"servers": 3})})
    assert any(r.startswith("sham_changes_nothing") for r in validate_plan(bad).reasons)


def test_cannot_approve_rejected_plan():
    plan = ScriptedProposer().propose("capacity").model_copy(update={"workload": "extreme"})
    with pytest.raises(ApprovalError):
        approve(plan, validate_plan(plan), "tester")


def test_edit_invalidates_prior_approval(approved, store):
    plan, approval = approved("capacity")
    edited = plan.model_copy(update={"duration": 600.0})
    assert edited.plan_id == plan.plan_id and edited.plan_hash() != plan.plan_hash()
    assert not approval_matches(edited, approval)
    spy = SpyTools()
    with pytest.raises(ApprovalError):
        run_plan(edited, approval, store=store, tools=spy)
    assert spy.calls == 0


def test_run_without_approval_refused(store):
    spy = SpyTools()
    with pytest.raises(ApprovalError):
        run_plan(ScriptedProposer().propose("capacity"), None, store=store, tools=spy)
    assert spy.calls == 0


def test_follow_up_gets_new_plan_id():
    plan = ScriptedProposer().propose("low_benefit")
    nxt = follow_up(plan, seeds=[7, 8, 9, 10])
    assert nxt.plan_id != plan.plan_id and nxt.parent_plan_id == plan.plan_id


def test_tool_error_is_recorded_and_run_fails(approved, store):
    def broken(req):
        from scientist_lab.simulator import SimulationError
        raise SimulationError("synthetic failure")

    bundle = run_plan(*approved("capacity"), store=store, tools={"queue.simulate": broken})
    assert bundle.status == "failed" and bundle.analysis is None
    assert all(c.outcome == "error" and c.error for c in bundle.tool_calls)


# ---------------------------------------------------------------- verification
def test_replay_verifies(approved, store):
    bundle = run_plan(*approved("capacity"), store=store)
    report = verify_bundle(store.load_bundle_raw(bundle.run_id))
    assert report.verified and report.replayed_calls == 40


def _tamper(store, run_id, mutate, rehash=False):
    raw = store.load_bundle_raw(run_id)
    mutate(raw)
    if rehash:
        from scientist_lab.schemas import sha256_of
        raw.pop("bundle_sha256")
        raw["bundle_sha256"] = sha256_of(raw)
    return verify_bundle(raw)


def test_corrupted_metric_detected(approved, store):
    bundle = run_plan(*approved("capacity"), store=store)

    def mutate(raw):
        raw["tool_calls"][0]["result"]["mean_wait"] += 0.5

    report = _tamper(store, bundle.run_id, mutate)
    assert not report.verified
    failed = {c.name for c in report.checks if not c.passed}
    assert {"bundle_hash", "replay_matches"} <= failed


def test_forged_hash_still_caught_by_replay(approved, store):
    """Attacker edits results AND recomputes the bundle hash: replay still catches it."""
    bundle = run_plan(*approved("capacity"), store=store)

    def mutate(raw):
        for p in raw["pairs"]:
            p["intervention_value"] = 0.0
            p["difference"] = p["baseline_value"]
        raw["analysis"]["outcome"] = "supported"

    report = _tamper(store, bundle.run_id, mutate, rehash=True)
    failed = {c.name for c in report.checks if not c.passed}
    assert not report.verified and "bundle_hash" not in failed
    assert "paired_differences" in failed


def test_outcome_flip_detected(approved, store):
    bundle = run_plan(*approved("low_benefit"), store=store)
    report = _tamper(store, bundle.run_id, lambda raw: raw["analysis"].update(outcome="supported"), rehash=True)
    assert {c.name for c in report.checks if not c.passed} == {"analysis_matches"}


def test_plan_edit_after_run_detected(approved, store):
    bundle = run_plan(*approved("capacity"), store=store)
    report = _tamper(store, bundle.run_id, lambda raw: raw["plan"].update(duration=900.0), rehash=True)
    failed = {c.name for c in report.checks if not c.passed}
    assert {"plan_hash", "approval_bound"} <= failed


def test_malformed_evidence_fails_cleanly():
    report = verify_bundle({"run_id": "run-x", "plan": "nonsense"})
    assert not report.verified and report.checks[0].name == "schema_valid"


# ---------------------------------------------------------------- storage and report
def test_evidence_is_write_once(approved, store):
    bundle = run_plan(*approved("sham"), store=store)
    with pytest.raises(FileExistsError):
        store.save_bundle(bundle)


def test_atomic_write_leaves_no_temp_files(tmp_path):
    target = tmp_path / "x" / "f.json"
    atomic_write_text(target, json.dumps({"a": 1}))
    atomic_write_text(target, json.dumps({"a": 2}))
    assert json.loads(target.read_text()) == {"a": 2}
    assert [p.name for p in target.parent.iterdir()] == ["f.json"]


def test_report_cites_run_records(approved, store):
    bundle = run_plan(*approved("capacity"), store=store)
    md = render_markdown(bundle, verify_bundle(store.load_bundle_raw(bundle.run_id)))
    for section in ("## Question", "## Hypothesis", "## Pre-registered plan", "## Actual runs", "## Metrics",
                    "## Verification", "## Result", "## Limitations"):
        assert section in md
    for p in bundle.pairs:
        assert p.baseline_record in md and p.intervention_record in md
    assert "SUPPORTED" in md and "scripted" in md
