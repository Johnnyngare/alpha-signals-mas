
import agents.scraper as scraper_module
import agents.analyst as analyst_module
import agents.reporter as reporter_module
from graph import graph
from state import GraphState


SEPARATOR = "=" * 65


def run_test(
    test_name: str,
    run_id: str,
    fail_module,
    fail_flag: str,
) -> GraphState:
    """
    Generic stress test runner.

    Args:
        test_name   : Human-readable test label.
        run_id      : Unique ID for this test run.
        fail_module : The module containing the _FAIL flag (e.g. scraper_module).
        fail_flag   : The attribute name of the flag (e.g. 'SCRAPER_FAIL').

    Flow:
        - Sets fail_flag = True on fail_module BEFORE the graph runs.
        - The graph's first pass through the broken agent writes either
          an error_message or broken output to state.
        - Agent D detects the violation and sets audit_result.failed_agent.
        - The router re-routes back to the broken agent.
        - The flag is then set to False IN THE SAME PROCESS so the retry
          succeeds — simulating the agent self-healing (e.g. data source
          comes back online, template engine recovers).
        - Graph continues to END.

    NOTE on flag-clearing timing:
        The flag is cleared AFTER graph.stream() starts but BEFORE the
        retry node executes. This is possible because stream() is a
        generator — it yields after each node, giving us a window to
        mutate module-level state between yields.
    """
    print(f"\n{SEPARATOR}")
    print(f"  {test_name}")
    print(f"  run_id: {run_id}")
    print(SEPARATOR)

    setattr(fail_module, fail_flag, True)
    print(f"\n[Test] Injected failure: {fail_module.__name__}.{fail_flag} = True")

    initial_state = GraphState(run_id=run_id)
    final_state_dict: dict = {}
    failure_injected = True
    nodes_visited: list[str] = []

    for state_update in graph.stream(
        initial_state.model_dump(),
        stream_mode="values"
    ):
        final_state_dict = state_update

        current_retry = state_update.get("retry_count", 0)
        if failure_injected and current_retry >= 1:
            setattr(fail_module, fail_flag, False)
            failure_injected = False
            print(f"\n[Test] ✅ Cleared failure flag: {fail_module.__name__}.{fail_flag} = False")
            print(f"[Test] Self-healing engaged. Next node execution will succeed.")

    final_state = GraphState(**final_state_dict)

    print(f"\n{'-' * 65}")
    print(f"  TEST RESULTS: {test_name}")
    print(f"{'-' * 65}")

    assert final_state.audit_result is not None, "FAIL: audit_result is None"
    assert final_state.audit_result.passed, \
        f"FAIL: Audit did not pass after recovery. Failures: {final_state.audit_result.failures}"
    assert final_state.retry_count >= 1, \
        f"FAIL: retry_count={final_state.retry_count}, expected >= 1 (no retry occurred)"
    assert len(final_state.audit_failures) > 0, \
        "FAIL: audit_failures history is empty — failure was never recorded"
    assert final_state.report_markdown, "FAIL: Final report is empty"
    assert final_state.error_message is None, \
        f"FAIL: error_message was not cleared after recovery: {final_state.error_message}"

    print(f"  ✅ Audit passed after recovery    : {final_state.audit_result.passed}")
    print(f"  ✅ Retry count (expected >= 1)    : {final_state.retry_count}")
    print(f"  ✅ Audit failure history recorded : {len(final_state.audit_failures)} failure(s)")
    print(f"  ✅ Final report present           : {len(final_state.report_markdown)} chars")
    print(f"  ✅ Error message cleared          : {final_state.error_message}")
    print(f"\n  Recorded failure(s) in audit history:")
    for failure in final_state.audit_failures:
        print(f"    ⚠️  {failure}")

    return final_state


def test_scraper_failure():
    """
    TEST 1: Agent A returns no records.

    Expected audit violation : RULE 1 — raw_data is empty
    Expected failed_agent    : 'scraper'
    Expected router action   : re-route to scraper node
    Self-heal                : flag cleared, scraper retries and succeeds
    """
    return run_test(
        test_name="TEST 1 — Scraper Failure & Self-Healing",
        run_id="stress_test_scraper",
        fail_module=scraper_module,
        fail_flag="SCRAPER_FAIL",
    )


def test_analyst_failure():
    """
    TEST 2: Agent B crashes and returns an error_message.

    Expected audit violation : RULE 4 — analysis is None
    Expected failed_agent    : 'analyst'
    Expected router action   : re-route to analyst node
    Self-heal                : flag cleared, analyst retries and succeeds

    NOTE: When ANALYST_FAIL=True, analyst_node returns {"error_message": "..."}
    without writing to state.analysis. Agent D sees analysis=None → RULE 4 fires.
    """
    return run_test(
        test_name="TEST 2 — Analyst Failure & Self-Healing",
        run_id="stress_test_analyst",
        fail_module=analyst_module,
        fail_flag="ANALYST_FAIL",
    )


def test_reporter_failure():
    """
    TEST 3: Agent C crashes and returns an error_message.

    Expected audit violation : RULE 6 — report_markdown is empty
    Expected failed_agent    : 'reporter'
    Expected router action   : re-route to reporter node
    Self-heal                : flag cleared, reporter retries and succeeds
    """
    return run_test(
        test_name="TEST 3 — Reporter Failure & Self-Healing",
        run_id="stress_test_reporter",
        fail_module=reporter_module,
        fail_flag="REPORTER_FAIL",
    )


def test_circuit_breaker():
    """
    TEST 4: Permanent scraper failure that never self-heals.

    The flag is NEVER cleared. The graph should:
        - Retry scraper up to MAX_RETRIES times
        - Router hits the circuit breaker condition
        - Graph terminates at END with audit_passed=False

    This proves the system cannot loop infinitely.
    """
    from state import MAX_RETRIES

    print(f"\n{SEPARATOR}")
    print(f"  TEST 4 — Circuit Breaker (Permanent Failure)")
    print(f"  run_id: stress_test_circuit_breaker")
    print(SEPARATOR)

    scraper_module.SCRAPER_FAIL = True
    print(f"\n[Test] Injected PERMANENT failure: SCRAPER_FAIL = True (will NOT be cleared)")
    print(f"[Test] Expecting circuit breaker to fire after {MAX_RETRIES} retries.")

    initial_state = GraphState(run_id="stress_test_circuit_breaker")
    final_state_dict: dict = {}

    for state_update in graph.stream(
        initial_state.model_dump(),
        stream_mode="values"
    ):
        final_state_dict = state_update

    scraper_module.SCRAPER_FAIL = False

    final_state = GraphState(**final_state_dict)

    print(f"\n{'-' * 65}")
    print(f"  TEST RESULTS: Circuit Breaker")
    print(f"{'-' * 65}")

    assert final_state.retry_count >= MAX_RETRIES, \
        f"FAIL: Circuit breaker did not fire. retry_count={final_state.retry_count}"
    assert len(final_state.audit_failures) >= MAX_RETRIES, \
        f"FAIL: Expected >= {MAX_RETRIES} accumulated failures, got {len(final_state.audit_failures)}"

    print(f"  ✅ Circuit breaker fired at retry  : {final_state.retry_count}")
    print(f"  ✅ Total accumulated failures      : {len(final_state.audit_failures)}")
    print(f"  ✅ Graph terminated without hang   : confirmed")
    print(f"\n  Full audit failure history:")
    for i, failure in enumerate(final_state.audit_failures, 1):
        print(f"    [{i}] {failure}")

    return final_state


if __name__ == "__main__":
    print("\n" + "=" * 65)
    print("  PHASE 5: STRESS TEST SUITE")
    print("=" * 65)

    results = {}

    results["scraper"]         = test_scraper_failure()
    results["analyst"]         = test_analyst_failure()
    results["reporter"]        = test_reporter_failure()
    results["circuit_breaker"] = test_circuit_breaker()

    print("\n\n" + "=" * 65)
    print("  ALL STRESS TESTS PASSED")
    print("=" * 65)
    for test_name, state in results.items():
        status = "✅ RECOVERED" if state.audit_result and state.audit_result.passed else "🛑 TERMINATED"
        print(f"  {status}  |  {test_name:<20} | retries={state.retry_count} | failures logged={len(state.audit_failures)}")
    print("=" * 65)