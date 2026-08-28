# Technical Requirements

Technical/implementation decisions for the harness, as opposed to product
scope (see REQUIREMENT.md) and build sequencing (see PLAN.md).

## Framework (PLAN.md Phase 0)

**Decision**: LangGraph. Revised from an initial plain-function-chain
recommendation — the user wants hands-on LangGraph experience, and the
pipeline stays simple as a graph too (one node per stage, linear edges,
no cycles for v1), so the added dependency is a reasonable tradeoff for the
learning goal.

Structure (`src/jobapply/graph.py`): a `StateGraph` over a single pydantic
`PipelineState` that threads through every stage (`job_url` in;
`job_context`, and later `tailored_resume` / `field_map`, accumulate as
stages complete; `error` set by any node that fails). Each PLAN.md phase
adds one node plus an edge — `fetch_jd` (Phase 1) is wired up; resume
customization (Phase 2) and autofill (Phase 4c) will follow the same
pattern. Escalation (Phase 6) will read `state.error` / low-confidence
fields rather than needing conditional graph edges, keeping the graph itself
linear.

## Data Contracts (PLAN.md Phase 0)

Four JSON contracts pass between stages, defined as pydantic models in
`src/jobapply/schemas.py` and illustrated with hand-crafted examples in
`docs/examples/`:

- `job_context.json` — output of the JD-fetch agent (Phase 1); input to
  resume customization (Phase 2) and autofill (Phase 4c).
- `tailored_resume.json` — output of resume customization (Phase 2).
  **Open**: `resume_file`'s format depends on the still-unresolved
  REQUIREMENT.md §19.1 question (Overleaf API vs. `.docx`); currently
  defaulted to `.docx` as a placeholder.
- `field_map.json` — output of the autofill agent's field-mapping step
  (Phase 4c). Each field carries a `confidence`; low confidence is the
  signal that triggers human escalation (Phase 6).
- `run_summary.json` — sent to the escalation channel after a full run
  completes (Phase 7).

All four validate against their pydantic models — see
`src/jobapply/schemas.py`.

## LLM Provider

Relates to PLAN.md Phase 3 (LLM provider abstraction). All agent calls go
through one interface (`llm.complete(prompt) -> str`) so the underlying
provider can change without touching agent code.

**Requirement**: use a free/open-source-hosted LLM for v1 development, with
the ability to switch to Claude later without code changes elsewhere.

**Options considered** (all OpenAI-compatible, so interchangeable behind the
same interface):

1. **Groq** (recommended starting point) — genuinely free tier, hosts
   open-weight models (Llama, Qwen, Gemma, DeepSeek-distilled variants), fast
   inference, supports tool/function calling. Free tier limits (rate-limited
   per minute/day) are generous enough for personal job-application volume.
   Use for Phase 1-2 build and testing.
2. **DeepSeek API** — not free, but very low cost per token. OpenAI-compatible.
   Stronger reasoning/writing quality (V3/R1 family) than typical free-tier
   hosted models. Fallback if Groq's hosted model quality isn't sufficient
   for resume-writing specifically.
3. **OpenRouter** — aggregator in front of 20+ free models behind one API
   key. Useful for quickly A/B-testing which free model writes the best
   resume content before committing to one for Phase 2.
4. **Ollama (local)** — zero API cost or rate limits, runs open-weight models
   on local hardware. No external dependency during dev, but needs adequate
   local hardware and tool-calling support varies by model/version.

**Decision**: start with Groq for Phase 1-2 development. Fall back to
DeepSeek if resume-writing quality is insufficient. Treat Claude as the
eventual production upgrade, swapped in via the same interface with no
changes to agent logic.

**Revision**: this `llm.complete()` interface applies to Phases 1-2 only
(pure text generation: JD classification, resume tailoring). Phase 4c
(autofill/apply) does not go through it — see below.

## Autofill/Apply Agent (PLAN.md Phase 4c)

**Decision**: drive the browser via the Claude Code CLI in headless/print
mode (`claude -p ... --output-format json`), spawned as a subprocess per
job, with a Playwright MCP server configured for the invocation. Not the
Anthropic API — the CLI authenticates against the user's Claude Code Pro
subscription, so this consumes Pro-plan usage rather than metered API
billing (no developer/API credits available).

Rationale: this is the one stage that needs an actual agent reasoning about
a live page (field detection by label, matching to the demographic JSON,
answering job-specific questions) rather than fixed selectors per ATS —
letting an LLM drive the browser directly avoids hand-writing and
maintaining brittle per-ATS DOM automation. Confirmed available on this
machine: `claude` CLI (v2.1.251), `node` (v24.15.0), `npx`.

The subprocess is required to return output shaped into the existing
`FieldMap` contract (`field_id`, `label`, `value`, `source`, `confidence`)
via `--output-format json` — nothing downstream (confidence-based escalation,
`run_summary.json`) changes because of this.

**Caveats to build around**:
- Pro-plan usage (5-hour rolling window + weekly cap) is shared with all
  other Claude Code usage on the account, including normal development —
  worth watching if application volume scales up.
- Playwright MCP has no built-in dry-run/no-submit mode; the Phase 4c
  dry-run boundary ("fill fields, stop before submit") is enforced purely by
  prompt instruction, which is weaker than a hard-coded stop. Needs
  verification before trusting it unsupervised.
- Confidence-per-field does not come for free — the prompt must explicitly
  require the agent to self-report a confidence score per answer, or the
  escalation trigger has nothing to read.
