import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from jobapply.schemas import ApplyResult, ResultCode, RunSummary

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
ESCALATION_LOG_PATH = REPO_ROOT / "runs" / "escalations.jsonl"

# Per REQUIREMENT.md Resolved Product Decisions #4: captcha/login_issue/
# failed escalate; applied/expired don't.
ESCALATING_RESULT_CODES = {ResultCode.CAPTCHA, ResultCode.LOGIN_ISSUE, ResultCode.FAILED}


def _notify(title: str, message: str) -> None:
    """macOS desktop notification. Best-effort -- the JSONL log below is
    the actual source of truth, so a notification failure (non-macOS,
    osascript missing, notifications disabled) is silently ignored."""
    script = f"display notification {json.dumps(message)} with title {json.dumps(title)}"
    try:
        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=5)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass


def _log(entry: dict) -> None:
    ESCALATION_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(ESCALATION_LOG_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")


def escalate(job_id: str, job_url: str, company: str, title: str, reason: str, detail: str | None = None) -> None:
    """Fire a human escalation: desktop notification + persistent JSONL
    log. See PLAN.md Phase 6."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "job_id": job_id,
        "job_url": job_url,
        "company": company,
        "title": title,
        "reason": reason,
        "detail": detail,
    }
    _log(entry)
    message = f"{company} — {title}\n{reason}" + (f": {detail}" if detail else "")
    _notify("Job application needs you", message[:250])


def should_escalate(result: ApplyResult) -> bool:
    return result.result_code in ESCALATING_RESULT_CODES


def escalate_apply_result(job_id: str, job_url: str, company: str, title: str, result: ApplyResult) -> None:
    if not should_escalate(result):
        return
    escalate(job_id, job_url, company, title, reason=f"apply_result: {result.result_code.value}", detail=result.detail)


def escalate_pipeline_error(job_id: str, job_url: str, company: str, title: str, error: str) -> None:
    escalate(job_id, job_url, company, title, reason="pipeline_error", detail=error)


def send_summary(summary: RunSummary) -> None:
    """One final summary after the full run, through the same channel --
    no per-application updates otherwise (REQUIREMENT.md Resolved Product
    Decisions #6)."""
    counts_line = ", ".join(f"{k}: {v}" for k, v in summary.counts.items())
    _notify("Job application run finished", f"{summary.total_jobs} jobs — {counts_line}"[:250])
    _log({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "type": "run_summary",
        "run_id": summary.run_id,
        "total_jobs": summary.total_jobs,
        "counts": summary.counts,
    })
