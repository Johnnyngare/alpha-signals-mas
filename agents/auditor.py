from agents.reporter import REQUIRED_SECTIONS
from state import GraphState, AuditResult

MIN_CONFIDENCE_SCORE: float = 0.5
"""
Minimum acceptable confidence score from Agent B.
Below this threshold, the data quality is considered too poor to report on.
"""

FORBIDDEN_KEYWORDS: list[str] = [
    "CRITICAL SYSTEM ERROR",
    "UNVERIFIED",
    "DO NOT DISTRIBUTE",
    "PLACEHOLDER",
]
"""
Safety guardrail: if any of these appear in the final report,
it indicates Agent C produced unsafe or template-error output.
"""

REQUIRED_MIN_RECORDS: int = 6
"""
We expect at least 2 sources × 3 markets minimum.
Fewer than this suggests the scraper had a partial failure.
"""


def auditor_node(state: GraphState) -> dict:
    """
    Agent D node function.

    Reads : state.raw_data, state.analysis, state.report_markdown,
            state.retry_count, state.run_id
    Writes: state.audit_result, state.retry_count, state.audit_failures
    """
    print(f"\n[Agent D — Auditor] Starting audit. retry_count={state.retry_count}")

    failures: list[str] = []
    failed_agent: str | None = None

    if not state.raw_data:
        failures.append("RULE 1 FAIL: raw_data is empty — Scraper produced no records.")
        failed_agent = "scraper"
        print("[Agent D — Auditor] RULE 1 FAIL: raw_data is empty.")

    # ------------------------------------------------------------------
    # RULE 2: At least two distinct sources must be present
    # ------------------------------------------------------------------
    if state.raw_data:
        sources_present = {r.source for r in state.raw_data}
        if len(sources_present) < 2:
            failures.append(
                f"RULE 2 FAIL: Only one data source found: {sources_present}. "
                "At least two bookmakers are required for comparison."
            )
            failed_agent = "scraper"
            print(f"[Agent D — Auditor] RULE 2 FAIL: only one source present {sources_present}.")

    if len(state.raw_data) < REQUIRED_MIN_RECORDS:
        failures.append(
            f"RULE 3 FAIL: Only {len(state.raw_data)} records found. "
            f"Minimum required: {REQUIRED_MIN_RECORDS}."
        )
        if failed_agent is None:
            failed_agent = "scraper"
        print(f"[Agent D — Auditor] RULE 3 FAIL: insufficient records ({len(state.raw_data)}).")

    if state.analysis is None:
        failures.append("RULE 4 FAIL: analysis is None — Analyst node did not produce output.")
        if failed_agent is None:
            failed_agent = "analyst"
        print("[Agent D — Auditor] RULE 4 FAIL: analysis is None.")

    if state.analysis is not None and state.analysis.confidence_score < MIN_CONFIDENCE_SCORE:
        failures.append(
            f"RULE 5 FAIL: Confidence score {state.analysis.confidence_score:.4f} "
            f"is below minimum threshold of {MIN_CONFIDENCE_SCORE}."
        )
        if failed_agent is None:
            failed_agent = "analyst"
        print(f"[Agent D — Auditor] RULE 5 FAIL: low confidence {state.analysis.confidence_score}.")

    if not state.report_markdown or len(state.report_markdown.strip()) == 0:
        failures.append("RULE 6 FAIL: report_markdown is empty — Reporter produced no output.")
        if failed_agent is None:
            failed_agent = "reporter"
        print("[Agent D — Auditor] RULE 6 FAIL: report_markdown is empty.")

    if state.report_markdown:
        missing_sections = [
            section for section in REQUIRED_SECTIONS
            if section not in state.report_markdown
        ]
        if missing_sections:
            failures.append(
                f"RULE 7 FAIL: Report is missing required sections: {missing_sections}"
            )
            if failed_agent is None:
                failed_agent = "reporter"
            print(f"[Agent D — Auditor] RULE 7 FAIL: missing sections {missing_sections}.")

    if state.report_markdown and state.run_id not in state.report_markdown:
        failures.append(
            f"RULE 8 FAIL: run_id '{state.run_id}' not found in report. "
            "Report may be stale or from a different run."
        )
        if failed_agent is None:
            failed_agent = "reporter"
        print(f"[Agent D — Auditor] RULE 8 FAIL: run_id missing from report.")

    if state.report_markdown:
        triggered_keywords = [
            kw for kw in FORBIDDEN_KEYWORDS
            if kw.upper() in state.report_markdown.upper()
        ]
        if triggered_keywords:
            failures.append(
                f"RULE 9 FAIL: Report contains forbidden keywords: {triggered_keywords}"
            )
            if failed_agent is None:
                failed_agent = "reporter"
            print(f"[Agent D — Auditor] RULE 9 FAIL: forbidden keywords {triggered_keywords}.")

    passed = len(failures) == 0

    audit_result = AuditResult(
        passed=passed,
        failures=failures,
        failed_agent=failed_agent,
        audit_notes=(
            f"Audit completed at retry_count={state.retry_count}. "
            f"{'All ' + str(len(REQUIRED_SECTIONS)) + ' structural rules passed.' if passed else f'{len(failures)} rule(s) failed. Routing to: {failed_agent}.'}"
        )
    )

    if passed:
        print(f"[Agent D — Auditor] ✅ AUDIT PASSED. Report is clean and complete.")
    else:
        print(f"[Agent D — Auditor] ❌ AUDIT FAILED. {len(failures)} failure(s). Re-routing to: {failed_agent}.")

    return {
        "audit_result": audit_result,
        "retry_count": state.retry_count + 1,
        "audit_failures": failures,  
    }