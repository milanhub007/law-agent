"""Web API for the legal agent.

Run:   uvicorn api:app --reload
Open:  http://127.0.0.1:8000        (the chat page)
       http://127.0.0.1:8000/docs   (API test page)
"""
import os
import tempfile
import uuid

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from pydantic import BaseModel
from langchain_core.messages import HumanMessage
from langgraph.types import Command

from graph_agent import app as agent, extract_text
from document_reader import read_document


app = FastAPI(title="Legal Information Agent")
INDEX_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "index.html")

ALLOWED_TYPES = {".txt", ".pdf", ".docx"}
MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB
MAX_DOC_CHARS = 100_000  # keeps very long documents from making answers slow and costly


@app.get("/")
def home():
    return FileResponse(INDEX_PATH)


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


class ResumeRequest(BaseModel):
    session_id: str
    answer: str


def config_for(session_id: str) -> dict:
    return {"configurable": {"thread_id": session_id}}


def build_response(session_id: str, result: dict) -> dict:
    """Turns the graph's result into JSON: either a question for the user or an answer."""
    if "__interrupt__" in result:
        return {
            "session_id": session_id,
            "type": "question",
            "question": result["__interrupt__"][0].value["question"],
        }

    answer = extract_text(result["messages"][-1])
    return {
        "session_id": session_id,
        "type": "answer",
        "answer": answer,
        "cases": [r.model_dump() for r in result.get("verification_results", [])],
        "binding": result.get("binding_results", []),
        "regulations": result.get("regulation_results", []),
        "statutes": result.get("statute_results", []),
    }


def has_conversation(session_id: str) -> bool:
    """False if the server has no saved state for this session, e.g. after a restart."""
    return bool(agent.get_state(config_for(session_id)).values.get("messages"))


@app.post("/chat")
def chat(req: ChatRequest):
    session_id = req.session_id
    if session_id and not has_conversation(session_id):
        session_id = None   # server restarted and forgot it: start a fresh conversation
    is_new = session_id is None
    session_id = session_id or str(uuid.uuid4())

    state_input = {"messages": [HumanMessage(content=req.message)]}
    if is_new:
        state_input["user_circuit"] = ""

    result = agent.invoke(state_input, config_for(session_id))
    return build_response(session_id, result)


@app.post("/upload")
def upload(file: UploadFile = File(...)):
    """Extracts the text from an uploaded document and returns it. Nothing is stored:
    the page sends the text along with the user's next message."""
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_TYPES:
        raise HTTPException(400, f"Unsupported file type '{ext or 'none'}'. Please upload a .txt, .pdf or .docx file.")

    data = file.file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(400, "This file is too large. The limit is 5 MB.")

    # document_reader works on file paths, so write to a temporary file first.
    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
        tmp.write(data)
        path = tmp.name
    try:
        text = read_document(path).strip()
    except Exception as e:
        raise HTTPException(400, f"Couldn't read this file: {e}")
    finally:
        os.remove(path)

    if not text:
        raise HTTPException(400, "No text was found in this file. If it's a scanned PDF, "
                                 "it needs text recognition (OCR), which isn't supported yet.")

    return {
        "filename": file.filename,
        "text": text[:MAX_DOC_CHARS],
        "chars": len(text),
        "truncated": len(text) > MAX_DOC_CHARS,
    }


@app.post("/resume")
def resume(req: ResumeRequest):
    if not agent.get_state(config_for(req.session_id)).next:
        raise HTTPException(
            status_code=409,
            detail="This conversation is no longer waiting for an answer, "
                   "probably because the server restarted.",
        )
    result = agent.invoke(Command(resume=req.answer), config_for(req.session_id))
    return build_response(req.session_id, result)