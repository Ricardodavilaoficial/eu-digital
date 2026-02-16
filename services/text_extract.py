# services/text_extract.py
from __future__ import annotations
import io
from typing import Tuple

def extract_text_from_bytes(data: bytes, filename: str) -> Tuple[str, str]:
    """
    Retorna (texto, kind) onde kind ∈ {"pdf","docx","text","unknown"}.
    """
    name = (filename or "").lower().strip()

    # PDF
    if name.endswith(".pdf"):
        try:
            from pypdf import PdfReader  # type: ignore
            reader = PdfReader(io.BytesIO(data))
            parts = []
            for page in reader.pages:
                try:
                    parts.append(page.extract_text() or "")
                except Exception:
                    pass
            text = "\n".join([p.strip() for p in parts if p and p.strip()])
            return (text, "pdf")
        except Exception:
            return ("", "pdf")

    # DOCX
    if name.endswith(".docx"):
        try:
            from docx import Document  # type: ignore
            doc = Document(io.BytesIO(data))
            text = "\n".join([p.text for p in doc.paragraphs if p.text and p.text.strip()])
            return (text.strip(), "docx")
        except Exception:
            return ("", "docx")

    # TXT/MD
    if name.endswith(".txt") or name.endswith(".md"):
        try:
            return (data.decode("utf-8", errors="ignore").strip(), "text")
        except Exception:
            return ("", "text")

    return ("", "unknown")
