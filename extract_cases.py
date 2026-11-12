import json
from typing import Literal, Optional
from pydantic import BaseModel, Field, field_validator
from langchain_anthropic import ChatAnthropic
from dotenv import load_dotenv

from court_listener import search_case_law
from citation_verifier import _lookup_citation

load_dotenv()


class CaseMention(BaseModel):
    case_name: str = Field(description="The case name as mentioned, e.g. 'Saucier v. Katz'")
    citation: Optional[str] = Field(default=None, description="The citation string if given, else null")


class ExtractedCases(BaseModel):
    cases: list[CaseMention] = Field(description="Every case mentioned by name, in order of appearance")

    @field_validator("cases", mode="before")
    @classmethod
    def _parse_stringified_cases(cls, v):
        # The model sometimes returns the field as a JSON string -- either the list
        # itself ('[...]') or the whole object nested inside it ('{"cases": []}').
        if isinstance(v, str):
            v = json.loads(v)
        if isinstance(v, dict):
            v = v.get("cases", [])
        return v


class NameMatchJudgment(BaseModel):
    decision: Literal["match", "no_match", "uncertain"]
    matched_cluster_id: Optional[int] = Field(default=None, description="cluster_id of the match, only if decision is "
                                                                        "'match'")
    reasoning: str = Field(description="one sentence explaining the decision")


model = ChatAnthropic(model="claude-sonnet-5")
extractor = model.with_structured_output(ExtractedCases).with_retry(stop_after_attempt=3)
judge = model.with_structured_output(NameMatchJudgment).with_retry(stop_after_attempt=3)


class VerificationResult(BaseModel):
    case_name: str
    citation: Optional[str]
    status: Literal["verified", "plausible", "needs_review", "unverified", "ambiguous"]
    cluster_id: Optional[int]
    detail: str
    court_id: Optional[str] = None


def extract_cases(text: str) -> ExtractedCases:
    return extractor.invoke(
        f"List every case mentioned by name in this text, with its citation if one is given:\n\n{text}"
    )


def check_case(case_name: str, citation: str | None) -> VerificationResult:
    if citation:
        r = _lookup_citation(citation)
        return VerificationResult(
            case_name=case_name, citation=citation,
            status=r["status"], cluster_id=r["cluster_id"], detail=r["detail"],
            court_id=r.get("court_id"),
        )

    search_result = search_case_law.invoke({"query": case_name})
    judgment = judge.invoke(
        f"A document claims there is a case called '{case_name}'. Here are results "
        f"from a case-law database search:\n\n{search_result}\n\n"
        f"Does ANY ONE of these results refer to the SAME case as '{case_name}'? "
        f"Be strict -- a shared surname is not enough; the full case name must substantially match."
    )
    status = {"match": "plausible", "uncertain": "needs_review", "no_match": "unverified"}[judgment.decision]
    return VerificationResult(
        case_name=case_name, citation=None,
        status=status, cluster_id=judgment.matched_cluster_id, detail=judgment.reasoning,
        court_id=None,  # known gap -- would need a third hop (cluster -> docket) not built yet
    )