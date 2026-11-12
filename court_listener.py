import os
import requests
from dotenv import load_dotenv
from langchain_core.tools import tool
import cache
import rate_limiter

load_dotenv()

COURTLISTENER_TOKEN = os.environ["COURT_LISTENER_API_KEY"]
BASE_URL = "https://www.courtlistener.com/api/rest/v4"


@tool
def search_case_law(query: str) -> str:
    """Search CourtListener for real case law matching a legal question or topic.
    Use this whenever the user asks about a case, doctrine, or precedent."""
    cache_key = f"search:{query}"
    cached = cache.get(cache_key)
    if cached is not None:
        print(f"  [cache hit: {cache_key}]")
        return cached

    print(f"  [cache miss, calling CourtListener: {cache_key}]")
    rate_limiter.wait_if_needed()
    resp = requests.get(
        f"{BASE_URL}/search/",
        params={"q": query, "type": "o", "order_by": "score desc"},
        headers={"Authorization": f"Token {COURTLISTENER_TOKEN}"},
    )
    resp.raise_for_status()
    rate_limiter.record_call()
    results = resp.json()["results"][:3]

    if not results:
        formatted = "No matching cases found in CourtListener."
    else:
        lines = []
        for r in results:
            citation = (r.get("citation") or ["no reporter citation on file"])[0]
            lines.append(
                f"- {r['caseName']} ({r.get('court_citation_string', r.get('court'))}, "
                f"filed {r.get('dateFiled')}) — citation: {citation}, "
                f"cluster_id: {r['cluster_id']}"
            )
        formatted = "\n".join(lines)

    cache.set(cache_key, formatted)
    return formatted


if __name__ == "__main__":
    print(search_case_law.invoke({"query": "qualified immunity police officers"}))
