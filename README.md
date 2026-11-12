# Case Law Agent

A legal information agent built with LangGraph and Claude. It searches case law via CourtListener, verifies citations, looks up statutes (GovInfo) and regulations (eCFR), and can analyze uploaded documents (.txt, .pdf, .docx).

## Setup

```bash
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS/Linux
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and fill in your API keys:

- `ANTHROPIC_API_KEY` — https://console.anthropic.com
- `COURT_LISTENER_API_KEY` — https://www.courtlistener.com/help/api/
- `GOVINFO_API_KEY` — https://api.govinfo.gov/docs/

## Run

Web app:

```bash
uvicorn api:app --reload
```

Then open http://127.0.0.1:8000 (chat page) or http://127.0.0.1:8000/docs (API docs).

Command-line chat:

```bash
python chat.py
```

## Disclaimer

This tool provides legal information, not legal advice.
