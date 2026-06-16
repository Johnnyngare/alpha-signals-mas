import sys
from graph import graph, checkpointer
from state import GraphState, AnalysisMode


THREAD_CONFIG = {"configurable": {"thread_id": "mas_main_thread"}}


def _print_pre_broadcast_summary(state: GraphState) -> None:
    print("\n" + "=" * 65)
    print("  HUMAN-IN-THE-LOOP GATE")
    print("=" * 65)
    print(f"  Run ID          : {state.run_id}")
    print(f"  Mode            : {state.analysis_mode.value}")
    print(f"  Records ingested: {len(state.raw_data)}")
    print(f"  Retry count     : {state.retry_count}")
    print(f"  Audit passed    : {state.audit_result.passed if state.audit_result else 'N/A'}")

    if state.analysis:
        print(f"  Anomalies found : {state.analysis.anomalies_detected}")
        print(f"  Arb opps        : {len(state.analysis.arb_opportunities)}")
        print(f"  Kelly bets      : {len(state.analysis.kelly_suggestions)}")
        print(f"  Confidence      : {state.analysis.confidence_score:.2%}")

    print(f"  Error message   : {state.error_message}")
    print("=" * 65)
    print("\n  The pipeline has completed analysis and is ready to broadcast.")
    print("  Review the summary above before releasing the PDF to Telegram.\n")


def _print_pipeline_complete(state: GraphState) -> None:
    print("\n" + "=" * 65)
    print("  PIPELINE COMPLETE")
    print("=" * 65)
    print(f"  Run ID          : {state.run_id}")
    print(f"  Records ingested: {len(state.raw_data)}")
    print(f"  Retry count     : {state.retry_count}")
    print(f"  Audit passed    : {state.audit_result.passed if state.audit_result else 'N/A'}")
    print(f"  Error message   : {state.error_message}")
    print(f"  Broadcast result: {state.broadcast_result}")

    if state.audit_failures:
        print(f"\n  Accumulated audit failures:")
        for f in state.audit_failures:
            print(f"    - {f}")


def run_pipeline(
    run_id: str = "production_run_001",
    analysis_mode: AnalysisMode = AnalysisMode.VALUE_SHEET,
    auto_approve: bool = False,
) -> GraphState:

    print("\n" + "=" * 65)
    print(f"  MULTI-AGENT SYSTEM -- Starting pipeline: {run_id}")
    print("=" * 65)

    initial_state = GraphState(run_id=run_id, analysis_mode=analysis_mode)
    final_state_dict: dict = {}

    # Phase 1: stream until interrupt before broadcaster
    # The checkpointer saves state at the interrupt point under THREAD_CONFIG
    for state_update in graph.stream(
        initial_state.model_dump(),
        config=THREAD_CONFIG,
        stream_mode="values"
    ):
        final_state_dict = state_update

    interrupted_state = GraphState(**final_state_dict)

    if not interrupted_state.audit_result or not interrupted_state.audit_result.passed:
        print("\n[Run] Pipeline terminated before broadcast gate (audit failed or circuit breaker).")
        _print_pipeline_complete(interrupted_state)
        return interrupted_state

    # Phase 2: human gate
    _print_pre_broadcast_summary(interrupted_state)

    if auto_approve:
        approved = True
        print("[Gate] Auto-approval enabled. Proceeding with broadcast.")
    else:
        while True:
            try:
                response = input("  >> Approve broadcast to Telegram? [Y/N]: ").strip().upper()
                if response in ("Y", "YES"):
                    approved = True
                    break
                elif response in ("N", "NO"):
                    approved = False
                    break
                else:
                    print("  Invalid input. Please enter Y or N.")
            except KeyboardInterrupt:
                print("\n\n[Gate] Keyboard interrupt received. Aborting broadcast.")
                approved = False
                break

    if not approved:
        print("\n[Gate] Broadcast REJECTED by operator. PDF will not be sent to Telegram.")
        _print_pipeline_complete(interrupted_state)
        return interrupted_state

    print("\n[Gate] Broadcast APPROVED. Resuming graph execution -> broadcaster node.")

    # Phase 3: resume from checkpointed state
    # Passing None as input tells LangGraph to resume from where it paused
    # The checkpointer retrieves the frozen state via THREAD_CONFIG thread_id
    final_dict = graph.invoke(None, config=THREAD_CONFIG)
    final_state = GraphState(**final_dict)

    _print_pipeline_complete(final_state)
    return final_state


if __name__ == "__main__":
    mode = AnalysisMode.VALUE_SHEET

    if "--arb" in sys.argv:
        mode = AnalysisMode.ARB_ALERT_DIGEST
        print("[Config] Mode override: ARB_ALERT_DIGEST")

    auto = "--auto" in sys.argv

    run_pipeline(
        run_id="production_run_001",
        analysis_mode=mode,
        auto_approve=auto,
    )