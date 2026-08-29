# Build Plan

Refined build order for the harness. Each phase depends only on the phase
before it, and produces an artifact that can be inspected without the next
phase existing yet.

## Phase 0 — Architecture & data contracts ✅ Complete
Decide the framework (simple function chain vs. something like LangGraph) and
lock the JSON schemas that pass between agents: `job_context.json` (JD +
metadata), tailored resume output, `field_map.json` (portal field -> answer),
`run_summary.json`. (`field_map.json` was the original plan here — it was
later replaced by `apply_result.json` during Phase 4c; see that section and
TECH_REQUIREMENT.md for why. Current contracts are whatever
`src/jobapply/schemas.py` defines, not this list.)

**Test**: write one hand-crafted example of each JSON file and confirm they
contain everything the next agent will need — no code yet, just schema
review.

**Delivered**: framework decision (LangGraph) recorded in
TECH_REQUIREMENT.md; all four contracts defined as pydantic models in
`src/jobapply/schemas.py`; hand-crafted examples in `docs/examples/`, each
validated against its model.

## Phase 1 — JD-fetch agent
Moved ahead of resume customization since it's resume customization's input.
Given one job link, open it and produce `job_context.json` (title, company,
raw JD text, role classification AI/ML).

**Test**: run against 8-10 real links across Workday/Greenhouse/other, inspect
each output JSON by hand for correct title/company/JD/role-classification.

## Phase 2 — Resume customization agent
Input: a `job_context.json` (from Phase 1, or a hand-written one for isolated
testing). Output: tailored resume file + a plain-text diff of what changed.

**Test**: run against 5 curated JDs (2 clearly AI, 2 clearly ML, 1 ambiguous)
and manually check: correct bullet targeted (Harmony vs. Fanatics), added
line is truthful/implied, <=2 non-duplicate keywords added, file still opens
correctly. This phase never needs a browser — testable purely on files.

## Phase 3 — LLM provider abstraction
Pick a free/open-source LLM, but wrap it behind one interface
(`llm.complete(prompt) -> str`) so Phases 1-2 never call the vendor SDK
directly. Can be built in parallel with Phase 1/2 — not blocking, just needs
to exist before a vendor call gets hardwired somewhere. Applies to Phases
1-2 only (pure text generation) — Phase 4c does not go through this
interface; see below.

**Test**: same prompt through the chosen free model and through Claude,
confirm identical call signature and both return usable text.

## Phase 4 — Autofill research
4a: survey open-source Playwright job-autofill repos (see ApplyPilot,
AIHawk, job-seek — TECH_REQUIREMENT.md). 4b: instrument/inspect the Simplify
extension (DOM + network) to learn its field-detection heuristics and where
it fails. Now scoped as informing what context/known quirks to feed the
agent in 4c (e.g. Workday tenant patterns), not as a spec for hand-written
DOM selectors — see the Phase 4c approach change below.

**Test**: a short written findings doc with a concrete list of
field-detection heuristics and known failure cases — testable as "does this
doc let someone else start Phase 4c without re-researching," not just a
summary.

## Phase 4c — Autofill agent, single ATS first
Revised approach (see TECH_REQUIREMENT.md: Autofill/Apply Agent): instead of
hand-written Playwright selectors per ATS, drive the browser via the Claude
Code CLI in headless mode (`claude -p ... --output-format stream-json`), spawned as
a subprocess per job with a Playwright MCP server (browser) and a Gmail MCP
server (OTP retrieval during account-creation flows) attached — using Claude
Code Pro-plan usage, not API billing. The subprocess is given `JobContext` +
`TailoredResume` + the demographic JSON + the job-specific answer bank, and
returns one `ApplyResult` per job (`applied` / `expired` / `captcha` /
`login_issue` / `failed:detail`) — an outcome-level result, not a per-field
confidence map (REQUIREMENT.md Resolved Product Decisions #4-5). `captcha`,
`login_issue`, and `failed` escalate to Phase 6; `applied`/`expired` don't.

The prompt itself is adapted from ApplyPilot's `prompt.py` (copied in,
remapped to our contracts). Its CAPTCHA-solving section was kept as-is
initially, then revisited after the first dry run per plan and commented
out (root cause not confirmed), replaced with a simple bounded-retry
policy (try twice, then escalate) that restores Phase 8's original intent
— see TECH_REQUIREMENT.md and ISSUE.md. Not yet tested against a real
CAPTCHA.

Pick one ATS (Workday or Greenhouse) first. Run in **dry-run mode** — fill
fields, stop before final submit. Note: Playwright MCP has no built-in
dry-run lock, so this boundary is enforced purely by prompt instruction and
must be verified, not assumed.

**Test, step 1 (isolated)**: before wiring into the graph, run one raw
`claude -p` + Playwright MCP invocation by hand against a real posting on
the chosen ATS. Confirm: (a) it returns a clean `ApplyResult`, (b) it stops
before clicking submit, (c) OTP retrieval via Gmail MCP works if an account
signup flow triggers one.

Status: run several times against real postings (DXC/Workday, SuccessFactors,
ApplyToJob, BambooHR, Cognizant, Capital One/Workday) — see
TECH_REQUIREMENT.md for what each returned. (a) confirmed every time.
(b) confirmed on two logged runs, including one that reached the actual
final Review page (Capital One) rather than stopping earlier; not yet
confirmed reliable across every run. (c) confirmed working — the Capital
One run created a Workday account, retrieved the verification email via
`gmail:read_email`, and completed activation via the link inside it.

**Test, step 2 (wired in)**: run against 2-3 real postings on that ATS as a
graph node, manually verify the result and any filled fields, confirm it
stops before submit every time. Not started — `apply_job` is not yet added
as a graph node (see `graph.py`, only `fetch_jd` is wired up).

## Phase 5 — Chain the agents
Wire JD-fetch -> resume-customize -> autofill with per-job state written to
disk (e.g. `runs/<job_id>/state.json`), stateless across jobs.

**Test**: run one real job link end-to-end in dry-run mode; confirm
`state.json` accumulates correctly at each stage and nothing carries over
into a second job's run.

## Phase 6 — Human escalation
Wire the escalation channel — pick the simplest thing that works for dev
(even a local notification/log) before committing to WhatsApp.

**Test**: force a hard pipeline error and force each escalating `ApplyResult`
outcome (`captcha`, `login_issue`, `failed`) separately, confirm each
produces an escalation message with enough context (link,
error, current state) to act on.

## Phase 7 — Full run + summary
Turn dry-run off (or leave it on until confident) and run the whole test
list end-to-end.

**Test**: run 5 curated links, confirm each lands in applied/escalated/
errored, and one final summary is produced with correct counts, sent through
the escalation channel.

## Phase 8 — CAPTCHA, deferred and reconsidered
Solving CAPTCHAs to get past anti-bot protection is the part most likely to
cross an ATS's Terms of Service, and also the least reliable piece to
automate. Treat "CAPTCHA encountered" as an escalation trigger in v1 (solved
manually when pinged) rather than building a solver — Phase 6 already gives
an escalation path for free.

**Test (only if pursued later)**: hit a known CAPTCHA-gated page, confirm it
escalates with a screenshot + link rather than hanging.

## Changes from the original ordering
- JD-fetch moved from step 6 to step 1, since resume customization can't be
  tested against real JDs without it.
- CAPTCHA solving moved to a deferred/reconsider slot rather than a build
  target, for the ToS/reliability reason above.
