# Video Script — "The AI reviewer that remembers every failed fix" (3 min)

Name: [YOUR NAME]. Format: screen recording + voiceover, 1080p.
Before recording: close extra tabs, bump terminal font, silence notifications.

---

## 1. Quick intro (0:00–0:30)

**ON SCREEN:** The Briefing page (localhost:3001), then a fast scroll through
the Atlas. Let the wall of verdicts register.

**SAY:**

> "I'm [name]. Every on-call engineer has lived this: a change ships that
> recreates a failure you've *already had*. I built a deployment gate that
> stops it — it remembers every postmortem this organization has ever filed,
> and it cross-examines every pull request against that memory before merge.
> It's called Never Twice."

---

## 2. The problem: an agent without memory (0:30–1:00)

**ON SCREEN:** The Tribunal page (`/tribunal`). Load the dns-resolver diff,
but DON'T convene yet. Point at the three empty witness seats.

**SAY:**

> "Here's the problem in one screenshot. This is a proposed change that sets
> minimum healthy hosts to zero — a classic way to take a fleet down. A
> standard LLM reviewer knows nothing about our history. Watch the seat on
> the left — that's the same model you'd get with any generic AI gate. It's
> about to rate this change low-risk, because it's guessing from first
> principles. Thirteen percent confidence. Zero evidence. That's the agent
> without memory."

Convene the tribunal here, then cut to the next section while B testifies.

---

## 3. The demo: memory in the loop (1:00–2:30)

**ON SCREEN:** Stay on the Tribunal. Witness B lands: HIGH RISK, 86%,
evidence 135.

**SAY:**

> "Same diff. Same model. The only change: now it can read the archive.
> High risk, eighty-six percent, a hundred and thirty-five evidence items.
> In the bank are typed memory units from real postmortems — summaries,
> what finally worked, and crucially, the *failed fixes*: the things a smart
> team already tried before it worked. The verdict cites the actual incident
> where this exact setting caused an outage."

**ON SCREEN:** Switch to the Atlas (`/atlas`). Search "minimum healthy
hosts". Show a failed-fix unit with its source URL.

**SAY:**

> "This is the memory itself. Notice the failed-fix unit — 'reducing the
> minimum healthy host count to zero, the fleet went fully unhealthy.' Most
> RAG demos can tell you what broke. This tells you what your own engineers
> already tried in vain. That's the line between an agent that sounds smart
> and one that prevents repeats."

**ON SCREEN:** Learning Lab (`/learning-lab`). Show the feedback ledger, then
the feedback probe script output in the terminal.

**SAY:**

> "And the loop closes with humans. An engineer grades a verdict — good
> catch, or false positive. The grade is retained as memory, and the next
> verdict cites it by ID. On an identical diff, one piece of feedback moved
> confidence from twelve point five to forty-two percent. That's a control
> loop, not a suggestion box."

**ON SCREEN:** Eval page (`/eval`). Show the A/B/C table and the split-check
passing.

**SAY:**

> "And because a claim you can't measure is just vibes — the same diff is
> scored three ways: no memory, memory as context, full pipeline. False
> positive rate drops from one in two to zero the moment memory enters the
> pipeline. The held-out split is enforced at the retention layer and
> re-proven live, so the eval can't grade the agent on memories of itself."

---

## 4. Wrap-up (2:30–3:00)

**ON SCREEN:** Back to the Tribunal's delta panel: "+64.4 pts, low → high."

**SAY:**

> "The surprise for me wasn't that memory made the agent more accurate. It's
> that it made it *calmer* — fewer false alarms, because the model stops
> pattern-matching on vibes and starts pattern-matching on lived experience.
> Failed fixes are the most valuable memories your agent isn't keeping.
> Code and the full evaluation harness are on the repo — link below."

---

## 5 YouTube titles

1. The AI reviewer that remembers every failed fix
2. I measured my AI agent's memory by deleting it
3. Why your RAG demo can't prevent outages (and what can)
4. Three judges, one diff: I made my agent prove its memory works
5. The deployment gate that never lets the same incident happen twice
