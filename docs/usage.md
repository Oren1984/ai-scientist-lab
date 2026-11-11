# Usage (Windows PowerShell)

## Option A — Docker Compose (recommended)

```powershell
docker compose up -d --build
```

This builds the image and starts the app at <http://127.0.0.1:8501>. The port is published on
`127.0.0.1` only. The container runs as a non-root user with a read-only root filesystem, no added
capabilities and `no-new-privileges`. Evidence is kept in the `lab-data` volume.

Smoke checks:

```powershell
(Invoke-WebRequest http://127.0.0.1:8501/_stcore/health -UseBasicParsing).Content     # -> ok
docker compose exec lab python -m pytest -q                                            # -> all tests pass
docker compose exec lab python -m scientist_lab demo --approve-as $env:USERNAME        # -> 3 runs, all verified
docker compose exec lab python -m scientist_lab list
```

Stop the app with `docker compose down`. Add `-v` to also delete the evidence volume.

## Option B — local Python (3.11+)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -e .
python -m pytest -q
python -m scientist_lab demo --approve-as $env:USERNAME
streamlit run app/streamlit_app.py      # binds 127.0.0.1:8501 via .streamlit/config.toml
```

Evidence goes to `.\data` by default. Set `$env:SCIENTIST_LAB_DATA` to change the location.

## CLI walkthrough (one plan, step by step)

```powershell
python -m scientist_lab propose --scenario capacity --out plan.json   # capacity | sham | low_benefit
python -m scientist_lab validate plan.json                            # policy gate (exit 2 if rejected)
python -m scientist_lab approve plan.json --by $env:USERNAME          # binds approval to the plan hash
python -m scientist_lab run plan.json                                 # runs, verifies, writes report.md
python -m scientist_lab verify <run_id>                               # independent replay at any time
```

If you edit `plan.json` after approval, `run` refuses it with exit code 3: the approval is void. An
out-of-scope plan, such as `"workload": "extreme"`, is rejected with exit code 2, and no simulator call
is made.

Exit codes: 0 ok · 1 run failed or verification failed · 2 policy rejection · 3 missing or void
approval · 4 proposal or lookup error.

## UI

- **Plan & Approval**:
  1. Choose a proposer and a question, then press *Propose plan*.
  2. Review the plan table and the policy-gate result.
  3. Approve as a named operator.
  4. Press *Run approved plan*.

  Opening *Edit plan* and applying a change voids the approval. Out-of-range values are rejected,
  with the reasons listed.
- **Runs & Evidence** shows the scientific result and verification status side by side. It has a
  paired comparison chart, a paired differences chart (with 95% CI band and min_effect line), and a
  pairs table with record IDs. Use it to re-verify, download the JSON bundle and Markdown report, or
  start an exploratory follow-up under a new plan ID. Expanders show the tool call log, plan, approval,
  policy decision, versions and the policy rejections log.
- **Help Center** gives a short explanation of the workflow, statuses and allowed parameters.

Deep links: `?page=runs&run=<run_id>`, `?page=plan`, `?page=help`.

## Optional local model (Ollama)

```powershell
ollama serve                    # in another terminal
ollama pull llama3.2
$env:OLLAMA_MODEL = "llama3.2"  # Docker default host: http://host.docker.internal:11434
```

In the UI, choose **Ollama**. From the CLI, run `python -m scientist_lab propose --ollama "<question>"`.
The model's JSON goes into the same typed plan and through the same policy gate and approval. The
report states the proposer mode and model. If Ollama is unreachable, you get a clear error, and the
scripted path keeps working offline.
