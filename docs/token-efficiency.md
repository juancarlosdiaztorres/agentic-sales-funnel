# Token Efficiency

## The Problem

Running Scout for 10 leads in a single Claude Code session accumulates context across all searches: every search result, every page fetch, every intermediate step consumes tokens. For 10 leads × 7 signal queries × 4 results each = 280 search results in context before scoring even begins.

## Two Paths

### Path A — Full Scout (high quality, higher cost)
```
Claude Code session
  └── Scout agent
        ├── WebSearch × N (discovery)
        ├── WebSearch × 7 per company (signals)
        ├── WebFetch × 2 per company (page content)
        └── Score + structure
```
All inside Claude. Context grows with every company. Best for: initial runs, unknown markets, when you need Scout's judgment on discovery.

### Path B — Python pre-fetch + Scout scoring (lower cost)
```
scripts/scout_research.py          # 0 Claude tokens
  ├── Serper searches × 7 per company
  ├── Page fetches × 2 per company
  └── Saves compact JSON

Claude Code session
  └── Scout agent (receives pre-fetched JSON)
        └── Score + structure only  # ~50% fewer tokens
```

Best for: known company lists, repeat runs on same market, when you want to control which companies get scored.

## scout_research.py Modes

### Mode A — Discovery (finds company names automatically)
```bash
python3 scripts/scout_research.py \
  --markets Spain \
  --industries fintech neobanks gaming \
  --candidates 15
```
Note: discovery without a language model is noisy. Use Mode B when possible.

### Mode B — Specific companies (skip discovery)
```bash
python3 scripts/scout_research.py \
  --companies Wallapop Bit2Me SeQura "Job and Talent" \
  --markets Spain
```
This is the reliable path. Use Scout for discovery first, then use `--companies` for targeted signal research.

## Recommended Workflow

1. **Run Scout once per market** to discover and score leads:
   ```
   Run Scout with: target_markets: ["Spain"], industries: [...], lead_count: 10
   ```

2. **Save the lead JSON** — it's your asset. Stored in `outputs/leads/`.

3. **For follow-up companies** (e.g., a prospect mentioned in a meeting), use Mode B:
   ```bash
   python3 scripts/scout_research.py --companies "Acme Corp" --markets Spain
   ```
   Then paste the output JSON into Scout for scoring.

4. **For one-pagers on known companies** (no Scout needed), use Analyst in standalone mode:
   ```
   Use the Analyst agent with: company name "Acme Corp", Spain, fintech
   ```

## Token Efficiency Rules in Scout

Scout's system prompt enforces these rules to limit token usage during its own research:
- Max 4 WebSearch queries per lead (priority order: fraud_or_ato → sms_otp_dependency → auth_stack → hiring)
- Prefer search snippets over WebFetch when snippet supports the claim
- Max 2 WebFetch calls per lead
- Never WebFetch a homepage
- Only WebFetch allowed paths: `/security`, `/developers`, `/docs`, `/blog`, `/careers`, `/press`
