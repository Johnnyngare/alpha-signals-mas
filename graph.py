from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from state import GraphState, MAX_RETRIES
from agents.scraper import scraper_node
from agents.analyst import analyst_node
from agents.reporter import reporter_node
from agents.auditor import auditor_node
from agents.broadcaster import broadcaster_node


def audit_router(state: GraphState) -> str:
    print(f"\n[Router] Evaluating routing decision. retry_count={state.retry_count}")

    if state.retry_count >= MAX_RETRIES:
        print(f"[Router] MAX_RETRIES ({MAX_RETRIES}) reached. Forcing END.")
        return "end"

    if state.audit_result and state.audit_result.passed:
        print("[Router] Audit PASSED. Routing to broadcaster.")
        return "broadcast"

    if state.audit_result and state.audit_result.failed_agent:
        target = state.audit_result.failed_agent
        print(f"[Router] Audit FAILED. Re-routing to: {target}")
        return target

    if state.error_message:
        print(f"[Router] Unrecoverable error, no failed_agent identified. Forcing END.")
        return "end"

    print("[Router] WARNING: Unhandled routing state. Defaulting to END.")
    return "end"


def build_graph() -> object:
    builder = StateGraph(GraphState)

    builder.add_node("scraper",     scraper_node)
    builder.add_node("analyst",     analyst_node)
    builder.add_node("reporter",    reporter_node)
    builder.add_node("auditor",     auditor_node)
    builder.add_node("broadcaster", broadcaster_node)

    builder.set_entry_point("scraper")

    builder.add_edge("scraper",     "analyst")
    builder.add_edge("analyst",     "reporter")
    builder.add_edge("reporter",    "auditor")
    builder.add_edge("broadcaster", END)

    builder.add_conditional_edges(
        "auditor",
        audit_router,
        {
            "broadcast": "broadcaster",
            "end":       END,
            "scraper":   "scraper",
            "analyst":   "analyst",
            "reporter":  "reporter",
        }
    )

    checkpointer = MemorySaver()

    compiled = builder.compile(
        interrupt_before=["broadcaster"],
        checkpointer=checkpointer,
    )

    print("[Graph] StateGraph compiled successfully.")
    print("[Graph] Topology: scraper -> analyst -> reporter -> auditor -> (conditional) -> [INTERRUPT] -> broadcaster -> END")
    return compiled, checkpointer


graph, checkpointer = build_graph()