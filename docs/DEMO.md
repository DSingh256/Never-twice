# DEMO — the judged walkthrough (10 minutes)

Everything below runs against the live system; every number shown on screen is
computed from real records. If a step shows an empty state, the demo says so
out loud — that is the product being honest, not a failure of the demo.

## 0. Start everything

```bash
bash scripts/start-hindsight.sh                    # Hindsight on :8888 (bank nevertwice-prod)
.venv/Scripts/python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
cd frontend && npm run build && npx next start -p 3001   # or npm run dev
```

Health check (all three must be green): <http://localhost:3001> header strip,
or `curl localhost:8000/api/health`.

## 1. The memory exists (2 min) — Atlas

Open **/atlas**. Show:

- Incident summaries, failed fixes, what worked — retained from *real*
  postmortems, each carrying its source URL and tags (`kind:*`, `bank:nevertwice`).
- Engineer feedback section: this grows live later in the demo.
- Live recall: search "minimum healthy hosts" and watch the bank answer.

Talking point: "These are not chunks of prose. Each unit is a typed fact — the
*failed fix* units are the gold: RAG demos tell you what broke; this tells you
what a smart team already tried in vain."

## 2. The gate (3 min) — Analysis Room

Open **/analyze**. Paste the dangerous diff (from the demo box below or any
risky terraform change) and press **run verdict**.

Watch the SSE replay: understand_diff → recall_memories → recall_feedback →
reflect → verdict. Open the resulting case page:

- the **level stamp** and **computed confidence bar**,
- the memories the verdict stood on (with scores),
- suggested checks before merge.

Demo diff:

```diff
diff --git a/infra/dns-resolver/terraform/main.tf b/infra/dns-resolver/terraform/main.tf
--- a/infra/dns-resolver/terraform/main.tf
+++ b/infra/dns-resolver/terraform/main.tf
@@ -14,9 +14,7 @@
-  min_healthy_hosts = 2
+  min_healthy_hosts = 0
```

Talking point: "The verdict is not the model's mood. Level is normalised, a
lone memory cannot justify an elevated alert, and confidence is arithmetic over
evidence, retrieval quality and past feedback — config-driven, never asked from
the LLM."

## 3. The loop closes live (3 min) — Learning Lab

Two options (A is faster, B is the full proof):

**A. UI loop.** On the case page from step 2, submit feedback
(`good_catch`, note: "this exact pattern broke us before"). Then re-run the
same diff in the Analysis Room. The new verdict's confidence is higher and the
case page shows **learned-from-feedback** entries citing the retained feedback
memory by ID.

**B. Scripted proof.**

```bash
.venv/Scripts/python.exe scripts/feedback_probe.py --reuse-baseline <case_id>
```

Expected output (real run from the build):

```
== pass 1: analysis 6 level=low confidence=0.125 evidence=0
== submitting feedback: good_catch (200, retained)
== pass 2: analysis 7 level=low confidence=0.4246 evidence=1
RESULT: VERDICT CHANGED after feedback
```

Talking point: "One grade, measurably different next verdict — the loop is a
control system, not a suggestion box."

## 4. The measured claim (2 min) — Eval

Open **/eval** and show the latest run's table:

```
cond  scored    acc  prec   rec    f1   fpr   conf  lat_ms
A                                                   ← LLM only
B                                                   ← + recall
C                                                   ← + reflect + feedback
```

- The benchmark was generated from **held-out** incidents (one risky + one safe
  PR per incident, plus near-miss controls).
- `GET /api/eval/split-check` shows `heldout_leaked_into_bank: []` — the eval
  is not graded on memories of itself.
- Metrics are computed from per-item rows (`/api/eval/runs/{id}`); the run
  stores its config snapshot.

Talking point: "Condition A is what a generic LLM gate knows: nothing about us.
The delta from A to C is the value of organizational memory, measured."

## 5. The archive (1 min) — Archive + Learning Lab

Open **/archive**: every case, including failures ("a black box that hides
crashes teaches nothing"). Open **/learning-lab**: the feedback ledger with
reviewer, note, and the memory ids it produced.

## 6. The webhook (optional, 1 min)

```bash
GITHUB_WEBHOOK_SECRET=... # in .env
# configure the repo webhook to POST /api/webhooks/github, then open a PR
curl -s localhost:8000/api/webhooks/github/status
```

A PR that touches `min_healthy_hosts` gets an analysis with `origin=webhook`
in the Archive; the verdict streams to any SSE listener.

## Fallback lines (if something is slow)

- reflect is slow on CPU → say "local model, cold start; in deployment the
  chain falls back per config/llm.yaml".
- an analysis failed → open the Archive and show the failure record as a
  feature: "we archive failures, we don't retry them into fake successes".
