from datetime import datetime, timezone
from state import GraphState, MarketRecord, AnalysisResult, AnalysisMode, ArbOpportunity, KellySuggestion

REPORTER_FAIL: bool = False

REQUIRED_SECTIONS: list[str] = [
    "## Executive Summary",
    "## Raw Data Snapshot",
    "## Anomaly Analysis",
    "## Arbitrage Opportunities",
    "## Kelly Criterion Value Bets",
    "## Flagged Markets",
    "## Confidence Assessment",
    "## Methodology",
]


def _format_raw_data_table(records: list[MarketRecord]) -> str:
    if not records:
        return "_No records available._\n"
    header = "| Source | Market | Value | Timestamp |\n|--------|--------|-------|-----------|"
    rows = [
        f"| {r.source} | {r.market} | {r.value} | {r.timestamp} |"
        for r in records
    ]
    return header + "\n" + "\n".join(rows)


def _format_findings(analysis: AnalysisResult) -> str:
    if not analysis.findings:
        return "_No findings recorded._\n"
    return "\n".join(
        f"{i+1}. {finding}"
        for i, finding in enumerate(analysis.findings)
    )


def _format_flagged_markets(analysis: AnalysisResult) -> str:
    if not analysis.flagged_records:
        return "_No markets flagged. All lines within tolerance._\n"
    return "\n".join(
        f"- ** {market}** -- Discrepancy exceeds threshold. Recommend manual review."
        for market in analysis.flagged_records
    )


def _format_arb_opportunities(arbs: list[ArbOpportunity]) -> str:
    if not arbs:
        return "_No confirmed arbitrage opportunities detected in this scan._\n"
    lines = []
    for i, arb in enumerate(arbs, 1):
        lines.append(f"**ARB {i}: {arb.fixture}**")
        lines.append(f"- Arb Margin   : {arb.arb_margin:.6f} (must be < 1.0)")
        lines.append(f"- Profit       : {arb.profit_pct:.2f}% guaranteed on balanced stakes")
        lines.append(f"- Home Line    : {arb.home_outcome}")
        lines.append(f"- Draw Line    : {arb.draw_outcome}")
        lines.append(f"- Away Line    : {arb.away_outcome}")
        lines.append(f"- Recommended Stakes (per 100 units):")
        for leg, stake in arb.recommended_stakes.items():
            lines.append(f"  - {leg}: {stake} units")
        lines.append("")
    return "\n".join(lines)


def _format_kelly_suggestions(kelly_list: list[KellySuggestion]) -> str:
    if not kelly_list:
        return "_No value bets met the Kelly minimum edge threshold._\n"
    header = "| Market | Best Odds | Bookmaker | True Prob | Kelly % | EV |\n|--------|-----------|-----------|-----------|---------|-----|"
    rows = [
        f"| {k.market} | {k.best_odds} | {k.best_bookmaker} | "
        f"{k.true_probability:.2%} | {k.kelly_fraction:.2%} | {k.expected_value:.4f} |"
        for k in kelly_list
    ]
    return header + "\n" + "\n".join(rows)


def reporter_node(state: GraphState) -> dict:
    print(f"\n[Agent C -- Reporter] Starting. Compiling report for run_id={state.run_id}.")

    if REPORTER_FAIL:
        print("[Agent C -- Reporter] SIMULATED FAILURE: template engine crashed.")
        return {
            "report_markdown": "",
            "error_message": "Agent C failed: report template engine encountered a fatal error."
        }

    if state.analysis is None:
        print("[Agent C -- Reporter] WARNING: No analysis found in state.")
        return {
            "report_markdown": (
                "# DEGRADED REPORT\n\n"
                "> WARNING: Agent B analysis was not available. "
                "This report is incomplete and will fail audit.\n"
            ),
            "error_message": None
        }

    analysis     = state.analysis
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    mode_label   = "VALUE SHEET" if analysis.analysis_mode == AnalysisMode.VALUE_SHEET else "ARB ALERT DIGEST"
    retry_notice = (
        f"\n> WARNING: Correction Run #{state.retry_count} -- "
        "This report was regenerated after a prior audit failure.\n"
        if state.retry_count > 0 else ""
    )

    action_line = (
        "!! ACTION REQUIRED -- Anomalies detected. Review flagged markets immediately."
        if analysis.anomalies_detected > 0
        else ">> ALL CLEAR -- No significant discrepancies detected across monitored markets."
    )

    executive_summary = f"""\
## Executive Summary

{retry_notice}
**Run ID:** `{state.run_id}`
**Mode:** {mode_label}
**Generated At:** {generated_at}
**Total Records Ingested:** {len(state.raw_data)}
**Markets Analysed:** {len(set(r.market for r in state.raw_data))}
**Anomalies Detected:** {analysis.anomalies_detected}
**Arb Opportunities:** {len(analysis.arb_opportunities)}
**Kelly Suggestions:** {len(analysis.kelly_suggestions)}
**Overall Confidence:** {analysis.confidence_score:.2%}

{action_line}
"""

    raw_data_snapshot = f"""\
## Raw Data Snapshot

{_format_raw_data_table(state.raw_data)}
"""

    anomaly_analysis = f"""\
## Anomaly Analysis

{_format_findings(analysis)}
"""

    arb_section = f"""\
## Arbitrage Opportunities

{_format_arb_opportunities(analysis.arb_opportunities)}
"""

    kelly_section = f"""\
## Kelly Criterion Value Bets

{_format_kelly_suggestions(analysis.kelly_suggestions)}
"""

    flagged_markets = f"""\
## Flagged Markets

{_format_flagged_markets(analysis)}
"""

    confidence_assessment = f"""\
## Confidence Assessment

| Metric | Value |
|--------|-------|
| Confidence Score | {analysis.confidence_score:.4f} |
| Anomaly Rate | {analysis.anomalies_detected}/{len(set(r.market for r in state.raw_data))} markets |
| Arb Opportunities | {len(analysis.arb_opportunities)} confirmed |
| Kelly Suggestions | {len(analysis.kelly_suggestions)} value bets |
| Data Completeness | {len(state.raw_data)} records received |
| Retry Count | {state.retry_count} |

{"WARNING: Confidence degraded due to anomaly volume." if analysis.confidence_score < 0.8 else "Confidence level is acceptable."}
"""

    methodology = f"""\
## Methodology

- **Data Sources:** Betway, 1xBet, William Hill, Paddy Power (via The-Odds-API live feed)
- **Anomaly Detection:** Best vs worst odds discrepancy across all bookmakers for each outcome
- **Detection Threshold:** {5.0}% deviation triggers flagging
- **Arbitrage Detection:** Sum of implied probabilities across best available odds per outcome
- **Kelly Formula:** f* = (b*p - q) / b, quartered for conservative sizing, capped at 25%
- **Analysis Mode:** {mode_label}
- **Report Engine:** Agent C v2.0 -- LangGraph Multi-Agent System
"""

    full_report = "\n".join([
        f"# Market Intelligence Report -- {state.run_id}",
        "",
        executive_summary,
        raw_data_snapshot,
        anomaly_analysis,
        arb_section,
        kelly_section,
        flagged_markets,
        confidence_assessment,
        methodology,
    ])

    print(f"[Agent C -- Reporter] Report compiled. "
          f"{len(full_report)} characters, {len(full_report.splitlines())} lines.")

    return {"report_markdown": full_report, "error_message": None}