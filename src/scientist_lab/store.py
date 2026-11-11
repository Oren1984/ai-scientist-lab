"""Filesystem evidence store with atomic writes and unique IDs."""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel

from .schemas import Approval, EvidenceBundle, ExperimentPlan, PolicyDecision, VerificationReport


def default_data_dir() -> Path:
    return Path(os.environ.get("SCIENTIST_LAB_DATA", "data")).resolve()


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def _dump(obj: BaseModel | dict[str, Any]) -> str:
    data = obj.model_dump(mode="json") if isinstance(obj, BaseModel) else obj
    return json.dumps(data, indent=2, sort_keys=True) + "\n"


class EvidenceStore:
    def __init__(self, root: Optional[Path] = None):
        self.root = Path(root) if root else default_data_dir()

    # -- plans, approvals, policy decisions -------------------------------------------
    def save_plan(self, plan: ExperimentPlan) -> Path:
        path = self.root / "plans" / f"{plan.plan_id}.{plan.plan_hash()[:12]}.json"
        atomic_write_text(path, _dump(plan))
        return path

    def save_policy_decision(self, decision: PolicyDecision) -> Path:
        path = self.root / "policy" / f"{decision.decision_id}.json"
        atomic_write_text(path, _dump(decision))
        return path

    def save_approval(self, approval: Approval) -> Path:
        path = self.root / "approvals" / f"{approval.plan_id}.{approval.plan_hash[:12]}.json"
        atomic_write_text(path, _dump(approval))
        return path

    def list_policy_decisions(self) -> list[PolicyDecision]:
        folder = self.root / "policy"
        if not folder.exists():
            return []
        out = [PolicyDecision.model_validate_json(p.read_text(encoding="utf-8")) for p in folder.glob("*.json")]
        return sorted(out, key=lambda d: d.decided_at, reverse=True)

    # -- runs ------------------------------------------------------------------------
    def run_dir(self, run_id: str) -> Path:
        return self.root / "runs" / run_id

    def save_bundle(self, bundle: EvidenceBundle) -> Path:
        path = self.run_dir(bundle.run_id) / "bundle.json"
        if path.exists():
            raise FileExistsError(f"evidence for {bundle.run_id} already exists; runs are write-once")
        atomic_write_text(path, _dump(bundle))
        return path

    def save_report(self, run_id: str, markdown: str) -> Path:
        path = self.run_dir(run_id) / "report.md"
        atomic_write_text(path, markdown)
        return path

    def save_verification(self, report: VerificationReport) -> Path:
        path = self.run_dir(report.run_id) / f"verification-{report.verified_at.replace(':', '')}.json"
        atomic_write_text(path, _dump(report))
        return path

    def load_bundle_raw(self, run_id: str) -> dict[str, Any]:
        return json.loads((self.run_dir(run_id) / "bundle.json").read_text(encoding="utf-8"))

    def load_bundle(self, run_id: str) -> EvidenceBundle:
        return EvidenceBundle.model_validate(self.load_bundle_raw(run_id))

    def latest_verification(self, run_id: str) -> Optional[VerificationReport]:
        files = sorted(self.run_dir(run_id).glob("verification-*.json"))
        if not files:
            return None
        return VerificationReport.model_validate_json(files[-1].read_text(encoding="utf-8"))

    def list_runs(self) -> list[str]:
        folder = self.root / "runs"
        if not folder.exists():
            return []
        runs = [p for p in folder.iterdir() if (p / "bundle.json").exists()]
        return [p.name for p in sorted(runs, key=lambda p: (p / "bundle.json").stat().st_mtime, reverse=True)]
