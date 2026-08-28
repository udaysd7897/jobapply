import json
import re

from playwright.sync_api import sync_playwright

from jobapply.llm import LLM
from jobapply.schemas import JobContext, Portal, RoleType

EXTRACTION_SYSTEM_PROMPT = """\
You extract structured metadata from the raw text of a job posting page.
Given the page text, respond with ONLY a JSON object (no markdown fences,
no commentary) with exactly these keys:

- "company": the hiring company's name
- "title": the job title as posted
- "role_type": either "ai_engineer" or "ml_engineer" — classify based on
  the posting's focus. If the role is ambiguous or fits neither cleanly,
  default to "ai_engineer".
"""


def _extract_metadata(llm: LLM, page_text: str) -> dict:
    raw = llm.complete(page_text[:12000], system=EXTRACTION_SYSTEM_PROMPT)
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        raise ValueError(f"LLM did not return JSON metadata: {raw!r}")
    return json.loads(match.group(0))


def _detect_portal(job_url: str) -> Portal:
    if "myworkdayjobs.com" in job_url or "workday.com" in job_url:
        return Portal.WORKDAY
    if "greenhouse.io" in job_url:
        return Portal.GREENHOUSE
    return Portal.OTHER


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60]


def fetch_job_context(job_url: str, llm: LLM | None = None) -> JobContext:
    """PLAN.md Phase 1: open a job posting and extract its JD into a
    JobContext, the input to resume customization (Phase 2)."""
    llm = llm or LLM()

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.goto(job_url, wait_until="domcontentloaded")
        page.wait_for_timeout(2000)
        page_text = page.inner_text("body")
        browser.close()

    metadata = _extract_metadata(llm, page_text)
    company = metadata["company"]
    title = metadata["title"]

    return JobContext(
        job_id=_slug(f"{company}-{title}") or _slug(job_url),
        job_url=job_url,
        portal=_detect_portal(job_url),
        company=company,
        title=title,
        jd_text=page_text.strip(),
        role_type=RoleType(metadata["role_type"]),
    )
