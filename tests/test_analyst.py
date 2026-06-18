"""
Unit tests for Agent B (Analyst) mathematical functions.

WHAT WE ARE TESTING:
--------------------
1. _compute_kelly   — Kelly Criterion formula boundary conditions
2. _detect_arb      — Arbitrage detection true/false positive verification
3. _build_fixture_map — Data structure construction from raw MarketRecord list

WHAT WE ARE NOT TESTING HERE:
------------------------------
- analyst_node() end-to-end behavior — covered by stress_test.py
- LangGraph state routing — covered by stress_test.py
- API response parsing — covered by scraper tests (future)

Each test function is completely self-contained. No shared fixtures
that could mask test isolation failures.
"""

import pytest
from agents.analyst import (
    _compute_kelly,
    _detect_arb,
    _build_fixture_map,
    ANOMALY_THRESHOLD_PCT,
    MIN_KELLY_EDGE,
    MAX_KELLY_FRACTION,
)
from state import MarketRecord



def _make_record(
    source: str,
    fixture: str,
    outcome: str,
    value: float,
) -> MarketRecord:
    return MarketRecord(
        source=source,
        market=f"{fixture} -- {outcome}",
        value=value,
        timestamp="2026-06-19T09:00:00Z",
    )



class TestComputeKelly:

    def test_returns_none_when_only_one_bookmaker(self):
        result = _compute_kelly(
            market="England vs Croatia -- Draw",
            best_odds=3.85,
            best_bookmaker="1xBet",
            all_odds={"1xBet": 3.85},
        )
        assert result is None, "Should return None with only one bookmaker — cannot derive consensus probability"

    def test_returns_none_when_best_odds_at_or_below_one(self):
        result = _compute_kelly(
            market="Canada vs Qatar -- Home Win",
            best_odds=1.0,
            best_bookmaker="Betway",
            all_odds={"Betway": 1.0, "1xBet": 1.05},
        )
        assert result is None, "Odds of 1.0 produce b=0.0 — division by zero in Kelly formula"

    def test_returns_none_when_kelly_fraction_below_minimum_edge(self):
        result = _compute_kelly(
            market="Germany vs Ivory Coast -- Home Win",
            best_odds=1.52,
            best_bookmaker="Betway",
            all_odds={"Betway": 1.52, "1xBet": 1.51, "William Hill": 1.50, "Paddy Power": 1.50},
        )
        assert result is None, (
            "Tight odds cluster should produce a Kelly fraction below MIN_KELLY_EDGE "
            f"({MIN_KELLY_EDGE}) and return None"
        )

    def test_returns_valid_suggestion_for_clear_value_bet(self):
        result = _compute_kelly(
            market="Brazil vs Haiti -- Away Win",
            best_odds=1.35,
            best_bookmaker="1xBet",
            all_odds={"1xBet": 1.35, "Betway": 1.25, "William Hill": 1.29},
        )
        assert result is not None, "Clear discrepancy across bookmakers should produce a Kelly suggestion"
        assert result.market == "Brazil vs Haiti -- Away Win"
        assert result.best_bookmaker == "1xBet"
        assert result.best_odds == 1.35
        assert 0.0 < result.kelly_fraction <= MAX_KELLY_FRACTION, (
            f"Kelly fraction {result.kelly_fraction} must be between 0 and MAX_KELLY_FRACTION ({MAX_KELLY_FRACTION})"
        )
        assert result.true_probability > 0.0
        assert result.true_probability < 1.0

    def test_kelly_fraction_never_exceeds_maximum(self):
        result = _compute_kelly(
            market="Extreme Value Test -- Home Win",
            best_odds=10.0,
            best_bookmaker="1xBet",
            all_odds={"1xBet": 10.0, "Betway": 2.0},
        )
        if result is not None:
            assert result.kelly_fraction <= MAX_KELLY_FRACTION, (
                f"Kelly fraction must never exceed cap of {MAX_KELLY_FRACTION}"
            )

    def test_kelly_fraction_never_negative(self):
        result = _compute_kelly(
            market="Negative Edge Test -- Away Win",
            best_odds=1.10,
            best_bookmaker="Betway",
            all_odds={"Betway": 1.10, "1xBet": 1.09, "William Hill": 1.08},
        )
        if result is not None:
            assert result.kelly_fraction >= 0.0, "Kelly fraction must never be negative"

    def test_expected_value_calculation_is_correct(self):
        best_odds = 1.35
        all_odds  = {"1xBet": 1.35, "Betway": 1.25, "William Hill": 1.29}

        implied_probs    = [1 / o for o in all_odds.values()]
        consensus_prob   = sum(implied_probs) / len(implied_probs)
        b                = best_odds - 1.0
        expected_ev      = round((b * consensus_prob) - (1.0 - consensus_prob), 4)

        result = _compute_kelly(
            market="EV Verification Test -- Home Win",
            best_odds=best_odds,
            best_bookmaker="1xBet",
            all_odds=all_odds,
        )

        if result is not None:
            assert abs(result.expected_value - expected_ev) < 0.001, (
                f"EV calculation mismatch. Expected ~{expected_ev}, got {result.expected_value}"
            )



class TestDetectArb:

    def test_returns_none_when_no_arb_exists(self):
        outcome_map = {
            "Home Win": {"Betway": 1.70, "1xBet": 1.75, "William Hill": 1.70},
            "Draw":     {"Betway": 3.80, "1xBet": 3.85, "William Hill": 3.75},
            "Away Win": {"Betway": 4.75, "1xBet": 5.07, "William Hill": 4.75},
        }
        result = _detect_arb("England vs Croatia", outcome_map)
        assert result is None, (
            "Realistic bookmaker odds should NOT produce arb — "
            "bookmakers build in a margin that prevents this"
        )

    def test_returns_none_when_missing_outcome(self):
        outcome_map = {
            "Home Win": {"Betway": 1.70, "1xBet": 1.75},
            "Draw":     {"Betway": 3.80, "1xBet": 3.85},
        }
        result = _detect_arb("Incomplete Fixture", outcome_map)
        assert result is None, "Missing Away Win outcome — arb cannot be computed for 3-way market"

    def test_returns_none_when_outcome_map_empty(self):
        result = _detect_arb("Empty Fixture", {})
        assert result is None, "Empty outcome map should return None without raising"

    def test_detects_true_arb_when_margin_below_one(self):
        outcome_map = {
            "Home Win": {"BookA": 3.20},
            "Draw":     {"BookB": 3.20},
            "Away Win": {"BookC": 3.20},
        }
        result = _detect_arb("Synthetic Arb Fixture", outcome_map)
        assert result is not None, "1/3.20 * 3 = 0.9375 < 1.0 — arb window must be detected"
        assert result.arb_margin < 1.0, f"arb_margin={result.arb_margin} must be < 1.0"
        assert result.profit_pct > 0.0, "Guaranteed profit must be positive"

    def test_arb_profit_calculation_is_mathematically_correct(self):
        outcome_map = {
            "Home Win": {"BookA": 3.20},
            "Draw":     {"BookB": 3.20},
            "Away Win": {"BookC": 3.20},
        }
        result = _detect_arb("Profit Calculation Test", outcome_map)
        assert result is not None

        expected_margin = (1 / 3.20) + (1 / 3.20) + (1 / 3.20)
        expected_profit = round((1 - expected_margin) * 100, 4)

        assert abs(result.arb_margin - expected_margin) < 0.0001, (
            f"Margin mismatch. Expected {expected_margin:.6f}, got {result.arb_margin}"
        )
        assert abs(result.profit_pct - expected_profit) < 0.01, (
            f"Profit mismatch. Expected {expected_profit:.4f}%, got {result.profit_pct}"
        )

    def test_arb_stakes_sum_to_approximately_100(self):
        outcome_map = {
            "Home Win": {"BookA": 3.20},
            "Draw":     {"BookB": 3.20},
            "Away Win": {"BookC": 3.20},
        }
        result = _detect_arb("Stakes Sum Test", outcome_map)
        assert result is not None

        total_stakes = sum(result.recommended_stakes.values())
        assert abs(total_stakes - 100.0) < 0.1, (
            f"Recommended stakes must sum to ~100 units. Got {total_stakes}"
        )

    def test_arb_uses_best_available_odds_per_outcome(self):
        outcome_map = {
            "Home Win": {"Betway": 2.90, "1xBet": 3.20, "William Hill": 2.80},
            "Draw":     {"Betway": 3.10, "1xBet": 3.20, "William Hill": 3.00},
            "Away Win": {"Betway": 3.00, "1xBet": 3.20, "William Hill": 2.90},
        }
        result = _detect_arb("Best Odds Selection Test", outcome_map)
        if result is not None:
            assert "1xBet" in result.home_outcome
            assert "1xBet" in result.draw_outcome
            assert "1xBet" in result.away_outcome



class TestBuildFixtureMap:

    def test_correctly_groups_records_by_fixture_and_outcome(self):
        records = [
            _make_record("Betway",       "England vs Croatia", "Home Win", 1.70),
            _make_record("1xBet",        "England vs Croatia", "Home Win", 1.78),
            _make_record("William Hill", "England vs Croatia", "Away Win", 4.75),
        ]
        result = _build_fixture_map(records)

        assert "England vs Croatia" in result
        assert "Home Win" in result["England vs Croatia"]
        assert "Away Win" in result["England vs Croatia"]
        assert result["England vs Croatia"]["Home Win"]["Betway"] == 1.70
        assert result["England vs Croatia"]["Home Win"]["1xBet"] == 1.78

    def test_handles_multiple_fixtures_independently(self):
        records = [
            _make_record("Betway", "England vs Croatia", "Home Win", 1.70),
            _make_record("Betway", "Brazil vs Haiti",    "Home Win", 1.11),
        ]
        result = _build_fixture_map(records)

        assert "England vs Croatia" in result
        assert "Brazil vs Haiti" in result
        assert len(result) == 2

    def test_returns_empty_dict_for_empty_input(self):
        result = _build_fixture_map([])
        assert result == {} or len(result) == 0, "Empty input must produce empty output"

    def test_skips_records_with_malformed_market_string(self):
        records = [
            _make_record("Betway", "England vs Croatia", "Home Win", 1.70),
            MarketRecord(
                source="Betway",
                market="malformed_no_separator",
                value=2.00,
                timestamp="2026-06-19T09:00:00Z",
            ),
        ]
        result = _build_fixture_map(records)
        assert "England vs Croatia" in result
        assert "malformed_no_separator" not in result

    def test_later_record_overwrites_earlier_for_same_source(self):
        records = [
            _make_record("Betway", "England vs Croatia", "Home Win", 1.70),
            _make_record("Betway", "England vs Croatia", "Home Win", 1.75),
        ]
        result = _build_fixture_map(records)
        assert result["England vs Croatia"]["Home Win"]["Betway"] == 1.75, (
            "Second record for same source+market should overwrite the first"
        )

    def test_handles_four_bookmakers_correctly(self):
        records = [
            _make_record("Betway",       "Germany vs Ivory Coast", "Away Win", 5.00),
            _make_record("1xBet",        "Germany vs Ivory Coast", "Away Win", 5.95),
            _make_record("William Hill", "Germany vs Ivory Coast", "Away Win", 5.00),
            _make_record("Paddy Power",  "Germany vs Ivory Coast", "Away Win", 5.50),
        ]
        result = _build_fixture_map(records)
        bookmakers = result["Germany vs Ivory Coast"]["Away Win"]

        assert len(bookmakers) == 4
        assert bookmakers["1xBet"] == 5.95
        assert bookmakers["Betway"] == 5.00




class TestAnomalyThresholdConsistency:

    def test_threshold_constant_is_positive(self):
        assert ANOMALY_THRESHOLD_PCT > 0.0, "Anomaly threshold must be positive"

    def test_threshold_is_percentage_not_decimal(self):
        assert ANOMALY_THRESHOLD_PCT >= 1.0, (
            "Threshold should be expressed as a percentage (e.g. 5.0), "
            "not a decimal (e.g. 0.05)"
        )

    def test_min_kelly_edge_is_positive(self):
        assert MIN_KELLY_EDGE > 0.0, "Minimum Kelly edge must be positive to prevent noise trades"

    def test_max_kelly_fraction_is_below_one(self):
        assert MAX_KELLY_FRACTION < 1.0, "Max Kelly fraction must be below 1.0 — never bet entire bankroll"

    def test_max_kelly_fraction_is_conservative(self):
        assert MAX_KELLY_FRACTION <= 0.25, (
            "Max Kelly fraction should be 25% or less for conservative production sizing"
        )