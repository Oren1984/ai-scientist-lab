"""Command-line interface.

    python -m scientist_lab propose --scenario capacity
    python -m scientist_lab validate <plan.json>
    python -m scientist_lab approve <plan.json> --by <name>
    python -m scientist_lab run <plan.json>
    python -m scientist_lab verify <run_id>
    python -m scientist_lab demo --approve-as <name>
    python -m scientist_lab list
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .policy import ApprovalError, approve, validate_plan
from .proposer import SCENARIOS, OllamaProposer, ProposerError, ScriptedProposer
from .report import render_markdown
from .runner import PolicyRejected, run_plan
from .schemas import Approval, ExperimentPlan
from .store import EvidenceStore
from .verifier import verify_bundle


def _load_plan(path: str) -> ExperimentPlan:
    return ExperimentPlan.model_validate_json(Path(path).read_text(encoding="utf-8"))


def _find_approval(store: EvidenceStore, plan: ExperimentPlan) -> Approval | None:
    path = store.root / "approvals" / f"{plan.plan_id}.{plan.plan_hash()[:12]}.json"
    return Approval.model_validate_json(path.read_text(encoding="utf-8")) if path.exists() else None


def _execute(store: EvidenceStore, plan: ExperimentPlan, approval: Approval | None) -> int:
    try:
        bundle = run_plan(plan, approval, store=store)
    except PolicyRejected as exc:
        print(f"REJECTED by policy (no simulator call made): {exc.decision.reasons}")
        return 2
    except ApprovalError as exc:
        print(f"NOT RUN: {exc}")
        return 3
    verification = verify_bundle(store.load_bundle_raw(bundle.run_id))
    store.save_verification(verification)
    store.save_report(bundle.run_id, render_markdown(bundle, verification))
    a = bundle.analysis
    print(f"run {bundle.run_id}: status={bundle.status} "
          f"outcome={a.outcome if a else 'n/a'} verification={verification.status}")
    if a:
        print(f"  mean d={a.mean_difference:.4f} 95% CI [{a.ci_low:.4f}, {a.ci_high:.4f}] - {a.rationale}")
    print(f"  evidence: {store.run_dir(bundle.run_id)}")
    return 0 if bundle.status == "completed" and verification.verified else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="scientist_lab", description="AI Scientist Lab V1.0 CLI")
    ap.add_argument("--data", help="evidence directory (default: $SCIENTIST_LAB_DATA or ./data)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("propose", help="propose a plan and save it for review")
    p.add_argument("--scenario", choices=sorted(SCENARIOS), default="capacity")
    p.add_argument("--ollama", metavar="QUESTION", help="use the local Ollama model for this question")
    p.add_argument("--out", help="write plan JSON here (default: print + store)")

    v = sub.add_parser("validate", help="run the policy gate on a plan file")
    v.add_argument("plan")

    a = sub.add_parser("approve", help="validate and approve a plan file (binds to its hash)")
    a.add_argument("plan")
    a.add_argument("--by", required=True, help="operator name recorded with the approval")

    r = sub.add_parser("run", help="execute an approved plan file")
    r.add_argument("plan")

    ver = sub.add_parser("verify", help="independently replay and verify a run")
    ver.add_argument("run_id")

    d = sub.add_parser("demo", help="propose, approve, run and verify all three scenarios")
    d.add_argument("--approve-as", required=True, help="operator name; passing it is the explicit approval")

    sub.add_parser("list", help="list stored runs")

    args = ap.parse_args(argv)
    store = EvidenceStore(Path(args.data) if args.data else None)

    if args.cmd == "propose":
        try:
            plan = OllamaProposer().propose(args.ollama) if args.ollama else ScriptedProposer().propose(args.scenario)
        except ProposerError as exc:
            print(f"proposal failed: {exc}")
            return 4
        path = Path(args.out) if args.out else store.save_plan(plan)
        if args.out:
            path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
        print(plan.model_dump_json(indent=2))
        print(f"\nplan saved to {path}\nplan hash {plan.plan_hash()}")
        return 0

    if args.cmd == "validate":
        plan = _load_plan(args.plan)
        decision = validate_plan(plan)
        store.save_policy_decision(decision)
        print(json.dumps(decision.model_dump(mode="json"), indent=2))
        return 0 if decision.allowed else 2

    if args.cmd == "approve":
        plan = _load_plan(args.plan)
        decision = validate_plan(plan)
        store.save_policy_decision(decision)
        try:
            approval = approve(plan, decision, args.by)
        except ApprovalError as exc:
            print(f"NOT APPROVED: {exc}")
            return 2
        print(f"approved {plan.plan_id} hash {approval.plan_hash} -> {store.save_approval(approval)}")
        return 0

    if args.cmd == "run":
        plan = _load_plan(args.plan)
        return _execute(store, plan, _find_approval(store, plan))

    if args.cmd == "verify":
        try:
            raw = store.load_bundle_raw(args.run_id)
        except FileNotFoundError:
            print(f"no evidence for {args.run_id}")
            return 4
        report = verify_bundle(raw)
        store.save_verification(report)
        for c in report.checks:
            print(f"  {'PASS' if c.passed else 'FAIL'} {c.name}: {c.detail}")
        print(f"verification: {report.status}")
        return 0 if report.verified else 1

    if args.cmd == "demo":
        rc = 0
        for scenario in ("capacity", "sham", "low_benefit"):
            plan = ScriptedProposer().propose(scenario)
            store.save_plan(plan)
            decision = validate_plan(plan)
            store.save_policy_decision(decision)
            approval = approve(plan, decision, args.approve_as)
            store.save_approval(approval)
            print(f"[{scenario}] {SCENARIOS[scenario]['title']}")
            rc = max(rc, _execute(store, plan, approval))
        return rc

    if args.cmd == "list":
        for run_id in store.list_runs():
            b = store.load_bundle(run_id)
            print(f"{run_id}  {b.status:9}  {b.analysis.outcome if b.analysis else 'n/a':12}  {b.plan.question[:70]}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
