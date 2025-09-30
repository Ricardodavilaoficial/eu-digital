# services/wa_bot.py
# FacÌ§ada v1 â€” MEI RoboÌ‚ (30/09/2025)
# Objetivo: manter a fachada estaÌvel enquanto extraÃ­mos moÌdulos internos.
# - Se NLU_MODE != "v1", delega tudo para services/wa_bot_legacy.py (comportamento atual).
# - Se NLU_MODE == "v1", usa pipeline novo se disponiÌvel; caso contraÌrio, cai no legacy.
# - Sem mudar rotas/integracÌ§oÌƒes do backend. Safe-by-default.
#
# Entradas principais (mantidas):
#   - process_inbound(event)  : ponto de entrada geneÌrico (webhook/servicÌ§os)
#   - reply_to_text(uid, text, ctx=None)
#   - schedule_appointment(uid, ag, *, allow_fallback=True)
#   - reschedule_appointment(uid, ag_id, updates)
#
# ObservacÌ§oÌƒes:
# - Este arquivo NAÌƒO inclui regra de negoÌcio pesada.
# - O legacy eÌ responsaÌvel por todos os detalhes enquanto migramos por etapas.
# - Logs claros para diagnosticar flags/queda de moÌdulos.
#
# VersoÌƒes:
#   v1.0.0-fachada (2025-09-30) â€” primeira fachada com delegacÌ§aÌƒo condicional.

from __future__ import annotations

import os
import traceback
from typing import Any, Dict, Optional, Tuple

__version__ = "1.0.0-fachada"
BUILD_DATE = "2025-09-30"

# Feature flags (com defaults seguros)
NLU_MODE = os.getenv("NLU_MODE", "legacy").strip().lower()  # "v1" | "legacy"
DEMO_MODE = os.getenv("DEMO_MODE", "0").strip() in ("1", "true", "True")

# Tentativa de carregar implementacÌ§aÌƒo legacy
try:
    from . import wa_bot_legacy as _legacy
    _HAS_LEGACY = True
except Exception as e:
    _legacy = None  # type: ignore
    _HAS_LEGACY = False
    print(f"[WA_BOT][FACHADA] Aviso: naÌƒo encontrei services/wa_bot_legacy.py ({e})", flush=True)

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
    # Comentado para naÌƒo poluir logs em producÌ§aÌƒo:
    # print(f"[WA_BOT][FACHADA] Pipeline novo indisponiÌvel (ok nesta fase): {e}", flush=True)


def _using_legacy() -> bool:
    """Decide se devemos usar o legacy nesta chamada."""
    if NLU_MODE != "v1":
        return True
    # Se pediram v1, mas os moÌdulos novos naÌƒo estaÌƒo presentes, cair no legacy.
    if not _HAS_NEW:
        return True
    # v1 habilitado + moÌdulos presentes: seguir para novo
    return False


def _ensure_legacy(func_name: str):
    if not _HAS_LEGACY or _legacy is None:
        raise RuntimeError(
            f"[WA_BOT][FACHADA] '{func_name}' requisitou legacy, mas services/wa_bot_legacy.py naÌƒo foi encontrado."
        )


# =============================
# Pontos de entrada "estaÌveis"
# =============================

def healthcheck() -> Dict[str, Any]:
    """Retorna informacÌ§oÌƒes leves para diagnoÌstico."""
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
    """Entrada geneÌrica (ex.: webhook do WhatsApp)."""
    try:
        if _using_legacy():
            _ensure_legacy("process_inbound")
            return _legacy.process_inbound(event)  # type: ignore[attr-defined]
        # Pipeline novo (v1) â€” neste estaÌgio, delegamos quase tudo ao legacy,
        # mas este bloco existe para evolucÌ§oÌƒes graduais sem mudar a fachada.
        _ensure_legacy("process_inbound(v1-fallback)")
        return _legacy.process_inbound(event)  # type: ignore[attr-defined]
    except Exception as e:
        print(f"[WA_BOT][FACHADA] process_inbound ERRO: {e}\n{traceback.format_exc()}", flush=True)
        # Nunca explodir: devolver shape conhecido
        return {"ok": False, "error": str(e), "stage": "fachada"}


def reply_to_text(uid: str, text: str, ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Resposta a uma mensagem de texto (contexto opcional)."""
    ctx = ctx or {}
    try:
        if _using_legacy():
            _ensure_legacy("reply_to_text")
            return _legacy.reply_to_text(uid, text, ctx)  # type: ignore[attr-defined]
        # Aqui entra o pipeline novo. Por ora, delegamos ao legacy para evitar regressaÌƒo.
        _ensure_legacy("reply_to_text(v1-fallback)")
        return _legacy.reply_to_text(uid, text, ctx)  # type: ignore[attr-defined]
    except Exception as e:
        print(f"[WA_BOT][FACHADA] reply_to_text ERRO: {e}\n{traceback.format_exc()}", flush=True)
        return {"ok": False, "error": str(e), "stage": "fachada"}


def schedule_appointment(uid: str, ag: Dict[str, Any], *, allow_fallback: bool = True) -> Tuple[bool, str, Optional[str]]:
    """Cria um agendamento. Retorna (ok, motivo, ag_id).

    Nesta fase, usamos sempre o legacy (que jaÌ valida e persiste). Quando o engine
    novo estiver pronto, ativaremos via NLU_MODE=v1 mantendo assinatura.
    """
    try:
        _ensure_legacy("schedule_appointment")
        return _legacy.schedule_appointment(uid, ag, allow_fallback=allow_fallback)  # type: ignore[attr-defined]
    except Exception as e:
        print(f"[WA_BOT][FACHADA] schedule_appointment ERRO: {e}\n{traceback.format_exc()}", flush=True)
        return False, str(e), None


def reschedule_appointment(uid: str, ag_id: str, updates: Dict[str, Any]) -> Tuple[bool, str]:
    """Reagenda um registro existente. Assinatura enxuta e estaÌvel."""
    try:
        _ensure_legacy("reschedule_appointment")
        return _legacy.reschedule_appointment(uid, ag_id, updates)  # type: ignore[attr-defined]
    except Exception as e:
        print(f"[WA_BOT][FACHADA] reschedule_appointment ERRO: {e}\n{traceback.format_exc()}", flush=True)
        return False, str(e)


# =============================
# UtilitaÌrios de diagnoÌstico
# =============================

def info() -> str:
    """String humana com status raÌpido."""
    h = healthcheck()
    return (
        f"MEI RoboÌ‚ â€” wa_bot fachada v{h['version']} ({h['build_date']})\n"
        f"NLU_MODE={h['nlu_mode']} DEMO_MODE={h['demo_mode']}\n"
        f"legacy={h['has_legacy']} new_pipeline={h['has_new_pipeline']}"
    )


__all__ = [
    "healthcheck",
    "process_inbound",
    "reply_to_text",
    "schedule_appointment",
    "reschedule_appointment",
    "info",
]


