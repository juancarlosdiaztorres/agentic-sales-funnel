# Architecture

## Pipeline Overview

Two modes share the same data model and agents. Choose based on context:

```
┌─────────────────────────────────────────────────────────────────┐
│  BULK MODE  (run once per market/API — generates account list)  │
│                                                                  │
│  Market Mapper ──► Scout (batch) ──► Analyst ──► Demo Builder   │
│  "Top 50 Spain     "Score top N    "One-pager   "PWA demo       │
│   for Num.Verif."   for ICP fit"    per lead"    per lead"      │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  ON-DEMAND MODE  (triggered by a specific company or meeting)   │
│                                                                  │
│  [company name] ──► Analyst (standalone Mode B)                 │
│  "Tengo reunión     runs own research, scores, generates pager  │
│   con Glovo"                                                     │
│                                                                  │
│  [company name] ──► Scout (single) ──► Analyst                  │
│  "Quiero señales    deep ICP signals   one-pager                 │
│   de Revolut"       first                                        │
└─────────────────────────────────────────────────────────────────┘
```

Both modes produce the same **account record** (`schemas/account/v1.json`).
The record starts sparse and is enriched progressively by each agent.

---

## The Account Record (shared data model)

```
{id, company, volume, api_fit}   ← Market Mapper fills this
        +
{icp.score, icp.signals}         ← Scout adds this
        +
{outreach.one_pager_path}        ← Analyst adds this
        +
{demo.demo_path}                 ← Demo Builder adds this
```

A record created on-demand (Analyst standalone) fills all fields in one pass.
A record created by Market Mapper fills only the first layer; Scout enriches it later.

---

## Agents

### Market Mapper (Layer 1 — Market Intelligence)
**Input:** market(s), verticals, api_focus, count, tier_filter
**Output:** `outputs/market-maps/market_map_{market}_{date}.json` + `.md`
→ Array of account records (bulk origin, volume filled, icp null)

Runs **once per market per quarter** (or per new market entry).
Produces a prioritized list of accounts by API call volume potential.
Uses aggregated WebSearch (max 15 calls total — by vertical, not per-company).
Does NOT do per-company deep research — uses model knowledge for well-known companies.

**Two sub-modes:**
- **Country:** `market_map_spain_2026-02-28.json`
- **Global:** `market_map_global_2026-02-28.json` — pan-European/global accounts operating in ≥ min_markets target markets (ES, DE, BR, GB). Volume aggregated across all target markets.

**Volume estimation model (API-specific):**
```
Number Verification + SIM Swap (login-triggered):
  DAU         = MAU × 0.30  (consumer; gambling ×0.50; banking ×0.20)
  logins/day  = DAU × 1.2
  SMS OTP/day = logins × 0.30
  Annual NV   = SMS_OTP/day × 365
  Annual SS   = risky_txns/day × 365

KYC Match + Age Verification (onboarding-triggered):
  onboardings/month = MAU × 0.05
  Annual KYC        = onboardings/month × 12

Device Status (session-triggered):
  Annual = DAU × avg_sessions × 365
```

### Scout (Layer 2 — ICP Scoring)
**Input:** account record(s) from Market Mapper OR just a company name (standalone)
**Output:** enriched account record(s) with `icp.*` fields filled, `api_tags` added

**Two modes:**
- **Batch:** receives array from Market Mapper, enriches `icp.*` only (does NOT overwrite `volume.*`), filters score ≥ 6.0 — saves to `outputs/leads/leads_{market}_{date}.json`
- **Single:** receives one company name, runs full research + scoring — saves to `outputs/accounts/{slug}-{iso2}.json`

**Scoring model (base 5.0):**

| Signal | Adjustment |
|--------|-----------|
| SMS OTP dependency confirmed | +2.0 |
| Public fraud / ATO incident | +2.0 |
| International expansion | +1.5 |
| Fraud/identity hiring | +1.0 |
| Regulated financial activity | +1.0 |
| Mobile-first, high-DAU | +1.0 |
| Passkeys/FIDO mentions | +0.5 |
| CIAM partner (Okta/Auth0/Ping) | +0.5 |
| Already integrated with your product APIs | -2.0 |
| B2B-only, no consumer auth | -1.5 |
| No mobile app | -1.0 |
| No phone-number identity | -1.0 |

**api_tags:** convenience field derived from `api_fit` — array of APIs where `relevant: true`. Enables fast filtering without parsing full `api_fit`.

### Analyst (Layer 3 — Account Intelligence)
**Input:** enriched account record OR just a company name (standalone Mode B)
**Output:** `outputs/one-pagers/{company-slug}-{date}.md` + fills `outreach.*` in record

**Two modes:**
- **Mode A (standard):** receives full account record with `icp.*` filled → generates one-pager
- **Mode B (standalone):** receives just a company name → runs own research, scores, generates one-pager, fills all fields

One-pagers in **Spanish** for ES/LATAM accounts, **English** otherwise.
Every claim cites its source inline: `([Publisher, Date](URL))`.

### Demo Builder (Layer 4 — Demo Generation)
**Input:** account record with `outreach.one_pager_path` filled
**Output:** `outputs/demos/{app}-{company}-{iso2}-{date}.html` + fills `demo.*` in record

Generates a self-contained iOS-style PWA HTML file:
- Fictional app name per vertical (neobank → Crest/Vault, CIAM → Nexus)
- Visual identity scraped from company site
- 2–3 key user flows with API integration highlighted
- Safari "Add to Home Screen" compatible

### Orchestrator
**Input:** market + verticals (bulk mode) OR company name (on-demand mode)
**Output:** full pipeline output — market map + leads JSON + one-pager per qualifying lead

**Bulk mode:** chains Market Mapper → Scout batch → Analyst
**On-demand mode:** runs Analyst standalone (Mode B)
Filters Score Tier A+B (score ≥ 6.0) before invoking Analyst.

---

## Score Tiers vs Account Tiers

Two separate classification systems — **never mix them**:

| System | Name | Values | Meaning |
|--------|------|--------|---------|
| Score Tier | Lead quality | A / B / C | A ≥ 8.0, B 6.0–7.9, C < 6.0 |
| Account Tier | Company size | 1 / 2 / 3 | 1 = large incumbents (strategic, not pipeline), 2 = mid-market (primary), 3 = smaller scale-ups (secondary) |

Account Tier 1 companies are excluded from the standard pipeline. They are handled as strategic accounts through enterprise channels.

---

## API Focus Dimensions

Each account record scores `api_fit` per API independently:

| API | Primary signal | Volume trigger |
|-----|---------------|----------------|
| Number Verification | SMS OTP dependency in consumer auth flows | Login events |
| SIM Swap Detection | Fraud/ATO exposure + financial transaction risk | High-value transactions |
| KYC Match | Regulated onboarding (AML, PSD2, MiCA, gaming) | Onboarding events |
| Age Verification | Age-restricted content or services | Onboarding events |
| Device Status | Connectivity/roaming signals needed | Session events |

---

## Scripts

### scripts/discovery.py
Zero-token company name discovery. Extracts names from Crunchbase URL slugs via Serper.
- Input: markets, industries, count
- Output: `outputs/leads/discovery_{market}_{date}.json`
- 0 Claude tokens — pure Serper + Python slug parsing

### scripts/scout_research.py
Pre-fetches signal data per company via Serper + requests (0 Claude tokens).
Saves compact JSON for Scout to score in a single call with reduced context.
- Input: `--companies` list OR `--markets` + `--industries` for discovery
- Output: `outputs/leads/research_{market}_{date}.json` or `research_custom_{companies}_{date}.json`

### scripts/scout.py
Full pipeline via Anthropic API (requires `ANTHROPIC_API_KEY`).
Runs discovery (Serper + Haiku), signal research (Serper), and scoring (Sonnet) in isolated per-company calls.
- No context accumulation across companies
- Same depth as Claude Code Scout, ~10x cheaper for large runs
- Output: `outputs/leads/leads_{market}_{date}.json`

---

## Output Structure

```
outputs/
├── market-maps/    # Market Mapper output — account lists by market
│   ├── market_map_{market}_{YYYY-MM-DD}.json
│   └── market_map_{market}_{YYYY-MM-DD}.md
├── accounts/       # Individual enriched account records (progressive enrichment)
│   └── {company-slug}-{iso2}.json
├── leads/          # Scout batch output — scored account arrays
│   ├── leads_{market}_{YYYY-MM-DD}.json
│   └── discovery_{market}_{YYYY-MM-DD}.json
├── one-pagers/     # Analyst output
│   └── {company-slug}-{YYYY-MM-DD}.md
└── demos/          # Demo Builder output
    └── {app-name}-{company-slug}-{iso2}-{YYYY-MM-DD}.html
```

`outputs/` is gitignored — all generated content stays local.

---

## schemas/

`schemas/account/v1.json` — JSON Schema for the account record.
All agents must read and conform to this schema when reading or writing account data.

`schemas/account/examples.json` — example records for both bulk and on-demand origins:
- `bulk_after_market_mapper` — volume filled, icp null (Market Mapper output, Scout not yet run)
- `on_demand_fully_enriched` — all fields filled in one pass (Analyst standalone Mode B)
