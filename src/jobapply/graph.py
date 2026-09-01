from pathlib import Path

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from jobapply.agents.apply.agent import apply_job
from jobapply.agents.jd_fetch.agent import fetch_job_context
from jobapply.agents.resume.agent import tailor_resume
from jobapply.escalate import escalate_apply_result, escalate_pipeline_error
from jobapply.schemas import ApplyResult, JobContext, TailoredResume

RUNS_DIR = Path(__file__).resolve().parent.parent.parent / "runs"


class PipelineState(BaseModel):
    """Shared state threaded through the pipeline graph. One node per
    stage, linear edges, no cycles -- see TECH_REQUIREMENT.md: Framework.
    Escalation reads state.error / apply_result.result_code rather than
    branching the graph, so the graph stays linear even though not every
    job reaches every stage."""

    job_url: str
    dry_run: bool = True
    job_context: JobContext | None = None
    tailored_resume: TailoredResume | None = None
    apply_result: ApplyResult | None = None
    error: str | None = None


def _persist(state: PipelineState) -> None:
    """Write the accumulated state to runs/<job_id>/state.json after each
    stage (PLAN.md Phase 5). No-op before job_context exists -- there's no
    stable job_id to file under yet, and a fetch_jd failure is still
    captured in escalations.jsonl via the raw job_url."""
    if not state.job_context:
        return
    job_dir = RUNS_DIR / state.job_context.job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "state.json").write_text(state.model_dump_json(indent=2))


def fetch_jd_node(state: PipelineState) -> dict:
    try:
        job_context = fetch_job_context(state.job_url)
    except Exception as exc:
        return {"error": f"fetch_jd failed: {exc}"}
    _persist(state.model_copy(update={"job_context": job_context}))
    return {"job_context": job_context}


def tailor_resume_node(state: PipelineState) -> dict:
    if state.error:
        return {}
    try:
        tailored = tailor_resume(state.job_context)
    except Exception as exc:
        update = {"error": f"tailor_resume failed: {exc}"}
        _persist(state.model_copy(update=update))
        return update
    _persist(state.model_copy(update={"tailored_resume": tailored}))
    return {"tailored_resume": tailored}


def apply_node(state: PipelineState) -> dict:
    if state.error:
        return {}
    try:
        result = apply_job(state.job_context, state.tailored_resume, dry_run=state.dry_run)
    except Exception as exc:
        update = {"error": f"apply_job failed: {exc}"}
        _persist(state.model_copy(update=update))
        return update
    _persist(state.model_copy(update={"apply_result": result}))
    return {"apply_result": result}


def escalate_node(state: PipelineState) -> dict:
    job_context = state.job_context
    job_id = job_context.job_id if job_context else state.job_url
    job_url = job_context.job_url if job_context else state.job_url
    company = job_context.company if job_context else "unknown"
    title = job_context.title if job_context else "unknown"

    if state.error:
        escalate_pipeline_error(job_id, job_url, company, title, state.error)
    elif state.apply_result:
        # escalate_apply_result no-ops internally for applied/expired.
        escalate_apply_result(job_id, job_url, company, title, state.apply_result)
    return {}


def build_graph():
    graph = StateGraph(PipelineState)
    graph.add_node("fetch_jd", fetch_jd_node)
    graph.add_node("tailor_resume", tailor_resume_node)
    graph.add_node("apply", apply_node)
    graph.add_node("escalate", escalate_node)
    graph.add_edge(START, "fetch_jd")
    graph.add_edge("fetch_jd", "tailor_resume")
    graph.add_edge("tailor_resume", "apply")
    graph.add_edge("apply", "escalate")
    graph.add_edge("escalate", END)
    return graph.compile()
