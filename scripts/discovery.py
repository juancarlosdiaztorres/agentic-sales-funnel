#!/usr/bin/env python3
"""
discovery.py — Zero-token company discovery using structured web sources.

Finds candidate company names by querying sources that use structured URLs
(Crunchbase, Tracxn, EU-Startups, Dealroom). Company name is extracted from
the URL slug — never from article titles. If we can't get a name from the URL,
we skip it. No LLM, no guessing.

Output: JSON list of {name, source_url, source} — ready for:
  python3 scripts/scout_research.py --companies [paste names]

Usage:
  python3 scripts/discovery.py --markets Spain --industries fintech neobanks
  python3 scripts/discovery.py --markets Brazil Germany --industries gaming crypto --count 20
  python3 scripts/discovery.py --markets Spain --industries fintech --sources crunchbase eu-startups

Requirements: pip install requests python-dotenv (same as scout_research.py)
No Anthropic API key needed.
"""

import argparse
import json
import os
import re
import time
from datetime import datetime, date
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

SERPER_API_KEY = os.getenv("SERPER_API_KEY")

# ─── Structured sources ───────────────────────────────────────────────────────
# Each source has a Serper query template and a URL regex that captures the
# company slug. If the URL doesn't match the pattern, the result is discarded.

SOURCES = {
    "crunchbase": {
        "query": "site:crunchbase.com/organization {industry} {market}",
        "url_pattern": r"crunchbase\.com/organization/([a-z0-9][a-z0-9-]{1,40}[a-z0-9])",
        "title_strip": r"\s*[-|].*crunchbase.*$",  # used to validate title, not extract
    },
    "tracxn": {
        "query": "site:tracxn.com {industry} companies {market}",
        "url_pattern": r"tracxn\.com/d/companies/[^/]+/([a-z0-9][a-z0-9-]{1,40}[a-z0-9])(?:__|/|$)",
        "title_strip": None,
    },
    "eu-startups": {
        "query": "site:eu-startups.com/startup {industry} {market}",
        "url_pattern": r"eu-startups\.com/startup/([a-z0-9][a-z0-9-]{1,40}[a-z0-9])",
        "title_strip": None,
    },
    "dealroom": {
        "query": "site:app.dealroom.co/companies {industry} {market}",
        "url_pattern": r"dealroom\.co/companies/([a-z0-9][a-z0-9-]{1,40}[a-z0-9])",
        "title_strip": None,
    },
    "startupxplore": {
        # Spain-focused startup directory with structured company URLs
        "query": "site:startupxplore.com/startups {industry} {market}",
        "url_pattern": r"startupxplore\.com/startups/([a-z0-9][a-z0-9-]{1,40}[a-z0-9])",
        "title_strip": None,
    },
    "f6s": {
        "query": "site:f6s.com {industry} startup {market}",
        "url_pattern": r"f6s\.com/([a-z0-9][a-z0-9-]{1,40}[a-z0-9])(?:/|$)",
        "title_strip": None,
    },
}

# Geographic locale codes for Serper — improves local relevance
MARKET_TO_GL = {
    "spain":   "es",
    "germany": "de",
    "brazil":  "br",
    "uk":      "gb",
    "france":  "fr",
    "italy":   "it",
    "mexico":  "mx",
    "poland":  "pl",
    "netherlands": "nl",
}

# Slugs that are site navigation, not company names
SLUG_BLOCKLIST = {
    "about", "careers", "jobs", "blog", "news", "press", "contact", "login",
    "signup", "register", "terms", "privacy", "help", "search", "explore",
    "discover", "trending", "featured", "companies", "startups", "startup",
    "company", "list", "guide", "report", "overview", "top-10", "best-of",
    "fintech", "neobank", "neobanks", "banking", "payment", "payments",
    "gaming", "crypto", "cryptocurrency", "blockchain", "insurance", "identity",
    "security", "spain", "germany", "brazil", "united-kingdom", "europe",
    "latam", "latin-america", "usa", "uk", "funding", "venture", "capital",
    "accelerator", "incubator", "ecosystem", "community", "directory",
    "profile", "portfolio", "invest", "investor", "fund", "vc",
}

# Accounts too large or already covered — exclude from results
EXCLUDED_ACCOUNTS = {
    "google", "microsoft", "apple", "amazon", "meta", "facebook",
    "santander", "bbva", "caixabank", "sabadell", "bankinter",
    "orange", "vodafone", "deutsche-telekom", "deutsche-bank",
    "itau", "itaú", "bradesco", "nubank",
}


# ─── Helpers ─────────────────────────────────────────────────────────────────

def serper_search(query: str, gl: str | None = None, num: int = 10) -> list[dict]:
    if not SERPER_API_KEY:
        raise ValueError("SERPER_API_KEY not set in .env")
    payload: dict = {"q": query, "num": num}
    if gl:
        payload["gl"] = gl
    resp = requests.post(
        "https://google.serper.dev/search",
        headers={"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"},
        json=payload,
        timeout=10,
    )
    resp.raise_for_status()
    return [
        {"title": r.get("title", ""), "url": r.get("link", ""), "snippet": r.get("snippet", "")}
        for r in resp.json().get("organic", [])
    ]


def slug_to_name(slug: str) -> str:
    """'job-and-talent' → 'Job and Talent', 'bit2me' → 'Bit2Me'"""
    stop_words = {"and", "or", "the", "of", "in", "de", "la", "el", "van", "von"}
    parts = slug.split("-")
    return " ".join(
        p if p in stop_words else p.capitalize()
        for p in parts
    ).strip()


def extract_slug(url: str, pattern: str) -> str | None:
    m = re.search(pattern, url.lower())
    if not m:
        return None
    slug = m.group(1)

    # Basic blocklist
    if slug in SLUG_BLOCKLIST or len(slug) < 4:
        return None

    # Reject article/numeric identifiers
    if re.search(r'\d{4,}', slug):
        return None

    # Reject slugs ending in corporate suffixes — holding/shell companies
    if re.search(r'-(sl|sa|slu|ltd|llc|inc|bv|gmbh|ag|sas|srl|spa)$', slug):
        return None

    # Reject slugs ending in -2, -3 etc (secondary/duplicate Crunchbase entries)
    if re.search(r'-\d+$', slug):
        return None

    # Reject slugs that contain country/market names (directories, not companies)
    country_terms = {"spain", "germany", "brazil", "france", "italy", "europe",
                     "latam", "usa", "uk", "global", "international", "worldwide"}
    if any(ct in slug.split("-") for ct in country_terms):
        return None

    # Reject slugs that START with an industry keyword (e.g. "fintech-panda-spain")
    industry_prefixes = {"fintech", "neobank", "crypto", "gaming", "insurance",
                         "insurtech", "lendtech", "paytech", "regtech", "wealthtech"}
    if slug.split("-")[0] in industry_prefixes:
        return None

    return slug


def is_excluded(name: str) -> bool:
    key = name.lower().replace(" ", "-")
    return any(ex in key for ex in EXCLUDED_ACCOUNTS)


# ─── Core discovery ───────────────────────────────────────────────────────────

def discover(
    markets: list[str],
    industries: list[str],
    count: int,
    sources: list[str],
    verbose: bool = True,
) -> list[dict]:
    """
    Query each source for each (market × industry) combination.
    Extract company names from structured URL slugs only.
    Returns a deduplicated list of {name, source_url, source}.
    """
    seen_slugs: set[str] = set()
    results: list[dict] = []
    total_queries = 0

    for source_name in sources:
        source = SOURCES[source_name]
        pattern = source["url_pattern"]

        for market in markets:
            gl = MARKET_TO_GL.get(market.lower())

            for industry in industries:
                query = source["query"].format(industry=industry, market=market)
                total_queries += 1

                try:
                    hits = serper_search(query, gl=gl, num=10)
                    new_this_query = 0
                    for hit in hits:
                        slug = extract_slug(hit["url"], pattern)
                        if not slug or slug in seen_slugs:
                            continue
                        name = slug_to_name(slug)
                        if is_excluded(name):
                            continue
                        seen_slugs.add(slug)
                        results.append({
                            "name": name,
                            "source_url": hit["url"],
                            "source": source_name,
                            "market": market,
                            "industry": industry,
                        })
                        new_this_query += 1

                    if verbose:
                        print(f"  [{source_name}] {market}/{industry}: {len(hits)} results → {new_this_query} new names")

                except Exception as e:
                    if verbose:
                        print(f"  ⚠️  [{source_name}] {market}/{industry}: {e}")

                time.sleep(0.15)

        if len(results) >= count * 2:
            break

    if verbose:
        print(f"\n  Total queries: {total_queries}  |  Unique names found: {len(results)}")

    return results[:count]


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Discover company names using structured web sources (0 Claude tokens)"
    )
    parser.add_argument("--markets",    nargs="+", required=True, metavar="MARKET",
                        help="Target markets, e.g. Spain Germany Brazil")
    parser.add_argument("--industries", nargs="+", required=True, metavar="INDUSTRY",
                        help="Target industries, e.g. fintech neobanks gaming")
    parser.add_argument("--count",      type=int, default=20,
                        help="Target number of companies to find (default: 20)")
    parser.add_argument("--sources",    nargs="+", default=list(SOURCES.keys()),
                        choices=list(SOURCES.keys()),
                        help=f"Sources to query (default: all). Options: {', '.join(SOURCES.keys())}")
    parser.add_argument("--output-dir", default="outputs/leads")
    parser.add_argument("--quiet",      action="store_true", help="Suppress progress output")
    args = parser.parse_args()

    print(f"\n🔍 Discovery: {args.markets} × {args.industries}")
    print(f"   Sources: {args.sources}")
    print(f"   Target: {args.count} companies\n")

    candidates = discover(
        markets=args.markets,
        industries=args.industries,
        count=args.count,
        sources=args.sources,
        verbose=not args.quiet,
    )

    # Output
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    market_slug = "_".join(m.lower() for m in args.markets)
    today = date.today().isoformat()
    out_path = output_dir / f"discovery_{market_slug}_{today}.json"

    output = {
        "meta": {
            "generated_at": datetime.now().isoformat(),
            "markets": args.markets,
            "industries": args.industries,
            "sources_queried": args.sources,
            "companies_found": len(candidates),
        },
        "companies": candidates,
        "next_step": (
            "python3 scripts/scout_research.py --companies "
            + " ".join('"' + c["name"] + '"' for c in candidates)
            + " --markets " + " ".join(args.markets)
        ),
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Found {len(candidates)} companies")
    print(f"   Saved: {out_path}\n")

    if candidates:
        print("Companies found:")
        for i, c in enumerate(candidates, 1):
            print(f"  {i:>3}. {c['name']:<30} [{c['source']}] {c['market']}/{c['industry']}")
        print()
        print("Next step:")
        print(f"  {output['next_step']}")
    else:
        print("⚠️  No companies found. Try different --industries or --sources.")
        print("   Crunchbase and Tracxn tend to have the best coverage.")

    print()


if __name__ == "__main__":
    main()
