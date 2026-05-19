"""
Utilitários puros do Conversational Front.

Regras:
- Sem chamadas de rede.
- Sem acesso a banco.
- Sem dependência de estado global.
- Apenas funções determinísticas.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict


def split_sentences_pt(text: str) -> list[str]:
    try:
        t = str(text or "").strip()
        if not t:
            return []
        parts = re.split(r'(?<=[.!?])\s+', t)
        return [p.strip() for p in parts if p.strip()]
    except Exception:
        return [str(text or "").strip()]


def has_question(text: str) -> bool:
    try:
        return "?" in str(text or "")
    except Exception:
        return False


def strip_trailing_question(text: str) -> str:
    try:
        t = str(text or "").strip()
        qpos = t.rfind("?")
        if qpos == -1:
            return t
        return t[:qpos].strip()
    except Exception:
        return str(text or "").strip()


def normalize_identity_text(value: Any) -> str:
    try:
        s = str(value or "").strip().lower()
        s = "".join(
            ch for ch in s
            if ch.isalnum() or ch.isspace()
        )
        return " ".join(s.split())
    except Exception:
        return ""


def extract_json_string_field(raw: str, field_name: str) -> str:
    try:
        s = str(raw or "")
        if not s:
            return ""
        m = re.search(
            rf'"{re.escape(field_name)}"\s*:\s*"((?:\\.|[^"\\])*)"',
            s,
            flags=re.DOTALL,
        )
        if not m:
            # Salvage para JSON truncado no meio do valor string.
            # Ex.: {"replyText":"Olá...   sem aspas/fecha-chaves finais.
            start = re.search(
                rf'"{re.escape(field_name)}"\s*:\s*"',
                s,
                flags=re.DOTALL,
            )
            if not start:
                return ""

            frag = s[start.end():]
            buf = []
            escaped = False
            for ch in frag:
                if escaped:
                    buf.append(ch)
                    escaped = False
                    continue
                if ch == "\\":
                    escaped = True
                    buf.append(ch)
                    continue
                if ch == '"':
                    break
                buf.append(ch)

            val = "".join(buf).strip()
            if not val:
                return ""
            val = val.replace(r"\/", "/")
            val = val.replace(r'\"', '"')
            val = val.replace(r"\n", "\n")
            val = val.replace(r"\t", "\t")
            val = val.replace(r"\r", "")
            return str(val).strip()

        val = m.group(1)
        val = val.replace(r"\/", "/")
        val = val.replace(r'\"', '"')
        val = val.replace(r"\n", "\n")
        val = val.replace(r"\t", "\t")
        val = val.replace(r"\r", "")
        return str(val).strip()
    except Exception:
        return ""


def extract_json_object_field(raw: str, field_name: str) -> Dict[str, Any]:
    try:
        s = str(raw or "")
        if not s:
            return {}
        m = re.search(
            rf'"{re.escape(field_name)}"\s*:\s*(\{{.*?\}})',
            s,
            flags=re.DOTALL,
        )
        if not m:
            return {}
        obj = json.loads(m.group(1))
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def looks_like_dialogue_stub(text: str) -> bool:
    """
    Detecta saídas em formato de falas rotuladas, script curto ou abertura solta.
    Regra estrutural: sem listas por segmento e sem frases prontas.
    """
    try:
        t = str(text or "").strip()
        if not t:
            return True

        if len(t) < 24:
            return True

        sentences = [s.strip() for s in split_sentences_pt(t) if str(s).strip()]
        first = sentences[0] if sentences else t

        if len(sentences) == 1 and "?" in t:
            return True

        # rótulos de fala / script
        if re.search(r"(^|\n)\s*\*{0,2}[A-Za-zÀ-ÿ _-]{2,20}\*{0,2}\s*:", t):
            return True

        if re.search(r"(^|\n)\s*[-–—]\s*[A-Za-zÀ-ÿ _-]{2,20}\s*:", t):
            return True

        # abertura com sinal típico de fala roteirizada
        if re.match(r'^[\-\–\—"\“\”\'«»]', first):
            return True

        if first.endswith("?"):
            return True

        return False
    except Exception:
        return False


def looks_like_technical_output(text: str) -> bool:
    try:
        t = str(text or "").strip()
        if not t:
            return False
        if t.startswith("PACK_"):
            return True
        if "\nPACK_" in t:
            return True
        if "segment_value_map_v1" in t or "value_packs_v1" in t:
            return True
        return False
    except Exception:
        return False

