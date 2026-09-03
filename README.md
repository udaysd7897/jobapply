# jobapply

Personal-use agent harness that takes a list of job posting links and runs
them through: fetch the JD → tailor the resume → autofill/apply → escalate
to a human when something needs attention → summarize the run. Scope is AI
Engineer / ML Engineer roles in India across Workday, Greenhouse, and other
ATSs. Not distributed.

See `CLAUDE.md` for architecture, `REQUIREMENT.md` for product scope and
resolved decisions, `PLAN.md` for build phases, `TECH_REQUIREMENT.md` for
technical decisions/gotchas, and `ISSUE.md` for known open bugs.

## Setup

```
uv sync
uv run playwright install chromium
```

Requires a `.env` with `GROQ_API_KEY` set, and `config/profile.json` /
`config/base_resume.html` (real personal data, gitignored — see
`config/profile.example.json` for the shape).

## Usage

```
uv run jobapply-fetch-jd <job_url>          # Phase 1 only: fetch a JD, write job_context.json
uv run jobapply-run <job_url> [job_url...]  # full pipeline: fetch, tailor, apply, escalate, summarize
```

`jobapply-run` drives a real browser and can submit real applications —
run it directly in your own terminal, not from within a Claude Code session.
