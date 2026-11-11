"""Markdown report. Every numerical claim cites the run record(s) it came from."""

from __future__ import annotations

from typing import Optional

from .schemas import EvidenceBundle, VerificationReport


def _f(x: float) -> str:
    return f"{x:.4f}"


def render_markdown(bundle: EvidenceBundle, verification: Optional[VerificationReport] = None) -> str:
    p, a = bundle.plan, bundle.analysis
    all_records = ", ".join(f"`{c.record_id}`" for c in bundle.tool_calls[:4])
    if len(bundle.tool_calls) > 4:
        all_records += f", … ({len(bundle.tool_calls)} records in `bundle.json`)"
    mode = "scripted (offline, deterministic)" if bundle.mode == "scripted" else (
        f"ollama local model `{p.proposer.model}` (model-generated plan)")
    lines = [
        f"# Experiment report — {bundle.run_id}",
        "",
        f"*AI Scientist Lab V1.0 · developed and built by Oren Salami · proposer mode: **{mode}***",
        "",
        "## Question",
        p.question,
        "",
        "## Hypothesis",
        p.hypothesis,
        "",
        "## Pre-registered plan",
        f"- Plan ID: `{p.plan_id}`" + (f" (follow-up of `{p.parent_plan_id}`)" if p.parent_plan_id else ""),
        f"- Plan hash: `{bundle.plan_hash}`",
        f"- Workload: `{p.workload}`, run duration {p.duration:g} time units (identical for both arms)",
        f"- Baseline: {p.baseline.servers} server(s); intervention ({p.intervention_kind}): "
        f"{p.intervention.servers} server(s)" + (f", sham label `{p.intervention.sham_label}`"
                                                  if p.intervention.sham_label else ""),
        f"- Primary metric: `{p.metric}`; comparison: {p.comparison}",
        f"- Seeds ({len(p.seeds)}): {', '.join(map(str, p.seeds))}",
        f"- Decision rule: `{p.decision_rule.kind}`, min_effect={p.decision_rule.min_effect:g}, "
        f"confidence={p.decision_rule.confidence:g}, tolerance={p.decision_rule.tolerance:g}",
        f"- Approved by `{bundle.approval.approved_by}` at {bundle.approval.approved_at} "
        f"(bound to plan hash `{bundle.approval.plan_hash[:16]}…`)",
        f"- Policy decision `{bundle.policy_decision.decision_id}`: "
        f"{'allowed' if bundle.policy_decision.allowed else 'rejected'}",
        "",
        "## Actual runs",
        f"{len(bundle.tool_calls)} `queue.simulate` calls, status **{bundle.status}**. Records: {all_records}",
        "",
        "| Seed | Baseline | Intervention | Difference (b − i) | Evidence |",
        "|---:|---:|---:|---:|---|",
    ]
    for pr in bundle.pairs:
        lines.append(f"| {pr.seed} | {_f(pr.baseline_value)} | {_f(pr.intervention_value)} | "
                     f"{_f(pr.difference)} | `{pr.baseline_record}`, `{pr.intervention_record}` |")
    if bundle.errors:
        lines += ["", "**Errors:**", *[f"- {e}" for e in bundle.errors]]

    lines += ["", "## Metrics"]
    if a:
        cite = f"(from {a.n_pairs} pairs: `{bundle.pairs[0].baseline_record}` … `{bundle.pairs[-1].intervention_record}`)"
        lines += [
            f"- Mean paired difference: **{_f(a.mean_difference)}** {cite}",
            f"- 95% CI: [{_f(a.ci_low)}, {_f(a.ci_high)}]; SD {_f(a.sd_difference)} {cite}",
            f"- Range of differences: [{_f(a.min_difference)}, {_f(a.max_difference)}]; "
            f"max |d| = {a.max_abs_difference:.3g} {cite}",
        ]
    else:
        lines.append("- No analysis: the run did not complete all planned calls.")

    lines += ["", "## Verification (reported separately from the result)"]
    if verification:
        lines.append(f"- Status: **{verification.status}** ({verification.replayed_calls} calls replayed, "
                     f"checked {verification.verified_at})")
        lines += [f"  - {'PASS' if c.passed else 'FAIL'} `{c.name}` {c.detail}" for c in verification.checks]
    else:
        lines.append("- Not yet verified. Run `python -m scientist_lab verify <run_id>`.")

    lines += ["", "## Result"]
    if a:
        lines += [f"**{a.outcome.upper()}** — {a.rationale}."]
    else:
        lines += ["**NO RESULT** — the run failed; see errors above."]

    lines += [
        "",
        "## Limitations",
        "- Synthetic sandbox only: a single FIFO multi-server queue with exponential inter-arrival and "
        "service times. Results say nothing about real systems.",
        "- The confidence interval uses a t approximation over seeds; seeds are independent draws of the "
        "same synthetic workload, not samples from a real population.",
        "- Waiting time includes customers that arrive near the end of the run window; no warm-up period "
        "is removed.",
        "- A pre-registered decision rule was applied once; exploratory follow-ups require a new plan ID.",
        f"- Proposer mode: {mode}.",
        "",
        f"Versions: {', '.join(f'{k}={v}' for k, v in sorted(bundle.versions.items()))}. "
        f"Bundle SHA-256: `{bundle.bundle_sha256}`.",
        "",
    ]
    return "\n".join(lines)
