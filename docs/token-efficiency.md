# Token Efficiency

## The Problem

Running Scout for 10 leads in a single Claude Code session accumulates context: every search result, every page fetch, every intermediate step consumes tokens. For 10 leads × 4 signal queries × 4 results each = 160 search results in context before scoring begins.

The new pipeline introduces two upstream stages (Market Mapper + discovery.py) that reduce what Scout needs to do — or skip it entirely for well-known companies.

---

## Three Paths

### Path 1 — Market Mapper (cheapest Claude path)

Market Mapper uses aggregated queries — 15 WebSearch calls total across all companies in a vertical, not per-company. It uses model knowledge for well-known companies and skips WebFetch entirely.

```
Market Mapper (15 WebSearch total)
  ├── "top neobanks Spain users 2024 2025"  → 5 companies at once
  ├── "gambling apps Spain MAU 2024"        → 5 more companies
  └── "marketplace apps Spain funding"      → 5 more
          ↓
  Account records with volume.* filled (icp.* null)
          ↓
Scout batch (4 queries × N companies)
  └── Enriches icp.* only — no volume re-research
```

Best for: quarterly market scans, entering a new market, building the initial lead list.

### Path 2 — discovery.py + Scout (zero-token discovery)

`scripts/discovery.py` extracts company names from Crunchbase URL slugs via Serper — 0 Claude tokens for discovery. You then pass the company list to Scout for ICP scoring.

```
scripts/discovery.py               # 0 Claude tokens
  ├── Serper queries by vertical
  └── Slug extraction (Crunchbase, Dealroom, etc.)
          ↓
  Company name list (JSON)
          ↓
Scout (4 queries × N companies)
  └── Full ICP research + scoring per company
```

Best for: when you want zero-cost discovery but full Scout depth on each company.

### Path 3 — scout_research.py + Scout scoring (Serper pre-fetch)

`scripts/scout_research.py` runs all signal queries via Serper and saves compact JSON. Scout then scores only — no signal searches needed.

```
scripts/scout_research.py          # 0 Claude tokens
  ├── Serper searches × 4–7 per company
  ├── Page fetches × 2 per company
  └── Saves compact JSON
          ↓
Claude Code session
  └── Scout (receives pre-fetched JSON)
        └── Score + structure only  # ~50% fewer tokens
```

Best for: known company lists, repeat runs on same market.

---

## Comparison

| | Market Mapper | discovery.py + Scout | scout_research.py + Scout |
|---|---|---|---|
| Discovery method | Aggregated WebSearch | Crunchbase slug extraction | Serper queries |
| Claude tokens (discovery) | Low (aggregated) | **Zero** | **Zero** |
| Claude tokens (scoring) | None (Market Mapper only) | Normal Scout | Reduced (~50%) |
| Volume estimates | Yes (API-specific) | No | No |
| ICP signals | First-pass only | Full Scout depth | Full Scout depth |
| Best for | New market scans | Targeted lists | Repeat runs |

---

## Recommended Workflows

### New market entry
```
Run Market Mapper for [market], verticals: [list], api_focus: [list]
```
Then:
```
Run Scout batch on these accounts: [paste market-map JSON]
```

### One-off meeting prep
```
Use the Analyst agent for company: [name], [market]
```
Analyst runs its own research in standalone mode — no Market Mapper or Scout needed.

### Token-efficient batch (known companies)
```bash
python3 scripts/scout_research.py \
  --companies "Wallapop" "Bnext" "SeQura" \
  --markets Spain \
  --api-focus number_verification sim_swap
```
Then in Claude Code:
```
Score and structure these pre-researched companies: [paste JSON from outputs/leads/research_*.json]
```

### Zero-token company name discovery
```bash
python3 scripts/discovery.py \
  --markets Spain \
  --industries fintech neobanks gambling marketplace gig \
  --count 30
```
Then in Claude Code:
```
Run Scout with these companies: [paste discovery JSON]
```

---

## Token Efficiency Rules Built Into Scout

Scout's system prompt enforces these rules automatically:
- Max 4 WebSearch queries per lead (priority: fraud_or_ato → sms_otp_dependency → auth_stack → hiring)
- Prefer search snippets over WebFetch when snippet supports the claim
- Max 2 WebFetch calls per lead
- Never WebFetch a homepage
- Only WebFetch allowed paths: `/security`, `/developers`, `/docs`, `/blog`, `/careers`, `/press`

In batch mode, Scout skips volume research entirely (already filled by Market Mapper) — only runs ICP signal queries.
