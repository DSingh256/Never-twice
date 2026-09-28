# Failed fixes are the most valuable memories your agent isn't keeping

*Most agents remember what happened. Almost none remember what the response
team already tried — and that's the difference between an agent that sounds
smart and one that prevents the same outage twice.*

If you ask a retrieval system "why did the DNS resolver fail last March?", it
will happily return the postmortem. That's the demo everyone has seen. What it
won't tell you — because almost no one stores it as a first-class fact — is
that the response team **already tried three fixes that didn't work** before
the fourth one stuck. The failure mode isn't missing information. It's missing
*experience*, specifically the expensive kind: the paths a competent team
walked down and had to abandon.

I've been building a deployment gate around that idea. The system is called
**Never Twice**, and every merge request is cross-examined against an
organizational memory of postmortems before it's allowed anywhere near
production. The memory layer is
[Hindsight](https://github.com/vectorize-io/hindsight), an agent-memory system
from [Vectorize](https://vectorize.io/what-is-agent-memory) that handles
retain, recall and reflection as first-class operations instead of a vector
database with extra steps.

This post is about the design decision that made the whole thing click:
**decomposing postmortems into typed memory units, with failed fixes as
citizens of equal rank to root causes.** And then — because a claim about
memory you can't measure is just vibes — how to build an ablation that makes
the memory's value falsifiable.

## What the gate does

The shape of the system is a funnel:

1. **Ingest.** A source list of real postmortem URLs gets fetched, cleaned,
   and passed through an extraction pass that must produce a validated
   incident object — symptoms, trigger change, root cause, **failed fixes**,
   successful fix, preventive actions. If extraction can't find a root cause,
   the incident is marked `rejected` and *not* retained. An agent memory full
   of guessed causes is worse than an empty one.
2. **Split.** Incidents are partitioned — by source, deterministically — into
   a **memory split** (safe to retain) and a **held-out split** (never
   retained, reserved for evaluation).
3. **Retain.** Each incident becomes several memory units in Hindsight, one
   document with typed facts, tagged so provenance survives: `kind:incident`,
   `kind:feedback`, and so on.
4. **Gate.** A proposed diff is summarized by an LLM into structured change
   facts (config keys, old→new values, affected component). Those facts drive
   a recall query into the bank, and a reflection step decides whether the
   change resembles a historically dangerous pattern.

Two guarantees hold everywhere, and they're enforced in code, not in prose:

- **Confidence is computed, never asked for.** The LLM produces a risk level
  and rationale; the confidence number is arithmetic over evidence count,
  retrieval scores and past feedback, done in Python
  (`backend/pipeline/confidence.py`). Asking a model how confident it is gets
  you a number that correlates with how confident it sounds.
- **The eval can't leak into itself.** Retention refuses held-out incidents at
  the API layer, and a live endpoint re-checks the invariant on every call:

```python
# backend/api/eval.py — the leak check the UI can prove at any time
heldout_ids = {i.id for i in session.exec(
    select(Incident).where(Incident.split == "heldout"))}
retained_incident_ids = {r.incident_id for r in session.exec(
    select(RetainedMemory).where(RetainedMemory.origin_kind == "incident"))}
leaked = sorted(heldout_ids & retained_incident_ids)
return {"heldout_leaked_into_bank": leaked, "ok": len(leaked) == 0}
```

## Typed memory units, not chunks

The standard ingest pattern for agent memory is: chunk the document, embed the
chunks, done. For postmortems that throws away the most useful signal — *the
role each fact played in the story*. A root cause and a failed fix have
opposite practical meanings, and a retrieval system that can't tell them
apart will hand the agent both with equal confidence.

So instead of chunks, the incident object is decomposed into units at retain
time, each retained as its own fact inside the Hindsight document:

```python
# backend/pipeline/retain.py (excerpt) — one incident, several typed units
units = [
    ("incident_summary", incident.title, [incident.summary]),
    ("failed_fix",       incident.title, incident.failed_fixes),
    ("successful_fix",   incident.title, [incident.successful_fix]),
    ("precursor",        incident.title, [incident.precursor_signature]),
]
for kind, title, facts in units:
    for fact in facts:
        hindsight.retain_memory(
            content=fact,
            context=f"{title} ({kind})",
            memory_kind=kind,
            tags=["kind:incident", f"unit:{kind}"],
            document_id=f"incident-{incident.id}",
        )
```

The consequence shows up at recall time. When a proposed change reduces
`min_healthy_hosts` from 2 to 0, the recall hits include, verbatim: *"reduced
the minimum healthy host count to zero — the fleet could go fully unhealthy
during a deploy"*, tagged `unit:failed_fix`. The gate's verdict then says not
just "this resembles a past incident" but **"a team tried this exact setting
before, and here's what it cost them."** That sentence changes how a reviewer
reacts.

## The loop closes with engineer feedback

Retained memory alone makes the gate smarter than a fresh model, but the
interesting behavior is what happens after a verdict ships. Every verdict can
be graded by a human — `good_catch` or `false_positive` — and the grade is
retained back into Hindsight as a feedback memory. The next analysis that
recalls similar changes sees it.

On an identical diff, before and after one feedback retention:

```
pass 1: level=low  confidence=0.125  evidence=0
(submit good_catch → retained as memory)
pass 2: level=low  confidence=0.4246 evidence=1
        ↑ verdict now cites the feedback memory by ID
```

Same diff, same model, same code. The only variable that moved is memory.
That's the whole point: the gate is a control loop with a human in it, not a
chat interface with a stateless model behind it. It uses
[Hindsight](https://hindsight.vectorize.io/) retain/recall for the incident
corpus and for the feedback ledger alike — the agent's improvement and its
knowledge live in the same memory system.

## Proving it: the A/B/C ablation

"This agent has memory" is not a claim. "This agent, with memory, catches
historically dangerous changes that the same model without memory rates as
low-risk" is. To make it falsifiable, every evaluation of the gate runs three
conditions over the same held-out benchmark:

- **A — no memory.** The raw model, diff in, verdict out.
- **B — memory as context.** Recall hits are pasted into the prompt.
- **C — the full pipeline.** Recall + reflection over evidence + feedback,
  i.e. the actual production path.

The benchmark itself is generated from the held-out split: for each held-out
incident, an LLM writes a *risky* PR that re-introduces the failure precursor
and a *safe* PR that touches the same component harmlessly, plus near-miss
controls. Ground truth comes from the incident record, not from the model's
opinion of its own output. Metrics — accuracy, precision, recall, false
positive rate — are computed from per-item rows, never asserted. The warm-up
feedback slice is excluded from scoring in all three conditions, per incident,
so the columns compare identical case sets.

The honest numbers, from a live run on Groq's `openai/gpt-oss-120b`:

| cond | scored | accuracy | precision | recall | F1 | FPR |
|---|---|---|---|---|---|---|
| A (no memory) | 6 | 0.33 | 0.00 | 0.00 | 0.00 | 0.00 |
| B (+ recall) | 6 | 0.67 | 1.00 | 0.50 | 0.67 | 0.00 |
| C (full pipeline) | 5 | 0.80 | 1.00 | 0.75 | 0.86 | 0.00 |

Two things to say about a table like that, because credibility lives in the
footnotes. First: **the naked model missed every historically dangerous
change** — recall 0.00, it rated the risky PRs safe — while the memory-backed
conditions recover them with precision 1.00 and a false-positive rate of
zero. The gate doesn't just catch more; it cries wolf less, which is what
actually determines whether engineers keep it enabled. (The full pipeline
also costs ~82 seconds a case against the naked model's 1.5 — memory has a
latency price, and the ablation shows that too.) Second: six scored cases is
a *smoke test*, not a benchmark — one C item hit a reflect timeout and is
recorded as an error rather than quietly dropped, which is why C scores over
5. The honest claim isn't "80% accuracy"; it's "memory moved every metric in
the right direction on a leakage-checked benchmark, and here's the harness
that will prove it on a bigger corpus." The sample is small because the
held-out corpus is 9 incidents, and I'd rather ship a small honest number
than a large soft one. The harness, not the headline, is the artifact.

The Tribunal view makes the same point interactively: one diff, judged three
times by three "witnesses" — the naked model, the model with recall, and the
full pipeline — with the delta rendered on screen. On the `min_healthy_hosts`
diff, witness A says *low risk at 13% confidence with zero evidence*; witness
B, having read the archive, says *high risk at 86% with 135 evidence items*.

## What I'd tell myself before starting

**1. Store the response, not just the incident.** The single highest-leverage
schema decision was making `failed_fixes` a required, first-class field. Root
causes tell you what went wrong; failed fixes tell you what *your own team
already tried* — and an agent that re-proposes a failed fix is worse than no
agent at all.

**2. Compute the number you're tempted to ask the model for.** Confidence,
evidence counts, retrieval thresholds: all of it lives in code. The one time
an LLM's self-reported confidence was accidentally surfaced, it took five
minutes to find a case where it was confidently wrong. Schema-validated
outputs plus computed metrics is the difference between a system that can be
audited and one that can only be quoted.

**3. Eval leakage is an architecture problem, not a test bug.** The held-out
split has to be enforced at the retention layer — one `if` that refuses to
retain anything not marked `memory` — and checked by an endpoint, not a test
that runs once. Anything weaker and your benchmark quietly grades the agent on
memories of itself.

**4. Free-tier LLM routing is a systems problem.** Reflect is an agentic,
multi-turn tool-calling loop; hosting it on the same model as everything else
means a rate-limit window in the middle of a demo. Routing the app's verdict
calls to one model and the memory server's reflection to another — or keeping
reflection local — buys the reliability back. Plan quota like you plan
capacity.

**5. The ablation is the product.** Before the A/B/C harness existed, the
project was a demo with opinions. After it, the project was a claim with a
measurement attached. It changed what I built next — every feature now gets
asked: which column does this move?

The code that matters most is not the LLM plumbing. It's the split
enforcement, the computed confidence, and the typed memory units. Those three
decisions are what let an agent's memory be *believed* rather than merely
*consulted* — and they're portable to any domain where the past contains
warnings, not just text.
