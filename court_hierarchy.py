import os
import re
import requests
from dotenv import load_dotenv

import cache
import rate_limiter

load_dotenv()

COURTLISTENER_TOKEN = os.environ["COURT_LISTENER_API_KEY"]
BASE_URL = "https://www.courtlistener.com/api/rest/v4"


# Static, set by 28 U.S.C. § 41 -- stable since 1981, doesn't need an API call.
CIRCUIT_STATES = {
    "ca1": {"Maine", "Massachusetts", "New Hampshire", "Rhode Island", "Puerto Rico"},
    "ca2": {"Connecticut", "New York", "Vermont"},
    "ca3": {"Delaware", "New Jersey", "Pennsylvania", "Virgin Islands"},
    "ca4": {"Maryland", "North Carolina", "South Carolina", "Virginia", "West Virginia"},
    "ca5": {"Louisiana", "Mississippi", "Texas"},
    "ca6": {"Kentucky", "Michigan", "Ohio", "Tennessee"},
    "ca7": {"Illinois", "Indiana", "Wisconsin"},
    "ca8": {"Arkansas", "Iowa", "Minnesota", "Missouri", "Nebraska", "North Dakota", "South Dakota"},
    "ca9": {"Alaska", "Arizona", "California", "Guam", "Hawaii", "Idaho", "Montana", "Nevada",
            "Northern Mariana Islands", "Oregon", "Washington"},
    "ca10": {"Colorado", "Kansas", "New Mexico", "Oklahoma", "Utah", "Wyoming"},
    "ca11": {"Alabama", "Florida", "Georgia"},
    "cadc": {"District of Columbia"},
}

_DISTRICT_PATTERN = re.compile(r"^(?:[SNEWM]\.D\.|D\.)\s+(.+)$")


def extract_state_from_short_name(short_name: str) -> str | None:
    match = _DISTRICT_PATTERN.match(short_name or "")
    return match.group(1) if match else None


def get_circuit_for_court(court: dict) -> str | None:
    """Returns the circuit court_id that binds this court. 'scotus' for the
    Supreme Court (binds everywhere). None if this court isn't placeable --
    e.g. a state court, which has its own, separate hierarchy not handled here."""
    court_id = court.get("id")
    if court_id == "scotus":
        return "scotus"
    if court_id in CIRCUIT_STATES:
        return court_id
    if court.get("jurisdiction") == "FD":
        state = extract_state_from_short_name(court.get("short_name"))
        for circuit, states in CIRCUIT_STATES.items():
            if state in states:
                return circuit
    return None


def get_court(court_id: str) -> dict:
    cache_key = f"court:{court_id}"
    cached = cache.get(cache_key)
    if isinstance(cached, dict):
        print(f"  [cache hit: {cache_key}]")
        return cached

    print(f"  [cache miss, calling CourtListener: {cache_key}]")
    rate_limiter.wait_if_needed()
    resp = requests.get(
        f"{BASE_URL}/courts/{court_id}/",
        headers={"Authorization": f"Token {COURTLISTENER_TOKEN}"},
    )
    resp = requests.get(
        f"{BASE_URL}/courts/{court_id}/",
        headers={"Authorization": f"Token {COURTLISTENER_TOKEN}"},
    )
    resp.raise_for_status()
    data = resp.json()
    cache.set(cache_key, data)
    return data


def label_binding_status(case_court: dict, user_circuit: str) -> str:
    """user_circuit: the circuit governing the user's own court (or 'scotus'
    if they're asking as if before the Supreme Court itself)."""
    case_circuit = get_circuit_for_court(case_court)

    if case_circuit is None:
        return "unknown (state court or unrecognized -- not covered by this check)"
    if case_circuit == "scotus":
        return "binding (Supreme Court binds every federal court)"
    if case_circuit == user_circuit:
        return "binding"
    return "persuasive only (different circuit)"


def get_court_id_for_docket(docket_id: int) -> str | None:
    """One extra API call beyond citation-lookup -- neither it nor the cluster
    object contains court info directly, only the docket does."""
    cache_key = f"docket_court:{docket_id}"
    cached = cache.get(cache_key)
    if isinstance(cached, dict) and "court_id" in cached:
        print(f"  [cache hit: {cache_key}]")
        return cached["court_id"]

    print(f"  [cache miss, calling CourtListener: {cache_key}]")
    rate_limiter.wait_if_needed()
    resp = requests.get(
        f"{BASE_URL}/dockets/{docket_id}/",
        headers={"Authorization": f"Token {COURTLISTENER_TOKEN}"},
    )
    resp = requests.get(
        f"{BASE_URL}/dockets/{docket_id}/",
        headers={"Authorization": f"Token {COURTLISTENER_TOKEN}"},
    )
    resp.raise_for_status()
    court_id = resp.json().get("court_id")
    cache.set(cache_key, {"court_id": court_id})
    return court_id


STATE_TO_CIRCUIT = {}
for _circuit, _states in CIRCUIT_STATES.items():
    for _state in _states:
        STATE_TO_CIRCUIT[_state.lower()] = _circuit

_STATE_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(s) for s in sorted(STATE_TO_CIRCUIT, key=len, reverse=True)) + r")\b"
)


def find_circuit_in_text(text: str) -> str | None:
    """Finds a U.S. state named in free text and returns its circuit.
    Returns None if no state is named, or if states from different circuits
    are named (ambiguous)."""
    circuits = {STATE_TO_CIRCUIT[m.group(1)] for m in _STATE_PATTERN.finditer((text or "").lower())}
    return circuits.pop() if len(circuits) == 1 else None


def resolve_user_circuit(user_input: str) -> str | None:
    """Accepts a state/territory name, or a circuit id directly (e.g. 'ca1',
    'scotus'), case-insensitive. Returns the circuit id, or None if unrecognized."""
    cleaned = (user_input or "").strip().lower()
    if not cleaned:
        return None
    if cleaned in CIRCUIT_STATES or cleaned == "scotus":
        return cleaned
    return STATE_TO_CIRCUIT.get(cleaned)


if __name__ == "__main__":
    for court_id in ("mad", "nysd", "cand", "txnd", "scotus", "ca1"):
        court = get_court(court_id)
        print(f"{court_id} -> {get_circuit_for_court(court)}")

    print()
    for user_input in ("Massachusetts", "california", "CA1", "Ohio", "Atlantis"):
        print(f"'{user_input}' -> {resolve_user_circuit(user_input)}")