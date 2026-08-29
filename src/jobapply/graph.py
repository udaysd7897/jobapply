from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from jobapply.agents.jd_fetch import fetch_job_context
from jobapply.schemas import JobContext


class PipelineState(BaseModel):
    """Shared state threaded through the pipeline graph. Grows a field per
    stage as PLAN.md phases are built (tailored_resume after Phase 2,
    apply_result after Phase 4c)."""

    job_url: str
    job_context: JobContext | None = None
    error: str | None = None


def fetch_jd_node(state: PipelineState) -> dict:
    try:
        return {"job_context": fetch_job_context(state.job_url)}
    except Exception as exc:
        return {"error": f"fetch_jd failed: {exc}"}


def build_graph():
    graph = StateGraph(PipelineState)
    graph.add_node("fetch_jd", fetch_jd_node)
    graph.add_edge(START, "fetch_jd")
    graph.add_edge("fetch_jd", END)
    return graph.compile()
