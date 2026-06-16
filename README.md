cat > README.md << 'EOF'
# Alpha Signals MAS — LangGraph Multi-Agent Intelligence System

A production-grade, local Multi-Agent System built with LangGraph that scrapes
live World Cup betting odds, detects market anomalies and arbitrage opportunities,
generates a styled PDF intelligence report, and broadcasts it to a private Telegram channel.

## Architecture
scraper -> analyst -> reporter -> auditor -> [HUMAN GATE] -> broadcaster

### Agents
- **Agent A (Scraper):** Fetches live odds from The-Odds-API (Betway, 1xBet, William Hill, Paddy Power)
- **Agent B (Analyst):** Detects anomalies, arbitrage opportunities, and Kelly Criterion value bets
- **Agent C (Reporter):** Compiles structured Markdown intelligence report
- **Agent D (Auditor):** Validates report against 9 structural rules with conditional re-routing
- **Agent E (Broadcaster):** Generates styled PDF and transmits via Telegram Bot API

## Stack
- Python 3.13 / LangGraph 0.2.55 / Pydantic v2
- The-Odds-API (live sports odds)
- fpdf2 (PDF generation)
- python-telegram-bot 20.7

## Usage

```bash
python run.py           # Value Sheet mode, human approval gate
python run.py --arb     # Arbitrage Alert Digest mode
python run.py --auto    # Auto-approve broadcast (for scheduled runs)
python stress_test.py   # Run full self-healing stress test suite
```

## Environment Variables
TELEGRAM_BOT_TOKEN=your_bot_token

TELEGRAM_CHANNEL_ID=@your_channel

ODDS_API_KEY=your_odds_api_key
