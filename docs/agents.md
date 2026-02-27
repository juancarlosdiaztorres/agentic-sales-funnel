# Agent Configuration

Agents live in `.claude/agents/` — one markdown file per agent. Each file has a YAML frontmatter block followed by a system prompt.

```
.claude/agents/
├── scout.md          # Lead research + scoring
├── analyst.md        # One-pager generation
├── orchestrator.md   # Chains Scout → Analyst
└── demo-builder.md   # iOS PWA demo generation
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

Available tools: `WebSearch`, `WebFetch`, `Read`, `Write`, `Bash`, `Glob`, `Grep`

## How agents are invoked

**From Claude Code chat:**
```
Run Scout with: target_markets: ["Germany"], industries: ["fintech"], lead_count: 5
Use the Analyst agent with this lead: [paste JSON]
Run Orchestrator with: target_markets: ["Brazil"], industries: ["gaming"], lead_count: 3
```

**As subagents (from orchestrators or other agents):**
Claude Code can invoke agents as subagents using the Task tool, including in background mode for parallel execution.

## Adapting agents to your use case

1. Copy the sanitized template from `agents/` into `.claude/agents/`
2. Replace `[YOUR PRODUCT]` placeholders with your product name and API descriptions
3. Update the scoring model with your ICP-specific signals
4. Update the output schema fields relevant to your use case

## Key design decisions

**Scout — ICP focus:**
The ICP section is the most important part of Scout. It defines what a good lead looks like. For Open Gateway APIs, the core criterion is: *the company must use SMS-OTP in their own authentication flows*. Generic marketplaces or B2B-only companies without consumer auth are excluded.

**Analyst — inline citations:**
Every data point in the one-pager must cite its source inline: `([Publisher, Date](URL))`. This is enforced in the system prompt. The one-pager is a sales document — every claim must be defensible.

**Analyst — standalone mode:**
Analyst works with or without a Scout JSON. If given just a company name, it runs its own research (4 priority searches), scores the lead, and generates the one-pager. Useful for one-off requests without running a full Scout pass.

**Demo Builder — fictional app names:**
The demo generates a fictional app per vertical (neobank → Crest/Vault, CIAM → Nexus) to avoid using real company branding in an uncertified demo. The visual identity (colors, fonts) is scraped from the company's actual site.

## Outputs

| Agent | Output path | Format |
|-------|------------|--------|
| Scout | `outputs/leads/leads_{market}_{date}.json` | JSON (strict schema) |
| Analyst | `outputs/one-pagers/{company}-{date}.md` | Markdown |
| Demo Builder | `outputs/demos/{app}-{company}-{date}.html` | Self-contained HTML |

All filenames include a date suffix — outputs never overwrite.
