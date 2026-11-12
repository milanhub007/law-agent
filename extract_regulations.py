import re
from ecfr_lookup import _lookup_section_raw

CFR_CITATION_PATTERN = re.compile(r"(\d{1,3})\s*CFR\s*§?\s*(\d+(?:\.\d+)*)", re.IGNORECASE)


def extract_cfr_citations(text: str) -> list[str]:
    matches = CFR_CITATION_PATTERN.findall(text)
    seen = set()
    citations = []
    for title, section in matches:
        normalized = f"{title} CFR {section}"
        if normalized not in seen:
            seen.add(normalized)
            citations.append(normalized)
    return citations


def check_regulation(citation: str) -> dict:
    match = CFR_CITATION_PATTERN.search(citation)
    if not match:
        return {"citation": citation, "status": "unverified",
                "detail": f"'{citation}' doesn't look like a CFR citation I can parse."}

    title, section = match.groups()
    part = section.split(".")[0]

    try:
        results = _lookup_section_raw(title, part, per_page=1000)
    except Exception as e:
        return {"citation": citation, "status": "needs_review", "detail": f"Lookup failed: {e}"}

    for r in results:
        if r.get("hierarchy", {}).get("section") == section:
            heading = r.get("headings", {}).get("section") or r.get("hierarchy_headings", {}).get("section") or ""
            heading = re.sub(r"</?strong>", "", heading)
            return {"citation": citation, "status": "verified", "detail": f"Found: {heading}"}

    return {
        "citation": citation, "status": "unverified",
        "detail": f"'{citation}' was not found among {len(results)} sections in part {part}.",
    }


if __name__ == "__main__":
    sample_text = "This references 40 CFR 112.7 and also 30 CFR 254.46 for spill rules."
    citations = extract_cfr_citations(sample_text)
    print(f"Extracted: {citations}")
    for c in citations:
        print(check_regulation(c))