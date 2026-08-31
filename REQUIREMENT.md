# Project Guide

An Agent Harness for Job Applications on Job Portals

## Requirements

1. Input: An Excel sheet containing job links.
2. The architecture should be as simple as possible.

## Approach

1. Use a chain of agents.
2. An agent opens the job posting and gets the JD into the harness's memory.
3. An agent customises the resume based on the JD.
4. An agent applies for the job.
5. The agent should have preconfigured patterns for Workday and Greenhouse.
6. Whenever the agent gets stuck or encounters an error, escalate to a human.

## Requirements: Resume Customisation Tool

1. The resume format should be professional and easily editable/interactable by an LLM agent. Does Overleaf have an API, or should we use a `.doc`/`.docx` format?
2. The agent should have room to add just one line to the experience section and add up to two skills to improve the ATS score.
3. For AI roles, add a line to the Harmony experience. For ML roles, add a line to the Fanatics Software Engineer 2 experience.
4. The new line should be implied by existing experience. It should not add anything completely unrelated, such as reframing the experience as fine-tuning if I have no experience with it.
5. It should identify at most two critical missing keywords and add them to the Skills section. If a keyword is already implied by the resume, do not add it.

## Requirements: Job Application Tool

1. Use Playwright to interact with the web.
2. Demographic information will be available in structured JSON. Some semantic or similarity search may be required to map the information to the fields extracted from the portal.
3. For job-specific questions (e.g., "Tell me about your experience with LLMs"), the agent should perform a semantic search to retrieve relevant answers and reframe them according to the JD.
4. If the retrieved answer has low confidence, involve a human in the loop via WhatsApp or another suitable channel.
5. Study aSimplify Job Application Chrome extension to thoroughly understand how it works. AFAIK, it does not work on some sites.

## Resolved Product Decisions (v1 scope)

1. **Job source**: a manually provided list of job links (per the Excel input above). Sourcing jobs automatically from HiringCafe is future scope, not v1.
2. **Role scope**: this pipeline is specific to "AI Engineer" and "Machine Learning Engineer" roles only. If a posting's role is ambiguous (e.g., "AI/ML Engineer", "Applied Scientist"), default to classifying it as an AI Engineer role.
3. **Human oversight**: the pipeline runs fully autonomously at runtime, with no per-application review step. During development, the pipeline will be monitored manually end-to-end.
4. **Escalation triggers**: revised — the apply agent (PLAN.md Phase 4c) reports an outcome-level result per application (applied / expired / captcha / login_issue / failed:reason), not a per-field confidence score. Escalation is driven by that outcome (captcha, login_issue, and failed cases escalate; applied and expired do not), rather than by low confidence on any individual answer. The exact channel (WhatsApp or otherwise) is a technical decision, not fixed by this requirement.
5. **Free-text answers**: generated using the semantic search + JD-reframing approach above. The agent answers screening questions directly and confidently rather than self-reporting per-answer confidence — the original "escalate on low-confidence answer" mechanic (§20.4) is dropped in favor of the outcome-level escalation in #4. Human escalation itself is still required; only the granularity of the trigger changed.
6. **Reporting**: after the full input list has been processed, send one final summary to the human through the same escalation channel. No per-application status updates.
7. **Resume format (resolves §19.1)**: HTML as the source-of-truth format (`config/base_resume.html`), not Overleaf/LaTeX or `.docx`. Rendered to PDF via headless Chromium's native print-to-PDF (Playwright's `page.set_content()` + `page.pdf()`, already a dependency). HTML is simple for an LLM/code to edit precisely (target a specific element), and Playwright already gives us headless Chrome for free.
8. **Missing-keyword cap (revises §19.5)**: exactly one missing keyword added, not "up to two" — reasoned as only one new skill area can plausibly be picked up/credible at a time. See TECH_REQUIREMENT.md: Resume Tailoring.
