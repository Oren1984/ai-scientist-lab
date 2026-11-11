# AI Scientist Lab V1.0 — Work Plan

**Target repository** — `ai-scientist-lab` (new, built from scratch).  
**Working branch** — `feat/scientist-lab-v1` once the repository is initialized  
**Credit** — Developed and built by Oren Salami · V1.0

## Brief for Claude

Build a local research proof of concept that tests whether a bounded research agent can turn a question into a reproducible experimental conclusion. Use one synthetic, non-biological sandbox. Ship a small Python application, Streamlit UI and one Docker Compose service. Use typed contracts, modular components and filesystem evidence. Keep the deterministic path offline and CPU-friendly. Read the repository instructions and inspect the working tree before implementation.

## First experiment — synthetic queue dynamics

Use a small simulated service queue. Ask whether increasing service capacity reduces waiting time under a specified workload. The agent chooses an allowed workload, baseline and intervention, metric, paired seed set and decision rule. Use a fixed arrival trace per pair, vary only capacity, and keep workload and run duration identical. Add a sham intervention that changes nothing and should yield zero paired difference. Include one scenario with little or no benefit to show how the system reports an inconclusive result or a result outside the expected direction.

## Execution workflow

1. **Propose.** The agent returns a structured hypothesis and experiment plan. Record the primary metric, sample size, seed list, comparison and decision rule before evaluation. Show the plan for operator approval.
2. **Validate.** A policy gate independently checks the plan against allowed parameters, a fixed tool catalog and run budgets. Bind approval to the exact validated plan. A changed plan requires a new approval. Reject malformed or out-of-scope requests with a recorded reason.
3. **Execute.** A trusted runner dispatches typed simulator calls. The agent can propose plans and read returned evidence. Execution goes through the runner, with a fixed budget and synthetic data. Expose no shell, arbitrary code execution or external tools to the agent.
4. **Verify.** An independent verifier replays the recorded plan, recalculates the paired differences and compares them with the recorded results. Report verification separately from the scientific outcome. Use explicit statuses such as supported, contradicted or inconclusive. Run exploratory follow-ups under a new plan ID.
5. **Report.** Present question, hypothesis, plan, actual runs, metrics, verification, result and limitations. Every numerical claim links to its run record. Export a JSON evidence bundle and a Markdown report.

## Build sequence

- **Milestone 1 — Simulator and CLI.** Implement the seeded queue, plan schema, deterministic proposal strategy, runner and verifier. Confirm that the same approved plan yields the same evidence and that tampering is detected.
- **Milestone 2 — Operator UI.** Add **Plan & Approval**, **Runs & Evidence** and a short **Help Center**. Show a paired comparison chart and one visible failed or inconclusive case. Bind the app to localhost by default. Store evidence per run with atomic writes and unique IDs. Record tool outcomes, errors, policy decisions, parameters and versions.
- **Milestone 3 — Optional local model.** If practical, add an Ollama adapter that produces the same typed proposals through the same checks. Preserve the offline scripted demo and identify the mode in reports. Document whether a real model was exercised and which results came from it.

## Definition of done

- One command starts the app through Docker Compose. Document setup and smoke commands for Windows PowerShell.
- A complete seeded run goes from proposal to explicit approval, evidence export and independent replay. A rejected plan makes no simulator call. A plan edit invalidates prior approval.
- Demonstrate a supported result, a sham comparison and a non-supporting result. Verify replay and corrupted evidence, and test simulator limits and invalid inputs. Include actual test output in the handoff summary.
- Provide a short README, a small `docs/` directory with methodology and usage, and two or three screenshots from the running app. Keep runtime data and secrets out of Git. Prepare a local diff for review. Commit or push when the operator authorizes it.

## Sources and scope

- [Sakana AI — The AI Scientist](https://sakana.ai/ai-scientist/), primary inspiration for the computational research loop.
- [ESCAPE LAB](https://github.com/Oren1984/escape-lab), reference for separation of proposal and authorization.
- [Agent Repair Lab](https://github.com/Oren1984/agent-repair-lab), reference for independent verification.
- [Causal Universe: What If?](https://github.com/Oren1984/causal-universe-what-if), reference for matched simulation comparisons.

Implement the new simulator and workflow in this repository. The references inform the design. The experiment evaluates reproducibility and evidence quality in the stated synthetic setting.
