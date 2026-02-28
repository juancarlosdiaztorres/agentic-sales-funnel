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
│  [company name] ──► Analyst (standalone)                        │
│  "Tengo reunión     runs own research, scores, generates pager  │
│   con Glovo"                                                     │
│                                                                  │
│  [company name] ──► Scout (single) ──► Analyst                  │
│  "Quiero señales    deep ICP signals   one-pager                 │
│   de Revolut"       first                                        │
└─────────────────────────────────────────────────────────────────┘
```

Both modes produce the same **account record** (schemas/account/v1.json).
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
**Input:** market(s), verticals, count, api_focus
**Output:** `outputs/market-maps/market_map_{market}_{date}.json`
→ Array of account records (bulk origin, volume filled, icp null)

Runs **once per market per quarter** (or per new market entry).
Produces a prioritized list of accounts by SMS volume potential.
Does NOT do per-company deep research — uses aggregated WebSearch + model knowledge.

Two sub-modes:
- **Country:** `market_map_spain_2026-02-28.json`
- **Global:** `market_map_global_2026-02-28.json` — pan-European/global accounts operating in ≥2 target markets

### Scout (Layer 2 — ICP Scoring)
**Input:** account record(s) from Market Mapper OR just a company name (standalone)
**Output:** enriched account record(s) with `icp.*` fields filled

Two modes:
- **Batch:** receives array from Market Mapper, scores all (filters score ≥ 6.0 by default)
- **Single:** receives one company name, runs full research + scoring

Scoring model (base 5.0):

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

### Analyst (Layer 3 — Account Intelligence)
**Input:** enriched account record OR just a company name (standalone Mode B)
**Output:** `outputs/one-pagers/{company}-{iso2}-{date}.md` + fills `outreach.*` in record

Two modes:
- **Mode A (standard):** receives full account record with icp.* filled → generates one-pager
- **Mode B (standalone):** receives just a company name → runs own research, scores, generates one-pager, fills all fields

One-pagers in **Spanish** for ES/LATAM accounts, **English** otherwise.

### Demo Builder (Layer 4 — Demo Generation)
**Input:** account record with outreach.one_pager_path filled
**Output:** `outputs/demos/{app}-{company}-{iso2}-{date}.html` + fills `demo.*` in record

### Orchestrator
**Input:** Scout parameters (same as Market Mapper)
**Output:** runs full bulk pipeline, creates market map + one-pager per qualifying lead

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

Each account record scores api_fit per API independently:

| API | Primary signal |
|-----|---------------|
| Number Verification | SMS OTP dependency in consumer auth flows |
| SIM Swap Detection | Fraud/ATO exposure + financial transaction risk |
| KYC Match | Regulated onboarding (AML, PSD2, MiCA, gaming) |
| Age Verification | Age-restricted content or services |
| Device Status | Connectivity/roaming signals needed |

---

## Output Structure

```
outputs/
├── market-maps/    # Market Mapper output — account lists by market
│   └── market_map_{market}_{YYYY-MM-DD}.json
├── accounts/       # Individual enriched account records (progressive)
│   └── {company-slug}-{iso2}.json
├── leads/          # Legacy Scout output (to be migrated)
│   └── leads_{market}_{YYYY-MM-DD}.json
├── one-pagers/     # Analyst output
│   └── {company-slug}-{iso2}-{YYYY-MM-DD}.md
└── demos/          # Demo Builder output
    └── {app-name}-{company-slug}-{iso2}-{YYYY-MM-DD}.html
```

`outputs/` is gitignored — all generated content stays local.

---

## schemas/

`schemas/account/v1.json` — JSON Schema for the account record.
All agents must read and conform to this schema when reading or writing account data.
`schemas/account/examples.json` — example records for both bulk and on-demand origins.
