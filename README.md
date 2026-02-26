# Agentic Sales Funnel

A multi-agent pipeline that automates B2B sales workflows — from lead research to personalized outreach documents and interactive demos.

## Architecture

```
Scout → Analyst → Demo Builder
          ↑
      Orchestrator (chains all three)
```

| Agent | Input | Output |
|-------|-------|--------|
| **Scout** | Market + industry parameters | Structured lead JSON with fit scores and signals |
| **Analyst** | Single lead JSON | Personalized one-pager (markdown) |
| **Demo Builder** | Lead JSON + one-pager | Mobile PWA demo app (single HTML file) |
| **Orchestrator** | Scout parameters | Runs full pipeline end-to-end |

## How It Works

1. **Scout** researches companies matching your ICP, scores them by fit, and returns structured JSON with signals, sources, and outreach angles.
2. **Analyst** takes a single lead and generates a signal-backed, persona-targeted one-pager ready to send before a first meeting.
3. **Demo Builder** scrapes the company's visual identity and generates a mobile PWA demo that mocks your product's integration into their flows.
4. **Orchestrator** chains the three agents: runs Scout, filters by score tier, and invokes Analyst (and optionally Demo Builder) for each qualifying lead.

## Output Structure

```
outputs/
├── leads/          # Scout JSON output per run
├── one-pagers/     # Analyst markdown one-pagers
└── demos/          # Demo Builder PWA HTML files
```

> `outputs/` is gitignored — all generated content stays local.

## Agent Configuration

Agents live in `.claude/agents/`. Each is a markdown file with a YAML frontmatter (`name`, `description`, `tools`) and a system prompt.

To adapt to your use case, edit:
- `scout.md` — define your ICP, scoring model, and search strategy
- `analyst.md` — define your one-pager structure and tone
- `demo-builder.md` — define your demo flows and visual identity scraping logic
- `orchestrator.md` — adjust score thresholds and pipeline logic

## Usage

Run from Claude Code. Example orchestrator invocation:

```
Run Orchestrator with:
- target_markets: ["Germany", "UK"]
- industries: ["fintech", "identity"]
- lead_count: 5
```

Or run agents individually:

```
Run Scout with target_markets: ["Brazil"], industries: ["gaming"], lead_count: 10
```

```
Use the Analyst agent with this lead: [paste Scout lead JSON]
```

## Design Principles

- **No fabrication** — every claim in Scout output and one-pagers traces back to a real source
- **Inline citations** — Analyst cites sources next to every data point
- **Separation of concerns** — Scout discovers, Analyst writes, Demo Builder visualizes
- **Dynamic inputs** — no hardcoded targets; parameters are always runtime inputs
- **Outputs never overwrite** — filenames include date suffix

## Stack

- [Claude Code](https://claude.ai/code) — agent runtime
- Claude Sonnet / Haiku — underlying models
- Vanilla HTML/CSS/JS — demo output (no build step)
