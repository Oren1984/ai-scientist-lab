"""Proposers turn a research question into a typed, pre-registered ExperimentPlan.

* ScriptedProposer — deterministic, offline, always available (default).
* OllamaProposer   — optional local model; its output passes through the same
                     typed builder and the same policy gate as scripted plans.

Proposers have no access to the simulator, the runner or the filesystem.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any, Optional

from .schemas import ArmSpec, DecisionRule, ExperimentPlan, ProposerInfo
from .store import new_id


class ProposerError(RuntimeError):
    pass


def seed_list(start: int, n: int, step: int = 7919) -> list[int]:
    return [start + i * step for i in range(n)]


SCENARIOS: dict[str, dict[str, Any]] = {
    "capacity": {
        "title": "Capacity increase under moderate load (expected: supported)",
        "question": "Does increasing service capacity from 2 to 3 servers reduce mean waiting time "
                    "under the moderate workload?",
        "hypothesis": "Adding a third server reduces mean waiting time by at least 0.1 time units.",
        "workload": "moderate", "baseline": 2, "intervention": 3, "kind": "capacity",
        "n_seeds": 20, "duration": 500.0, "min_effect": 0.1,
    },
    "sham": {
        "title": "Sham intervention (expected: zero paired difference)",
        "question": "Does relabelling the queue (a sham change) alter mean waiting time under the moderate workload?",
        "hypothesis": "The sham relabel produces exactly zero paired difference on every seed.",
        "workload": "moderate", "baseline": 2, "intervention": 2, "kind": "sham",
        "n_seeds": 20, "duration": 500.0, "min_effect": 0.0,
    },
    "low_benefit": {
        "title": "Capacity increase under light load (expected: not supported)",
        "question": "Does increasing service capacity from 2 to 3 servers reduce mean waiting time "
                    "under the light workload?",
        "hypothesis": "Adding a third server reduces mean waiting time by at least 0.1 time units.",
        "workload": "light", "baseline": 2, "intervention": 3, "kind": "capacity",
        "n_seeds": 20, "duration": 500.0, "min_effect": 0.1,
    },
}


def build_plan(*, question: str, hypothesis: str, workload: str, baseline_servers: int,
               intervention_servers: int, intervention_kind: str, seeds: list[int], duration: float,
               min_effect: float, metric: str, proposer: ProposerInfo,
               parent_plan_id: Optional[str] = None) -> ExperimentPlan:
    sham = intervention_kind == "sham"
    return ExperimentPlan(
        plan_id=new_id("plan"),
        parent_plan_id=parent_plan_id,
        question=question,
        hypothesis=hypothesis,
        workload=workload,
        duration=float(duration),
        baseline=ArmSpec(label="baseline", servers=int(baseline_servers)),
        intervention=ArmSpec(label="intervention", servers=int(intervention_servers),
                             sham_label="sham-relabel" if sham else None),
        intervention_kind=intervention_kind,
        metric=metric,
        seeds=[int(s) for s in seeds],
        decision_rule=DecisionRule(kind="paired_null" if sham else "paired_mean_reduction",
                                   min_effect=0.0 if sham else float(min_effect)),
        proposer=proposer,
    )


class ScriptedProposer:
    mode = "scripted"

    def propose(self, scenario: str = "capacity") -> ExperimentPlan:
        if scenario not in SCENARIOS:
            raise ProposerError(f"unknown scenario {scenario!r}; choose from {sorted(SCENARIOS)}")
        s = SCENARIOS[scenario]
        return build_plan(
            question=s["question"], hypothesis=s["hypothesis"], workload=s["workload"],
            baseline_servers=s["baseline"], intervention_servers=s["intervention"],
            intervention_kind=s["kind"], seeds=seed_list(1001, s["n_seeds"]), duration=s["duration"],
            min_effect=s["min_effect"], metric="mean_wait",
            proposer=ProposerInfo(mode="scripted", note=f"deterministic scenario '{scenario}'"),
        )


def follow_up(plan: ExperimentPlan, **changes: Any) -> ExperimentPlan:
    """Exploratory follow-up: always a new plan ID that links back to its parent."""
    fields = dict(
        question=plan.question, hypothesis=plan.hypothesis, workload=plan.workload,
        baseline_servers=plan.baseline.servers, intervention_servers=plan.intervention.servers,
        intervention_kind=plan.intervention_kind, seeds=plan.seeds, duration=plan.duration,
        min_effect=plan.decision_rule.min_effect, metric=plan.metric, proposer=plan.proposer,
    )
    fields.update(changes)
    return build_plan(parent_plan_id=plan.plan_id, **fields)


_OLLAMA_PROMPT = """You are a research planner for a synthetic queue simulator.
Allowed workloads: light, moderate, heavy. Servers: integers 1-8. Duration: 50-2000.
intervention_kind is "capacity" (servers differ) or "sham" (servers equal, nothing changes).
Number of seeds: 3-50. min_effect: positive float in time units.
Return ONLY a JSON object with keys: hypothesis (string), workload, baseline_servers,
intervention_servers, intervention_kind, n_seeds, seed_start (integer), duration, min_effect.
Research question: {question}
"""

_KEYS = ("hypothesis", "workload", "baseline_servers", "intervention_servers", "intervention_kind",
         "n_seeds", "seed_start", "duration", "min_effect")


class OllamaProposer:
    mode = "ollama"

    def __init__(self, model: Optional[str] = None, host: Optional[str] = None, timeout: float = 60.0):
        self.model = model or os.environ.get("OLLAMA_MODEL", "llama3.2")
        self.host = (host or os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")).rstrip("/")
        self.timeout = timeout

    def _generate(self, prompt: str) -> str:
        body = json.dumps({"model": self.model, "prompt": prompt, "format": "json", "stream": False,
                           "options": {"temperature": 0, "seed": 7}}).encode("utf-8")
        req = urllib.request.Request(f"{self.host}/api/generate", data=body,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310 - local host only
                return json.loads(resp.read().decode("utf-8"))["response"]
        except (urllib.error.URLError, OSError, KeyError, ValueError) as exc:
            raise ProposerError(f"Ollama not reachable at {self.host}: {exc}") from exc

    def propose(self, question: str) -> ExperimentPlan:
        raw = self._generate(_OLLAMA_PROMPT.format(question=question))
        return self.parse(question, raw)

    def parse(self, question: str, raw: str) -> ExperimentPlan:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            raise ProposerError("model output contained no JSON object")
        try:
            data = json.loads(match.group(0))
            missing = [k for k in _KEYS if k not in data]
            if missing:
                raise ProposerError(f"model output missing keys: {missing}")
            n = int(data["n_seeds"])
            if not 1 <= n <= 1000:  # sanity bound on list construction; the policy gate decides the rest
                raise ProposerError(f"n_seeds={n} is not a usable seed count")
            return build_plan(
                question=question, hypothesis=str(data["hypothesis"])[:500] or "unspecified",
                workload=str(data["workload"]), baseline_servers=int(data["baseline_servers"]),
                intervention_servers=int(data["intervention_servers"]),
                intervention_kind=str(data["intervention_kind"]),
                seeds=seed_list(int(data["seed_start"]), n), duration=float(data["duration"]),
                min_effect=float(data["min_effect"]), metric="mean_wait",
                proposer=ProposerInfo(mode="ollama", model=self.model, note=f"host={self.host}"),
            )
        except ProposerError:
            raise
        except (TypeError, ValueError) as exc:
            raise ProposerError(f"model output could not be typed into a plan: {exc}") from exc
