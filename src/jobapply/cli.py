import sys
from pathlib import Path

from jobapply.agents.jd_fetch.agent import fetch_job_context

RUNS_DIR = Path(__file__).resolve().parent.parent.parent / "runs"


def fetch_jd(job_url: str) -> Path | None:
    # Deliberately calls fetch_job_context() directly, not the graph --
    # this command is Phase 1 only. Going through build_graph() would also
    # run tailor_resume/apply/escalate, turning a "just fetch a JD" test
    # into a live apply attempt.
    try:
        context = fetch_job_context(job_url)
    except Exception as exc:
        print(f"error: fetch_jd failed: {exc}", file=sys.stderr)
        return None

    out_dir = RUNS_DIR / context.job_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "job_context.json"
    out_path.write_text(context.model_dump_json(indent=2))

    print(f"company:   {context.company}")
    print(f"title:     {context.title}")
    print(f"portal:    {context.portal.value}")
    print(f"role_type: {context.role_type.value}")
    print(f"jd_text:   {len(context.jd_text)} chars")
    print(f"saved to:  {out_path}")
    return out_path


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: jobapply-fetch-jd <job_url>", file=sys.stderr)
        raise SystemExit(1)
    fetch_jd(sys.argv[1])
