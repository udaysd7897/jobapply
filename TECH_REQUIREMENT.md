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
`job_context`, and later `tailored_resume` / `apply_result`, accumulate as
stages complete; `error` set by any node that fails). Each PLAN.md phase
adds one node plus an edge — `fetch_jd` (Phase 1) is wired up; resume
customization (Phase 2) and autofill (Phase 4c) will follow the same
pattern. Escalation (Phase 6) will read `state.error` / `ApplyResult.result_code`
(`captcha`/`login_issue`/`failed`) rather than needing conditional graph
edges, keeping the graph itself linear.

## Data Contracts (PLAN.md Phase 0)

Four JSON contracts pass between stages, defined as pydantic models in
`src/jobapply/schemas.py` and illustrated with hand-crafted examples in
`docs/examples/`:

- `job_context.json` — output of the JD-fetch agent (Phase 1); input to
  resume customization (Phase 2) and autofill (Phase 4c).
- `tailored_resume.json` — output of resume customization (Phase 2, not yet
  built). **Open**: `resume_file`'s format depends on the still-unresolved
  REQUIREMENT.md §19.1 question (Overleaf API vs. `.docx`) — the schema has
  no default (`resume_file: str`, plain required field); `docs/examples/`
  uses `.docx` only as an illustrative value. At runtime, `prompt.py`'s
  `build_prompt` always derives a `.pdf` path via
  `Path(resume_file).with_suffix(".pdf")` regardless of `resume_file`'s
  actual extension, since the apply agent uploads a PDF — live tests so
  far have passed a real `.pdf` (`ResumeAI.pdf`) directly, bypassing this
  open question rather than resolving it.
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

## JD-Fetch Agent (PLAN.md Phase 1)

**Gotcha found via live testing**: `fetch_job_context` originally waited
`domcontentloaded` + a fixed 2-second sleep before reading `page.inner_text
("body")`. Confirmed live against a real Workday posting (Qualcomm) that
this is unreliable — the page body was still completely empty (0 chars) at
2 seconds, a client-rendered SPA that only finished populating around 6
seconds in. Worked fine on Greenhouse/Rippling by luck (faster-rendering
pages), silently produced empty `company`/`title`/`jd_text` and a
meaningless default `role_type` on Workday. Fixed by waiting for
`networkidle` instead of a fixed sleep, plus a hard failure if the
extracted text is still under 200 chars afterward (fail loudly instead of
feeding the LLM near-nothing and getting garbage back).

## Resume Tailoring (PLAN.md Phase 2)

**Format decision (resolves REQUIREMENT.md §19.1)**: `config/base_resume.html`
is the source of truth — real personal data, gitignored, alongside
`config/profile.json`. Not Overleaf/LaTeX, not `.docx`. Rationale: HTML has
addressable elements a plain code edit can target precisely (a specific
bullet list, a specific skills container), and Playwright already gives us
headless Chromium for free — no new format-specific library needed.

**Rendering**: HTML -> PDF via Playwright's headless Chromium, the same
mechanism `~/ApplyPilot`'s `src/applypilot/scoring/pdf.py` uses:
`page.set_content(html, wait_until="networkidle")` then
`page.pdf(path=..., format="Letter", print_background=True)`. This is a
two-line usage of Playwright's own public API, not a substantial adaptation
of ApplyPilot's code (their `pdf.py` also parses a plain-text resume format
into HTML via a template — we skip that entirely since the base resume is
already hand-authored HTML), so no AGPL-provenance note is needed here the
way there is for `prompt.py`.

**Decide vs. edit, kept as two separate steps**: the LLM (Groq, via the
Phase 3 `llm.complete()` interface) only ever decides *what* to change —
it returns (a) one new bullet to add (or null) and (b) one missing skill
keyword to add (or null), as small JSON. A separate, plain-code step then
performs the actual HTML edit and renders to PDF. The LLM is deliberately
never asked to output or rewrite the whole HTML file — that would risk it
exceeding the one-bullet/one-keyword constraint REQUIREMENT.md sets, with
no structural guarantee stopping it.

**New bullet is appended, not a rewrite of an existing one — this went
through two design iterations, both live-tested**:
1. First design: reframe an *existing* bullet in place (quote one back
   verbatim, replace it with a reworded version) — motivated by wanting to
   avoid unbounded resume growth. Bullet count never changed, which was
   good, but live-tested against two real JDs (Emergent, Rippling) it
   converged on rewording the *same* generic bullet both times, producing
   near-identical output regardless of what was actually distinctive about
   each JD.
2. Reverted to appending one new bullet (closer to REQUIREMENT.md's
   original wording), but pointed the LLM specifically at the JD's most
   *distinctive* unmet requirement rather than any generic implied line —
   given the candidate's real experience anywhere in the resume (not just
   the target entry's own bullets), and explicitly told not to restate
   something the target entry's existing bullets already cover well.
   Re-tested against the same two real JDs: Emergent (a reliability-framed
   role) got a bullet about 24/7 production support and SLA-driven
   debugging; Rippling (an HR/IT/Finance compliance-heavy product) got a
   bullet about IAM policies and audit-logging — genuinely different,
   each grounded in real resume content. `ExperienceEdit` (`schemas.py`)
   is `{target, added_line}` again, not `{target, original_bullet,
   reframed_line}`.

**Missing-keyword cap revised to exactly one** (REQUIREMENT.md Resolved
Product Decisions #8), down from the original "up to two" (§19.5) — only
one new skill area can plausibly be picked up/credible at a time.

**`TailoredResume.resume_file` now means the rendered PDF**, not the HTML
source — that's the file Phase 4c's apply agent actually uploads. The HTML
is an intermediate artifact (exact storage location under `runs/<job_id>/`
not yet decided).

**Built and live-tested** (`src/jobapply/agents/resume.py`). Real
`config/base_resume.html` in place with `id="harmony-bullets"`,
`id="fanatics-swe2-bullets"`, and `id="skills-section"` anchors (the
skills section has categorized sub-groups, e.g. "LLM Systems", "Retrieval,
Speech & ML" — not a flat list, so the missing-keyword decision also
names a category). Verified end-to-end against a live Groq call for both
role types, and visually confirmed the rendered PDF looks correct.

**Two bugs found via live testing, both fixed**:
- The skill-category match required the LLM's proposed category string to
  exactly equal an existing `.skill-label`'s text. The LLM instead
  paraphrased ("Speech & ML" for the real "Retrieval, Speech & ML"),
  which silently fell through to "no match" and created a near-duplicate
  category instead of appending to the real one. Fixed with substring
  matching (`_resolve_category`) against the actual extracted category
  list in either direction, rather than requiring an exact quote.
- Even after that fix, the match still failed: `_extract_skill_categories`
  HTML-*unescapes* labels for readability (`&amp;` -> `&`), but the
  resolved category was then searched for directly in the still-escaped
  raw HTML, so `&` never matched `&amp;`. Fixed by re-escaping the matched
  category (`html.escape(matched_category)`) before building the search
  regex.
- The LLM proposed a "missing" keyword that was already a literal,
  exact-match skill chip in the resume (`LangGraph`) despite an explicit
  prompt instruction not to, and despite the exact text being present in
  what it was given — a genuine model-reliability miss, not a
  missing-context problem (confirmed: the text was there). Rewording the
  prompt further wasn't trusted to fix this reliably, so a deterministic
  check was added instead: before inserting, verify the proposed keyword
  doesn't already appear (case-insensitive) anywhere in the resume text,
  and silently drop it if it does. Don't rely on LLM self-restraint alone
  for a fact that's mechanically checkable.

**Fourth issue found (real Qualcomm/Workday JD, genuinely ambiguous "AI /
ML Engineer" title)**: the new bullet drew on a skill ("Fine Tuning") that
was real, but then invented specifics with zero basis anywhere in the
resume -- "quantization techniques" and "sub-second inference latency on
CPU-only nodes" (confirmed: neither term, nor "CPU" or "latency", appears
anywhere in the resume text). A more clear-cut fabrication than the
earlier borderline calls (an unevidenced "React" addition, a speculative
"24/7 production support" claim). Also separately confirmed a
chronology bug on the same JD: on a run where it targeted Fanatics SWE2
(Aug 2021-Dec 2023), the new bullet attributed LangGraph/EKS/Terraform --
all only evidenced in the *later* Harmony role (Feb 2024-present) -- which
is impossible; the candidate didn't have those tools yet at the Fanatics
job. Fixed the chronology bug with an explicit prompt rule (only draw
supporting evidence from roles at or before the target's own dates). The
fabrication issue is not yet fixed -- prompt wording alone has now failed
to hold three times (this, and the two duplicate-keyword misses above);
options being weighed: a stricter "every specific technique/metric must
be traceable to an exact resume phrase" rule, a second-pass LLM
verification call against the resume text, or always surfacing the diff
for human review before use (Phase 2 currently has no review step).

Not yet run against the full 5-JD curated set (2 AI, 2 ML, 1 ambiguous)
PLAN.md's Phase 2 test calls for — only a handful of real JDs tested so far.

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

**Gotchas hit setting this up for real**: `llm.py` didn't actually call
`load_dotenv()`, so a `GROQ_API_KEY` in `.env` was silently never read —
fixed by adding it there. Separately, Groq's hosted model catalog rotates:
the originally-hardcoded default (`llama-3.3-70b-versatile`) no longer
exists (`404 model_not_found`) by the time this was actually tested.
Current default is `openai/gpt-oss-120b` (confirmed live against
`client.models.list()` on 2026-09-01) — if a similar error shows up again,
re-check the live model list rather than assuming the hardcoded default
still exists.

**Revision**: this `llm.complete()` interface applies to Phases 1-2 only
(pure text generation: JD classification, resume tailoring). Phase 4c
(autofill/apply) does not go through it — see below.

## Autofill/Apply Agent (PLAN.md Phase 4c)

**Decision**: drive the browser via the Claude Code CLI in headless/print
mode (`claude -p ... --output-format stream-json`), spawned as a subprocess
per job, with a Playwright MCP server configured for the invocation. Not the
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
- **CAPTCHA — revised (2026-08-30)**: the copied ApplyPilot CAPTCHA section
  (CapSolver API + a manual fallback where the agent tries to solve
  puzzle/audio challenges itself) is now **disabled** — commented out in
  `prompt.py`, not deleted, in case any of it is worth reviving later.
  Detection itself was not the problem (live testing showed the agent
  successfully clicking a reCAPTCHA checkbox); the actual issue is that
  with no `CAPSOLVER_API_KEY` configured, the section's manual fallback
  has the agent try to solve puzzle/audio challenges itself — exactly the
  ToS-risk/self-solving behavior PLAN.md Phase 8 originally wanted to
  avoid. Replaced with a much simpler policy: try to interact with any
  detected verification widget at most twice; if still unresolved, output
  `RESULT:CAPTCHA` and stop. No external solving API, no puzzle-solving —
  this restores Phase 8's original "escalate, don't auto-solve" intent.
  Not yet tested against a real CAPTCHA.
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

One-time setup (done — completed 2026-08-29): create a Google OAuth client,
download `gcp-oauth.keys.json`, place in `~/.gmail-mcp/`, run
`npx @gongrzhe/server-gmail-autoauth-mcp auth` once to complete the browser
consent flow and store `~/.gmail-mcp/credentials.json`. After that, the
Gmail MCP server works globally without re-authenticating per job.

**Caveat**: the Google Cloud OAuth app is in "Testing" publishing status
(not verified), so per Google's policy the resulting refresh token expires
7 days after the consent flow — after that, Gmail MCP calls will start
failing until the `npx ... auth` flow above is redone. Publishing to
"Production" would avoid this, but the scope this server requests
(`gmail.modify`) is a Restricted scope requiring Google's CASA security
review to verify — not practical for a personal single-user tool, so
redoing this flow roughly weekly is the accepted tradeoff for now.

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
- Pro-plan usage limits (exact mechanism not verified in this repo — general
  Claude subscription plans have rolling-window and/or weekly caps, but the
  precise numbers aren't confirmed here) are shared with all other Claude
  Code usage on the account, including normal development —
  worth watching if application volume scales up.
- Playwright MCP has no built-in dry-run/no-submit mode; the Phase 4c
  dry-run boundary ("fill fields, stop before submit") is enforced purely by
  prompt instruction, which is weaker than a hard-coded stop. Needs
  verification before trusting it unsupervised.

**Module layout** (`src/jobapply/agents/apply/`):
- `profile.py` — loads `config/profile.json` (real data, gitignored; template
  at `config/profile.example.json`). Started out matching ApplyPilot's
  profile shape closely; has since diverged as real fields were filled in
  (`date_of_birth`, a restructured `compensation` block with real CTC
  figures, `notice_period_days`) and unused ApplyPilot concepts were
  dropped (`location_preferences`) — check `profile.example.json` directly
  for the current shape rather than assuming it still mirrors ApplyPilot.
- `prompt.py` — adapted from ApplyPilot, see above.
- `mcp_config.py` — builds the Playwright + Gmail MCP server config.
- `agent.py` — `apply_job(job_context, tailored_resume, dry_run) -> ApplyResult`;
  one sequential `subprocess.Popen` per job, no threading/dashboard/SQLite.
  Streams the full session to `runs/<job_id>/session_log.jsonl` (added
  after a live test where the single-final-result `subprocess.run` version
  gave no way to diagnose an unexpected CAPTCHA outcome) and extracts a
  field→value audit list via `extract_filled_fields()` into
  `runs/<job_id>/filled_fields.json` — see CLAUDE.md for why that was added.

Live-tested against real postings (not just structurally): a Workday
posting (DXC) failed twice on the employer's own resume-upload endpoint
returning persistent HTTP 500s, unrelated to this code; two other-ATS
postings (SuccessFactors, ApplyToJob) each returned a clean `applied`
`ApplyResult`; a BambooHR posting was run twice with full session
logging, and the second run correctly stopped before clicking Submit per
the dry-run instruction (logged verbatim: "this is a dry run"); a
Cognizant posting correctly returned `login_issue` after the site's
email-sign-in-link never arrived (~9 minutes of patient retries via
`gmail:search_emails`, then gave up rather than trying the disallowed SSO
option); a Capital One/Workday posting completed a full account
creation + email verification (`gmail:read_email` found the activation
link, `browser_navigate` completed it) + multi-page form fill, corrected
resume-parser field misalignment by re-reading the actual PDF, and
correctly stopped at the real final Review page rather than an earlier
step. Gmail OTP/verification retrieval is confirmed working end-to-end.

**Gotcha found via the Cognizant/Capital One runs: the spawned session was
reading this repo's own `CLAUDE.md`.** Claude Code auto-discovers `CLAUDE.md`
by walking up from the subprocess's working directory. Since `apply_job()`
didn't set `cwd` explicitly, the spawned session inherited this repo as its
cwd, loaded this very file as project context, read its own warning about
"the apply agent" being a risky live action, and refused to proceed —
quoting `CLAUDE.md` back and recommending the user run it from their own
terminal (which is exactly what was already happening). Fixed by spawning
the subprocess with `cwd` set to a fresh `tempfile.mkdtemp()` directory
outside the repo — none of the paths passed to it (mcp-config, resume PDF,
prompt text) are cwd-relative, so this has no functional side effect.
`--bare` was considered and rejected: it also disables OAuth/keychain auth,
which would break the whole point of this design (Pro-plan login, not API
billing). `--safe-mode` disables `CLAUDE.md` too but its docs are ambiguous
about whether it also disables explicitly-passed `--mcp-config` servers —
not worth the risk of silently losing Playwright/Gmail tools to find out.
