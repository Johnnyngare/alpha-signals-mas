import sys
import time
from datetime import datetime, timezone

from logging_config import configure_logging
configure_logging()

from database import initialize_database, save_pipeline_run, save_market_anomalies
initialize_database()

import logging
# Import the builder instance and the string path from the graph layer
from graph import builder_instance, checkpoint_db_path
# Import SqliteSaver here to instantiate fresh contexts
from langgraph.checkpoint.sqlite import SqliteSaver
from state import GraphState, AnalysisMode

logger = logging.getLogger(__name__)

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

    pipeline_start = time.time()

    logger.info("Pipeline starting. run_id=%s, mode=%s, auto_approve=%s",
                run_id, analysis_mode.value, auto_approve)

    print("\n" + "=" * 65)
    print(f"  MULTI-AGENT SYSTEM -- Starting pipeline: {run_id}")
    print("=" * 65)

    initial_state = GraphState(run_id=run_id, analysis_mode=analysis_mode)
    final_state_dict: dict = {}

    with SqliteSaver.from_conn_string(checkpoint_db_path) as memory:
        graph = builder_instance.compile(
            interrupt_before=["broadcaster"],
            checkpointer=memory,
        )
        
        try:
            for state_update in graph.stream(
                initial_state.model_dump(),
                config=THREAD_CONFIG,
                stream_mode="values"
            ):
                final_state_dict = state_update

        except Exception as e:
            logger.error(
                "Unhandled exception during graph streaming. run_id=%s error=%s",
                run_id, str(e),
                exc_info=True
            )
            print(f"\n[Pipeline] FATAL ERROR during execution: {e}")
            raise

    interrupted_state = GraphState(**final_state_dict)

    if not interrupted_state.audit_result or not interrupted_state.audit_result.passed:
        logger.warning(
            "Pipeline terminated before broadcast gate. run_id=%s audit_passed=%s",
            run_id,
            interrupted_state.audit_result.passed if interrupted_state.audit_result else False
        )
        print("\n[Run] Pipeline terminated before broadcast gate.")
        _print_pipeline_complete(interrupted_state)

        try:
            execution_secs = round(time.time() - pipeline_start, 2)
            executed_at    = datetime.now(timezone.utc).isoformat()
            save_pipeline_run(
                run_id            = interrupted_state.run_id,
                executed_at       = executed_at,
                fixtures_scanned  = len(set(
                    r.market.split(" -- ")[0] for r in interrupted_state.raw_data
                )) if interrupted_state.raw_data else 0,
                records_ingested  = len(interrupted_state.raw_data),
                markets_analysed  = len(set(r.market for r in interrupted_state.raw_data)),
                anomalies_found   = interrupted_state.analysis.anomalies_detected if interrupted_state.analysis else 0,
                arb_opportunities = len(interrupted_state.analysis.arb_opportunities) if interrupted_state.analysis else 0,
                kelly_suggestions = len(interrupted_state.analysis.kelly_suggestions) if interrupted_state.analysis else 0,
                confidence_score  = interrupted_state.analysis.confidence_score if interrupted_state.analysis else 0.0,
                retry_count       = interrupted_state.retry_count,
                audit_passed      = interrupted_state.audit_result.passed if interrupted_state.audit_result else False,
                broadcast_result  = "not_attempted",
                execution_secs    = execution_secs,
                analysis_mode     = interrupted_state.analysis_mode.value,
            )
        except Exception as e:
            logger.error("Failed to persist terminated run to database. error=%s", str(e), exc_info=True)

        return interrupted_state

    _print_pre_broadcast_summary(interrupted_state)

    if auto_approve:
        approved = True
        logger.info("Auto-approval enabled. Proceeding with broadcast. run_id=%s", run_id)
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
                logger.warning("Broadcast aborted by keyboard interrupt. run_id=%s", run_id)
                approved = False
                break

    if not approved:
        logger.info("Broadcast rejected by operator. run_id=%s", run_id)
        print("\n[Gate] Broadcast REJECTED by operator.")
        _print_pipeline_complete(interrupted_state)

        try:
            execution_secs = round(time.time() - pipeline_start, 2)
            executed_at    = datetime.now(timezone.utc).isoformat()
            save_pipeline_run(
                run_id            = interrupted_state.run_id,
                executed_at       = executed_at,
                fixtures_scanned  = len(set(
                    r.market.split(" -- ")[0] for r in interrupted_state.raw_data
                )) if interrupted_state.raw_data else 0,
                records_ingested  = len(interrupted_state.raw_data),
                markets_analysed  = len(set(r.market for r in interrupted_state.raw_data)),
                anomalies_found   = interrupted_state.analysis.anomalies_detected if interrupted_state.analysis else 0,
                arb_opportunities = len(interrupted_state.analysis.arb_opportunities) if interrupted_state.analysis else 0,
                kelly_suggestions = len(interrupted_state.analysis.kelly_suggestions) if interrupted_state.analysis else 0,
                confidence_score  = interrupted_state.analysis.confidence_score if interrupted_state.analysis else 0.0,
                retry_count       = interrupted_state.retry_count,
                audit_passed      = interrupted_state.audit_result.passed if interrupted_state.audit_result else False,
                broadcast_result  = "rejected_by_operator",
                execution_secs    = execution_secs,
                analysis_mode     = interrupted_state.analysis_mode.value,
            )
        except Exception as e:
            logger.error("Failed to persist rejected run to database. error=%s", str(e), exc_info=True)

        return interrupted_state

    logger.info("Broadcast approved. Resuming graph. run_id=%s", run_id)
    print("\n[Gate] Broadcast APPROVED. Resuming graph execution -> broadcaster node.")

    try:

        with SqliteSaver.from_conn_string(checkpoint_db_path) as memory:
            graph = builder_instance.compile(
                interrupt_before=["broadcaster"],
                checkpointer=memory,
            )
            final_dict  = graph.invoke(None, config=THREAD_CONFIG)
            final_state = GraphState(**final_dict)
    except Exception as e:
        logger.error(
            "Unhandled exception during broadcaster resume. run_id=%s error=%s",
            run_id, str(e),
            exc_info=True
        )
        raise

    logger.info(
        "Pipeline complete. run_id=%s records=%d anomalies=%d broadcast=%s",
        run_id,
        len(final_state.raw_data),
        final_state.analysis.anomalies_detected if final_state.analysis else 0,
        final_state.broadcast_result,
    )

    _print_pipeline_complete(final_state)

    try:
        execution_secs = round(time.time() - pipeline_start, 2)
        executed_at    = datetime.now(timezone.utc).isoformat()

        kelly_map: dict[str, tuple[float, float]] = {}
        if final_state.analysis and final_state.analysis.kelly_suggestions:
            for k in final_state.analysis.kelly_suggestions:
                kelly_map[k.market] = (k.kelly_fraction, k.expected_value)

        save_pipeline_run(
            run_id            = final_state.run_id,
            executed_at       = executed_at,
            fixtures_scanned  = len(set(
                r.market.split(" -- ")[0] for r in final_state.raw_data
            )) if final_state.raw_data else 0,
            records_ingested  = len(final_state.raw_data),
            markets_analysed  = len(set(r.market for r in final_state.raw_data)),
            anomalies_found   = final_state.analysis.anomalies_detected if final_state.analysis else 0,
            arb_opportunities = len(final_state.analysis.arb_opportunities) if final_state.analysis else 0,
            kelly_suggestions = len(final_state.analysis.kelly_suggestions) if final_state.analysis else 0,
            confidence_score  = final_state.analysis.confidence_score if final_state.analysis else 0.0,
            retry_count       = final_state.retry_count,
            audit_passed      = final_state.audit_result.passed if final_state.audit_result else False,
            broadcast_result  = final_state.broadcast_result or "not_attempted",
            execution_secs    = execution_secs,
            analysis_mode     = final_state.analysis_mode.value,
        )

        if final_state.analysis and final_state.analysis.findings:
            save_market_anomalies(
                run_id      = final_state.run_id,
                executed_at = executed_at,
                findings    = final_state.analysis.findings,
                kelly_map   = kelly_map,
            )

    except Exception as e:
        logger.error("Failed to persist run to database. error=%s", str(e), exc_info=True)

    return final_state


if __name__ == "__main__":
    mode = AnalysisMode.VALUE_SHEET

    if "--arb" in sys.argv:
        mode = AnalysisMode.ARB_ALERT_DIGEST
        logger.info("Mode override: ARB_ALERT_DIGEST")
        print("[Config] Mode override: ARB_ALERT_DIGEST")

    auto = "--auto" in sys.argv

    try:
        run_pipeline(
            run_id="production_run_001",
            analysis_mode=mode,
            auto_approve=auto,
        )
    except Exception as e:
        logger.critical(
            "Pipeline crashed with unhandled exception: %s",
            str(e),
            exc_info=True
        )
        sys.exit(1)