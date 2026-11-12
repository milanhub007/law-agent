import re
import uuid
from document_reader import read_document
from graph_agent import app, extract_text
from voice_io import listen, speak

from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.types import Command

STOP_WORDS = {"stop", "exit", "quit", "goodbye"}


def clean_for_speech(text: str) -> str:
    text = re.sub(r"https?://\S+", "", text)   # don't read URLs aloud
    text = re.sub(r"[#*_`>|]", "", text)       # strip markdown symbols
    text = re.sub(r"\n{2,}", ". ", text)
    return re.sub(r"\s+", " ", text).strip()


def get_input(prompt: str, voice: bool) -> str:
    if not voice:
        return input(prompt).strip()
    print(prompt)
    while True:
        heard = listen()
        if heard:
            return heard
        print("Didn't catch that -- try again.")


def say(text: str, voice: bool) -> None:
    if voice:
        speak(clean_for_speech(text))


def print_checks(result: dict) -> None:
    confirmed = [r for r in result["verification_results"] if r.status in ("verified", "plausible")]
    flagged = [r for r in result["verification_results"] if r.status in ("needs_review", "unverified", "ambiguous")]
    if confirmed or flagged:
        print("--- CASE VERIFICATION ---")
        for r in confirmed:
            print(f"  CONFIRMED: {r.case_name} [{r.status}, court_id {r.court_id}]: {r.detail}")
        for r in flagged:
            print(f"  COULDN'T VERIFY: {r.case_name} [{r.status}]: {r.detail}")

    if result.get("binding_results"):
        print("--- BINDING STATUS ---")
        for r in result["binding_results"]:
            print(f"  {r['case_name']}: {r['binding_status']}")

    if result.get("regulation_results"):
        print("--- REGULATION CHECK ---")
        for r in result["regulation_results"]:
            print(f"  {r['citation']} [{r['status']}]: {r['detail']}")

    if result.get("statute_results"):
        print("--- STATUTE CHECK ---")
        for r in result["statute_results"]:
            link = f" | {r['url']}" if r["url"] else ""
            print(f"  {r['citation']} [{r['status']}]: {r['detail']}{link}")


def main():
    voice = input("Use voice? (y/n): ").strip().lower() == "y"
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}

    file_path = input("Path to a document to discuss (or press Enter to skip): ").strip()
    document_text = read_document(file_path) if file_path else ""
    if document_text:
        print(f"\n[Loaded {len(document_text)} characters from {file_path}]\n")
        intent = get_input("I've read the document. What would you like help with?", voice)
        first_message = f"Document:\n\n{document_text}\n\nRequest: {intent}"
    else:
        first_message = get_input("What's your question?", voice)

    state_input = {"messages": [HumanMessage(content=first_message)], "user_circuit": ""}

    while True:
        result = app.invoke(state_input, config)

        while "__interrupt__" in result:
            question = result["__interrupt__"][0].value["question"]
            print(f"\n[The agent is asking]: {question}")
            say(question, voice)
            answer = get_input("Your answer:", voice)
            result = app.invoke(Command(resume=answer), config)

        for m in result["messages"]:
            if hasattr(m, "tool_calls") and m.tool_calls:
                for call in m.tool_calls:
                    print(f"  [called {call['name']}({call['args']})]")
            if isinstance(m, ToolMessage):
                print(f"  [tool result: {m.content}]")

        answer_text = extract_text(result["messages"][-1])
        print("\n" + answer_text + "\n")
        print_checks(result)
        say(answer_text, voice)

        stop_hint = "say 'stop'" if voice else "press Enter"
        follow_up = get_input(f"\nYou ({stop_hint} to end):", voice)
        if not follow_up or follow_up.lower().strip(" .!") in STOP_WORDS:
            break
        state_input = {"messages": [HumanMessage(content=follow_up)]}


if __name__ == "__main__":
    main()