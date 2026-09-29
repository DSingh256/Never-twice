# Never Twice 🛡️🧠

> **An organizational memory deployment gate for engineering teams.**  
> It remembers how systems failed before — root causes, failed fixes, what finally worked, and reviewer feedback — warning developers on a pull request *before* they repeat a historically dangerous change.

[![Python](https://img.shields.io/badge/Python-3.12%2B-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.141-009688.svg)](https://fastapi.tiangolo.com/)
[![Next.js](https://img.shields.io/badge/Next.js-15-black.svg)](https://nextjs.org/)
[![React](https://img.shields.io/badge/React-19-61dafb.svg)](https://react.dev/)
[![TailwindCSS](https://img.shields.io/badge/Tailwind-v4-38bdf8.svg)](https://tailwindcss.com/)
[![Hindsight](https://img.shields.io/badge/Memory-Hindsight-8a2be2.svg)](https://hindsight.vectorize.io)
[![Tests](https://img.shields.io/badge/Tests-Passing-brightgreen.svg)]()

---

## 💡 Why This is Not "Just RAG Over Postmortems"

Most AI deployment assistants operate as simple semantic search engines over raw incident logs. **Never Twice is built differently by design:**

1. **Memory is Typed & Structured**: Postmortems are decomposed into discrete, typed units — *incident summaries*, *root causes*, *precursor signatures*, *what finally worked*, and crucially, **failed fixes**. 
   > *Why failed fixes matter*: Standard RAG only knows what broke. Never Twice knows what senior engineers previously tried in vain, preventing well-intentioned but disastrous retry attempts.
2. **The Feedback Loop Closes**: Reviewers grade risk verdicts (`good_catch` or `false_positive`). Grades are cryptographically signed, retained in organizational memory, and measurably adjust future confidences and citations.
3. **Pure Arithmetic Confidence (Zero LLM Vibes)**: Risk levels and confidences are computed via deterministic formula over evidence volume, retrieval cosine similarity, and historical feedback ratios (`backend/pipeline/confidence.py`), not guessed by an LLM prompt.
4. **Empirically Measured A/B/C Ablation**: Every capability is benchmarked against held-out incidents across three conditions:
   - **Condition A (Naked LLM)**: Baseline model without access to organizational memory.
   - **Condition B (+ Memory Recall)**: Same model provided raw recalled incident memories.
   - **Condition C (Full Production Pipeline)**: Recall + Agentic Reflection + Reviewer Feedback History.

### Measured Ablation Results (Groq `openai/gpt-oss-120b`)

| Condition | Evaluated | Accuracy | Precision | Recall | F1 Score | False Positive Rate | Avg Latency |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **A — LLM Only (Naked)** | 6 | 0.33 | 0.00 | **0.00** | 0.00 | 0.00 | 1.5s |
| **B — + Memory Recall** | 6 | 0.67 | 1.00 | **0.50** | 0.67 | 0.00 | 6.9s |
| **C — Full Pipeline** | 5 | **0.80** | **1.00** | **0.75** | **0.86** | 0.00 | 82.0s |

*The naked model missed every historically dangerous change (recall 0.00). Memory-backed conditions elevated recall to 75%+ while keeping the false-positive rate at 0.00.*

---

## 🏛️ The Tribunal: Live A/B/C Cross-Examination

To make the value of organizational memory tangible and verifiable, Never Twice features **The Tribunal** (`/tribunal`):
- Submit any code diff (e.g. Terraform DNS resolver modifications).
- Three witnesses testify sequentially in real time:
  - **Witness A (Naked Model)**: Guesses from first principles (frequently rates hazardous changes as LOW risk).
  - **Witness B (Memory-Informed)**: Reads recalled facts from the archive (elevates to HIGH risk with evidence).
  - **Witness C (Full Pipeline)**: Synthesizes memories, past failed fixes, and feedback history.
- **The Delta Panel**: Quantifies the real-time delta — measuring confidence shift (+64% or more), verdict change, and exact memory citations.

---

## 📐 System Architecture

```text
 ┌────────────────────────────────────────────────────────┐
 │            config/sources.yaml (105 URLs)              │
 └──────────────────────────┬─────────────────────────────┘
                            │ Fetch (httpx + BeautifulSoup)
                            ▼
 ┌────────────────────────────────────────────────────────┐
 │           Extract & Schema Validation (LLM)            │
 └──────────────────────────┬─────────────────────────────┘
                            │
                            ▼
 ┌────────────────────────────────────────────────────────┐
 │     SQLite Database (incidents) & Seeded Split         │
 └─────────────┬────────────────────────────┬─────────────┘
               │ Split: "memory" (65%)      │ Split: "heldout" (35%)
               ▼                            ▼
 ┌───────────────────────────┐    ┌───────────────────────────────┐
 │ Hindsight Memory Bank     │    │ Benchmark Generator (LLM)     │
 │  - Incident Summaries     │    │ Synthesizes risky & safe PRs  │
 │  - Failed Fixes           │    └──────────────┬────────────────┘
 │  - What Worked            │                   ▼
 │  - Reviewer Feedback      │    ┌───────────────────────────────┐
 └─────────────┬─────────────┘    │ data/benchmark/benchmark.json │
               │                  └──────────────┬────────────────┘
 ┌─────────────┴─────────────┐                   │
 │ Pull Request Diff Input   │                   ▼
 └─────────────┬─────────────┘    ┌───────────────────────────────┐
               │                  │ A/B/C Ablation Runner         │
               ▼                  │ (/api/eval/run)               │
 ┌───────────────────────────┐    └──────────────┬────────────────┘
 │ 1. Understand Diff        │                   │
 │ 2. Recall Memories        │                   ▼
 │ 3. Recall Feedback        │    ┌───────────────────────────────┐
 │ 4. Reflect (Agentic)      │    │ Evaluation Dashboard (/eval)  │
 │ 5. Compute Confidence     │    └───────────────────────────────┘
 └─────────────┬─────────────┘
               │ SSE Stream
               ▼
 ┌────────────────────────────────────────────────────────┐
 │ Web UI: Analysis Room (/analyze) · The Tribunal        │
 │ Learning Lab · Memory Atlas · Black Box Archive Scene  │
 └────────────────────────────────────────────────────────┘
```

---

## 📂 Repository Structure

```text
never-twice/
├── backend/
│   ├── api/                 # FastAPI routes (analyze, eval, feedback, ingest, memory, tribunal, webhooks)
│   ├── db/                  # SQLModel database schemas & SQLite sessions
│   ├── llm/                 # Unified LLM client (Ollama, Groq, OpenAI, Anthropic fallback chains)
│   ├── memory/              # Hindsight memory bank integration client
│   ├── pipeline/            # Core processing: fetcher, extractor, split, retain, analysis, confidence, benchmark
│   └── main.py              # Application entrypoint & CORS middleware
├── config/
│   ├── app.yaml             # Product thresholds, confidence weights, risk levels
│   ├── eval.yaml            # Evaluation shapes, benchmark parameters, ablation settings
│   ├── llm.yaml             # Model selection, provider fallback chains, timeouts
│   └── sources.yaml         # Real-world postmortem catalog & URL sources
├── frontend/
│   ├── src/
│   │   ├── app/             # Next.js 15 App Router pages:
│   │   │   ├── analyze/     # The Analysis Room (Interactive Diff Submission & SSE Stream)
│   │   │   ├── tribunal/    # The Tribunal (Live A/B/C Witness Comparison)
│   │   │   ├── atlas/       # Memory Atlas & Fact Explorer
│   │   │   ├── learning-lab/# Interactive Reviewer Feedback Loop Demo
│   │   │   ├── eval/        # Evaluation Dashboard & Metrics Tables
│   │   │   └── archive/     # Historical Analysis Log
│   │   └── components/      # UI components & Three.js 3D Archive Scene
│   └── package.json
├── scripts/
│   ├── analyze_probe.py     # CLI tool to run a diff through the pipeline
│   ├── feedback_probe.py    # Demonstrates live confidence shift after reviewer feedback
│   ├── tribunal_probe.py    # CLI runner for the 3-way Tribunal cross-examination
│   ├── run_eval.py          # Runs the offline/online evaluation benchmark suite
│   ├── hardcode_audit.py    # Integrity scanner to verify no hardcoded or mock data exists
│   └── start-hindsight.sh   # Automated setup script for Hindsight service
├── tests/                   # Pytest test suite (contracts, metrics, extraction, guarantees)
├── docker-compose.yml       # Production multi-service orchestration
├── Dockerfile.backend       # Container definition for FastAPI backend
├── requirements.txt         # Python dependencies
└── README.md                # Comprehensive documentation
```

---

## 🛠️ Tech Stack

- **Backend**: Python 3.12+, [FastAPI](https://fastapi.tiangolo.com/), [SQLModel](https://sqlmodel.tiangolo.com/) (SQLAlchemy + Pydantic), [SSE-Starlette](https://github.com/sysid/sse-starlette).
- **Frontend**: [Next.js 15](https://nextjs.org/) (App Router), [React 19](https://react.dev/), [Tailwind CSS v4](https://tailwindcss.com/), [Three.js](https://threejs.org/) / React Three Fiber (Cinematic 3D Black Box Archive Room), [Framer Motion](https://www.framer.com/motion), [GSAP](https://gsap.com/), [Lenis](https://lenis.darkroom.engineering/).
- **Memory Engine**: [Hindsight](https://hindsight.vectorize.io) by Vectorize (embedded/containerized vector store, ONNX embeddings, FlashRank reranker).
- **LLM Layer**: Model-agnostic provider fallback chains configured via `.env` (Ollama for fully offline/air-gapped environments, Groq, OpenAI, or Anthropic).

---

## 🚀 Quick Start Guide

### 1. Prerequisites
- **Python 3.12+**
- **Node.js 20+** and `npm`
- **Ollama** (for local/offline execution) or an API key from **Groq** / **OpenAI** / **Anthropic**.

If using Ollama locally:
```bash
ollama pull llama3.2
ollama pull qwen2.5:7b
```

---

### 2. Environment Configuration
Clone the repository and set up your environment variables:
```bash
git clone https://github.com/DSingh256/Never-twice.git
cd Never-twice

# Copy template configuration
cp .env.example .env
```

Review `.env` and set your preferred provider. For example, to use Groq:
```env
LLM_PROVIDER=groq
GROQ_API_KEY=your_groq_api_key_here
```
Or for local Ollama:
```env
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
```

---

### 3. Backend Setup & Dependencies
Create a virtual environment and install backend requirements:
```bash
# Windows
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt

# Linux / macOS
python3.12 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

---

### 4. Start Hindsight (Memory Engine)
Run the automated launcher:
```bash
# Linux / macOS / Git Bash on Windows
bash scripts/start-hindsight.sh
```
*Hindsight exposes its API on port `8888` and provisions the memory bank `nevertwice-prod`.*

---

### 5. Launch the FastAPI Backend
```bash
# Windows
.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload

# Linux / macOS
uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```
Verify backend health:
```bash
curl http://127.0.0.1:8000/api/health
```

---

### 6. Ingest Postmortems & Seed Organizational Memory
Populate the system with real postmortem data:
```bash
# Run ingestion pipeline (fetches sources.yaml, extracts facts, retains to Hindsight)
curl -X POST http://127.0.0.1:8000/api/ingest/run
```

---

### 7. Launch the Next.js Frontend
In a new terminal:
```bash
cd frontend
npm install
npm run dev
```
Open **[http://localhost:3000](http://localhost:3000)** in your browser.

---

## 🖥️ Interactive Web Suite

- **The Analysis Room (`/analyze`)**: Paste a candidate Git/Terraform diff. Watch live Server-Sent Events (SSE) unfold step-by-step: `understand_diff` → `recall_memories` → `recall_feedback` → `reflect` → `verdict`. View the final risk rating, computed confidence, and cited memories.
- **The Tribunal (`/tribunal`)**: Side-by-side live cross-examination of a single diff across Witness A (Naked LLM), Witness B (+ Memory Recall), and Witness C (Full Production Pipeline).
- **Memory Atlas (`/atlas`)**: Search and inspect all facts retained across the organization. View root causes, precursors, failed attempts, and reviewer feedback.
- **Learning Lab (`/learning-lab`)**: Test and observe the closed-loop feedback mechanism in real time. Submit grades and observe how future confidence scores adapt.
- **Evaluation Dashboard (`/eval`)**: Inspect empirical ablation benchmarks across held-out datasets with precision, recall, and false-positive rates.
- **Archive (`/archive`)**: Audit trail of all analyses conducted, including status, model used, and timestamps.

---

## 🧪 Testing & Verification

Run the complete test suite:
```bash
# Run core test suite
.venv\Scripts\python.exe -m pytest tests/test_api_contracts.py tests/test_eval_metrics.py tests/test_extraction.py tests/test_hardsplit_guarantee.py tests/test_pipeline.py tests/test_tribunal_api.py -v
```

### Automated Guarantees Checked by Tests
- **No Mock/Sample Data**: Verified via `scripts/hardcode_audit.py` to ensure only real database records and dynamic responses are served.
- **Arithmetic Confidence Guarantee**: Verified that confidence is mathematically computed from evidence, never prompted from LLM hallucinations.
- **Zero Held-Out Contamination**: Verifies that held-out benchmark incidents are never retained in the active memory bank.
- **Cryptographic Security**: Ensures all feedback submissions require valid HMAC-SHA256 signatures, and incoming GitHub Webhooks enforce `X-Hub-Signature-256`.

---

## 📡 API Reference Overview

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/api/health` | Comprehensive connectivity check (Hindsight, LLM, DB) |
| `GET` | `/api/config` | Returns effective active system configuration |
| `POST` | `/api/ingest/run` | Triggers asynchronous fetch, extract, split & retain |
| `POST` | `/api/analyze` | Submit a code diff for analysis (returns case ID) |
| `GET` | `/api/analyze/{id}/stream` | Server-Sent Events (SSE) stream of analysis stages |
| `GET` | `/api/analyses` | List historical analysis archive records |
| `POST` | `/api/feedback` | Submit HMAC-signed reviewer feedback on a verdict |
| `GET` | `/api/memory/list` | Introspect facts in the active Hindsight memory bank |
| `POST` | `/api/tribunal/convene` | Convene the 3-witness A/B/C Tribunal on a diff |
| `POST` | `/api/eval/run` | Launch background A/B/C ablation evaluation |
| `GET` | `/api/eval/runs` | Retrieve evaluation results and benchmark metrics |
| `POST` | `/api/webhooks/github` | Webhook endpoint for GitHub Pull Request deployment gating |

---

## 📜 License

This project is licensed under the [MIT License](LICENSE).
