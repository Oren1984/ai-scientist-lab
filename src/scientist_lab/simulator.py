"""Seeded multi-server FIFO queue simulator (synthetic, non-biological).

The arrival trace (arrival times and per-customer service demands) depends only on
(workload, duration, seed). Both arms of a pair therefore see the identical trace;
only the number of servers differs. `sham_label` is recorded but has no effect.
"""

from __future__ import annotations

import hashlib
import heapq
import random
import struct
from dataclasses import dataclass

from .schemas import SimulateRequest, SimulateResult


class SimulationError(ValueError):
    """Invalid input or a simulator limit was exceeded."""


@dataclass(frozen=True)
class Workload:
    name: str
    arrival_rate: float  # customers per time unit
    service_rate: float  # per server, customers per time unit
    description: str


WORKLOADS: dict[str, Workload] = {
    "light": Workload("light", 0.6, 1.0, "Arrival rate 0.6, mean service time 1.0"),
    "moderate": Workload("moderate", 1.8, 1.0, "Arrival rate 1.8, mean service time 1.0"),
    "heavy": Workload("heavy", 3.5, 1.0, "Arrival rate 3.5, mean service time 1.0"),
}

MIN_SERVERS, MAX_SERVERS = 1, 8
MIN_DURATION, MAX_DURATION = 50.0, 2000.0
MAX_CUSTOMERS = 20_000
MAX_SEED = 2**31 - 1


def _validate(req: SimulateRequest) -> Workload:
    if req.workload not in WORKLOADS:
        raise SimulationError(f"unknown workload {req.workload!r}")
    if not (MIN_SERVERS <= req.servers <= MAX_SERVERS):
        raise SimulationError(f"servers must be in [{MIN_SERVERS}, {MAX_SERVERS}], got {req.servers}")
    if not (MIN_DURATION <= req.duration <= MAX_DURATION) or req.duration != req.duration:
        raise SimulationError(f"duration must be in [{MIN_DURATION}, {MAX_DURATION}], got {req.duration}")
    if not (0 <= req.seed <= MAX_SEED):
        raise SimulationError(f"seed must be in [0, {MAX_SEED}], got {req.seed}")
    return WORKLOADS[req.workload]


def arrival_trace(workload: Workload, duration: float, seed: int) -> list[tuple[float, float]]:
    """Return [(arrival_time, service_demand)], fixed by (workload, duration, seed)."""
    rng = random.Random(seed)
    t = 0.0
    trace: list[tuple[float, float]] = []
    while True:
        t += rng.expovariate(workload.arrival_rate)
        if t > duration:
            break
        trace.append((t, rng.expovariate(workload.service_rate)))
        if len(trace) > MAX_CUSTOMERS:
            raise SimulationError(f"customer limit {MAX_CUSTOMERS} exceeded")
    return trace


def _trace_hash(trace: list[tuple[float, float]]) -> str:
    h = hashlib.sha256()
    for a, s in trace:
        h.update(struct.pack("<dd", a, s))
    return h.hexdigest()


def simulate(req: SimulateRequest) -> SimulateResult:
    workload = _validate(req)
    trace = arrival_trace(workload, req.duration, req.seed)
    free_at = [0.0] * req.servers  # min-heap of times each server becomes free
    waits: list[float] = []
    busy = 0.0
    last_departure = 0.0
    for arrival, demand in trace:
        free = heapq.heappop(free_at)
        start = arrival if arrival > free else free
        waits.append(start - arrival)
        end = start + demand
        busy += demand
        last_departure = max(last_departure, end)
        heapq.heappush(free_at, end)

    n = len(waits)
    if n == 0:
        mean = p95 = mx = 0.0
    else:
        ordered = sorted(waits)
        mean = sum(waits) / n
        p95 = ordered[min(n - 1, int(0.95 * n))]
        mx = ordered[-1]
    horizon = max(req.duration, last_departure)
    return SimulateResult(
        n_customers=n,
        mean_wait=mean,
        p95_wait=p95,
        max_wait=mx,
        utilization=busy / (req.servers * horizon),
        trace_sha256=_trace_hash(trace),
    )
