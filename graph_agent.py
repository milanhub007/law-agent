import os
import sqlite3
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from dotenv import load_dotenv
from langgraph.graph import StateGraph, START, END, MessagesState
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.types import interrupt
from langchain_anthropic import ChatAnthropic
from langchain_core.tools import tool
from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage

from court_listener import search_case_law
from citation_verifier import verify_citation
from extract_cases import extract_cases, check_case, VerificationResult
from ecfr_lookup import search_regulations
from extract_regulations import extract_cfr_citations, check_regulation
from court_hierarchy import label_binding_status, get_court, find_circuit_in_text
from govinfo_lookup import search_statutes
from extract_statutes import extract_usc_citations, check_statute, verify_statute

load_dotenv()


@tool
def ask_user(question: str) -> str:
    """Ask the user a clarifying question BEFORE answering, when missing facts
    would change your answer: e.g. which U.S. state they're in, hourly vs
    salaried, when something happened. Put all your questions in one message."""
    answer = interrupt({"question": question})
    return f"User's answer: {answer}"


tools = [search_case_law, verify_citation, search_regulations, search_statutes, verify_statute, ask_user]
model = ChatAnthropic(model="claude-sonnet-5").bind_tools(tools)

SYSTEM = SystemMessage(content=(
    "You are a legal information assistant for members of the U.S. public, most of "
    "whom have no legal background.\n\n"

    "HOW TO RESPOND\n"
    "- Use plain language: short sentences, no jargon, and explain any legal term you "
    "must use.\n"
    "- You can explain general legal concepts directly from your own knowledge. But any "
    "SPECIFIC case, regulation or statute you name must come from the tools below.\n"
    "- People describe situations, not legal categories. Identify the legal issue for "
    "them.\n"
    "- End substantive answers with 'Your next steps' (2-4 concrete actions) and a "
    "one-line summary of the most important point.\n\n"

    "ANSWER FIRST, THEN INVITE DETAILS\n"
    "- If you can give a useful answer, give it right away. Don't ask questions first. "
    "Base it on the most common situation and state your assumptions briefly, e.g. "
    "'Assuming you're paid hourly...'.\n"
    "- After answering, if more details would make the answer more specific, end with a "
    "short 'To give you a more specific answer' line listing 1-3 things to tell you, "
    "such as their state or whether they're paid hourly.\n"
    "- Only call ask_user BEFORE answering when you genuinely cannot give any useful "
    "answer without the information, for example 'Is this case binding on me?' with no "
    "state given, or a question too vague to identify the legal issue at all.\n\n"

    "TOOLS AND ACCURACY\n"
    "- Specific case: use search_case_law, then verify_citation before citing it.\n"
    "- Federal regulation (CFR): use search_regulations.\n"
    "- Federal statute (U.S. Code): if you know the likely section, confirm it with "
    "verify_statute. Otherwise use search_statutes, which is a keyword search and can be "
    "noisy, so check that the section headings actually fit the question.\n"
    "- Never cite a case, regulation or statute you have not found or verified with "
    "these tools.\n"
    "- Coverage: court opinions (federal and state), federal regulations, and federal "
    "statutes (latest published edition of the U.S. Code). State statutes are NOT "
    "covered. Many everyday issues (landlord-tenant, most consumer and family law) are "
    "state law. When an answer depends on state law, say clearly that you can give "
    "general information but cannot verify that state's specific rules, and point the "
    "person to an official or legal-aid source for their state.\n"
    "- These tools cover U.S. law only. If a case or law is clearly from another country, "
    "don't search for it; say you can't verify it and suggest an appropriate source.\n"
    "- If you can't find authority, say so. Never invent an answer.\n\n"

    "LIMITS AND SAFETY\n"
    "- You provide legal information, not legal advice, and you are not a lawyer. Say "
    "this briefly when giving guidance on someone's specific situation.\n"
    "- Recommend a lawyer or free legal aid when stakes are high: court proceedings, "
    "criminal charges, eviction, large sums, immigration status, or a vulnerable "
    "person. Suggest LawHelp.org to find free legal aid.\n"
    "- Deadlines: if a time limit might apply, flag it prominently, but only state a "
    "specific deadline if it comes from a verified source. Otherwise say a deadline "
    "may apply and urge them to confirm it quickly.\n"
    "- Safety comes first. If someone describes immediate danger, tell them to call "
    "911. Domestic violence: National Domestic Violence Hotline, 1-800-799-7233. "
    "Thoughts of suicide or self-harm: call or text 988. Give these before any legal "
    "information, and don't ask clarifying questions first."
))


def extract_text(message) -> str:
    return "".join(
        b.get("text", "") for b in message.content_blocks if b.get("type") == "text"
    )


class AgentState(MessagesState):
    user_circuit: str
    verification_results: list
    regulation_results: list
    statute_results: list
    binding_results: list


def agent_node(state: AgentState) -> dict:
    response = model.invoke([SYSTEM] + state["messages"])
    return {"messages": [response]}


def capture_jurisdiction_node(state: AgentState) -> dict:
    """Looks for the user's state in their own words: their messages and their
    answers to ask_user. Never in the agent's text, which may mention other states."""
    if state.get("user_circuit"):
        return {}
    for m in state["messages"]:
        text = None
        if isinstance(m, HumanMessage) and isinstance(m.content, str):
            text = m.content
            if text.startswith("Document:") and "\nRequest:" in text:
                text = text.rsplit("\nRequest:", 1)[1]   # ignore states named inside a document
        elif isinstance(m, ToolMessage) and m.name == "ask_user":
            text = m.content
        if text and (circuit := find_circuit_in_text(text)):
            return {"user_circuit": circuit}
    return {}


def verify_node(state: AgentState) -> dict:
    final_text = extract_text(state["messages"][-1])
    try:
        extracted = extract_cases(final_text)
        results = [check_case(c.case_name, c.citation) for c in extracted.cases]
    except Exception as e:
        results = [VerificationResult(
            case_name="(verification step itself failed)", citation=None,
            status="needs_review", cluster_id=None,
            detail=f"Could not complete citation verification due to an internal error: {e}",
            court_id=None,
        )]
    return {"verification_results": results}


def binding_node(state: AgentState) -> dict:
    user_circuit = state.get("user_circuit", "")
    results = []
    for r in state["verification_results"]:
        if r.status not in ("verified", "plausible"):
            continue
        if not r.court_id:
            results.append({"case_name": r.case_name, "binding_status": "unknown (no court data available)"})
            continue
        if not user_circuit:
            results.append({"case_name": r.case_name, "binding_status": "unknown (jurisdiction not provided)"})
            continue
        try:
            court = get_court(r.court_id)
        except Exception:
            results.append({"case_name": r.case_name, "binding_status": "unknown (court lookup failed)"})
            continue
        results.append({"case_name": r.case_name, "binding_status": label_binding_status(court, user_circuit)})
    return {"binding_results": results}


def statute_verify_node(state: AgentState) -> dict:
    final_text = extract_text(state["messages"][-1])
    return {"statute_results": [check_statute(c) for c in extract_usc_citations(final_text)]}


def regulation_verify_node(state: AgentState) -> dict:
    final_text = extract_text(state["messages"][-1])
    citations = extract_cfr_citations(final_text)
    results = [check_regulation(c) for c in citations]
    return {"regulation_results": results}


graph = StateGraph(AgentState)
graph.add_node("agent", agent_node)
graph.add_node("tools", ToolNode(tools, handle_tool_errors=True))
graph.add_node("capture_jurisdiction", capture_jurisdiction_node)
graph.add_node("verify", verify_node)
graph.add_node("binding", binding_node)
graph.add_node("regulation", regulation_verify_node)
graph.add_node("statute", statute_verify_node)

graph.add_edge(START, "capture_jurisdiction")
graph.add_conditional_edges("agent", tools_condition, {"tools": "tools", END: "verify"})
graph.add_edge("tools", "capture_jurisdiction")
graph.add_edge("capture_jurisdiction", "agent")
graph.add_edge("verify", "binding")
graph.add_edge("binding", "regulation")
graph.add_edge("regulation", "statute")
graph.add_edge("statute", END)

# Conversations are saved to this file, so they survive server restarts.
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "conversations.sqlite")

# Tells LangGraph that VerificationResult objects are safe to load back from the file.
serde = JsonPlusSerializer(allowed_msgpack_modules=[("extract_cases", "VerificationResult")])

checkpointer = SqliteSaver(sqlite3.connect(DB_PATH, check_same_thread=False), serde=serde)
app = graph.compile(checkpointer=checkpointer)
