# Agentic Sales Funnel

A multi-agent pipeline that automates B2B sales workflows — from lead research to personalized outreach documents and interactive demos. Built on Claude Code sub-agents.

## Pipeline

```
Scout ──► Analyst ──► Demo Builder
  │
  └── Orchestrator (runs the full pipeline end-to-end)
```

| Agent | Input | Output |
|-------|-------|--------|
| **Scout** | Market + industry parameters | Scored lead JSON with signals and sources |
| **Analyst** | Scout lead JSON *or* just a company name | Signal-backed one-pager (markdown) |
| **Demo Builder** | Lead JSON + one-pager | iOS-style PWA demo (single HTML file) |
| **Orchestrator** | Scout parameters | Full pipeline: leads JSON + one-pager per qualifying lead |

## Quick Start

### Requirements
- [Claude Code](https://claude.ai/code) (agents run inside Claude Code sessions)
- A [Serper.dev](https://serper.dev) API key for `scripts/scout_research.py` (free tier: 2,500 searches/month)

### Setup

```bash
git clone https://github.com/your-username/agentic-sales-funnel
cd agentic-sales-funnel
cp .env.example .env         # add your SERPER_API_KEY
pip install -r requirements.txt
```

Copy agent templates into Claude Code's agent directory:
```bash
mkdir -p .claude/agents
cp agents/*.md .claude/agents/
```
Then edit `.claude/agents/*.md` to replace `[YOUR PRODUCT]` placeholders with your product details.

### Run the pipeline (Claude Code)

**Full pipeline via Orchestrator:**
```
Run Orchestrator with:
- target_markets: ["Germany", "UK"]
- industries: ["fintech", "identity"]
- lead_count: 5
```

**Scout only:**
```
Run Scout with: target_markets: ["Brazil"], industries: ["gaming", "crypto"], lead_count: 10
```

**One-pager for a specific company (no Scout needed):**
```
Use the Analyst agent for company: Acme Corp, Spain, fintech
```

**Demo for a specific lead:**
```
Use Demo Builder with this lead: [paste Scout lead JSON]
```

### Pre-fetch signals without Claude (token-efficient path)

```bash
# Research specific companies (recommended)
python3 scripts/scout_research.py \
  --companies Wallapop Bit2Me "Job and Talent" \
  --markets Spain \
  --api-focus number_verification sim_swap

# Discovery mode (finds company names automatically — noisier)
python3 scripts/scout_research.py \
  --markets Spain \
  --industries fintech neobanks gaming \
  --candidates 15
```

Then in Claude Code:
```
Score and structure these pre-researched companies: [paste JSON from outputs/leads/research_*.json]
```

See [docs/token-efficiency.md](docs/token-efficiency.md) for the full comparison.

## Repo Structure

```
.
├── agents/                  # Sanitized agent templates (copy to .claude/agents/)
│   ├── scout.md
│   ├── analyst.md
│   ├── orchestrator.md
│   └── demo-builder.md
├── scripts/
│   ├── scout_research.py    # Pre-fetch signals via Serper (no Claude API key needed)
│   └── scout.py             # Full pipeline via Anthropic API (requires API key)
├── docs/
│   ├── architecture.md      # System design and agent internals
│   ├── agents.md            # How to configure and adapt agents
│   └── token-efficiency.md  # Cheap vs expensive execution paths
├── .env.example
├── requirements.txt
└── outputs/                 # Gitignored — stays local
    ├── leads/
    ├── one-pagers/
    └── demos/
```

## How It Works

### 1. Scout — Lead research and scoring

Scout runs two sub-steps:
- **Discovery:** searches for companies matching your ICP in the target market
- **Scoring:** runs 4–6 signal queries per company (fraud/ATO exposure, SMS OTP dependency, auth stack, hiring signals, regulatory pressure) and scores on a 0–10 scale

Core ICP criterion: **the company must use SMS-OTP in their own authentication flows** (login, onboarding, transaction auth). Companies are excluded if they have no consumer auth, no phone-number-based identity, or are already covered by enterprise channels.

### 2. Analyst — One-pager generation

Analyst takes a single lead and produces a one-pager structured for a first meeting pre-read:
- Company snapshot and problem statement
- Specific API solution with integration hypothesis
- Why now (regulatory, incident, hiring signals)
- Quantified benefits with annual API call volume estimate
- Objection handling

Every data point cites its source inline: `([Publisher, Date](URL))`.

**Standalone mode:** Analyst also works with just a company name — it runs its own research, scores the lead, and generates the one-pager without needing Scout to have run first.

### 3. Demo Builder — Mobile PWA demo

Demo Builder generates a single self-contained HTML file that works as an iOS-style PWA:
- Scrapes the company's visual identity (colors, fonts)
- Creates a fictional app name per vertical
- Mocks 2–3 key user flows with the target API integration highlighted
- Designed for Safari "Add to Home Screen" on iPhone

## Design Principles

- **No fabrication** — every claim in Scout output and one-pagers traces back to a real, cited source
- **Inline citations** — every data point in Analyst output includes `([Publisher, Date](URL))`
- **Two classification systems** — Score Tier (A/B/C = lead quality) and Account Tier (1/2/3 = company size) are always kept separate
- **Outputs never overwrite** — all filenames include a `YYYY-MM-DD` date suffix
- **Dynamic inputs** — no hardcoded targets; all parameters are runtime inputs

## Documentation

- [Architecture](docs/architecture.md) — system design, agent internals, scoring model
- [Agent Configuration](docs/agents.md) — how to configure, adapt, and invoke agents
- [Token Efficiency](docs/token-efficiency.md) — full vs pre-fetch execution paths compared

## Stack

- [Claude Code](https://claude.ai/code) — agent runtime
- [Serper.dev](https://serper.dev) — Google Search API for `scout_research.py`
- Vanilla HTML/CSS/JS — demo output (no build step, single file)
