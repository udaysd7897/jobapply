import json
import os
import re
import subprocess
import threading
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


FORM_FILL_TOOLS = {
    "mcp__playwright__browser_fill_form",
    "mcp__playwright__browser_type",
    "mcp__playwright__browser_select_option",
    "mcp__playwright__browser_file_upload",
}


def extract_filled_fields(session_log_path: Path) -> list[dict]:
    """Pull every field value the agent actually entered out of a session
    log, as a flat audit list -- added after discovering fabricated values
    (postal code, salary, start date -- all "FILL_IN" in profile.json)
    buried in raw tool-call JSON that would otherwise require manually
    grepping the full transcript to notice."""
    events: list[dict] = []
    for line in session_log_path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if msg.get("type") != "assistant":
            continue
        for block in msg.get("message", {}).get("content", []):
            if block.get("type") != "tool_use" or block.get("name") not in FORM_FILL_TOOLS:
                continue
            name = block["name"]
            inp = block.get("input", {})
            if name == "mcp__playwright__browser_fill_form":
                for f in inp.get("fields", []):
                    events.append({"field": f.get("name"), "value": f.get("value"), "via": "fill_form"})
            elif name == "mcp__playwright__browser_type":
                events.append({"field": inp.get("element"), "value": inp.get("text"), "via": "type"})
            elif name == "mcp__playwright__browser_select_option":
                events.append({"field": inp.get("element"), "value": inp.get("values"), "via": "select_option"})
            elif name == "mcp__playwright__browser_file_upload":
                events.append({"field": "file_upload", "value": inp.get("paths"), "via": "file_upload"})
    return events


def _print_event(msg: dict) -> None:
    """Live progress to the terminal. The full raw event still goes to the
    session log regardless -- this is just a readable subset."""
    if msg.get("type") != "assistant":
        return
    for block in msg.get("message", {}).get("content", []):
        if block.get("type") == "text":
            print("[TEXT]", block["text"][:300])
        elif block.get("type") == "tool_use":
            name = block.get("name", "").replace("mcp__playwright__", "").replace("mcp__gmail__", "gmail:")
            print(f"[TOOL] {name} {json.dumps(block.get('input', {}))[:200]}")


def apply_job(job_context: JobContext, tailored_resume: TailoredResume, dry_run: bool = True) -> ApplyResult:
    """PLAN.md Phase 4c: drive the browser via a headless Claude Code
    session (Pro-plan usage, not API billing) with Playwright + Gmail MCP
    servers attached. Returns one outcome per job -- see
    TECH_REQUIREMENT.md: Autofill/Apply Agent.

    Every event of the session (assistant text, every tool call and its
    result, the final result) is streamed to session_log.jsonl -- added
    after a live test where we had no way to diagnose why the agent missed
    a CAPTCHA, since --output-format json only gives a single final blob.
    """
    prompt = build_prompt(job_context, tailored_resume, dry_run=dry_run)

    BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    job_dir = RUNS_DIR / job_context.job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    mcp_config_path = job_dir / "mcp-config.json"
    mcp_config_path.write_text(json.dumps(build_mcp_config(BROWSER_PROFILE_DIR)))
    session_log_path = job_dir / "session_log.jsonl"

    cmd = [
        "claude",
        "--model", MODEL,
        "-p",
        "--mcp-config", str(mcp_config_path),
        "--permission-mode", "bypassPermissions",
        "--no-session-persistence",
        "--allowedTools", "mcp__gmail__search_emails,mcp__gmail__read_email",
        "--output-format", "stream-json",
        "--verbose",
    ]

    # Must strip ANTHROPIC_API_KEY: if set, it takes precedence over the
    # Pro-plan claude.ai login and this call would bill API credits instead
    # of Pro-plan usage (verified against this installed CLI -- see
    # TECH_REQUIREMENT.md). CLAUDECODE/CLAUDE_CODE_ENTRYPOINT are stripped
    # so the subprocess doesn't think it's nested inside another session.
    env = os.environ.copy()
    for key in ("ANTHROPIC_API_KEY", "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT"):
        env.pop(key, None)

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
    )
    proc.stdin.write(prompt)
    proc.stdin.close()

    timed_out = threading.Event()
    timer = threading.Timer(TIMEOUT_SECONDS, lambda: (timed_out.set(), proc.kill()))
    timer.start()

    final_result: dict | None = None
    try:
        with open(session_log_path, "w") as log_file:
            for line in proc.stdout:
                log_file.write(line)
                log_file.flush()
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    msg = json.loads(stripped)
                except json.JSONDecodeError:
                    continue
                _print_event(msg)
                if msg.get("type") == "result":
                    final_result = msg
    finally:
        proc.wait()
        timer.cancel()

    filled_fields_path = job_dir / "filled_fields.json"
    filled_fields_path.write_text(json.dumps(extract_filled_fields(session_log_path), indent=2))

    if timed_out.is_set():
        return ApplyResult(job_id=job_context.job_id, portal=job_context.portal, result_code=ResultCode.FAILED, detail=f"apply agent timed out after {TIMEOUT_SECONDS}s -- see {session_log_path}")

    if final_result is None:
        return ApplyResult(job_id=job_context.job_id, portal=job_context.portal, result_code=ResultCode.FAILED, detail=f"no result event in session -- see {session_log_path}")

    if final_result.get("is_error"):
        return ApplyResult(job_id=job_context.job_id, portal=job_context.portal, result_code=ResultCode.FAILED, detail=f"agent error: {final_result.get('result', '')[:500]}")

    code, detail = _parse_result(final_result.get("result", ""))
    return ApplyResult(job_id=job_context.job_id, portal=job_context.portal, result_code=code, detail=detail)
