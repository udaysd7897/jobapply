# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

An agent harness that reads a list of job posting links and runs them through
a pipeline: fetch the JD → tailor the resume → autofill/apply. Personal-use
tool, not distributed. Scope is currently AI Engineer / ML Engineer roles in
India (Workday, Greenhouse, and other ATSs).

**Read these before making product or architecture decisions** — they are
the source of truth, not a historical record:
- `REQUIREMENT.md` — product scope and the "Resolved Product Decisions"
  section (job source, role scope, escalation model, reporting).
- `PLAN.md` — build order by phase, each with a concrete test. Check which
  phase a change belongs to before restructuring something.
- `TECH_REQUIREMENT.md` — technical decisions and *why*, including several
  gotchas discovered the hard way (see below).
- `ISSUE.md` — known open bugs.

## Commands

```
uv sync                                    # install/sync dependencies
uv run jobapply-fetch-jd <job_url>         # Phase 1: fetch a JD, write job_context.json to runs/<job_id>/
uv run playwright install chromium         # one-time browser binary install (needed after a fresh uv sync)
```

There is no test suite or linter configured. The established pattern for
verifying a change (used throughout this repo's history) is a one-off
structural check via `uv run python -c "..."`: construct the relevant
pydantic model(s) by hand, call the function, assert on the output. See
recent git history for examples. Validate any new/changed JSON contract
against its pydantic model and its example in `docs/examples/`.

Running the apply agent for real (`apply_job`) spawns a live `claude`
subprocess that drives a real browser against a real job posting — treat it
as a live action with real-world consequences (it can submit real
applications), not a normal test. It also tends to get blocked by Claude
Code's own auto-mode safety classifier when invoked *from within* a Claude
Code session; running it directly in the user's own terminal avoids that.

## Architecture

### Two separate LLM backends — do not mix them up
- **Phases 1-2** (JD-fetch classification, resume tailoring): pure text
  generation through `src/jobapply/llm.py`'s `LLM` class, a thin wrapper
  around Groq's OpenAI-compatible API (`GROQ_API_KEY` env var). Swappable to
  another OpenAI-compatible provider by changing this one class only.
- **Phase 4c** (autofill/apply): NOT the LLM class above. It shells out to
  the `claude` CLI itself in headless mode (`src/jobapply/agents/apply/agent.py`),
  because it needs an agent that can actually drive a browser via MCP tools,
  and because it runs on the user's Claude Code Pro-plan usage rather than
  metered API billing (no API credits available for this project).
  **Critical**: `ANTHROPIC_API_KEY` must be stripped from that subprocess's
  env (`agent.py` does this) — if left set, `claude` authenticates with it
  instead of the Pro-plan login and silently bills API credits, defeating
  the entire point. This was verified directly against the installed CLI,
  not theoretical.

### Pipeline orchestration
`src/jobapply/graph.py` is a LangGraph `StateGraph` over `PipelineState`
(pydantic). One node per pipeline stage, linear edges, no cycles — chosen
deliberately over a plain function chain (see TECH_REQUIREMENT.md
"Framework" for why). Only `fetch_jd` is wired in so far; resume
customization (Phase 2) and the apply agent (Phase 4c) exist as standalone
modules but are not yet added as graph nodes.

### Data contracts
`src/jobapply/schemas.py` defines the pydantic models that cross stage
boundaries: `JobContext` (Phase 1 output), `TailoredResume` (Phase 2
output, not yet built), `ApplyResult` (Phase 4c output — one outcome per
application: `applied`/`expired`/`captcha`/`login_issue`/`failed`, **not**
a per-field confidence map — that design was tried and abandoned, see
REQUIREMENT.md Resolved Product Decisions #4-5), `RunSummary` (Phase 7,
not yet built). Each has a hand-written example in `docs/examples/` that
must validate against its model — that's the whole point of the example,
so keep them in sync when a schema changes.

### The apply agent (`src/jobapply/agents/apply/`)
- `profile.py` loads `config/profile.json` (real personal data, gitignored)
  against the shape in `config/profile.example.json`. No pydantic
  validation on this one — it's a raw dict.
- `prompt.py` builds the instruction prompt handed to the spawned `claude`
  session. **Adapted from a third-party AGPL-3.0 project (ApplyPilot)** —
  see the file's own docstring and TECH_REQUIREMENT.md for what was kept,
  what was rewritten, and the license implication (fine for personal use,
  worth reconsidering before ever distributing this repo). Its original
  CAPTCHA-solving section (CapSolver API + a self-solving puzzle fallback)
  is commented out, not deleted, after live testing found it structurally
  blind to standard reCAPTCHA and prone to auto-solving anyway with no API
  key configured — see ISSUE.md. The active `_build_captcha_section()` is
  a simple bounded-retry policy: try twice, then escalate.
- `mcp_config.py` builds the MCP server config passed to that session:
  Playwright (with a persistent `--user-data-dir` so login cookies survive
  across jobs) and Gmail (`@gongrzhe/server-gmail-autoauth-mcp`, for OTP
  retrieval during per-employer account signup — deliberately scoped with
  an **allow-list** of exactly `search_emails`/`read_email`, not a
  deny-list, since the server exposes ~19 tools including `send_email`).
  Gmail auth is a one-time `npx @gongrzhe/server-gmail-autoauth-mcp auth`
  flow storing credentials in `~/.gmail-mcp/`; while the Google Cloud OAuth
  app stays in "Testing" publishing status, that token expires every 7
  days and needs redoing.
- `agent.py`'s `apply_job()` runs one `claude -p --output-format
  stream-json` subprocess per job (sequential, no threading/dashboard/DB —
  that ApplyPilot machinery was deliberately dropped). Every event of the
  session is streamed to `runs/<job_id>/session_log.jsonl`, and
  `extract_filled_fields()` pulls a clean field→value audit list out of
  that log into `runs/<job_id>/filled_fields.json` — added after
  discovering fabricated values (a hallucinated postal code, salary, and
  start date, all corresponding to placeholder profile values) that were
  otherwise invisible without grepping the raw transcript. When adding new
  form-interaction tool types, extend `FORM_FILL_TOOLS` /
  `extract_filled_fields()` so they still show up in that audit file.
- The dry-run boundary ("fill the form, stop before clicking Submit") is
  enforced **only by prompt instruction** — Playwright MCP has no
  technical dry-run lock. Treat this as unreliable until proven otherwise
  for a given change; do not assume it holds.

### Runtime artifacts (`runs/`, gitignored)
Per job, under `runs/<job_id>/`: `upload/` (resume copy for the browser to
attach), `mcp-config.json`, `session_log.jsonl` (full apply-agent
transcript), `filled_fields.json` (extracted audit). `runs/_browser_profile/`
is the shared (not per-job) persistent Playwright profile.

### Personal data
`config/profile.json` is the real demographic/compensation JSON the apply
prompt reads (REQUIREMENT.md's "structured JSON" requirement); never
committed. `config/profile.example.json` is the template/schema reference —
keep it in sync when `profile.json`'s shape changes. `ResumeAI.pdf` at the
repo root is the real base resume; also gitignored (`*.pdf`).
