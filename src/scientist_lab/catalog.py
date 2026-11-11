"""Fixed tool catalog and run budgets. The agent can only name tools listed here."""

from __future__ import annotations

from typing import Callable

from . import simulator
from .schemas import SimulateRequest, SimulateResult

TOOL_CATALOG: dict[str, Callable[[SimulateRequest], SimulateResult]] = {
    "queue.simulate": simulator.simulate,
}

ALLOWED_METRICS = ("mean_wait", "p95_wait")
ALLOWED_INTERVENTIONS = ("capacity", "sham")
MIN_SEEDS, MAX_SEEDS = 3, 50
MAX_SIM_CALLS_PER_PLAN = 100  # budget: 2 calls (baseline + intervention) per seed
MAX_SIM_TIME_PER_PLAN = 100_000.0  # budget: sum of simulated duration over all calls
