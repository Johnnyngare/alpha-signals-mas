
"""
GraphState: The single source of truth for the entire multi-agent system.

ARCHITECTURE NOTE — How LangGraph reads and writes this state:
--------------------------------------------------------------
LangGraph treats the state as an IMMUTABLE SNAPSHOT passed into each node.
Each node receives a full copy of the current state and returns a DICTIONARY
containing ONLY the keys it wants to update. LangGraph then merges that
partial dict back into the state for the next node.

This means:
  - Nodes NEVER mutate the state object directly.
  - A node that returns {} changes nothing.
  - A node that returns {"retry_count": 3} ONLY updates retry_count;
    all other fields remain exactly as they were.

For list fields (like `raw_data` and `audit_failures`), we use LangGraph's
`Annotated` + `operator.add` reducer pattern. This tells the graph engine:
"When merging, APPEND the new list to the existing list, don't replace it."
This is critical for accumulating records across agent runs.
"""

from __future__ import annotations

import operator
from enum import Enum
from typing import Annotated, Any, Literal, Optional
from pydantic import BaseModel, Field


class AnalysisMode(str, Enum):
    VALUE_SHEET      = "value_sheet"
    ARB_ALERT_DIGEST = "arb_alert_digest"


class ArbOpportunity(BaseModel):
    fixture:          str   = Field(description="The match fixture string")
    home_outcome:     str   = Field(description="Best home odds bookmaker and value")
    draw_outcome:     str   = Field(description="Best draw odds bookmaker and value")
    away_outcome:     str   = Field(description="Best away odds bookmaker and value")
    arb_margin:       float = Field(description="Sum of implied probabilities. <1.0 = arb exists")
    profit_pct:       float = Field(description="Guaranteed profit % on balanced stakes")
    recommended_stakes: dict[str, float] = Field(
        default_factory=dict,
        description="Recommended stake per outcome to guarantee profit on a 100-unit bankroll"
    )


class KellySuggestion(BaseModel):
    market:           str   = Field(description="The specific market (fixture + outcome)")
    best_odds:        float = Field(description="Best available decimal odds")
    best_bookmaker:   str   = Field(description="Bookmaker offering best odds")
    true_probability: float = Field(description="Consensus-implied true probability")
    kelly_fraction:   float = Field(description="Recommended bankroll fraction (0.0-1.0)")
    expected_value:   float = Field(description="Expected value per unit staked")
    
class MarketRecord(BaseModel):
    """
    A single raw data record produced by Agent A (The Scraper).
    Represents one unit of scraped market intelligence.
    """
    source: str = Field(description="Origin of the data, e.g. 'Betway', 'Binance'")
    market: str = Field(description="The specific market, e.g. 'BTC/USDT', 'Man Utd vs Arsenal Over 2.5'")
    value: float = Field(description="The raw numerical value: price, odds, spread, etc.")
    timestamp: str = Field(description="ISO 8601 timestamp string of when the record was captured")
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary extra fields: volume, liquidity, source confidence score, etc."
    )


class AnalysisResult(BaseModel):
    anomalies_detected:  int              = Field(description="Total count of anomalies or discrepancies found")
    findings:            list[str]        = Field(default_factory=list)
    confidence_score:    float            = Field(ge=0.0, le=1.0)
    flagged_records:     list[str]        = Field(default_factory=list)
    arb_opportunities:   list[ArbOpportunity]  = Field(default_factory=list, description="Confirmed arb opportunities")
    kelly_suggestions:   list[KellySuggestion] = Field(default_factory=list, description="Kelly-sized value bets")
    analysis_mode:       AnalysisMode     = Field(default=AnalysisMode.VALUE_SHEET)


class AuditResult(BaseModel):
    """
    The structured output of Agent D (The Auditor).
    Drives the conditional routing decision at the graph's final edge.
    """
    passed: bool = Field(
        description="True if the report passes ALL audit rules. False triggers re-routing."
    )
    failures: list[str] = Field(
        default_factory=list,
        description="List of specific rule violations found. Empty if passed=True."
    )
    failed_agent: Optional[Literal["scraper", "analyst", "reporter"]] = Field(
        default=None,
        description=(
            "If passed=False, which upstream agent is responsible for the failure. "
            "This is the key the conditional router reads to decide where to re-route."
        )
    )
    audit_notes: str = Field(
        default="",
        description="Free-text auditor commentary for logging and debugging."
    )



class GraphState(BaseModel):
    """
    The complete shared state that flows through every node in the graph.

    REDUCER MECHANICS:
    ------------------
    Fields annotated with `Annotated[list[X], operator.add]` use LangGraph's
    REDUCER pattern. Instead of the default "last write wins" merge, the graph
    ENGINE calls operator.add (list concatenation) when merging updates.

    Example: if state.raw_data = [record_1] and Agent A returns
    {"raw_data": [record_2]}, the graph produces state.raw_data = [record_1, record_2].

    Fields WITHOUT a reducer annotation use the default: the returned value
    REPLACES the existing value entirely.
    """


    raw_data: Annotated[list[MarketRecord], operator.add] = Field(
        default_factory=list,
        description=(
            "Accumulating list of raw market records. Uses operator.add reducer "
            "so that retry runs APPEND new records rather than overwriting prior ones."
        )
    )


    analysis: Optional[AnalysisResult] = Field(
        default=None,
        description="The latest analysis result. Replaced on each write (no reducer needed)."
    )

    analysis_mode: AnalysisMode = Field(
        default=AnalysisMode.VALUE_SHEET,
        description=(
            "Controls Agent B output mode. "
            "VALUE_SHEET: all discrepancy findings. "
            "ARB_ALERT_DIGEST: only confirmed arbitrage opportunities."
        )
    )


    report_markdown: str = Field(
        default="",
        description=(
            "The compiled Markdown intelligence report. Replaced on each write. "
            "An empty string signals the Reporter has not yet run."
        )
    )


    audit_result: Optional[AuditResult] = Field(
        default=None,
        description=(
            "The latest audit result. The conditional router at the END of the graph "
            "reads audit_result.passed and audit_result.failed_agent to determine "
            "whether to terminate or re-route to a broken agent."
        )
    )

    # --- Graph Control Fields ---
    retry_count: int = Field(
        default=0,
        description=(
            "Incremented by Agent D each time it triggers a re-route. "
            "The conditional router checks this against MAX_RETRIES to prevent "
            "infinite correction loops — our circuit breaker."
        )
    )

    audit_failures: Annotated[list[str], operator.add] = Field(
        default_factory=list,
        description=(
            "Persistent audit failure log. Uses operator.add so every failure "
            "from every audit pass is accumulated — never overwritten. "
            "This gives us a full correction history at termination."
        )
    )

    error_message: Optional[str] = Field(
        default=None,
        description=(
            "Set by any agent that encounters an unrecoverable exception. "
            "If populated, the graph should route to END to prevent cascading failures."
        )
    )

    broadcast_result: Optional[str] = Field(
        default=None,
        description=(
            "Set by Agent E (Broadcaster) after attempting Telegram delivery. "
            "Values: 'success', 'failed: <reason>', or None if not yet attempted."
        )
    )

    run_id: str = Field(
        default="run_001",
        description="Unique identifier for this graph execution. Useful for logging."
    )



MAX_RETRIES: int = 3
"""
Maximum number of times Agent D can re-route the graph before forcing termination.
This is the circuit breaker that prevents infinite self-healing loops.
"""