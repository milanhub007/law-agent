import os
import re
from datetime import date

import requests
from dotenv import load_dotenv
from langchain_core.tools import tool

import cache

load_dotenv()

GOVINFO_API_KEY = os.environ["GOVINFO_API_KEY"]
BASE_URL = "https://api.govinfo.gov"

SEC_PATTERN = re.compile(r"-sec(.+)$")
TITLE_PATTERN = re.compile(r"title(\d+)")


def search_raw(query: str, page_size: int = 5) -> dict:
    resp = requests.post(
        f"{BASE_URL}/search",
        headers={"X-Api-Key": GOVINFO_API_KEY, "Content-Type": "application/json"},
        json={
            "query": query,
            "pageSize": str(page_size),
            "offsetMark": "*",
            "sorts": [{"field": "score", "sortOrder": "DESC"}],
        },
    )
    resp.raise_for_status()
    return resp.json()


def latest_edition(title: str) -> str | None:
    """Finds the newest published edition of a U.S. Code title, e.g. USCODE-2024-title42.
    Checks this year and the 3 before it, newest first."""
    cache_key = f"uscode_edition:{title}"
    cached = cache.get(cache_key)
    if isinstance(cached, dict) and "package_id" in cached:
        return cached["package_id"]

    this_year = date.today().year
    for year in range(this_year, this_year - 4, -1):
        package_id = f"USCODE-{year}-title{title}"
        print(f"  [calling GovInfo: does {package_id} exist?]")
        resp = requests.get(f"{BASE_URL}/packages/{package_id}/summary",
                            headers={"X-Api-Key": GOVINFO_API_KEY})
        if resp.status_code == 200:
            cache.set(cache_key, {"package_id": package_id})
            return package_id
    return None  # not cached on purpose: an edition may appear later


def title_sections(package_id: str) -> dict:
    """Every section in one U.S. Code title, mapped section number -> granule.
    Paginates through all pages once, then served from the cache."""
    cache_key = f"uscode_sections:{package_id}"
    cached = cache.get(cache_key)
    if isinstance(cached, dict) and cached:
        print(f"  [cache hit: {cache_key}]")
        return cached

    print(f"  [cache miss, calling GovInfo: {cache_key}]")
    sections = {}
    url = f"{BASE_URL}/packages/{package_id}/granules"
    params = {"offsetMark": "*", "pageSize": 1000}
    while url:
        resp = requests.get(url, headers={"X-Api-Key": GOVINFO_API_KEY}, params=params)
        resp.raise_for_status()
        data = resp.json()
        for g in data.get("granules", []):
            m = SEC_PATTERN.search(g.get("granuleId", ""))
            if m:
                sections[m.group(1)] = {"granule_id": g["granuleId"], "heading": g.get("title", "")}
        url = data.get("nextPage")
        params = None  # nextPage already carries its own query string

    cache.set(cache_key, sections)
    return sections


def _search_statutes_core(query: str, max_results: int = 5) -> list[dict]:
    cache_key = f"uscode_search:{query}"
    cached = cache.get(cache_key)
    if isinstance(cached, list):
        print(f"  [cache hit: {cache_key}]")
        return cached

    print(f"  [cache miss, calling GovInfo: {cache_key}]")
    data = search_raw(f"collection:(USCODE) and {query}", page_size=max_results * 3)

    latest = {}  # keep only the newest edition of each section
    for r in data.get("results", []):
        t = TITLE_PATTERN.search(r.get("packageId", ""))
        s = SEC_PATTERN.search(r.get("granuleId", ""))
        if not (t and s):
            continue
        key = (t.group(1), s.group(1))
        if key not in latest or r.get("dateIssued", "") > latest[key]["date_issued"]:
            latest[key] = {
                "citation": f"{key[0]} U.S.C. § {key[1]}",
                "heading": r.get("title", ""),
                "date_issued": r.get("dateIssued", ""),
                "url": f"https://www.govinfo.gov/link/uscode/{key[0]}/{key[1]}",
            }

    results = list(latest.values())[:max_results]
    cache.set(cache_key, results)
    return results


@tool
def search_statutes(query: str) -> str:
    """Keyword search of the U.S. Code (federal statutes), e.g. 'overtime pay'.
        Results can be noisy and may miss the main statute. If you already know the
        likely section, use verify_statute instead. Federal statutes only -- not
        state law, regulations or case law."""
    try:
        results = _search_statutes_core(query)
    except requests.HTTPError as e:
        return f"Statute search failed: {e}"
    if not results:
        return "No matching federal statutes found."
    return "\n".join(
        f"- {r['citation']}: {r['heading']} ({r['date_issued'][:4]} edition)\n  URL: {r['url']}"
        for r in results
    )


if __name__ == "__main__":
    print(search_statutes.invoke({"query": "overtime pay"}))