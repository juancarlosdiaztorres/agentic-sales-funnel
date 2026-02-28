# Agent Configuration

Agents live in `.claude/agents/` — one markdown file per agent. Each file has a YAML frontmatter block followed by a system prompt.

```
.claude/agents/
├── market-mapper.md   # Market intelligence — volume-ranked account lists
├── scout.md           # ICP scoring — enriches account records with icp.*
├── analyst.md         # One-pager generation per lead
├── orchestrator.md    # Chains full pipeline end-to-end
└── demo-builder.md    # iOS PWA demo generation
```

This directory is gitignored. The `agents/` directory at the repo root contains sanitized public templates.

## Frontmatter format

```yaml
---
name: AgentName
description: One-line description shown when Claude decides which agent to invoke.
             Be specific — Claude uses this to route requests.
tools: WebSearch, WebFetch   # comma-separated list
---
```

Available tools: `WebSearch`, `WebFetch`, `Read`, `Write`, `Bash`, `Glob`, `Grep`, `Task`

## How agents are invoked

**From Claude Code chat:**
```
Run Market Mapper for Spain, verticals: neobanks, gambling, api_focus: number_verification, sim_swap
Run Scout with these accounts: [paste market-map JSON]
Use the Analyst agent for company: Glovo, Spain
Run Orchestrator for Spain, verticals: fintech, neobanks, api_focus: number_verification
```

**As subagents (from Orchestrator):**
The Orchestrator chains Market Mapper → Scout → Analyst using the Task tool.

## Adapting agents to your use case

1. Copy the sanitized template from `agents/` into `.claude/agents/`
2. Replace `[YOUR PRODUCT]` placeholders with your product name and API descriptions
3. Update the scoring model in Scout with your ICP-specific signals
4. Update the volume estimation model in Market Mapper for your trigger events
5. Update the api_fit rules to match your APIs

## Key design decisions

**Market Mapper — volume-first:**
Market Mapper ranks accounts by realistic API call volume potential, not just headcount. Volume is API-specific: NV/SIM Swap are triggered at login events (DAU × logins × OTP rate), KYC/Age at onboarding (MAU × 5% monthly growth). This ensures the list is ranked by actual commercial potential.

**Market Mapper — global mode:**
When `market: "global"`, Market Mapper targets pan-regional companies operating in ≥ min_markets of the target markets (ES, DE, BR, GB). Volume is summed across all target markets the company operates in.

**Scout — two modes:**
- Batch (from Market Mapper): receives pre-filled account records, only enriches `icp.*` and refines `api_fit.*`. Does NOT overwrite `volume.*`.
- Single (standalone): receives just a company name, fills all fields in one pass.

**Scout — ICP focus:**
The ICP section is the most important part of Scout. Core criterion: *the company must use SMS-OTP in their own authentication flows*. Generic marketplaces or B2B-only companies without consumer auth are excluded.

**Analyst — inline citations:**
Every data point in the one-pager must cite its source inline: `([Publisher, Date](URL))`. This is enforced in the system prompt. The one-pager is a sales document — every claim must be defensible.

**Analyst — two modes:**
- Mode A (standard): receives full account record with `icp.*` filled → generates one-pager only
- Mode B (standalone): receives just a company name → runs own research, scores, generates one-pager, fills all fields

**Demo Builder — fictional app names:**
The demo generates a fictional app per vertical (neobank → Crest/Vault, CIAM → Nexus) to avoid using real company branding. The visual identity (colors, fonts) is scraped from the company's actual site.

## Outputs

| Agent | Output path | Format | Fields filled |
|-------|------------|--------|---------------|
| Market Mapper | `outputs/market-maps/market_map_{market}_{date}.json` | JSON + Markdown | `company`, `volume`, `api_fit` |
| Scout (batch) | `outputs/leads/leads_{market}_{date}.json` | JSON (account/v1 array) | `icp`, `api_tags`, `api_fit` refined |
| Scout (single) | `outputs/accounts/{slug}-{iso2}.json` | JSON (account/v1) | all fields |
| Analyst | `outputs/one-pagers/{company-slug}-{date}.md` | Markdown | `outreach.*` in record |
| Demo Builder | `outputs/demos/{app}-{company}-{iso2}-{date}.html` | Self-contained HTML | `demo.*` in record |

All filenames include a date suffix — outputs never overwrite.

## Shared data model

All agents read and write account records conforming to `schemas/account/v1.json`.

Records are enriched progressively — each agent fills its layer and leaves the rest null:

```
{id, company, volume, api_fit}   ← Market Mapper fills this
        +
{icp.score, icp.signals}         ← Scout adds this
        +
{outreach.one_pager_path}        ← Analyst adds this
        +
{demo.demo_path}                 ← Demo Builder adds this
```

The `meta.enrichments` array is an audit log — every agent appends an entry with `fields_added`.
