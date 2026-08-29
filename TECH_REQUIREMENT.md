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
- `apply_result.json` — output of the autofill agent (Phase 4c): one
  outcome per application (`applied` / `expired` / `captcha` / `login_issue`
  / `failed`), not a per-field confidence score. Revised from an original
  `field_map.json` design (per-field `confidence` driving escalation) after
  adopting the Claude-Code-driven approach below, which reports an
  application-level result rather than a field-by-field map; `captcha`,
  `login_issue`, and `failed` are what trigger human escalation (Phase 6)
  now — see REQUIREMENT.md Resolved Product Decisions #4-5.
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

The subprocess reports one `ApplyResult` per job (`applied` / `expired` /
`captcha` / `login_issue` / `failed:detail`) rather than a per-field
`FieldMap` — see Data Contracts above. `captcha`, `login_issue`, and
`failed` escalate to a human (Phase 6); `applied` and `expired` do not.

**Adapted from ApplyPilot** (`~/ApplyPilot`, `Pickle-Pixel/ApplyPilot`,
AGPL-3.0-only — see the evaluation in this doc's history/PLAN.md for why
its `apply` module as a whole wasn't reused wholesale): its `prompt.py` is
copied into this repo as the starting prompt, adapted to our contracts
(`JobContext`/`TailoredResume`/our profile JSON) instead of ApplyPilot's own
config shapes. Since this is a personal, non-distributed tool the AGPL
provenance of this one file is a non-issue in practice, but worth knowing if
this repo is ever shared. Everything else from ApplyPilot's `apply` module
(threading/`ThreadPoolExecutor` for parallel workers, the SQLite job queue,
`dashboard.py`'s live rendering, per-worker Chrome/CDP-port management in
`chrome.py`) is dropped — v1 processes one job at a time, sequentially, with
state on disk (Phase 5) instead of a job database, and plain print/log
output instead of a dashboard.

**Decisions on two things the copied prompt does that don't match earlier
plans, resolved explicitly rather than silently inherited**:
- **CAPTCHA**: the copied prompt includes ApplyPilot's full CAPTCHA-solving
  section (CapSolver API + a manual fallback where the agent itself solves
  puzzle/audio challenges) — the opposite of PLAN.md Phase 8's original
  "escalate to human, don't auto-solve" decision. Kept as-is for now per
  explicit instruction, to be revisited later; no `CAPSOLVER_API_KEY` is
  configured, so it currently runs the manual-fallback path (attempts the
  puzzle/audio solve itself) before giving up with `RESULT:CAPTCHA`, rather
  than escalating immediately on detection.
- **Per-answer confidence**: dropped. The copied prompt has the agent answer
  screening questions directly and confidently, with no self-reported
  confidence per answer — matches REQUIREMENT.md Resolved Product Decisions
  #4-5 (outcome-level escalation only).

**Gmail MCP server (`@gongrzhe/server-gmail-autoauth-mcp`)**: required, not
optional — most ATS portals require creating a per-company account, and
email OTP verification is common during that flow. Registered alongside the
Playwright MCP server in the same `--mcp-config`. Scoped with an
**allow-list** (`--allowedTools mcp__gmail__search_emails,mcp__gmail__read_email`),
not ApplyPilot's deny-list approach — the Gmail MCP server exposes ~19 tools
including `send_email`, `delete_email`, and label/filter management, and
ApplyPilot's own deny-list leaves `send_email` allowed (arguably an
oversight on their part). An allow-list of exactly the two read-only tools
needed for OTP retrieval is safer on a real personal Gmail account and
doesn't depend on staying in sync with the server's full tool list.

One-time setup (not yet done): create a Google OAuth client, download
`gcp-oauth.keys.json`, place in `~/.gmail-mcp/`, run
`npx @gongrzhe/server-gmail-autoauth-mcp auth` once to complete the browser
consent flow and store `~/.gmail-mcp/credentials.json`. After that, the
Gmail MCP server works globally without re-authenticating per job.

**Persistent browser profile**: `@playwright/mcp` is passed
`--user-data-dir=<repo-local path>` so login sessions/cookies survive across
jobs, instead of ApplyPilot's separate Chrome-process + CDP-port-per-worker
management (which exists to support their parallel workers — not needed
here).

**Critical: `ANTHROPIC_API_KEY` must be stripped from the subprocess env.**
Verified directly against this installed CLI (v2.1.251): if
`ANTHROPIC_API_KEY` is set in the environment, `claude` uses it and bills
API credits instead of the Pro-plan login, silently defeating the entire
point of this design (no developer/API credits available). Confirmed fix:
`env.pop("ANTHROPIC_API_KEY", None)` before spawning — with the key
stripped, `claude -p` authenticates via the stored Pro-plan OAuth login
instead. Implemented in `src/jobapply/agents/apply/agent.py`, which also
strips `CLAUDECODE`/`CLAUDE_CODE_ENTRYPOINT` so the subprocess doesn't think
it's nested inside another Claude Code session.

**Caveats to build around**:
- Pro-plan usage (5-hour rolling window + weekly cap) is shared with all
  other Claude Code usage on the account, including normal development —
  worth watching if application volume scales up.
- Playwright MCP has no built-in dry-run/no-submit mode; the Phase 4c
  dry-run boundary ("fill fields, stop before submit") is enforced purely by
  prompt instruction, which is weaker than a hard-coded stop. Needs
  verification before trusting it unsupervised.

**Module layout** (`src/jobapply/agents/apply/`):
- `profile.py` — loads `config/profile.json` (real data, gitignored; template
  at `config/profile.example.json`, shape matches ApplyPilot's profile so
  the adapted `prompt.py` needs no remapping).
- `prompt.py` — adapted from ApplyPilot, see above.
- `mcp_config.py` — builds the Playwright + Gmail MCP server config.
- `agent.py` — `apply_job(job_context, tailored_resume, dry_run) -> ApplyResult`;
  one sequential `subprocess.run` per job, no threading/dashboard/SQLite.

Structurally verified (`build_prompt` runs end-to-end against placeholder
profile data and a real PDF, producing a well-formed ~19K-char prompt); the
full `claude -p` + MCP round trip against a real posting is still Phase 4c's
Test step 1, not yet run.
