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
import traceback
import logging
from typing import Any, Dict, Optional, Tuple, Callable  # <- acrescentado Callable

# >>> PATCH: gerar audioUrl institucional (lead + áudio)
from services.institutional_tts_media import generate_institutional_audio_url

__version__ = "1.0.0-fachada"
BUILD_DATE = "2025-09-30"

# Feature flags (com defaults seguros)
NLU_MODE = os.getenv("NLU_MODE", "legacy").strip().lower()  # "v1" | "legacy"
DEMO_MODE = os.getenv("DEMO_MODE", "0").strip() in ("1", "true", "True")

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


# ==========================================================
# ✅ PATCH ÚNICO: substituir completamente reply_to_text(...)
# ==========================================================
def reply_to_text(uid: str, text: str, ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Retorna um dict com replyText (texto a ser enviado).
    - uid vazio -> handler de vendas (lead)
    - uid presente -> delega ao wa_bot_legacy.process_change capturando o texto gerado
    """
    ctx = ctx or {}
    from_e164 = (ctx.get("from_e164") or "").strip()

    # 1) LEAD / VENDAS (uid ausente)
    if not uid:
        try:
            from services.bot_handlers import sales_lead
            reply = sales_lead.generate_reply(text=text, ctx=ctx)  # deve retornar string
            if not reply:
                reply = "Oi! Sou o MEI Robô. Quer conhecer os planos?"

            # >>> PATCH: quando lead + áudio, gerar audioUrl institucional (sem quebrar nada)
            audio_url = None
            if ctx.get("msg_type") == "audio":
                try:
                    audio_url = generate_institutional_audio_url(
                        text=reply,
                        base_url=os.environ.get("BACKEND_BASE_URL", "").rstrip("/")
                    )
                except Exception:
                    audio_url = None

            out = {"ok": True, "route": "sales_lead", "replyText": reply}
            if audio_url:
                out["audioUrl"] = audio_url
            return out

        except Exception:
            # fallback ultra conservador (nunca fica mudo)
            return {"ok": True, "route": "sales_lead", "replyText": "Oi! Sou o MEI Robô. Quer conhecer os planos?"}

    # 2) SUPORTE (uid presente) — usa o legacy de forma compatível
    try:
        legacy = _get_legacy_module()

        captured = {"text": None}

        def _capture_send_text(to: str, msg: str):
            captured["text"] = msg
            return msg

        # payload mínimo compatível com process_change do legacy
        value = {
            "messages": [
                {
                    "from": from_e164 or uid,
                    "type": "text",
                    "text": {"body": text or ""},
                }
            ]
        }

        legacy.process_change(value, _capture_send_text, uid, app_tag=ctx.get("app_tag") or "wa_bot")
        out = captured["text"] or "Certo."
        return {"ok": True, "route": "support_legacy", "replyText": out}

    except Exception as e:
        # fallback conservador (não quebra o webhook)
        return {"ok": False, "route": "support_legacy", "replyText": "Certo.", "error": str(e)}


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
        value = (change or {}).get("value") or {}
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
        t = (body or "").strip().lower()
        if t in ("oi", "ola", "olá", "oie", "hello", "hi", "hey"):
            send_fn(from_id, "Oi! Estou ligado ✅. Posso te ajudar com *agendamento* ou digite *precos*.")
            return True
        if t == "precos" or "preço" in t or "precos" in t or "preços" in t or "preco" in t:
            send_fn(from_id, "Tabela: Corte masc R$50 | Barba R$35 | Combo R$75. Diga *agendar* para marcar.")
            return True
        if "agendar" in t or "agenda" in t:
            send_fn(from_id, "Me diga o dia e hora (ex.: *amanhã 15h*) que eu verifico disponibilidade.")
            return True
        send_fn(from_id, "Recebi ✅. Para preços, digite *precos*. Para marcar, diga *agendar* + horário.")
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
    # Só responde para mensagens de TEXTO (conteúdo público) e não toca no pipeline de voz.
    if not (uid_default or ""):
        try:
            from services.bot_handlers.sales_lead import handle_sales_lead  # type: ignore
            if handle_sales_lead(change, effective_send, app_tag=app_tag):
                return True
        except Exception:
            # fallback ultra conservador: se handler não existir, não quebra o fluxo
            pass


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
