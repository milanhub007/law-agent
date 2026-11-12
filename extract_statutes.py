import re
from langchain_core.tools import tool

from govinfo_lookup import latest_edition, title_sections

USC_CITATION_PATTERN = re.compile(
    r"(\d+)\s*U\.?\s?S\.?\s?C\.?\s*(?:§+\s*)?(\d+[A-Za-z0-9\-]*)", re.IGNORECASE
)


@tool
def verify_statute(citation: str) -> str:
    """Check that a specific U.S. Code citation exists, e.g. '29 U.S.C. § 207',
    and get its official section heading. Use this when you already know the
    likely statute -- it's precise, unlike search_statutes. Federal statutes only."""
    r = check_statute(citation)
    if r["status"] == "verified":
        return f"VERIFIED: {r['citation']} -- {r['detail']}. URL: {r['url']}"
    return f"{r['status'].upper()}: {r['detail']}"


def extract_usc_citations(text: str) -> list[str]:
    seen, out = set(), []
    for title, section in USC_CITATION_PATTERN.findall(text):
        c = f"{title} U.S.C. § {section}"
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def check_statute(citation: str) -> dict:
    m = USC_CITATION_PATTERN.search(citation)
    if not m:
        return {"citation": citation, "status": "unverified", "url": None,
                "detail": f"'{citation}' doesn't look like a U.S. Code citation I can parse."}

    title, section = m.groups()
    package_id = latest_edition(title)
    if not package_id:
        return {"citation": citation, "status": "needs_review", "url": None,
                "detail": f"Couldn't find a recent published edition of title {title}."}

    hit = title_sections(package_id).get(section)
    edition = package_id.split("-")[1]
    if hit:
        return {"citation": citation, "status": "verified",
                "url": f"https://www.govinfo.gov/link/uscode/{title}/{section}",
                "detail": f"Found: {hit['heading']} ({edition} edition)"}
    return {"citation": citation, "status": "unverified", "url": None,
            "detail": f"No section {section} in title {title} ({edition} edition)."}


if __name__ == "__main__":
    print(extract_usc_citations("See 29 U.S.C. § 207 and 42 USC 1983, but not 555 U.S. 223."))
    for c in ("42 U.S.C. § 1983", "29 U.S.C. 207", "42 U.S.C. § 999999"):
        print(check_statute(c))