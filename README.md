# Tasman Sales Bot

Conversational sales bot (LangGraph) for the **TASMAN** hotel group (6 hotels),
implementing the Sales Direction *2026 Sales Flow*: **the bot quotes instantly,
the human negotiates and closes**. Current channels: **Telegram** (long polling)
and console; WhatsApp Cloud API plugs in later on top of the same graph.
LEADS/CRM storage is switchable between local Excel and **Google Sheets**.

## Implemented flows

- **A · Individuals (1–4 rooms)** — fully autonomous: multi-hotel fact sheets,
  availability and rates via Cloudbeds (mock), proposal with payment link and
  PDF, lead registration per hotel, Cloudbeds close (Closed Won),
  post-confirmation (requirements + upsells) and human escalation.
- **B · Groups (5+ rooms or 15+ people)** — brief → OCC from Cloudbeds →
  discount table (<50%: 20% · 51–70%: 15% · 71–90%: 10%) → **human validation
  in console** (approve / adjust discount / reject) → delivery + LEADS GRUPOS
  TASMAN + Slack #grupos (15+ rooms notifies Sales Direction). Closed Won
  creates the room block in Cloudbeds and the sales-rep task.
- **C · VIPs** — assisted CLI for the advisor: `python -m src.cli.vip_lead`.
- **D · Events without rooms** — brief + hotel supervision notification
  (a human quotes) + extra catalog of tours/experiences.
- **Automations** — 1/3/5-day follow-ups and reports (Mon/Thu KPIs, weekly
  executive, per-hotel operational) as on-demand jobs.

## Architecture

```
src/
├── main.py                     # Console chat (client + advisor validation)
├── channels/telegram_runner.py # Telegram channel: 1 chat = 1 graph thread
├── config/settings.py          # MXN, 16% VAT, hotels, group policy, llm_factory
├── orchestrator/graph.py       # LangGraph: chat ↔ tools + 3 intercepted pipelines
├── agents/concierge_agent.py   # Multi-hotel sales agent prompt
├── nodes/                      # chat, confirmation, groups (interrupt), fan-out, summary
├── tools/tasman_tools.py       # 12 LLM tools (service wrappers)
├── services/                   # Pure logic, no LLM (testable)
│   ├── cloudbeds_service.py    #   mock PMS: availability, OCC, reservations, payments
│   ├── pricing_service.py      #   MXN quotes + OCC→discount table
│   ├── store.py                #   switchable storage: local Excel ⇄ Google Sheets
│   ├── leads_service.py        #   per-hotel LEADS + LEADS GRUPOS TASMAN
│   ├── crm_service.py          #   CRM TASMAN (B2B/B2C)
│   ├── followup_service.py     #   1/3/5-day cadence
│   ├── reporting_service.py    #   KPIs, executive, operational
│   ├── slack_service.py        #   #grupos, HQ, direction, per-hotel operational
│   └── pdf_service.py          #   per-hotel PDF quote
├── jobs/                       # run_followups · run_reports
├── cli/vip_lead.py             # Flow C (advisor)
└── data/
    ├── generate_tasman_data.py # Generates fact sheets + Cloudbeds seed + working files
    └── hotels/*.xlsx           # Editable fact sheet per hotel
```

Working files (Excel, in `output/`): `leads/<HOTEL>.xlsx` × 6,
`leads/LEADS GRUPOS TASMAN.xlsx`, `CRM TASMAN.xlsx`, `cloudbeds_pms.xlsx`
(PMS mock) and `cotizaciones/*.pdf`. With `STORAGE_BACKEND=sheets`, LEADS and
CRM live in Google Sheets instead.

Principles: **deterministic first** (only the conversation and the creative
Slack message use the LLM; prices, discounts, records and PDFs are plain code),
swappable LLM via `llm_factory` (`.env`), and human validation with LangGraph's
`interrupt()`.

## Setup

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # DEEPSEEK_API_KEY, TELEGRAM_BOT_TOKEN (+ optional Slack/Sheets)
python -m src.data.generate_tasman_data
```

## Usage

```bash
python -m src.channels.telegram_runner # Telegram bot (requires TELEGRAM_BOT_TOKEN)
python -m src.main                     # console chat (+ advisor console on groups)
python -m src.cli.vip_lead             # flow C: VIP capture by the advisor
python -m src.jobs.run_followups       # pending follow-ups (1/3/5 days)
python -m src.jobs.run_reports todos   # kpis | directivo | operativo | todos
```

Without `SLACK_WEBHOOK_URL` (or if the webhook fails) notifications are printed
to the console. Note: an incoming webhook posts to one fixed channel; the
per-audience channels get split once the client creates the real webhooks.

## Google Sheets as LEADS/CRM storage

1. In [Google Cloud Console](https://console.cloud.google.com): create a
   project, enable the **Google Sheets API** and create a **Service Account**
   with a JSON key.
2. Save the key as `service-account.json` in the project root.
3. Create an empty Google Sheet and share it (**Editor**) with the service
   account email (`...@...iam.gserviceaccount.com`).
4. In `.env`: `STORAGE_BACKEND=sheets` and `GOOGLE_SHEET_ID=<ID from the URL>`.

The tabs (`CRM_B2B`, `CRM_B2C`, `LEADS_GRUPOS`, `LEADS_<hotel>`) are created
automatically the first time the bot writes.

## Tests

```bash
python -m tests.smoke_test      # deterministic pipeline, no API key
python -m tests.e2e_chat_test   # real conversation: full flows A and B
```
