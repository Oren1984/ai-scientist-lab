"""AI Scientist Lab V1.0 — operator UI (Plan & Approval, Runs & Evidence, Help Center)."""

from __future__ import annotations

import json

import altair as alt
import pandas as pd
import streamlit as st

from scientist_lab import SIMULATOR_VERSION, __version__, catalog, simulator
from scientist_lab.policy import ApprovalError, approval_matches, approve, validate_plan
from scientist_lab.proposer import SCENARIOS, OllamaProposer, ProposerError, ScriptedProposer, follow_up
from scientist_lab.report import render_markdown
from scientist_lab.runner import PolicyRejected, run_plan
from scientist_lab.schemas import Approval, ArmSpec, DecisionRule, ExperimentPlan
from scientist_lab.store import EvidenceStore
from scientist_lab.verifier import verify_bundle

PAGES = {"plan": "Plan & Approval", "runs": "Runs & Evidence", "help": "Help Center"}
OUTCOME_COLOR = {"supported": "green", "contradicted": "red", "inconclusive": "orange"}

st.set_page_config(page_title="AI Scientist Lab", page_icon="🔬", layout="wide")
store = EvidenceStore()
ss = st.session_state
ss.setdefault("plan", None)
ss.setdefault("approval", None)
ss.setdefault("proposal_error", None)

qp = st.query_params
if "page" not in ss:
    ss.page = qp.get("page", "plan") if qp.get("page") in PAGES else "plan"
if ss.get("nav_to"):  # programmatic navigation requested by a button on the previous run
    ss.page = ss.pop("nav_to")


def go(page: str) -> None:
    ss.nav_to = page
    st.rerun()


with st.sidebar:
    st.title("🔬 AI Scientist Lab")
    st.caption(f"V{__version__} · {SIMULATOR_VERSION}")
    st.radio("Section", list(PAGES), format_func=PAGES.get, key="page")
    st.divider()
    st.caption("Synthetic queue sandbox. Offline by default. Agent proposes; operator approves; "
               "trusted runner executes; independent verifier replays.")
    st.caption(f"Evidence directory: `{store.root}`")
    st.caption("Developed and built by **Oren Salami** · V1.0")


def outcome_badge(outcome: str | None) -> str:
    if not outcome:
        return ":gray[**NO RESULT**]"
    return f":{OUTCOME_COLOR[outcome]}[**{outcome.upper()}**]"


def verify_badge(status: str | None) -> str:
    return {"verified": ":green[**VERIFIED**]", "failed": ":red[**VERIFICATION FAILED**]"}.get(
        status or "", ":gray[**NOT VERIFIED**]")


# ------------------------------------------------------------------ Plan & Approval
def page_plan() -> None:
    st.header("Plan & Approval")
    st.write("1 · **Propose** → 2 · **Validate** (policy gate) → 3 · **Approve** (bound to plan hash) → "
             "4 · **Execute** (trusted runner) → 5 · **Verify** (independent replay)")

    with st.container(border=True):
        st.subheader("1 · Propose")
        mode = st.radio("Proposer", ["scripted", "ollama"], horizontal=True,
                        format_func=lambda m: "Scripted (offline, deterministic)" if m == "scripted"
                        else "Ollama (optional local model)")
        if mode == "scripted":
            scenario = st.selectbox("Research question", list(SCENARIOS),
                                    format_func=lambda k: SCENARIOS[k]["title"])
            st.caption(SCENARIOS[scenario]["question"])
        else:
            question = st.text_area("Research question", SCENARIOS["capacity"]["question"])
            model = st.text_input("Model", OllamaProposer().model)
        if st.button("Propose plan", type="primary") or (ss.plan is None and mode == "scripted"):
            try:
                plan = (ScriptedProposer().propose(scenario) if mode == "scripted"
                        else OllamaProposer(model=model).propose(question))
                ss.plan, ss.approval, ss.proposal_error = plan.model_dump(mode="json"), None, None
                store.save_plan(plan)
            except ProposerError as exc:
                ss.proposal_error = str(exc)
        if ss.proposal_error:
            st.error(f"Proposal failed: {ss.proposal_error}. The scripted proposer remains available offline.")

    if ss.plan is None:
        return
    plan = ExperimentPlan.model_validate(ss.plan)

    with st.container(border=True):
        st.subheader("Proposed plan")
        c1, c2, c3 = st.columns(3)
        c1.markdown(f"**Plan ID** `{plan.plan_id}`" + (f"  \nfollow-up of `{plan.parent_plan_id}`"
                                                      if plan.parent_plan_id else ""))
        c2.markdown(f"**Plan hash** `{plan.plan_hash()[:16]}…`")
        c3.markdown(f"**Proposer** `{plan.proposer.mode}`" + (f" · `{plan.proposer.model}`" if plan.proposer.model else ""))
        st.markdown(f"**Question.** {plan.question}  \n**Hypothesis.** {plan.hypothesis}")
        st.dataframe(pd.DataFrame([
            ("Workload", plan.workload), ("Run duration", f"{plan.duration:g}"),
            ("Baseline servers", plan.baseline.servers),
            ("Intervention", f"{plan.intervention_kind}: {plan.intervention.servers} server(s)"
             + (f", label {plan.intervention.sham_label}" if plan.intervention.sham_label else "")),
            ("Primary metric", plan.metric), ("Sample size (pairs)", len(plan.seeds)),
            ("Seeds", ", ".join(map(str, plan.seeds))), ("Comparison", plan.comparison),
            ("Decision rule", f"{plan.decision_rule.kind}, min_effect={plan.decision_rule.min_effect:g}, "
                              f"confidence={plan.decision_rule.confidence:g}"),
            ("Tools", ", ".join(plan.tools)),
        ], columns=["Field", "Value"]).astype(str), hide_index=True, width="stretch")

        with st.expander("Edit plan (any edit invalidates approval)"):
            with st.form("edit"):
                e1, e2, e3 = st.columns(3)
                workload = e1.selectbox("Workload", ["light", "moderate", "heavy", "extreme"],
                                        index=["light", "moderate", "heavy", "extreme"].index(plan.workload)
                                        if plan.workload in simulator.WORKLOADS else 0)
                b_srv = e2.number_input("Baseline servers", 0, 20, plan.baseline.servers)
                i_srv = e3.number_input("Intervention servers", 0, 20, plan.intervention.servers)
                n_seeds = e1.number_input("Number of seeds", 1, 80, len(plan.seeds))
                duration = e2.number_input("Duration", 10.0, 5000.0, plan.duration, step=50.0)
                min_eff = e3.number_input("min_effect", 0.0, 10.0, plan.decision_rule.min_effect, step=0.05)
                if st.form_submit_button("Apply edit"):
                    seeds = [plan.seeds[0] + 7919 * i for i in range(int(n_seeds))]
                    edited = plan.model_copy(update={
                        "workload": workload, "duration": float(duration), "seeds": seeds,
                        "baseline": ArmSpec(label="baseline", servers=int(b_srv)),
                        "intervention": plan.intervention.model_copy(update={"servers": int(i_srv)}),
                        "decision_rule": DecisionRule(**{**plan.decision_rule.model_dump(),
                                                         "min_effect": float(min_eff)}),
                    })
                    ss.plan = edited.model_dump(mode="json")
                    store.save_plan(edited)
                    st.rerun()

    decision = validate_plan(plan)
    with st.container(border=True):
        st.subheader("2 · Validate — policy gate")
        if decision.allowed:
            st.success(f"Allowed by policy ({len(decision.checks)} checks passed).")
        else:
            st.error("Rejected by policy. The runner will make no simulator call for this plan.")
            for r in decision.reasons:
                st.markdown(f"- `{r}`")
        with st.expander("All policy checks"):
            st.dataframe(pd.DataFrame([c.model_dump() for c in decision.checks]), hide_index=True,
                         width="stretch")

    with st.container(border=True):
        st.subheader("3 · Approve")
        approval =Approval.model_validate(ss.approval) if ss.approval else None
        if approval and not approval_matches(plan, approval):
            st.warning("The plan changed after approval. The previous approval is void; approve again.")
        elif approval:
            st.success(f"Approved by **{approval.approved_by}** at {approval.approved_at}, bound to hash "
                       f"`{approval.plan_hash[:16]}…`.")
        a1, a2 = st.columns([2, 1])
        who = a1.text_input("Operator name", value="operator")
        if a2.button("Approve this exact plan", disabled=not decision.allowed):
            try:
                store.save_policy_decision(decision)
                approval = approve(plan, decision, who)
                store.save_approval(approval)
                ss.approval = approval.model_dump(mode="json")
                st.rerun()
            except ApprovalError as exc:
                st.error(str(exc))

    with st.container(border=True):
        st.subheader("4 · Execute and 5 · Verify")
        st.caption("The runner re-checks policy and the approval hash itself; the button never bypasses it.")
        if st.button("Run approved plan", type="primary"):
            try:
                bundle = run_plan(plan, approval, store=store)
                report = verify_bundle(store.load_bundle_raw(bundle.run_id))
                store.save_verification(report)
                store.save_report(bundle.run_id, render_markdown(bundle, report))
                a = bundle.analysis
                st.success(f"Run `{bundle.run_id}` finished.")
                st.markdown(f"Result: {outcome_badge(a.outcome if a else None)} · "
                            f"Verification: {verify_badge(report.status)}")
                ss.selected_run = bundle.run_id
            except PolicyRejected as exc:
                st.error(f"Not run — policy rejected the plan (no simulator call): {exc.decision.reasons}")
            except ApprovalError as exc:
                st.error(f"Not run — {exc}")
        if ss.get("selected_run"):
            if st.button("Open in Runs & Evidence →"):
                go("runs")


# ------------------------------------------------------------------ Runs & Evidence
def page_runs() -> None:
    st.header("Runs & Evidence")
    runs = store.list_runs()
    if not runs:
        st.info("No runs yet. Propose, approve and run a plan first, or run "
                "`python -m scientist_lab demo --approve-as <name>`.")
        _rejections()
        return
    wanted = ss.get("selected_run") or qp.get("run")
    labels = {}
    for r in runs:
        b = store.load_bundle(r)
        labels[r] = f"{r} · {b.analysis.outcome if b.analysis else b.status} · {b.plan.workload} " \
                    f"{b.plan.baseline.servers}→{b.plan.intervention.servers} ({b.plan.intervention_kind})"
    run_id = st.selectbox("Run", runs, index=runs.index(wanted) if wanted in runs else 0, format_func=labels.get)
    ss.selected_run = run_id
    raw = store.load_bundle_raw(run_id)
    bundle = store.load_bundle(run_id)
    verification = store.latest_verification(run_id)
    a, p = bundle.analysis, bundle.plan

    st.markdown(f"**Question.** {p.question}  \n**Hypothesis.** {p.hypothesis}")
    c1, c2, c3, c4 = st.columns(4)
    c1.markdown(f"Scientific result  \n### {outcome_badge(a.outcome if a else None)}")
    c2.markdown(f"Verification (separate)  \n### {verify_badge(verification.status if verification else None)}")
    c3.metric("Mean paired difference", f"{a.mean_difference:.4f}" if a else "–",
              help="baseline − intervention; positive = less waiting")
    c4.metric("95% CI", f"[{a.ci_low:.3f}, {a.ci_high:.3f}]" if a else "–")
    if a:
        st.caption(f"Decision: {a.rationale}. Mode: `{bundle.mode}`. Pairs: {a.n_pairs}.")

    if bundle.pairs:
        df = pd.DataFrame([pr.model_dump() for pr in bundle.pairs])
        long = df.melt(id_vars=["seed"], value_vars=["baseline_value", "intervention_value"],
                       var_name="arm", value_name=p.metric)
        long["arm"] = long["arm"].str.replace("_value", "")
        long["seed"] = long["seed"].astype(str)
        g1, g2 = st.columns(2)
        with g1:
            st.markdown("**Paired comparison** (same arrival trace per seed)")
            lines = alt.Chart(long).mark_line(color="#9aa0a6", strokeWidth=1).encode(
                x=alt.X("arm:N", sort=["baseline", "intervention"], title=None),
                y=alt.Y(f"{p.metric}:Q", title=p.metric), detail="seed:N")
            dots = alt.Chart(long).mark_circle(size=60).encode(
                x=alt.X("arm:N", sort=["baseline", "intervention"]), y=f"{p.metric}:Q",
                color=alt.Color("arm:N", scale=alt.Scale(range=["#4c78a8", "#f58518"])),
                tooltip=["seed", "arm", alt.Tooltip(f"{p.metric}:Q", format=".4f")])
            st.altair_chart((lines + dots).properties(height=320), width="stretch")
        with g2:
            st.markdown("**Paired differences** with 95% CI and min_effect")
            df["seed_s"] = df["seed"].astype(str)
            bars = alt.Chart(df).mark_bar(color="#54a24b").encode(
                x=alt.X("seed_s:N", sort=None, title="seed"), y=alt.Y("difference:Q", title="d = baseline − intervention"),
                tooltip=["seed", alt.Tooltip("difference:Q", format=".6f"), "baseline_record"])
            layers = [bars, alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(color="black").encode(y="y:Q")]
            if a and p.decision_rule.kind == "paired_mean_reduction":
                layers.append(alt.Chart(pd.DataFrame({"y": [p.decision_rule.min_effect]}))
                              .mark_rule(color="red", strokeDash=[6, 4]).encode(y="y:Q"))
                layers.append(alt.Chart(pd.DataFrame({"lo": [a.ci_low], "hi": [a.ci_high]}))
                              .mark_rect(opacity=0.15, color="#4c78a8").encode(y="lo:Q", y2="hi:Q"))
            st.altair_chart(alt.layer(*layers).properties(height=320), width="stretch")

        st.markdown("**Pairs** — every number links to its run record")
        st.dataframe(df[["seed", "baseline_value", "intervention_value", "difference", "baseline_record",
                         "intervention_record"]], hide_index=True, width="stretch")

    b1, b2, b3, b4 = st.columns(4)
    if b1.button("Re-verify (independent replay)"):
        verification = verify_bundle(raw)
        store.save_verification(verification)
        st.rerun()
    b2.download_button("Download JSON evidence", json.dumps(raw, indent=2), file_name=f"{run_id}.json",
                       mime="application/json")
    b3.download_button("Download Markdown report", render_markdown(bundle, verification),
                       file_name=f"{run_id}.md", mime="text/markdown")
    if b4.button("Exploratory follow-up (new plan ID)"):
        ss.plan = follow_up(p).model_dump(mode="json")
        ss.approval = None
        go("plan")

    if verification:
        with st.expander(f"Verification checks ({verification.status}, {verification.replayed_calls} calls replayed)",
                         expanded=not verification.verified):
            st.dataframe(pd.DataFrame([c.model_dump() for c in verification.checks]), hide_index=True,
                         width="stretch")
    with st.expander("Tool call log (outcomes, errors, parameters)"):
        st.dataframe(pd.DataFrame([{
            "record_id": c.record_id, "tool": c.tool, "outcome": c.outcome, "error": c.error,
            **c.request.model_dump(), **({"mean_wait": c.result.mean_wait, "n_customers": c.result.n_customers}
                                         if c.result else {}), "elapsed_ms": c.elapsed_ms}
            for c in bundle.tool_calls]), hide_index=True, width="stretch")
    with st.expander("Plan, approval, policy decision and versions"):
        st.json({"plan": raw["plan"], "plan_hash": raw["plan_hash"], "approval": raw["approval"],
                 "policy_decision": raw["policy_decision"], "versions": raw["versions"],
                 "bundle_sha256": raw["bundle_sha256"]}, expanded=False)
    with st.expander("Markdown report preview"):
        st.markdown(render_markdown(bundle, verification))
    _rejections()


def _rejections() -> None:
    rejected = [d for d in store.list_policy_decisions() if not d.allowed][:20]
    with st.expander(f"Policy rejections log ({len(rejected)} recent)"):
        if not rejected:
            st.caption("No rejected plans recorded.")
        for d in rejected:
            st.markdown(f"- `{d.decided_at}` `{d.plan_id}` — " + "; ".join(d.reasons))


# ------------------------------------------------------------------ Help Center
def page_help() -> None:
    st.header("Help Center")
    st.markdown(f"""
**What this is.** A local proof of concept that tests whether a bounded research agent can turn a
question into a reproducible experimental conclusion inside one synthetic sandbox: a seeded
multi-server FIFO queue. Nothing here models a real system.

**Workflow.**
1. *Propose* — the agent returns a typed hypothesis and plan: workload, baseline and intervention,
   primary metric, paired seed list and decision rule, all fixed before evaluation.
2. *Validate* — the policy gate checks allowed parameters, the fixed tool catalog
   (`{", ".join(catalog.TOOL_CATALOG)}`) and budgets (≤ {catalog.MAX_SIM_CALLS_PER_PLAN} calls,
   ≤ {catalog.MAX_SIM_TIME_PER_PLAN:g} simulated time units). Rejections are recorded with reasons.
3. *Approve* — you approve the exact plan; the approval stores its SHA-256 hash. Any edit changes the
   hash and voids the approval.
4. *Execute* — the trusted runner dispatches typed `queue.simulate` calls. Each pair uses one
   arrival trace; only server count differs. The agent has no shell, code execution or external tools.
5. *Verify* — the verifier replays every call from the recorded plan and recomputes the paired
   differences. Verification status is shown apart from the scientific result.

**Statuses.** Result: *supported*, *contradicted* or *inconclusive* per the pre-registered rule.
Verification: *verified* or *failed*.

**Decision rule (capacity).** d = baseline − intervention. Supported if mean d ≥ min_effect and the
95% CI lower bound > 0; contradicted if the CI upper bound < min_effect; inconclusive otherwise.
**Sham.** Supported if every |d| ≤ tolerance.

**Allowed space.** Workloads {", ".join(f"`{k}` (λ={w.arrival_rate}, μ={w.service_rate})"
                                       for k, w in simulator.WORKLOADS.items())}; servers
{simulator.MIN_SERVERS}–{simulator.MAX_SERVERS}; duration {simulator.MIN_DURATION:g}–{simulator.MAX_DURATION:g};
{catalog.MIN_SEEDS}–{catalog.MAX_SEEDS} seeds.

**Follow-ups.** Exploratory follow-ups always get a new plan ID that links to the parent plan.

**Optional local model.** Set `OLLAMA_HOST` and `OLLAMA_MODEL` and choose *Ollama* on the plan page.
Model output is typed into the same plan schema and goes through the same gate. Reports state the mode.

**CLI.** `python -m scientist_lab demo --approve-as <name>` runs the three scenarios; see `docs/usage.md`.

*AI Scientist Lab V{__version__} — developed and built by Oren Salami.*
""")


{"plan": page_plan, "runs": page_runs, "help": page_help}[ss.page]()
