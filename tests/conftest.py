import pytest

from scientist_lab.policy import approve, validate_plan
from scientist_lab.proposer import ScriptedProposer
from scientist_lab.store import EvidenceStore


@pytest.fixture
def store(tmp_path):
    return EvidenceStore(tmp_path / "data")


@pytest.fixture
def approved():
    """Return (plan, approval) for a scripted scenario."""

    def _make(scenario="capacity", plan=None):
        plan = plan or ScriptedProposer().propose(scenario)
        return plan, approve(plan, validate_plan(plan), "tester")

    return _make
