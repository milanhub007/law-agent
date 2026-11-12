import os
import requests
from langchain_core.tools import tool
from dotenv import load_dotenv

import cache
import rate_limiter
from court_hierarchy import get_court_id_for_docket

load_dotenv()

COURTLISTENER_TOKEN = os.environ["COURT_LISTENER_API_KEY"]
BASE_URL = "https://www.courtlistener.com/api/rest/v4"


def _lookup_citation(citation: str) -> dict:
    """Structured core logic - cached, and reusable by code, not just by the LLM tool below cached. """
    normalised = citation.split("(")[0].strip()
    cache_key = f"cite:{normalised}"
    cached = cache.get(cache_key)
    if isinstance(cached, dict) and "status" in cached:
        print(f"  [cache hit: {cache_key}]")
        return cached
    print(f"  [cache miss, calling CourtListener: {cache_key}]")
    rate_limiter.wait_if_needed()
    resp = requests.post(
        f"{BASE_URL}/citation-lookup/",
        headers={"Authorization": f"Token {COURTLISTENER_TOKEN}"},
        json={"text": citation},
    )
    resp.raise_for_status()
    rate_limiter.record_call()
    results = resp.json()

    if not results:
        result = {"status": "unverified", "cluster_id": None, "case_name": None,
                  "detail": f"'{citation}' wasn't recognized as a citation at all."}
    else:
        r = results[0]
        cl_status = r.get("status")
        if cl_status == 200:
            case = r["clusters"][0]
            court_id = get_court_id_for_docket(case["docket_id"]) if case.get("docket_id") else None
            result = {"status": "verified", "cluster_id": case["id"], "case_name": case["case_name"],
                      "detail": f"matches {case['case_name']}", "court_id": court_id}
        elif cl_status == 404:
            result = {"status": "unverified", "cluster_id": None, "case_name": None,
                      "detail": "validly formatted but no matching case was found.", "court_id": None}
        elif cl_status == 300:
            result = {"status": "ambiguous", "cluster_id": None, "case_name": None,
                      "detail": "matched multiple cases — needs human review.", "court_id": None}
        else:
            result = {"status": "unverified", "cluster_id": None, "case_name": None,
                      "detail": f"could not be resolved (status {cl_status}).", "court_id": None}

    cache.set(cache_key, result)
    return result


@tool
def verify_citation(citation: str) -> str:
    """Check whether a case citation actually exists in CourtListener's database.
    Call this before stating ANY citation is real."""
    r = _lookup_citation(citation)
    if r["status"] == "verified":
        return f"VERIFIED: '{citation}' matches {r['case_name']}, cluster_id: {r['cluster_id']}"
    elif r["status"] == "ambiguous":
        return f"AMBIGUOUS: '{citation}' — {r['detail']}"
    else:
        return f"UNVERIFIED: '{citation}' — {r['detail']}"
