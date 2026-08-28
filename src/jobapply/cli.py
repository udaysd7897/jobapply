import sys
from pathlib import Path

from jobapply.graph import build_graph

RUNS_DIR = Path(__file__).resolve().parent.parent.parent / "runs"


def fetch_jd(job_url: str) -> Path | None:
    graph = build_graph()
    result = graph.invoke({"job_url": job_url})

    if result.get("error"):
        print(f"error: {result['error']}", file=sys.stderr)
        return None

    context = result["job_context"]
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
