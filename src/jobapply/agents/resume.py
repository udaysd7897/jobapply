import html
import json
import re
from pathlib import Path

from playwright.sync_api import sync_playwright

from jobapply.llm import LLM
from jobapply.schemas import ExperienceEdit, JobContext, RoleType, TailoredResume

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
BASE_RESUME_PATH = REPO_ROOT / "config" / "base_resume.html"
BASE_RESUME_VERSION = "v1"
RUNS_DIR = REPO_ROOT / "runs"

TARGET_BULLETS_ID = {
    RoleType.AI_ENGINEER: "harmony-bullets",
    RoleType.ML_ENGINEER: "fanatics-swe2-bullets",
}
TARGET_FIELD = {
    RoleType.AI_ENGINEER: "harmony",
    RoleType.ML_ENGINEER: "fanatics_swe2",
}
TARGET_LABEL = {
    RoleType.AI_ENGINEER: "Harmony",
    RoleType.ML_ENGINEER: "Fanatics Software Engineer II",
}

ANALYSIS_SYSTEM_PROMPT = """\
You compare a resume against a job description and make two separate,
independent decisions:

1. REFRAME (rewrite in place, never add a new bullet): look at the
   existing bullets listed under TARGET BULLETS below (all belong to
   "{target_label}"). Pick the ONE bullet that already shows adjacent or
   implied experience for something the JD asks for but doesn't state
   explicitly. Rewrite that ONE bullet so the JD-relevant angle is
   explicit. This is a rewrite of a real existing bullet, not a new
   fact -- do not invent tools, metrics, or outcomes not already present
   or clearly implied in that original bullet. If no existing bullet is a
   defensible fit, output null. Quote the chosen bullet's original text
   back VERBATIM from the list below, character for character -- this is
   used to find and replace it, so it must match exactly.

2. MISSING KEYWORD (separate decision): the SINGLE highest-impact JD
   requirement the resume gives no basis for at all -- a real
   tool/technology/term, suitable to add as a bare skill-list keyword. Do
   not propose one if it, or a close synonym, already appears ANYWHERE in
   the resume -- check the Projects and Experience sections too, not just
   the Skills list. Do not propose deeply specialized skills the resume
   shows zero adjacency to. Assign it to the existing skill category it
   best fits
   ({categories}), or propose a short new category name only if truly none
   fit. Output null if nothing is critical enough.

Respond with ONLY a JSON object (no markdown fences, no commentary):
{{
  "reframe": {{"original_bullet": "<verbatim from TARGET BULLETS>", "reframed_line": "..."}} or null,
  "missing": {{"keyword": "...", "category": "..."}} or null
}}
"""


def _strip_html_to_text(raw_html: str) -> str:
    text = re.sub(r"<style[^>]*>.*?</style>", "", raw_html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _extract_skill_categories(raw_html: str) -> list[str]:
    labels = re.findall(r'class="skill-label">([^<]*)<', raw_html)
    return [html.unescape(label) for label in labels]


def _find_bullets_list(raw_html: str, bullets_id: str) -> tuple[int, int]:
    """Return (start, end) offsets of the <ul id=bullets_id>...</ul> body."""
    anchor = re.search(rf'id="{re.escape(bullets_id)}"', raw_html)
    if not anchor:
        raise ValueError(f"no element with id={bullets_id!r} found in base_resume.html")
    close = re.search(r"</ul>", raw_html[anchor.end():])
    if not close:
        raise ValueError(f"no closing </ul> found after id={bullets_id!r}")
    return anchor.end(), anchor.end() + close.start()


def _extract_bullets(raw_html: str, bullets_id: str) -> list[str]:
    start, end = _find_bullets_list(raw_html, bullets_id)
    items = re.findall(r"<li>(.*?)</li>", raw_html[start:end], re.DOTALL)
    return [html.unescape(item).strip() for item in items]


def _analyze(llm: LLM, resume_text: str, jd_text: str, target_label: str, target_bullets: list[str], categories: list[str]) -> dict:
    system = ANALYSIS_SYSTEM_PROMPT.format(target_label=target_label, categories=", ".join(categories))
    bullets_block = "\n".join(f"- {b}" for b in target_bullets)
    prompt = f"TARGET BULLETS ({target_label}):\n{bullets_block}\n\nFULL RESUME:\n{resume_text}\n\nJOB DESCRIPTION:\n{jd_text}"
    raw = llm.complete(prompt, system=system)
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        raise ValueError(f"LLM did not return JSON analysis: {raw!r}")
    return json.loads(match.group(0))


def _replace_bullet(raw_html: str, bullets_id: str, original_bullet: str, reframed_line: str) -> str:
    body_start, body_end = _find_bullets_list(raw_html, bullets_id)
    body = raw_html[body_start:body_end]

    li_pattern = re.compile(r"<li>(.*?)</li>", re.DOTALL)
    wanted = original_bullet.strip()
    target_match = None
    for m in li_pattern.finditer(body):
        if html.unescape(m.group(1)).strip() == wanted:
            target_match = m
            break
    if target_match is None:
        # Fuzzy fallback: the LLM may not have quoted it 100% verbatim.
        for m in li_pattern.finditer(body):
            li_text = html.unescape(m.group(1)).strip()
            if wanted in li_text or li_text in wanted:
                target_match = m
                break
    if target_match is None:
        raise ValueError(f"could not find a bullet matching original_bullet under id={bullets_id!r}: {original_bullet!r}")

    replace_start = body_start + target_match.start(1)
    replace_end = body_start + target_match.end(1)
    return raw_html[:replace_start] + html.escape(reframed_line) + raw_html[replace_end:]


def _resolve_category(category: str, existing_categories: list[str]) -> str | None:
    """Match loosely: the LLM may paraphrase a label (e.g. "Speech & ML" for
    the real "Retrieval, Speech & ML") rather than quote it verbatim."""
    cat_lower = category.lower()
    for existing in existing_categories:
        existing_lower = existing.lower()
        if cat_lower in existing_lower or existing_lower in cat_lower:
            return existing
    return None


def _insert_skill(raw_html: str, keyword: str, category: str, existing_categories: list[str]) -> str:
    section = re.search(r'id="skills-section"', raw_html)
    if not section:
        raise ValueError('no element with id="skills-section" found in base_resume.html')
    section_end = re.search(r"</section>", raw_html[section.end():])
    if not section_end:
        raise ValueError('no closing </section> found after id="skills-section"')
    section_close_at = section.end() + section_end.start()

    body = raw_html[section.end():section_close_at]
    matched_category = _resolve_category(category, existing_categories)
    label_match = None
    if matched_category:
        label_match = re.search(rf'class="skill-label">{re.escape(html.escape(matched_category))}<', body, re.IGNORECASE)

    new_chip = f'<span class="chip">{html.escape(keyword)}</span>'

    if label_match:
        chips_open = re.search(r'class="chips">', body[label_match.end():])
        chips_close = re.search(r"</div>", body[label_match.end() + chips_open.end():])
        insert_at = section.end() + label_match.end() + chips_open.end() + chips_close.start()
        return raw_html[:insert_at] + new_chip + raw_html[insert_at:]

    new_group = (
        f'<div class="skill-group"><div class="skill-label">{html.escape(category)}</div>'
        f'<div class="chips">{new_chip}</div></div>'
    )
    return raw_html[:section_close_at] + new_group + raw_html[section_close_at:]


def _render_pdf(rendered_html: str, output_path: Path) -> None:
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.set_content(rendered_html, wait_until="networkidle")
        page.pdf(path=str(output_path), format="Letter", print_background=True)
        browser.close()


def tailor_resume(job_context: JobContext, llm: LLM | None = None) -> TailoredResume:
    """PLAN.md Phase 2: pick the single highest-impact bullet to reframe
    IN PLACE (never adds a new bullet) and the single highest-impact
    missing skill keyword, edit them into config/base_resume.html, and
    render to PDF. See TECH_REQUIREMENT.md: Resume Tailoring."""
    llm = llm or LLM()

    base_html = BASE_RESUME_PATH.read_text()
    resume_text = _strip_html_to_text(base_html)
    categories = _extract_skill_categories(base_html)
    target_label = TARGET_LABEL.get(job_context.role_type, TARGET_LABEL[RoleType.AI_ENGINEER])
    bullets_id = TARGET_BULLETS_ID.get(job_context.role_type, TARGET_BULLETS_ID[RoleType.AI_ENGINEER])
    target_bullets = _extract_bullets(base_html, bullets_id)

    analysis = _analyze(llm, resume_text, job_context.jd_text, target_label, target_bullets, categories)

    reframe = analysis.get("reframe")
    original_bullet = reframe["original_bullet"] if reframe else None
    reframed_line = reframe["reframed_line"] if reframe else None

    missing = analysis.get("missing")
    keyword = missing["keyword"] if missing else None
    category = missing["category"] if missing else None

    # Deterministic safety net: the LLM has repeatedly proposed keywords
    # that already appear verbatim in the resume text despite an explicit
    # instruction not to (confirmed live -- e.g. proposing "LangGraph" as
    # missing when it's already a literal skill chip). Don't trust the
    # LLM's self-check alone; verify against the actual text.
    if keyword and keyword.lower() in resume_text.lower():
        keyword = None
        category = None

    edited_html = base_html
    if original_bullet and reframed_line:
        edited_html = _replace_bullet(edited_html, bullets_id, original_bullet, reframed_line)
    if keyword:
        edited_html = _insert_skill(edited_html, keyword, category, categories)

    job_dir = RUNS_DIR / job_context.job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    html_path = job_dir / "resume.html"
    html_path.write_text(edited_html)
    pdf_path = job_dir / "resume.pdf"
    _render_pdf(edited_html, pdf_path)

    target_field = TARGET_FIELD.get(job_context.role_type, TARGET_FIELD[RoleType.AI_ENGINEER])
    return TailoredResume(
        job_id=job_context.job_id,
        resume_file=str(pdf_path),
        base_resume_version=BASE_RESUME_VERSION,
        experience_edit=ExperienceEdit(
            target=target_field,
            original_bullet=original_bullet or "(no defensible reframe found)",
            reframed_line=reframed_line or "(no defensible reframe found)",
        ),
        skills_added=[keyword] if keyword else [],
    )
