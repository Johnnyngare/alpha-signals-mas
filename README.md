# Alpha Signals MAS — LangGraph Multi-Agent Intelligence System

A production-grade Multi-Agent System built with LangGraph that ingests live 2026 FIFA World Cup betting odds, detects market anomalies and arbitrage opportunities, applies Kelly Criterion stake sizing, compiles a styled PDF intelligence report, and broadcasts it to a private Telegram channel — with a human-in-the-loop approval gate before every transmission.

---

## System Architecture
Agent A          Agent B          Agent C          Agent D

Scraper    →    Analyst    →    Reporter    →    Auditor

│

┌──────────┴──────────┐

│                     │

PASS                   FAIL

│                     │

[HUMAN GATE]         Re-route to

│             broken agent

Agent E                (self-heal)

Broadcaster

│

END

### Agent Responsibilities

| Agent | Role | Key Output |
|-------|------|------------|
| A — Scraper | Fetches live odds from 4 bookmakers via The-Odds-API | `raw_data: list[MarketRecord]` |
| B — Analyst | Detects anomalies, arb windows, Kelly value bets | `analysis: AnalysisResult` |
| C — Reporter | Compiles structured Markdown intelligence report | `report_markdown: str` |
| D — Auditor | Validates against 9 structural rules, routes failures | `audit_result: AuditResult` |
| E — Broadcaster | Builds styled PDF, transmits via Telegram Bot API | `broadcast_result: str` |

---

## Key Features

- **Live data ingestion** — Real-time odds from Betway, 1xBet, William Hill, Paddy Power
- **Arbitrage detection** — Scans implied probability margins across all bookmakers per fixture
- **Kelly Criterion sizing** — Outputs optimal bankroll fraction for each identified edge
- **Self-healing loop** — Agent D re-routes failed runs back to the broken agent automatically
- **Human-in-the-loop gate** — Pipeline pauses before broadcast, requires Y/N terminal approval
- **Subscription verification** — HMAC token registry gates access to the broadcast channel
- **PDF generation** — Styled multi-page report with tables, color-coded anomalies, and branding
- **Docker ready** — Multi-stage Dockerfile for clean containerized deployment
- **Scheduler** — Built-in cron and Python scheduler for automated interval runs

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| Agent orchestration | LangGraph 0.2.55 |
| State management | Pydantic v2 `BaseModel` with typed reducers |
| Language | Python 3.13 |
| Live odds feed | The-Odds-API v4 |
| PDF engine | fpdf2 with DejaVu Unicode fonts |
| Telegram delivery | python-telegram-bot 20.7 |
| Containerization | Docker (multi-stage build) |
| Scheduling | `schedule` library + cron |

---

## Setup

```bash
git clone https://github.com/YOUR_USERNAME/alpha-signals-mas.git
cd alpha-signals-mas

python -m venv venv
source venv/Scripts/activate  # Windows
# source venv/bin/activate    # Mac/Linux

pip install -r requirements.txt
```

Create a `.env` file in the project root:
TELEGRAM_BOT_TOKEN=your_bot_token

TELEGRAM_CHANNEL_ID=@your_channel

ODDS_API_KEY=your_odds_api_key

SUBSCRIBER_TOKEN=your_plaintext_token

SUBSCRIPTION_SALT=your_salt_value

---

## Usage

```bash
# Value Sheet mode — human approval gate before broadcast
python run.py

# Arbitrage Alert Digest mode
python run.py --arb

# Auto-approve for scheduled/unattended runs
python run.py --auto

# Run self-healing stress test suite (4 failure scenarios)
python stress_test.py

# Start the automated scheduler
python scheduler.py
```

---

## LangGraph State Design

All agents read from and write to a single shared `GraphState` (Pydantic v2 model). Nodes return partial dicts — only the keys they own. List fields use `operator.add` reducers for accumulation across retry runs. The auditor's `failed_agent` field drives conditional re-routing without any agent having direct knowledge of graph topology.

---

## Project Structure
├── agents/

│   ├── scraper.py       # Agent A — live odds ingestion + fallback

│   ├── analyst.py       # Agent B — arb detection + Kelly sizing

│   ├── reporter.py      # Agent C — report compiler

│   ├── auditor.py       # Agent D — guardrail + conditional router

│   └── broadcaster.py   # Agent E — PDF build + Telegram delivery

├── fonts/               # DejaVu Unicode TTF assets

├── state.py             # GraphState, sub-schemas, AnalysisMode enum

├── graph.py             # StateGraph topology + MemorySaver checkpointer

├── pdf_builder.py       # fpdf2 PDF layout engine

├── run.py               # Entry point with human-in-the-loop gate

├── stress_test.py       # Self-healing test suite (4 scenarios)

├── scheduler.py         # Automated interval runner

├── subscription.py      # HMAC token verification layer

├── Dockerfile           # Multi-stage production container

└── requirements.txt

---

## Stress Test Results

| Test | Failure Injected | Recovery | Retries | Failures Logged |
|------|-----------------|----------|---------|-----------------|
| 1 | Scraper down | RECOVERED | 2 | 3 |
| 2 | Analyst crash | RECOVERED | 2 | 3 |
| 3 | Reporter crash | RECOVERED | 2 | 1 |
| 4 | Permanent failure | TERMINATED (circuit breaker) | 3 | 9 |
