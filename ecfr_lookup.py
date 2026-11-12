import re
import requests
from langchain_core.tools import tool

import cache

BASE_URL = "https://www.ecfr.gov/api/search/v1"


def _strip_tags(text: str) -> str:
    return re.sub(r"</?strong>|<span[^>]*>|</span>", "", text or "")


def _search_regulations_core(query: str, max_results: int = 3) -> list[dict]:
    cache_key = f"ecfr_search:{query}"
    cached = cache.get(cache_key)
    if isinstance(cached, list):
        print(f"  [cache hit: {cache_key}]")
        return cached

    print(f"  [cache miss, calling eCFR: {cache_key}]")
    resp = requests.get(
        f"{BASE_URL}/results",
        params={"query": query, "per_page": max_results, "date": "current"},
    )
    resp.raise_for_status()
    results = resp.json().get("results", [])[:max_results]

    formatted = []
    for r in results:
        h = r.get("hierarchy", {})
        title, section = h.get("title"), h.get("section")
        citation = f"{title} CFR {section}" if title and section else None
        url = f"https://www.ecfr.gov/current/title-{title}/section-{section}" if title and section else None
        heading = _strip_tags(r.get("headings", {}).get("section") or r.get("hierarchy_headings", {}).get("section"))
        excerpt = _strip_tags(r.get("full_text_excerpt", ""))
        formatted.append({
            "citation": citation,
            "heading": heading,
            "excerpt": excerpt,
            "url": url,
            "current": r.get("ends_on") is None,
        })

    cache.set(cache_key, formatted)
    return formatted


def _lookup_section_raw(title: str, part: str, per_page: int = 100) -> list[dict]:
    """Looks up every section in a given CFR title+part using the real
    hierarchy[title]/hierarchy[part] filters, confirmed against the live API --
    not fuzzy keyword search. Query is left empty on purpose: this is a
    structural lookup, not a relevance search."""
    cache_key = f"ecfr_hierarchy:{title}:{part}"
    cached = cache.get(cache_key)
    if isinstance(cached, list):
        print(f"  [cache hit: {cache_key}]")
        return cached

    print(f"  [cache miss, calling eCFR: {cache_key}]")
    resp = requests.get(
        f"{BASE_URL}/results",
        params={"hierarchy[title]": title, "hierarchy[part]": part, "date": "current", "per_page": per_page},
    )
    resp.raise_for_status()
    results = resp.json().get("results", [])
    cache.set(cache_key, results)
    return results

@tool
def search_regulations(query: str) -> str:
    """Search the current Code of Federal Regulations (CFR) for a regulatory topic
    or requirement. Covers U.S. federal regulations only -- not statutes, not case
    law, not state or non-U.S. rules. Returns real citations like '30 CFR 285.830'."""
    results = _search_regulations_core(query)
    if not results:
        return "No matching regulations found in the current CFR."
    if not all(r["current"] for r in results):
        print("  [WARNING: a result's 'current' flag was False despite date=current]")

    lines = []
    for r in results:
        lines.append(
            f"- {r['citation']}: {r['heading']}\n"
            f"  Excerpt: {r['excerpt']}\n"
            f"  URL: {r['url']}"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    for title, part, section in [("30", "250", "250.187"), ("30", "250", "250.188"), ("40", "112", "112.7")]:
        results = _lookup_section_raw(title, part, per_page=1000)
        found = any(r.get("hierarchy", {}).get("section") == section for r in results)
        print(f"{title} CFR {section}: {'FOUND' if found else 'NOT FOUND'} among {len(results)} results in part {part}")