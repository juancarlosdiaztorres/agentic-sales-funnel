# Agentic Sales Funnel

A multi-agent pipeline that automates B2B sales workflows — from market mapping to personalized outreach documents and interactive demos. Built on Claude Code sub-agents with a shared progressive-enrichment data model.

## Pipeline

```
Market Mapper ──► Scout (batch) ──► Analyst ──► Demo Builder
"Top 50 Spain     "Score top N    "One-pager   "PWA demo
 for Num.Verif."   for ICP fit"    per lead"    per lead"

[company name] ──► Analyst (standalone)
"Tengo reunión     runs own research + scoring + one-pager
 con Glovo"
```

| Agent | Input | Output | Fields filled |
|-------|-------|--------|---------------|
| **Market Mapper** | Market + verticals + api_focus | Account list ranked by API call volume | `company`, `volume`, `api_fit` |
| **Scout** | Account records (batch) or company name (single) | ICP-scored account records | `icp`, `api_tags` |
| **Analyst** | Account record or company name | Signal-backed one-pager (markdown) | `outreach` |
| **Demo Builder** | Account record + one-pager | iOS-style PWA demo (single HTML) | `demo` |
| **Orchestrator** | Market + verticals (bulk) or company name (on-demand) | Full pipeline output | all |

All agents read and write `schemas/account/v1.json` — a shared record enriched progressively by each layer.

## TL;DR — launch from zero

**Requirements:** [Claude Code](https://claude.ai/code) (Pro or Team plan) + [Serper.dev](https://serper.dev) API key (free tier: 2,500 searches/month)

```bash
# 1. Clone and install
git clone https://github.com/your-username/agentic-sales-funnel
cd agentic-sales-funnel
pip install -r requirements.txt

# 2. Configure
cp .env.example .env          # add SERPER_API_KEY (get one free at serper.dev)
mkdir -p .claude/agents
cp agents/*.md .claude/agents/
# Edit each .claude/agents/*.md — replace [YOUR PRODUCT] with your product name and API descriptions
```

**3. Run in a Claude Code chat session:**

```
# Fastest path — one-pager for a specific company (no pre-built lead list needed):
Use the Analyst agent for company: Revolut, UK, fintech

# Full pipeline — market scan → ICP scoring → one-pager per qualifying lead:
Run Orchestrator:
- markets: ["Spain", "Germany"]
- verticals: ["fintech", "neobanks", "gambling"]
- api_focus: ["number_verification", "sim_swap"]
- lead_count: 20
```

That's it. Outputs land in `outputs/` (gitignored). See [docs/token-efficiency.md](docs/token-efficiency.md) for the cheapest execution paths.

---

## Quick Start

### Requirements
- [Claude Code](https://claude.ai/code) — agent runtime (agents run inside Claude Code sessions)
- A [Serper.dev](https://serper.dev) API key for scripts (free tier: 2,500 searches/month)

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

**Full bulk pipeline:**
```
Run Orchestrator:
- markets: ["Germany", "UK"]
- verticals: ["fintech", "identity", "gaming"]
- api_focus: ["number_verification", "sim_swap"]
- lead_count: 20
```

**Market map only:**
```
Run Market Mapper for Germany, verticals: fintech neobanks, api_focus: number_verification sim_swap
```

**One-pager for a specific company (most common):**
```
Use the Analyst agent for company: Acme Corp, Germany, fintech
```

**Global accounts (multi-market):**
```
Run Market Mapper for global, verticals: neobanks fintech gig, api_focus: number_verification, min_markets: 2
```

**Score a pre-built company list:**
```
Run Scout batch with these accounts: [paste market-map JSON]
```

### Pre-fetch signals without Claude (token-efficient)

```bash
# Zero-token company name discovery
python3 scripts/discovery.py \
  --markets Germany \
  --industries fintech neobanks gaming \
  --count 30

# Research specific companies (recommended)
python3 scripts/scout_research.py \
  --companies "N26" "Trade Republic" "Nuri" \
  --markets Germany \
  --api-focus number_verification sim_swap

# Full pipeline via Anthropic API (no Claude Code needed)
python3 scripts/scout.py \
  --markets Germany \
  --industries fintech neobanks \
  --lead-count 10 \
  --min-score 6.0
```

See [docs/token-efficiency.md](docs/token-efficiency.md) for full path comparison.

## Repo Structure

```
.
├── agents/                  # Sanitized agent templates (copy to .claude/agents/)
│   ├── market-mapper.md
│   ├── scout.md
│   ├── analyst.md
│   ├── orchestrator.md
│   └── demo-builder.md
├── schemas/
│   └── account/
│       ├── v1.json          # Shared data model — all agents conform to this
│       └── examples.json    # Reference records (bulk + on-demand)
├── scripts/
│   ├── discovery.py         # Zero-token company name discovery via Crunchbase slugs
│   ├── scout_research.py    # Pre-fetch signals via Serper (no Claude API key)
│   └── scout.py             # Full pipeline via Anthropic API
├── docs/
│   ├── architecture.md      # System design, agent internals, volume estimation model
│   ├── agents.md            # How to configure and adapt agents
│   └── token-efficiency.md  # Cheap vs expensive execution paths
├── .env.example
├── requirements.txt
└── outputs/                 # Gitignored — stays local
    ├── market-maps/         # Market Mapper output (JSON + MD)
    ├── accounts/            # Individual enriched account records
    ├── leads/               # Scout batch output + discovery lists
    ├── one-pagers/          # Analyst output (Markdown)
    └── demos/               # Demo Builder output (HTML)
```

## How It Works

### 1. Market Mapper — Volume-ranked account lists

Market Mapper uses **aggregated WebSearch** (15 calls total across all companies in a vertical, not per-company) to build a ranked list of target accounts. It ranks by realistic API call volume potential — not just user count.

Volume is API-specific:
- **Number Verification / SIM Swap** — triggered at login events: `DAU × logins × OTP rate × 365`
- **KYC Match / Age Verification** — triggered at onboarding: `MAU × 5% growth × 12`
- **Device Status** — triggered at session events: `DAU × sessions × 365`

Two sub-modes: **country** (single market) and **global** (pan-regional, volume aggregated across all operating markets).

### 2. Scout — ICP scoring

Scout enriches account records with deep ICP signals found in public sources. Two modes:
- **Batch** (from Market Mapper): enriches `icp.*` only, filters to score ≥ 6.0, does NOT overwrite volume data
- **Single** (standalone): receives just a company name, runs full research + scoring in one pass

Core ICP criterion: the company must use SMS-OTP in their own authentication flows. Companies are excluded if they have no consumer auth, no phone-number-based identity, or are already covered by enterprise channels.

### 3. Analyst — One-pager generation

Analyst takes a single lead and produces a one-pager structured for a first meeting pre-read:
- Company snapshot and problem statement
- Specific API solution with integration hypothesis
- Why now — including regulatory context (SMS-OTP deprecation advisories, SIM swap surge stats, vertical-specific regulations: PSD2, DORA, MiCA, CCD2, gaming KYC)
- Business case / volumetrics — per-API call forecast table with explicit math (`logins/day × OTP rate × 365`), real SMS cost exposure (including A2P markup and retry storms — SMS is not 1:1)
- Customer benefits — UX (silent auth, no OTP friction), security (carrier-layer vs behavioral), transparency (deterministic Boolean, auditable), latency (<100ms vs 3-8s SMS), operational cost savings
- Personas and objection handling

Every data point cites its source inline: `([Publisher, Date](URL))`.

**Standalone mode (Mode B):** Analyst also works with just a company name — runs its own research, scores, and generates the one-pager without needing Market Mapper or Scout to have run first.

### 4. Demo Builder — Mobile PWA demo

Demo Builder generates a single self-contained HTML file that works as an iOS-style PWA:
- Fictional app name per vertical (neobank → Crest/Vault, CIAM → Nexus)
- Visual identity scraped from the company's actual site
- 2–3 key user flows with the target API integration highlighted
- Safari "Add to Home Screen" compatible

## Design Principles

- **Progressive enrichment** — same account record flows through all agents; each fills its layer and leaves the rest null
- **No fabrication** — every claim in Scout output and one-pagers traces back to a real, cited source
- **Volume-first ranking** — Market Mapper ranks by API call potential, not just headcount
- **Two-mode flexibility** — bulk (quarterly market scans) and on-demand (single company, immediate)
- **Outputs never overwrite** — all filenames include a `YYYY-MM-DD` date suffix
- **Dynamic inputs** — no hardcoded targets; all parameters are runtime inputs

## Documentation

- [Architecture](docs/architecture.md) — system design, agent internals, volume estimation model
- [Agent Configuration](docs/agents.md) — how to configure, adapt, and invoke agents
- [Token Efficiency](docs/token-efficiency.md) — cheap vs expensive execution paths compared

## Stack

- [Claude Code](https://claude.ai/code) — agent runtime
- [Serper.dev](https://serper.dev) — Google Search API for scripts
- Vanilla HTML/CSS/JS — demo output (no build step, single file)
