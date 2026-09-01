import sys
from datetime import datetime, timezone

from jobapply.escalate import send_summary
from jobapply.graph import build_graph
from jobapply.schemas import JobResult, RunSummary


def _job_status(result_state: dict) -> tuple[str, str | None]:
    if result_state.get("error"):
        return "errored", result_state["error"]

    apply_result = result_state.get("apply_result")
    if apply_result is None:
        return "errored", "pipeline did not reach the apply stage"

    code = apply_result.result_code.value
    if code == "applied":
        return "applied", None
    if code == "expired":
        return "skipped", None
    detail = f" ({apply_result.detail})" if apply_result.detail else ""
    return "escalated", f"apply_result: {code}{detail}"


def run_all(job_urls: list[str], dry_run: bool = True) -> RunSummary:
    """PLAN.md Phase 7: run the whole input list end-to-end, one final
    summary sent through the escalation channel afterward -- no
    per-application updates (REQUIREMENT.md Resolved Product Decisions #6)."""
    run_id = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
    started_at = datetime.now(timezone.utc).isoformat()
    graph = build_graph()

    job_results: list[JobResult] = []
    for job_url in job_urls:
        result_state = graph.invoke({"job_url": job_url, "dry_run": dry_run})
        job_context = result_state.get("job_context")
        status, reason = _job_status(result_state)
        job_results.append(JobResult(
            job_id=job_context.job_id if job_context else job_url,
            company=job_context.company if job_context else "unknown",
            title=job_context.title if job_context else "unknown",
            status=status,
            reason=reason,
        ))

    counts: dict[str, int] = {}
    for jr in job_results:
        counts[jr.status] = counts.get(jr.status, 0) + 1

    summary = RunSummary(
        run_id=run_id,
        started_at=started_at,
        finished_at=datetime.now(timezone.utc).isoformat(),
        total_jobs=len(job_urls),
        counts=counts,
        jobs=job_results,
    )
    send_summary(summary)
    return summary


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: jobapply-run <job_url> [job_url ...]", file=sys.stderr)
        raise SystemExit(1)
    summary = run_all(sys.argv[1:])
    print(summary.model_dump_json(indent=2))
