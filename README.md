# Never Twice

> A deployment gate powered by organizational memory. It remembers how systems
> failed before — root causes, failed fixes, what finally worked, engineer
> feedback — and warns developers on a pull request *before* they repeat a
> historically dangerous change.

Built on [Hindsight](https://hindsight.vectorize.io) (Vectorize). Built for the
"hack with Hyd" hackathon.

## Why this is not "just RAG over postmortems"

The judge question, answered by construction:

1. **Memory has structure.** Postmortems are decomposed into retainable units —
   incident summaries, *failed fixes*, what finally worked, precursor
   signatures. Failed fixes are first-class citizens: most RAG demos can tell
   you what broke, not what a smart team already tried in vain.
2. **The loop closes.** Engineers grade verdicts (`good_catch` /
   `false_positive`); grades are retained as memory and measurably change later
   verdicts. Proven live: on an identical diff, confidence went **0.125 →
   0.4246** after one feedback retention, and the next verdict cited the
   feedback memory by ID.
3. **The ablation is measured, not asserted.** The same held-out benchmark is
   scored three ways (no memory / memory as context / memory + reflect +
   feedback), with accuracy, precision, recall and false-positive rate computed
   from per-item rows. Latest run (Groq `openai/gpt-oss-120b`):

   | cond | scored | accuracy | precision | recall | F1 | FPR | latency |
   |---|---|---|---|---|---|---|---|
   | A — LLM only | 6 | 0.33 | 0.00 | 0.00 | 0.00 | 0.00 | 1.5s |
   | B — + recall | 6 | 0.67 | 1.00 | 0.50 | 0.67 | 0.00 | 6.9s |
   | C — full pipeline | 5 | 0.80 | 1.00 | 0.75 | 0.86 | 0.00 | 82s |

   The naked model missed every historically dangerous change (recall 0.00);
   memory-backed conditions hold the false-positive rate at zero. One C item
   errored on a reflect timeout and is recorded, not hidden. See
   `GET /api/eval/runs` for per-item rows.

## The Tribunal (live before/after)

The ablation, made interactive: `/tribunal` judges one diff three ways — the
naked model, the model shown recalled memories, and the full production
pipeline — with witness verdicts streaming into their seats and a delta panel
quantifying what the archive changed. Scripted version:
`scripts/tribunal_probe.py`.

## Architecture (5-minute tour)

```
sources.yaml (105 real postmortem URLs)
      │  fetch (httpx+bs4) → extract (schema-validated LLM, "rejected" if no root cause)
      ▼
SQLite (incidents) ── seeded split ──► memory (17) / held-out (9)
      │                                     │
      ▼ retain (Hindsight)                  ▼ benchmark generator (LLM writes
Hindsight bank ◄── feedback ────┐           │  risky + safe PRs per held-out incident)
   │   │   │                    │           ▼
   │   │   └─ recall ◄──────────┤      data/benchmark/benchmark.json
   │   └───── reflect ──────────┤           │
   └───────── feedback recall ──┘           ▼
      │                              A/B/C ablation runner
      ▼                                     │
verdict + COMPUTED confidence               ▼
      │                               /api/eval/runs + Eval page
      ▼
Analysis Room (SSE step replay) · Learning Lab · Atlas · Archive
```

* `backend/pipeline/` — fetch, extract, split, retain, analysis, confidence,
  benchmark, ablation
* `backend/api/` — FastAPI routers: health, ingest, analyze (+SSE), feedback,
  memory, eval, webhooks
* `backend/memory/hindsight_client.py` — every Hindsight call, in one place
* `frontend/` — Next.js 15 + Tailwind 4 "Black Box Archive" UI
* `config/*.yaml` — all product behaviour; `.env` — all secrets
* `scripts/` — probes and CLIs used to verify everything live

## Quick start (local, offline-capable)

Prereqs: Python 3.12, Node 20+, [Ollama](https://ollama.com) with
`ollama pull llama3.2` and `ollama pull qwen2.5:7b`.

```bash
# 1. Environment
cp .env.example .env          # then edit if you deviate from the defaults

# 2. Python deps
py -3.12 -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt   # (Windows; on unix: python3 -m venv)

# 3. Start Hindsight (embedded Postgres, ONNX embeddings, FlashRank reranker)
bash scripts/start-hindsight.sh          # waits for /health, prints the bank id

# 4. Start the backend
.venv/Scripts/python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000

# 5. Ingest real postmortems → extract → split → retain
curl -X POST localhost:8000/api/ingest/run

# 6. Frontend
cd frontend && npm install && npm run dev   # http://localhost:3000
```

Then open the **Analysis Room**, paste a diff like:

```diff
--- a/infra/dns-resolver/terraform/main.tf
+++ b/infra/dns-resolver/terraform/main.tf
@@ -14,9 +14,7 @@
-  min_healthy_hosts = 2
+  min_healthy_hosts = 0
```

…and watch the verdict cite the memories it stood on, step by step.

## The demo script (docs/DEMO.md)

A full judged walkthrough lives in [`docs/DEMO.md`](docs/DEMO.md), including
the feedback-loop moment (live confidence shift) and the A/B/C table.

## Honest-system guarantees

| Guarantee | Where enforced |
|---|---|
| No hardcoded/sample data anywhere | `scripts/hardcode_audit.py` (CI-runnable); UI renders real DB rows or empty states |
| Confidence computed, never LLM-produced | `backend/pipeline/confidence.py` |
| Held-out incidents never retained | `retain.py` refuses `split != "memory"`; `GET /api/eval/split-check` proves it live |
| LLM output always schema-validated | `backend/llm/client.py` (Pydantic + retry + model-chain fallback) |
| Every LLM/Hindsight difference in one module | `backend/memory/hindsight_client.py` |
| Feedback is authenticated | HMAC-SHA256 signed bodies (`FEEDBACK_SIGNING_SECRET`) |
| Webhooks are authenticated | `X-Hub-Signature-256` over the raw body (`GITHUB_WEBHOOK_SECRET`); 503 when unconfigured |
| Failures are archived, never hidden | `analyses.status='failed'` shown in the Archive UI verbatim |

## Configuration

All product behaviour lives in `config/*.yaml` — thresholds, risk weights,
split seed, benchmark shape, ablation conditions, model chains. Secrets live
only in `.env` (see `.env.example`). Nothing tunable is hardcoded.

## API map

```
GET  /api/health                     real connectivity: Hindsight, LLM, DB
GET  /api/config                     the effective product configuration
POST /api/ingest/run|sources|retry   ingestion pipeline
POST /api/analyze                    submit a diff (ui|api|webhook origin)
GET  /api/analyze/{id}/stream        SSE replay of analysis steps + verdict
GET  /api/analyses[/{id}]            archive records
POST /api/feedback                   HMAC-signed verdict feedback → memory
GET  /api/feedback                   feedback ledger
GET  /api/memory/stats|list|search   Atlas/Console introspection
GET  /api/memory/graph|tags          Hindsight graph/tags passthrough
POST /api/eval/generate              LLM-writes benchmark from held-out incidents
POST /api/eval/run                   A/B/C ablation (background)
GET  /api/eval/runs[/{id}]           measured results
GET  /api/eval/split-check           live proof: no held-out leakage
POST /api/webhooks/github            signed GitHub PR gate
GET  /api/webhooks/github/status     readiness
```

## Testing

```bash
.venv/Scripts/python.exe -m pytest tests/ -v
```

Covers extraction validation (no-invention rules), confidence computation,
split determinism, the held-out-not-retained guarantee, benchmark loading,
verdict level normalisation, feedback signature verification and webhook
signature verification.

## Design docs

* [`DESIGN.md`](DESIGN.md) — architecture decisions in depth
* [`DECISIONS.md`](DECISIONS.md) — the decision log (D1…D9)
* [`docs/DEMO.md`](docs/DEMO.md) — judged walkthrough
