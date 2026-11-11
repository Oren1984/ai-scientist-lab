# Methodology

## Research question

Does increasing service capacity reduce waiting time under a specified workload? The setting is a
synthetic multi-server FIFO queue. It is a sandbox for testing the research loop. It is not a model
of any real system.

## Sandbox: seeded queue simulator (`simulator.py`)

- Arrivals follow a Poisson process (exponential inter-arrival times, rate λ). Each customer carries an
  exponential service demand (rate μ). Both come from `random.Random(seed)`.
- The **arrival trace depends only on (workload, duration, seed)**. Within a pair, both arms see the
  identical trace (same arrival times, same service demands, same run duration). **Only the server
  count differs.** Every result records a SHA-256 of its trace, so this is checkable.
- Customers are served first come, first served by the earliest free server. Waiting time is the time
  from arrival to start of service.
- Workloads: `light` (λ=0.6), `moderate` (λ=1.8), `heavy` (λ=3.5), all with μ=1.0.
- Limits: 1–8 servers, duration 50–2000, seed in [0, 2³¹−1], at most 20,000 customers per call.
  The simulator rejects anything outside these limits, as a second line of defence behind the policy gate.

## Pre-registration (`schemas.ExperimentPlan`)

The plan fixes the following before any simulator call: question, hypothesis, workload, run duration,
baseline and intervention arms, intervention kind, primary metric, the full seed list (sample size =
number of pairs), the comparison and the decision rule. The plan's canonical-JSON SHA-256 is its
identity for approval.

## Interventions

- **capacity**: the intervention arm has a different server count. Nothing else may change (the
  policy enforces this).
- **sham**: the intervention arm has the same server count plus a `sham_label` that the simulator
  ignores. It must yield exactly zero paired difference on every seed. It is a negative control for the
  whole pipeline.

## Statistics and decision rules (`analysis.py`)

For each seed *i*: `d_i = metric(baseline, seed_i) − metric(intervention, seed_i)`. A positive value
means less waiting under the intervention.

- 95% CI for the mean of `d` uses the t distribution with n−1 degrees of freedom. Critical values come
  from a table for df ≤ 30 and a Cornish–Fisher expansion above that.
- `paired_mean_reduction` (capacity), with practical threshold `min_effect`:
  - **supported** if mean d ≥ min_effect and the CI lower bound > 0;
  - **contradicted** if the CI upper bound < min_effect (confidently below a meaningful reduction,
    including a negative effect);
  - **inconclusive** otherwise.
- `paired_null` (sham): **supported** if every |d_i| ≤ tolerance (1e‑9), otherwise **contradicted**.

The rule is applied once, to the pre-registered plan. Exploratory follow-ups (`proposer.follow_up`)
always get a new plan ID that links to the parent. They need their own validation and approval.

## Control and trust boundaries

1. **Proposer** (scripted or Ollama) can only return a plan. It has no access to the simulator, the
   runner or the filesystem. Ollama output is parsed into the same typed builder.
2. **Policy gate** (`policy.validate_plan`) independently checks the workload, server range, duration,
   metric, seed count, uniqueness and range, intervention kind and its constraints, decision rule
   consistency, tool names against the fixed catalog (`queue.simulate` only), and budgets (≤ 100 calls,
   ≤ 100,000 simulated time units per plan). Every decision is stored with its reasons.
3. **Approval** stores `plan_id` + `plan_hash` + approver. `approve()` refuses a rejected plan or a
   decision computed for another plan version.
4. **Runner** re-runs the policy gate and checks the approval hash itself. A rejected or unapproved plan
   raises an error before any simulator call. It dispatches only catalog tools with typed requests and
   records each call's parameters, outcome, error and timing.
5. **Verifier** reads the raw JSON and performs these checks:
   - schema validation and bundle SHA-256;
   - plan hash and approval binding;
   - a policy re-check;
   - calls match the plan;
   - **full replay** of every call with exact comparison;
   - recomputation of the paired differences and the decision.

   Verification status (`verified`/`failed`) is reported apart from the scientific outcome.
   Recomputing the bundle hash after tampering does not hide changes, because replay still catches them.

## Evidence

Each run writes `data/runs/<run_id>/bundle.json`. Runs are write-once, with atomic temp-file plus
`os.replace` writes. The bundle holds the plan, plan hash, approval, policy decision, all tool call
records, pairs, analysis, versions (app, simulator, Python), proposer mode, timestamps and its own
SHA-256. A `report.md` and `verification-*.json` sit next to it. Record IDs have the form
`<run_id>/seed-<seed>/<arm>`. Every number in the report and UI cites them.

`EvidenceBundle.evidence_fingerprint()` hashes the scientific content without IDs or timestamps. The
same approved plan always yields the same fingerprint.

## Limitations

- One synthetic queue model with exponential distributions. No warm-up removal. End-of-window
  arrivals are included.
- The t-based CI treats seeds as independent replications of one synthetic workload.
- Floating-point results are reproducible on IEEE-754 platforms with the same Python `random`
  implementation. The Windows host (Python 3.12.10) and the container (python:3.12-slim) matched exactly.
- The optional Ollama path was implemented and tested with recorded and mocked model output. A live
  model was **not** exercised in this build because no Ollama server was running. All reported
  results come from the scripted proposer.
