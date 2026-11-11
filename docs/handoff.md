# Handoff summary — AI Scientist Lab V1.0

*Developed and built by Oren Salami · V1.0 · build date 2026-11-11*

## Milestones

| Milestone | Status |
|---|---|
| 1 — Simulator and CLI | Done. Seeded queue, typed plan schema, deterministic scripted proposer, policy gate, trusted runner, independent verifier, CLI. The same approved plan gives the same evidence fingerprint, and tampering is detected. |
| 2 — Operator UI | Done. Plan & Approval, Runs & Evidence and Help Center. Paired comparison and difference charts, a visible non-supporting (contradicted) case, localhost binding, write-once atomic evidence per run, and records of tool outcomes, errors, policy decisions, parameters and versions. |
| 3 — Optional local model | Adapter implemented (`OllamaProposer`, same typed builder, same gate). **A real model was not exercised**: no Ollama server was running on the build machine. Tests use recorded and mocked model output. All reported results come from the scripted proposer (`mode: scripted`). |

## Definition-of-done evidence

- **One command:** `docker compose up -d --build`. Health returned `ok` from PowerShell `Invoke-WebRequest`.
- **Full seeded run:** proposal → explicit approval → evidence export → independent replay. Tested
  through the CLI, the UI (driven in a browser) and the test suite.
- **Rejected plan makes no simulator call:** `test_rejected_plan_makes_no_simulator_call` uses a call
  spy. The UI also showed "Not run — policy rejected the plan (no simulator call)" when baseline
  servers were set to 12.
- **Plan edit invalidates approval:** `test_edit_invalidates_prior_approval` and the CLI exit code 3.
  The UI also showed "The plan changed after approval. The previous approval is void".
- **Supported, sham and non-supporting results:**

  | Scenario | Result | Numbers |
  |---|---|---|
  | `capacity` | supported | mean d = 3.1309, 95% CI [2.4293, 3.8325] |
  | `sham` | supported null | all 20 d = 0 |
  | `low_benefit` | contradicted | mean d = 0.0797, CI upper 0.0949 < 0.1 |

  The same numbers came out on the Windows host and in the Linux container.
- **Replay and corrupted evidence:** replay verifies 40/40 calls. Corrupted values, forged hashes,
  outcome flips, plan edits and malformed JSON are all detected.
- **Simulator limits and invalid inputs:** covered in `tests/test_simulator.py`.
- **Docs:** `README.md`, `docs/methodology.md`, `docs/usage.md`, and three screenshots in
  `docs/screenshots/`. These were captured from the running container through the in-app browser at
  a 1440×1000 viewport, downscaled to 800 px.

## Actual test output (`python -m pytest -v`, Windows host, Python 3.12.10)

```
tests/test_proposer_and_cli.py::test_scripted_proposer_is_deterministic PASSED
tests/test_proposer_and_cli.py::test_ollama_output_goes_through_same_gate PASSED
tests/test_proposer_and_cli.py::test_ollama_malformed_output_rejected[no json here] PASSED
tests/test_proposer_and_cli.py::test_ollama_malformed_output_rejected[{"workload": "light"}] PASSED
tests/test_proposer_and_cli.py::test_ollama_malformed_output_rejected[{"hypothesis": "x", "workload": "light", "baseline_servers": "two", "intervention_servers": 3, "intervention_kind": "capacity", "n_seeds": 5, "seed_start": 1, "duration": 100, "min_effect": 0.1}] PASSED
tests/test_proposer_and_cli.py::test_ollama_unreachable_is_clean_error PASSED
tests/test_proposer_and_cli.py::test_cli_demo_end_to_end PASSED         
tests/test_proposer_and_cli.py::test_cli_propose_approve_run_and_edit PASSED
tests/test_simulator.py::test_same_seed_same_result PASSED              
tests/test_simulator.py::test_different_seed_different_trace PASSED     
tests/test_simulator.py::test_arms_share_trace_only_servers_differ PASSED
tests/test_simulator.py::test_sham_label_has_no_effect PASSED           
tests/test_simulator.py::test_more_servers_never_increase_wait PASSED   
tests/test_simulator.py::test_invalid_inputs_rejected[bad0] PASSED      
tests/test_simulator.py::test_invalid_inputs_rejected[bad1] PASSED      
tests/test_simulator.py::test_invalid_inputs_rejected[bad2] PASSED      
tests/test_simulator.py::test_invalid_inputs_rejected[bad3] PASSED      
tests/test_simulator.py::test_invalid_inputs_rejected[bad4] PASSED      
tests/test_simulator.py::test_invalid_inputs_rejected[bad5] PASSED      
tests/test_simulator.py::test_invalid_inputs_rejected[bad6] PASSED      
tests/test_simulator.py::test_invalid_inputs_rejected[bad7] PASSED      
tests/test_simulator.py::test_untyped_input_rejected_by_schema PASSED   
tests/test_simulator.py::test_customer_limit_enforced PASSED            
tests/test_simulator.py::test_heaviest_allowed_call_stays_within_limit PASSED
tests/test_workflow.py::test_supported_scenario PASSED                  
tests/test_workflow.py::test_sham_scenario_yields_exact_zero PASSED     
tests/test_workflow.py::test_low_benefit_scenario_is_not_supported PASSED
tests/test_workflow.py::test_few_seeds_can_be_inconclusive PASSED       
tests/test_workflow.py::test_t_critical_values PASSED                   
tests/test_workflow.py::test_same_approved_plan_same_evidence PASSED    
tests/test_workflow.py::test_rejected_plan_makes_no_simulator_call PASSED
tests/test_workflow.py::test_out_of_scope_plans_rejected[update0-seed_count] PASSED
tests/test_workflow.py::test_out_of_scope_plans_rejected[update1-seeds_unique] PASSED
tests/test_workflow.py::test_out_of_scope_plans_rejected[update2-seed_count] PASSED
tests/test_workflow.py::test_out_of_scope_plans_rejected[update3-duration_in_range] PASSED
tests/test_workflow.py::test_out_of_scope_plans_rejected[update4-metric_allowed] PASSED
tests/test_workflow.py::test_out_of_scope_plans_rejected[update5-tools_in_catalog] PASSED
tests/test_workflow.py::test_out_of_scope_plans_rejected[update6-intervention_kind_allowed] PASSED
tests/test_workflow.py::test_budget_enforced PASSED                     
tests/test_workflow.py::test_sham_must_not_change_servers PASSED        
tests/test_workflow.py::test_cannot_approve_rejected_plan PASSED        
tests/test_workflow.py::test_edit_invalidates_prior_approval PASSED     
tests/test_workflow.py::test_run_without_approval_refused PASSED        
tests/test_workflow.py::test_follow_up_gets_new_plan_id PASSED          
tests/test_workflow.py::test_tool_error_is_recorded_and_run_fails PASSED
tests/test_workflow.py::test_replay_verifies PASSED                     
tests/test_workflow.py::test_corrupted_metric_detected PASSED           
tests/test_workflow.py::test_forged_hash_still_caught_by_replay PASSED  
tests/test_workflow.py::test_outcome_flip_detected PASSED               
tests/test_workflow.py::test_plan_edit_after_run_detected PASSED        
tests/test_workflow.py::test_malformed_evidence_fails_cleanly PASSED    
tests/test_workflow.py::test_evidence_is_write_once PASSED              
tests/test_workflow.py::test_atomic_write_leaves_no_temp_files PASSED   
tests/test_workflow.py::test_report_cites_run_records PASSED            
============================= 54 passed in 2.03s ==============================
```

The same suite passes inside the container (`docker compose exec lab python -m pytest -q` → `54 passed`).

## Tamper check through the CLI (actual output)

One paired difference in `bundle.json` was edited, and the verifier was run:

```
  PASS schema_valid:
  FAIL bundle_hash: recorded=30c0f272ed25cb89... recomputed=19d377331fc04386...
  PASS plan_hash: recorded plan matches recorded plan hash
  PASS approval_bound: approval references this exact plan version
  PASS policy_allowed: plan passes the policy gate on re-check
  PASS calls_match_plan: expected 40 calls, recorded 40
  PASS replay_matches: 40 calls replayed exactly
  FAIL paired_differences: 19/20 pairs recomputed exactly
  FAIL analysis_matches: no analysis recorded or pairs could not be recomputed
verification: failed
```

## Known limitations and notes

- Work was committed directly to `main`, at the operator's instruction. The plan named a
  `feat/scientist-lab-v1` branch, but the operator required that everything end up on `main` only.
- At startup, Streamlit prints "External URL", which it gets from a public IP lookup. The app itself
  makes no other outbound calls. The Ollama call goes only to the configured `OLLAMA_HOST`.
- The screenshots are JPEG captures at 800 px width.
- Headless Chrome `--screenshot` only captures Streamlit's loading skeleton, so the screenshots were
  taken in the in-app browser.
