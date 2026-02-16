# domain/contact_memory.py
# Memória por contato (cliente) para o MEI Robô.
#
# Objetivo:
# - Dado (uid, telefone, payload Meta), montar um "resumo" curto do contato:
#   nome, telefone, tags, histórico textual e últimos registros (timeline/acervoContato).
# - Isso é passado como contexto extra para o mini-RAG do acervo.
#
# ATIVAÇÃO:
# - CONTROLADA POR ENV: CONTACT_MEMORY_MODE
#   - off  -> desativa (padrão)
#   - read / write / on / full -> ativa leitura
#
# Futuro:
# - "write" pode ser usado para o bot gravar eventos automáticos (ex.: nascimento do filho etc.)

import logging
import os
import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

try:
    from services.db import db as DB  # type: ignore
except Exception:
    DB = None


def _db_ready() -> bool:
    return DB is not None


# ===== Helpers de telefone (reuso de lógica, sem dependência circular) =====
try:
    from services.phone_utils import br_equivalence_key, digits_only  # type: ignore
except Exception:
    import re as _re

    _DIGITS_RE = _re.compile(r"\D+")

    def digits_only(s: str) -> str:
        return _DIGITS_RE.sub("", s or "")

    def _ensure_cc_55(d: str) -> str:
        d = digits_only(d)
        if d.startswith("00"):
            d = d[2:]
        if not d.startswith("55"):
            d = "55" + d
        return d

    def _br_split(msisdn: str) -> Tuple[str, str, str]:
        d = _ensure_cc_55(msisdn)
        cc = d[:2]
        rest = d[2:]
        ddd = rest[:2] if len(rest) >= 10 else rest[:2]
        local = rest[2:]
        return cc, ddd, local

    def br_equivalence_key(msisdn: str) -> str:
        cc, ddd, local = _br_split(msisdn)
        local8 = digits_only(local)[-8:]
        return f"{cc}{ddd}{local8}"


# ===== Feature flag =====
def contact_memory_enabled_for(uid: str) -> bool:
    """
    Controla se a memória por contato está ativa para esse MEI.

    Regras:
      - CONTACT_MEMORY_MODE in {read, write, on, full} -> ON
      - Se CONTACT_MEMORY_UIDS (lista de uids) estiver setada,
        só ativa para esses uids.
    """
    mode = (os.getenv("CONTACT_MEMORY_MODE") or "").strip().lower()
    if mode in ("read", "write", "on", "full"):
        # Se houver allowlist, respeita
        allow_raw = os.getenv("CONTACT_MEMORY_UIDS") or ""
        allow = [x.strip() for x in allow_raw.split(",") if x.strip()]
        if allow:
            return bool(uid and uid in allow)
        return True
    return False


# ===== Lookup do cliente =====
def _find_cliente_doc(uid: str, telefone: str, value: Dict[str, Any]) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """
    Tenta achar o documento do cliente em profissionais/{uid}/clientes
    usando telefone e waKey.
    """
    if not _db_ready() or not uid:
        return None, None

    digits = ""
    try:
        from services.phone_utils import digits_only as _digits_only  # type: ignore
        digits = _digits_only(telefone or "")
    except Exception:
        digits = digits_only(telefone or "")

    wa_id = ""
    nome_contato = ""
    try:
        value = value or {}
        contacts = value.get("contacts") or []
        if contacts and isinstance(contacts, list):
            wa_id = contacts[0].get("wa_id") or ""
            prof = contacts[0].get("profile") or {}
            nome_contato = (prof.get("name") or "").strip()
    except Exception:
        pass

    eq_key = ""
    try:
        eq_key = br_equivalence_key(wa_id or telefone or "")
    except Exception:
        eq_key = ""

    col = DB.collection(f"profissionais/{uid}/clientes")

    # 1) telefone exato (campo telefone normalizado)
    if digits:
        try:
            q = col.where("telefone", "==", digits).limit(1).stream()
            for d in q:
                data = d.to_dict() or {}
                if nome_contato and not data.get("nome"):
                    data.setdefault("nome", nome_contato)
                return d.id, data
        except Exception as e:
            logging.info("[CONTACT_MEMORY] lookup por telefone falhou: %s", e)

    # 1b) compat: telefone_v2.digits (UI contatos.html)
    if digits:
        try:
            q = col.where("telefone_v2.digits", "==", digits).limit(1).stream()
            for d in q:
                data = d.to_dict() or {}
                if nome_contato and not data.get("nome"):
                    data.setdefault("nome", nome_contato)
                return d.id, data
        except Exception as e:
            logging.info("[CONTACT_MEMORY] lookup por telefone_v2.digits falhou: %s", e)

    # 2) waKey, se existir
    if eq_key:
        try:
            q = col.where("waKey", "==", eq_key).limit(1).stream()
            for d in q:
                data = d.to_dict() or {}
                if nome_contato and not data.get("nome"):
                    data.setdefault("nome", nome_contato)
                return d.id, data
        except Exception as e:
            logging.info("[CONTACT_MEMORY] lookup por waKey falhou: %s", e)

    # 2b) compat: telefone_v2.waKey (UI contatos.html)
    if eq_key:
        try:
            q = col.where("telefone_v2.waKey", "==", eq_key).limit(1).stream()
            for d in q:
                data = d.to_dict() or {}
                if nome_contato and not data.get("nome"):
                    data.setdefault("nome", nome_contato)
                return d.id, data
        except Exception as e:
            logging.info("[CONTACT_MEMORY] lookup por telefone_v2.waKey falhou: %s", e)

    return None, None


# ===== Helpers de formatação =====
def _shorten(text: str, limit: int) -> str:
    t = (text or "").strip()
    if len(t) <= limit:
        return t
    return t[: limit - 3].rstrip() + "..."


def _safe_date(dt_val: Any) -> Optional[str]:
    if not dt_val:
        return None
    try:
        if isinstance(dt_val, datetime):
            return dt_val.astimezone(timezone.utc).isoformat()[:10]
        if isinstance(dt_val, str):
            # tenta pegar só a parte de data
            if "T" in dt_val:
                return dt_val.split("T", 1)[0]
            return dt_val[:10]
    except Exception:
        return None
    return None


# ===== Contexto principal =====
def build_contact_context(
    uid: str,
    telefone: str,
    value: Dict[str, Any],
    *,
    max_chars: int = 800,
) -> str:
    """
    Monta um resumo textual do contato para ser usado como contexto
    extra em cima do acervo do MEI.

    Estrutura típica do retorno (em linguagem natural, simples):
      "Nome do contato: Ana Souza | Telefone: 55... |
       Tags: pediatria, retorno | Histórico do contato (resumo): ... |
       Registros recentes do contato:
        - 2025-01-10: Filho nasceu saudável...
        - 2025-02-01: Retorno de revisão, tudo ok..."

    Tudo em uma string compacta, para caber junto com o prompt/RAG.
    """
    if not contact_memory_enabled_for(uid):
        return ""

    cliente_id, cliente = _find_cliente_doc(uid, telefone, value or {})
    if not cliente_id or not cliente:
        return ""

    partes: List[str] = []

    nome = (cliente.get("nome") or cliente.get("nomeContato") or "").strip()
    if nome:
        partes.append(f"Nome do contato: {nome}")

    tel = (cliente.get("telefone") or "").strip()
    if tel:
        partes.append(f"Telefone: {tel}")

    tags = cliente.get("tags") or cliente.get("etiquetas") or []
    if isinstance(tags, list) and tags:
        tags_str = ", ".join(sorted(str(t) for t in tags if t))
        if tags_str:
            partes.append(f"Tags: {tags_str}")

    historico = (
        cliente.get("historico")
        or cliente.get("anotacoes")
        or cliente.get("anotações")
        or cliente.get("obs")
        or cliente.get("observacoes")
        or cliente.get("observações")
        or ""
    )
    if historico:
        partes.append("Histórico do contato (resumo): " + _shorten(str(historico), 400))

    eventos: List[str] = []

    if _db_ready():
        # 1) timeline / histórico de eventos (subcoleções opcionais)
        try:
            for subname in ("timeline", "historico", "historicoEventos"):
                try:
                    col = (
                        DB.collection(f"profissionais/{uid}/clientes/{cliente_id}/{subname}")
                        .order_by("createdAt", direction="DESCENDING")
                        .limit(5)
                    )
                    docs = list(col.stream())
                    if not docs:
                        continue

                    for d in docs:
                        data = d.to_dict() or {}
                        txt = (
                            data.get("texto")
                            or data.get("descricao")
                            or data.get("descricaoEvento")
                            or ""
                        )
                        if not txt:
                            continue
                        dt_label = _safe_date(data.get("createdAt"))
                        prefix = f"{dt_label}: " if dt_label else ""
                        eventos.append(" - " + prefix + _shorten(str(txt), 120))
                    if eventos:
                        break
                except Exception:
                    continue
        except Exception as e:
            logging.info("[CONTACT_MEMORY] erro ao ler timeline: %s", e)

        # 2) acervo específico do contato (se existir)
        try:
            col = (
                DB.collection(f"profissionais/{uid}/clientes/{cliente_id}/acervoContato")
                .order_by("updatedAt", direction="DESCENDING")
                .limit(3)
            )
            docs = list(col.stream())
            for d in docs:
                data = d.to_dict() or {}
                titulo = data.get("titulo") or data.get("nome") or "item"
                resumo = data.get("resumoCurto") or data.get("descricao") or ""
                dt_label = _safe_date(data.get("updatedAt") or data.get("createdAt"))
                linha = f" - {titulo}"
                if dt_label:
                    linha += f" ({dt_label})"
                if resumo:
                    linha += f": {_shorten(str(resumo), 100)}"
                eventos.append(linha)
        except Exception as e:
            logging.info("[CONTACT_MEMORY] erro ao ler acervoContato: %s", e)

        # 3) compat: anexos do contato (UI usa subcoleção "files")
        try:
            col = (
                DB.collection(f"profissionais/{uid}/clientes/{cliente_id}/files")
                .order_by("updatedAt", direction="DESCENDING")
                .limit(3)
            )
            docs = list(col.stream())
            for d in docs:
                data = d.to_dict() or {}
                nome = data.get("name") or data.get("filename") or data.get("originalName") or "arquivo"
                ctype = data.get("contentType") or data.get("mime") or ""
                dt_label = _safe_date(data.get("updatedAt") or data.get("createdAt"))
                linha = f" - Anexo: {nome}"
                if ctype:
                    linha += f" [{ctype}]"
                if dt_label:
                    linha += f" ({dt_label})"
                eventos.append(linha)
        except Exception as e:
            logging.info("[CONTACT_MEMORY] erro ao ler files: %s", e)

    if eventos:
        partes.append("Registros recentes do contato:")
        partes.extend(eventos)

    ctx = " | ".join(partes)
    if len(ctx) > max_chars:
        ctx = ctx[: max_chars - 3].rstrip() + "..."
    return ctx

# ===============================
# WRITE — EVENTOS NA LINHA DO TEMPO
# ===============================

def _server_ts() -> Any:
    """
    Preferencialmente usa SERVER_TIMESTAMP do Firestore.
    Fallback: datetime UTC.
    """
    try:
        from google.cloud import firestore  # type: ignore
        return firestore.SERVER_TIMESTAMP
    except Exception:
        return datetime.now(timezone.utc)


def _sha1_16(s: str) -> str:
    return hashlib.sha1((s or "").encode("utf-8")).hexdigest()[:16]


def store_contact_event(
    uid: str,
    telefone: str,
    summary: str,
    *,
    importance: int = 1,
    dedupe_key: Optional[str] = None,
    source: str = "auto",
) -> bool:
    """
    Grava um evento compacto na timeline do contato.

    - NÃO salva conversa inteira
    - dedupe por dedupeKey
    - mantém histórico completo (não apaga eventos antigos)
    - atualiza profissionais/{uid}/clientes/{cid}.lastEvent
    """
    uid = (uid or "").strip()
    telefone = (telefone or "").strip()
    summary = (summary or "").strip()
    if not uid or not telefone or not summary:
        return False

    if not contact_memory_enabled_for(uid):
        return False

    if not _db_ready():
        return False

    # resolve contato
    cliente_id, _cliente = _find_cliente_doc(uid, telefone, {})
    if not cliente_id:
        return False

    ded = (dedupe_key or "").strip()
    if not ded:
        ded = _sha1_16(summary)

    try:
        col = DB.collection(f"profissionais/{uid}/clientes/{cliente_id}/timeline")

        # dedupe: se já existe um evento com a mesma dedupeKey, não grava de novo
        try:
            q = col.where("dedupeKey", "==", ded).limit(1).stream()
            for _ in q:
                return False
        except Exception:
            pass

        # cria evento
        doc = col.document()
        doc.set(
            {
                "texto": summary[:180],
                "type": "auto",
                "importance": 3 if int(importance) >= 3 else (2 if int(importance) == 2 else 1),
                "dedupeKey": ded[:64],
                "source": (source or "auto")[:32],
                "createdAt": _server_ts(),
            }
        )

        # atualiza lastEvent no doc do cliente
        try:
            DB.collection(f"profissionais/{uid}/clientes").document(cliente_id).set(
                {
                    "lastEvent": {
                        "summary": summary[:180],
                        "importance": 3 if int(importance) >= 3 else (2 if int(importance) == 2 else 1),
                        "dedupeKey": ded[:64],
                        "createdAt": _server_ts(),
                        "source": (source or "auto")[:32],
                    }
                },
                merge=True,
            )
        except Exception:
            pass

        return True
    except Exception as e:
        logging.info("[CONTACT_MEMORY][WRITE] falhou: %s", e)
        return False
