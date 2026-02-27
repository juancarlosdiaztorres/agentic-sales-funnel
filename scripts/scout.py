#!/usr/bin/env python3
"""
scout.py — Efficient lead scouting for Open Gateway API sales.

Architecture:
  1. Serper.dev   → company discovery + signal searches (free tier: 2,500/month)
  2. requests     → full page fetch for key sources (no Claude tokens)
  3. Claude Sonnet → scoring per company in isolated context (no history accumulation)

Cost vs Claude Code Scout:
  - Same depth (Sonnet + full pages)
  - ~10x cheaper (no context accumulation across companies)
  - Scales to 100+ leads per run

Usage:
    python scout.py --markets Spain --industries fintech neobanks --lead-count 5
    python scout.py --markets Germany UK Brazil --industries gaming fintech --lead-count 20
"""

import argparse
import json
import os
import time
from datetime import datetime
from pathlib import Path

import anthropic
import requests
from dotenv import load_dotenv

load_dotenv()

SERPER_API_KEY   = os.getenv("SERPER_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

SONNET_MODEL = "claude-sonnet-4-6"
HAIKU_MODEL  = "claude-haiku-4-5-20251001"

# Always exclude — from CLAUDE.md existing accounts + Tier 1
EXCLUDED_ACCOUNTS = {
    "google", "microsoft", "cyberark", "palo alto", "paloalto",
    "itaú", "itau", "santander", "bbva", "caixabank", "sabadell", "bankinter",
    "orange", "vodafone", "deutsche telekom",
    "meta", "apple", "amazon",
}

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; research-bot/1.0)"}


# ─── Serper ──────────────────────────────────────────────────────────────────

def serper_search(query: str, num: int = 5) -> list[dict]:
    if not SERPER_API_KEY:
        raise ValueError("SERPER_API_KEY not set in .env")
    resp = requests.post(
        "https://google.serper.dev/search",
        headers={"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"},
        json={"q": query, "num": num},
        timeout=10,
    )
    resp.raise_for_status()
    return [
        {
            "title": r.get("title", ""),
            "url":   r.get("link", ""),
            "snippet": r.get("snippet", ""),
            "date":  r.get("date"),
        }
        for r in resp.json().get("organic", [])
    ]


# ─── WebFetch ────────────────────────────────────────────────────────────────

def fetch_page(url: str, max_chars: int = 3000) -> str:
    """Fetch a page and return plain text (stripped HTML tags), capped at max_chars."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=8)
        resp.raise_for_status()
        text = resp.text
        # Strip HTML tags simply
        import re
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:max_chars]
    except Exception:
        return ""


# ─── Step 1: Company discovery ───────────────────────────────────────────────

def discover_companies(
    markets: list[str],
    industries: list[str],
    lead_count: int,
    excluded: set[str],
) -> list[str]:
    """Discover candidate company names via Serper + Haiku extraction."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    raw_snippets = []

    for market in markets:
        for industry in industries:
            for query in [
                f"top {industry} startups {market} 2025",
                f"best {industry} apps {market} 2024 2025 users growth",
                f"{industry} scale-ups {market} funding series raised",
                f"{industry} challenger {market} neobank fintech list",
            ]:
                try:
                    results = serper_search(query, num=8)
                    raw_snippets.extend(results)
                    time.sleep(0.1)
                except Exception as e:
                    print(f"    ⚠️  Search error: {e}")

    # Compact: only title + snippet
    snippets_text = "\n".join(
        f"- {r['title']}: {r['snippet']}"
        for r in raw_snippets
    )[:5000]

    # Haiku just for name extraction — cheap, fast
    resp = client.messages.create(
        model=HAIKU_MODEL,
        max_tokens=500,
        messages=[{
            "role": "user",
            "content": (
                f"Extract company names from these search results.\n"
                f"Target: {', '.join(industries)} companies in {', '.join(markets)}.\n"
                f"Rules:\n"
                f"- Only real companies with a digital product\n"
                f"- Exclude: {', '.join(sorted(excluded))}\n"
                f"- No banks in top-5 by assets in any country\n"
                f"- Return ONLY a JSON array of strings, max {lead_count * 4} names\n\n"
                f"{snippets_text}"
            ),
        }],
    )

    text = resp.content[0].text.strip()
    if "```" in text:
        text = text.split("```")[1].lstrip("json").strip().rstrip("```")
    try:
        names = json.loads(text)
    except Exception:
        import re
        names = re.findall(r'"([^"]{2,50})"', text)

    return [n for n in names if not any(ex in n.lower() for ex in excluded)][: lead_count * 3]


# ─── Step 2: Deep research per company ───────────────────────────────────────

SIGNAL_QUERIES = {
    "fraud_or_ato":  '{q} fraud "account takeover" OR phishing OR smishing',
    "auth_stack":    '{q} "SMS OTP" OR "two-factor" OR MFA OR authentication passkeys FIDO',
    "sms_otp":       '{q} "SMS verification" OR "phone verification" OR "SMS code"',
    "sim_swap":      '{q} "SIM swap" OR "SIM hijacking" OR "number porting"',
    "regulatory":    '{q} KYC OR AML OR "Banco de España" OR CNMV OR PSD2 OR BaFin OR FCA',
    "hiring":        '{q} "fraud engineer" OR "identity engineer" OR "security engineer" site:linkedin.com',
    "developer":     '{q} "API documentation" OR "developer portal" OR SDK',
}


def research_company(company: str) -> dict:
    """
    Run all signal queries + fetch the top result for each.
    Returns a dict with rich text per signal category.
    """
    signals = {}

    for key, template in SIGNAL_QUERIES.items():
        query = template.format(q=f'"{company}"')
        try:
            results = serper_search(query, num=4)
            # Fetch full text from the top result for depth
            if results:
                top_url = results[0]["url"]
                full_text = fetch_page(top_url, max_chars=2000)
                results[0]["full_text"] = full_text
            signals[key] = results
        except Exception as e:
            signals[key] = []
            print(f"    ⚠️  {key}: {e}")
        time.sleep(0.15)

    return signals


def _compact_signals(signals: dict) -> str:
    """Flatten signals to a compact string for the Sonnet prompt."""
    parts = []
    for key, results in signals.items():
        if not results:
            continue
        parts.append(f"\n### {key}")
        for r in results:
            parts.append(f"- [{r.get('date', '')}] {r['title']} ({r['url']})")
            parts.append(f"  Snippet: {r['snippet'][:300]}")
            if r.get("full_text"):
                parts.append(f"  Content: {r['full_text'][:800]}")
    return "\n".join(parts)[:12000]


# ─── Step 3: Score + structure with Sonnet ───────────────────────────────────

SYSTEM_PROMPT = """You are Scout, a lead intelligence agent for Open Gateway API sales.
APIs: Number Verification (silent auth replacing SMS OTP), SIM Swap Detection, KYC Match, Age Verification.

Scoring (base 5.0):
+2.0 SMS OTP dependency | +2.0 public fraud/ATO incident
+1.5 international expansion | +1.0 fraud/identity hiring
+1.0 regulated activity (banking/investment license) | +1.0 mobile-first high-DAU
+0.5 passkeys/FIDO mentions | +0.5 CIAM partner (Okta/Auth0/Ping/ForgeRock)
-2.0 already integrated with [your product] APIs | -1.5 B2B-only no consumer auth
-1.0 no mobile app | -1.0 no phone-number identity evidence

Account Tier (company size, separate from Score Tier):
- Tier 1: large incumbents → exclude
- Tier 2: mid-market challengers → primary target
- Tier 3: smaller scale-ups → secondary target

Score Tier (lead quality):
- A: ≥8.0 | B: 6.0-7.9 | C: <6.0

Output ONLY valid JSON. No markdown, no explanation."""

OUTPUT_SCHEMA = """{
  "company": {
    "name": "string", "website": "string|null", "hq_country": "string|null",
    "regions": ["string"], "industry": "string|null", "size_signal": "string|null"
  },
  "fit": {
    "score": "number (1 decimal)", "tier": "A|B|C",
    "use_cases": ["string"],
    "recommended_api_bundle": [{"api": "string", "role": "string", "why": "string"}],
    "why_now": ["string"]
  },
  "commercial_motion": {"primary": "direct|via_channel_partner|via_ciam_integration", "rationale": "string"},
  "buyers_and_personas": [{"title": "string", "function": "string", "why_they_care": ["string"]}],
  "integration_hypothesis": {
    "where_it_fits": ["string"], "architecture_guess": ["string"],
    "dependencies": ["string"], "time_to_poc_days": "number|null"
  },
  "signals": {
    "auth_stack_mentions": ["string"], "fraud_or_ato_mentions": ["string"],
    "sms_otp_mentions": ["string"], "passkeys_or_fido_mentions": ["string"],
    "regulatory_or_trust_safety_mentions": ["string"], "hiring_signals": ["string"]
  },
  "estimates": {
    "monthly_auth_volume": "string|null", "sms_cost_exposure": "string|null",
    "estimation_basis": "string|null"
  },
  "first_outreach_angle": {
    "one_liner": "string", "value_props": ["string"],
    "suggested_next_step": "string", "open_gateway_positioning": "string"
  },
  "risks_and_objections": [{"risk": "string", "mitigation": "string"}],
  "sources": [{"url": "string", "title": "string|null", "publisher": "string|null", "date": "string|null", "snippet": "string"}],
  "research_gaps": ["string"]
}"""


def score_and_structure(company: str, signals: dict, api_focus: list[str], markets: list[str]) -> dict:
    """Fresh Sonnet call per company — no accumulated context."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    signals_text = _compact_signals(signals)

    user_prompt = f"""Company to research: {company}
Target markets context: {', '.join(markets)}
API focus: {', '.join(api_focus)}

Signal research gathered:
{signals_text}

Return ONLY the JSON object matching this schema:
{OUTPUT_SCHEMA}"""

    resp = client.messages.create(
        model=SONNET_MODEL,
        max_tokens=3000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )

    text = resp.content[0].text.strip()
    if "```" in text:
        text = text.split("```")[1].lstrip("json").strip()
        if text.endswith("```"):
            text = text[:-3]
    return json.loads(text)


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Open Gateway API Lead Scout")
    parser.add_argument("--markets",    nargs="+", required=True, metavar="MARKET",
                        help="Target markets, e.g. Spain Germany Brazil")
    parser.add_argument("--industries", nargs="+", required=True, metavar="INDUSTRY",
                        help="Target industries, e.g. fintech neobanks gaming")
    parser.add_argument("--api-focus",  nargs="+",
                        default=["number_verification", "sim_swap"], metavar="API")
    parser.add_argument("--lead-count", type=int, default=10,
                        help="Number of leads to return (default: 10)")
    parser.add_argument("--min-score",  type=float, default=0.0,
                        help="Minimum score to include in output (e.g. 6.0 for Tier A+B only)")
    parser.add_argument("--exclude",    nargs="+", default=[], metavar="COMPANY",
                        help="Additional companies to exclude")
    parser.add_argument("--output-dir", default="outputs/leads")
    args = parser.parse_args()

    excluded = EXCLUDED_ACCOUNTS | {e.lower() for e in args.exclude}

    print(f"\n🔍 Scout — {args.markets} | {args.industries} | {args.lead_count} leads")
    print(f"   Sonnet for scoring, Haiku for discovery, Serper for searches\n")

    # Step 1 — Discover
    print("① Discovering companies...")
    candidates = discover_companies(args.markets, args.industries, args.lead_count, excluded)
    if not candidates:
        print("  ❌ No candidates found. Try broader industries or markets.")
        return
    print(f"  → {len(candidates)} candidates: {', '.join(candidates[:8])}{'...' if len(candidates) > 8 else ''}\n")

    # Steps 2+3 — Research + Score (one clean Sonnet call per company)
    print("② Researching and scoring (one isolated call per company)...")
    leads = []
    for i, company in enumerate(candidates, 1):
        print(f"  [{i:02d}/{len(candidates):02d}] {company}", end=" ... ", flush=True)
        try:
            signals = research_company(company)
            lead    = score_and_structure(company, signals, args.api_focus, args.markets)
            score   = lead.get("fit", {}).get("score", 0)
            tier    = lead.get("fit", {}).get("tier", "?")
            print(f"score {score:.1f} — Tier {tier}")
            if score >= args.min_score:
                leads.append(lead)
        except json.JSONDecodeError as e:
            print(f"⚠️  JSON parse error: {e}")
        except Exception as e:
            print(f"⚠️  {e}")

    # Sort and trim
    leads.sort(key=lambda x: x.get("fit", {}).get("score", 0), reverse=True)
    leads = leads[:args.lead_count]

    # Save
    date        = datetime.now().strftime("%Y-%m-%d")
    market_slug = "_".join(args.markets).lower().replace(" ", "_")
    Path(args.output_dir).mkdir(parents=True, exist_ok=True)
    output_path = f"{args.output_dir}/leads_{market_slug}_{date}.json"

    output = {
        "meta": {
            "generated_at": datetime.now().isoformat(),
            "target_markets": args.markets,
            "industries": args.industries,
            "api_focus": args.api_focus,
            "lead_count_requested": args.lead_count,
            "lead_count_returned": len(leads),
            "model_scoring": SONNET_MODEL,
            "model_discovery": HAIKU_MODEL,
            "search_engine": "serper.dev",
            "tier_distribution": {
                "tier_a": sum(1 for l in leads if l.get("fit", {}).get("score", 0) >= 8.0),
                "tier_b": sum(1 for l in leads if 6.0 <= l.get("fit", {}).get("score", 0) < 8.0),
                "tier_c": sum(1 for l in leads if l.get("fit", {}).get("score", 0) < 6.0),
            },
        },
        "leads": leads,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    # Summary
    m = output["meta"]
    print(f"\n✅ Done — {len(leads)} leads saved to {output_path}")
    print(f"   Tier A: {m['tier_distribution']['tier_a']} | "
          f"Tier B: {m['tier_distribution']['tier_b']} | "
          f"Tier C: {m['tier_distribution']['tier_c']}")
    print("\n   Top leads:")
    for lead in leads[:5]:
        name  = lead.get("company", {}).get("name", "?")
        score = lead.get("fit", {}).get("score", 0)
        tier  = lead.get("fit", {}).get("tier", "?")
        ol    = lead.get("first_outreach_angle", {}).get("one_liner", "")[:90]
        print(f"   • {name} ({score:.1f} / Tier {tier})")
        print(f"     {ol}")


if __name__ == "__main__":
    main()
