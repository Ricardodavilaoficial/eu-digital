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
from typing import Any, Dict, Optional, Tuple, Callable  # <- acrescentado Callable

# Runtime mode router (sales vs operational)

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
        if any(k in t for k in ("voz", "áudio", "audio", "audios", "ptt", "fala", "responder por voz")):
            return "VOZ"
        if any(k in t for k in ("oi", "olá", "ola", "bom dia", "boa tarde", "boa noite", "valeu", "obrigado", "obrigada")):
            return "SOCIAL"
        return "OTHER"
    except Exception:
        return "OTHER"


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

        if include_segment_id and d.get("segment_id"):
            out["segment_id"] = _clip_front_text(d.get("segment_id"), 80)

        if include_archetype_id and d.get("archetype_id"):
            out["archetype_id"] = _clip_front_text(d.get("archetype_id"), 80)

        if d.get("conversation_mode"):
            out["conversation_mode"] = _clip_front_text(d.get("conversation_mode"), 80)

        if d.get("one_liner"):
            out["one_liner"] = _clip_front_text(d.get("one_liner"), 180)

        if d.get("micro_scene"):
            out["micro_scene"] = _clip_front_text(d.get("micro_scene"), 260)

        if d.get("primary_goal"):
            out["primary_goal"] = _clip_front_text(d.get("primary_goal"), 120)

        if d.get("service_noun"):
            out["service_noun"] = _clip_front_text(d.get("service_noun"), 80)

        if d.get("handoff_format"):
            out["handoff_format"] = _clip_front_text(d.get("handoff_format"), 120)

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
        except Exception:
            out["segments"] = {}

        try:
            subs = {}
            for doc in db.collection("kb_subsegments_v1").stream():
                subs[doc.id] = doc.to_dict() or {}
            out["subsegments"] = subs
        except Exception:
            out["subsegments"] = {}

        try:
            archs = {}
            for doc in db.collection("kb_archetypes_v1").stream():
                archs[doc.id] = doc.to_dict() or {}
            out["archetypes"] = archs
        except Exception:
            out["archetypes"] = {}
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
        micro = str(((pack.get("runtime_short") or {}) if isinstance(pack, dict) else {}).get("micro_scene") or "")
        reply = _simple_tpl(micro, slots).strip()
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
        s = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if len(s) <= limit:
            return s

        # fallback seguro mínimo:
        # preserva o banco novo, zera anexos menos críticos
        minimal = {
            "answer_playbook_v1": {
                "runtime_selector_v1": ((payload.get("answer_playbook_v1") or {}).get("runtime_selector_v1") or {}),
                "pack_selection_policy_v1": {},
                "segment_template_v1": {},
                "segment_value_map_v1": {},
            },
            "value_packs_v1": {},
            "platform_pricing": {},
            "kb_segments_v1": payload.get("kb_segments_v1") or {},
            "kb_subsegments_v1": payload.get("kb_subsegments_v1") or {},
            "kb_archetypes_v1": payload.get("kb_archetypes_v1") or {},
        }
        s2 = json.dumps(minimal, ensure_ascii=False, separators=(",", ":"))
        if len(s2) <= limit:
            return s2

        # último fallback: mantém subsegments primeiro, depois archetypes e segments
        ultra_minimal = {
            "answer_playbook_v1": {
                "runtime_selector_v1": ((payload.get("answer_playbook_v1") or {}).get("runtime_selector_v1") or {}),
            },
            "value_packs_v1": {},
            "platform_pricing": {},
            "kb_segments_v1": payload.get("kb_segments_v1") or {},
            "kb_subsegments_v1": payload.get("kb_subsegments_v1") or {},
            "kb_archetypes_v1": payload.get("kb_archetypes_v1") or {},
        }
        s3 = json.dumps(ultra_minimal, ensure_ascii=False, separators=(",", ":"))
        if len(s3) <= limit:
            return s3

        # fallback extremo: subsegments sozinhos + archetypes se couber
        extreme = {
            "answer_playbook_v1": {
                "runtime_selector_v1": ((payload.get("answer_playbook_v1") or {}).get("runtime_selector_v1") or {}),
            },
            "kb_subsegments_v1": payload.get("kb_subsegments_v1") or {},
            "kb_archetypes_v1": payload.get("kb_archetypes_v1") or {},
            "kb_segments_v1": {},
            "value_packs_v1": {},
            "platform_pricing": {},
        }
        s4 = json.dumps(extreme, ensure_ascii=False, separators=(",", ":"))
        if len(s4) <= limit:
            return s4

        # fallback extremo 2: só subsegments
        ultra_minimal = {
            "answer_playbook_v1": {
                "runtime_selector_v1": ((payload.get("answer_playbook_v1") or {}).get("runtime_selector_v1") or {}),
            },
            "kb_subsegments_v1": payload.get("kb_subsegments_v1") or {},
            "kb_archetypes_v1": {},
            "kb_segments_v1": {},
            "value_packs_v1": {},
            "platform_pricing": {},
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

        if _size(work) <= limit:
            return work

        # 1) podar o que menos importa para o lookup do banco novo
        ap = dict(work.get("answer_playbook_v1") or {})
        svm = dict(ap.get("segment_value_map_v1") or {})
        if svm:
            ap["segment_value_map_v1"] = {}
            work["answer_playbook_v1"] = ap
            if _size(work) <= limit:
                return work

        # 2) corta value packs antes de tocar no banco novo
        if work.get("value_packs_v1"):
            work["value_packs_v1"] = {}
            if _size(work) <= limit:
                return work

        # 3) corta pricing antes de tocar no banco novo
        if work.get("platform_pricing"):
            work["platform_pricing"] = {}
            if _size(work) <= limit:
                return work

        # 4) enxuga answer_playbook pesado, preservando só runtime_selector
        ap = dict(work.get("answer_playbook_v1") or {})
        keep_runtime = {
            "runtime_selector_v1": ap.get("runtime_selector_v1") or {},
            "pack_selection_policy_v1": {},
            "segment_template_v1": {},
            "segment_value_map_v1": {},
        }
        work["answer_playbook_v1"] = keep_runtime
        if _size(work) <= limit:
            return work

        # 5) agora sim começa a poda do banco novo, do menos crítico para o mais crítico
        # segments cai antes
        if work.get("kb_segments_v1"):
            work["kb_segments_v1"] = {}
            if _size(work) <= limit:
                return work

        # archetypes cai depois
        if work.get("kb_archetypes_v1"):
            work["kb_archetypes_v1"] = {}
            if _size(work) <= limit:
                return work

        # subsegments é a última camada a cair
        if work.get("kb_subsegments_v1"):
            work["kb_subsegments_v1"] = {}
            if _size(work) <= limit:
                return work

        return work
    except Exception:
        return payload or {}


def _build_front_kb_snapshot(topic: str) -> str:
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
            compact_archetypes[aid] = _compact_front_kb_doc(ad)
    except Exception:
        compact_archetypes = {}


    # ✅ packs_v1: snapshot em JSON compacto (para render determinístico no front)
    try:
        pb = (kb.get("answer_playbook_v1") or {}) if isinstance(kb, dict) else {}
        rs = (pb.get("runtime_selector_v1") or {}) if isinstance(pb, dict) else {}
        mode = str((rs.get("mode") or "")).strip().lower()
        if mode == "packs_v1":
            import json as _json
            snapshot_limit = FRONT_KB_MAX_CHARS_PACKS_V1
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
                    "pack_selection_policy_v1": pb.get("pack_selection_policy_v1") if isinstance(pb, dict) else {},
                    "segment_template_v1": pb.get("segment_template_v1") if isinstance(pb, dict) else {},
                    "segment_value_map_v1": pb.get("segment_value_map_v1") if isinstance(pb, dict) else {},
                },
                "value_packs_v1": kb.get("value_packs_v1") or {},
                "platform_pricing": {"current": pricing_compact} if pricing_compact else {},
                "kb_segments_v1": compact_segments,
                "kb_subsegments_v1": compact_subsegments,
                "kb_archetypes_v1": compact_archetypes,
            }

            # garantia mínima: se houver subsegments reais, eles são prioridade máxima
            # para a arquitetura do front baseada no banco novo
            if not payload.get("kb_subsegments_v1") and compact_subsegments:
                payload["kb_subsegments_v1"] = compact_subsegments
            payload = _prune_front_kb_payload(payload, snapshot_limit)
            s = _safe_json_dumps_with_limit(payload, snapshot_limit)
            try:
                parsed_ok = False
                try:
                    obj_test = json.loads(s)
                    parsed_ok = isinstance(obj_test, dict)
                except Exception:
                    parsed_ok = False

                logging.info(
                    "[WA_BOT][KB_SNAPSHOT] topic=%s chars=%s limit=%s valid_json=%s has_segments=%s has_subsegments=%s has_archetypes=%s n_segments=%s n_subsegments=%s n_archetypes=%s",
                    str(topic or "").strip().upper(),
                    len(s or ""),
                    snapshot_limit,
                    parsed_ok,
                    bool((payload or {}).get("kb_segments_v1")),
                    bool((payload or {}).get("kb_subsegments_v1")),
                    bool((payload or {}).get("kb_archetypes_v1")),
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
def reply_to_text(uid: str, text: str, ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Retorna um dict com replyText (texto a ser enviado).
    - uid vazio -> handler de vendas (lead)
    - uid presente -> delega ao wa_bot_legacy.process_change capturando o texto gerado
    """
    ctx = ctx or {}
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
                ai_turns = 0
                wa_key = (ctx.get("waKey") or ctx.get("wa_key") or ctx.get("from_e164") or "").strip()
                uid_owner = (ctx.get("uid_owner") or "").strip()
                try:
                    from services.speaker_state import get_speaker_state  # type: ignore
                    st = get_speaker_state(wa_key, uid_owner=(uid_owner or None)) if wa_key else {}
                    ai_turns = int(st.get("ai_turns") or 0)
                except Exception:
                    ai_turns = 0

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

                front_turns_allowed = bool((ai_turns < MAX_AI_TURNS) or POST5_AI_ENABLED)

                if front_turns_allowed and (not force_operational) and front_mode == "packs_v1":
                    try:
                        front_attempted = True
                        from services.conversational_front import handle as _front_handle  # type: ignore

                        # Monta KB Snapshot compacto (Firestore->wa_bot) com teto.
                        topic_hint = _front_topic_hint(text or "")
                        kb_snapshot = _build_front_kb_snapshot(topic_hint)

                        state_summary = {
                            "ai_turns": ai_turns,
                            "is_lead": True,
                            "name_hint": ctx.get("name_hint") or ctx.get("displayName") or ctx.get("leadName") or "",
                            "segment_hint": ctx.get("segment_hint") or "",
                            # Micro-contexto (best-effort). Se não vier, segue vazio.
                            "last_intent": ctx.get("last_intent") or ctx.get("lastIntent") or "",
                            "last_user_goal": ctx.get("last_user_goal") or ctx.get("lastUserGoal") or "",
                        }

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


                        # ✅ packs_v1: render determinístico só entra como RESCUE, não como atropelo da IA
                        try:
                            dec = (front_out.get("decider") or {}) if isinstance(front_out, dict) else {}
                            current_reply = str((front_out.get("replyText") or "") if isinstance(front_out, dict) else "").strip()
                            current_source = str((front_out.get("replySource") or "") if isinstance(front_out, dict) else "").strip().lower()

                            should_rescue_with_pack = bool(
                                dec and (
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
                                    # downgrade seguro: mantém reply do front e não força link-only
                                    out["planNextStep"] = "NONE"
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
                            # 🔒 Mata a confusão de "IA primeiro vs fallback":
                            # Se o FRONT respondeu, isso é IA-first por definição.
                            out["aiMeta"] = {
                                "ia_first": True,
                                # Mantém compat com telemetria esperada no worker/outbox
                                "iaSource": str((front_out.get("iaSource") or "front")),
                                "replySource": str(front_out.get("replySource") or "front"),
                                "route": "conversational_front",
                                "fallbackReason": "",
                            }
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

            # ⚠️ IMPORTANTE: NÃO gerar áudio aqui para LEAD.
            # O worker (routes/ycloud_tasks_bp.py) decide áudio/texto e faz TTS.
            _final_cut_one_q(out)
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
                    _final_cut_one_q(out)
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
            _final_cut_one_q(out)
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
                        am["kbUsed"] = bool(
                            contract.get("hydrated_from_docs")
                            or contract.get("has_example_line")
                            or contract.get("has_practical_scene")
                            or contract.get("archetype_id")
                            or contract.get("segment")
                        )

                        am["kbExampleUsed"] = bool(contract.get("has_example_line"))
                        am["kbSceneUsed"] = bool(contract.get("has_practical_scene"))

                        am["kbDocPath"] = (
                            contract.get("segment")
                            or contract.get("archetype_id")
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

        # ✅ Unificar núcleo de VENDAS: passa SEMPRE pelo reply_to_text(...)
        # Isso garante que o Módulo 1 (Conversational Front) seja o "dono" nos 5 primeiros turnos.
        try:
            out = reply_to_text("", _body or "", ctx_local) or {}
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
