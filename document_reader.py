import os
from pypdf import PdfReader
import docx


def read_document(file_path: str) -> str:
    """Reads a plain text file. PDF/DOCX support can come later, as its own lesson."""
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"No such file: {file_path}")

    ext = os.path.splittext(file_path)[1].lower()

    if ext == ".txt":
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()

    elif ext == ".pdf":
        reader = PdfReader(file_path)
        pages_text = [page.extract_text() or "" for page in reader.pages]
        return "\n".join(pages_text)

    elif ext == ".docx":
        doc = docx.Document(file_path)
        return "\n".join(p.text for p in doc.paragraphs)

    else:
        raise ValueError(f"Unsupported file type: {ext} (supported: .txt, .pdf, .docx)")


if __name__ == "__main__":
    text = read_document("sample.txt")
    print(f"length: {len(text)} chars\n")
    print(text[:300])
