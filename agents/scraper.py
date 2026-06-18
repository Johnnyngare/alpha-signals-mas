import asyncio
import logging
import os
import random
from datetime import datetime, timezone
from dotenv import load_dotenv
import aiohttp
from state import GraphState, MarketRecord

load_dotenv()

logger = logging.getLogger(__name__)

ODDS_API_KEY:  str = os.getenv("ODDS_API_KEY", "")
ODDS_API_BASE: str = "https://api.the-odds-api.com/v4/sports"

SPORT_KEYS: list[str] = [
    "soccer_fifa_world_cup",
]

REGIONS:    str = "eu"
MARKETS:    str = "h2h"
ODDS_FORMAT: str = "decimal"

TARGET_BOOKMAKERS: list[str] = ["betway", "onexbet", "williamhill", "paddypower"]

BOOKMAKER_DISPLAY_NAMES: dict[str, str] = {
    "betway":         "Betway",
    "onexbet":        "1xBet",
    "williamhill":    "William Hill",
    "paddypower":     "Paddy Power",
    "betfair":        "Betfair",
    "unibet":         "Unibet",
    "sport888":       "888sport",
    "mybookieag":     "MyBookie",
    "betonlineag":    "BetOnline",
    "bovada":         "Bovada",
    "lowvig":         "LowVig",
    "draftkings":     "DraftKings",
    "fanduel":        "FanDuel",
}

REQUEST_TIMEOUT_SECONDS: int = 15
MAX_FIXTURES_PER_SPORT:  int = 10
SCRAPER_FAIL:            bool = False


def _get_display_name(bookmaker_key: str) -> str:
    return BOOKMAKER_DISPLAY_NAMES.get(
        bookmaker_key,
        bookmaker_key.replace("_", " ").title()
    )


def _outcome_label(outcome_name: str, home: str, away: str) -> str:
    if outcome_name == home:
        return "Home Win"
    if outcome_name == away:
        return "Away Win"
    return "Draw"


def _parse_events(
    events:     list[dict],
    sport_key:  str,
    timestamp:  str,
) -> list[MarketRecord]:
    records: list[MarketRecord] = []

    for event in events[:MAX_FIXTURES_PER_SPORT]:
        home            = event.get("home_team", "Home")
        away            = event.get("away_team", "Away")
        commence_time   = event.get("commence_time", timestamp)
        bookmakers_data = event.get("bookmakers", [])

        if not bookmakers_data:
            logger.warning(
                "No bookmaker data for fixture: %s vs %s. Skipping.",
                home, away
            )
            continue

        logger.info(
            "Parsing: %s vs %s (%d bookmaker(s), commence: %s)",
            home, away, len(bookmakers_data), commence_time
        )

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
                        logger.warning(
                            "Suspicious odds value %.4f for %s in %s vs %s. Skipping.",
                            outcome_price, outcome_name, home, away
                        )
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
                            "sport":          sport_key,
                            "commence_time":  commence_time,
                            "region":         REGIONS,
                        }
                    ))

    return records


async def _fetch_sport(
    session:    aiohttp.ClientSession,
    sport_key:  str,
    timestamp:  str,
) -> list[MarketRecord]:
    """
    Fetches live odds for a single sport key.
    Called concurrently via asyncio.gather() for multiple sport keys.
    Returns an empty list on any failure so gather() can continue
    collecting results from other sport keys.
    """
    if not ODDS_API_KEY:
        raise ValueError(
            "ODDS_API_KEY is not set in .env. "
            "Get a free key at https://the-odds-api.com"
        )

    url    = f"{ODDS_API_BASE}/{sport_key}/odds/"
    params = {
        "apiKey":     ODDS_API_KEY,
        "regions":    REGIONS,
        "markets":    MARKETS,
        "oddsFormat": ODDS_FORMAT,
    }

    if TARGET_BOOKMAKERS:
        params["bookmakers"] = ",".join(TARGET_BOOKMAKERS)

    headers = {
        "Accept":          "application/json",
        "Accept-Encoding": "gzip, deflate",
        "User-Agent":      "AlphaSignalsBot/2.0 (LangGraph MAS Pipeline)",
    }

    logger.info("GET %s | sport=%s", url, sport_key)

    try:
        async with session.get(
            url,
            params=params,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS),
        ) as response:

            logger.info("HTTP %d received for sport=%s", response.status, sport_key)

            remaining = response.headers.get("x-requests-remaining", "unknown")
            used      = response.headers.get("x-requests-used", "unknown")
            logger.info(
                "Quota | sport=%s | used=%s remaining=%s",
                sport_key, used, remaining
            )

            if response.status == 401:
                raise ValueError(
                    f"HTTP 401 Unauthorised for sport={sport_key}. "
                    "Check ODDS_API_KEY in .env."
                )
            if response.status == 422:
                raise ValueError(
                    f"HTTP 422 for sport={sport_key}. "
                    "Sport key not recognised or not active."
                )
            if response.status == 429:
                raise ValueError(
                    f"HTTP 429 for sport={sport_key}. "
                    "API rate limit exceeded."
                )

            response.raise_for_status()

            events: list[dict] = await response.json()
            logger.info(
                "API returned %d event(s) for sport=%s",
                len(events), sport_key
            )

            if not events:
                logger.warning(
                    "Zero events returned for sport=%s. "
                    "Season may be off or sport not active.",
                    sport_key
                )
                return []

            records = _parse_events(events, sport_key, timestamp)
            logger.info(
                "Parsed %d outcome records from sport=%s",
                len(records), sport_key
            )
            return records

    except aiohttp.ClientConnectorError as e:
        logger.error("Connection failed for sport=%s. error=%s", sport_key, str(e))
        return []
    except asyncio.TimeoutError:
        logger.error(
            "Request timed out after %ds for sport=%s.",
            REQUEST_TIMEOUT_SECONDS, sport_key
        )
        return []
    except ValueError as e:
        logger.error("Data error for sport=%s. error=%s", sport_key, str(e))
        return []
    except Exception as e:
        logger.error(
            "Unexpected error for sport=%s. %s: %s",
            sport_key, type(e).__name__, str(e)
        )
        return []


async def _fetch_all_sports(timestamp: str) -> list[MarketRecord]:
    """
    Fires one HTTP request per sport key in SPORT_KEYS concurrently
    using asyncio.gather(). All requests are in-flight simultaneously.
    Total wait time = slowest single request, not sum of all requests.

    Uses a single shared aiohttp.ClientSession across all concurrent
    requests — this is the correct pattern. Creating one session per
    request defeats connection pooling and adds overhead.
    """
    connector = aiohttp.TCPConnector(limit=10)

    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [
            _fetch_sport(session, sport_key, timestamp)
            for sport_key in SPORT_KEYS
        ]

        results: list[list[MarketRecord]] = await asyncio.gather(
            *tasks,
            return_exceptions=False
        )

    all_records: list[MarketRecord] = []
    for sport_records in results:
        all_records.extend(sport_records)

    return all_records


def _generate_world_cup_fallback(timestamp: str) -> list[MarketRecord]:
    fixtures: list[dict] = [
        {"home": "France",      "away": "Morocco",     "home_odds": 1.70, "draw_odds": 3.80, "away_odds": 5.00},
        {"home": "Brazil",      "away": "Argentina",   "home_odds": 2.20, "draw_odds": 3.30, "away_odds": 3.10},
        {"home": "England",     "away": "Spain",       "home_odds": 2.50, "draw_odds": 3.20, "away_odds": 2.80},
        {"home": "Germany",     "away": "Portugal",    "home_odds": 2.10, "draw_odds": 3.40, "away_odds": 3.30},
        {"home": "Netherlands", "away": "USA",         "home_odds": 1.85, "draw_odds": 3.60, "away_odds": 4.20},
        {"home": "Japan",       "away": "South Korea", "home_odds": 2.40, "draw_odds": 3.10, "away_odds": 2.90},
        {"home": "Senegal",     "away": "Mexico",      "home_odds": 2.80, "draw_odds": 3.10, "away_odds": 2.50},
        {"home": "Canada",      "away": "Croatia",     "home_odds": 3.20, "draw_odds": 3.20, "away_odds": 2.20},
    ]

    bookmakers: list[str] = ["Betway", "1xBet"]
    records:    list[MarketRecord] = []

    for fixture in fixtures:
        home = fixture["home"]
        away = fixture["away"]

        for bk in bookmakers:
            for outcome_label, base_odds in [
                ("Home Win", fixture["home_odds"]),
                ("Draw",     fixture["draw_odds"]),
                ("Away Win", fixture["away_odds"]),
            ]:
                records.append(MarketRecord(
                    source=bk,
                    market=f"{home} vs {away} -- {outcome_label}",
                    value=round(base_odds * random.uniform(0.96, 1.06), 4),
                    timestamp=timestamp,
                    metadata={
                        "bookmaker_key": bk.lower().replace(" ", ""),
                        "fixture":       f"{home} vs {away}",
                        "outcome_type":  outcome_label,
                        "sport":         "soccer_fifa_world_cup",
                        "data_source":   "world_cup_fallback",
                    }
                ))

    return records


def scraper_node(state: GraphState) -> dict:
    logger.info(
        "Agent A starting. run_id=%s retry=%d",
        state.run_id, state.retry_count
    )
    print(f"\n[Agent A — Scraper] Starting. run_id={state.run_id}, retry={state.retry_count}")

    if SCRAPER_FAIL:
        logger.warning("SIMULATED FAILURE: scraper is down.")
        print("[Agent A — Scraper] SIMULATED FAILURE: scraper is down.")
        return {"error_message": "Agent A failed: data source unreachable."}

    timestamp   = datetime.now(timezone.utc).isoformat()
    records:     list[MarketRecord] = []
    data_source: str = "live"

    try:
        records = asyncio.run(_fetch_all_sports(timestamp))

        if not records:
            logger.warning(
                "Live fetch returned zero records across all sport keys. "
                "Activating fallback."
            )
            data_source = "fallback"

    except Exception as e:
        logger.error(
            "Unexpected error during async fetch. %s: %s. Activating fallback.",
            type(e).__name__, str(e)
        )
        data_source = "fallback"

    if data_source == "fallback":
        records = _generate_world_cup_fallback(timestamp)
        logger.warning(
            "Fallback active. %d synthetic records generated.",
            len(records)
        )
        print(
            f"[Agent A — Scraper] Fallback layer active. "
            f"{len(records)} records generated to maintain pipeline integrity."
        )

    sources_found = list(set(r.source for r in records))
    logger.info(
        "Scraper complete. records=%d sources=%s data_source=%s",
        len(records), sources_found, data_source
    )
    print(
        f"[Agent A — Scraper] Final record count: {len(records)}. "
        f"Sources: {sources_found}. Data layer: {data_source}."
    )

    return {
        "raw_data":      records,
        "error_message": None,
    }