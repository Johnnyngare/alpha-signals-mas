import os
import random
from datetime import datetime, timezone
from dotenv import load_dotenv
import requests
from state import GraphState, MarketRecord

load_dotenv()

ODDS_API_KEY: str = os.getenv("ODDS_API_KEY", "")

ODDS_API_BASE_URL: str = "https://api.the-odds-api.com/v4/sports"
SPORT_KEY:         str = "soccer_fifa_world_cup"
REGIONS:           str = "eu"
MARKETS:           str = "h2h"
ODDS_FORMAT:       str = "decimal"

TARGET_BOOKMAKERS: list[str] = ["betway", "onexbet", "williamhill", "paddypower"]

BOOKMAKER_DISPLAY_NAMES: dict[str, str] = {
    "betway":          "Betway",
    "onexbet":         "1xBet",
    "williamhill":     "William Hill",
    "paddypower":      "Paddy Power",
    "betfair":         "Betfair",
    "unibet":          "Unibet",
    "sport888":        "888sport",
    "draftkings":      "DraftKings",
    "fanduel":         "FanDuel",
    "mybookieag":      "MyBookie",
    "betonlineag":     "BetOnline",
    "bovada":          "Bovada",
    "lowvig":          "LowVig",
    "wynnbet":         "WynnBet",
    "betrivers":       "BetRivers",
    "pointsbetus":     "PointsBet",
    "superbook":       "SuperBook",
    "ballybet":        "BallyBet",
    "hardrockbet":     "Hard Rock Bet",
    "fliff":           "Fliff",
    "tipico_us":       "Tipico",
}

REQUEST_TIMEOUT_SECONDS: int = 15
MAX_FIXTURES:            int = 10

SCRAPER_FAIL: bool = False


def _get_display_name(bookmaker_key: str) -> str:
    return BOOKMAKER_DISPLAY_NAMES.get(bookmaker_key, bookmaker_key.replace("_", " ").title())


def _outcome_label(outcome_name: str, home: str, away: str) -> str:
    if outcome_name == home:
        return "Home Win"
    if outcome_name == away:
        return "Away Win"
    return "Draw"


def _fetch_available_sports() -> list[str]:
    """
    Diagnostic helper. Calls /v4/sports to list all currently
    active sport keys. Used to verify the World Cup key is live.
    """
    url = f"{ODDS_API_BASE_URL}/?apiKey={ODDS_API_KEY}"
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
        resp.raise_for_status()
        sports = resp.json()
        soccer_keys = [s["key"] for s in sports if "soccer" in s.get("key", "")]
        return soccer_keys
    except Exception as e:
        print(f"[Agent A — Scraper] Could not fetch sport list: {e}")
        return []


def _fetch_live_odds(timestamp: str) -> list[MarketRecord]:
    """
    Primary data fetch from The-Odds-API v4 for soccer_fifa_world_cup.

    Endpoint: GET /v4/sports/{sport}/odds/
    Params:
        apiKey      — your API key
        regions     — eu (returns European bookmakers incl. Betway, 1xBet)
        markets     — h2h (head-to-head 3-way match odds)
        oddsFormat  — decimal
        bookmakers  — comma-separated bookmaker keys to filter

    Response structure:
    [
      {
        "id":        "...",
        "sport_key": "soccer_fifa_world_cup",
        "home_team": "France",
        "away_team": "Brazil",
        "commence_time": "2026-06-16T18:00:00Z",
        "bookmakers": [
          {
            "key":  "betway",
            "title": "Betway",
            "markets": [
              {
                "key": "h2h",
                "outcomes": [
                  {"name": "France", "price": 2.10},
                  {"name": "Brazil", "price": 3.20},
                  {"name": "Draw",   "price": 3.40}
                ]
              }
            ]
          }
        ]
      }
    ]
    """
    if not ODDS_API_KEY:
        raise ValueError(
            "ODDS_API_KEY is not set in .env. "
            "Get a free key at https://the-odds-api.com and add it to .env."
        )

    url = f"{ODDS_API_BASE_URL}/{SPORT_KEY}/odds/"
    params: dict = {
        "apiKey":     ODDS_API_KEY,
        "regions":    REGIONS,
        "markets":    MARKETS,
        "oddsFormat": ODDS_FORMAT,
    }

    if TARGET_BOOKMAKERS:
        params["bookmakers"] = ",".join(TARGET_BOOKMAKERS)

    headers: dict = {
        "Accept":          "application/json",
        "Accept-Encoding": "gzip, deflate",
        "Connection":      "keep-alive",
        "User-Agent":      "AlphaSignalsBot/2.0 (LangGraph MAS Pipeline)",
    }

    print(f"[Agent A — Scraper] GET {url}")
    print(f"[Agent A — Scraper] Params: sport={SPORT_KEY}, regions={REGIONS}, "
          f"markets={MARKETS}, bookmakers={TARGET_BOOKMAKERS}")

    response = requests.get(
        url,
        params=params,
        headers=headers,
        timeout=REQUEST_TIMEOUT_SECONDS
    )

    print(f"[Agent A — Scraper] HTTP {response.status_code} received.")

    if response.status_code == 401:
        raise ValueError(
            f"HTTP 401 Unauthorised — API key is invalid or missing. "
            f"Check ODDS_API_KEY in .env. Raw: {response.text[:200]}"
        )
    if response.status_code == 422:
        raise ValueError(
            f"HTTP 422 — Sport key '{SPORT_KEY}' is not recognised or not currently active. "
            f"Raw response: {response.text[:300]}"
        )
    if response.status_code == 429:
        raise ValueError(
            f"HTTP 429 — API rate limit exceeded. "
            f"Check your quota at https://the-odds-api.com/account. "
            f"Raw: {response.text[:200]}"
        )

    response.raise_for_status()

    remaining = response.headers.get("x-requests-remaining", "unknown")
    used      = response.headers.get("x-requests-used", "unknown")
    print(f"[Agent A — Scraper] Quota — requests used: {used}, remaining: {remaining}")

    events: list[dict] = response.json()
    print(f"[Agent A — Scraper] API returned {len(events)} event(s) for '{SPORT_KEY}'.")

    if not events:
        available = _fetch_available_sports()
        print(f"[Agent A — Scraper] Active soccer sport keys on your account: {available}")
        raise ValueError(
            f"Zero events returned for sport='{SPORT_KEY}'. "
            f"The tournament may not yet be listed or your account tier may not include it. "
            f"Active soccer keys found: {available}"
        )

    records: list[MarketRecord] = []
    fixtures_parsed: int = 0

    for event in events[:MAX_FIXTURES]:
        home            = event.get("home_team", "Home")
        away            = event.get("away_team", "Away")
        commence_time   = event.get("commence_time", timestamp)
        bookmakers_data = event.get("bookmakers", [])

        if not bookmakers_data:
            print(f"[Agent A — Scraper] No bookmaker data for fixture: {home} vs {away}. Skipping.")
            continue

        fixtures_parsed += 1
        print(f"[Agent A — Scraper] Parsing: {home} vs {away} "
              f"({len(bookmakers_data)} bookmaker(s), commence: {commence_time})")

        for bookmaker in bookmakers_data:
            bk_key  = bookmaker.get("key", "unknown")
            bk_name = _get_display_name(bk_key)

            for market in bookmaker.get("markets", []):
                if market.get("key") != "h2h":
                    continue

                for outcome in market.get("outcomes", []):
                    outcome_name  = outcome.get("name", "")
                    outcome_price = outcome.get("price", 0.0)

                    if outcome_price <= 1.0:
                        print(f"[Agent A — Scraper] WARNING: Suspicious odds value {outcome_price} "
                              f"for {outcome_name} in {home} vs {away}. Skipping outcome.")
                        continue

                    label = _outcome_label(outcome_name, home, away)

                    records.append(MarketRecord(
                        source=bk_name,
                        market=f"{home} vs {away} -- {label}",
                        value=round(float(outcome_price), 4),
                        timestamp=timestamp,
                        metadata={
                            "bookmaker_key":  bk_key,
                            "fixture":        f"{home} vs {away}",
                            "outcome_type":   label,
                            "sport":          SPORT_KEY,
                            "commence_time":  commence_time,
                            "region":         REGIONS,
                        }
                    ))

    if not records:
        raise ValueError(
            f"Events were returned ({len(events)}) but zero MarketRecords could be parsed. "
            f"TARGET_BOOKMAKERS {TARGET_BOOKMAKERS} may not match any bookmakers "
            f"in the API response. Try setting TARGET_BOOKMAKERS = [] to fetch all bookmakers."
        )

    print(f"[Agent A — Scraper] Parsed {len(records)} outcome records "
          f"from {fixtures_parsed} fixtures.")

    return records


def _generate_world_cup_fallback(timestamp: str) -> list[MarketRecord]:
    """
    Fallback layer — activated ONLY when the live API call fails.
    Uses realistic 2026 FIFA World Cup group stage fixtures and odds.
    Keeps the downstream pipeline running without crashing.
    """
    fixtures: list[dict] = [
        {"home": "France",        "away": "Morocco",      "home_odds": 1.70, "draw_odds": 3.80, "away_odds": 5.00},
        {"home": "Brazil",        "away": "Argentina",    "home_odds": 2.20, "draw_odds": 3.30, "away_odds": 3.10},
        {"home": "England",       "away": "Spain",        "home_odds": 2.50, "draw_odds": 3.20, "away_odds": 2.80},
        {"home": "Germany",       "away": "Portugal",     "home_odds": 2.10, "draw_odds": 3.40, "away_odds": 3.30},
        {"home": "Netherlands",   "away": "USA",          "home_odds": 1.85, "draw_odds": 3.60, "away_odds": 4.20},
        {"home": "Japan",         "away": "South Korea",  "home_odds": 2.40, "draw_odds": 3.10, "away_odds": 2.90},
        {"home": "Senegal",       "away": "Mexico",       "home_odds": 2.80, "draw_odds": 3.10, "away_odds": 2.50},
        {"home": "Canada",        "away": "Croatia",      "home_odds": 3.20, "draw_odds": 3.20, "away_odds": 2.20},
    ]

    bookmakers: list[str] = ["Betway", "1xBet"]
    records: list[MarketRecord] = []

    for fixture in fixtures:
        home = fixture["home"]
        away = fixture["away"]

        for bk in bookmakers:
            noise = lambda base: round(base * random.uniform(0.96, 1.06), 4)

            for outcome_label, base_odds in [
                ("Home Win", fixture["home_odds"]),
                ("Draw",     fixture["draw_odds"]),
                ("Away Win", fixture["away_odds"]),
            ]:
                records.append(MarketRecord(
                    source=bk,
                    market=f"{home} vs {away} -- {outcome_label}",
                    value=noise(base_odds),
                    timestamp=timestamp,
                    metadata={
                        "bookmaker_key": bk.lower().replace(" ", "").replace("x", "x"),
                        "fixture":       f"{home} vs {away}",
                        "outcome_type":  outcome_label,
                        "sport":         SPORT_KEY,
                        "data_source":   "world_cup_fallback",
                    }
                ))

    return records


def scraper_node(state: GraphState) -> dict:
    print(f"\n[Agent A — Scraper] Starting. run_id={state.run_id}, retry={state.retry_count}")

    if SCRAPER_FAIL:
        print("[Agent A — Scraper] SIMULATED FAILURE: scraper is down.")
        return {"error_message": "Agent A failed: data source unreachable."}

    timestamp = datetime.now(timezone.utc).isoformat()
    records:     list[MarketRecord] = []
    data_source: str = "live"

    try:
        records = _fetch_live_odds(timestamp)

    except requests.exceptions.Timeout:
        print(f"[Agent A — Scraper] NETWORK ERROR: Request timed out after "
              f"{REQUEST_TIMEOUT_SECONDS}s. Activating World Cup fallback layer.")
        data_source = "fallback"

    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response is not None else "unknown"
        body   = e.response.text[:300] if e.response is not None else ""
        print(f"[Agent A — Scraper] NETWORK ERROR: HTTP {status}. "
              f"Body snippet: {body}. Activating World Cup fallback layer.")
        data_source = "fallback"

    except requests.exceptions.ConnectionError as e:
        print(f"[Agent A — Scraper] NETWORK ERROR: Connection failed — {e}. "
              f"Activating World Cup fallback layer.")
        data_source = "fallback"

    except ValueError as e:
        print(f"[Agent A — Scraper] DATA ERROR: {e}. "
              f"Activating World Cup fallback layer.")
        data_source = "fallback"

    except Exception as e:
        print(f"[Agent A — Scraper] UNEXPECTED ERROR: {type(e).__name__}: {e}. "
              f"Activating World Cup fallback layer.")
        data_source = "fallback"

    if data_source == "fallback":
        records = _generate_world_cup_fallback(timestamp)
        print(f"[Agent A — Scraper] World Cup fallback active. "
              f"{len(records)} records generated across "
              f"{len(records) // (2 * 3)} fixtures.")

    sources_found = list(set(r.source for r in records))
    print(f"[Agent A — Scraper] Final record count: {len(records)}. "
          f"Sources: {sources_found}. Data layer: {data_source}.")

    return {
        "raw_data":      records,
        "error_message": None,
    }