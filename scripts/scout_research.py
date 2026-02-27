#!/usr/bin/env python3
"""
scout_research.py — Web research pre-fetcher for Open Gateway API Scout.

Does all the heavy web lifting (Serper searches + page fetching) WITHOUT
calling Claude. Outputs compact JSON for the Claude Code Scout agent to score.

Two modes:
  (A) Discovery mode  — finds company names automatically via structured sources
  (B) Companies mode  — skip discovery, research a specific list you provide

Requirements: pip install requests python-dotenv
No Anthropic API key needed.

Usage:
  (A) python scout_research.py --markets Spain --industries fintech neobanks --candidates 15
  (B) python scout_research.py --companies Wallapop Bit2Me CyberArk --markets Spain
  (B) python scout_research.py --companies "Job and Talent" SeQura Fintonic

Then paste output into Claude Code Scout:
  "Score and structure these pre-researched companies for Open Gateway API fit.
   Use the signals provided — do not run additional web searches."
"""

import argparse
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

SERPER_API_KEY = os.getenv("SERPER_API_KEY")
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; research-bot/1.0)"}

# Account Tier 1 — always exclude (already Telefónica clients or too large)
EXCLUDED_ACCOUNTS = {
    "google", "microsoft", "cyberark", "palo alto", "itaú", "itau",
    "santander", "bbva", "caixabank", "sabadell", "bankinter",
    "orange", "vodafone", "deutsche telekom",
    "meta", "apple", "amazon",
}

# Signal queries — priority order matches scout.md search strategy
SIGNAL_QUERIES = {
    "fraud_or_ato":       '"{company}" fraud "account takeover" OR phishing OR smishing',
    "sms_otp_dependency": '"{company}" "SMS OTP" OR "SMS verification" OR "phone verification" OR "two-factor authentication"',
    "auth_stack":         '"{company}" MFA OR authentication OR passkeys OR FIDO OR "developer docs" OR SDK',
    "hiring":             '"{company}" "fraud engineer" OR "identity engineer" OR "security engineer" site:linkedin.com',
    "sim_swap":           '"{company}" "SIM swap" OR "SIM hijacking" OR "number porting"',
    "regulatory":         '"{company}" KYC OR AML OR "Banco de España" OR CNMV OR PSD2 OR BaFin OR FCA',
}

# Discovery queries target structured company databases, not article lists
# URL slugs (crunchbase.com/organization/wallapop) reliably contain company names
DISCOVERY_QUERIES = [
    '"{industry}" "{market}" startup 2024 2025 site:crunchbase.com/organization',
    '"{industry}" companies "{market}" funding raised site:sifted.eu OR site:elreferente.es OR site:expansion.com',
    '"{industry}" startups "{market}" site:f6s.com OR site:angel.co',
    'top "{industry}" apps "{market}" 2025 SMS login authentication users funding',
]

# Structured URL patterns where the slug IS the company name
STRUCTURED_URL_PATTERNS = [
    (r'crunchbase\.com/organization/([a-z0-9][a-z0-9-]+[a-z0-9])', 'crunchbase'),
    (r'linkedin\.com/company/([a-z0-9][a-z0-9-]+[a-z0-9])', 'linkedin'),
    (r'f6s\.com/([a-z0-9][a-z0-9-]+[a-z0-9])(?:/|$)', 'f6s'),
    (r'angel\.co/company/([a-z0-9][a-z0-9-]+[a-z0-9])', 'angelco'),
]

# Generic slugs to ignore (not company names)
SLUG_BLOCKLIST = {
    "about", "careers", "jobs", "blog", "news", "press", "contact",
    "login", "signup", "register", "terms", "privacy", "help",
    "search", "explore", "discover", "trending", "featured",
    "fintech", "neobank", "banking", "payment", "gaming", "crypto",
    "insurance", "identity", "security", "startup", "company",
    "spain", "germany", "brazil", "united-kingdom", "europe", "latam",
    "top-10", "best-of", "list", "guide", "report", "overview",
}


# ─── Helpers ─────────────────────────────────────────────────────────────────

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
            "title":   r.get("title", ""),
            "url":     r.get("link", ""),
            "snippet": r.get("snippet", ""),
            "date":    r.get("date"),
        }
        for r in resp.json().get("organic", [])
    ]


def fetch_page(url: str, max_chars: int = 2500) -> str:
    """Fetch a URL and return plain text (no HTML tags), capped at max_chars."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=8)
        resp.raise_for_status()
        text = re.sub(r"<[^>]+>", " ", resp.text)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:max_chars]
    except Exception:
        return ""


def slug_to_name(slug: str) -> str:
    """Convert URL slug to display name: 'job-and-talent' → 'Job and Talent'"""
    stop_words = {"and", "or", "the", "of", "in", "de", "la", "el"}
    parts = slug.split("-")
    return " ".join(
        p if p in stop_words else p.capitalize()
        for p in parts
    ).strip()


def extract_from_url(url: str) -> str | None:
    """Extract a company name from a structured database URL."""
    for pattern, source in STRUCTURED_URL_PATTERNS:
        m = re.search(pattern, url.lower())
        if m:
            slug = m.group(1)
            if slug in SLUG_BLOCKLIST or len(slug) < 3:
                return None
            return slug_to_name(slug)
    return None


def _extract_publisher(url: str) -> str:
    try:
        m = re.search(r'https?://(?:www\.)?([^/]+)', url)
        return m.group(1) if m else ""
    except Exception:
        return ""


# ─── Step 1 (Mode A): Discover company names from structured sources ──────────

def discover_candidates(
    markets: list[str],
    industries: list[str],
    count: int,
    excluded: set[str],
) -> list[str]:
    """
    Discover real company names by extracting from structured URL slugs
    (Crunchbase, LinkedIn, F6S, Angel.co) rather than article word patterns.
    Falls back to title-word extraction only when URL extraction yields nothing.
    """
    seen: set[str] = set()
    candidates: list[str] = []

    for market in markets:
        for industry in industries:
            for template in DISCOVERY_QUERIES:
                query = template.format(industry=industry, market=market)
                try:
                    results = serper_search(query, num=10)
                    for r in results:
                        # Primary: extract from structured URL slug
                        name = extract_from_url(r["url"])

                        # Fallback: careful title extraction (only short proper nouns)
                        if not name:
                            title_words = re.findall(
                                r'\b([A-Z][a-z]{2,}(?:[A-Z][a-z]+)?)\b',
                                r["title"]
                            )
                            # Only accept if it looks like a brand name (short, not a common word)
                            generic = {
                                "Spain", "Germany", "Brazil", "Europe", "Fintech",
                                "Neobank", "Banking", "Payment", "Gaming", "Crypto",
                                "Insurance", "Identity", "Security", "Startup",
                                "Company", "Report", "Guide", "Review", "List",
                                "News", "Blog", "Top", "Best", "How", "Why",
                            }
                            for w in title_words:
                                if w not in generic and len(w) <= 20:
                                    name = w
                                    break

                        if name:
                            key = name.lower()
                            if (
                                key not in seen
                                and key not in excluded
                                and not any(ex in key for ex in excluded)
                            ):
                                seen.add(key)
                                candidates.append(name)

                    time.sleep(0.1)
                except Exception as e:
                    print(f"  ⚠️  Search error: {e}")

            if len(candidates) >= count * 4:
                break

    return candidates[:count * 3]


# ─── Step 2: Research signals per company ────────────────────────────────────

def research_company(company: str, max_fetch: int = 2) -> dict:
    """
    Run signal queries in priority order (matches scout.md search strategy).
    Fetches full page for top result when useful; skips homepages.
    """
    signals = {}
    fetch_count = 0

    for key, template in SIGNAL_QUERIES.items():
        query = template.format(company=company)
        try:
            results = serper_search(query, num=4)
            if results and results[0]["url"] and fetch_count < max_fetch:
                url = results[0]["url"]
                # Never fetch homepages (zero signal value per scout.md rules)
                is_homepage = bool(re.match(r'https?://[^/]+/?$', url))
                if not is_homepage:
                    full_text = fetch_page(url, max_chars=2000)
                    if full_text:
                        results[0]["full_text"] = full_text
                        fetch_count += 1
            signals[key] = results
        except Exception as e:
            signals[key] = []
        time.sleep(0.12)

    return signals


def signals_to_compact(company: str, signals: dict) -> dict:
    """Convert raw signals to compact structure aligned with scout.md schema."""
    compact: dict = {
        "company": company,
        "signals": {key: [] for key in SIGNAL_QUERIES},
    }

    for key, results in signals.items():
        for r in results:
            entry = {
                "title":     r.get("title", "")[:120],
                "snippet":   r.get("snippet", "")[:300],
                "url":       r.get("url", ""),
                "date":      r.get("date"),
                "publisher": _extract_publisher(r.get("url", "")),
            }
            if r.get("full_text"):
                entry["content"] = r["full_text"][:1500]
            compact["signals"][key].append(entry)

    compact["pre_score"] = _pre_score(signals)
    return compact


def _pre_score(signals: dict) -> float:
    """
    Rough pre-filter score — not the Scout scoring model.
    Checks whether actual signal content mentions key terms.
    """
    score = 0.0

    def has_signal(key: str, keywords: list[str]) -> bool:
        for r in signals.get(key, []):
            text = (r.get("snippet", "") + r.get("full_text", "")).lower()
            if any(kw.lower() in text for kw in keywords):
                return True
        return False

    if has_signal("fraud_or_ato", ["fraud", "account takeover", "phishing", "smishing"]):
        score += 2.0
    if has_signal("sms_otp_dependency", ["sms otp", "sms verification", "phone verification", "two-factor"]):
        score += 2.0
    if has_signal("auth_stack", ["authentication", "mfa", "passkeys", "fido", "sdk"]):
        score += 0.5
    if has_signal("hiring", ["fraud engineer", "identity engineer", "security engineer"]):
        score += 1.0
    if has_signal("regulatory", ["kyc", "aml", "psd2", "bafin", "fca", "banco de españa"]):
        score += 0.5

    return score


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Pre-fetch web signals for Open Gateway API Scout (no Anthropic key needed)"
    )

    # Mode A — discovery
    parser.add_argument("--markets",    nargs="+", metavar="MARKET",
                        help="Target markets, e.g. Spain Germany Brazil")
    parser.add_argument("--industries", nargs="+", metavar="INDUSTRY",
                        help="Target industries, e.g. fintech neobanks gaming")
    parser.add_argument("--candidates", type=int, default=15,
                        help="Companies to research in discovery mode (default: 15)")

    # Mode B — specific companies
    parser.add_argument("--companies",  nargs="+", metavar="COMPANY",
                        help="Skip discovery — research these specific companies directly")

    # Shared options
    parser.add_argument("--api-focus",  nargs="+",
                        default=["number_verification", "sim_swap"],
                        metavar="API",
                        help="API focus (metadata only — used by Scout for scoring context)")
    parser.add_argument("--min-prescore", type=float, default=2.0,
                        help="Min pre-score to include a company (discovery mode only)")
    parser.add_argument("--exclude",    nargs="+", default=[], metavar="COMPANY")
    parser.add_argument("--output-dir", default="outputs/leads")
    args = parser.parse_args()

    # Validate
    if not args.companies and not (args.markets and args.industries):
        parser.error("Provide either --companies OR both --markets and --industries")

    excluded = EXCLUDED_ACCOUNTS | {e.lower() for e in (args.exclude or [])}

    # ── Mode B: specific companies ─────────────────────────────────────────────
    if args.companies:
        companies = [c for c in args.companies if c.lower() not in excluded]
        markets = args.markets or ["(not specified)"]
        print(f"\n🔍 Scout Research (companies mode) — {companies}")
        print(f"   Researching {len(companies)} specific companies | No Claude calls\n")

        print("② Fetching signals...")
        researched = []
        for i, company in enumerate(companies, 1):
            print(f"  [{i:02d}/{len(companies):02d}] {company}", end=" ... ", flush=True)
            try:
                signals = research_company(company)
                compact = signals_to_compact(company, signals)
                total = sum(len(v) for v in signals.values())
                print(f"✓ (pre_score={compact['pre_score']:.1f}, {total} hits)")
                researched.append(compact)
            except Exception as e:
                print(f"⚠️  {e}")

    # ── Mode A: discovery ──────────────────────────────────────────────────────
    else:
        markets = args.markets
        print(f"\n🔍 Scout Research (discovery mode) — {markets} | {args.industries} | {args.candidates} companies")
        print(f"   No Claude calls — Serper structured-source extraction\n")

        print("① Discovering candidates from structured sources (Crunchbase, LinkedIn, F6S)...")
        candidates = discover_candidates(markets, args.industries, args.candidates, excluded)
        if not candidates:
            print("  ❌ No candidates found. Try --companies mode or broader terms.")
            return
        print(f"  → {len(candidates)} candidates found\n")

        print("② Fetching signals per company...")
        researched = []
        skipped = 0
        for i, company in enumerate(candidates, 1):
            print(f"  [{i:02d}/{len(candidates):02d}] {company}", end=" ... ", flush=True)
            try:
                signals = research_company(company)
                compact = signals_to_compact(company, signals)
                pre_score = compact["pre_score"]
                total = sum(len(v) for v in signals.values())
                if pre_score < args.min_prescore:
                    print(f"skipped (pre_score={pre_score:.1f})")
                    skipped += 1
                    continue
                researched.append(compact)
                print(f"✓ (pre_score={pre_score:.1f}, {total} hits)")
            except Exception as e:
                print(f"⚠️  {e}")

        print(f"\n  → {len(researched)} passed pre-filter ({skipped} skipped)\n")

    # Sort by pre_score descending for easier review
    researched.sort(key=lambda x: x.get("pre_score", 0), reverse=True)

    # ── Summary table ──────────────────────────────────────────────────────────
    print("\n📊 Pre-score ranking (before Claude scoring):")
    for r in researched:
        bar = "█" * int(r["pre_score"])
        print(f"   {r['company']:<30} {r['pre_score']:.1f} {bar}")

    # ── Save ───────────────────────────────────────────────────────────────────
    date = datetime.now().strftime("%Y-%m-%d")
    if args.companies:
        slug = "_".join(args.companies[:3]).lower().replace(" ", "_")[:40]
        output_path = f"{args.output_dir}/research_custom_{slug}_{date}.json"
    else:
        market_slug = "_".join(markets).lower().replace(" ", "_")
        output_path = f"{args.output_dir}/research_{market_slug}_{date}.json"

    Path(args.output_dir).mkdir(parents=True, exist_ok=True)

    output = {
        "meta": {
            "generated_at":         datetime.now().isoformat(),
            "mode":                 "companies" if args.companies else "discovery",
            "target_markets":       markets,
            "industries":           args.industries or [],
            "api_focus":            args.api_focus,
            "lead_count_requested": len(researched),
            "companies_researched": len(researched),
            "time_window_days":     365,
            "instructions": (
                "Paste this JSON into Claude Code Scout with: "
                "'Score and structure these pre-researched companies for Open Gateway API fit. "
                "Use the signals provided — do not run additional web searches. "
                "Focus on SMS-OTP dependency and fraud/ATO exposure.'"
            ),
        },
        "companies": researched,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Done — {len(researched)} companies → {output_path}")
    print(f"\n   Next step — paste into Claude Code Scout:")
    print(f"   \"Score and structure these pre-researched companies: [contents of {output_path}]\"")


if __name__ == "__main__":
    main()
