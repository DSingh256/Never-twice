# DESIGN — Never Twice

## Product thesis

Deployment gates today are static: lint rules, test suites, one-size approval
policies. None of them know what *this* organization has already lived through.
Never Twice makes organizational memory the gate: a pull request is judged
against the retained record of how similar changes failed before, what fixes
were tried and failed, what finally worked, and what engineers said about past
alerts.

The design constraint that shapes everything: **the system must stay honest**.
An empty system says so. A failure is archived, not hidden. A number on screen
is computed from records, not narrated by a model.

## The three Hindsight operations, as load-bearing structure

| Operation | What it holds | Why it is not vanilla RAG |
|---|---|---|
| `retain` | Per-incident memory units (summary, failed fixes, successful fix, precursor signature) + engineer feedback + PR outcomes | Memory is decomposed and typed, not chunked prose. "Failed fixes" exist nowhere in a classic RAG index. |
| `recall` | Query built from structured change facts, scoped with tags (`kind:*`, `bank:nevertwice`) | Retrieval feeds a *reasoning* step, it does not end in a citation list. |
| `reflect` | Reasoning over evidence + past feedback with a JSON schema, forced to cite what it stands on | The model must reconcile the proposed change with prior failure *and prior human judgement*. |

## Pipeline decisions

### Ingestion → extraction → split → retention

* Sources: 105 real postmortem URLs harvested from danluu's post-mortem
  collection by `scripts/discover_sources.py`; a declared selection policy
  (`max_total`, `max_per_org`) keeps the corpus diverse. Nothing is authored by
  hand.
* Extraction is schema-validated (Pydantic). An article without a stated root
  cause is **rejected**, not guessed into shape — a fabricated root cause would
  poison every later verdict.
* The memory/held-out split is a **pure function** of the incident rows, the
  order key and a config seed. Re-running cannot shift the partition silently;
  the seeded RNG draws indices over a canonical order.
* Retention refuses held-out incidents in code. The split guarantee is also
  *checkable live* via `GET /api/eval/split-check`, which intersects retained
  document IDs with held-out incident IDs. This caught a real bug during the
  build: the first ingestion predated the split fix and leaked all 9 held-out
  incidents into the bank; the purge script removed them and the check went
  green.

### Analysis (the verdict)

Five steps, each persisted and SSE-streamed:

1. `understand_diff` — LLM extracts structured change facts; no risk language
   allowed yet.
2. `recall_memories` — Hindsight recall over the facts, thresholded at
   `risk.min_retrieval_score`.
3. `recall_feedback` — scoped to `kind:feedback` memories.
4. `reflect` — Hindsight reflect with a response schema; the LLM proposes
   level/rationale/matches/checks grounded in evidence.
5. `verdict` — assembly in code: level normalisation (LLMs say "potentially
   high"), the small-sample guard (a lone memory cannot justify "elevated"),
   and **computed confidence**.

### Confidence is arithmetic, not opinion

```
confidence = w_e * evidence_factor    (saturating with #memories)
           + w_r * retrieval_factor   (mean normalised retrieval score)
           + w_f * feedback_factor    (net past engineer agreement, mapped to [0,1])
```

Weights, saturation and the floor live in `config/app.yaml`. The LLM is never
asked for a number it could flatter itself with.

### The feedback loop

Feedback arrives HMAC-signed, is retained as `kind:feedback` memory with
deterministic document IDs, and re-enters the loop at step 3. Because the
feedback factor is part of confidence and the feedback text is part of the
reflect prompt, one retained grade measurably moves the next verdict on a
similar change. This is demonstrated, not claimed — `scripts/feedback_probe.py`
prints the before/after on an identical diff.

### Evaluation: the A/B/C ablation

* The benchmark is **derived**: per held-out incident, the LLM writes one risky
  PR (introducing the incident's real precursor) and one safe PR (benign work
  on the same component), plus near-miss safe controls at a configured ratio so
  false positives are measurable. The generator never labels; labels come from
  the case kind.
* Conditions: **A** diff only (the "just RAG?" control is really "just LLM"),
  **B** diff + recalled memories as context, **C** the full pipeline
  (recall + reflect + feedback, with warm-up feedback simulated from ground
  truth on an earlier slice only — never the item being scored).
* Metrics (accuracy, precision, recall, F1, false-positive rate, mean
  confidence, mean latency) are computed from `eval_items` rows by SQL-free
  aggregation in `_compute_metrics`. The run stores its exact config snapshot
  so results can never be quietly re-tuned.

## The Black Box Archive (product form)

The UI treats the system like a flight recorder: every verdict is a *case*,
every case carries its step-by-step replay, its evidence, its confidence bars,
and its feedback trail. Five screens:

1. **Briefing** — live health, the wall of prior verdicts, feedback pulse.
2. **Analysis Room** — paste a diff, watch the verdict being reached step by
   step over SSE.
3. **Learning Lab** — where the loop closes: feedback ledger, mechanism,
   measured effect.
4. **Atlas** — the memory bank itself: sections by memory kind, tag cloud,
   live recall.
5. **Eval** — the A/B/C table, straight from `eval_items`.

Paper-and-ink "archive" visual language: evidence labels in small-caps mono,
stamps for levels, honest empty states ("the archive fills as real memory is
ingested"). No sample data exists anywhere in the product.

## Rules the codebase enforces

1. All Hindsight API knowledge lives in `backend/memory/hindsight_client.py`.
2. All LLM calls validate against Pydantic schemas, retry with backoff, and
   fall through a model chain before surfacing `LlmCallError`.
3. Product behaviour in `config/*.yaml`; secrets in `.env` only.
4. Confidence computed in code.
5. Held-out never retained — enforced and live-checkable.
6. Failures are records: a failed analysis is displayed as failed, never
   retried into a fake success.
