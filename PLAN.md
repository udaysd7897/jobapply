# Build Plan

Refined build order for the harness. Each phase depends only on the phase
before it, and produces an artifact that can be inspected without the next
phase existing yet.

## Phase 0 — Architecture & data contracts
Decide the framework (simple function chain vs. something like LangGraph) and
lock the JSON schemas that pass between agents: `job_context.json` (JD +
metadata), tailored resume output, `field_map.json` (portal field -> answer),
`run_summary.json`.

**Test**: write one hand-crafted example of each JSON file and confirm they
contain everything the next agent will need — no code yet, just schema
review.

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
to exist before a vendor call gets hardwired somewhere.

**Test**: same prompt through the chosen free model and through Claude,
confirm identical call signature and both return usable text.

## Phase 4 — Autofill research
4a: survey open-source Playwright job-autofill repos.
4b: instrument/inspect the Simplify extension (DOM + network) to learn its
field-detection heuristics and where it fails.

**Test**: a short written findings doc with a concrete list of
field-detection heuristics and known failure cases — testable as "does this
doc let someone else start Phase 4c without re-researching," not just a
summary.

## Phase 4c — Autofill agent, single ATS first
Pick one ATS (Workday or Greenhouse) and build field-mapping: static fields
from the demographic JSON, job-specific fields via semantic search + reframe.
Run in **dry-run mode** — fill fields, stop before final submit.

**Test**: run against 2-3 real postings on that ATS, manually verify every
filled field, confirm it stops before submit every time.

## Phase 5 — Chain the agents
Wire JD-fetch -> resume-customize -> autofill with per-job state written to
disk (e.g. `runs/<job_id>/state.json`), stateless across jobs.

**Test**: run one real job link end-to-end in dry-run mode; confirm
`state.json` accumulates correctly at each stage and nothing carries over
into a second job's run.

## Phase 6 — Human escalation
Wire the escalation channel — pick the simplest thing that works for dev
(even a local notification/log) before committing to WhatsApp.

**Test**: force a hard error and force a low-confidence answer separately,
confirm each produces an escalation message with enough context (link,
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
