import pytest
from pydantic import ValidationError

from scientist_lab.schemas import SimulateRequest
from scientist_lab.simulator import MAX_CUSTOMERS, SimulationError, WORKLOADS, arrival_trace, simulate


def req(**kw):
    base = dict(workload="moderate", servers=2, duration=500.0, seed=11)
    base.update(kw)
    return SimulateRequest(**base)


def test_same_seed_same_result():
    assert simulate(req()) == simulate(req())


def test_different_seed_different_trace():
    assert simulate(req(seed=1)).trace_sha256 != simulate(req(seed=2)).trace_sha256


def test_arms_share_trace_only_servers_differ():
    a, b = simulate(req(servers=2)), simulate(req(servers=3))
    assert a.trace_sha256 == b.trace_sha256
    assert a.n_customers == b.n_customers
    assert b.mean_wait < a.mean_wait


def test_sham_label_has_no_effect():
    assert simulate(req()) == simulate(req(sham_label="sham-relabel"))


def test_more_servers_never_increase_wait():
    waits = [simulate(req(servers=c)).mean_wait for c in range(1, 9)]
    assert all(x >= y for x, y in zip(waits, waits[1:]))


@pytest.mark.parametrize("bad", [
    dict(workload="extreme"), dict(servers=0), dict(servers=9), dict(duration=10.0),
    dict(duration=5000.0), dict(seed=-1), dict(seed=2**31), dict(duration=float("nan")),
])
def test_invalid_inputs_rejected(bad):
    with pytest.raises(SimulationError):
        simulate(req(**bad))


def test_untyped_input_rejected_by_schema():
    with pytest.raises(ValidationError):
        SimulateRequest(workload="moderate", servers="two", duration=500, seed=1)
    with pytest.raises(ValidationError):
        SimulateRequest(workload="moderate", servers=2, duration=500, seed=1, shell="rm -rf /")


def test_customer_limit_enforced(monkeypatch):
    import scientist_lab.simulator as sim
    monkeypatch.setattr(sim, "MAX_CUSTOMERS", 50)
    with pytest.raises(SimulationError, match="customer limit"):
        sim.arrival_trace(WORKLOADS["heavy"], 2000.0, 1)
    assert MAX_CUSTOMERS == 20_000


def test_heaviest_allowed_call_stays_within_limit():
    assert len(arrival_trace(WORKLOADS["heavy"], 2000.0, 3)) < MAX_CUSTOMERS
