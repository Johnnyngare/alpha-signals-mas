from __future__ import annotations
from collections import defaultdict
from typing import Optional
from state import GraphState, MarketRecord, AnalysisResult, ArbOpportunity, KellySuggestion, AnalysisMode

ANOMALY_THRESHOLD_PCT:  float = 5.0
MIN_KELLY_EDGE:         float = 0.02
MAX_KELLY_FRACTION:     float = 0.25
KELLY_FRACTION_DIVISOR: float = 4.0
ANALYST_FAIL:           bool  = False


def _build_fixture_map(records: list[MarketRecord]) -> dict[str, dict[str, dict[str, float]]]:
    fixture_map: dict[str, dict[str, dict[str, float]]] = defaultdict(lambda: defaultdict(dict))
    for record in records:
        parts = record.market.split(" -- ", 1)
        if len(parts) != 2:
            continue
        fixture, outcome = parts[0].strip(), parts[1].strip()
        fixture_map[fixture][outcome][record.source] = record.value
    return fixture_map


def _detect_arb(
    fixture: str,
    outcome_map: dict[str, dict[str, float]]
) -> Optional[ArbOpportunity]:
    outcome_keys = list(outcome_map.keys())
    home_key = next((k for k in outcome_keys if "Home" in k), None)
    draw_key = next((k for k in outcome_keys if "Draw" in k), None)
    away_key = next((k for k in outcome_keys if "Away" in k), None)

    if not all([home_key, draw_key, away_key]):
        return None

    best_home_bk  = max(sorted(outcome_map[home_key].keys()), key=outcome_map[home_key].get)
    best_draw_bk  = max(sorted(outcome_map[draw_key].keys()), key=outcome_map[draw_key].get)
    best_away_bk  = max(sorted(outcome_map[away_key].keys()), key=outcome_map[away_key].get)

    best_home_odd = outcome_map[home_key][best_home_bk]
    best_draw_odd = outcome_map[draw_key][best_draw_bk]
    best_away_odd = outcome_map[away_key][best_away_bk]

    arb_margin = (1 / best_home_odd) + (1 / best_draw_odd) + (1 / best_away_odd)

    if arb_margin >= 1.0:
        return None

    profit_pct = round((1 - arb_margin) * 100, 4)
    total      = 100.0

    stakes = {
        f"{best_home_bk} — {home_key}": round((1 / best_home_odd) / arb_margin * total, 2),
        f"{best_draw_bk} — {draw_key}": round((1 / best_draw_odd) / arb_margin * total, 2),
        f"{best_away_bk} — {away_key}": round((1 / best_away_odd) / arb_margin * total, 2),
    }

    return ArbOpportunity(
        fixture=fixture,
        home_outcome=f"{best_home_bk} @ {best_home_odd}",
        draw_outcome=f"{best_draw_bk} @ {best_draw_odd}",
        away_outcome=f"{best_away_bk} @ {best_away_odd}",
        arb_margin=round(arb_margin, 6),
        profit_pct=profit_pct,
        recommended_stakes=stakes,
    )


def _compute_kelly(
    market: str,
    best_odds: float,
    best_bookmaker: str,
    all_odds: dict[str, float]
) -> Optional[KellySuggestion]:
    if len(all_odds) < 2:
        return None

    implied_probs = [1 / o for o in all_odds.values() if o > 1.0]
    if not implied_probs:
        return None

    consensus_prob = sum(implied_probs) / len(implied_probs)
    b = best_odds - 1.0
    p = consensus_prob
    q = 1.0 - p

    if b <= 0:
        return None

    kelly_fraction = (b * p - q) / b
    kelly_fraction = max(0.0, kelly_fraction)
    kelly_fraction = min(kelly_fraction / KELLY_FRACTION_DIVISOR, MAX_KELLY_FRACTION)
    kelly_fraction = round(kelly_fraction, 4)

    expected_value = round((b * p) - q, 4)

    if kelly_fraction < MIN_KELLY_EDGE:
        return None

    return KellySuggestion(
        market=market,
        best_odds=best_odds,
        best_bookmaker=best_bookmaker,
        true_probability=round(consensus_prob, 4),
        kelly_fraction=kelly_fraction,
        expected_value=expected_value,
    )


def _run_value_sheet_analysis(
    fixture_map: dict[str, dict[str, dict[str, float]]]
) -> tuple[list[str], list[str], list[ArbOpportunity], list[KellySuggestion]]:
    findings:          list[str]             = []
    flagged_records:   list[str]             = []
    arb_opportunities: list[ArbOpportunity]  = []
    kelly_suggestions: list[KellySuggestion] = []

    for fixture, outcome_map in fixture_map.items():
        arb = _detect_arb(fixture, outcome_map)
        if arb:
            arb_opportunities.append(arb)
            findings.append(
                f"ARB DETECTED [{fixture}]: margin={arb.arb_margin:.4f}, "
                f"guaranteed profit={arb.profit_pct:.2f}% on 100-unit stake."
            )

        for outcome, bookmaker_odds in outcome_map.items():
            market_key = f"{fixture} -- {outcome}"
            if len(bookmaker_odds) < 2:
                findings.append(f"SKIP [{market_key}]: Only one source, cannot compare.")
                continue

            sorted_by_name = sorted(bookmaker_odds.items(), key=lambda x: x[0])
            sorted_by_odds = sorted(sorted_by_name, key=lambda x: x[1], reverse=True)
            best_bk,  best_odd  = sorted_by_odds[0]
            worst_bk, worst_odd = sorted_by_odds[-1]

            discrepancy_pct = abs(best_odd - worst_odd) / worst_odd * 100

            if discrepancy_pct > ANOMALY_THRESHOLD_PCT:
                finding = (
                    f"ANOMALY [{market_key}]: {best_bk}={best_odd}, "
                    f"{worst_bk}={worst_odd}, "
                    f"Discrepancy={discrepancy_pct:.2f}% -- exceeds {ANOMALY_THRESHOLD_PCT}% threshold."
                )
                findings.append(finding)
                flagged_records.append(market_key)
                print(f"[Agent B -- Analyst] {finding}")

                kelly = _compute_kelly(
                    market=market_key,
                    best_odds=best_odd,
                    best_bookmaker=best_bk,
                    all_odds=bookmaker_odds,
                )
                if kelly:
                    kelly_suggestions.append(kelly)
                    print(
                        f"[Agent B -- Analyst] Kelly [{market_key}]: "
                        f"f*={kelly.kelly_fraction:.2%}, EV={kelly.expected_value:.4f}, "
                        f"best odds={best_odd} @ {best_bk}"
                    )
            else:
                findings.append(
                    f"CLEAN  [{market_key}]: {best_bk}={best_odd}, "
                    f"{worst_bk}={worst_odd}, "
                    f"Discrepancy={discrepancy_pct:.2f}% -- within tolerance."
                )

    return findings, flagged_records, arb_opportunities, kelly_suggestions


def _run_arb_digest_analysis(
    fixture_map: dict[str, dict[str, dict[str, float]]]
) -> tuple[list[str], list[str], list[ArbOpportunity], list[KellySuggestion]]:
    findings:          list[str]             = []
    flagged_records:   list[str]             = []
    arb_opportunities: list[ArbOpportunity]  = []

    for fixture, outcome_map in fixture_map.items():
        arb = _detect_arb(fixture, outcome_map)
        if arb:
            arb_opportunities.append(arb)
            flagged_records.append(fixture)
            findings.append(
                f"ARB CONFIRMED [{fixture}]: "
                f"Home={arb.home_outcome}, "
                f"Draw={arb.draw_outcome}, "
                f"Away={arb.away_outcome} | "
                f"Margin={arb.arb_margin:.4f} | "
                f"Profit={arb.profit_pct:.2f}%"
            )
            print(f"[Agent B -- Analyst] {findings[-1]}")
        else:
            findings.append(f"NO ARB [{fixture}]: margin >= 1.0, no guaranteed profit available.")

    return findings, flagged_records, arb_opportunities, []


def analyst_node(state: GraphState) -> dict:
    print(f"\n[Agent B -- Analyst] Starting. Received {len(state.raw_data)} records. "
          f"Mode: {state.analysis_mode.value}")

    if ANALYST_FAIL:
        print("[Agent B -- Analyst] SIMULATED FAILURE: analysis engine crashed.")
        return {"error_message": "Agent B failed: analysis engine encountered a fatal error."}

    if not state.raw_data:
        print("[Agent B -- Analyst] WARNING: raw_data is empty.")
        return {
            "analysis": AnalysisResult(
                anomalies_detected=0,
                findings=["WARNING: No raw data available for analysis."],
                confidence_score=0.0,
                flagged_records=[],
                analysis_mode=state.analysis_mode,
            )
        }

    fixture_map = _build_fixture_map(state.raw_data)
    mode        = state.analysis_mode

    if mode == AnalysisMode.ARB_ALERT_DIGEST:
        findings, flagged_records, arb_opportunities, kelly_suggestions = \
            _run_arb_digest_analysis(fixture_map)
    else:
        findings, flagged_records, arb_opportunities, kelly_suggestions = \
            _run_value_sheet_analysis(fixture_map)

    anomaly_count = len(flagged_records)
    markets_total = len(fixture_map) * (1 if mode == AnalysisMode.ARB_ALERT_DIGEST
                                        else sum(len(v) for v in fixture_map.values()))

    if markets_total == 0:
        base_confidence = 0.0
    else:
        base_confidence = 1.0 - (anomaly_count / max(markets_total, 1)) * 0.2
        base_confidence = round(max(0.1, min(1.0, base_confidence)), 4)

    result = AnalysisResult(
        anomalies_detected=anomaly_count,
        findings=findings,
        confidence_score=base_confidence,
        flagged_records=flagged_records,
        arb_opportunities=arb_opportunities,
        kelly_suggestions=kelly_suggestions,
        analysis_mode=mode,
    )

    print(
        f"[Agent B -- Analyst] Complete. "
        f"Fixtures: {len(fixture_map)}, "
        f"Anomalies/Arbs: {anomaly_count}, "
        f"Arb opportunities: {len(arb_opportunities)}, "
        f"Kelly suggestions: {len(kelly_suggestions)}, "
        f"Confidence: {base_confidence}"
    )

    return {"analysis": result, "error_message": None}