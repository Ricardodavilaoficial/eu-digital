# services/wa_bot.py
# Façada v1 — MEI Robô (30/09/2025)
# Objetivo: manter a fachada estável enquanto extraímos módulos internos.
# - Se NLU_MODE != "v1", delega tudo para services/wa_bot_legacy.py (comportamento atual).
# - Se NLU_MODE == "v1", usa pipeline novo se disponível; caso contrário, cai no legacy.
# - Sem mudar rotas/integrações do backend. Safe-by-default.
#
# Entradas principais (mantidas):
#   - process_inbound(event)  : ponto de entrada genérico (webhook/serviços)
#   - reply_to_text(uid, text, ctx=None)
#   - schedule_appointment(uid, ag, *, allow_fallback=True)
#   - reschedule_appointment(uid, ag_id, updates)
#
# Observações:
# - Este arquivo NÃO inclui regra de negócio pesada.
# - O legacy é responsável por todos os detalhes enquanto migramos por etapas.
# - Logs claros para diagnosticar flags/queda de módulos.
#
# Versões:
#   v1.0.0-fachada (2025-09-30) — primeira fachada com delegação condicional.

from __future__ import annotations

import os
import json
import traceback
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple, Callable  # <- acrescentado Callable

# Runtime mode router (sales vs operational)

logger = logging.getLogger(__name__)

__version__ = "1.0.0-fachada"
BUILD_DATE = "2025-09-30"

# Feature flags (com defaults seguros)
NLU_MODE = os.getenv("NLU_MODE", "legacy").strip().lower()  # "v1" | "legacy"
DEMO_MODE = os.getenv("DEMO_MODE", "0").strip() in ("1", "true", "True")
SUPPORT_V2 = os.getenv("SUPPORT_V2", "0").strip() in ("1", "true", "True")

# ==========================================================
# Conversational Front (IA inicial com hard cap)
# ==========================================================
CONVERSATIONAL_FRONT = os.getenv("CONVERSATIONAL_FRONT", "false").strip().lower() in ("1","true","yes","on")
MAX_AI_TURNS = int(os.getenv("MAX_AI_TURNS", "5") or 5)
POST5_AI_ENABLED = os.getenv("POST5_AI_ENABLED", "true").strip().lower() in ("1","true","yes","on")

# ==========================================================
# Front KB Snapshot (compacto, com teto)
# - Firestore é fonte da verdade
# - O front NÃO consulta Firestore
# ==========================================================
FRONT_KB_MAX_CHARS = int(os.getenv("FRONT_KB_MAX_CHARS", "2500") or 2500)
FRONT_KB_MAX_CHARS_PACKS_V1 = int(
    os.getenv("FRONT_KB_MAX_CHARS_PACKS_V1", "12000") or 12000
)

LEAD_MEMORY_TTL_DAYS = 180
LEAD_MEMORY_SUMMARY_MAX_CHARS = 500

# -------------------------------------------------------------------
# Legacy deve ser "lazy": só importa quando realmente for necessário
# -------------------------------------------------------------------
_legacy = None  # type: ignore
_HAS_LEGACY = True  # assume que existe; só marcamos False se o import falhar quando tentarmos usar

def _get_legacy_module():
    global _legacy, _HAS_LEGACY
    if _legacy is not None:
        return _legacy
    try:
        from . import wa_bot_legacy as mod  # import sob demanda
        _legacy = mod
        return _legacy
    except Exception as e:
        _HAS_LEGACY = False
        raise RuntimeError(f"[WA_BOT][FACHADA] legacy indisponível: {e}")

# Tentativa de carregar pipeline novo (opcional nestas etapas iniciais)
try:
    from .nlu import intent as _nlu_intent  # opcional
    from .domain import pricing as _pricing  # opcional
    from .domain.scheduling import engine as _sched_engine  # opcional
    _HAS_NEW = True
except Exception as e:
    _nlu_intent = None  # type: ignore
    _pricing = None     # type: ignore
    _sched_engine = None  # type: ignore
    _HAS_NEW = False
    # Comentado para não poluir logs:
    # print(f"[WA_BOT][FACHADA] Pipeline novo indisponível (ok nesta fase): {e}", flush=True)


def _using_legacy() -> bool:
    """Decide se devemos usar o legacy nesta chamada."""
    if NLU_MODE != "v1":
        return True
    if not _HAS_NEW:
        return True
    return False


def _ensure_legacy(func_name: str):
    # força import sob demanda; se falhar, levanta erro claro
    _get_legacy_module()


# =============================
# Pontos de entrada "estáveis"
# =============================

def healthcheck() -> Dict[str, Any]:
    """Retorna informações leves para diagnóstico."""
    return {
        "module": "services.wa_bot (fachada)",
        "version": __version__,
        "build_date": BUILD_DATE,
        "nlu_mode": NLU_MODE,
        "demo_mode": DEMO_MODE,
        "has_legacy": bool(_HAS_LEGACY),
        "has_new_pipeline": bool(_HAS_NEW),
    }


def process_inbound(event: Dict[str, Any]) -> Dict[str, Any]:
    """Entrada genérica (ex.: webhook do WhatsApp)."""
    try:
        if _using_legacy():
            _ensure_legacy("process_inbound")
            legacy = _get_legacy_module()
            if hasattr(legacy, "process_inbound"):
                return legacy.process_inbound(event)  # type: ignore[attr-defined]
            # Legacy não possui process_inbound: não tratar como erro; sinalizar e seguir
            return {"ok": False, "reason": "legacy_no_process_inbound", "stage": "fachada"}
        # v1 habilitado mas mantemos fallback no legacy nesta fase
        _ensure_legacy("process_inbound(v1-fallback)")
        legacy = _get_legacy_module()
        if hasattr(legacy, "process_inbound"):
            return legacy.process_inbound(event)  # type: ignore[attr-defined]
        return {"ok": False, "reason": "legacy_no_process_inbound(v1)", "stage": "fachada"}
    except Exception as e:
        print(f"[WA_BOT][FACHADA] process_inbound ERRO: {e}\n{traceback.format_exc()}", flush=True)
        # Nunca explodir: devolver shape conhecido
        return {"ok": False, "error": str(e), "stage": "fachada"}



# -------------------------------------------------------------------
# Helpers (VENDAS / lead): fallback neutro + logs específicos
# -------------------------------------------------------------------

def _sales_lead_neutral_fallback(name: str = "") -> str:
    name = (name or "").strip()
    if name:
        return f"{name}, perfeito. Você quer falar de pedidos, agenda, orçamento ou só conhecer?"
    return "Show 🙂 Me diz teu nome e o que você quer resolver: pedidos, agenda, orçamento ou conhecer?"

def _looks_like_link_request(t: str) -> bool:
    try:
        s = (t or "").strip().lower()
        if not s:
            return False
        # Não depende de palavra exata; só pega casos óbvios (link/site/url/endereço/onde entro)
        return (
            ("link" in s)
            or ("site" in s)
            or ("url" in s)
            or ("endereço" in s)
            or ("endereco" in s)
            or ("onde entro" in s)
            or ("onde eu entro" in s)
        )
    except Exception:
        return False


def _ensure_send_link_in_reply(reply: str, next_step: str) -> str:
    """
    Regra canônica: se next_step == SEND_LINK, a resposta precisa conter o link (FRONTEND_BASE).
    Evita o bug: "vou te mandar o link" sem link.
    """
    try:
        ns = str(next_step or "").strip().upper()
        if ns != "SEND_LINK":
            return str(reply or "").strip()

        r = str(reply or "").strip()
        # Se já tem URL, não mexe
        if ("http://" in r) or ("https://" in r):
            return r

        base = (os.getenv("FRONTEND_BASE") or "").strip().rstrip("/")
        if not base:
            return r

        if not r:
            return base
        return (r + "\n" + base).strip()
    except Exception:
        return str(reply or "").strip()



def _get_signup_url() -> str:
    try:
        base = (
            os.getenv("FRONTEND_BASE")
            or os.getenv("FRONTEND_BASE_URL")
            or "https://www.meirobo.com.br"
        )
        base = str(base or "").strip().rstrip("/")
        if not base:
            return "https://www.meirobo.com.br"
        if not base.startswith("http"):
            base = "https://" + base.lstrip("/")
        return base
    except Exception:
        return "https://www.meirobo.com.br"


def _pick_lead_name(out: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> str:
    try:
        ctx = ctx or {}
        segment_refs = [
            out.get("segment"),
            out.get("segmentHint"),
            out.get("leadSegmentRaw"),
            ctx.get("segment"),
            ctx.get("segment_hint"),
            ctx.get("segmentHint"),
            ctx.get("leadSegmentRaw"),
        ]
        candidates = [
            out.get("nameToSay"),
            out.get("leadName"),
            out.get("displayName"),
            out.get("name"),
            ctx.get("name_hint"),
            ctx.get("displayName"),
            ctx.get("leadName"),
        ]
        for v in candidates:
            s = _sanitize_lead_name_candidate(v, segment_refs=segment_refs)
            if s:
                return s
        return ""
    except Exception:
        return ""





def _sanitize_state_name_candidate(value: str, segment_hint: str = "") -> str:
    try:
        s = str(value or "").strip()
        if not s:
            return ""
        seg = str(segment_hint or "").strip()
        cleaned = _sanitize_lead_name_candidate(s, segment_refs=[seg] if seg else [])
        if cleaned:
            return cleaned
        return ""
    except Exception:
        return ""

def _normalize_lead_identity_text(value: Any) -> str:
    try:
        s = str(value or "").strip().lower()
        s = "".join(
            ch for ch in s
            if ch.isalnum() or ch.isspace()
        )
        return " ".join(s.split())
    except Exception:
        return ""


def _sanitize_lead_name_candidate(value: Any, segment_refs: Optional[list] = None) -> str:
    """
    Validação estrutural de nome.
    Não identifica profissão/segmento por palavra-chave.
    Apenas impede que o mesmo texto usado como segmento/atividade
    seja reaproveitado como nome do lead.
    """
    try:
        s = str(value or "").strip()
        if not s:
            return ""

        if len(s) > 32:
            return ""

        tokens = [t for t in s.replace("\n", " ").split(" ") if t.strip()]
        if len(tokens) > 3:
            return ""

        if not any(ch.isalpha() for ch in s):
            return ""

        if any(ch.isdigit() for ch in s):
            return ""

        cand_norm = _normalize_lead_identity_text(s)
        cand_tokens = set(cand_norm.split())
        if not cand_norm or not cand_tokens:
            return ""

        for ref in (segment_refs or []):
            ref_norm = _normalize_lead_identity_text(ref)
            ref_tokens = set(ref_norm.split())
            if not ref_norm or not ref_tokens:
                continue
            if cand_norm == ref_norm:
                return ""
            if cand_tokens and cand_tokens.issubset(ref_tokens):
                return ""

        return s
    except Exception:
        return ""


def _build_sales_text_only_closure_reply(name: str) -> str:
    try:
        link = _get_signup_url()
        nm = str(name or "").strip()
        if nm:
            return f"Perfeito, {nm}. Obrigado pelo seu interesse. Aqui está o link para assinar a plataforma MEI Robô:\n{link}"
        return f"Perfeito. Obrigado pelo seu interesse. Aqui está o link para assinar a plataforma MEI Robô:\n{link}"
    except Exception:
        return "Perfeito. Obrigado pelo seu interesse. Aqui está o link para assinar a plataforma MEI Robô:\nhttps://www.meirobo.com.br"


def _is_sales_text_only_closure(out: Dict[str, Any]) -> bool:
    """
    Regra soberana de produto (100% estrutural, sem palavras-chave):
    Se o sistema indicar fechamento/ativação, a resposta deve ser TEXTO ONLY.
    """
    try:
        out = out or {}

        plan_next = str(out.get("planNextStep") or "").strip().upper()
        intent_final = str(out.get("intentFinal") or out.get("planIntent") or "").strip().upper()
        prefers_text = bool(out.get("prefersText"))

        und = out.get("understanding") or {}
        if isinstance(und, dict):
            und_intent = str(und.get("intent") or "").strip().upper()
            und_next = str(und.get("next_step") or und.get("nextStep") or "").strip().upper()
        else:
            und_intent = ""
            und_next = ""

        # Fonte principal: fluxo definido pelo sistema
        if plan_next == "SEND_LINK":
            return True

        if und_next == "SEND_LINK":
            return True

        # Fonte secundária: intenção semântica consolidada
        closing_intents = {"ACTIVATE","ACTIVATE_SEND_LINK","SIGNUP_LINK","ATIVAR"}

        if intent_final in closing_intents:
            return True

        if und_intent in closing_intents:
            return True

        # Fonte auxiliar: coerência com decisão já tomada
        if prefers_text and (intent_final in closing_intents or und_intent in closing_intents):
            return True

        return False

    except Exception:
        return False


def _apply_sales_text_only_closure(out: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Aplica a regra de canal (sem alterar linguagem gerada pela IA).
    NÃO cria texto novo.
    NÃO usa frase fixa.
    """
    try:
        out = dict(out or {})

        if not _is_sales_text_only_closure(out):
            return out

        lead_name = _pick_lead_name(out, ctx)

        out["prefersText"] = True
        out["textOnlyReason"] = "sales_closure_send_link"
        out["replyText"] = _build_sales_text_only_closure_reply(lead_name)
        out["planNextStep"] = "SEND_LINK"

        if not str(out.get("intentFinal") or "").strip():
            und = out.get("understanding") or {}
            if isinstance(und, dict):
                und_intent = str(und.get("intent") or "").strip().upper()
                if und_intent:
                    out["intentFinal"] = und_intent
                else:
                    out["intentFinal"] = "ATIVAR"
            else:
                out["intentFinal"] = "ATIVAR"

        # Garante que nunca vira áudio
        out.pop("audioUrl", None)
        out["spokenText"] = ""
        out["ttsText"] = ""

        dd = out.get("decisionDebug") or {}
        if isinstance(dd, dict):
            dd["text_only_closure_applied"] = True
            dd["text_only_closure_reason"] = "sales_closure_send_link"
            out["decisionDebug"] = dd

        return out

    except Exception:
        return dict(out or {})




def _clean_final_reply_tail(text: Any) -> str:
    """
    Saneamento final, determinístico e independente de segmento.

    Objetivo: impedir que resíduos de montagem/polimento escapem no fim
    da resposta, sem alterar estratégia, prompt, KB, intenção ou conteúdo
    já aprovado pelo front.

    Regra central:
    - se já existe uma frase completa e o trecho final ficou sem fechamento,
      o guard corta a sobra até a última pontuação forte;
    - se não há frase completa anterior, apenas normaliza e pontua.
    """
    try:
        import re

        t = str(text or "").strip()
        if not t:
            return ""

        # Não mexe em respostas cujo fechamento operacional é um link.
        # Evita quebrar URL, assinatura ou envio link-only.
        last_line = (t.splitlines()[-1] if t.splitlines() else t).strip()
        if re.search(r"https?://\S+$", last_line, flags=re.IGNORECASE):
            return t

        # Normaliza espaços sem destruir quebras de linha úteis.
        t = re.sub(r"[ \t]+", " ", t).strip()
        t = re.sub(r"\n{3,}", "\n\n", t).strip()
        t = t.strip(" \t\r\n\u200b\u200c\u200d\ufeff")

        def _norm_tokens(x: str) -> list[str]:
            try:
                return re.findall(r"[a-z0-9áàâãéêíóôõúç]+", x.lower(), flags=re.IGNORECASE)
            except Exception:
                return []

        def _last_strong_match(s: str):
            try:
                matches = list(re.finditer(r"[.!?](?:[\)\]\}'\"])?", s))
                return matches[-1] if matches else None
            except Exception:
                return None

        def _cut_at_last_strong(s: str) -> str:
            m = _last_strong_match(s)
            if not m:
                return s.strip()
            return s[: m.end()].strip()

        def _looks_like_unfinished_tail(tail: str, full_text: str) -> bool:
            """
            Heurística estrutural, sem palavras-chave:
            identifica sobra final quando já existe frase completa anterior.
            """
            try:
                tail = str(tail or "").strip()
                if not tail:
                    return False

                weak_end = tail[-1:] in {",", ";", ":", "-", "–", "—", "(", "[", "{", "/"}
                if weak_end:
                    return True

                tail_tokens = _norm_tokens(tail)
                if not tail_tokens:
                    return True

                # Palavra final muito curta em trecho longo costuma indicar corte duro
                # no meio da geração, como final incompleto de uma palavra.
                if len(tail) >= 70 and len(tail_tokens[-1]) <= 3:
                    return True

                # Um trecho final longo sem pontuação forte, depois de uma frase completa,
                # é mais arriscado manter do que cortar.
                if len(tail) >= 90:
                    return True

                # Se a cauda tem pontuação fraca interna e não fecha frase, é sobra.
                if len(tail) >= 45 and re.search(r"[,;:]", tail):
                    return True

                # Se a resposta inteira já é longa e a cauda ficou média/sem fecho,
                # prioriza preservar as frases completas já aprovadas.
                if len(full_text) >= 500 and len(tail) >= 35:
                    return True

                return False
            except Exception:
                return False

        # 1) Remove duplicação estrutural do início reaparecendo no fim.
        #    A comparação é por tokens, sem depender de tema, segmento ou frase pronta.
        last_strong = _last_strong_match(t)
        if last_strong is not None and t[-1:] not in {".", "!", "?"}:
            head = t[: last_strong.end()].strip()
            tail = t[last_strong.end() :].strip()
            head_tokens = _norm_tokens(head)
            tail_tokens = _norm_tokens(tail)
            duplicated_opening = bool(
                head_tokens
                and tail_tokens
                and len(tail_tokens) >= 5
                and head_tokens[: len(tail_tokens)] == tail_tokens
            )
            if duplicated_opening:
                t = head

        # 2) Se existe frase completa antes e o final ficou incompleto,
        #    corta até a última pontuação forte. Isso corrige tanto rabo solto
        #    quanto truncamento duro no meio de palavra.
        last_strong = _last_strong_match(t)
        if last_strong is not None and t[-1:] not in {".", "!", "?"}:
            head = t[: last_strong.end()].strip()
            tail = t[last_strong.end() :].strip()
            if head and _looks_like_unfinished_tail(tail, t):
                t = head

        # 3) Se ainda terminou com pontuação fraca, corta no último fechamento forte.
        if t and t[-1:] in {",", ";", ":", "-", "–", "—"}:
            cut = _cut_at_last_strong(t)
            if cut and cut != t:
                t = cut
            else:
                t = t.rstrip(" ,;:-–—").strip()

        # 4) Garantia final: resposta útil termina com pontuação forte.
        #    Só pontua quando não houve evidência suficiente para cortar.
        if t and t[-1:] not in {".", "!", "?"}:
            t = t.rstrip(" ,;:-–—").strip()
            if t:
                t += "."

        return t.strip()
    except Exception:
        return str(text or "").strip()


def _apply_final_reply_tail_guard(out: Dict[str, Any]) -> Dict[str, Any]:
    """Aplica o saneamento final em replyText e spokenText, sem mudar metadados."""
    try:
        if not isinstance(out, dict):
            return out

        before_reply = str(out.get("replyText") or "")
        before_spoken = str(out.get("spokenText") or "")

        after_reply = _clean_final_reply_tail(before_reply)
        after_spoken = _clean_final_reply_tail(before_spoken or after_reply)

        if after_reply:
            out["replyText"] = after_reply
        if after_spoken:
            out["spokenText"] = after_spoken

        try:
            if before_reply.strip() != str(out.get("replyText") or "").strip() or before_spoken.strip() != str(out.get("spokenText") or "").strip():
                logging.info(
                    "[WA_BOT][FINAL_TAIL_GUARD] reply_len_before=%s reply_len_after=%s spoken_len_before=%s spoken_len_after=%s",
                    len(before_reply.strip()),
                    len(str(out.get("replyText") or "").strip()),
                    len(before_spoken.strip()),
                    len(str(out.get("spokenText") or "").strip()),
                )
        except Exception:
            pass
    except Exception:
        pass
    return out

def _log_sales_lead_fallback(ctx: Optional[Dict[str, Any]], *, reason: str, err: Optional[Exception] = None):
    try:
        ctx = ctx or {}
        payload = {
            "route": "sales_lead_fallback",
            "reason": reason,
            "from_e164": (ctx.get("from_e164") or "").strip(),
            "waKey": (ctx.get("waKey") or ctx.get("wa_key") or "").strip(),
            "event_key": (ctx.get("event_key") or ctx.get("eventKey") or "").strip(),
            "wamid": (ctx.get("wamid") or ctx.get("message_id") or ctx.get("msg_id") or "").strip(),
        }
        if err is not None:
            payload["err"] = (str(err) or err.__class__.__name__)[:220]
        logging.info("[WA_BOT][VENDAS] fallback: %s", payload)
    except Exception:
        # nunca quebrar por log
        pass



def _truncate_lead_summary(text: Any, max_chars: int = LEAD_MEMORY_SUMMARY_MAX_CHARS) -> str:
    try:
        s = str(text or "").strip()
    except Exception:
        return ""
    if not s:
        return ""
    if len(s) <= max_chars:
        return s
    return s[: max_chars - 1].rstrip() + "…"


def _build_lead_summary(out: Dict[str, Any], ctx: Dict[str, Any]) -> str:
    try:
        name = (
            out.get("leadName")
            or out.get("displayName")
            or out.get("nameToSay")
            or ctx.get("displayName")
            or ctx.get("name_hint")
            or ""
        )

        segment = (
            out.get("leadSegmentRaw")
            or out.get("segmentHint")
            or ctx.get("segment")
            or ctx.get("segment_hint")
            or ""
        )

        intent = (
            out.get("intent")
            or out.get("lastIntent")
            or ctx.get("intent")
            or ""
        )

        topic = (
            out.get("topic")
            or out.get("lastTopic")
            or ctx.get("topic")
            or ""
        )

        parts = []

        if name and segment:
            parts.append(f"{name} atua em {segment}.")
        elif name:
            parts.append(f"{name} entrou em contato.")
        elif segment:
            parts.append(f"Lead atua em {segment}.")

        if intent:
            parts.append(f"Demonstrou interesse em {intent}.")

        if topic:
            parts.append(f"Tema principal: {topic}.")

        return _truncate_lead_summary(" ".join(parts))
    except Exception:
        return ""


def _load_institutional_lead_memory(wa_key: str) -> Dict[str, Any]:
    """
    Carrega memória persistente do lead institucional por telefone.
    Best-effort: nunca bloqueia o atendimento.
    """
    try:
        wa_key = "".join(ch for ch in str(wa_key or "") if ch.isdigit())
        if not wa_key:
            return {}

        from firebase_admin import firestore  # type: ignore
        db = firestore.client()
        snap = db.collection("institutional_leads").document(wa_key).get()
        data = (snap.to_dict() or {}) if snap else {}
        if not isinstance(data, dict):
            return {}

        segment = str(
            data.get("segment")
            or data.get("segment_hint")
            or data.get("leadSegment")
            or ""
        ).strip()

        name = _sanitize_lead_name_candidate(
            (
                data.get("name_hint")
                or data.get("displayName")
                or data.get("leadName")
                or ""
            ),
            segment_refs=[
                segment,
                data.get("segment"),
                data.get("segment_hint"),
                data.get("leadSegment"),
                data.get("leadSegmentRaw"),
            ],
        )

        out: Dict[str, Any] = {}
        if name:
            out["name_hint"] = name
            out["displayName"] = name
            out["leadName"] = name
        if segment:
            out["segment_hint"] = segment
            out["segment"] = segment

        if data.get("lastIntent"):
            out["lastIntent"] = data.get("lastIntent")

        if data.get("lastTopic"):
            out["lastTopic"] = data.get("lastTopic")

        if data.get("nextStep"):
            out["lastNextStep"] = data.get("nextStep")

        if data.get("summary"):
            out["lead_memory_summary"] = data.get("summary")

        if data.get("turns"):
            out["lead_memory_turns"] = data.get("turns")

        try:
            logger.info(
                "lead_memory_loaded waKey=%s has_name=%s has_segment=%s has_summary=%s",
                wa_key,
                bool(data.get("displayName") or data.get("name_hint")),
                bool(data.get("segment") or data.get("segment_hint")),
                bool(data.get("summary")),
            )
        except Exception:
            pass

        return out
    except Exception:
        return {}


def _save_institutional_lead_memory(wa_key: str, out: Optional[Dict[str, Any]] = None, ctx: Optional[Dict[str, Any]] = None) -> None:
    """
    Persiste memória do lead institucional por telefone.
    Usa merge=True e só grava campos não vazios.
    """
    try:
        wa_key = "".join(ch for ch in str(wa_key or "") if ch.isdigit())
        if not wa_key:
            return

        from firebase_admin import firestore  # type: ignore
        db = firestore.client()

        out = out or {}
        ctx = ctx or {}

        snap = db.collection("institutional_leads").document(wa_key).get()
        data = (snap.to_dict() or {}) if snap else {}
        if not isinstance(data, dict):
            data = {}

        now = firestore.SERVER_TIMESTAMP

        created_at = data.get("createdAt") if isinstance(data, dict) else None

        understanding = out.get("understanding") if isinstance(out.get("understanding"), dict) else {}

        operational_contract = (
            out.get("operationalContract")
            if isinstance(out.get("operationalContract"), dict)
            else {}
        )

        segment = (
            out.get("segment")
            or out.get("segmentHint")
            or operational_contract.get("segment")
            or ctx.get("segment")
            or ctx.get("segment_hint")
            or ctx.get("segmentHint")
            or ""
        )

        segment_hint = (
            out.get("segmentHint")
            or operational_contract.get("segment")
            or ctx.get("segment_hint")
            or ctx.get("segment")
            or ctx.get("segmentHint")
            or ""
        )

        lead_segment_raw = (
            out.get("leadSegmentRaw")
            or understanding.get("leadSegmentRaw")
            or ctx.get("leadSegmentRaw")
            or segment
            or ""
        )

        existing_lead_name = _sanitize_lead_name_candidate(

            (

                data.get("name_hint")

                or data.get("displayName")

                or data.get("leadName")

                or ""

            ),

            segment_refs=[

                data.get("segment"),

                data.get("segment_hint"),

                data.get("leadSegment"),

                data.get("leadSegmentRaw"),

                segment,

                segment_hint,

                lead_segment_raw,

            ],

        )


        ctx_lead_name = _sanitize_lead_name_candidate(

            (

                ctx.get("displayName")

                or ctx.get("name_hint")

                or ctx.get("leadName")

                or ""

            ),

            segment_refs=[

                segment,

                segment_hint,

                lead_segment_raw,

                ctx.get("segment"),

                ctx.get("segment_hint"),

                ctx.get("segmentHint"),

            ],

        )


        front_lead_name = _sanitize_lead_name_candidate(

            (

                out.get("leadName")

                or out.get("displayName")

                or out.get("nameToSay")

                or ""

            ),

            segment_refs=[

                segment,

                segment_hint,

                lead_segment_raw,

                ctx.get("segment"),

                ctx.get("segment_hint"),

                ctx.get("segmentHint"),

            ],

        )


        reply_source = str(

            out.get("replySource")

            or out.get("source")

            or out.get("iaSource")

            or ""

        ).strip()


        if existing_lead_name:

            lead_name = existing_lead_name

        elif ctx_lead_name:

            lead_name = ctx_lead_name

        else:

            lead_name = front_lead_name


        last_intent = (


            out.get("intent")


            or out.get("lastIntent")


            or understanding.get("intent")


            or ctx.get("intent")


            or ctx.get("lastIntent")


            or ""


        )

        last_topic = (


            out.get("topic")


            or out.get("lastTopic")


            or understanding.get("intent")


            or ctx.get("topic")


            or ctx.get("lastTopic")


            or ""


        )

        next_step = (


            out.get("nextStep")


            or understanding.get("next_step")


            or ctx.get("nextStep")


            or ctx.get("lastNextStep")


            or ""


        )

        turns_prev = 0
        try:
            turns_prev = int(data.get("turns") or 0)
        except Exception:
            turns_prev = 0

        turns = turns_prev + 1

        summary = _build_lead_summary(out, ctx)

        expires_at = datetime.utcnow() + timedelta(days=LEAD_MEMORY_TTL_DAYS)

        payload = {
            "waKey": wa_key,
            "fromE164": (
            ctx.get("fromE164")
            or ctx.get("from")
            or out.get("fromE164")
            or ""
        ),
            "source": "whatsapp_institutional_sales",
            "status": "active",
            "createdAt": created_at or now,
            "updatedAt": now,
            "lastSeenAt": now,
            "lastMessageAt": now,
            "expiresAt": expires_at,
            "displayName": lead_name,
            "name_hint": lead_name,
            "leadName": lead_name,
            "segment": segment,
            "segment_hint": segment_hint,
            "leadSegmentRaw": lead_segment_raw,
            "lastIntent": last_intent,
            "lastTopic": last_topic,
            "nextStep": next_step,
            "summary": summary,
            "turns": turns,
        }

        payload = {
            k: v
            for k, v in payload.items()
            if v not in (None, "", [], {})
        }

        db.collection("institutional_leads").document(wa_key).set(payload, merge=True)

        try:
            logger.info(
                "lead_memory_saved waKey=%s fields=%s has_summary=%s turns=%s",
                wa_key,
                sorted(payload.keys()),
                bool(payload.get("summary")),
                payload.get("turns"),
            )
        except Exception:
            pass
    except Exception:
        pass


def _apply_safe_ai_meta(out: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Garantia mínima de aiMeta para auditoria, sem alterar comportamento."""
    try:
        aiMeta = out.get("aiMeta") or {}
        if not isinstance(aiMeta, dict):
            aiMeta = {}
    except Exception:
        aiMeta = {}

    try:
        ctx = ctx or {}
    except Exception:
        ctx = {}

    try:
        aiMeta.setdefault("channel", "whatsapp")
        aiMeta.setdefault("entryType", (ctx.get("msg_type") or "").lower())
    except Exception:
        pass

    try:
        aiMeta.setdefault("aiTurns", int((ctx or {}).get("ai_turns") or 0))
        aiMeta.setdefault("maxAiTurns", int(MAX_AI_TURNS))
    except Exception:
        pass

    try:
        if "responseOrigin" not in aiMeta:
            aiMeta["responseOrigin"] = (
                "conversational_front" if (ctx or {}).get("free_mode") else "sales_lead"
            )
    except Exception:
        pass

    try:
        out["aiMeta"] = aiMeta
    except Exception:
        pass

    return out



# ==========================================================
# Front KB Snapshot (v1): montagem compacta a partir do Firestore
# - Sem "Firestore bruto": só campos selecionados
# - Sem NLP pesado no código: apenas hint determinístico de tópico
# - Prioridade de corte:
#   1) Guardrails + Pitch (KIT_BASE)
#   2) Bloco do tópico
#   3) Feature catalog (o que sobrar)
# ==========================================================

def _front_topic_hint(user_text: str) -> str:
    """
    Hint determinístico e barato (não é NLU/planejador):
    só ajuda a escolher qual bloco do snapshot incluir.
    """
    try:
        t = (user_text or "").lower()
        if any(k in t for k in ("agenda", "agendar", "horário", "horario", "marcar", "marcação", "marcacao")):
            return "AGENDA"
        if any(k in t for k in ("preço", "preco", "valor", "plano", "planos", "quanto custa", "mensal", "assinatura")):
            return "PRECO"
        if any(k in t for k in ("orçamento", "orcamento", "contratar", "ativar", "assinar", "fechar", "como funciona", "quero o mei robô")):
            return "ORCAMENTO"
        if ("mei rob" in t) and any(k in t for k in ("ajuda", "whatsapp", "vender", "vendas", "faz", "faria", "atendimento", "pacientes", "clientes")):
            return "ORCAMENTO"
        if any(k in t for k in ("voz", "áudio", "audio", "audios", "ptt", "fala", "responder por voz")):
            return "VOZ"
        if any(k in t for k in ("oi", "olá", "ola", "bom dia", "boa tarde", "boa noite", "valeu", "obrigado", "obrigada")):
            return "SOCIAL"
        return "OTHER"
    except Exception:
        return "OTHER"


def _front_normalize_text_for_match(user_text: str) -> str:
    try:
        import unicodedata
        t = unicodedata.normalize("NFKD", str(user_text or ""))
        t = "".join(ch for ch in t if not unicodedata.combining(ch))
        return t.lower()
    except Exception:
        return str(user_text or "").lower()


def _front_target_subsegment_ids(user_text: str) -> list:
    """
    Seleção determinística mínima para o snapshot institucional.

    Regra:
    - só seleciona quando o texto declara um subsegmento claro;
    - não força seleção em mensagens ambíguas;
    - não decide a resposta final, apenas preserva o documento certo antes do prune.
    """
    try:
        t = _front_normalize_text_for_match(user_text)

        if any(k in t for k in ("otorrino", "otorrinolaringologia", "ouvido nariz garganta")):
            return ["consultorio_medico_otorrinolaringologia"]

        if any(k in t for k in ("clinica de exames", "clinica exames", "exames medicos", "laboratorio de exames", "laboratorio clinico")):
            return ["saude__clinica_exames_medicos"]

        if any(k in t for k in ("consultorio medico", "consultorio de medico", "consultorio de medicina")):
            return ["saude__consultorio_medico"]

        if any(k in t for k in ("otica", "loja de oculos", "loja de óculos", "oculos de grau", "óculos de grau")):
            return ["comercio_varejista__loja_oculos"]

        return []
    except Exception:
        return []


def _front_snapshot_json_len(obj: object) -> int:
    try:
        return len(json.dumps(obj or {}, ensure_ascii=False, separators=(",", ":")))
    except Exception:
        return 999999


def _front_clip_runtime_value(value: object, str_limit: int = 360, list_limit: int = 5, depth: int = 0) -> object:
    """
    Compactação genérica e conservadora para blocos V2.
    Mantém estrutura útil, corta excesso textual e evita JSON grande demais.
    """
    try:
        if value is None:
            return None

        if isinstance(value, str):
            return _clip_front_text(value, str_limit)

        if isinstance(value, (int, float, bool)):
            return value

        if isinstance(value, list):
            out = []
            for item in value[:list_limit]:
                clipped = _front_clip_runtime_value(item, str_limit=str_limit, list_limit=3, depth=depth + 1)
                if clipped not in (None, "", [], {}):
                    out.append(clipped)
            return out

        if isinstance(value, dict):
            if depth >= 3:
                return {}

            out = {}
            for k, v in list(value.items())[:12]:
                key = str(k or "").strip()
                if not key:
                    continue
                clipped = _front_clip_runtime_value(v, str_limit=max(180, str_limit - 80), list_limit=4, depth=depth + 1)
                if clipped not in (None, "", [], {}):
                    out[key] = clipped
            return out

        return _clip_front_text(str(value), str_limit)
    except Exception:
        return None


def _front_compact_v2_runtime_block(block: object, char_limit: int = 1800) -> dict:
    """
    Compacta um bloco V2 para caber no snapshot.
    Preserva chaves prioritárias primeiro e reduz o restante por limite.
    """
    try:
        if not isinstance(block, dict) or not block:
            return {}

        priority_keys = [
            "summary",
            "value_proposition",
            "positioning",
            "main_promises",
            "key_situations",
            "real_customer_situations",
            "decision_sequence",
            "consultant_decision_sequence",
            "operational_sequence",
            "response_rules",
            "next_steps",
            "handoff_triggers",
            "safety_limits",
            "limits",
            "dont_diagnose",
            "do_not_diagnose",
            "micro_scene_conversational",
            "lead_refinement_question",
            "micro_scene",
        ]

        ordered_keys = []
        for k in priority_keys:
            if k in block:
                ordered_keys.append(k)
        for k in block.keys():
            if k not in ordered_keys:
                ordered_keys.append(k)

        out = {}
        for k in ordered_keys:
            v = _front_clip_runtime_value(block.get(k), str_limit=420, list_limit=5, depth=0)
            if v not in (None, "", [], {}):
                out[str(k)] = v

            if _front_snapshot_json_len(out) >= char_limit:
                break

        while len(out) > 1 and _front_snapshot_json_len(out) > char_limit:
            last_key = list(out.keys())[-1]
            out.pop(last_key, None)

        return out
    except Exception:
        return {}


def _front_compact_snapshot_priority(value: object) -> object:
    try:
        clipped = _front_clip_runtime_value(value, str_limit=260, list_limit=6, depth=0)
        return clipped if clipped not in (None, "", [], {}) else {}
    except Exception:
        return {}


def _front_compact_selected_subsegment_doc(raw_doc: dict, base_doc: dict) -> dict:
    """
    Documento selecionado recebe tratamento especial:
    - mantém compactação canônica existente;
    - injeta V2 compactado;
    - evita copiar blocos longos integralmente.
    """
    try:
        v2_keys = {
            "commercial_runtime",
            "operational_runtime",
            "medical_runtime",
            "behavior_components",
            "snapshot_priority",
        }
        out = {
            k: v
            for k, v in dict(base_doc or {}).items()
            if k not in v2_keys
        }

        if not isinstance(raw_doc, dict):
            return out

        basic_fields = [
            "id",
            "name",
            "summary",
            "description",
            "one_liner",
            "micro_scene",
            "micro_scene_conversational",
            "lead_refinement_question",
            "segment_id",
            "archetype_id",
            "keywords",
            "negative_keywords",
            "common_intents",
            "preferred_capabilities",
            "customer_noun",
            "conversion_noun",
            "handoff_format",
            "operational_ritual",
            "operational_rules",
        ]

        for key in basic_fields:
            if key in raw_doc and key not in out:
                value = _front_clip_runtime_value(raw_doc.get(key), str_limit=520, list_limit=8, depth=0)
                if value not in (None, "", [], {}):
                    out[key] = value

        if "snapshot_priority" in raw_doc:
            sp = _front_compact_snapshot_priority(raw_doc.get("snapshot_priority"))
            if sp not in (None, "", [], {}):
                out["snapshot_priority"] = sp

        v2_limits = {
            "commercial_runtime": 2600,
            "operational_runtime": 2200,
            "medical_runtime": 1800,
            "behavior_components": 1600,
        }

        for key, block_limit in v2_limits.items():
            if key in raw_doc:
                block = _front_compact_v2_runtime_block(raw_doc.get(key), char_limit=block_limit)
                if block:
                    out[key] = block

        return out
    except Exception:
        return dict(base_doc or {})


def _front_reduce_kb_docs_to_selected_subsegments(
    *,
    selected_ids: Any,
    compact_subsegments: Dict[str, Any],
    compact_segments: Dict[str, Any],
    compact_archetypes: Dict[str, Any],
    raw_subsegments: Dict[str, Any],
) -> tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], list[str]]:
    """
    Reduz os docs operacionais ao alvo selecionado e seus pais diretos.
    Não faz matching flexível: IDs precisam bater exatamente com o KB.
    """
    selected_subsegments: Dict[str, Any] = {}
    selected_segments: Dict[str, Any] = {}
    selected_archetypes: Dict[str, Any] = {}
    protected_ids: list[str] = []

    try:
        for sid in list(selected_ids or []):
            sid_s = str(sid or "").strip()
            if not sid_s:
                continue

            base_doc = (compact_subsegments or {}).get(sid_s) or {}
            if not isinstance(base_doc, dict) or not base_doc:
                continue

            raw_doc = (raw_subsegments or {}).get(sid_s) or {}
            selected_doc = _front_compact_selected_subsegment_doc(
                raw_doc if isinstance(raw_doc, dict) else {},
                base_doc,
            )
            if not isinstance(selected_doc, dict) or not selected_doc:
                continue

            selected_subsegments[sid_s] = selected_doc
            protected_ids.append(sid_s)

            seg_id = str(selected_doc.get("segment_id") or "").strip()
            seg_doc = (compact_segments or {}).get(seg_id) or {}
            if seg_id and isinstance(seg_doc, dict) and seg_doc:
                selected_segments[seg_id] = seg_doc

            arch_id = str(selected_doc.get("archetype_id") or "").strip()
            arch_doc = (compact_archetypes or {}).get(arch_id) or {}
            if arch_id and isinstance(arch_doc, dict) and arch_doc:
                selected_archetypes[arch_id] = arch_doc
    except Exception:
        return {}, {}, {}, []

    return selected_subsegments, selected_segments, selected_archetypes, protected_ids


def _front_minimal_hydratable_docs(docs: Any) -> Dict[str, Any]:
    """
    Fallback estrutural para serialização: preserva só campos hidratáveis do KB.
    Não cria conteúdo comercial nem frases de resposta.
    """
    keep_fields = (
        "id",
        "name",
        "segment_id",
        "archetype_id",
        "one_liner",
        "micro_scene_conversational",
        "lead_refinement_question",
        "micro_scene",
        "conversation_mode",
        "primary_goal",
        "customer_noun",
        "conversion_noun",
        "service_noun",
    )
    out: Dict[str, Any] = {}
    try:
        if not isinstance(docs, dict):
            return {}
        for doc_id, doc in list(docs.items()):
            if not isinstance(doc, dict):
                continue
            item: Dict[str, Any] = {}
            for field in keep_fields:
                value = doc.get(field)
                if value in (None, "", [], {}):
                    continue
                compacted = _front_clip_runtime_value(
                    value,
                    str_limit=420,
                    list_limit=4,
                    depth=0,
                )
                if compacted not in (None, "", [], {}):
                    item[field] = compacted
            if item:
                out[str(doc_id)] = item
    except Exception:
        return {}
    return out


def _safe_str(x: Any) -> str:
    try:
        if x is None:
            return ""
        if isinstance(x, str):
            return x.strip()
        # listas/dicts viram texto compacto (sem dump gigante)
        if isinstance(x, list):
            parts = []
            for it in x[:24]:
                s = _safe_str(it)
                if s:
                    parts.append(s)
            return "\n".join(parts).strip()
        if isinstance(x, dict):
            # tenta preservar ordem “humana”
            parts = []
            for k, v in list(x.items())[:40]:
                vs = _safe_str(v)
                if vs:
                    parts.append(f"- {k}: {vs}")
            return "\n".join(parts).strip()
        return str(x).strip()
    except Exception:
        return ""


def _clip_front_text(x: Any, max_len: int = 180) -> str:
    try:
        s = _safe_str(x)
        if not s:
            return ""
        s = " ".join(s.split())
        return s[:max_len].strip()
    except Exception:
        return ""


def _compact_front_kb_doc(
    d: Dict[str, Any],
    *,
    doc_id: str = "",
    include_segment_id: bool = False,
    include_archetype_id: bool = False,
) -> Dict[str, Any]:
    """
    Compactação mínima e estável para o snapshot packs_v1.
    Mantém só o que ajuda a:
    - identificar trilho operacional
    - hidratar contrato
    - reconstruir microcena
    """
    try:
        if not isinstance(d, dict):
            return {}

        out: Dict[str, Any] = {}

        if doc_id:
            out["id"] = _clip_front_text(doc_id, 80)

        if include_segment_id and d.get("segment_id"):
            out["segment_id"] = _clip_front_text(d.get("segment_id"), 80)

        if include_archetype_id and d.get("archetype_id"):
            out["archetype_id"] = _clip_front_text(d.get("archetype_id"), 80)

        if d.get("name"):
            out["name"] = _clip_front_text(d.get("name"), 120)

        if d.get("conversation_mode"):
            out["conversation_mode"] = _clip_front_text(d.get("conversation_mode"), 80)

        if d.get("description"):
            out["description"] = _clip_front_text(d.get("description"), 220)

        if d.get("one_liner"):
            out["one_liner"] = _clip_front_text(d.get("one_liner"), 180)

        if d.get("one_question"):
            out["one_question"] = _clip_front_text(d.get("one_question"), 180)

        if d.get("micro_scene_conversational"):
            out["micro_scene_conversational"] = _clip_front_text(
                d.get("micro_scene_conversational"),
                900,
            )

        if d.get("micro_scene"):
            out["micro_scene"] = _clip_front_text(d.get("micro_scene"), 500)

        if d.get("direct_scene"):
            out["direct_scene"] = _clip_front_text(d.get("direct_scene"), 900)

        if d.get("runtime_long_text"):
            out["runtime_long_text"] = _clip_front_text(d.get("runtime_long_text"), 900)

        if d.get("primary_goal"):
            out["primary_goal"] = _clip_front_text(d.get("primary_goal"), 120)

        if d.get("customer_noun"):
            out["customer_noun"] = _clip_front_text(d.get("customer_noun"), 80)

        if d.get("conversion_noun"):
            out["conversion_noun"] = _clip_front_text(d.get("conversion_noun"), 120)

        if d.get("service_noun"):
            out["service_noun"] = _clip_front_text(d.get("service_noun"), 80)

        if d.get("keywords"):
            out["keywords"] = [
                _clip_front_text(x, 40)
                for x in (d.get("keywords") or [])[:8]
                if _clip_front_text(x, 40)
            ]

        if d.get("common_intents"):
            out["common_intents"] = [
                _clip_front_text(x, 60)
                for x in (d.get("common_intents") or [])[:6]
                if _clip_front_text(x, 60)
            ]

        if d.get("preferred_capabilities"):
            out["preferred_capabilities"] = [
                _clip_front_text(x, 60)
                for x in (d.get("preferred_capabilities") or [])[:6]
                if _clip_front_text(x, 60)
            ]

        if d.get("operational_ritual"):
            out["operational_ritual"] = [
                _clip_front_text(x, 100)
                for x in (d.get("operational_ritual") or [])[:5]
                if _clip_front_text(x, 100)
            ]

        if d.get("handoff_format"):
            out["handoff_format"] = [
                _clip_front_text(x, 80)
                for x in (d.get("handoff_format") or [])[:5]
                if _clip_front_text(x, 80)
            ]

        # ==========================================================
        # Firestore V2 Runtime Blocks
        # FASE 2 = preservação compactada para snapshot.
        # Blocos completos continuam no Firestore; o snapshot recebe
        # apenas o necessário para o GPT-4o-mini trabalhar com foco.
        # ==========================================================

        if "snapshot_priority" in d:
            sp = _front_compact_snapshot_priority(d.get("snapshot_priority"))
            if sp not in (None, "", [], {}):
                out["snapshot_priority"] = sp

        if "commercial_runtime" in d:
            block = _front_compact_v2_runtime_block(d.get("commercial_runtime"), char_limit=900)
            if block:
                out["commercial_runtime"] = block

        if "operational_runtime" in d:
            block = _front_compact_v2_runtime_block(d.get("operational_runtime"), char_limit=800)
            if block:
                out["operational_runtime"] = block

        if "medical_runtime" in d:
            block = _front_compact_v2_runtime_block(d.get("medical_runtime"), char_limit=700)
            if block:
                out["medical_runtime"] = block

        if "behavior_components" in d:
            block = _front_compact_v2_runtime_block(d.get("behavior_components"), char_limit=650)
            if block:
                out["behavior_components"] = block

        # FRONT_KB_GENERIC_SUBSEGMENT_TARGET_V1_COMPACT_FIELDS
        if "enabled" in d:
            out["enabled"] = bool(d.get("enabled"))
        if d.get("negative_keywords"):
            out["negative_keywords"] = [
                _clip_front_text(x, 60)
                for x in (d.get("negative_keywords") or [])[:8]
                if _clip_front_text(x, 60)
            ]

        # FRONT_KB_GENERIC_SUBSEGMENT_TARGET_V1_ROUTING_ANCHORS
        if d.get("routing_identity_anchors"):
            out["routing_identity_anchors"] = [
                _clip_front_text(x, 80)
                for x in (d.get("routing_identity_anchors") or [])[:10]
                if _clip_front_text(x, 80)
            ]
        if d.get("routing_negative_anchors"):
            out["routing_negative_anchors"] = [
                _clip_front_text(x, 80)
                for x in (d.get("routing_negative_anchors") or [])[:10]
                if _clip_front_text(x, 80)
            ]

        return out
    except Exception:
        return {}


def _fetch_front_kb_sources(topic_hint: str = "") -> Dict[str, Any]:
    """
    Busca poucas fontes canônicas no Firestore (curtas):
    - platform_kb/sales
    - platform_pricing/current
    Retorna dicts (vazios se falhar).
    """
    out: Dict[str, Any] = {"kb": {}, "pricing": {}, "segments": {}, "subsegments": {}, "archetypes": {}}
    try:
        from firebase_admin import firestore  # type: ignore
        db = firestore.client()
        try:
            snap = db.collection("platform_kb").document("sales").get()
            out["kb"] = (snap.to_dict() or {}) if snap else {}
        except Exception:
            out["kb"] = {}
        try:
            snap2 = db.collection("platform_pricing").document("current").get()
            out["pricing"] = (snap2.to_dict() or {}) if snap2 else {}
        except Exception:
            out["pricing"] = {}

        # NOVO: carregar base operacional
        try:
            segs = {}
            for doc in db.collection("kb_segments_v1").stream():
                segs[doc.id] = doc.to_dict() or {}
            out["segments"] = segs
            logging.info("[WA_BOT][KB_SOURCE_PROBE] collection=kb_segments_v1 count=%s sample=%s", len(segs), list(segs.keys())[:5])
        except Exception as e:
            out["segments"] = {}
            logging.warning("[WA_BOT][KB_SOURCE_PROBE] collection=kb_segments_v1 error=%s", str(e)[:180])

        try:
            subs = {}
            for doc in db.collection("kb_subsegments_v1").stream():
                subs[doc.id] = doc.to_dict() or {}
            out["subsegments"] = subs
            logging.info("[WA_BOT][KB_SOURCE_PROBE] collection=kb_subsegments_v1 count=%s sample=%s", len(subs), list(subs.keys())[:5])
        except Exception as e:
            out["subsegments"] = {}
            logging.warning("[WA_BOT][KB_SOURCE_PROBE] collection=kb_subsegments_v1 error=%s", str(e)[:180])

        try:
            archs = {}
            for doc in db.collection("kb_archetypes_v1").stream():
                archs[doc.id] = doc.to_dict() or {}
            out["archetypes"] = archs
            logging.info("[WA_BOT][KB_SOURCE_PROBE] collection=kb_archetypes_v1 count=%s sample=%s", len(archs), list(archs.keys())[:5])
        except Exception as e:
            out["archetypes"] = {}
            logging.warning("[WA_BOT][KB_SOURCE_PROBE] collection=kb_archetypes_v1 error=%s", str(e)[:180])
    except Exception:
        # sem Firestore? snapshot vazio (front ainda funciona, só fica mais “simpático”)
        pass
    return out


def _simple_tpl(s: str, slots: Dict[str, str]) -> str:
    out = str(s or "")
    # substituição simples {{key}}
    try:
        for k, v in (slots or {}).items():
            out = out.replace("{{" + str(k) + "}}", str(v))
    except Exception:
        pass
    return out


def _select_pack_id(decider: Dict[str, Any], kb: Dict[str, Any]) -> str:
    value_packs = kb.get("value_packs_v1") or {}
    seg_map = kb.get("segment_value_map_v1") or {}
    seg_tpl = kb.get("segment_template_v1") or {}
    policy = kb.get("pack_selection_policy_v1") or {}

    pack_profile = str(decider.get("packProfile") or "generic").strip()
    intent = str(decider.get("intent") or "").strip().upper()
    segment_key = str(decider.get("segmentKey") or "").strip()

    # normaliza perfil por intent
    if pack_profile in ("", "generic", "DEFAULT"):
        if intent in ("SCHEDULE", "BOOK", "AGENDA", "AGENDAR"):
            pack_profile = "by_schedule"
        elif intent in ("ORDERS", "ORDER", "PEDIDO", "PEDIDOS"):
            pack_profile = "by_orders"
        elif intent in ("STATUS", "PROCESS"):
            pack_profile = "by_status"
        elif intent in ("SERVICES", "PRICE"):
            pack_profile = "by_schedule"
        else:
            pack_profile = "by_schedule"

    preferred: list = []
    do_not_use: list = []
    try:
        if segment_key and isinstance(seg_map, dict) and segment_key in seg_map:
            seg = seg_map.get(segment_key) or {}
            preferred = list(seg.get("preferred_packs") or [])
            do_not_use = list(seg.get("do_not_use") or [])
        else:
            dp = ((seg_tpl.get("default_preferred_packs_by_profile") or {}) if isinstance(seg_tpl, dict) else {})
            preferred = list((dp.get(pack_profile) or []))
    except Exception:
        preferred = []

    # enforce: 1 pack
    try:
        _ = int((policy.get("max_packs_per_response") or 1))
    except Exception:
        pass

    for pid in preferred:
        try:
            pid = str(pid)
            if pid in (do_not_use or []):
                continue
            if isinstance(value_packs, dict) and pid in value_packs:
                return pid
        except Exception:
            continue

    try:
        if isinstance(value_packs, dict) and value_packs:
            return str(next(iter(value_packs.keys())))
    except Exception:
        pass
    return ""


def _render_pack_reply(decider: Dict[str, Any], kb: Dict[str, Any]) -> Dict[str, Any]:
    """Render determinístico: 1 pack, short por padrão, tokens por segmento."""
    value_packs = kb.get("value_packs_v1") or {}
    seg_map = kb.get("segment_value_map_v1") or {}
    policy = kb.get("pack_selection_policy_v1") or {}

    pack_id = str(decider.get("packId") or decider.get("pack_id") or "").strip()
    if not pack_id:
        pack_id = _select_pack_id(decider, kb)

    if not pack_id or not isinstance(value_packs, dict) or pack_id not in value_packs:
        return {"ok": False, "reason": "no_pack"}

    pack = dict(value_packs.get(pack_id) or {})

    segment_key = str(decider.get("segmentKey") or "").strip()
    seg_tokens = {}
    do_not_use = []
    seg_question_text = "Qual é seu tipo de negócio?"
    try:
        seg_handling = (policy.get("segment_handling") or {}) if isinstance(policy, dict) else {}
        seg_question_text = str(seg_handling.get("segment_question_text") or seg_question_text)
    except Exception:
        pass

    if segment_key and isinstance(seg_map, dict) and segment_key in seg_map:
        seg = seg_map.get(segment_key) or {}
        try:
            do_not_use = list(seg.get("do_not_use") or [])
        except Exception:
            do_not_use = []
        if pack_id in do_not_use:
            # se segmento proíbe, troca pack pelo primeiro permitido
            try:
                pref = list(seg.get("preferred_packs") or [])
                for pid in pref:
                    pid = str(pid)
                    if pid != pack_id and pid not in do_not_use and pid in value_packs:
                        pack_id = pid
                        pack = dict(value_packs.get(pid) or {})
                        break
            except Exception:
                pass

        try:
            tokens = (seg.get("tokens") or {}) if isinstance(seg, dict) else {}
            seg_tokens = (tokens.get(pack_id) or {}) if isinstance(tokens, dict) else {}
        except Exception:
            seg_tokens = {}

    # slots defaults
    slots: Dict[str, str] = {}
    try:
        seg_slots = (pack.get("segment_slots") or {}) if isinstance(pack, dict) else {}
        for k, v in (seg_slots or {}).items():
            dv = (v or {}).get("default")
            if dv is not None:
                slots[str(k)] = str(dv)
    except Exception:
        pass

    # override tokens
    try:
        if isinstance(seg_tokens, dict):
            for k, v in seg_tokens.items():
                if v is not None:
                    slots[str(k)] = str(v)
    except Exception:
        pass

    render_mode = str(decider.get("renderMode") or "short").strip().lower()
    if render_mode not in ("short", "long"):
        render_mode = "short"

    if render_mode == "long":
        txt = str(((pack.get("runtime_long") or {}) if isinstance(pack, dict) else {}).get("text") or "")
        reply = _simple_tpl(txt, slots).strip()
    else:
        short = ((pack.get("runtime_short") or {}) if isinstance(pack, dict) else {})
        value_one_liner = str(short.get("value_one_liner") or "").strip()
        bridge_line = str(short.get("bridge_line") or "").strip()
        micro = str(
            short.get("micro_scene_conversational")
            or short.get("micro_scene")
            or ""
        ).strip()

        reply_parts = []
        if value_one_liner:
            reply_parts.append(_simple_tpl(value_one_liner, slots).strip())
        if bridge_line:
            reply_parts.append(_simple_tpl(bridge_line, slots).strip())
        if micro:
            reply_parts.append(_simple_tpl(micro, slots).strip())

        reply = "\n".join([p for p in reply_parts if p]).strip()
        ex = str(slots.get("example_line") or "").strip()
        if ex:
            reply = (reply + "\n" + ex).strip()

    # 1 pergunta no máximo: clarify > segment
    needs_clarify = str(decider.get("needsClarify") or "no").strip().lower()
    clarify_q = str(decider.get("clarifyQuestion") or "").strip()
    should_ask_segment = str(decider.get("shouldAskSegment") or "no").strip().lower()

    q = ""
    if needs_clarify == "yes" and clarify_q:
        q = clarify_q
    elif (not segment_key) and should_ask_segment == "yes":
        q = seg_question_text

    if q:
        if "?" not in q:
            q = q.rstrip(".!") + "?"
        if "?" not in reply:
            reply = (reply.rstrip() + " " + q).strip()

    return {
        "ok": True,
        "packId": pack_id,
        "renderMode": render_mode,
        "segmentKey": segment_key,
        "replyText": reply.strip(),
        "spokenText": "",
    }



def _prefer_structured_front_reply(front_out: Dict[str, Any], rendered: Dict[str, Any]) -> Dict[str, Any]:
    """
    Decide qual saída usar no front:
    - se houver render determinístico válido, ele vence
    - senão mantém o front_out original
    Safe-by-default: não inventa texto novo aqui
    """
    try:
        out = dict(front_out or {})
        rend = dict(rendered or {})

        rendered_reply = str(rend.get("replyText") or "").strip()
        if not rendered_reply:
            return out

        out["replyText"] = rendered_reply

        rendered_spoken = str(rend.get("spokenText") or "").strip()
        if rendered_spoken:
            out["spokenText"] = rendered_spoken

        if rend.get("packId"):
            out["packId"] = rend.get("packId")
        if rend.get("renderMode"):
            out["renderMode"] = rend.get("renderMode")
        if rend.get("segmentKey"):
            out["segmentKey"] = rend.get("segmentKey")

        out["replySource"] = "pack_engine"
        return out
    except Exception:
        return dict(front_out or {})


def _load_prof_robot_persona_v1(uid: str) -> Dict[str, Any]:
    """Carrega (best-effort) a persona/jeito de atender do profissional.
    - Fontes aceitas (compat):
        1) profissionais/{uid}.config.jeitoAtenderV1  (canônico novo)
        2) profissionais/{uid}.config.robotPersona    (legado do front)
    - Safe-by-default: retorna {} em qualquer falha/ausência
    """
    uid = (uid or "").strip()
    if not uid:
        return {}
    try:
        from firebase_admin import firestore  # type: ignore
        db = firestore.client()
        snap = db.collection("profissionais").document(uid).get()
        data = (snap.to_dict() or {}) if snap else {}
        cfg = data.get("config") or {}
        # Preferência: V1 canônico; fallback: legado robotPersona
        persona = cfg.get("jeitoAtenderV1") or {}
        if not isinstance(persona, dict) or not persona:
            persona = cfg.get("robotPersona") or {}
        return persona if isinstance(persona, dict) else {}
    except Exception:
        return {}



def _safe_json_dumps_with_limit(payload: dict, limit: int) -> str:
    """
    Serializa payload garantindo JSON válido dentro do limite.
    Nunca corta string no meio.
    """
    try:
        protected_subsegment_ids = [
            str(x or "").strip()
            for x in (payload.get("_protected_subsegment_ids") or [])
            if str(x or "").strip()
        ]

        payload_for_dump = dict(payload or {})
        payload_for_dump.pop("_protected_subsegment_ids", None)

        s = json.dumps(payload_for_dump, ensure_ascii=False, separators=(",", ":"))
        if len(s) <= limit:
            return s

        if protected_subsegment_ids:
            kb_sub = payload.get("kb_subsegments_v1") or {}
            kb_seg = payload.get("kb_segments_v1") or {}
            kb_arch = payload.get("kb_archetypes_v1") or {}

            protected_subsegments = {
                sid: kb_sub.get(sid)
                for sid in protected_subsegment_ids
                if isinstance(kb_sub, dict) and isinstance(kb_sub.get(sid), dict)
            }
            protected_segment_ids = {
                str(doc.get("segment_id") or "").strip()
                for doc in protected_subsegments.values()
                if isinstance(doc, dict) and str(doc.get("segment_id") or "").strip()
            }
            protected_archetype_ids = {
                str(doc.get("archetype_id") or "").strip()
                for doc in protected_subsegments.values()
                if isinstance(doc, dict) and str(doc.get("archetype_id") or "").strip()
            }

            protected_segments = {
                sid: kb_seg.get(sid)
                for sid in protected_segment_ids
                if isinstance(kb_seg, dict) and isinstance(kb_seg.get(sid), dict)
            }
            protected_archetypes = {
                aid: kb_arch.get(aid)
                for aid in protected_archetype_ids
                if isinstance(kb_arch, dict) and isinstance(kb_arch.get(aid), dict)
            }

            protected_minimal = {
                "answer_playbook_v1": {
                    "runtime_selector_v1": ((payload.get("answer_playbook_v1") or {}).get("runtime_selector_v1") or {}),
                    "segment_value_map_v1": {},
                },
                "value_packs_v1": {},
                "platform_pricing": {},
                "process_facts": {},
                "kb_segments_v1": _front_minimal_hydratable_docs(protected_segments),
                "kb_subsegments_v1": _front_minimal_hydratable_docs(protected_subsegments),
                "kb_archetypes_v1": _front_minimal_hydratable_docs(protected_archetypes),
            }
            s_protected = json.dumps(protected_minimal, ensure_ascii=False, separators=(",", ":"))
            if len(s_protected) <= limit:
                return s_protected

            protected_core = dict(protected_minimal)
            protected_core["kb_segments_v1"] = {}
            protected_core["kb_archetypes_v1"] = {}
            s_core = json.dumps(protected_core, ensure_ascii=False, separators=(",", ":"))
            if protected_core.get("kb_subsegments_v1") and len(s_core) <= limit:
                return s_core

        # fallback seguro mínimo:
        # preserva o runtime de packs_v1 antes do banco operacional auxiliar.
        minimal = {
            "answer_playbook_v1": {
                "runtime_selector_v1": ((payload.get("answer_playbook_v1") or {}).get("runtime_selector_v1") or {}),
                "pack_selection_policy_v1": ((payload.get("answer_playbook_v1") or {}).get("pack_selection_policy_v1") or {}),
                "segment_template_v1": ((payload.get("answer_playbook_v1") or {}).get("segment_template_v1") or {}),
                "segment_value_map_v1": ((payload.get("answer_playbook_v1") or {}).get("segment_value_map_v1") or {}),
            },
            "value_packs_v1": payload.get("value_packs_v1") or {},
            "platform_pricing": {},
            "process_facts": payload.get("process_facts") or {},
            "kb_segments_v1": {},
            "kb_subsegments_v1": {},
            "kb_archetypes_v1": {},
        }
        s2 = json.dumps(minimal, ensure_ascii=False, separators=(",", ":"))
        if len(s2) <= limit:
            return s2

        # último fallback: mantém o mínimo que permite escolher/renderizar pack.
        ultra_minimal = {
            "answer_playbook_v1": {
                "runtime_selector_v1": ((payload.get("answer_playbook_v1") or {}).get("runtime_selector_v1") or {}),
                "pack_selection_policy_v1": ((payload.get("answer_playbook_v1") or {}).get("pack_selection_policy_v1") or {}),
                "segment_template_v1": ((payload.get("answer_playbook_v1") or {}).get("segment_template_v1") or {}),
                "segment_value_map_v1": ((payload.get("answer_playbook_v1") or {}).get("segment_value_map_v1") or {}),
            },
            "value_packs_v1": payload.get("value_packs_v1") or {},
            "platform_pricing": {},
            "process_facts": payload.get("process_facts") or {},
            "kb_segments_v1": {},
            "kb_subsegments_v1": {},
            "kb_archetypes_v1": {},
        }
        s3 = json.dumps(ultra_minimal, ensure_ascii=False, separators=(",", ":"))
        if len(s3) <= limit:
            return s3

        # fallback extremo: só packs + selector, sem mapa segmentado.
        extreme = {
            "answer_playbook_v1": {
                "runtime_selector_v1": ((payload.get("answer_playbook_v1") or {}).get("runtime_selector_v1") or {}),
            },
            "kb_segments_v1": {},
            "platform_pricing": {},
            "value_packs_v1": payload.get("value_packs_v1") or {},
            "process_facts": payload.get("process_facts") or {},
            "kb_subsegments_v1": {},
            "kb_archetypes_v1": {},
        }
        s4 = json.dumps(extreme, ensure_ascii=False, separators=(",", ":"))
        if len(s4) <= limit:
            return s4

        # fallback extremo 2: selector puro.
        ultra_minimal = {
            "answer_playbook_v1": {
                "runtime_selector_v1": ((payload.get("answer_playbook_v1") or {}).get("runtime_selector_v1") or {}),
            },
            "kb_segments_v1": {},
            "value_packs_v1": {},
            "platform_pricing": {},
            "process_facts": payload.get("process_facts") or {},
            "kb_subsegments_v1": {},
            "kb_archetypes_v1": {},
        }
        s5 = json.dumps(ultra_minimal, ensure_ascii=False, separators=(",", ":"))
        return s5 if len(s5) <= limit else "{}"
    except Exception:
        return "{}"


def _prune_front_kb_payload(payload: dict, limit: int) -> dict:
    """
    Reduz payload por etapas, preservando JSON válido.
    Remove blocos inteiros, nunca corta no meio.
    """
    try:
        work = dict(payload or {})

        def _size(obj: dict) -> int:
            return len(json.dumps(obj, ensure_ascii=False, separators=(",", ":")))

        def _lean_operational_docs(docs: Any) -> Dict[str, Any]:
            """
            Mantém um índice mínimo dos documentos operacionais para o front
            conseguir reconhecer semanticamente segmento/subsegmento.
            Não cria regra comercial, não usa palavra-chave fixa e não escolhe
            segmento no código: apenas preserva campos já vindos do Firestore.
            """
            out: Dict[str, Any] = {}
            try:
                if not isinstance(docs, dict):
                    return {}
                keep_fields = (
                    "id",
                    "segment_id",
                    "archetype_id",
                    "name",
                    "description",
                    "one_liner",
                    "micro_scene_conversational",
                    "lead_refinement_question",
                    "micro_scene",
                    "direct_scene",
                    "runtime_long_text",
                    "primary_goal",
                    "customer_noun",
                    "conversion_noun",
                    "enabled",
                    "keywords",
                    "negative_keywords",
                    "common_intents",
                    "preferred_capabilities",
                    "operational_ritual",
                    "handoff_format",
                    "conversation_mode",
                    "service_noun",
                    "snapshot_priority",
                    "commercial_runtime",
                    "operational_runtime",
                    "medical_runtime",
                    "behavior_components",
                )
                for doc_id, doc in list(docs.items()):
                    if not isinstance(doc, dict):
                        continue
                    item: Dict[str, Any] = {}
                    for field in keep_fields:
                        value = doc.get(field)
                        if value not in (None, "", [], {}):
                            if field == "snapshot_priority":
                                compacted = _front_compact_snapshot_priority(value)
                                if compacted not in (None, "", [], {}):
                                    item[field] = compacted
                            elif field in ("commercial_runtime", "operational_runtime", "medical_runtime", "behavior_components"):
                                compacted = _front_compact_v2_runtime_block(value, char_limit=700)
                                if compacted:
                                    item[field] = compacted
                            else:
                                item[field] = value
                    if item:
                        out[str(doc_id)] = item
                return out
            except Exception:
                return {}

        if _size(work) <= limit:
            return work

        # 1) corta pricing antes do runtime de vendas.
        if work.get("platform_pricing"):
            work["platform_pricing"] = {}
            if _size(work) <= limit:
                return work

        # 2) antes de apagar documentos operacionais inteiros, reduz esses docs
        # para um índice semântico mínimo. Isso preserva a capacidade do front
        # de reconhecer segmento/subsegmento informado em linguagem livre.
        if (
            work.get("kb_segments_v1")
            or work.get("kb_subsegments_v1")
            or work.get("kb_archetypes_v1")
        ):
            if work.get("kb_segments_v1"):
                work["kb_segments_v1"] = _lean_operational_docs(work.get("kb_segments_v1"))
            if work.get("kb_subsegments_v1"):
                work["kb_subsegments_v1"] = _lean_operational_docs(work.get("kb_subsegments_v1"))
            if work.get("kb_archetypes_v1"):
                work["kb_archetypes_v1"] = _lean_operational_docs(work.get("kb_archetypes_v1"))
            if _size(work) <= limit:
                return work

        # 3) enxuga partes menos essenciais do playbook, preservando seleção e tokens.
        ap = dict(work.get("answer_playbook_v1") or {})
        keep_runtime = {
            "runtime_selector_v1": ap.get("runtime_selector_v1") or {},
            "pack_selection_policy_v1": ap.get("pack_selection_policy_v1") or {},
            "segment_template_v1": ap.get("segment_template_v1") or {},
            "segment_value_map_v1": ap.get("segment_value_map_v1") or {},
        }
        work["answer_playbook_v1"] = keep_runtime
        if _size(work) <= limit:
            return work

        # 4) prioridade arquitetural:
        # antes de sacrificar docs operacionais segmentados, preserva
        # kb_segments/kb_subsegments/kb_archetypes e tenta reduzir packs globais.
        #
        # Motivo:
        # - docs segmentados permitem o front reconhecer "loja de óculos";
        # - sem eles, o front cai em fallback global e mistura conteúdo genérico;
        # - não cria regra comercial, apenas preserva a fonte operacional.
        ap = dict(work.get("answer_playbook_v1") or {})
        if ap.get("segment_value_map_v1"):
            ap["segment_value_map_v1"] = {}
            work["answer_playbook_v1"] = ap
            if _size(work) <= limit:
                return work

        # 6) antes de sacrificar fatos operacionais curtos, reduz agressivamente
        # campos longos dos packs globais.
        #
        # Princípio arquitetural:
        # - continuidade depende mais de fatos objetivos curtos do que de
        #   microcenas longas;
        # - process_facts deve sobreviver o máximo possível;
        # - não introduzimos regras comerciais nem palavras-chave;
        # - apenas priorizamos densidade operacional por token.
        try:
            vp = dict(work.get("value_packs_v1") or {})
            trimmed = {}

            for pid, pack in list(vp.items()):
                if not isinstance(pack, dict):
                    continue

                p = dict(pack)

                rs = dict(p.get("runtime_short") or {})
                if rs:
                    # continuidade precisa mais do núcleo factual do que de
                    # cenas longas conversacionais.
                    rs.pop("micro_scene_conversational", None)
                    "lead_refinement_question",
                    rs.pop("micro_scene", None)

                    if rs:
                        p["runtime_short"] = rs
                    else:
                        p.pop("runtime_short", None)

                # runtime_long é o maior consumidor de snapshot e não é
                # essencial para respostas de continuidade.
                p.pop("runtime_long", None)

                trimmed[pid] = p

            if trimmed:
                work["value_packs_v1"] = trimmed

            if _size(work) <= limit:
                return work
        except Exception:
            pass

        # 7) proteção do subsegmento selecionado:
        # quando há candidato explícito, o documento específico tem prioridade
        # sobre packs globais. Isso evita preservar fallback e sacrificar V2.
        protected_subsegment_ids = []
        try:
            protected_subsegment_ids = [
                str(x or "").strip()
                for x in (work.get("_protected_subsegment_ids") or [])
                if str(x or "").strip()
            ]
        except Exception:
            protected_subsegment_ids = []

        if protected_subsegment_ids:
            if work.get("value_packs_v1"):
                work["value_packs_v1"] = {}
                if _size(work) <= limit:
                    return work

            ap = dict(work.get("answer_playbook_v1") or {})
            if ap.get("segment_value_map_v1"):
                ap["segment_value_map_v1"] = {}
                work["answer_playbook_v1"] = ap
                if _size(work) <= limit:
                    return work

            if work.get("process_facts"):
                work["process_facts"] = {}
                if _size(work) <= limit:
                    return work

            ap = dict(work.get("answer_playbook_v1") or {})
            if ap.get("segment_template_v1") or ap.get("pack_selection_policy_v1") or ap.get("segment_value_map_v1"):
                work["answer_playbook_v1"] = {
                    "runtime_selector_v1": ap.get("runtime_selector_v1") or {},
                }
                if _size(work) <= limit:
                    return work

        # 8) último recurso antes de remover packs globais:
        # só agora sacrifica docs operacionais segmentados quando não há proteção
        # ou quando, mesmo protegido, os pais ainda precisam ser reduzidos.
        if work.get("kb_archetypes_v1"):
            work["kb_archetypes_v1"] = {}
            if _size(work) <= limit:
                return work

        if work.get("kb_segments_v1"):
            work["kb_segments_v1"] = {}
            if _size(work) <= limit:
                return work

        if work.get("kb_subsegments_v1") and not protected_subsegment_ids:
            work["kb_subsegments_v1"] = {}
            if _size(work) <= limit:
                return work

        # 9) último recurso comercial: remove packs somente se nem assim couber.
        if work.get("value_packs_v1"):
            work["value_packs_v1"] = {}
            if _size(work) <= limit:
                return work

        ap = dict(work.get("answer_playbook_v1") or {})
        if ap.get("segment_template_v1") or ap.get("pack_selection_policy_v1"):
            work["answer_playbook_v1"] = {
                "runtime_selector_v1": ap.get("runtime_selector_v1") or {},
            }
            if _size(work) <= limit:
                return work

        # 8) process_facts é a última estrutura operacional a cair.
        # Ela alimenta respostas objetivas de continuidade e possui alta
        # densidade de valor por caractere.
        if work.get("process_facts"):
            work["process_facts"] = {}
            if _size(work) <= limit:
                return work

        return work
    except Exception:
        return payload or {}


def _compact_value_packs_for_front(value_packs: Any) -> Dict[str, Any]:
    """
    Compacta packs globais para o snapshot do front.
    Preserva o runtime curto e os slots; remove textos longos que estouram o limite.
    """
    out: Dict[str, Any] = {}
    try:
        if not isinstance(value_packs, dict):
            return {}

        for pid, pack in list(value_packs.items()):
            if not isinstance(pack, dict):
                continue

            p: Dict[str, Any] = {}

            if pack.get("label"):
                p["label"] = _clip_front_text(pack.get("label"), 80)

            runtime_short = pack.get("runtime_short") or {}
            if isinstance(runtime_short, dict):
                runtime_short_out: Dict[str, Any] = {}

                value_one_liner = _clip_front_text(runtime_short.get("value_one_liner"), 520)
                bridge_line = _clip_front_text(runtime_short.get("bridge_line"), 220)
                micro_scene_conversational = _clip_front_text(
                    runtime_short.get("micro_scene_conversational"),
                    900,
                )
                micro_scene = _clip_front_text(runtime_short.get("micro_scene"), 320)

                if value_one_liner:
                    runtime_short_out["value_one_liner"] = value_one_liner
                if bridge_line:
                    runtime_short_out["bridge_line"] = bridge_line
                if micro_scene_conversational:
                    runtime_short_out["micro_scene_conversational"] = micro_scene_conversational
                if micro_scene:
                    runtime_short_out["micro_scene"] = micro_scene

                if runtime_short_out:
                    p["runtime_short"] = runtime_short_out

            runtime_long = pack.get("runtime_long") or {}
            if isinstance(runtime_long, dict):
                runtime_long_text = _clip_front_text(runtime_long.get("text"), 2200)
                if runtime_long_text:
                    p["runtime_long"] = {"text": runtime_long_text}

            slots_out: Dict[str, Any] = {}
            segment_slots = pack.get("segment_slots") or {}
            if isinstance(segment_slots, dict):
                for sk, sv in list(segment_slots.items()):
                    if not isinstance(sv, dict):
                        continue
                    default_value = _clip_front_text(sv.get("default"), 140)
                    if default_value:
                        slots_out[str(sk)] = {"default": default_value}
            if slots_out:
                p["segment_slots"] = slots_out

            outcomes = pack.get("outcomes") or []
            if isinstance(outcomes, list):
                picked = [
                    _clip_front_text(x, 100)
                    for x in outcomes[:4]
                    if _clip_front_text(x, 100)
                ]
                if picked:
                    p["outcomes"] = picked

            limits = pack.get("limits") or []
            if isinstance(limits, list):
                picked = [
                    _clip_front_text(x, 100)
                    for x in limits[:3]
                    if _clip_front_text(x, 100)
                ]
                if picked:
                    p["limits"] = picked

            if p:
                out[str(pid)] = p

        return out
    except Exception:
        return {}




def _compact_segment_value_map_for_front(segment_value_map: Any, topic: str = "") -> Dict[str, Any]:
    """
    Compacta o mapa de personalização por segmento para o snapshot do front.
    Preserva somente dados operacionais usados pelo runtime e reduz tokens ao tópico atual.
    """
    out: Dict[str, Any] = {}
    try:
        if not isinstance(segment_value_map, dict):
            return {}

        topic_key = str(topic or "").strip().upper()

        for seg_key, profile in list(segment_value_map.items()):
            if not isinstance(profile, dict):
                continue

            item: Dict[str, Any] = {}

            preferred = profile.get("preferred_packs") or []
            if isinstance(preferred, list):
                picked = [
                    str(x or "").strip().upper()
                    for x in preferred[:6]
                    if str(x or "").strip()
                ]
                if picked:
                    item["preferred_packs"] = picked

            blocked = profile.get("do_not_use") or []
            if isinstance(blocked, list):
                picked = [
                    str(x or "").strip().upper()
                    for x in blocked[:6]
                    if str(x or "").strip()
                ]
                if picked:
                    item["do_not_use"] = picked

            tokens = profile.get("tokens") or {}
            if isinstance(tokens, dict):
                tokens_out: Dict[str, Any] = {}
                for pack_key, token_map in list(tokens.items()):
                    pack_id = str(pack_key or "").strip().upper()
                    if topic_key and pack_id != topic_key:
                        continue
                    if not isinstance(token_map, dict):
                        continue

                    token_out: Dict[str, Any] = {}
                    for tk, tv in list(token_map.items()):
                        clipped = _clip_front_text(tv, 420)
                        if clipped:
                            token_out[str(tk)] = clipped
                    if token_out:
                        tokens_out[pack_id] = token_out

                if tokens_out:
                    item["tokens"] = tokens_out

            if item:
                out[str(seg_key)] = item

        return out
    except Exception:
        return {}


def _front_find_kb_map_anywhere(obj: Any, target_key: str, max_depth: int = 5) -> Dict[str, Any]:
    """
    Localiza mapas do platform_kb em qualquer nível razoável do snapshot.
    Não cria regra comercial; apenas resolve a localização real do dado no Firestore.
    """
    try:
        if max_depth < 0 or not target_key:
            return {}

        if isinstance(obj, dict):
            direct = obj.get(target_key)
            if isinstance(direct, dict):
                return direct

            for _, value in obj.items():
                found = _front_find_kb_map_anywhere(value, target_key, max_depth=max_depth - 1)
                if isinstance(found, dict) and found:
                    return found

        elif isinstance(obj, list):
            for item in obj:
                found = _front_find_kb_map_anywhere(item, target_key, max_depth=max_depth - 1)
                if isinstance(found, dict) and found:
                    return found

        return {}
    except Exception:
        return {}


# FRONT_KB_GENERIC_SUBSEGMENT_TARGET_V1
# Seleção genérica KB-driven de subsegmentos antes do prune.
# Não contém palavras-chave de negócio; usa somente campos publicados no Firestore.
def _front_kb_match_norm_v1(value: object) -> str:
    try:
        import re
        import unicodedata

        s = str(value or "")
        s = unicodedata.normalize("NFKD", s)
        s = "".join(ch for ch in s if not unicodedata.combining(ch))
        s = s.lower()
        s = re.sub(r"[^a-z0-9]+", " ", s)
        return " ".join(s.split())
    except Exception:
        return str(value or "").lower().strip()


def _front_kb_match_tokens_v1(value: object) -> set:
    try:
        return {tok for tok in _front_kb_match_norm_v1(value).split() if len(tok) >= 3}
    except Exception:
        return set()


def _front_kb_clean_list_v1(value: object) -> list:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple, set)):
        out = []
        for item in value:
            s = str(item or "").strip()
            if s:
                out.append(s)
        return out
    return []


def _front_kb_identity_values_for_doc_v1(doc_key: str, doc: object) -> list:
    """Valores identitários vindos do KB.

    Se routing_identity_anchors existir, ele é soberano para seleção genérica.
    Caso contrário, usa fallback conservador por id/name/keywords.
    """
    try:
        if not isinstance(doc, dict):
            return []

        explicit = _front_kb_clean_list_v1(doc.get("routing_identity_anchors"))
        if explicit:
            return [str(v or "").strip() for v in explicit if str(v or "").strip()]

        values = [
            str(doc_key or ""),
            str(doc.get("id") or ""),
            str(doc.get("name") or ""),
        ]

        for item in _front_kb_clean_list_v1(doc.get("keywords")):
            values.append(str(item or ""))

        return [v for v in values if str(v or "").strip()]
    except Exception:
        return []

def _front_kb_identity_terms_for_doc_v1(doc_key: str, doc: object) -> set:
    try:
        terms = set()
        for value in _front_kb_identity_values_for_doc_v1(doc_key, doc):
            terms.update(_front_kb_match_tokens_v1(value))
        return terms
    except Exception:
        return set()


def _front_kb_identity_phrases_for_doc_v1(doc_key: str, doc: object) -> set:
    try:
        phrases = set()
        for value in _front_kb_identity_values_for_doc_v1(doc_key, doc):
            norm = _front_kb_match_norm_v1(value)
            if norm and len(norm) >= 4:
                phrases.add(norm)
        return phrases
    except Exception:
        return set()


def _front_kb_negative_matches_current_text_v1(user_text: str, doc: object) -> bool:
    try:
        if not isinstance(doc, dict):
            return False

        q_norm = _front_kb_match_norm_v1(user_text)
        q_tokens = _front_kb_match_tokens_v1(user_text)

        items = []
        items.extend(_front_kb_clean_list_v1(doc.get("routing_negative_anchors")))
        items.extend(_front_kb_clean_list_v1(doc.get("negative_keywords")))

        for item in items:
            norm = _front_kb_match_norm_v1(item)
            toks = _front_kb_match_tokens_v1(item)

            if not norm or not toks:
                continue

            if len(toks) == 1:
                tok = next(iter(toks))
                if tok in q_tokens:
                    return True
                continue

            if len(norm) >= 4 and norm in q_norm:
                return True
            if toks.issubset(q_tokens):
                return True

        return False
    except Exception:
        return False

def _front_score_subsegment_for_current_text_v1(user_text: str, doc_key: str, doc: object) -> int:
    """Score genérico KB-driven.

    routing_identity_anchors/id/name/keywords destravam seleção.
    Contexto reforça apenas depois.
    negative_keywords veta.
    """
    try:
        if not isinstance(doc, dict):
            return 0
        if doc.get("enabled") is False:
            return 0
        if _front_kb_negative_matches_current_text_v1(user_text, doc):
            return 0

        q_norm = _front_kb_match_norm_v1(user_text)
        q_tokens = _front_kb_match_tokens_v1(user_text)
        if not q_norm or not q_tokens:
            return 0

        score = 0
        identity_score = 0

        for item in _front_kb_clean_list_v1(doc.get("routing_identity_anchors")):
            norm = _front_kb_match_norm_v1(item)
            toks = _front_kb_match_tokens_v1(item)
            overlap = len(q_tokens.intersection(toks))
            if overlap:
                points = overlap * 8
                score += points
                identity_score += points
            if norm and len(norm) >= 4 and norm in q_norm:
                points = 14
                score += points
                identity_score += points

        synthetic_id = str(doc.get("id") or doc_key or "").strip()

        for raw, weight in (
            (synthetic_id, 1),
            (doc.get("name"), 6),
        ):
            if not raw:
                continue
            norm = _front_kb_match_norm_v1(raw)
            toks = _front_kb_match_tokens_v1(raw)
            overlap = len(q_tokens.intersection(toks))
            if overlap:
                points = overlap * weight
                score += points
                identity_score += points
            if norm and len(norm) >= 4 and norm in q_norm:
                points = weight + 5
                score += points
                identity_score += points

        for item in _front_kb_clean_list_v1(doc.get("keywords")):
            norm = _front_kb_match_norm_v1(item)
            toks = _front_kb_match_tokens_v1(item)
            overlap = len(q_tokens.intersection(toks))
            if overlap:
                points = overlap * 7
                score += points
                identity_score += points
            if norm and len(norm) >= 4 and norm in q_norm:
                points = 12
                score += points
                identity_score += points

        if identity_score < 8:
            return 0

        for field in ("service_noun", "conversion_noun", "primary_goal", "one_liner"):
            raw = doc.get(field)
            if not raw:
                continue
            overlap = len(q_tokens.intersection(_front_kb_match_tokens_v1(raw)))
            if overlap:
                score += overlap

        for item in _front_kb_clean_list_v1(doc.get("common_intents")):
            norm = _front_kb_match_norm_v1(item)
            toks = _front_kb_match_tokens_v1(item)
            overlap = len(q_tokens.intersection(toks))
            if norm and len(norm) >= 8 and norm in q_norm:
                score += 4
            elif overlap >= 2:
                score += overlap

        return max(int(score), 0)
    except Exception:
        return 0

def _front_select_kb_subsegment_ids_from_text_v1(
    *,
    user_text: str,
    subsegments: object,
    max_ids: int = 1,
    min_score: int = 16,
    relative_floor: float = 0.85,
) -> list:
    """Seleciona top 1 apenas quando há âncora identitária rara/específica.

    Conservador por padrão:
    - id/name/keywords são a fonte de identidade;
    - common_intents e campos contextuais não destravam seleção;
    - negative_keywords vetam com regra segura;
    - enabled=False nunca entra;
    - termo comum no corpus não destrava seleção;
    - ambiguidade forte retorna [].
    """
    try:
        if not isinstance(subsegments, dict) or not str(user_text or "").strip():
            return []

        q_norm = _front_kb_match_norm_v1(user_text)
        q_tokens = _front_kb_match_tokens_v1(user_text)
        if not q_norm or not q_tokens:
            return []

        docs = {
            str(k or ""): v
            for k, v in subsegments.items()
            if str(k or "").strip() and isinstance(v, dict) and v.get("enabled") is not False
        }

        if not docs:
            return []

        corpus_size = max(1, len(docs))
        rare_limit = max(2, int(corpus_size * 0.02))

        token_doc_counts = {}
        phrase_doc_counts = {}

        for key, doc in docs.items():
            for tok in _front_kb_identity_terms_for_doc_v1(key, doc):
                token_doc_counts[tok] = token_doc_counts.get(tok, 0) + 1

            for phrase in _front_kb_identity_phrases_for_doc_v1(key, doc):
                phrase_tokens = _front_kb_match_tokens_v1(phrase)
                if len(phrase_tokens) >= 2:
                    phrase_doc_counts[phrase] = phrase_doc_counts.get(phrase, 0) + 1

        ranked = []

        for key, doc in docs.items():
            if _front_kb_negative_matches_current_text_v1(user_text, doc):
                continue

            identity_terms = _front_kb_identity_terms_for_doc_v1(key, doc)
            identity_phrases = _front_kb_identity_phrases_for_doc_v1(key, doc)

            phrase_hits = []
            for phrase in identity_phrases:
                phrase_tokens = _front_kb_match_tokens_v1(phrase)
                if len(phrase_tokens) < 2:
                    continue
                if phrase and phrase in q_norm and int(phrase_doc_counts.get(phrase) or 0) <= rare_limit:
                    phrase_hits.append(phrase)

            token_hits = []
            for tok in q_tokens.intersection(identity_terms):
                if len(tok) >= 5 and int(token_doc_counts.get(tok) or 0) <= rare_limit:
                    token_hits.append(tok)

            # Sem âncora identitária rara, não protege nada.
            if not phrase_hits and not token_hits:
                continue

            base_score = _front_score_subsegment_for_current_text_v1(
                user_text=str(user_text or ""),
                doc_key=key,
                doc=doc,
            )
            if base_score <= 0:
                continue

            phrase_bonus = sum(
                20 + (len(_front_kb_match_tokens_v1(phrase)) * 4)
                for phrase in phrase_hits
            )
            token_bonus = len(token_hits) * 14

            score = int(base_score) + int(phrase_bonus) + int(token_bonus)

            ranked.append((
                score,
                key,
                len(phrase_hits),
                len(token_hits),
            ))

        ranked.sort(key=lambda item: (-item[0], item[1]))

        if not ranked:
            return []

        top_score, top_key, top_phrase_count, top_token_count = ranked[0]

        if int(top_score) < max(int(min_score), 16):
            return []

        if len(ranked) > 1:
            runner_score = int(ranked[1][0])

            # Empate forte: melhor discovery do que snapshot contaminado.
            if runner_score >= int(int(top_score) * float(relative_floor)):
                return []

        return [top_key]
    except Exception:
        return []

def _build_front_kb_snapshot(topic: str, user_text: str = "") -> str:
    """
    Monta snapshot textual compacto com teto de chars.
    """
    src = _fetch_front_kb_sources()
    kb = src.get("kb") or {}
    pr = src.get("pricing") or {}
    segments = src.get("segments") or {}
    subsegments = src.get("subsegments") or {}
    archetypes = src.get("archetypes") or {}

    # BASE OPERACIONAL COMPACTA (nomes canônicos esperados pelo front)
    compact_segments = {}
    try:
        for sid, sd in list((segments or {}).items()):
            if not isinstance(sd, dict):
                continue
            compact_segments[sid] = _compact_front_kb_doc(
                sd,
                doc_id=sid,
                include_archetype_id=True,
            )
    except Exception:
        compact_segments = {}

    compact_subsegments = {}
    try:
        for sid, sd in list((subsegments or {}).items()):
            if not isinstance(sd, dict):
                continue
            compact_subsegments[sid] = _compact_front_kb_doc(
                sd,
                doc_id=sid,
                include_segment_id=True,
                include_archetype_id=True,
            )
    except Exception:
        compact_subsegments = {}

    compact_archetypes = {}
    try:
        for aid, ad in list((archetypes or {}).items()):
            if not isinstance(ad, dict):
                continue
            compact_archetypes[aid] = _compact_front_kb_doc(ad, doc_id=aid)
    except Exception:
        compact_archetypes = {}

    protected_subsegment_ids = []
    try:
        target_subsegment_ids = _front_target_subsegment_ids(user_text)

        if target_subsegment_ids and compact_subsegments:
            reduced_subsegments, reduced_segments, reduced_archetypes, reduced_protected_ids = (
                _front_reduce_kb_docs_to_selected_subsegments(
                    selected_ids=target_subsegment_ids,
                    compact_subsegments=compact_subsegments,
                    compact_segments=compact_segments,
                    compact_archetypes=compact_archetypes,
                    raw_subsegments=subsegments,
                )
            )

            if reduced_subsegments:
                compact_subsegments = reduced_subsegments
                compact_segments = reduced_segments
                compact_archetypes = reduced_archetypes
                protected_subsegment_ids = reduced_protected_ids

            logging.info(
                "[WA_BOT][KB_TARGET_SUBSEGMENT] targets=%s kept_subsegments=%s kept_segments=%s kept_archetypes=%s",
                target_subsegment_ids,
                list(compact_subsegments.keys())[:8],
                list(compact_segments.keys())[:8],
                list(compact_archetypes.keys())[:8],
            )
    except Exception as e:
        protected_subsegment_ids = []
        logging.warning("[WA_BOT][KB_TARGET_SUBSEGMENT] error=%s", str(e)[:180])


    # ✅ packs_v1: snapshot em JSON compacto (para render determinístico no front)
    try:
        pb = (kb.get("answer_playbook_v1") or {}) if isinstance(kb, dict) else {}
        rs = (pb.get("runtime_selector_v1") or {}) if isinstance(pb, dict) else {}
        mode = str((rs.get("mode") or "")).strip().lower()
        if mode == "packs_v1":
            import json as _json
            snapshot_limit = FRONT_KB_MAX_CHARS_PACKS_V1
            value_packs_source = _front_find_kb_map_anywhere(kb, "value_packs_v1")
            segment_value_map_source = _front_find_kb_map_anywhere(kb, "segment_value_map_v1")
            pack_selection_policy_source = _front_find_kb_map_anywhere(kb, "pack_selection_policy_v1")
            segment_template_source = _front_find_kb_map_anywhere(kb, "segment_template_v1")
            process_facts_source = _front_find_kb_map_anywhere(kb, "process_facts")
            # pricing compacto (canônico: platform_pricing/current)
            pricing_compact = {}
            try:
                if isinstance(pr, dict) and pr:
                    pricing_compact = {
                        "billing_model": pr.get("billing_model") or "",
                        "currency": pr.get("currency") or "BRL",
                        "display_prices": pr.get("display_prices") or {},
                        "plans": pr.get("plans") or {},
                        "notes": pr.get("notes") or "",
                        "version": pr.get("version") or "",
                    }
            except Exception:
                pricing_compact = {}
            payload = {
                "answer_playbook_v1": {
                    "runtime_selector_v1": pb.get("runtime_selector_v1") if isinstance(pb, dict) else {},
                    "pack_selection_policy_v1": pack_selection_policy_source or (pb.get("pack_selection_policy_v1") if isinstance(pb, dict) else {}),
                    "segment_template_v1": segment_template_source or (pb.get("segment_template_v1") if isinstance(pb, dict) else {}),
                    "segment_value_map_v1": _compact_segment_value_map_for_front(
                        segment_value_map_source or (pb.get("segment_value_map_v1") if isinstance(pb, dict) else {}),
                        topic,
                    ),
                },
                "value_packs_v1": _compact_value_packs_for_front(value_packs_source or kb.get("value_packs_v1") or {}),
                "platform_pricing": {"current": pricing_compact} if pricing_compact else {},
                "process_facts": process_facts_source or kb.get("process_facts") or {},
                "kb_segments_v1": compact_segments,
                "kb_subsegments_v1": compact_subsegments,
                "kb_archetypes_v1": compact_archetypes,
                "_protected_subsegment_ids": protected_subsegment_ids,
            }

            # garantia mínima: se houver subsegments reais, eles são prioridade máxima
            # para a arquitetura do front baseada no banco novo
            if not payload.get("kb_subsegments_v1") and compact_subsegments:
                payload["kb_subsegments_v1"] = compact_subsegments

            logging.info(
                "[WA_BOT][KB_SNAPSHOT][BEFORE_PRUNE] src_segments=%s src_subsegments=%s src_archetypes=%s compact_segments=%s compact_subsegments=%s compact_archetypes=%s payload_segments=%s payload_subsegments=%s payload_archetypes=%s",
                len(segments or {}),
                len(subsegments or {}),
                len(archetypes or {}),
                len(compact_segments or {}),
                len(compact_subsegments or {}),
                len(compact_archetypes or {}),
                len((payload or {}).get("kb_segments_v1") or {}),
                len((payload or {}).get("kb_subsegments_v1") or {}),
                len((payload or {}).get("kb_archetypes_v1") or {}),
            )

            # FRONT_KB_GENERIC_SUBSEGMENT_TARGET_V1
            try:
                _generic_target_subsegment_ids = _front_select_kb_subsegment_ids_from_text_v1(
                    user_text=user_text,
                    subsegments=compact_subsegments,
                    max_ids=1,
                    min_score=16,
                    relative_floor=0.85,
                )
                if _generic_target_subsegment_ids:
                    _sub, _seg, _arch, _protected_subsegment_ids = (
                        _front_reduce_kb_docs_to_selected_subsegments(
                            selected_ids=_generic_target_subsegment_ids,
                            compact_subsegments=compact_subsegments,
                            compact_segments=compact_segments,
                            compact_archetypes=compact_archetypes,
                            raw_subsegments=subsegments,
                        )
                    )
                    if _sub:
                        payload["kb_subsegments_v1"] = _sub
                        payload["kb_segments_v1"] = _seg
                        payload["kb_archetypes_v1"] = _arch
                        payload["_protected_subsegment_ids"] = _protected_subsegment_ids

                    try:
                        import json as _json_for_generic_target_v1
                        import logging as _logging_for_generic_target_v1
                        _logging_for_generic_target_v1.info(
                            "[WA_BOT][KB_TARGET_SUBSEGMENT_GENERIC] selected=%s protected=%s payload_chars=%s limit=%s",
                            list(_generic_target_subsegment_ids),
                            list(payload.get("_protected_subsegment_ids") or []),
                            len(_json_for_generic_target_v1.dumps(payload or {}, ensure_ascii=False, separators=(",", ":"))),
                            snapshot_limit,
                        )
                    except Exception:
                        pass
            except Exception as _generic_target_err:
                try:
                    import logging as _logging_for_generic_target_err_v1
                    _logging_for_generic_target_err_v1.info(
                        "[WA_BOT][KB_TARGET_SUBSEGMENT_GENERIC_ERROR] err=%s",
                        str(_generic_target_err),
                    )
                except Exception:
                    pass
            payload = _prune_front_kb_payload(payload, snapshot_limit)

            logging.info(
                "[WA_BOT][KB_SNAPSHOT][AFTER_PRUNE] payload_segments=%s payload_subsegments=%s payload_archetypes=%s payload_value_packs=%s payload_chars=%s limit=%s",
                len((payload or {}).get("kb_segments_v1") or {}),
                len((payload or {}).get("kb_subsegments_v1") or {}),
                len((payload or {}).get("kb_archetypes_v1") or {}),
                len((payload or {}).get("value_packs_v1") or {}),
                len(_json.dumps(payload or {}, ensure_ascii=False, separators=(",", ":"))),
                snapshot_limit,
            )

            try:
                subsegments_v1 = (payload or {}).get("kb_subsegments_v1") or {}

                has_commercial_runtime = False
                has_operational_runtime = False
                has_medical_runtime = False
                has_behavior_components = False
                has_snapshot_priority = False

                for doc in subsegments_v1.values():
                    if not isinstance(doc, dict):
                        continue

                    has_commercial_runtime = has_commercial_runtime or ("commercial_runtime" in doc)
                    has_operational_runtime = has_operational_runtime or ("operational_runtime" in doc)
                    has_medical_runtime = has_medical_runtime or ("medical_runtime" in doc)
                    has_behavior_components = has_behavior_components or ("behavior_components" in doc)
                    has_snapshot_priority = has_snapshot_priority or ("snapshot_priority" in doc)

                logging.info(
                    "[KB_V2_SNAPSHOT] "
                    "commercial_runtime=%s "
                    "operational_runtime=%s "
                    "medical_runtime=%s "
                    "behavior_components=%s "
                    "snapshot_priority=%s "
                    "subsegments=%s",
                    has_commercial_runtime,
                    has_operational_runtime,
                    has_medical_runtime,
                    has_behavior_components,
                    has_snapshot_priority,
                    len(subsegments_v1),
                )

            except Exception:
                pass

            s = _safe_json_dumps_with_limit(payload, snapshot_limit)
            try:
                parsed_ok = False
                try:
                    obj_test = json.loads(s)
                    parsed_ok = isinstance(obj_test, dict)
                except Exception:
                    parsed_ok = False

                _ap_log = (payload or {}).get("answer_playbook_v1") or {}
                logging.info(
                    "[WA_BOT][KB_SNAPSHOT][SOURCE_PROBE_BUILD_3DC26CB] topic=%s chars=%s limit=%s valid_json=%s has_value_packs=%s has_segment_value_map=%s has_segments=%s has_subsegments=%s has_archetypes=%s n_value_packs=%s n_segments=%s n_subsegments=%s n_archetypes=%s",
                    str(topic or "").strip().upper(),
                    len(s or ""),
                    snapshot_limit,
                    parsed_ok,
                    bool((payload or {}).get("value_packs_v1")),
                    bool((_ap_log or {}).get("segment_value_map_v1")) if isinstance(_ap_log, dict) else False,
                    bool((payload or {}).get("kb_segments_v1")),
                    bool((payload or {}).get("kb_subsegments_v1")),
                    bool((payload or {}).get("kb_archetypes_v1")),
                    len((payload or {}).get("value_packs_v1") or {}),
                    len((payload or {}).get("kb_segments_v1") or {}),
                    len((payload or {}).get("kb_subsegments_v1") or {}),
                    len((payload or {}).get("kb_archetypes_v1") or {}),
                )
            except Exception:
                pass

            return s
    except Exception:
        pass

    def _pick_dict(d: Any, keys: list[str], max_lines: int = 24) -> str:
        """Extrai poucos campos (compacto) de um dict do Firestore, sem dump gigante."""
        if not isinstance(d, dict):
            return ""
        lines = []
        for k in keys:
            v = d.get(k)
            if v is None:
                continue
            if isinstance(v, list):
                picked = []
                for it in v[:6]:
                    s = _safe_str(it)
                    if s:
                        picked.append(s)
                if picked:
                    lines.append(f"- {k}: " + " | ".join(picked))
            else:
                s = _safe_str(v)
                if s:
                    lines.append(f"- {k}: {s}")
            if len(lines) >= max_lines:
                break
        return "\n".join(lines).strip()

    # Blocos “verdade do produto” e “playbook” — compactos (não estourar teto)
    truth_block = ""
    try:
        truth = kb.get("product_truth_v1")
        truth_txt = _pick_dict(
            truth,
            ["one_liner", "core_rule", "does_well", "limits", "fit_question"],
            max_lines=18,
        )
        if truth_txt:
            truth_block = "[VERDADE DO PRODUTO]\n" + truth_txt
    except Exception:
        truth_block = ""

    playbook_block = ""
    try:
        pb = kb.get("answer_playbook_v1")
        pb_txt = _pick_dict(pb, ["pattern"], max_lines=10)
        ms = pb.get("micro_scenes") if isinstance(pb, dict) else None
        ms_txt = _pick_dict(
            ms,
            ["food_example", "health_example", "tech_support_example"],
            max_lines=10,
        )
        joined = "\n".join([t for t in [pb_txt, ms_txt] if t]).strip()
        if joined:
            playbook_block = "[PLAYBOOK DE RESPOSTA]\n" + joined
    except Exception:
        playbook_block = ""

    # KIT_BASE (sempre)
    kit_blocks = []
    for key, title in (
        ("tone_rules", "TOM (tone_rules)"),
        ("behavior_rules", "REGRAS DE VENDEDOR (behavior_rules)"),
        ("brand_guardrails", "GUARDRAILS (brand_guardrails)"),
        ("product_pitch", "PITCH OFICIAL (product_pitch)"),
        ("closing_guidance", "FECHAMENTO (closing_guidance)"),
        ("operational_capabilities", "CAPACIDADES (operational_capabilities)"),
    ):
        txt = _safe_str(kb.get(key))
        if txt:
            kit_blocks.append(f"[{title}]\n{txt}".strip())


    # tone_spark (openers/closers) — opcional, mas útil para "vida" controlada
    try:
        ts = kb.get("tone_spark") or {}
        if isinstance(ts, dict):
            op = _safe_str(ts.get("openers"))
            cl = _safe_str(ts.get("closers"))
            if op:
                kit_blocks.append(f"[SPARK OPENERS]\n{op}".strip())
            if cl:
                kit_blocks.append(f"[SPARK CLOSERS]\n{cl}".strip())
    except Exception:
        pass

    kit_base = "\n\n".join([b for b in kit_blocks if b]).strip()

    # BLOCO DO TÓPICO
    topic = (topic or "OTHER").strip().upper()
    topic_block = ""
    try:
        via = kb.get("value_in_action_blocks") or {}
        if topic == "AGENDA":
            ttxt = _safe_str(via.get("scheduling_scene"))
            if ttxt:
                topic_block = f"[AGENDA]\n{ttxt}".strip()
        elif topic == "ORCAMENTO":
            ttxt = _safe_str(via.get("services_quote_scene"))
            if ttxt:
                topic_block = f"[ORÇAMENTO]\n{ttxt}".strip()
        elif topic == "PRECO":
            # pricing pode ser objeto grande — tentamos extrair só “resumo”
            ptxt = _safe_str(pr.get("summary") or pr.get("text") or pr.get("public_summary") or pr.get("plans"))
            if not ptxt:
                ptxt = _safe_str(kb.get("pricing") or kb.get("pricing_summary"))
            if ptxt:
                topic_block = f"[PREÇOS]\n{ptxt}".strip()
        elif topic == "VOZ":
            vtxt = _safe_str(kb.get("voice_pill") or kb.get("voice") or kb.get("voice_rules"))
            if vtxt:
                topic_block = f"[VOZ]\n{vtxt}".strip()
        elif topic in ("SALES", "VALUE_SALES", "MONEY", "SOCIAL", "OTHER"):
            # Quando cair em OTHER/SOCIAL (muito comum em “ganhar dinheiro”),
            # ainda assim damos um bloco de VALOR EM VENDAS pra evitar resposta genérica.
            sv = via.get("sales_value_scene") or {}
            ttxt = ""
            if isinstance(sv, dict):
                ttxt = _safe_str(sv.get("scene_text") or sv.get("sales_value_scene_text") or sv.get("text") or "")
            if not ttxt:
                # fallback: alguns docs guardam o texto direto
                ttxt = _safe_str(via.get("sales_value_scene_text") or "")
            if ttxt:
                topic_block = f"[VALOR EM VENDAS]\n{ttxt}".strip()
        else:
            topic_block = ""  # sem extra
    except Exception:
        topic_block = ""

    # FEATURE CATALOG (opcional, filtrado por tópico)
    feat_block = ""
    try:
        feats = kb.get("feature_catalog") or kb.get("features") or []
        if isinstance(feats, list) and feats:
            # filtro por tags simples
            tkey = topic.lower()
            picked = []
            for f in feats[:120]:
                if not isinstance(f, dict):
                    continue
                fid = _safe_str(f.get("id") or f.get("key") or "")
                desc = _safe_str(f.get("desc") or f.get("description") or "")
                tags = f.get("tags") or f.get("topics") or []
                tags_lc = [str(x).lower() for x in tags] if isinstance(tags, list) else [str(tags).lower()]
                if topic in ("SOCIAL","OTHER"):
                    # social/other: não entope; só 2 itens “gerais”
                    if "core" in tags_lc or "geral" in tags_lc or "general" in tags_lc:
                        picked.append((fid, desc))
                else:
                    if tkey in tags_lc or topic.lower() in tags_lc:
                        picked.append((fid, desc))
                if len(picked) >= 6:
                    break
            if picked:
                lines = []
                for fid, desc in picked:
                    if fid and desc:
                        lines.append(f"- {fid}: {desc}")
                    elif fid:
                        lines.append(f"- {fid}")
                    elif desc:
                        lines.append(f"- {desc}")
                feat_block = "[FEATURES]\n" + "\n".join(lines)
    except Exception:
        feat_block = ""

    # Montagem com prioridade + corte
    # IMPORTANTE: tópico primeiro para não ser truncado quando o KIT_BASE encosta no teto.
    parts = []
    if topic_block:
        parts.append(topic_block)
    if truth_block:
        parts.append(truth_block)
    if playbook_block:
        parts.append(playbook_block)
    if kit_base:
        parts.append(kit_base)
    if feat_block:
        parts.append(feat_block)

    snapshot = ("\n\n".join([p for p in parts if p]).strip()) if parts else ""
    if not snapshot:
        return ""

    # Corte rígido final
    return snapshot[:FRONT_KB_MAX_CHARS]

# ==========================================================
# ✅ PATCH ÚNICO: substituir completamente reply_to_text(...)
# ==========================================================


def _front_smart_cut_for_audio(text: str, max_chars: int = 460) -> str:
    """
    Encurta fala para TTS sem cortar palavra/frase no meio.
    Regra técnica de canal/custo; não cria frase comercial.
    """
    try:
        s = " ".join(str(text or "").split()).strip()
        if not s or len(s) <= max_chars:
            return s

        soft = s[:max_chars].rstrip()

        # Preferência: encerrar em pontuação natural próxima do limite.
        floor = max(0, int(max_chars * 0.62))
        best = -1
        for mark in (".", "!", "?"):
            pos = soft.rfind(mark)
            if pos >= floor:
                best = max(best, pos)

        if best >= floor:
            return soft[: best + 1].strip()

        # Fallback: corta no último espaço, nunca no meio da palavra.
        sp = soft.rfind(" ")
        if sp >= floor:
            return soft[:sp].rstrip(" ,;:-") + "."

        return soft.rstrip(" ,;:-") + "."
    except Exception:
        return str(text or "").strip()


def _prepare_worker_tts_text(out: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Para inbound de áudio, entrega ao worker um texto falável já limpo.
    Mantém replyText intacto para auditoria/texto; ajusta spokenText/ttsText.
    """
    try:
        out = dict(out or {})
        ctx = ctx or {}
        msg_type = str(ctx.get("msg_type") or "").strip().lower()
        if msg_type not in ("audio", "voice", "ptt"):
            return out

        if _is_sales_text_only_closure(out):
            return out

        source = str(
            out.get("spokenText")
            or out.get("ttsText")
            or out.get("replyText")
            or ""
        ).strip()
        if not source:
            return out

        clipped = _front_smart_cut_for_audio(source, 460)
        out["spokenText"] = clipped
        out["ttsText"] = clipped

        dbg = out.get("decisionDebug") or {}
        if isinstance(dbg, dict):
            dbg["worker_tts_text_prepared"] = True
            dbg["worker_tts_text_len"] = len(clipped)
            out["decisionDebug"] = dbg

        return out
    except Exception:
        return dict(out or {})

def reply_to_text(uid: str, text: str, ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Retorna um dict com replyText (texto a ser enviado).
    - uid vazio -> handler de vendas (lead)
    - uid presente -> delega ao wa_bot_legacy.process_change capturando o texto gerado
    """
    ctx = ctx or {}
    try:
        if not (uid or "").strip():
            _wa_mem_key = (
                ctx.get("waKey")
                or ctx.get("wa_key")
                or ctx.get("from_e164")
                or ctx.get("wa_id")
                or ""
            )
            lead_memory = _load_institutional_lead_memory(str(_wa_mem_key or ""))
            if lead_memory:
                for _k, _v in lead_memory.items():
                    if _v and not ctx.get(_k):
                        ctx[_k] = _v
    except Exception:
        pass

    try:
        ai_turns = int((ctx or {}).get("ai_turns") or 0)
    except Exception:
        ai_turns = 0
    from_e164 = (ctx.get("from_e164") or "").strip()
    uid = (uid or "").strip()
    text = text or ""
    # Identidade do remetente para sessão do legacy: prefira wa_id (somente dígitos).
    sender_id = "".join(ch for ch in ((ctx.get("wa_id") or ctx.get("from_id") or from_e164 or "")) if ch.isdigit())

    def _force_audio_reply_if_needed(out: Dict[str, Any], reply_text: str) -> None:
        """
        Regra de produto: inbound em áudio => responder em áudio (best-effort).
        - Se já existe audioUrl, não mexe.
        - Tenta voz do MEI (uid) via /api/voz/tts (se voiceId existir).
        - Fallback: TTS institucional (gera signed URL).
        """
        # 🔴 REGRA SOBERANA: fechamento comercial nunca vira áudio
        if _is_sales_text_only_closure(out):
            return

        msg_type = (ctx.get("msg_type") or "").strip().lower()
        if msg_type not in ("audio", "voice", "ptt"):
            return

        # Se já tem áudio, OK.
        existing = (out.get("audioUrl") or "").strip()
        if existing:
            return

        # Sem texto final -> nada pra falar.
        t = (reply_text or "").strip()
        if not t:
            return

        # 1) Tenta voz do MEI (quando uid existe e há voiceId)
        try:
            voice_id = ""
            if uid:
                try:
                    from firebase_admin import firestore  # type: ignore
                    db = firestore.client()
                    snap = db.collection("profissionais").document(uid).get()
                    data = snap.to_dict() or {}
                    voz = data.get("vozClonada") or {}
                    voice_id = (voz.get("voiceId") or "").strip()
                except Exception:
                    voice_id = ""

            if voice_id:
                try:
                    import requests  # local import (não quebra se faltar)
                    base = (os.environ.get("BACKEND_BASE_URL") or os.environ.get("BACKEND_BASE") or "").strip().rstrip("/")
                    if not base:
                        base = (os.environ.get("RENDER_EXTERNAL_URL") or "").strip().rstrip("/")
                    if not base:
                        try:
                            from flask import request  # type: ignore
                            base = (request.host_url or "").strip().rstrip("/")
                        except Exception:
                            base = ""

                    if base:
                        r = requests.post(
                            f"{base}/api/voz/tts",
                            json={"text": t, "voice_id": voice_id, "reason": "inbound_audio"},
                            timeout=25,
                        )
                        if r.status_code == 200:
                            j = r.json() or {}
                            url = (j.get("audioUrl") or j.get("url") or "").strip()
                            if url:
                                out["audioUrl"] = url
                                out.setdefault("audioDebug", {})
                                out["audioDebug"].update({"ok": True, "mode": "mei"})
                                return
                except Exception:
                    # cai pro institucional
                    pass
        except Exception:
            pass

        # 2) Fallback: voz institucional (não deixa o lead no vácuo)
        try:
            from services.institutional_tts_media import generate_institutional_audio_url
            url = (generate_institutional_audio_url(text=t) or "").strip()
            out.setdefault("audioDebug", {})
            if url:
                out["audioUrl"] = url
                out["audioDebug"].update({"ok": True, "mode": "institutional"})
            else:
                out["audioDebug"].update({"ok": False, "mode": "institutional", "err": "empty_audio_url"})
        except Exception as e:
            out.setdefault("audioDebug", {})
            out["audioDebug"].update({"ok": False, "mode": "institutional", "err": (str(e) or "exception")[:180]})


    # ✅ Guard-rail final: no máximo 1 pergunta no replyText/spokenText
    def _final_cut_one_q(out: Dict[str, Any]) -> None:
        try:
            def _cut_one_q(s: str) -> str:
                s = (s or "").strip()
                if s.count("?") <= 1:
                    return s
                p = s.find("?")
                return (s[: p + 1]).strip()
            if isinstance(out, dict):
                if "replyText" in out:
                    out["replyText"] = _cut_one_q(str(out.get("replyText") or ""))
                if "spokenText" in out:
                    out["spokenText"] = _cut_one_q(str(out.get("spokenText") or ""))
        except Exception:
            pass


    # 1) LEAD / VENDAS (uid ausente)
    if not uid:
        # ----------------------------------------------------------
        # 🎯 GATE ÚNICO — Conversational Front (até MAX_AI_TURNS)
        # ----------------------------------------------------------
        front_reason = ""
        front_err = ""
        front_attempted = False
        front_out = None
        try:
            if CONVERSATIONAL_FRONT:
                # leitura segura do contador
                # fail-safe: se não conseguir ler estado, assume 0 (ENTRA no front),
                # porque o hard cap é garantido pelo MAX_AI_TURNS + bump (best-effort).
                wa_key = (ctx.get("waKey") or ctx.get("wa_key") or ctx.get("from_e164") or "").strip()
                uid_owner = (ctx.get("uid_owner") or "").strip()
                try:
                    from services.speaker_state import get_speaker_state  # type: ignore
                    st = get_speaker_state(wa_key, uid_owner=(uid_owner or None)) if wa_key else {}
                    ai_turns = int(st.get("ai_turns") or ai_turns or 0)
                    if ctx is not None:
                        ctx["ai_turns"] = ai_turns
                except Exception:
                    pass

                try:
                    logging.info(
                        "[WA_BOT][FRONT_GATE] enabled=%s waKey=%s ai_turns=%s max=%s",
                        bool(CONVERSATIONAL_FRONT),
                        (wa_key or "")[:32],
                        ai_turns,
                        MAX_AI_TURNS,
                    )
                except Exception:
                    pass

                free_mode = ai_turns < MAX_AI_TURNS
                if ai_turns >= MAX_AI_TURNS:
                    use_front = False
                else:
                    use_front = True

                # Gate do Conversational Front (Módulo 1): só roda em packs_v1 e enquanto não forçado ao operacional
                front_kb_sources = None
                front_mode = "packs_v1"  # normalizado (lower/strip) mais abaixo
                front_mode_raw = "packs_v1"
                force_operational = False
                try:
                    from services.speaker_state import is_force_operational
                    force_operational = bool(is_force_operational(wa_key, uid_owner=(uid_owner or None)))
                except Exception:
                    force_operational = False
                try:
                    front_kb_sources = _fetch_front_kb_sources()
                    _kb0 = (front_kb_sources.get("kb") or {}) if isinstance(front_kb_sources, dict) else {}
                    _pb0 = (_kb0.get("answer_playbook_v1") or {}) if isinstance(_kb0, dict) else {}
                    _rs0 = (_pb0.get("runtime_selector_v1") or {}) if isinstance(_pb0, dict) else {}
                    front_mode_raw = str((_rs0.get("mode") or "packs_v1"))
                    front_mode = front_mode_raw.strip().lower()
                except Exception:
                    front_kb_sources = None
                    front_mode_raw = "packs_v1"
                    front_mode = "packs_v1"

                
                # ✅ Log do gate com os 3 valores que decidem o turno 2+
                try:
                    logging.info(
                        "[WA_BOT][FRONT_GATE_DECISION] waKey=%s ai_turns=%s max=%s force_operational=%s front_mode=%s",
                        (wa_key or "")[:32],
                        ai_turns,
                        MAX_AI_TURNS,
                        bool(force_operational),
                        (front_mode or "")[:32],
                    )
                except Exception:
                    pass

                front_turns_allowed = bool(free_mode)

                if use_front and free_mode and front_turns_allowed and (not force_operational) and front_mode == "packs_v1":
                    try:
                        front_attempted = True
                        from services.conversational_front import handle as _front_handle  # type: ignore

                        # Monta KB Snapshot compacto (Firestore->wa_bot) com teto.
                        topic_hint = _front_topic_hint(text or "")
                        kb_snapshot = _build_front_kb_snapshot(topic_hint, text or "")

                        _segment_for_name_guard = (
                            ctx.get("segment_hint")
                            or ctx.get("leadSegmentRaw")
                            or ctx.get("segment")
                            or ""
                        )

                        _safe_name_hint = _sanitize_state_name_candidate(
                            (
                                ctx.get("name_hint")
                                or ctx.get("displayName")
                                or ctx.get("leadName")
                                or ""
                            ),
                            segment_hint=_segment_for_name_guard,
                        )

                        state_summary = {
                            "ai_turns": ai_turns,
                            "is_lead": True,
                            "name_hint": _safe_name_hint,
                            "segment_hint": ctx.get("segment_hint") or "",
                            "msg_type": ctx.get("msg_type") or "",
                            "entry_type": ctx.get("msg_type") or "",
                            "topic_hint": topic_hint,
                            "kb_topic": topic_hint,
                            # Micro-contexto (best-effort). Se não vier, segue vazio.
                            "last_intent": ctx.get("last_intent") or ctx.get("lastIntent") or "",
                            "last_user_goal": ctx.get("last_user_goal") or ctx.get("lastUserGoal") or "",
                            # ---------------------------------------------------
                            # Memória conversacional persistida (best-effort)
                            #
                            # Apenas repassa ao front informações já carregadas
                            # do Firestore, sem criar regras de decisão no código.
                            # A IA continua soberana; o código apenas fornece
                            # contexto estrutural adicional.
                            # ---------------------------------------------------
                            "lead_memory_summary": (
                                ctx.get("lead_memory_summary")
                                or ctx.get("summary")
                                or ""
                            ),
                            "lead_memory_turns": (
                                ctx.get("lead_memory_turns")
                                or ctx.get("turns")
                                or 0
                            ),
                            "last_topic": (
                                ctx.get("last_topic")
                                or ctx.get("lastTopic")
                                or ""
                            ),
                            "last_next_step": (
                                ctx.get("last_next_step")
                                or ctx.get("lastNextStep")
                                or ""
                            ),
                        }

                        try:
                            logging.info(
                                "[WA_BOT][FRONT_CALL] topic_hint=%s state_summary_has_topic=%s",
                                str(topic_hint or "").strip().upper(),
                                bool(state_summary.get("topic_hint")),
                            )
                        except Exception:
                            pass

                        # Compat: se o front aceitar kb_snapshot como arg, usamos.
                        # Se não aceitar (TypeError), injeta no state_summary.
                        try:
                            front_out = _front_handle(
                                user_text=text or "",
                                state_summary=state_summary,
                                kb_snapshot=kb_snapshot,
                            ) or {}
                        except TypeError:
                            state_summary["kb_snapshot"] = kb_snapshot
                            front_out = _front_handle(
                                user_text=text or "",
                                state_summary=state_summary,
                            ) or {}

                        try:
                            ai_turns += 1
                            if ctx is not None:
                                ctx["ai_turns"] = ai_turns
                        except Exception:
                            pass

                        # ✅ packs_v1: render determinístico só entra como RESCUE, não como atropelo da IA
                        try:
                            dec = (front_out.get("decider") or {}) if isinstance(front_out, dict) else {}
                            current_reply = str((front_out.get("replyText") or "") if isinstance(front_out, dict) else "").strip()
                            current_source = str((front_out.get("replySource") or "") if isinstance(front_out, dict) else "").strip().lower()

                            contract = (
                                (front_out.get("operationalContract") or {})
                                if isinstance(front_out, dict)
                                else {}
                            )

                            front_reply_is_valid = bool(
                                current_reply
                                and current_source in (
                                    "front_structured_python_assembly",
                                    "front_ia_soberana",
                                    "front",
                                )
                                and isinstance(contract, dict)
                                and (
                                    contract.get("hydrated_from_platform_kb")
                                    or contract.get("hydrated_from_docs")
                                    or contract.get("kbRequiredOk")
                                    or contract.get("kb_required_ok")
                                    or contract.get("global_pack_fallback")
                                    or (
                                        str(contract.get("response_mode") or "").strip().upper() == "SCENE"
                                        and bool(contract.get("has_practical_scene"))
                                    )
                                )
                            )

                            try:
                                logging.info(
                                    "[WA_BOT][FRONT_REPLY_IN] "
                                    "len=%s source=%s valid=%s mode=%s platform_kb=%s",
                                    len(current_reply or ""),
                                    current_source,
                                    bool(front_reply_is_valid),
                                    str(contract.get("response_mode") or ""),
                                    bool(
                                        isinstance(contract, dict)
                                        and (
                                            contract.get("hydrated_from_platform_kb")
                                            or contract.get("global_pack_fallback")
                                        )
                                    ),
                                )
                            except Exception:
                                pass

                            should_rescue_with_pack = bool(
                                dec
                                and not front_reply_is_valid
                                and (
                                    (not current_reply)
                                    or current_source in ("pack_engine_fallback_default", "front_fallback_structural", "fallback")
                                )
                            )

                            if should_rescue_with_pack:
                                kb = ((front_kb_sources or {}).get("kb") or {}) if isinstance(front_kb_sources, dict) else {}
                                if not kb:
                                    kb = (_fetch_front_kb_sources().get("kb") or {})
                                rend = _render_pack_reply(dec, kb)
                                if rend.get("ok"):
                                    front_out = _prefer_structured_front_reply(front_out, rend)
                        except Exception:
                            pass

                        # ✅ transição: só faz sentido para CUSTOMER FINAL (quando existe uid_owner).
                        # Para LEAD (uid_owner vazio), NÃO deve pular o Módulo 1, senão derruba a conversa pro fallback cedo.
                        try:
                            dec = (front_out.get("decider") or {}) if isinstance(front_out, dict) else {}
                            _intent = str(dec.get("intent") or "").strip().upper()
                            _conf = str(dec.get("confidence") or "").strip().lower()
                            operational_intents = {"SCHEDULE","BOOK","AGENDA","AGENDAR","ORDERS","ORDER","PEDIDO","PEDIDOS","STATUS","PROCESS","ACTIVATE"}
                            # ✅ LEAD (uid_owner vazio) NÃO pode ligar force_operational.
                            # Só permitimos isso quando houver uid_owner (cliente final / operacional).
                            if (uid_owner or "").strip() and _intent in operational_intents and _conf in ("high", "medium"):
                                from services.speaker_state import set_force_operational
                                set_force_operational(
                                    wa_key,
                                    True,
                                    reason=f"intent={_intent} conf={_conf}",
                                    uid_owner=(uid_owner or None),
                                )
                        except Exception:
                            pass


                        # saída compatível com o worker
                        und = front_out.get("understanding") or {}

                        # ---------------------------------------------------
                        # Blindagem estrutural de identidade na saída do front
                        #
                        # O estado/contexto já é sanitizado antes de chamar o
                        # front, mas aqui impedimos que qualquer leadName cru
                        # vindo de front_out seja repassado ao worker, ao TTS
                        # ou à persistência.
                        #
                        # Não usa lista de profissões/segmentos.
                        # Não altera prompt.
                        # Não chama IA adicional.
                        # ---------------------------------------------------
                        try:
                            _front_segment_for_name_guard = (
                                front_out.get("segmentHint")
                                or front_out.get("leadSegmentRaw")
                                or (und.get("segmentHint") if isinstance(und, dict) else "")
                                or (und.get("leadSegmentRaw") if isinstance(und, dict) else "")
                                or ctx.get("segment_hint")
                                or ctx.get("leadSegmentRaw")
                                or ctx.get("segment")
                                or ""
                            )
                            _safe_front_lead_name = _sanitize_state_name_candidate(
                                (
                                    front_out.get("leadName")
                                    or front_out.get("displayName")
                                    or front_out.get("nameToSay")
                                    or (und.get("leadName") if isinstance(und, dict) else "")
                                    or (und.get("lead_name") if isinstance(und, dict) else "")
                                    or ""
                                ),
                                segment_hint=_front_segment_for_name_guard,
                            )
                        except Exception:
                            _safe_front_lead_name = ""

                        # espelha nextStep/shouldEnd dentro de understanding também (tolerante)
                        try:
                            if isinstance(und, dict):
                                und.setdefault("nextStep", front_out.get("nextStep") or front_out.get("next_step") or front_out.get("planNextStep") or "NONE")
                                und.setdefault("shouldEnd", bool(front_out.get("shouldEnd")))
                                und.setdefault("topicHint", topic_hint)
                        except Exception:
                            pass

                        out = {
                            "ok": True,
                            "route": "conversational_front",
                            "replyText": str(front_out.get("replyText") or "").strip(),
                            "spokenText": str(front_out.get("spokenText") or front_out.get("spoken_text") or "").strip(),
                            "understanding": und,
                            "leadName": _safe_front_lead_name,
                            "segmentHint": str(front_out.get("segmentHint") or "").strip(),
                            "planNextStep": front_out.get("nextStep") or "NONE",
                            "nameUse": front_out.get("nameUse") or "none",
                            # Telemetria leve (ignorada se o worker não usar)
                            "kbSnapshotSizeChars": len(kb_snapshot or ""),
                            # Auditoria: mata a dúvida "quem respondeu?"
                            "replySource": str(front_out.get("replySource") or "front"),
                            # Custo (best-effort) vindo do front
                            "tokenUsage": front_out.get("tokenUsage") or {},
                            # Produto: o worker é o dono do áudio. Se entrou por áudio, ele decide falar.
                            # Default seguro aqui: NÃO forçar texto.
                            "prefersText": bool(front_out.get("prefersText", False)),
                            "ttsOwner": "worker",
                        }

                        try:
                            if _safe_front_lead_name:
                                out["displayName"] = _safe_front_lead_name
                                out["name_hint"] = _safe_front_lead_name
                                if isinstance(front_out, dict):
                                    front_out["leadName"] = _safe_front_lead_name
                                    front_out["displayName"] = _safe_front_lead_name
                                    front_out["name_hint"] = _safe_front_lead_name
                            elif isinstance(front_out, dict):
                                front_out.pop("leadName", None)
                                front_out.pop("displayName", None)
                                front_out.pop("name_hint", None)
                        except Exception:
                            pass

                        # Blindagem final:
                        # Garante que o payload retornado pelo wa_bot utilize exatamente os
                        # textos já limpos extraídos do front, impedindo que qualquer envelope
                        # JSON bruto previamente presente em front_out seja persistido ou enviado.
                        try:
                            if isinstance(front_out, dict):
                                reply_text = str(out.get("replyText") or "").strip()
                                spoken_text = str(out.get("spokenText") or reply_text or "").strip()
                                front_out["replyText"] = str(reply_text or "").strip()
                                front_out["spokenText"] = str(spoken_text or reply_text or "").strip()
                                out["replyText"] = str(reply_text or "").strip()
                                out["spokenText"] = str(spoken_text or reply_text or "").strip()
                        except Exception:
                            pass

                        try:
                            logging.info(
                                "[WA_BOT][FRONT_OUT_BUILT] "
                                "reply_len=%s spoken_len=%s source=%s",
                                len(str(out.get("replyText") or "")),
                                len(str(out.get("spokenText") or "")),
                                str(out.get("replySource") or ""),
                            )
                        except Exception:
                            pass

                        # ✅ Regra de canal (sem alterar linguagem)
                        # Preserva a superfície do front antes da closure.
                        # Se o SEND_LINK for rebaixado por não haver pedido explícito de link,
                        # a resposta comercial original não pode continuar substituída por frase fixa.
                        try:
                            _pre_closure_reply = str(out.get("replyText") or "").strip()
                            _pre_closure_spoken = str(out.get("spokenText") or "").strip()
                            _pre_closure_prefers_text = bool(out.get("prefersText"))
                            _pre_closure_intent_final = str(out.get("intentFinal") or "").strip()
                        except Exception:
                            _pre_closure_reply = ""
                            _pre_closure_spoken = ""
                            _pre_closure_prefers_text = False
                            _pre_closure_intent_final = ""

                        out = _apply_sales_text_only_closure(out, ctx)

                        # ✅ Produto: SEND_LINK = venda fechada (link-only, sem pergunta)
                        # Guard-rail: NÃO mandar link cedo se o usuário não pediu link/site.
                        try:
                            if str(out.get("planNextStep") or "").strip().upper() == "SEND_LINK":
                                _wants_link = _looks_like_link_request(text or "")
                                if _wants_link:
                                    _url = "https://www.meirobo.com.br"
                                    _rt0 = (out.get("replyText") or "").strip()
                                    if ("http://" not in _rt0) and ("https://" not in _rt0):
                                        out["replyText"] = f"Perfeito. Aqui está o link pra assinar agora:\n{_url}"
                                    else:
                                        # se já tem link, garante que não termina com pergunta
                                        qpos = _rt0.find("?")
                                        if qpos != -1:
                                            out["replyText"] = (_rt0[: qpos]).rstrip()
                                    # ÁUDIO (humanizado): o front pode ter montado spokenText (com nome).
                                    # Se não vier, usamos um fallback curto (sem falar URL).
                                    out["spokenText"] = (out.get("spokenText") or (
                                        "Fechado. Te enviei o link no texto agora pra você copiar e assinar."
                                    )).strip()
                                else:
                                    # Downgrade seguro: mantém a resposta do front e não força link-only.
                                    out["planNextStep"] = "NONE"
                                    if str(out.get("textOnlyReason") or "").strip() == "sales_closure_send_link":
                                        if _pre_closure_reply:
                                            out["replyText"] = _pre_closure_reply
                                        if _pre_closure_spoken:
                                            out["spokenText"] = _pre_closure_spoken
                                        else:
                                            out["spokenText"] = out.get("replyText") or ""
                                        out["prefersText"] = _pre_closure_prefers_text
                                        out.pop("textOnlyReason", None)
                                        if _pre_closure_intent_final:
                                            out["intentFinal"] = _pre_closure_intent_final
                                        elif str(out.get("intentFinal") or "").strip().upper() == "ATIVAR":
                                            out.pop("intentFinal", None)
                        except Exception:
                            pass

                        # 🔧 Polimento vendedor (mínimo): evita CTA "como configurar/cadastrar" no modo VENDAS.
                        # O front pode evoluir isso, mas aqui garantimos que não escapa um "suporte disfarçado".
                        try:
                            import re
                            _rt = (out.get("replyText") or "").strip()
                            _topic = str((und or {}).get("topicHint") or (und or {}).get("topic") or topic_hint or "").strip().upper()

                            # ✅ Produto: se já é SEND_LINK, não adiciona pergunta/CTA nenhuma
                            if str(out.get("planNextStep") or "").strip().upper() == "SEND_LINK":
                                raise Exception("skip_polish_for_send_link")

                            # remove CTA de "como configurar/cadastrar" no final
                            _rt = re.sub(
                                r"(\s*Você\s+gostaria\s+de\s+saber\s+(mais\s+)?sobre\s+como\s+(configurar|cadastrar)\s+[^\?]*\??\s*)$",
                                "",
                                _rt,
                                flags=re.IGNORECASE,
                            ).strip()

                            # se sobrou pergunta técnica "como cadastrar/configurar", troca por pergunta de objetivo
                            if re.search(r"\bcomo\s+(configurar|cadastrar)\b", _rt, re.IGNORECASE):
                                _rt = re.sub(r"\s*\bcomo\s+(configurar|cadastrar)\b[^\?]*\??\s*$", "", _rt, flags=re.IGNORECASE).strip()

                            # 🛑 Regra: no máximo 1 pergunta.
                            # Importante: "no máximo 1" NÃO significa "sempre perguntar".
                            # O Módulo 1 (front) é quem decide se deve haver pergunta.
                            # Aqui só garantimos higiene: sem pergunta técnica e sem duplicar "?".
                            if (_rt or "").count("?") > 1:
                                qpos = _rt.find("?")
                                if qpos != -1:
                                    _rt = (_rt[: qpos + 1]).strip()

                            if _rt:
                                out["replyText"] = _rt
                        except Exception:
                            pass

                        # Guard final de acabamento: atua apenas no texto já pronto,
                        # depois do front e do polimento, antes de persistir/enviar.
                        # Não decide intenção, não consulta KB, não altera prompt.
                        out = _apply_final_reply_tail_guard(out)

                        try:
                            logging.info(
                                "[WA_BOT][FRONT_AFTER_POLISH] "
                                "reply_len=%s source=%s plan=%s",
                                len(str(out.get("replyText") or "")),
                                str(out.get("replySource") or ""),
                                str(out.get("planNextStep") or ""),
                            )
                        except Exception:
                            pass

                                                # Fallback de segurança: se o front vier vazio (JSON incompleto / bug raro),
                        # tenta um pack institucional padrão pra nunca ficar mudo.
                        if not str(out.get("replyText") or "").strip():
                            try:
                                _kb_fb = ((front_kb_sources or {}).get("kb") or {}) if isinstance(front_kb_sources, dict) else {}
                                if not _kb_fb:
                                    _kb_fb = (_fetch_front_kb_sources().get("kb") or {})
                                _rend_fb = _render_pack_reply({"packId": "PACK_A_WHAT_IS", "renderMode": "short"}, _kb_fb)
                                if _rend_fb.get("ok") and str(_rend_fb.get("replyText") or "").strip():
                                    out["replyText"] = str(_rend_fb.get("replyText") or "").strip()
                                    out["replySource"] = "pack_engine_fallback_default"
                            except Exception:
                                pass

# guard: texto vazio nunca passa nunca passa
                        if out["replyText"]:
                            # 🔒 FRONT respondeu => IA-first por definição.
                            # Mantém compat com o worker/outbox, mas SEM perder a telemetria
                            # rica já produzida pelo próprio front e/ou pelo operationalContract.
                            am = dict(front_out.get("aiMeta") or {})
                            contract = front_out.get("operationalContract") or {}

                            am.setdefault("ia_first", True)
                            am["iaSource"] = str(front_out.get("iaSource") or "front")
                            am["replySource"] = str(front_out.get("replySource") or "front")
                            am["route"] = "conversational_front"
                            am["fallbackReason"] = ""

                            if isinstance(contract, dict) and contract:
                                def _wa_norm_ai_meta_identity_v1(value: object) -> str:
                                    raw = str(value or "").strip().lower()
                                    raw = "".join(ch if (ch.isalnum() or ch.isspace()) else " " for ch in raw)
                                    return " ".join(raw.split())

                                def _wa_extract_turn_name_for_ai_meta_guard_v1() -> str:
                                    try:
                                        picked = _pick_lead_name(front_out, ctx)
                                        if str(picked or "").strip():
                                            return str(picked or "").strip()
                                    except Exception:
                                        pass

                                    try:
                                        txt = str(text or "").strip()
                                        m = re.search(
                                            r"(?i)\b(?:sou|me chamo|meu nome é|meu nome e)\s+(?:o\s+|a\s+)?([A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-zà-ÿ]{1,30})\b",
                                            txt,
                                        )
                                        if m:
                                            return str(m.group(1) or "").strip()
                                    except Exception:
                                        pass

                                    return ""

                                _ai_meta_lead_name_guard = _wa_extract_turn_name_for_ai_meta_guard_v1()

                                def _wa_drop_ai_meta_value_if_name_v1(value: object, field_name: str) -> str:
                                    v = str(value or "").strip()
                                    if (
                                        v
                                        and _ai_meta_lead_name_guard
                                        and _wa_norm_ai_meta_identity_v1(v) == _wa_norm_ai_meta_identity_v1(_ai_meta_lead_name_guard)
                                    ):
                                        try:
                                            logging.info(
                                                "[WA_AI_META_NAME_GUARD] dropped=True field=%s value=%s",
                                                field_name,
                                                v,
                                            )
                                        except Exception:
                                            pass
                                        return ""
                                    return v

                                _contract_segment_ai_meta = _wa_drop_ai_meta_value_if_name_v1(
                                    contract.get("segment"),
                                    "contract.segment",
                                )
                                _contract_id_ai_meta = _wa_drop_ai_meta_value_if_name_v1(
                                    contract.get("contract_id"),
                                    "contract.contract_id",
                                )
                                _contract_archetype_ai_meta = str(contract.get("archetype_id") or "").strip()

                                kb_used = bool(
                                    contract.get("hydrated_from_docs")
                                    or contract.get("has_example_line")
                                    or contract.get("has_practical_scene")
                                    or _contract_archetype_ai_meta
                                    or _contract_segment_ai_meta
                                )

                                am["kbUsed"] = kb_used
                                am["kbRequiredOk"] = bool(contract.get("hydrated_from_docs"))
                                am["kbExampleUsed"] = bool(contract.get("has_example_line"))
                                am["kbSceneUsed"] = bool(contract.get("has_practical_scene"))

                                am["kbDocPath"] = (
                                    _contract_segment_ai_meta
                                    or _contract_archetype_ai_meta
                                    or ""
                                )

                                am["kbContractId"] = str(
                                    _contract_id_ai_meta
                                    or _contract_archetype_ai_meta
                                    or _contract_segment_ai_meta
                                    or ""
                                )

                                if am["kbRequiredOk"]:
                                    am["kbMissReason"] = ""
                                    am["kbMissingFields"] = []
                                else:
                                    missing = []
                                    if not contract.get("hydrated_from_docs"):
                                        missing.append("hydrated_from_docs")
                                    if not (
                                        contract.get("has_example_line")
                                        or contract.get("has_practical_scene")
                                    ):
                                        missing.append("example_or_scene")
                                    am["kbMissReason"] = "kb_partial_or_missing"
                                    am["kbMissingFields"] = missing
                            else:
                                am.setdefault("kbUsed", False)
                                am.setdefault("kbRequiredOk", False)
                                am.setdefault("kbDocPath", "")
                                am.setdefault("kbContractId", "")
                                am.setdefault("kbExampleUsed", False)
                                am.setdefault("kbSceneUsed", False)
                                am.setdefault("kbMissReason", "missing_operational_contract")
                                am.setdefault("kbMissingFields", ["operationalContract"])

                            out["aiMeta"] = am
                            out = _apply_safe_ai_meta(out, ctx)
                            # -------------------------------------------------------
                            # Persistência do lead (best-effort)
                            # -------------------------------------------------------
                            #
                            # Além do nome e do resumo, persistimos também o segmento
                            # já identificado pela IA. Isso permite que interações
                            # futuras reutilizem diretamente o contexto do negócio,
                            # sem necessidade de redescoberta.
                            #
                            # A lógica abaixo apenas aproveita sinais já produzidos
                            # pelo pipeline; nenhuma regra baseada em palavras-chave
                            # é introduzida no código.
                            # -------------------------------------------------------
                            front_result = front_out
                            understanding_obj = {}
                            try:
                                understanding_obj = (
                                    front_result.get("understanding")
                                    if isinstance(front_result, dict)
                                    else {}
                                ) or {}
                            except Exception:
                                understanding_obj = {}

                            operational_contract_obj = (
                                front_result.get("operationalContract")
                                if isinstance(front_result.get("operationalContract"), dict)
                                else {}
                            )

                            def _wa_norm_identity_field_v1(value: object) -> str:
                                raw = str(value or "").strip().lower()
                                raw = "".join(ch if (ch.isalnum() or ch.isspace()) else " " for ch in raw)
                                return " ".join(raw.split())

                            def _wa_drop_segment_equal_name_v1(value: object, field_name: str) -> str:
                                v = str(value or "").strip()
                                n = str(_safe_front_lead_name or "").strip()
                                if (
                                    v
                                    and n
                                    and _wa_norm_identity_field_v1(v) == _wa_norm_identity_field_v1(n)
                                ):
                                    try:
                                        logging.info(
                                            "[WA_LEAD_MEMORY_FIELD_GUARD] dropped_segment_equal_name=True field=%s value=%s",
                                            field_name,
                                            v,
                                        )
                                    except Exception:
                                        pass
                                    return ""
                                return v

                            _segment_candidates = [
                                ("ctx.segment", ctx.get("segment")),
                                ("ctx.segment_hint", ctx.get("segment_hint")),
                                ("front.segment", front_result.get("segment")),
                                ("front.segmentHint", front_result.get("segmentHint")),
                                ("contract.segment", operational_contract_obj.get("segment")),
                                ("understanding.segmentHint", understanding_obj.get("segmentHint")),
                                ("understanding.leadSegmentRaw", understanding_obj.get("leadSegmentRaw")),
                            ]

                            segment_persisted = ""
                            for _field_name, _field_value in _segment_candidates:
                                _candidate = _wa_drop_segment_equal_name_v1(_field_value, _field_name)
                                if _candidate:
                                    segment_persisted = _candidate
                                    break

                            _segment_hint_candidates = [
                                ("ctx.segment_hint", ctx.get("segment_hint")),
                                ("front.segmentHint", front_result.get("segmentHint")),
                                ("contract.segment", operational_contract_obj.get("segment")),
                                ("understanding.segmentHint", understanding_obj.get("segmentHint")),
                            ]

                            segment_hint_persisted = ""
                            for _field_name, _field_value in _segment_hint_candidates:
                                _candidate = _wa_drop_segment_equal_name_v1(_field_value, _field_name)
                                if _candidate:
                                    segment_hint_persisted = _candidate
                                    break

                            _lead_segment_raw_candidates = [
                                ("front.leadSegmentRaw", front_result.get("leadSegmentRaw")),
                                ("understanding.leadSegmentRaw", understanding_obj.get("leadSegmentRaw")),
                            ]

                            lead_segment_raw_persisted = ""
                            for _field_name, _field_value in _lead_segment_raw_candidates:
                                _candidate = _wa_drop_segment_equal_name_v1(_field_value, _field_name)
                                if _candidate:
                                    lead_segment_raw_persisted = _candidate
                                    break

                            if segment_persisted:
                                ctx["segment"] = segment_persisted

                            if segment_hint_persisted:
                                ctx["segment_hint"] = segment_hint_persisted

                            if lead_segment_raw_persisted:
                                ctx["leadSegmentRaw"] = lead_segment_raw_persisted
                            try:
                                _save_institutional_lead_memory(wa_key, out, ctx)
                            except Exception:
                                pass
                            # incrementa contador SOMENTE se o front realmente respondeu
                            try:
                                from services.speaker_state import bump_ai_turns  # type: ignore
                                if wa_key:
                                    bump_ai_turns(wa_key, uid_owner=(uid_owner or None))
                            except Exception:
                                pass
                            try:
                                logging.info(
                                    "[WA_BOT][FRONT_OK] waKey=%s ai_turns=%s topic=%s kbChars=%s next=%s",
                                    (wa_key or "")[:32],
                                    ai_turns,
                                    str((und or {}).get("topic") or (und or {}).get("intent") or "")[:24],
                                    len(kb_snapshot or ""),
                                    str(out.get("planNextStep") or "NONE"),
                                )
                            except Exception:
                                pass
                            _final_cut_one_q(out)
                            out = _prepare_worker_tts_text(out, ctx)
                            return out
                        else:
                            front_reason = "front_empty_reply"
                    except Exception as e:
                        front_reason = "front_exception"
                        front_err = (str(e) or "exception")[:200]
                        try:
                            logging.exception(
                                "[WA_BOT][FRONT_EXCEPTION] waKey=%s ai_turns=%s topicHint=%s kbChars=%s err=%s",
                                (wa_key or "")[:32],
                                ai_turns,
                                (topic_hint or "")[:16],
                                len((kb_snapshot or "")),
                                front_err,
                            )
                        except Exception:
                            pass
                else:
                    # ✅ Nunca mais cair em FRONT_FALLBACK reason=unknown:
                    # registra por que o front NÃO rodou nesse turno.
                    try:
                        if not (wa_key or "").strip():
                            front_reason = "front_missing_wa_key"
                        elif int(ai_turns) >= int(MAX_AI_TURNS) and (not POST5_AI_ENABLED):
                            front_reason = "front_max_turns"
                        elif int(ai_turns) >= int(MAX_AI_TURNS) and POST5_AI_ENABLED:
                            front_reason = "front_post5_allowed_but_not_used"
                        elif bool(force_operational):
                            front_reason = "front_force_operational"
                        elif str(front_mode or "").strip().lower() != "packs_v1":
                            _raw = (front_mode_raw or "").strip()
                            if _raw:
                                front_reason = ("front_mode_mismatch:" + _raw[:24])
                            else:
                                front_reason = "front_mode_mismatch"
                        else:
                            front_reason = "front_gate_blocked"
                    except Exception:
                        front_reason = front_reason or "front_gate_blocked"


        except Exception:
            pass

        
        # log único para nunca mais ficar ambíguo
        try:
            if not front_reason:
                if not bool(CONVERSATIONAL_FRONT):
                    front_reason = "front_disabled"
                elif "ai_turns" in locals() and int(ai_turns) >= int(MAX_AI_TURNS) and (not POST5_AI_ENABLED):
                    front_reason = "front_max_turns"
                elif "ai_turns" in locals() and int(ai_turns) >= int(MAX_AI_TURNS) and POST5_AI_ENABLED:
                    front_reason = "front_post5_allowed_but_not_used"
                elif "force_operational" in locals() and bool(force_operational):
                    front_reason = "front_force_operational"
                elif "front_mode" in locals() and str(front_mode or "").strip().lower() != "packs_v1":
                    front_reason = "front_mode_mismatch"
                else:
                    front_reason = "unknown"
            logging.info(
                "[WA_BOT][FRONT_FALLBACK] reason=%s waKey=%s ai_turns=%s err=%s",
                (front_reason or "unknown"),
                (wa_key or "")[:32] if "wa_key" in locals() else "",
                ai_turns if "ai_turns" in locals() else "?",
                (front_err or "")[:120],
            )
        except Exception:
            pass


        # ----------------------------------------------------------
        # 🧭 Runtime mode (antes de sales_lead): pode forçar modo operacional
        # ----------------------------------------------------------
        try:
            detected_intent = str(
                (ctx.get("detected_intent") or ctx.get("detectedIntent") or ctx.get("intentFinal") or "") or
                (((ctx.get("understanding") or {}).get("intent") or "") if isinstance(ctx.get("understanding"), dict) else "") or
                (((front_out.get("understanding") or {}).get("intent") or "") if isinstance(front_out, dict) else "")
            ).strip().upper()

            confidence = (
                ctx.get("confidence")
                or ctx.get("intent_confidence")
                or (((ctx.get("understanding") or {}).get("confidence")) if isinstance(ctx.get("understanding"), dict) else None)
                or (((front_out.get("understanding") or {}).get("confidence")) if isinstance(front_out, dict) else None)
            )

            # runtime_mode resolvido localmente (packs_v1 + force_operational)
            mode = "sales"
            try:
                # ai_turns e intent/confidence já estão disponíveis aqui
                _turns = int(locals().get("ai_turns") or 0)
                _intent = str(detected_intent or "").strip().upper()
                _conf = str(confidence or "").strip().lower()
                operational_intents = {"SCHEDULE","BOOK","AGENDA","AGENDAR","ORDERS","ORDER","PEDIDO","PEDIDOS","STATUS","PROCESS","ACTIVATE"}
                # ✅ Canon: só CUSTOMER FINAL entra em operacional (uid_owner).
                # Nunca usar ctx["uid"] aqui (pode vazar/contaminar em LEAD).
                uid_oper = str(ctx.get("uid_owner") or "").strip()
                if uid_oper:
                    # Só cliente final (uid_owner) pode entrar em operacional.
                    if _turns >= 5:
                        mode = "operational"
                    elif _intent in operational_intents and _conf in ("high", "medium"):
                        mode = "operational"
            except Exception:
                mode = "sales"

            if mode == "operational":
                uid_oper = str(ctx.get("uid_owner") or "").strip()
                if uid_oper:
                    from services.bot_handlers import customer_final  # novo
                    ctx["force_operational"] = True
                    # força customer_final
                    return customer_final.generate_reply(uid_oper, text, ctx)  # type: ignore
        except Exception:
            pass

# ----------------------------------------------------------
        # ⬇️ Módulo B (atual): sales_lead (modo econômico)
        # ----------------------------------------------------------
        try:
            from services.bot_handlers import sales_lead
            reply_obj = sales_lead.generate_reply(text=text, ctx=ctx)
            # harmoniza retorno: string OU dict {replyText,...}
            lead_name = ""
            reply = ""
            if isinstance(reply_obj, dict):
                reply = str((reply_obj or {}).get("replyText") or "").strip()
                # tenta extrair nome se o handler tiver colocado
                lead_name = str((reply_obj or {}).get("name") or (reply_obj or {}).get("leadName") or "").strip()
            else:
                reply = str(reply_obj or "").strip()

            if not reply:
                _log_sales_lead_fallback(ctx, reason="empty_reply")
                reply = _sales_lead_neutral_fallback(lead_name)

            # ✅ Propaga o pacote completo do Sales (kbContext/kind/ttsOwner/etc)
            # e deixa o worker ser o DONO do áudio (evita duplicidade de TTS).
            out: Dict[str, Any] = {
                "ok": True,
                "route": "sales_lead",
                "replyText": reply,
                "replySource": "sales_lead",
                # 🔎 Telemetria do front (pra provar se tentou e por que caiu)
                "frontAttempted": bool(front_attempted),
                "frontReason": str(front_reason or "").strip(),
                "frontErr": str(front_err or "").strip(),
            }
            if isinstance(reply_obj, dict):
                # copia metadados úteis (sem sobrescrever replyText final já validado)
                for k in (
                    "kbContext","kind","ttsOwner","leadName","segment","goal","interest_level",
                    "prefersText","nameToSay","ttsText","spokenText","nameUse",
                    # IA-first / observabilidade (worker lê isso p/ ia_first + outbox)
                    "understanding","intentFinal","planNextStep","decisionDebug","policiesApplied",
                    "planIntent","planNextStepRaw","aiPlan","traceId",
                    # 🔎 Telemetria KB/contrato (não quebra nada se o worker ignorar)
                    "aiMeta",
                    "kbDocPath","kbContractId","kbSliceSizeChars","kbSliceFields",
                    "kbRequiredOk","kbMissReason","kbMissingFields","kbUsed","kbExampleUsed"
                ):
                    if k in reply_obj:
                        out[k] = reply_obj.get(k)

                # Compat: alguns caminhos do worker ainda leem planIntent/planNextStep.
                # sales_lead já entrega intentFinal/planNextStep; então garantimos aliases.
                try:
                    if not str(out.get("planIntent") or "").strip():
                        _if = str(out.get("intentFinal") or "").strip()
                        if _if:
                            out["planIntent"] = _if
                except Exception:
                    pass
                try:
                    if not str(out.get("planNextStep") or "").strip():
                        _ns = str(out.get("planNextStep") or out.get("plan_next_step") or "").strip()
                        if not _ns:
                            _ns = str(out.get("planNextStepRaw") or "").strip()
                        if not _ns:
                            _ns = str((out.get("understanding") or {}).get("next_step") or "").strip() if isinstance(out.get("understanding"), dict) else ""
                        if _ns:
                            out["planNextStep"] = _ns
                except Exception:
                    pass
                # garante nameToSay a partir de leadName (humanização no fechamento)
                try:
                    if not str(out.get("nameToSay") or "").strip():
                        ln = str(out.get("leadName") or "").strip()
                        if ln:
                            out["nameToSay"] = ln
                except Exception:
                    pass
                # normaliza ttsOwner padrão
                if not str(out.get("ttsOwner") or "").strip():
                    out["ttsOwner"] = "worker"
            else:
                out["ttsOwner"] = "worker"

            # ✅ Bugfix: se o Módulo 2 decidiu SEND_LINK, garante link no texto final
            try:
                _ns = str(out.get("planNextStep") or "").strip()
                out["replyText"] = _ensure_send_link_in_reply(out.get("replyText") or "", _ns)
            except Exception:
                pass

            # ✅ Regra de canal (sem alterar linguagem)
            out = _apply_sales_text_only_closure(out, ctx)

            # ⚠️ IMPORTANTE: NÃO gerar áudio aqui para LEAD.
            # O worker (routes/ycloud_tasks_bp.py) decide áudio/texto e faz TTS.
            out = _apply_safe_ai_meta(out, ctx)
            _final_cut_one_q(out)
            out = _prepare_worker_tts_text(out, ctx)
            try:
                _save_institutional_lead_memory(
                    ctx.get("waKey") or ctx.get("wa_key") or ctx.get("from_e164") or "",
                    out,
                    ctx,
                )
            except Exception:
                pass
            return out

        except Exception as e:
            # fallback ultra conservador (nunca fica mudo) — neutro, sem marketing
            _log_sales_lead_fallback(ctx, reason="exception", err=e)

            # Se caiu em exceção, mas o lead pediu LINK, não devolve triagem.
            try:
                if _looks_like_link_request(text):
                    base = (
                        os.getenv("FRONTEND_BASE")
                        or os.getenv("FRONTEND_BASE_URL")
                        or "https://mei-robo-prod.web.app"
                    )
                    base = (base or "").strip().rstrip("/")
                    link = base + "/"
                    reply = f"Aqui tá o link: {link}"
                    out = {
                        "ok": True,
                        "route": "sales_lead",
                        "replyText": reply,
                        "prefersText": True,
                        "intentFinal": "ACTIVATE",
                        "planNextStep": "SEND_LINK",
                        "policiesApplied": ["wa_bot:fallback_send_link_on_exception"],
                        "understanding": {
                            "route": "sales",
                            "intent": "ACTIVATE",
                            "confidence": "low",
                            "risk": "mid",
                            "depth": "shallow",
                            "next_step": "SEND_LINK",
                        },
                        "decisionDebug": {
                            "fallback": True,
                            "reason": "exception_in_sales_lead",
                            "err": (str(e) or "exception")[:180],
                        },
                        "ttsOwner": "worker",
                    }
                    out = _apply_sales_text_only_closure(out, ctx)
                    out = _apply_safe_ai_meta(out, ctx)
                    _final_cut_one_q(out)
                    out = _prepare_worker_tts_text(out, ctx)
                    return out
            except Exception:
                pass

            reply = _sales_lead_neutral_fallback()
            out = {
                "ok": True,
                "route": "sales_lead",
                "replyText": reply,
                "decisionDebug": {
                    "fallback": True,
                    "reason": "exception_in_sales_lead",
                    "err": (str(e) or "exception")[:180],
                },
                "ttsOwner": "worker",
            }
            out = _apply_sales_text_only_closure(out, ctx)
            out = _apply_safe_ai_meta(out, ctx)
            _final_cut_one_q(out)
            out = _prepare_worker_tts_text(out, ctx)
            return out
    # 2) SUPORTE (uid presente) — usa o legacy de forma compatível
    actor_type = str((ctx.get("actor_type") or "")).strip().lower()
    is_customer_final = (actor_type == "customer_final")

    # Observabilidade básica (customer_final)
    wa_key_cf = str((ctx.get("waKey") or ctx.get("wa_key") or ctx.get("from_e164") or "")).strip()

    # Se for CLIENTE FINAL (mensagem chegou no WABA do profissional), não usar SUPPORT_V2 (helpdesk da plataforma).
    # Ainda não troca a lógica interna: só separa rota + injeta persona para o legacy (mínimo seguro).
    if is_customer_final:
        try:
            if isinstance(ctx, dict) and not ctx.get("robotPersona"):
                _persona = _load_prof_robot_persona_v1(uid)
                if _persona:
                    ctx["robotPersona"] = _persona
                    ctx["robotPersonaId"] = "config.jeitoAtenderV1"
        except Exception:
            pass

        # ----------------------------------------------------------
        # CUSTOMER FINAL: tenta handler novo (safe-by-default)
        # ----------------------------------------------------------
        try:
            from services.bot_handlers import customer_final  # novo
            cf = customer_final.generate_reply(uid=uid, text=text, ctx=ctx)  # type: ignore
            if isinstance(cf, dict):
                reply_text = str(cf.get("replyText") or "").strip()
                if reply_text:
                    # ✅ Se o handler respondeu, NÃO cai no legacy.
                    try:
                        logging.info(
                            "[WA_BOT][CUSTOMER_FINAL_OK] waKey=%s route=%s",
                            (wa_key_cf or "")[:32],
                            str(cf.get("route") or "customer_final")[:48],
                        )
                    except Exception:
                        pass
                    # 🔧 Telemetria enriquecida a partir do contract do FRONT
                    am = cf.get("aiMeta") or {}

                    contract = cf.get("operationalContract") or {}

                    if isinstance(contract, dict) and contract:
                        def _wa_norm_customer_final_meta_identity_v1(value: object) -> str:
                            raw = str(value or "").strip().lower()
                            raw = "".join(ch if (ch.isalnum() or ch.isspace()) else " " for ch in raw)
                            return " ".join(raw.split())

                        def _wa_extract_customer_final_turn_name_for_meta_guard_v1() -> str:
                            try:
                                picked = _pick_lead_name(cf, ctx)
                                if str(picked or "").strip():
                                    return str(picked or "").strip()
                            except Exception:
                                pass

                            try:
                                txt = str(text or "").strip()
                                m = re.search(
                                    r"(?i)\b(?:sou|me chamo|meu nome é|meu nome e)\s+(?:o\s+|a\s+)?([A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-zà-ÿ]{1,30})\b",
                                    txt,
                                )
                                if m:
                                    return str(m.group(1) or "").strip()
                            except Exception:
                                pass

                            return ""

                        _customer_final_meta_name_guard = _wa_extract_customer_final_turn_name_for_meta_guard_v1()

                        def _wa_drop_customer_final_meta_value_if_name_v1(value: object, field_name: str) -> str:
                            v = str(value or "").strip()
                            if (
                                v
                                and _customer_final_meta_name_guard
                                and _wa_norm_customer_final_meta_identity_v1(v) == _wa_norm_customer_final_meta_identity_v1(_customer_final_meta_name_guard)
                            ):
                                try:
                                    logging.info(
                                        "[WA_CUSTOMER_FINAL_META_NAME_GUARD] dropped=True field=%s value=%s",
                                        field_name,
                                        v,
                                    )
                                except Exception:
                                    pass
                                return ""
                            return v

                        _customer_final_contract_segment_meta = _wa_drop_customer_final_meta_value_if_name_v1(
                            contract.get("segment"),
                            "contract.segment",
                        )
                        _customer_final_contract_archetype_meta = str(contract.get("archetype_id") or "").strip()

                        am["kbUsed"] = bool(
                            contract.get("hydrated_from_docs")
                            or contract.get("has_example_line")
                            or contract.get("has_practical_scene")
                            or _customer_final_contract_archetype_meta
                            or _customer_final_contract_segment_meta
                        )

                        am["kbExampleUsed"] = bool(contract.get("has_example_line"))
                        am["kbSceneUsed"] = bool(contract.get("has_practical_scene"))

                        am["kbDocPath"] = (
                            _customer_final_contract_segment_meta
                            or _customer_final_contract_archetype_meta
                            or ""
                        )

                        am["kbRequiredOk"] = bool(contract.get("hydrated_from_docs"))

                        am["kbMissReason"] = "" if am["kbRequiredOk"] else "kb_partial_or_missing"
                        am["kbMissingFields"] = []

                    out = {
                        "ok": True,
                        "route": cf.get("route") or "customer_final",
                        "replyText": reply_text,
                        # 🔎 Propaga telemetria/decisão do handler (worker pode usar ou ignorar)
                        "prefersText": bool(cf.get("prefersText", True)),
                        "understanding": cf.get("understanding") or {},
                        "planNextStep": cf.get("planNextStep") or cf.get("plan_next_step") or "",
                        "tokenUsage": cf.get("tokenUsage") or {},
                        "kbSnapshotSizeChars": cf.get("kbSnapshotSizeChars") or cf.get("kb_snapshot_chars") or 0,
                        "replySource": cf.get("replySource") or "customer_final",
                        "decisionDebug": cf.get("decisionDebug") or {},
                        # aiMeta básico (auditoria)
                        "aiMeta": am,
                        "ttsOwner": "worker",
                    }
                    # ✅ complementa aiMeta com carimbo de actor/persona (sem sobrescrever o que já veio)
                    try:
                        am = out.get("aiMeta") or {}
                        if not isinstance(am, dict):
                            am = {"mode": str(am)}
                        am.setdefault("actorType", "customer_final")
                        am.setdefault("personaUsed", bool((ctx or {}).get("robotPersona")))
                        am.setdefault("personaId", str((ctx or {}).get("robotPersonaId") or ""))
                        out["aiMeta"] = am
                    except Exception:
                        pass
                                        # ✅ Bugfix: se o Módulo 2 (customer_final) decidiu SEND_LINK, garante link no texto final
                    try:
                        _ns = str(out.get("planNextStep") or "").strip()
                        out["replyText"] = _ensure_send_link_in_reply(out.get("replyText") or "", _ns)
                    except Exception:
                        pass

                    out = _apply_safe_ai_meta(out, ctx)
                    _final_cut_one_q(out)
                    return out

        except Exception:
            pass


    try:
        # 2) SUPORTE (uid presente) — tenta SUPPORT_V2 (Action Map / Artigo), com fallback no legacy
        try:
            if SUPPORT_V2 and (not is_customer_final):
                # Best-effort: injeta persona do profissional (se existir) no ctx do suporte.
                try:
                    if isinstance(ctx, dict) and not ctx.get("robotPersona"):
                        _persona = _load_prof_robot_persona_v1(uid)
                        if _persona:
                            ctx["robotPersona"] = _persona
                            ctx["robotPersonaId"] = "config.jeitoAtenderV1"
                except Exception:
                    pass
                from services.bot_handlers import support_v2  # type: ignore
                v2 = support_v2.generate_reply(uid=uid, text=text, ctx=ctx)  # type: ignore
                if isinstance(v2, dict):
                    reply_text = str(v2.get("replyText") or "").strip()
                    if reply_text:
                        out = {
                            "ok": True,
                            "route": v2.get("route") or "support_v2",
                            "replyText": reply_text,

                            # 🔥 Propaga metadados para o worker decidir canal/humanização
                            "displayName": str(v2.get("displayName") or "").strip(),
                            "prefersText": bool(v2.get("prefersText")),

                            # ✅ Contexto canônico (cérebro) + tipo (p/ fala conceitual no worker)
                            # Observação: kbContext pode ser grande; o worker faz truncagem segura.
                            "kbContext": v2.get("kbContext") or "",
                            "kind": str(v2.get("kind") or "").strip(),
                            "nameToSay": str(v2.get("nameToSay") or "").strip(),

                            # Marca que o áudio deve ser decidido fora (worker)
                            "ttsOwner": "worker",
                        }
                        # ⚠️ IMPORTANTE: NÃO gerar áudio aqui (evita duplicidade de TTS).
                        _final_cut_one_q(out)
                        return out
        except Exception as e:
            # Nunca quebrar suporte por causa do v2; cai no legacy
            logging.exception("[WA_BOT][SUPPORT_V2] falhou, caindo no legacy: %s", e)

        legacy = _get_legacy_module()

        captured = {"text": None}

        def _capture_send_text(to: str, msg: str):
            captured["text"] = msg
            return msg

        # payload mínimo compatível com process_change do legacy
        value = {
            "messages": [
                {
                    "from": sender_id or (from_e164 or ""),
                    "type": "text",
                    "text": {"body": text or ""},
                }
            ]
        }

        legacy.process_change(value, _capture_send_text, uid, app_tag=ctx.get("app_tag") or "wa_bot")
        reply_text = captured["text"] or "Certo."
        out = {
            "ok": True,
            "route": ("customer_final_legacy" if is_customer_final else "support_legacy"),
            "replyText": reply_text,

            "aiMeta": {
                "actorType": ("customer_final" if is_customer_final else "support"),
                "personaUsed": bool(ctx.get("robotPersona")),
                "personaId": str(ctx.get("robotPersonaId") or ""),
            },


            # 🔒 Garante que o áudio será decidido no worker
            "ttsOwner": "worker",
        }
        out = _apply_safe_ai_meta(out, ctx)
        _final_cut_one_q(out)
        return out

    except Exception as e:
        # fallback conservador (não quebra o webhook)
        reply_text = "Certo."
        out = {
            "ok": False,
            "route": "support_legacy",
            "replyText": reply_text,
            "error": str(e),

            # 🔒 Garante que o áudio será decidido no worker
            "ttsOwner": "worker",
        }
        out = _apply_safe_ai_meta(out, ctx)
        _final_cut_one_q(out)
        return out


def schedule_appointment(uid: str, ag: Dict[str, Any], *, allow_fallback: bool = True) -> Tuple[bool, str, Optional[str]]:
    """Cria um agendamento. Retorna (ok, motivo, ag_id)."""
    try:
        _ensure_legacy("schedule_appointment")
        legacy = _get_legacy_module()
        return legacy.schedule_appointment(uid, ag, allow_fallback=allow_fallback)  # type: ignore[attr-defined]
    except Exception as e:
        print(f"[WA_BOT][FACHADA] schedule_appointment ERRO: {e}\n{traceback.format_exc()}", flush=True)
        return False, str(e), None


def reschedule_appointment(uid: str, ag_id: str, updates: Dict[str, Any]) -> Tuple[bool, str]:
    """Reagenda um registro existente. Assinatura enxuta e estável."""
    try:
        _ensure_legacy("reschedule_appointment")
        legacy = _get_legacy_module()
        return legacy.reschedule_appointment(uid, ag_id, updates)  # type: ignore[attr-defined]
    except Exception as e:
        print(f"[WA_BOT][FACHADA] reschedule_appointment ERRO: {e}\n{traceback.format_exc()}", flush=True)
        return False, str(e)


# =============================
# Utilitários de diagnóstico
# =============================

def info() -> str:
    """String humana com status rápido."""
    h = healthcheck()
    return (
        f"MEI Robô — wa_bot fachada v{h['version']} ({h['build_date']})\n"
        f"NLU_MODE={h['nlu_mode']} DEMO_MODE={h['demo_mode']}\n"
        f"legacy={h['has_legacy']} new_pipeline={h['has_new_pipeline']}"
    )

# =====================================================================
# >>> ADIÇÃO MÍNIMA: adapter process_change + auto-reply de backup
# =====================================================================

# Tenta importar o sender uma única vez (sem quebrar caso não exista)
try:
    from .wa_send import send_text as _send_text  # type: ignore
except Exception as _e:
    _send_text = None
    logging.exception("[WA_BOT][FACHADA] wa_send indisponível: %s", _e)

def _extract_from_and_text_from_change(change: Dict[str, Any]) -> Tuple[Optional[str], str]:
    """Extrai wa_id do remetente e o texto, seguindo o shape da Cloud API."""
    try:
        # Aceitar dois formatos:
        # (1) {"value": {...}}  (Meta-style)
        # (2) {...}            (já normalizado)
        value = change.get("value") if isinstance(change, dict) else None
        if not isinstance(value, dict) or not value:
            value = change if isinstance(change, dict) else {}
        msgs = value.get("messages") or []
        if not msgs:
            return None, ""
        m = msgs[0]
        from_id = m.get("from")
        text = ""
        if m.get("type") == "text":
            text = ((m.get("text") or {}).get("body") or "").strip()
        return from_id, text
    except Exception:
        return None, ""

def _basic_autoreply(from_id: Optional[str], body: str, send_fn: Optional[Callable[[str, str], Any]]) -> bool:
    """Resposta enxuta caso o legacy não esteja disponível."""
    try:
        if not from_id or send_fn is None:
            return False

        msg = "Entendi 🙂 Me diz rapidinho o que você precisa e eu te ajudo."
        send_fn(from_id, msg)
        return True
    except Exception as e:
        logging.exception("[WA_BOT][FACHADA] basic_autoreply erro: %s", e)
        return False

def process_change(
    change: Dict[str, Any],
    send_fn: Optional[Callable[[str, str], Any]] = None,
    uid_default: Optional[str] = None,
    app_tag: Optional[str] = None,
) -> bool:
    """
    Assinatura compatível com routes/webhook.py:
      process_change(value, _send_text, uid_default, app_tag)

    Estratégia:
      1) Se legacy tiver process_change(...) com a mesma assinatura, delega.
      2) Caso contrário, tenta legacy.process_inbound(change) / process_inbound(change).
      3) Persistindo indisponibilidade, responde com auto-reply básico (sem FALLBACK).
    """
    # Sender efetivo (preferir o injetado pelo webhook)
    effective_send = send_fn or _send_text

    # ✅ Opção B (Vendas com IA): se uid não veio resolvido, tratamos como LEAD.
    # Importante: o webhook continua burro — aqui é o cérebro (wa_bot).
    # Segurança/produto: resposta pública e curta; sem "número errado".
    if not (uid_default or ""):

        from_id, _body = _extract_from_and_text_from_change(change)

        # tenta capturar IDs do evento para observabilidade
        try:
            value = (change or {}).get("value") or {}
            msgs = value.get("messages") or []
            msg0 = msgs[0] if msgs else {}
            msg_type = (msg0.get("type") or "").strip().lower()
            wa_key_local = "".join(ch for ch in (from_id or "") if ch.isdigit())
            ctx_local = {
                "from_e164": from_id or "",
                "wa_id": from_id or "",  # ajuda o reply_to_text a formar sender_id
                "waKey": wa_key_local or (from_id or ""),
                "msg_type": msg_type,
                "wamid": (msg0.get("id") or "").strip(),
                "event_key": (change or {}).get("event_key") or (change or {}).get("eventKey") or "",
                "app_tag": app_tag or "",
                # contexto mínimo pra IA (sem “frases prontas”)
                "actor_type": "unknown_or_lead",
                "route_hint": "vendas",
            }
            try:
                lead_memory = _load_institutional_lead_memory(wa_key_local)
                if lead_memory:
                    ctx_local.update({k: v for k, v in lead_memory.items() if v})
            except Exception:
                pass
        except Exception:
            wa_key_local = "".join(ch for ch in (from_id or "") if ch.isdigit())
            ctx_local = {
                "from_e164": from_id or "",
                "wa_id": from_id or "",
                "waKey": wa_key_local or (from_id or ""),
                "msg_type": "",
                "app_tag": app_tag or "",
                "route_hint": "vendas",
            }
            try:
                lead_memory = _load_institutional_lead_memory(wa_key_local)
                if lead_memory:
                    ctx_local.update({k: v for k, v in lead_memory.items() if v})
            except Exception:
                pass

        # ✅ Unificar núcleo de VENDAS: passa SEMPRE pelo reply_to_text(...)
        # Isso garante que o Módulo 1 (Conversational Front) seja o "dono" nos 5 primeiros turnos.
        try:
            out = reply_to_text("", _body or "", ctx_local) or {}
            try:
                _save_institutional_lead_memory(wa_key_local, out, ctx_local)
            except Exception:
                pass
            reply_text = str(out.get("replyText") or "").strip()
            if not reply_text:
                _log_sales_lead_fallback(ctx_local, reason="empty_reply_from_reply_to_text")
                reply_text = _sales_lead_neutral_fallback(str(out.get("leadName") or "").strip())

            if reply_text and effective_send is not None and from_id:
                effective_send(from_id, reply_text)
                return True

        except Exception as e:
            # fallback compat: tentar o handler antigo (change -> replyText)
            try:
                from services.bot_handlers import sales_lead  # type: ignore
                out = sales_lead.handle_sales_lead(change)  # type: ignore
                lead_name = str((out or {}).get("name") or (out or {}).get("leadName") or "").strip()
                reply_text = str((out or {}).get("replyText") or "").strip()
                if not reply_text:
                    _log_sales_lead_fallback(ctx_local, reason="empty_reply_fallback")
                    reply_text = _sales_lead_neutral_fallback(lead_name)
                if reply_text and effective_send is not None and from_id:
                    effective_send(from_id, reply_text)
                    return True
            except Exception as e2:
                _log_sales_lead_fallback(ctx_local, reason="exception", err=e2 or e)
                if effective_send is not None and from_id:
                    effective_send(from_id, _sales_lead_neutral_fallback())
                    return True
            # sem sender/from_id, segue fluxo (não quebra)
            pass


    # ✅ SUPORTE V2: se uid_default existe e SUPPORT_V2 está ligado, tenta responder direto (sem legacy).
    try:
        if SUPPORT_V2 and (uid_default or ""):
            from_id, body = _extract_from_and_text_from_change(change)
            if body and effective_send is not None and from_id:
                ctx_local = {
                    "from_e164": from_id or "",
                    "wa_id": from_id or "",
                    "app_tag": app_tag or "",
                    "msg_type": ((((change or {}).get("value") or {}).get("messages") or [{}])[0].get("type") or "").strip().lower(),
                }
                out = reply_to_text(uid_default, body, ctx_local)
                txt = str((out or {}).get("replyText") or "").strip()
                if txt:
                    effective_send(from_id, txt)
                    # Se reply_to_text gerou audioUrl, o sender de áudio é feito em outro ponto do pipeline;
                    # aqui mantemos compat e só enviamos texto.
                    return True
    except Exception as e:
        logging.exception("[WA_BOT][SUPPORT_V2] process_change falhou, caindo no legacy: %s", e)

    # 1) Delegação ao legacy (tentando corresponder à assinatura que o blueprint usa)
    try:
        if _using_legacy() and _HAS_LEGACY:
            legacy = _get_legacy_module()
            if hasattr(legacy, "process_change"):
                try:
                    ok = bool(legacy.process_change(change, effective_send, uid_default, app_tag))  # type: ignore[attr-defined]
                    if ok:
                        return True
                except TypeError:
                    # Legacy pode ter assinatura diferente (apenas change). Tentar simples.
                    ok = bool(legacy.process_change(change))  # type: ignore[attr-defined]
                    if ok:
                        return True
            # Fallback para entrada genérica do legacy (somente se existir)
            if hasattr(legacy, "process_inbound"):
                resp = legacy.process_inbound(change)  # type: ignore[attr-defined]
                if isinstance(resp, dict) and resp.get("ok"):
                    return True
    except Exception as e:
        logging.exception("[WA_BOT][FACHADA] delegação ao legacy falhou: %s", e)

    # 2) Tentar a própria entrada genérica desta fachada
    try:
        resp2 = process_inbound(change)  # pode delegar ao legacy internamente
        if isinstance(resp2, dict) and resp2.get("ok"):
            return True
    except Exception as e:
        logging.exception("[WA_BOT][FACHADA] process_inbound local falhou: %s", e)

    # 3) Último recurso: auto-reply simples (não deixa cair em [FALLBACK])
    from_id, body = _extract_from_and_text_from_change(change)
    ok_basic = _basic_autoreply(from_id, body, effective_send)
    return bool(ok_basic)


__all__ = [
    "healthcheck",
    "process_inbound",
    "reply_to_text",
    "schedule_appointment",
    "reschedule_appointment",
    "info",
    # >>> novo adapter exposto:
    "process_change",
]
