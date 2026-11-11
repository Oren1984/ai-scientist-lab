import json

import pytest

from scientist_lab.cli import main
from scientist_lab.policy import validate_plan
from scientist_lab.proposer import OllamaProposer, ProposerError, ScriptedProposer


def test_scripted_proposer_is_deterministic():
    a, b = ScriptedProposer().propose("capacity"), ScriptedProposer().propose("capacity")
    strip = lambda p: p.model_dump(exclude={"plan_id", "created_at"})  # noqa: E731
    assert strip(a) == strip(b)


def test_ollama_output_goes_through_same_gate():
    good = json.dumps({"hypothesis": "More servers cut waiting.", "workload": "heavy", "baseline_servers": 3,
                       "intervention_servers": 5, "intervention_kind": "capacity", "n_seeds": 10,
                       "seed_start": 42, "duration": 400, "min_effect": 0.2})
    plan = OllamaProposer(model="test-model").parse("Does capacity help?", f"Sure! {good}")
    assert plan.proposer.mode == "ollama" and plan.proposer.model == "test-model"
    assert validate_plan(plan).allowed

    bad = json.loads(good) | {"workload": "datacenter", "intervention_servers": 64}
    plan = OllamaProposer().parse("Does capacity help?", json.dumps(bad))
    assert not validate_plan(plan).allowed


@pytest.mark.parametrize("raw", ["no json here", '{"workload": "light"}', '{"hypothesis": "x", "workload": "light",'
                                 ' "baseline_servers": "two", "intervention_servers": 3, "intervention_kind":'
                                 ' "capacity", "n_seeds": 5, "seed_start": 1, "duration": 100, "min_effect": 0.1}'])
def test_ollama_malformed_output_rejected(raw):
    with pytest.raises(ProposerError):
        OllamaProposer().parse("Does capacity help?", raw)


def test_ollama_unreachable_is_clean_error():
    with pytest.raises(ProposerError, match="not reachable"):
        OllamaProposer(host="http://127.0.0.1:9", timeout=1).propose("Does capacity help?")


def test_cli_demo_end_to_end(tmp_path, capsys):
    assert main(["--data", str(tmp_path), "demo", "--approve-as", "tester"]) == 0
    out = capsys.readouterr().out
    assert out.count("verification=verified") == 3
    assert "outcome=supported" in out and "outcome=contradicted" in out
    runs = list((tmp_path / "runs").iterdir())
    assert len(runs) == 3 and all((r / "report.md").exists() for r in runs)


def test_cli_propose_approve_run_and_edit(tmp_path, capsys):
    plan_file = tmp_path / "plan.json"
    data = ["--data", str(tmp_path / "d")]
    assert main(data + ["propose", "--scenario", "sham", "--out", str(plan_file)]) == 0
    assert main(data + ["run", str(plan_file)]) == 3  # not approved yet
    assert main(data + ["approve", str(plan_file), "--by", "tester"]) == 0
    assert main(data + ["run", str(plan_file)]) == 0
    plan = json.loads(plan_file.read_text())
    plan["duration"] = 700.0
    plan_file.write_text(json.dumps(plan))
    assert main(data + ["run", str(plan_file)]) == 3  # edit voids approval
    plan["workload"] = "extreme"
    plan_file.write_text(json.dumps(plan))
    assert main(data + ["validate", str(plan_file)]) == 2
    assert main(data + ["run", str(plan_file)]) == 2  # policy rejection, no simulator call
