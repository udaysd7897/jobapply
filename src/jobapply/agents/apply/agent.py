import json
import os
import re
import subprocess
from pathlib import Path

from jobapply.agents.apply.mcp_config import build_mcp_config
from jobapply.agents.apply.prompt import RUNS_DIR, build_prompt
from jobapply.schemas import ApplyResult, JobContext, ResultCode, TailoredResume

# Shared across jobs (not per-job) so login sessions/cookies persist.
BROWSER_PROFILE_DIR = RUNS_DIR / "_browser_profile"

MODEL = "sonnet"
TIMEOUT_SECONDS = 900

RESULT_LINE = re.compile(r"RESULT:([A-Z_]+)(?::(.+))?")

_CODE_MAP = {
    "APPLIED": ResultCode.APPLIED,
    "EXPIRED": ResultCode.EXPIRED,
    "CAPTCHA": ResultCode.CAPTCHA,
    "LOGIN_ISSUE": ResultCode.LOGIN_ISSUE,
    "FAILED": ResultCode.FAILED,
}


def _parse_result(text: str) -> tuple[ResultCode, str | None]:
    match = RESULT_LINE.search(text)
    if not match:
        return ResultCode.FAILED, f"no RESULT line in output: {text[-500:]!r}"
    code = _CODE_MAP.get(match.group(1), ResultCode.FAILED)
    return code, match.group(2)


def apply_job(job_context: JobContext, tailored_resume: TailoredResume, dry_run: bool = True) -> ApplyResult:
    """PLAN.md Phase 4c: drive the browser via a headless Claude Code
    session (Pro-plan usage, not API billing) with Playwright + Gmail MCP
    servers attached. Returns one outcome per job -- see
    TECH_REQUIREMENT.md: Autofill/Apply Agent."""
    prompt = build_prompt(job_context, tailored_resume, dry_run=dry_run)

    BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    mcp_config_path = RUNS_DIR / job_context.job_id / "mcp-config.json"
    mcp_config_path.parent.mkdir(parents=True, exist_ok=True)
    mcp_config_path.write_text(json.dumps(build_mcp_config(BROWSER_PROFILE_DIR)))

    cmd = [
        "claude",
        "--model", MODEL,
        "-p",
        "--mcp-config", str(mcp_config_path),
        "--permission-mode", "bypassPermissions",
        "--no-session-persistence",
        "--allowedTools", "mcp__gmail__search_emails,mcp__gmail__read_email",
        "--output-format", "json",
    ]

    # Must strip ANTHROPIC_API_KEY: if set, it takes precedence over the
    # Pro-plan claude.ai login and this call would bill API credits instead
    # of Pro-plan usage (verified against this installed CLI -- see
    # TECH_REQUIREMENT.md). CLAUDECODE/CLAUDE_CODE_ENTRYPOINT are stripped
    # so the subprocess doesn't think it's nested inside another session.
    env = os.environ.copy()
    for key in ("ANTHROPIC_API_KEY", "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT"):
        env.pop(key, None)

    try:
        proc = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            env=env,
            timeout=TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return ApplyResult(job_id=job_context.job_id, portal=job_context.portal, result_code=ResultCode.FAILED, detail="apply agent timed out")

    if proc.returncode != 0:
        return ApplyResult(job_id=job_context.job_id, portal=job_context.portal, result_code=ResultCode.FAILED, detail=f"claude exited {proc.returncode}: {proc.stderr[-500:]}")

    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return ApplyResult(job_id=job_context.job_id, portal=job_context.portal, result_code=ResultCode.FAILED, detail=f"non-JSON output: {proc.stdout[-500:]!r}")

    if data.get("is_error"):
        return ApplyResult(job_id=job_context.job_id, portal=job_context.portal, result_code=ResultCode.FAILED, detail=f"agent error: {data.get('result', '')[:500]}")

    code, detail = _parse_result(data.get("result", ""))
    return ApplyResult(job_id=job_context.job_id, portal=job_context.portal, result_code=code, detail=detail)
