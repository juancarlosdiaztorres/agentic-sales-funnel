# Architecture

## System Overview

```
┌─────────────────────────────────────────────────────────┐
│                     Orchestrator                        │
│          (chains Scout → Analyst automatically)         │
└───────────────┬─────────────────────────────────────────┘
                │
      ┌─────────▼─────────┐
      │       Scout        │   Finds companies, scores fit,
      │  (discovery +      │   returns structured lead JSON
      │   scoring)         │
      └─────────┬──────────┘
                │  lead JSON (one per company)
      ┌─────────▼──────────┐
      │      Analyst        │   Generates one-pager per lead
      │  (one-pager gen)    │   with inline citations
      └─────────┬───────────┘
                │  markdown one-pager
      ┌─────────▼──────────┐
      │   Demo Builder      │   Scrapes visual identity,
      │  (PWA demo gen)     │   generates iOS PWA demo
      └────────────────────┘
```

## Agents

### Scout
**Input:** target markets, industries, API focus, lead count
**Output:** `outputs/leads/leads_{market}_{date}.json`

Runs in two sub-steps:
1. **Discovery** — WebSearch to identify candidate companies matching ICP
2. **Research + scoring** — signal queries per company (fraud/ATO, SMS OTP, auth stack, hiring, regulatory), then scores on a 0–10 scale

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

### Analyst
**Input:** Scout lead JSON (or just a company name — standalone mode)
**Output:** `outputs/one-pagers/{company}_{date}.md`

Two modes:
- **Mode A (standard):** receives full Scout JSON, generates one-pager using provided signals and fills any research gaps
- **Mode B (standalone):** receives just a company name, runs its own research, scores the lead, and generates the one-pager

### Orchestrator
**Input:** Scout parameters (same as Scout)
**Output:** runs full pipeline, creates leads JSON + one-pager per qualifying lead

Filters Score Tier A+B (score ≥ 6.0) before invoking Analyst.

### Demo Builder
**Input:** company name + one-pager (or Scout lead JSON)
**Output:** `outputs/demos/{fictional-app}-{company}-{date}.html`

- Scrapes company visual identity (colors, fonts, UI style)
- Generates a fictional app name per vertical
- Produces self-contained iOS-style PWA (single HTML file, 390px, Safari Add to Home Screen)

## Score Tiers vs Account Tiers

Two separate classification systems — **never mix them**:

| System | Name | Values | Meaning |
|--------|------|--------|---------|
| Score Tier | Lead quality | A / B / C | A ≥ 8.0, B 6.0–7.9, C < 6.0 |
| Account Tier | Company size | 1 / 2 / 3 | 1 = large incumbents (exclude), 2 = mid-market (primary), 3 = smaller scale-ups (secondary) |

Account Tier 1 companies are excluded because they are likely already clients via enterprise channels.

## Output Structure

```
outputs/
├── leads/          # Scout JSON output per run
│   └── leads_{market}_{YYYY-MM-DD}.json
├── one-pagers/     # Analyst markdown one-pagers
│   └── {company-slug}-{YYYY-MM-DD}.md
└── demos/          # Demo Builder PWA HTML files
    └── {fictional-app}-{company}-{YYYY-MM-DD}.html
```

`outputs/` is gitignored — all generated content stays local.
