# services/conversational_front.py
# Conversational Front v1.0 — MEI Robô
#
# Papel:
# - Intérprete inicial de conversa (vendedor humano)
# - Até MAX_AI_TURNS (hard cap decidido fora)
# - IA entende, responde e devolve metadados simples
#
# Regras:
# - NÃO grava Firestore
# - NÃO chama rotas de envio
# - NÃO gera áudio
# - NÃO executa ações
#
# Saída SEMPRE compatível com o worker
#
# 2026-02

from __future__ import annotations

import logging
from typing import Dict, Any, Tuple
import json
import re
try:
    from services.pack_engine import render_pack_reply  # type: ignore
except Exception:
    render_pack_reply = None  # type: ignore

import os

# Robustez: resolver de KB (seleciona fatos do Firestore/KB sem entupir tokens)
try:
    from services.kb_resolver import build_kb_context  # type: ignore
except Exception:
    build_kb_context = None  # type: ignore

# Guardrails finais de VENDAS (anti-invenção + CTA forte)
try:
    from services.sales_guardrails import apply_sales_guardrails  # type: ignore
except Exception:
    apply_sales_guardrails = None  # type: ignore
try:
    # SDK novo (openai>=1.x)
    from openai import OpenAI  # type: ignore
    _HAS_OPENAI_CLIENT = True
except Exception:
    OpenAI = None  # type: ignore
    _HAS_OPENAI_CLIENT = False
import openai  # compat SDK antigo

# Utilitários puros extraídos (Fase 1A).
# Mantém os mesmos nomes internos usados pelo conversational_front.py.
from services.front_kb import (
    _compose_pack_runtime_compact_reply,
    _compose_pack_runtime_short_reply,
    _platform_apply_slots,
    _try_parse_kb_json,
)
from services.front_utils import (
    _front_fmt_brl_from_cents,
    _truncate,
    extract_json_object_field as _extract_json_object_field,
    extract_json_string_field as _extract_json_string_field,
    has_question as _has_question,
    looks_like_dialogue_stub as _looks_like_dialogue_stub,
    looks_like_technical_output as _looks_like_technical_output,
    normalize_identity_text as _front_normalize_identity_text,
    split_sentences_pt as _split_sentences_pt,
    strip_trailing_question as _strip_trailing_question,
    _split_user_operational_clauses,
    _build_user_operational_seed,
)

# Guards e heurísticas extraídos (Fase 2A).
# Mantém os mesmos nomes internos usados pelo conversational_front.py.
from services.front_guards import (
    _front_has_identity_request_tail,
    _front_identity_request_is_valid,
    _reply_mentions_name_request,
    _audit_operational_reply,
    _has_operational_shape,
    _is_live_operational_reply,
    _is_show_micro_scene,
    _looks_explanatory_reply,
    _looks_explanatory_sentence,
    _looks_like_bureaucratic_stub,
    _observer_voice_score,
    _operational_density_score,
    _operational_progress_score,
    _scene_transition_score,
    _should_force_kb_rebuild,
)

# Superfície final extraída (Fase 3B).
# Mantém os mesmos nomes internos usados pelo conversational_front.py.
from services.front_surface import (
    _apply_response_mode_surface,
    _restore_final_candidate_if_degraded,
    _sync_spoken_after_technical_rescue,
)

# Políticas de tamanho e formatação extraídas (Fase 3A).
# Mantém os mesmos nomes internos usados pelo conversational_front.py.
from services.front_policies import (
    _apply_reply_size_policy,
    _front_clean_free_mode_tail,
    _front_remove_known_open_question_tail,
    _front_trim_free_mode_sentence,
    _front_trim_to_complete_sentence,
    _preserve_technical_direct_reply_size,
    _resolve_reply_size_policy,
    _smart_truncate_text,
)

# Assembly e formatação extraídos (Fase 4A).
# Mantém os mesmos nomes internos usados pelo conversational_front.py.
from services.front_assembly import (
    _drop_abstract_closing,
    _drop_explanatory_opening,
    _compose_operational_reply,
    _derive_ritual_from_scene,
    _front_first_text,
    _front_finalize_reply_surface,
    _front_remove_unsafe_nominal_opening,
    _front_sanitize_lead_name_candidate,
    _heal_algorithmic_micro_scene,
    _humanize_ritual_flow,
    _humanize_scene_flow,
    _is_scene_echo,
    _looks_like_structural_scene_payload,
    _normalize_scene_compare,
    _render_progressive_operational_flow,
    _render_structured_operational_steps,
    _replace_last_question,
    _reply_has_lead_context,
    _sanitize_user_facing_reply,
    _split_scene_steps,
    _stabilize_scene_base,
    _strip_scene_narrator,
    wrap_show_response,
)


# -----------------------------
# Configuração fixa (produto)
# -----------------------------
MODEL = "gpt-4o-mini"
TEMPERATURE = 0.35
FRONT_ANSWER_MAX_TOKENS = int(os.getenv("FRONT_ANSWER_MAX_TOKENS", "350") or 350)  # saída do modelo (econômico, focado em 1 parágrafo)
FRONT_KB_MAX_CHARS = int(os.getenv("FRONT_KB_MAX_CHARS", "2500") or 2500)          # entrada (snapshot)
FRONT_KB_MAX_CHARS_PACKS_V1 = int(
    os.getenv("FRONT_KB_MAX_CHARS_PACKS_V1", "12000") or 12000
)
FRONT_REPLY_MAX_CHARS = int(os.getenv("FRONT_REPLY_MAX_CHARS", "1500") or 1500)      # corte final aumentado para permitir microcenas SHOW

FRONT_FREE_MODE_MAX_TURNS = int(os.getenv("FRONT_FREE_MODE_MAX_TURNS", "5") or 5)
FRONT_TRACE_ENABLED = (os.getenv("FRONT_TRACE_ENABLED", "1") or "1").strip().lower() in ("1", "true", "yes", "on")

# Feature flag (default ON, mas seguro): seleciona fatos do KB para o prompt (menos alucinação, menos tokens)
FRONT_KB_RESOLVER_ENABLED = (os.getenv("FRONT_KB_RESOLVER_ENABLED", "1") or "1").strip().lower() not in ("0","false","off","no")

# Feature flag nova: montagem determinística da resposta final pelo Python.
# Default OFF para não alterar produção antes dos testes.
FRONT_STRUCTURED_ASSEMBLY_ENABLED = (
    os.getenv("FRONT_STRUCTURED_ASSEMBLY_ENABLED", "0") or "0"
).strip().lower() in ("1", "true", "yes", "on")

DEFAULT_TONE = "linguagem simples, direta, educada e comum de conversa no WhatsApp"

def _resolve_tone_hint(state_summary: dict | None, contract: dict | None = None) -> str:
    try:
        raw = ""
        if isinstance(state_summary, dict):
            raw = str(
                state_summary.get("tone_hint")
                or state_summary.get("account_tone_hint")
                or state_summary.get("voice_tone_hint")
                or state_summary.get("style_tone_hint")
                or ""
            ).strip()

        if raw:
            return raw

        if isinstance(contract, dict):
            raw = str(
                contract.get("tone_hint")
                or contract.get("account_tone_hint")
                or contract.get("voice_tone_hint")
                or contract.get("style_tone_hint")
                or ""
            ).strip()

        if raw:
            return raw

        return DEFAULT_TONE

    except Exception:
        return DEFAULT_TONE


_client = OpenAI() if _HAS_OPENAI_CLIENT else None
# -----------------------------
# Enum fechado de tópicos
# -----------------------------
TOPICS = {
    "AGENDA",
    "PRECO",
    "ORCAMENTO",
    "PRODUTO",
    "SERVICOS",
    "PEDIDOS",
    "STATUS",
    "PROCESSO",
    "ATIVAR",
    "WHAT_IS",
    "VOZ",
    "SOCIAL",
    "TRIAL",
    "OTHER",
}

RESPONSE_MODES = {
    "DIRECT",
    "SCENE",
    "DISCOVERY",
    "CLOSING",
}

# -----------------------------
# Funções Utilitárias de Texto
# -----------------------------

def _extract_lead_name_from_current_turn(text: str) -> str:
    """
    Fallback estrutural genérico para nome no turno atual.
    Não usa lista de nomes, profissão ou segmento.
    Serve para o caminho JSON_FAIL_SAFE quando o modelo quebra o JSON.
    """
    try:
        t = str(text or "").strip()
        if not t:
            return ""

        m = re.search(
            r"(?i)\b(?:sou|me chamo|meu nome é|meu nome e)\s+(?:o\s+|a\s+)?([A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-zà-ÿ]{1,30})\b",
            t,
        )
        if m:
            return m.group(1).strip()

        return ""
    except Exception:
        return ""


def _humanize_reply_with_lead_context(
    reply: str,
    lead_name: str = "",
    lead_segment_raw: str = "",
) -> str:
    """
    Humaniza a resposta usando os sinais estruturados já extraídos.
    A variação textual fica com o modelo, evitando frase fixa no código.
    Garante a cópia integral do texto operacional gerado anteriormente.
    """
    try:
        text = str(reply or "").strip()
        if not text:
            return text

        name = str(lead_name or "").strip()
        segment_raw = str(lead_segment_raw or "").strip()

        if not name:
            return text

        lower = text.lower()

        # Verifica se o nome já está na abertura do texto.
        # Se estiver, considera a resposta já humanizada.
        first_chars = lower[:60]
        if name and name.lower() in first_chars and (
            not segment_raw or segment_raw.lower() in lower
        ):
            return text

        system = """
Você ajusta uma mensagem de WhatsApp.

Siga exatamente esta sequência:

1. Escreva uma frase inicial de cumprimento.
2. Inclua o nome do lead na frase inicial.
3. Escreva uma segunda frase demonstrando entusiasmo com a atividade do lead.
4. Pule uma linha.
5. Copie o texto base exatamente como ele é, palavra por palavra.
6. Retorne apenas o texto final.
"""

        user = f"""
[DADOS DO LEAD]
nome: {name}
atividade: {segment_raw}

[TEXTO BASE]
{text}
"""

        upgraded = _call_openai_for_front(
            system=system,
            user=user,
            max_tokens=600,
            temperature=0.35,
        )

        upgraded = _sanitize_user_facing_reply(str(upgraded or "").strip())

        # Normaliza espaços preservando quebras de linha.
        upgraded = re.sub(r"[ \t]{2,}", " ", upgraded).strip()

        if upgraded and _reply_has_lead_context(
            upgraded,
            lead_name=name,
            lead_segment_raw=segment_raw,
        ):
            return upgraded

        return text

    except Exception:
        return str(reply or "").strip()


def _front_structured_doc_content(docs: Dict[str, Any] | None) -> Dict[str, Any]:
    """
    Extrai conteúdo operacional de segmento/archetype já hidratados.
    Prioridade:
    1) subsegmento
    2) archetype
    3) segmento macro
    """
    try:
        docs = docs if isinstance(docs, dict) else {}
        sub_doc = docs.get("subsegment_doc") or {}
        arch_doc = docs.get("archetype_doc") or {}
        seg_doc = docs.get("segment_doc") or {}

        if not isinstance(sub_doc, dict):
            sub_doc = {}
        if not isinstance(arch_doc, dict):
            arch_doc = {}
        if not isinstance(seg_doc, dict):
            seg_doc = {}

        source_doc = sub_doc or arch_doc or seg_doc
        if not source_doc:
            return {}

        source_type = "subsegment" if sub_doc else ("archetype" if arch_doc else "segment")
        source_id = _front_first_text(
            source_doc.get("id"),
            source_doc.get("name"),
            source_doc.get("archetype_id"),
            source_doc.get("segment_id"),
        )

        scene = _front_first_text(
            sub_doc.get("micro_scene_conversational"),
            arch_doc.get("micro_scene_conversational"),
            seg_doc.get("micro_scene_conversational"),
            sub_doc.get("micro_scene"),
            arch_doc.get("micro_scene"),
            seg_doc.get("micro_scene"),
            sub_doc.get("direct_scene"),
            arch_doc.get("direct_scene"),
            seg_doc.get("direct_scene"),
            sub_doc.get("runtime_long_text"),
            arch_doc.get("runtime_long_text"),
            seg_doc.get("runtime_long_text"),
        )

        one_liner = _front_first_text(
            sub_doc.get("one_liner"),
            arch_doc.get("one_liner"),
            seg_doc.get("one_liner"),
        )

        service_noun = _front_first_text(
            sub_doc.get("service_noun"),
            arch_doc.get("service_noun"),
            seg_doc.get("service_noun"),
        )

        conversion_noun = _front_first_text(
            sub_doc.get("conversion_noun"),
            arch_doc.get("conversion_noun"),
            seg_doc.get("conversion_noun"),
        )

        pieces = []
        if scene:
            pieces.append(scene)
        elif one_liner:
            pieces.append(one_liner)

        core = "\n\n".join([p for p in pieces if p]).strip()
        if not core:
            return {}

        return {
            "core": core,
            "hasRichScene": bool(scene),
            "contentSourceType": source_type,
            "contentSourceId": source_id,
            "serviceNoun": service_noun,
            "conversionNoun": conversion_noun,
        }
    except Exception:
        return {}


def _front_platform_pack_content(
    *,
    kb_snapshot_obj: Dict[str, Any] | None,
    platform_segment_profile: Dict[str, Any] | None,
    selected_pack_id: str = "",
    response_mode: str = "DIRECT",
) -> Dict[str, Any]:
    """
    Extrai conteúdo do platform_kb/value_packs_v1 já resolvido.
    Não seleciona segmento por palavra local; usa selected_pack_id e profile já calculados.
    """
    try:
        if not selected_pack_id:
            return {}
        if not isinstance(kb_snapshot_obj, dict) or not kb_snapshot_obj:
            return {}

        material = _platform_pack_material(
            kb_snapshot_obj,
            platform_segment_profile if isinstance(platform_segment_profile, dict) else {},
            selected_pack_id,
        )
        if not isinstance(material, dict):
            return {}

        mode = str(response_mode or "").strip().upper()

        bridge_line = _front_first_text(
            material.get("bridge_line"),
        )

        value_one_liner = _front_first_text(
            material.get("value_one_liner"),
        )

        conversational_scene = _front_first_text(
            material.get("micro_scene_conversational"),
            material.get("micro_scene"),
        )

        if mode == "SCENE":
            main_body = _front_first_text(
                conversational_scene,
                material.get("direct_scene"),
                material.get("runtime_long_text"),
                material.get("runtime_short_reply"),
                material.get("runtime_compact_reply"),
                material.get("micro_scene"),
                material.get("reference_example"),
            )
        else:
            main_body = _front_first_text(
                conversational_scene,
                material.get("runtime_short_reply"),
                material.get("runtime_compact_reply"),
                material.get("direct_scene"),
                material.get("micro_scene"),
                material.get("reference_example"),
                material.get("runtime_long_text"),
            )

        pieces = []
        if value_one_liner and not conversational_scene:
            pieces.append(value_one_liner)
        if bridge_line and not conversational_scene:
            pieces.append(bridge_line)
        if main_body:
            pieces.append(main_body)

        core = "\n\n".join([p for p in pieces if p]).strip()

        if not core:
            return {}

        return {
            "value_one_liner": value_one_liner,
            "bridge_line": bridge_line,
            "micro_scene_conversational": conversational_scene,
            "micro_scene": conversational_scene or str(material.get("micro_scene") or "").strip(),
            "core": core,
            "contentSourceType": "platform_kb_pack",
            "contentSourceId": selected_pack_id,
            "materialSource": str(material.get("material_source") or "").strip(),
        }
    except Exception:
        return {}


def _front_build_structured_assembly_reply(
    *,
    current_reply: str = "",
    real_kb_docs: Dict[str, Any] | None = None,
    kb_snapshot_obj: Dict[str, Any] | None = None,
    platform_segment_profile: Dict[str, Any] | None = None,
    selected_pack_id: str = "",
    response_mode: str = "DIRECT",
    next_step: str = "NONE",
    ai_turns: int = 0,
    lead_name: str = "",
    lead_segment_raw: str = "",
    question_type: str = "broad",
) -> Dict[str, Any]:
    """
    Monta resposta final por fonte estruturada, atrás de feature flag.
    Prioridade:
    1) segmento/subsegmento/archetype hidratado
    2) platform_kb/value_packs_v1
    3) mantém resposta atual
    """
    try:
        if not FRONT_STRUCTURED_ASSEMBLY_ENABLED:
            return {}

        if str(next_step or "").strip().upper() == "SEND_LINK":
            return {}

        mode = str(response_mode or "").strip().upper()
        q_type = str(question_type or "broad").strip().lower()

        allow_structured_long = bool(
            q_type != "simulation"
            and (
                mode == "SCENE"
                or (mode == "DIRECT" and q_type == "broad")
            )
        )

        if not allow_structured_long:
            try:
                logging.info(
                    "[CONVERSATIONAL_FRONT][STRUCTURED_ASSEMBLY_SKIP] mode=%s ai_turns=%s selected_pack_id=%s reason=continuity_or_non_demonstrative",
                    mode,
                    turns,
                    str(selected_pack_id or "").strip().upper(),
                )
            except Exception:
                pass
            return {}

        source = _front_structured_doc_content(real_kb_docs)

        if not source:
            source = _front_platform_pack_content(
                kb_snapshot_obj=kb_snapshot_obj if isinstance(kb_snapshot_obj, dict) else {},
                platform_segment_profile=platform_segment_profile if isinstance(platform_segment_profile, dict) else {},
                selected_pack_id=selected_pack_id,
                response_mode=response_mode,
            )

        core = str((source or {}).get("core") or "").strip()
        if not core:
            return {}

        # Ajuste fino para DIRECT + fallback global do platform_kb:
        #
        # Quando não há documento estruturado do segmento, o pack global ajuda
        # a dar densidade operacional. Porém, se a IA soberana já respondeu
        # diretamente a pergunta específica do lead, essa resposta não deve ser
        # descartada pelo montador estruturado.
        #
        # Assim preservamos:
        # - IA decide e responde a intenção específica do turno.
        # - Código complementa com material confiável do KB.
        # - Sem palavras-chave hardcoded.
        # - Sem lista manual de profissões.
        # - Sem regex para interpretar fala.
        # - Sem alteração de prompt.
        # - Sem nova chamada ao modelo.
        # - Sem afetar SCENE nem docs estruturados.
        try:
            current_clean = _unwrap_front_json_envelope(current_reply) or current_reply
            current_clean = _sanitize_user_facing_reply(str(current_clean or "").strip())

            source_type = str((source or {}).get("contentSourceType") or "").strip()

            if (
                mode == "DIRECT"
                and source_type == "platform_kb_pack"
                and current_clean
                and core
                and q_type != "broad"
                and len(current_clean) < 260
                and len(core) > (len(current_clean) * 2)
                and current_clean not in core
                and core not in current_clean
            ):
                try:
                    logging.info(
                        "[STRUCTURED_CONCAT_TRIGGER] current_len=%s core_len=%s q_type=%s source_type=%s",
                        len(str(current_clean or "")),
                        len(str(core or "")),
                        str(q_type or ""),
                        str(source_type or ""),
                    )
                except Exception:
                    pass

                core = f"{current_clean}\n\n{core}".strip()
        except Exception:
            pass

        # Em SCENE com KB segmentada, não deixar um one_liner curto dominar
        # a resposta final. Quando não há cena rica no documento, preserva o
        # fluxo principal para a IA soberana/fallback operacional trabalhar.
        try:
            if (
                mode == "SCENE"
                and str((source or {}).get("contentSourceType") or "").strip() in ("subsegment", "archetype", "segment")
                and not bool((source or {}).get("hasRichScene"))
                and len(core) < 320
            ):
                return {}
        except Exception:
            pass

        try:
            logging.info(
                "[STRUCTURED_ASSEMBLY_CORE_PROBE] mode=%s q_type=%s selected_pack_id=%s source_type=%s current_len=%s core_len=%s core_head=%s",
                mode,
                q_type,
                str(selected_pack_id or "").strip().upper(),
                str((source or {}).get("contentSourceType") or "").strip(),
                len(str(current_reply or "")),
                len(str(core or "")),
                str(core or "").replace("\n", " ")[:220],
            )
        except Exception:
            pass

        assembled = _humanize_reply_with_lead_context(
            reply=core,
            lead_name=lead_name,
            lead_segment_raw=lead_segment_raw,
        )
        assembled = _unwrap_front_json_envelope(assembled) or assembled
        assembled = _sanitize_user_facing_reply(str(assembled or "").strip())

        try:
            logging.info(
                "[STRUCTURED_ASSEMBLY_ASSEMBLED_PROBE] mode=%s q_type=%s selected_pack_id=%s assembled_len=%s assembled_head=%s",
                mode,
                q_type,
                str(selected_pack_id or "").strip().upper(),
                len(str(assembled or "")),
                str(assembled or "").replace("\n", " ")[:220],
            )
        except Exception:
            pass

        # Se a camada de humanização voltar menor/truncada, preserva o core
        # estruturado já vindo da KB. Não cria frase, não usa palavra-chave e
        # não promove envelope JSON.
        try:
            core_clean = _unwrap_front_json_envelope(core) or core
            core_clean = _sanitize_user_facing_reply(str(core_clean or "").strip())
            if core_clean and len(assembled or "") < min(650, int(len(core_clean) * 0.80)):
                assembled = core_clean
        except Exception:
            pass

        if not assembled:
            return {}

        return {
            "replyText": assembled,
            "spokenText": assembled,
            "assemblyMode": "structured_python",
            "contentSourceType": str(source.get("contentSourceType") or "").strip(),
            "contentSourceId": str(source.get("contentSourceId") or "").strip(),
            "materialSource": str(source.get("materialSource") or "").strip(),
        }
    except Exception:
        return {}
def _front_fs_client():
    """
    Firestore canônico via firebase_admin.
    Best-effort: nunca quebra o front.
    """
    try:
        from services.firebase_admin_init import ensure_firebase_admin  # type: ignore
        ensure_firebase_admin()
        from firebase_admin import firestore as fb_firestore  # type: ignore
        return fb_firestore.client()
    except Exception:
        return None



def _front_get_platform_pricing() -> Dict[str, Any]:
    """
    Fonte única de preço da plataforma.
    """
    try:
        client = _front_fs_client()
        if client is None:
            return {}

        doc = client.collection("platform_pricing").document("current").get()
        if not doc or not doc.exists:
            return {}

        data = doc.to_dict() or {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _front_build_price_facts_block() -> str:
    """
    Monta um bloco factual curto para o prompt/repair,
    sem detector lexical e sem resposta pronta por segmento.
    """
    try:
        data = _front_get_platform_pricing()
        if not isinstance(data, dict) or not data:
            return ""

        starter = ""
        starter_plus = ""
        starter_storage = ""
        starter_plus_storage = ""

        dp = data.get("display_prices") or {}
        if isinstance(dp, dict):
            starter = str(dp.get("starter") or "").strip()
            starter_plus = str(dp.get("starter_plus") or "").strip()

        plans = data.get("plans") or {}
        if isinstance(plans, dict):
            st = plans.get("starter") or {}
            sp = plans.get("starter_plus") or {}

            if isinstance(st, dict):
                if not starter:
                    starter = _front_fmt_brl_from_cents(st.get("price_cents"))
                if st.get("storage_gb") is not None:
                    starter_storage = str(st.get("storage_gb"))

            if isinstance(sp, dict):
                if not starter_plus:
                    starter_plus = _front_fmt_brl_from_cents(sp.get("price_cents"))
                if sp.get("storage_gb") is not None:
                    starter_plus_storage = str(sp.get("storage_gb"))

        if not starter and not starter_plus:
            return ""

        parts = []
        if starter:
            parts.append(f"starter={starter}")
        if starter_plus:
            parts.append(f"starter_plus={starter_plus}")
        if starter_storage:
            parts.append(f"starter_storage_gb={starter_storage}")
        if starter_plus_storage:
            parts.append(f"starter_plus_storage_gb={starter_plus_storage}")

        return "platform_pricing_current: " + ", ".join(parts)
    except Exception:
        return ""


def _front_repair_price_reply(reply_text: str, name_hint: str = "") -> str:
    """
    Repair factual de preço.
    Não usa keyword matching.
    Não depende de segmento.
    """
    try:
        data = _front_get_platform_pricing()
        if not isinstance(data, dict) or not data:
            return str(reply_text or "").strip()

        starter = ""
        starter_plus = ""
        starter_storage = ""
        starter_plus_storage = ""

        dp = data.get("display_prices") or {}
        if isinstance(dp, dict):
            starter = str(dp.get("starter") or "").strip()
            starter_plus = str(dp.get("starter_plus") or "").strip()

        plans = data.get("plans") or {}
        if isinstance(plans, dict):
            st = plans.get("starter") or {}
            sp = plans.get("starter_plus") or {}

            if isinstance(st, dict):
                if not starter:
                    starter = _front_fmt_brl_from_cents(st.get("price_cents"))
                if st.get("storage_gb") is not None:
                    starter_storage = str(st.get("storage_gb"))

            if isinstance(sp, dict):
                if not starter_plus:
                    starter_plus = _front_fmt_brl_from_cents(sp.get("price_cents"))
                if sp.get("storage_gb") is not None:
                    starter_plus_storage = str(sp.get("storage_gb"))

        if not starter and not starter_plus:
            return str(reply_text or "").strip()

        parts = []
        if starter:
            parts.append(f"Starter: {starter}.")
        if starter_plus:
            parts.append(f"Starter Plus: {starter_plus}.")

        if starter_storage or starter_plus_storage:
            mem = "A diferença entre os planos é a memória."
            if starter_storage and starter_plus_storage:
                mem += f" Starter com {starter_storage} GB e Starter Plus com {starter_plus_storage} GB."
            parts.append(mem)

        repaired = " ".join([p for p in parts if p]).strip()
        if not repaired:
            return str(reply_text or "").strip()

        tail = ""
        nm = str(name_hint or "").strip()
        if nm:
            tail = f" {nm}, se quiser, eu te explico qual dos dois encaixa melhor no teu caso."
        else:
            tail = " Se quiser, eu te explico qual dos dois encaixa melhor no teu caso."

        return (repaired + tail).strip()
    except Exception:
        return str(reply_text or "").strip()
# -----------------------------
# Prompt base (alma do vendedor)
# -----------------------------

def _infer_segment_from_text(user_text: str, kb_snapshot: str) -> str:
    """
    Infere segmento somente quando houver sinal explícito e seguro no texto.

    Esta função NÃO deve escolher "o melhor documento disponível" do KB.
    Matching estrutural por conteúdo fica concentrado em _infer_segment_from_docs(),
    que possui validação de compatibilidade com o texto atual.
    """
    try:
        t = str(user_text or "").strip().lower()
        if not t:
            return ""

        def _norm(s: str) -> str:
            # Normalização agnóstica: apenas remove acentos e caracteres especiais
            return _normalize_lookup_key(s)

        norm = _norm(t)

        candidates = []
        sub_candidates = []
        try:
            obj = json.loads(kb_snapshot) if kb_snapshot and kb_snapshot.lstrip().startswith(("{", "[")) else None
        except Exception:
            obj = None

        def _key_matches_text(key: str, text_norm: str) -> bool:
            """
            Matching estrutural e genérico entre chave do KB e texto do lead.
            Não contém palavras-chave de segmento.
            Serve para variações naturais como masculino/feminino/plural
            quando a própria chave do KB já está próxima do texto.
            """
            try:
                key_norm = _norm(str(key or "").replace("__", " ").replace("_", " "))
                if not key_norm or not text_norm:
                    return False
                if key_norm in text_norm:
                    return True

                key_tokens = [t for t in _tokenize_lookup_text(key_norm) if len(t) >= 7]
                text_tokens = [t for t in _tokenize_lookup_text(text_norm) if len(t) >= 7]

                for kt in key_tokens:
                    for tt in text_tokens:
                        common = os.path.commonprefix([kt, tt])
                        if len(common) >= 7:
                            return True
                return False
            except Exception:
                return False

        if isinstance(obj, dict):
            kb_segments = _find_kb_map_anywhere(obj, "kb_segments_v1") or {}
            if isinstance(kb_segments, dict):
                candidates.extend([str(k).strip().lower() for k in kb_segments.keys() if str(k).strip()])

            kb_subsegments = _find_kb_map_anywhere(obj, "kb_subsegments_v1") or {}
            if isinstance(kb_subsegments, dict):
                sub_candidates = [str(k).strip().lower() for k in kb_subsegments.keys() if str(k).strip()]

            svm = _find_kb_map_anywhere(obj, "segment_value_map_v1") or {}
            if isinstance(svm, dict):
                for k, profile in svm.items():
                    key = str(k).strip().lower()
                    if not key:
                        continue

                    candidates.append(key)

                    try:
                        blob = json.dumps(profile or {}, ensure_ascii=False).lower()
                        blob_norm = _norm(blob)

                        # Usa o próprio conteúdo do KB como sinal.
                        # Ex.: key=psicologo pode conter "psicologia" no example_line.
                        if blob_norm and any(tok in norm for tok in _tokenize_lookup_text(blob_norm)):
                            candidates.append(key)
                    except Exception:
                        _preserve_continuity_reply = False
                        pass

        # Primeiro: se o conteúdo do perfil no KB casou com o texto,
        # retorna a chave estrutural do segmento.
        for seg in candidates:
            if _key_matches_text(seg, norm):
                return _norm(seg)

        for sub in sub_candidates:
            if _key_matches_text(sub, norm):
                return sub

        for seg in candidates:
            if _key_matches_text(seg, norm):
                return _norm(seg)

        # Fallback estrutural pelo conteúdo do próprio KB.
        # Continua sem palavras-chave locais: usa somente documentos do Firestore/snapshot.
        try:
            if isinstance(obj, dict):
                svm = _find_kb_map_anywhere(obj, "segment_value_map_v1") or {}
                if isinstance(svm, dict) and svm:
                    m = _keyword_doc_match(user_text, svm) or _best_doc_match(user_text, svm, min_score=2)
                    if m:
                        return _norm(m)
        except Exception:
            pass

        try:
            if isinstance(obj, dict):
                kb_subsegments = _find_kb_map_anywhere(obj, "kb_subsegments_v1") or {}
                if isinstance(kb_subsegments, dict) and kb_subsegments:
                    m = _keyword_doc_match(user_text, kb_subsegments) or _best_doc_match(user_text, kb_subsegments, min_score=3)
                    if m:
                        return str(m or "").strip()
        except Exception:
            pass

        # fallback semântico mínimo para papéis claros
        _txt = (user_text or "").lower()
        if "candidat" in _txt:
            return "politica_atendimento_publico"

        return ""
    except Exception:
        return ""


def _infer_operational_family(user_text: str, raw_profession: str = "") -> str:
    """
    Mantido só por compatibilidade.
    A família operacional deve nascer do KB resolvido, não de listas locais.
    """
    return ""

def _normalize_lookup_key(text: str) -> str:
    try:
        s = str(text or "").strip().lower()
        if not s:
            return ""
        repl = {
            "á": "a", "à": "a", "â": "a", "ã": "a",
            "é": "e", "ê": "e",
            "í": "i",
            "ó": "o", "ô": "o", "õ": "o",
            "ú": "u",
            "ç": "c",
        }
        for a, b in repl.items():
            s = s.replace(a, b)
        s = s.replace("-", "_").replace("/", " ").replace(".", " ")
        s = re.sub(r"\s+", " ", s).strip()
        return s
    except Exception:
        return str(text or "").strip().lower()


def _tokenize_lookup_text(text: str) -> list[str]:
    try:
        # Importante:
        # chaves estruturais do KB costumam vir com "_", "__" e combinações
        # como comercio_varejista__loja_oculos.
        # Para matching semântico estrutural, "_" precisa separar termos,
        # não formar um token único.
        #
        # Isso NÃO cria palavra-chave de segmento.
        # Apenas permite que os termos já existentes no Firestore participem
        # do score de overlap.
        s = _normalize_lookup_key(text).replace("_", " ")
        toks = [tok for tok in re.findall(r"[a-z0-9_]+", s) if len(tok) >= 3]
        return toks
    except Exception:
        return []


def _lookup_token_overlap_score(query: str, candidate: str) -> int:
    try:
        q_tokens = set(_tokenize_lookup_text(query))
        c_tokens = set(_tokenize_lookup_text(candidate.replace("__", " ")))
        if not q_tokens or not c_tokens:
            return 0

        overlap = q_tokens.intersection(c_tokens)
        score = len(overlap)

        # Tolerância morfológica mínima e genérica.
        # Não mapeia profissões/segmentos; só reduz plural simples para
        # melhorar o score quando o KB e o lead usam flexões diferentes.
        def _base(tok: str) -> str:
            t = str(tok or "").strip()
            if len(t) >= 5 and t.endswith("s"):
                return t[:-1]
            return t

        q_base = {_base(tok) for tok in q_tokens}
        c_base = {_base(tok) for tok in c_tokens}
        base_overlap = q_base.intersection(c_base)
        if base_overlap:
            score += max(0, len(base_overlap) - len(overlap))

        q_norm = _normalize_lookup_key(query)
        c_norm = _normalize_lookup_key(candidate.replace("__", " "))
        q_norm_flat = q_norm.replace("_", " ")
        c_norm_flat = c_norm.replace("_", " ")

        if c_norm_flat and c_norm_flat in q_norm_flat:
            score += 2
        elif q_norm_flat and q_norm_flat in c_norm_flat:
            score += 1

        return score
    except Exception:
        return 0


def _best_lookup_key_match(query: str, candidates: list[str], min_score: int = 2) -> str:
    try:
        q = str(query or "").strip()
        if not q or not candidates:
            return ""

        best_key = ""
        best_score = 0

        for cand in candidates:
            c = str(cand or "").strip()
            if not c:
                continue
            score = _lookup_token_overlap_score(q, c)
            if score > best_score:
                best_score = score
                best_key = c

        return best_key if best_score >= min_score else ""
    except Exception:
        return ""


def _iter_doc_text_fragments(value):
    """
    Extrai fragmentos textuais de forma recursiva.
    Não depende de segmento, profissão ou frase pronta.
    """
    try:
        if value is None:
            return

        if isinstance(value, str):
            s = value.strip()
            if s:
                yield s
            return

        if isinstance(value, (int, float, bool)):
            s = str(value).strip()
            if s:
                yield s
            return

        if isinstance(value, list):
            for item in value:
                yield from _iter_doc_text_fragments(item)
            return

        if isinstance(value, dict):
            for k, v in value.items():
                if str(k).strip().lower() in {"id", "doc_id", "created_at", "updated_at", "handoff_format"}:
                    continue
                yield from _iter_doc_text_fragments(v)
            return
    except Exception:
        return


def _collect_doc_texts(doc: Dict[str, Any]) -> list[str]:
    """
    Coleta todo texto útil do documento de forma estrutural.
    """
    try:
        if not isinstance(doc, dict):
            return []
        out = []
        seen = set()
        for part in _iter_doc_text_fragments(doc):
            norm = re.sub(r"\s+", " ", str(part).strip()).lower()
            if not norm or norm in seen:
                continue
            seen.add(norm)
            out.append(str(part).strip())
        return out
    except Exception:
        return []


def _score_query_against_doc(query: str, doc: Dict[str, Any], doc_key: str = "") -> int:
    """
    Score estrutural entre a consulta e o documento.
    Usa apenas sobreposição textual e sinais negativos do próprio banco.
    """
    try:
        q = str(query or "").strip()
        if not q or not isinstance(doc, dict):
            return 0

        score = 0
        parts = _collect_doc_texts(doc)

        if doc_key:
            parts.append(str(doc_key).strip())

        for part in parts:
            score += _lookup_token_overlap_score(q, part)

        neg = doc.get("negative_keywords") or []
        if isinstance(neg, list):
            neg_hits = 0
            for item in neg:
                neg_hits += _lookup_token_overlap_score(q, str(item or ""))
            if neg_hits:
                score -= neg_hits

        return max(score, 0)
    except Exception:
        return 0


def _best_doc_match(query: str, docs_map: Dict[str, Any], min_score: int = 2) -> str:
    """
    Escolhe o melhor documento do KB pelo conteúdo real do doc.
    """
    try:
        q = str(query or "").strip()
        if not q or not isinstance(docs_map, dict):
            return ""

        best_key = ""
        best_score = 0

        for key, doc in docs_map.items():
            if not isinstance(doc, dict):
                continue
            score = _score_query_against_doc(q, doc, str(key))
            if score > best_score:
                best_score = score
                best_key = str(key).strip()

        if best_score >= min_score:
            return best_key
        return ""
    except Exception:
        return ""




def _keyword_doc_match(query: str, docs_map: Dict[str, Any]) -> str:
    """
    Matching determinístico de alta confiança usando apenas o campo `keywords`
    vindo do Firestore.

    Não contém palavras-chave locais.
    Não conhece segmentos, profissões ou exemplos específicos.
    Não substitui o score atual: apenas antecipa matches explícitos do KB.
    """
    try:
        q = _normalize_lookup_key(query).replace("_", " ")
        q = re.sub(r"\s+", " ", q).strip()
        if not q or not isinstance(docs_map, dict):
            return ""

        for key, doc in docs_map.items():
            if not isinstance(doc, dict):
                continue

            keywords = doc.get("keywords") or []
            if isinstance(keywords, str):
                keywords = [keywords]
            if not isinstance(keywords, list):
                continue

            for item in keywords:
                kw = _normalize_lookup_key(item).replace("_", " ")
                kw = re.sub(r"\s+", " ", kw).strip()
                if len(kw) < 3:
                    continue

                pattern = r"(?<![a-z0-9])" + re.escape(kw) + r"(?![a-z0-9])"
                if re.search(pattern, q):
                    return str(key or "").strip()

        return ""
    except Exception:
        return ""

def _doc_identity_is_compatible_with_current_text(
    *,
    user_text: str,
    doc: Dict[str, Any],
    doc_key: str = "",
    min_score: int = 3,
) -> bool:
    """
    Valida se um documento do KB é realmente compatível com o texto atual.

    Não usa palavras-chave por segmento.
    Não força profissão.
    Não cria fallback específico.

    Objetivo:
    - impedir que um segmento declarado no turno atual caia em outro subsegmento
      apenas por aproximação fraca;
    - permitir que, sem subsegmento específico, o fluxo use o KB global/plataforma.
    """
    try:
        q = str(user_text or "").strip()
        if not q or not isinstance(doc, dict):
            return False

        # Validação de identidade deve usar apenas campos identitários.
        #
        # Não usa palavras-chave de segmento.
        # Não tenta interpretar formas de fala do lead.
        # Não usa microcena, ritual operacional ou textos longos.
        #
        # Motivo:
        # campos operacionais contêm termos genéricos como "cliente",
        # "agenda" e "atendimento", que podem validar falsamente um
        # subsegmento incompatível escolhido por similaridade.
        identity_doc = {
            "id": doc.get("id"),
            "name": doc.get("name"),
            "title": doc.get("title"),
            "label": doc.get("label"),
            "keywords": doc.get("keywords"),
            "one_liner": doc.get("one_liner"),
            "segment": doc.get("segment"),
            "segment_id": doc.get("segment_id"),
            "subsegment": doc.get("subsegment"),
            "subsegment_id": doc.get("subsegment_id"),
            "archetype_id": doc.get("archetype_id"),
            "service_noun": doc.get("service_noun"),
            "customer_noun": doc.get("customer_noun"),
        }

        score = _score_query_against_doc(q, identity_doc, str(doc_key or ""))
        return score >= int(min_score)
    except Exception:
        return False



def _clear_incompatible_kb_context_for_current_text(
    *,
    kb_snapshot: str,
    user_text: str,
    kb_context: Dict[str, Any],
    segment_hint: str = "",
) -> Dict[str, Any]:
    """
    Remove ancoragem segmentada incompatível com o texto atual.

    Não decide por profissão.
    Não usa palavras-chave de segmento.
    Não escolhe resposta pronta.

    Objetivo:
    - se o resolver trouxe um subsegmento errado, não deixar esse contrato contaminar
      a geração;
    - preservar sinais globais úteis do platform_kb, como intent_hint, pack_id,
      signup_url e fatos gerais.
    """
    try:
        ctx = dict(kb_context or {})
        if not ctx:
            return ctx

        sub_hint = str(
            ctx.get("effective_subsegment")
            or ctx.get("subsegment_hint")
            or ""
        ).strip().lower()

        if not sub_hint:
            return ctx

        # Continuidade: se o resolver trouxe o mesmo subsegmento já persistido
        # no lead, não limpar apenas porque o texto atual é genérico.
        # Ex.: "Onde vejo este atendimento depois?" deve herdar o segmento
        # anterior, não reabrir disputa por similaridade textual.
        try:
            persisted_hint = _normalize_lookup_key(segment_hint)
            resolved_hint = _normalize_lookup_key(sub_hint)
            if (
                persisted_hint
                and resolved_hint
                and (
                    persisted_hint == resolved_hint
                    or persisted_hint in resolved_hint
                    or resolved_hint in persisted_hint
                )
            ):
                return ctx
        except Exception:
            pass

        raw = str(kb_snapshot or "").strip()
        if not raw or not (raw.startswith("{") or raw.startswith("[")):
            return ctx

        obj = json.loads(raw)
        kb_sub = _find_kb_map_anywhere(obj, "kb_subsegments_v1")
        if not isinstance(kb_sub, dict) or not kb_sub:
            return ctx

        doc = kb_sub.get(sub_hint) or {}
        if isinstance(doc, dict) and _doc_identity_is_compatible_with_current_text(
            user_text=user_text,
            doc=doc,
            doc_key=sub_hint,
            min_score=2,
        ):
            return ctx

        # Contrato segmentado incompatível: limpa a ancoragem de segmento e
        # todo material operacional derivado dela.
        #
        # Preserva apenas sinais globais úteis do resolver. Isso impede que
        # uma microcena de subsegmento errado continue contaminando a geração
        # depois que a identidade foi reprovada.
        for key in (
            "subsegment_hint",
            "effective_subsegment",
            "segment_hint",
            "segment_id",
            "archetype_id",
            "segment_profile",
            "operational_family",
            "operational_reference",
            "segment_reference_example",
            "pack_micro_scene",
            "micro_scene",
            "micro_scene_conversational",
            "reference_example",
            "practical_scene",
            "direct_scene",
            "runtime_short_reply",
            "runtime_long_text",
            "has_reference_example",
            "has_practical_scene",
            "hydrated_from_docs",
            "micro_scene_allowed",
            "response_mode",
        ):
            ctx.pop(key, None)

        ctx["segment_context_status"] = "cleared_incompatible_for_current_text"
        return ctx
    except Exception:
        return dict(kb_context or {})



def _kb_context_segment_was_cleared(kb_context: Dict[str, Any]) -> bool:
    """
    Sinaliza que o resolver trouxe uma ancoragem segmentada incompatível
    e que ela foi removida para este turno.

    Não decide segmento.
    Não usa palavras-chave.
    Apenas impede re-hidratação do contrato removido.
    """
    try:
        return str((kb_context or {}).get("segment_context_status") or "").strip() == "cleared_incompatible_for_current_text"
    except Exception:
        return False

def _family_to_pack_id(family: str) -> str:
    f = str(family or "").strip().lower()
    if f == "agenda":
        return "PACK_A_AGENDA"
    if f == "pedidos":
        return "PACK_C_PEDIDOS"
    if f == "servicos":
        return "PACK_B_SERVICOS"
    if f == "status":
        return "PACK_D_STATUS"
    if f == "triagem":
        return "PACK_B_SERVICOS"
    return ""

def _stable_variant_index(seed_text: str, modulo: int) -> int:
    try:
        s = str(seed_text or "").strip()
        if modulo <= 0:
            return 0
        total = 0
        for ch in s:
            total += ord(ch)
        return total % modulo
    except Exception:
        return 0


def _kb_get_reference_example(kb_snapshot: str, segment: str, pack_id: str) -> str:
    """Pull reference_example for segment+pack from kb_snapshot (JSON if possible; heuristic fallback)."""
    try:
        if not kb_snapshot or not segment or not pack_id:
            return ""
        # JSON first (preferred)
        try:
            obj = json.loads(kb_snapshot) if kb_snapshot.lstrip().startswith(("{","[")) else None
        except Exception:
            obj = None
        if isinstance(obj, dict):
            # KB novo: subsegmento/segmento
            kb_sub = obj.get("kb_subsegments_v1") or {}
            kb_seg = obj.get("kb_segments_v1") or {}
            seg_key = str(segment or "").strip().lower()

            if isinstance(kb_sub, dict) and seg_key in kb_sub:
                one_liner = str((kb_sub.get(seg_key) or {}).get("one_liner") or "").strip()
                if one_liner:
                    return one_liner

            if isinstance(kb_seg, dict) and seg_key in kb_seg:
                one_liner = str((kb_seg.get(seg_key) or {}).get("one_liner") or "").strip()
                if one_liner:
                    return one_liner

            m = obj.get("segment_value_map_v1") if "segment_value_map_v1" in obj else obj
            if isinstance(m, dict) and segment in m:
                tokens = (m.get(segment) or {}).get("tokens") or {}
                p = tokens.get(pack_id) or {}
                ex = p.get("reference_example") or ""
                return str(ex).strip()

        # Heuristic fallback: works with common Firestore export / pretty prints like:
        # dentista (map) ... PACK_A_AGENDA ... reference_example (string) ... "Pra consultório..."
        kb = kb_snapshot
        kb_low = kb.lower()
        seg_low = (segment or "").lower()
        pack_low = (pack_id or "").lower()

        seg_pos = kb_low.find(seg_low)
        if seg_pos < 0:
            # last resort: search whole snapshot for pack+reference_example
            seg_pos = 0

        # Limit scan window to keep it fast
        window = kb[seg_pos: seg_pos + 5000]

        # Find pack block inside the window
        w_low = window.lower()
        p_pos = w_low.find(pack_low)
        if p_pos >= 0:
            window2 = window[p_pos: p_pos + 2500]
        else:
            window2 = window

        # Find 'reference_example' within the narrowed window
        w2_low = window2.lower()
        e_pos = w2_low.find("reference_example")
        if e_pos < 0:
            return ""

        tail = window2[e_pos: e_pos + 1200]

        # Strategy:
        # 1) Prefer quoted text after reference_example
        q = re.search(r'"([^\n\"]{12,240})"', tail, re.DOTALL)
        if q:
            return q.group(1).strip()

        # 2) Otherwise, take the next meaningful non-empty line that is not '(string)/(map)/(array)'
        lines = [ln.strip() for ln in tail.splitlines()]
        for ln in lines[1:10]:
            if not ln:
                continue
            if ln.startswith("(") and ln.endswith(")"):
                continue
            if ln.lower() in ("string", "map", "array"):
                continue
            if "(string" in ln.lower() or "(map" in ln.lower() or "(array" in ln.lower():
                continue
            # strip trailing type hints like '(string)'
            ln = re.sub(r"\(string\)\s*$", "", ln, flags=re.IGNORECASE).strip()
            if len(ln) >= 12:
                return ln
        return ""
    except Exception:
        return ""




def _kb_get_pack_runtime_short(kb_snapshot: str, pack_id: str) -> dict:
    try:
        out = {}
        if not kb_snapshot or not pack_id:
            return out
        try:
            obj = json.loads(kb_snapshot) if kb_snapshot.lstrip().startswith(("{", "[")) else None
        except Exception:
            obj = None
        if not isinstance(obj, dict):
            return out
        packs = obj.get("value_packs_v1") or {}
        pack = packs.get((pack_id or "").strip().upper()) or {}
        runtime_short = pack.get("runtime_short") or {}
        if not isinstance(runtime_short, dict):
            return out
        for k in ("micro_scene", "micro_scene_conversational", "value_one_liner", "bridge_line"):
            v = str(runtime_short.get(k) or "").strip()
            if v:
                out[k] = v
        if out.get("micro_scene_conversational") or out.get("micro_scene"):
            out["micro_scene"] = out.get("micro_scene_conversational") or out.get("micro_scene")
        return out
    except Exception:
        return {}



def _kb_get_micro_scene(kb_snapshot: str, pack_id: str) -> str:
    """Pull runtime_short.micro_scene for a given pack from kb_snapshot."""
    try:
        if not kb_snapshot or not pack_id:
            return ""
        try:
            obj = json.loads(kb_snapshot) if kb_snapshot.lstrip().startswith(("{", "[")) else None
        except Exception:
            obj = None
        if isinstance(obj, dict):
            # KB novo: se houver archetypes com micro_scene canônica do fluxo
            kb_arch = obj.get("kb_archetypes_v1") or {}
            if isinstance(kb_arch, dict):
                arch_by_pack = {
                    "PACK_A_AGENDA": ("servico_agendado", "servico_agendado_com_encaixe"),
                    "PACK_B_SERVICOS": ("comercio_catalogo_direto", "comercio_consultivo_presencial", "servico_tecnico_orcamento", "servico_tecnico_visita", "atendimento_profissional_triagem"),
                    "PACK_C_PEDIDOS": ("alimentacao_pedido",),
                    "PACK_D_STATUS": (),
                }
                for aid in arch_by_pack.get((pack_id or "").strip().upper(), ()):
                    d = kb_arch.get(aid) or {}
                    if isinstance(d, dict):
                        ms = str(d.get("micro_scene") or "").strip()
                        if ms:
                            return ms

            packs = obj.get("value_packs_v1") or {}
            if isinstance(packs, dict):
                p = packs.get((pack_id or "").strip().upper()) or {}
                runtime_short = p.get("runtime_short") or {}
                ms = str(
                    runtime_short.get("micro_scene_conversational")
                    or runtime_short.get("micro_scene")
                    or ""
                ).strip()
                if ms:
                    return ms
        return ""
    except Exception:
        return ""


def _extract_value_line(reply_text: str) -> str:
    """
    Pega a frase de valor antes do 'Na prática:' para reaproveitar o melhor do LLM
    sem deixar a parte prática ficar genérica.
    """
    try:
        r = (reply_text or "").strip()
        if not r:
            return ""
        low = r.lower()
        idx = low.find("na prática:")
        if idx != -1:
            r = r[:idx].strip()
        # pega só a primeira frase
        m = re.split(r"(?<=[\.\!\?])\s+", r, maxsplit=1)
        base = (m[0] if m else r).strip()
        return base.rstrip(".!?").strip()
    except Exception:
        return (reply_text or "").strip()





def _needs_discovery_question(
    topic: str,
    confidence: str,
    operational_family: str,
    ai_turns: int,
    effective_segment: str = "",
    needs_clarify: str = "",
    clarify_q: str = "",
    operational_reference: str = "",
    reference_example: str = "",
    reply_text: str = "",
) -> bool:
    """
    Decide se devemos abrir UMA pergunta de discovery.
    Regra arquitetural:
    - não depender de palavras-chave de negócio;
    - usar os sinais já produzidos pela IA e pelo KB;
    - só perguntar quando realmente ainda não houver operação suficiente
      para responder com utilidade.
    """
    try:
        topic = str(topic or "").upper()
        confidence = str(confidence or "").lower()
        operational_family = str(operational_family or "").strip()
        seg = str(effective_segment or "").strip().lower()
        needs_clarify = str(needs_clarify or "").strip().lower()
        clarify_q = str(clarify_q or "").strip()
        operational_reference = str(operational_reference or "").strip()
        reference_example = str(reference_example or "").strip()
        reply_text = str(reply_text or "").strip()

        if ai_turns > 0:
            return False

        # Se já temos ancoragem forte suficiente, não abrir discovery.
        # Mas segmento sozinho não basta se ainda não houver cena/exemplo/fluxo.
        if operational_reference:
            return False
        if reference_example:
            return False
        if seg and operational_family:
            return False

        # Se a IA já produziu um reply aproveitável, também não perguntar.
        if reply_text:
            return False

        # Clarify explícito do modelo é o sinal mais forte para permitir 1 pergunta.
        if needs_clarify == "yes":
            return True
        if clarify_q:
            return True

        # Discovery só entra quando a clarificação é realmente necessária.
        # Se ainda estamos no turno 0 e não há ancoragem, mas o caso é apenas
        # amplo (não colapsado), preferimos deixar o front tentar responder.
        if needs_clarify == "yes":
            return True

        if clarify_q:
            # Clarify_q sozinho não basta para mandar discovery no turno 0.
            # Ele pode ser só excesso de cautela do modelo.
            if ai_turns > 0:
                return True
            return False

        return False
    except Exception:
        return False

def _should_allow_question(*, user_text: str, kb_context: Dict[str, Any], reply_text: str, understanding: Dict[str, Any], decider: Dict[str, Any]) -> bool:
    try:
        rt = str(reply_text or "").strip()
        if "?" not in rt:
            return False

        response_mode = str(
            (decider or {}).get("response_mode")
            or (decider or {}).get("responseMode")
            or (understanding or {}).get("response_mode")
            or (understanding or {}).get("responseMode")
            or ""
        ).strip().upper()

        if response_mode == "DISCOVERY":
            return True

        question_type = str((decider or {}).get("questionType") or "").strip().lower()
        if question_type in ("clarify", "name", "segment", "link_permission"):
            return True

        topic = str((understanding or {}).get("topic") or "").strip().upper()
        confidence = str((understanding or {}).get("confidence") or "").strip().lower()
        wants_link = bool((kb_context or {}).get("wants_link_explicit"))
        needs_segment = bool((kb_context or {}).get("needs_segment_discovery"))
        needs_name = bool((kb_context or {}).get("needs_name_discovery"))

        # 1) ambiguidade real
        # OTHER com confidence medium não autoriza pergunta por si só.
        if confidence == "low":
            return True
        if topic in ("OTHER", "") and confidence in ("low", ""):
            return True

        # 2) descoberta de segmento/nome
        if needs_segment:
            return True
        if needs_name:
            return True

        # 3) abertura comercial clara para link/ativação
        if wants_link:
            return True

        return False
    except Exception:
        return False


def _unwrap_front_json_envelope(text: str) -> str:
    """
    Blindagem final: impede que o envelope JSON estruturado seja enviado
    como mensagem ao WhatsApp. Extrai somente o campo replyText quando
    a resposta final ainda vier no formato {"response_mode":..., "replyText":...}.
    """
    try:
        s = str(text or "").strip()
        if not s:
            return ""

        if s.startswith("```"):
            s = re.sub(r"^\s*```(?:json)?\s*", "", s, flags=re.I).strip()
            s = re.sub(r"\s*```\s*$", "", s).strip()

        if not s.startswith("{"):
            return str(text or "").strip()

        try:
            obj = json.loads(s)
            if isinstance(obj, dict):
                rt = str(obj.get("replyText") or obj.get("reply") or obj.get("mensagem") or "").strip()
                if rt:
                    return _sanitize_user_facing_reply(rt)
        except Exception:
            pass

        rt = _extract_json_string_field(s, "replyText")
        if not rt:
            rt = _extract_json_string_field(s, "reply")
        if not rt:
            rt = _extract_json_string_field(s, "mensagem")
        if rt:
            return _sanitize_user_facing_reply(rt)

        if '"replyText"' in s or '"response_mode"' in s or '"understanding"' in s:
            return ""

        return str(text or "").strip()
    except Exception:
        return str(text or "").strip()




def _sanitize_front_result_payload(payload: Any) -> Any:
    """
    Blindagem definitiva no ponto de saída do conversational_front.
    Independentemente do caminho executado (inclusive
    front_structured_python_assembly), garante que os campos replyText
    e spokenText contenham somente o texto final para o usuário.
    """
    try:
        if not isinstance(payload, dict):
            return payload

        raw_reply = payload.get("replyText")
        raw_spoken = payload.get("spokenText")

        clean_reply = _unwrap_front_json_envelope(raw_reply)
        clean_spoken = _unwrap_front_json_envelope(raw_spoken)

        if clean_reply:
            payload["replyText"] = clean_reply
            payload["spokenText"] = clean_spoken or clean_reply
            return payload

        # Se não foi possível extrair e o conteúdo parece um envelope JSON,
        # evita que o JSON bruto seja enviado ao WhatsApp.
        probe = str(raw_reply or "").strip()
        if (
            probe.startswith("{")
            and (
                '"replyText"' in probe
                or '"response_mode"' in probe
                or '"understanding"' in probe
            )
        ):
            fallback = "Me conta um pouco melhor o seu cenário."
            payload["replyText"] = fallback
            payload["spokenText"] = fallback
            payload["shouldEnd"] = False

        return payload
    except Exception:
        return payload

def _front_response_json_schema() -> Dict[str, Any]:
    return {
        "name": "conversational_front_response",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "response_mode": {
                    "type": "string",
                    "enum": ["DIRECT", "SCENE", "DISCOVERY", "CLOSING"],
                },
                "understanding": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "topic": {"type": "string"},
                        "confidence": {
                            "type": "string",
                            "enum": ["high", "medium", "low"],
                        },
                        "question_type": {
                            "type": "string",
                            "enum": ["broad", "punctual", "simulation"],
                        },
                    },
                    "required": ["topic", "confidence", "question_type"],
                },
                "nextStep": {
                    "type": "string",
                    "enum": ["SEND_LINK", "NONE"],
                },
                "replyText": {"type": "string"},
            },
            "required": ["response_mode", "understanding", "nextStep", "replyText"],
        },
    }


def _merge_identity_fields_from_raw_ai_payload(
    data: Dict[str, Any],
    raw: str,
) -> Dict[str, Any]:
    """
    Recupera campos estruturados do JSON textual quebrado.
    Não usa palavras-chave de profissão nem frases do usuário.
    Lê apenas campos que o próprio modelo já tentou devolver.
    """
    try:
        out = data if isinstance(data, dict) else {}
        understanding = out.get("understanding") if isinstance(out.get("understanding"), dict) else {}

        def _first(*vals: Any) -> str:
            for v in vals:
                ss = str(v or "").strip()
                if ss:
                    return ss
            return ""

        lead_name = _first(
            out.get("lead_name"),
            out.get("leadName"),
            understanding.get("lead_name"),
            understanding.get("leadName"),
            _extract_json_string_field(raw, "lead_name"),
            _extract_json_string_field(raw, "leadName"),
        )

        lead_segment = _first(
            out.get("lead_segment"),
            out.get("leadSegment"),
            out.get("segmentHint"),
            understanding.get("lead_segment"),
            understanding.get("leadSegment"),
            understanding.get("segmentHint"),
            _extract_json_string_field(raw, "lead_segment"),
            _extract_json_string_field(raw, "leadSegment"),
            _extract_json_string_field(raw, "segmentHint"),
        )

        lead_segment_raw = _first(
            out.get("lead_segment_raw"),
            out.get("leadSegmentRaw"),
            understanding.get("lead_segment_raw"),
            understanding.get("leadSegmentRaw"),
            _extract_json_string_field(raw, "lead_segment_raw"),
            _extract_json_string_field(raw, "leadSegmentRaw"),
            lead_segment,
        )

        if lead_name:
            out["lead_name"] = lead_name
            out["leadName"] = lead_name

        if lead_segment:
            out["lead_segment"] = lead_segment
            out["leadSegment"] = lead_segment

        if lead_segment_raw:
            out["lead_segment_raw"] = lead_segment_raw
            out["leadSegmentRaw"] = lead_segment_raw

        if isinstance(understanding, dict):
            if lead_name:
                understanding["leadName"] = lead_name
            if lead_segment:
                understanding["segmentHint"] = lead_segment
            if lead_segment_raw:
                understanding["leadSegmentRaw"] = lead_segment_raw
            out["understanding"] = understanding

        return out
    except Exception:
        return data if isinstance(data, dict) else {}


def _salvage_free_mode_payload(raw: str) -> Dict[str, Any]:
    try:
        reply = _extract_json_string_field(raw, "replyText")
        if not reply:
            reply = _extract_json_string_field(raw, "mensagem")
        spoken = _extract_json_string_field(raw, "spokenText")
        next_step = _extract_json_string_field(raw, "nextStep") or "NONE"
        understanding = _extract_json_object_field(raw, "understanding")
        topic = str((understanding or {}).get("topic") or "").strip().upper() or "OTHER"
        confidence = str((understanding or {}).get("confidence") or "").strip().lower() or "medium"
        if reply:
            payload = {
                "response_mode": _normalize_response_mode(_extract_json_string_field(raw, "response_mode")) or "DIRECT",
                "replyText": reply,
                "spokenText": spoken or reply,
                "understanding": {
                    "topic": topic,
                    "confidence": confidence,
                    "question_type": str((understanding or {}).get("question_type") or "broad").strip().lower(),
                },
                "nextStep": next_step,
            }
            return _merge_identity_fields_from_raw_ai_payload(payload, raw)
        return {}
    except Exception:
        return {}


def _build_free_mode_family_hint(user_text: str, effective_segment: str = "") -> str:
    """
    Mantido apenas por compatibilidade.
    Não injeta direção textual fixa no prompt.
    """
    return ""


def _parse_free_mode_text_response(
    raw: str,
    *,
    topic_hint: str = "OTHER",
    confidence_hint: str = "medium",
) -> Dict[str, Any]:
    """
    Em free_mode, a IA pode devolver texto livre.
    Este helper transforma texto puro em payload compatível com o worker.
    """
    try:
        txt = _sanitize_user_facing_reply(raw)
        txt = re.sub(r"\s{2,}", " ", txt).strip()

        if not txt:
            return {}

        topic = str(topic_hint or "OTHER").strip().upper() or "OTHER"
        if topic not in TOPICS:
            topic = "OTHER"

        if current_turn_topic_reset:
            topic = "OTHER"
            intent = "OTHER"
            if response_mode == "SCENE":
                response_mode = "DIRECT"

        confidence = str(confidence_hint or "medium").strip().lower() or "medium"
        if confidence not in ("high", "medium", "low"):
            confidence = "medium"

        return {
            "response_mode": "DIRECT",
            "replyText": txt,
            "spokenText": txt,
            "understanding": {
                "topic": topic,
                "confidence": confidence,
            },
            "nextStep": "NONE",
            "shouldEnd": False,
            "nameUse": "none",
            "prefersText": False,
            "replySource": "front_free_text",
        }
    except Exception:
        return {}


def _build_scene_hint_block(*, family_hint: str, micro_scene: str, reference_example: str, operational_reference: str) -> str:
    """
    Enxuga contexto adicional de cena antes de injetar no system_prompt.
    Prioridade:
    1) operational_reference
    2) reference_example + micro_scene
    3) micro_scene
    4) reference_example
    family_hint entra só como apoio, sem duplicar a mesma cena.
    """
    try:
        fh = str(family_hint or "").strip()
        ms = str(micro_scene or "").strip()
        ex = str(reference_example or "").strip()
        ps = str(operational_reference or "").strip()

        parts = []

        if fh:
            parts.append("Direção operacional prioritária:\n" + fh)

        if ps:
            parts.append("Cena preferencial do KB:\n" + ps)
        else:
            if ex and ms:
                parts.append("Referência de exemplo do segmento:\n" + ex)
                parts.append("Microcena sugerida:\n" + ms)
            elif ms:
                parts.append("Microcena sugerida:\n" + ms)
            elif ex:
                parts.append("Referência de exemplo do segmento:\n" + ex)

        return "\n\n".join([p for p in parts if p]).strip()
    except Exception:
        return ""




def compress_kb_context(kb_text: str, limit: int = 900) -> str:
    """
    Compacta o contexto do Firestore para reduzir ruído.
    Mantém apenas partes mais informativas.
    """

    if not kb_text:
        return ""

    kb_text = kb_text.strip()

    if len(kb_text) <= limit:
        return kb_text

    # quebra em linhas
    parts = [p.strip() for p in kb_text.split("\n") if p.strip()]

    # remove duplicações simples
    seen = set()
    filtered = []

    for p in parts:
        key = p.lower()[:80]
        if key not in seen:
            seen.add(key)
            filtered.append(p)

    compact = " ".join(filtered)

    return compact[:limit]


def build_dynamic_context_frame(segment: str, kb_text: str) -> str:
    """
    Cria enquadramento cognitivo para a IA
    sem usar palavras-chave ou scripts.
    """

    segment = segment or "negócio local"

    return (
        f"O usuário descreve uma situação comum de um {segment}. "
        "A resposta deve mostrar como o robô ajuda na conversa real com o cliente. "
        "Mostre de forma natural o que acontece quando o cliente manda mensagem "
        "e como o robô conduz o próximo passo. "
        "Evite explicar software; descreva a cena prática. "
        f"\n\nContexto disponível:\n{kb_text}"
    )


def _build_user_scene_block(*, operational_reference: str, reference_example: str, kb_section: str, kb_compact: str) -> str:
    """
    Enxuga o payload do usuário para evitar duplicação entre:
    - operational_reference
    - reference_example
    - KB Context
    - KB SNAPSHOT COMPACTO
    Mantém fallback do snapshot, mas prioriza o que já foi selecionado.
    """
    try:
        ps = str(operational_reference or "").strip()
        ex = str(reference_example or "").strip()
        ks = str(kb_section or "").strip()
        kc = str(kb_compact or "").strip()

        parts = []

        if ps:
            parts.append("[REGRA CRÍTICA DE GERAÇÃO]\nUse a CENA PREFERENCIAL DO KB como apoio quando a IA decidir demonstrar valor prático.\n- A decisão de usar microcena é da IA, não é obrigatória.\n- Se a pergunta for institucional, direta ou exploratória, responda primeiro com clareza.\n- Use o KB como fonte de verdade, nunca como roteiro obrigatório.\n- Nunca invente etapas fora do KB.\n- O exemplo serve apenas como referência de tom, não de comportamento.")
            parts.append(f"[CENA PREFERENCIAL]\n{ps}")
        elif ex:
            parts.append(f"[EXEMPLO DO SEGMENTO]\n{ex}")
        else:
            if ex:
                parts.append(f"[EXEMPLO DO SEGMENTO]\n{ex}")

        if ks:
            parts.append(ks)

        if kc:
            parts.append("[KB SNAPSHOT COMPACTO — FALLBACK]\n" + kc)

        return "\n\n".join([p for p in parts if p]).strip()
    except Exception:
        return str(kb_compact or "").strip()


def _de_genericize_free_mode_text(text: str) -> str:
    # IA TOTAL: não reescrever semântica por regex.
    # Mantemos só uma higiene textual mínima.
    try:
        t = str(text or "").strip()
        if not t:
            return ""
        t = re.sub(r"\s+\?", "?", t)
        t = re.sub(r"\.\s*\.", ".", t)
        t = re.sub(r"\s+,", ",", t)
        t = re.sub(r"\s+\.", ".", t)
        t = re.sub(r"\s{2,}", " ", t)
        t = re.sub(r"\n{3,}", "\n\n", t)
        return t.strip(" \n")
    except Exception:
        return str(text or "").strip()


def _has_strong_kb_anchor(
    *,
    kb_context: Dict[str, Any],
    effective_segment: str,
    operational_family: str,
    operational_reference: str,
    reference_example: str,
    selected_pack_id: str,
) -> bool:
    """
    Mede se o banco novo já deu base suficiente para a IA responder
    sem cair em fallback genérico.
    Não decide texto. Só mede força de ancoragem.
    """
    try:
        score = 0
        if str(effective_segment or "").strip():
            score += 2
        if str((kb_context or {}).get("subsegment_hint") or "").strip():
            score += 2
        if str((kb_context or {}).get("archetype_id") or "").strip():
            score += 2
        if str(operational_family or "").strip():
            score += 1
        if str(operational_reference or "").strip():
            score += 3
        if str(reference_example or "").strip():
            score += 2
        if str(selected_pack_id or "").strip():
            score += 1
        return score >= 6
    except Exception:
        return False


def _preferred_topic_from_kb(*, kb_context: Dict[str, Any], current_topic: str) -> str:
    """
    Determina topic preferido com base no KB.
    Evita que casos ancorados caiam em OTHER.
    """
    try:
        topic = str(current_topic or "").strip().upper() or "OTHER"
        intent_hint = str((kb_context or {}).get("intent_hint") or "").strip().upper()
        if intent_hint in TOPICS and intent_hint not in ("OTHER", ""):
            return intent_hint

        archetype = str((kb_context or {}).get("archetype_id") or "").strip().lower()
        primary_goal = str(
            ((kb_context or {}).get("segment_profile") or {}).get("primary_goal") or ""
        ).lower()

        # prioridade por archetype
        if archetype == "servico_tecnico_visita":
            return "PROCESSO"

        if archetype in ("comercio_catalogo_direto", "alimentacao_pedido"):
            return "PRODUTO"

        if archetype == "comercio_consultivo_presencial":
            return "SERVICOS"

        if archetype in ("servico_agendado", "servico_agendado_com_encaixe"):
            return "AGENDA"

        if "visita" in primary_goal:
            return "PROCESSO"

        if "compra" in primary_goal or "reserva" in primary_goal:
            return "PRODUTO"

        if "agendar" in primary_goal or "marcar" in primary_goal:
            return "AGENDA"

        family = str((kb_context or {}).get("operational_family") or "").strip().lower()
        fam_map = {
            "agenda": "AGENDA",
            "pedidos": "PEDIDOS",
            "servicos": "SERVICOS",
            "triagem": "PROCESSO",
            "status": "STATUS",
        }
        if family in fam_map:
            return fam_map[family]

        pack_id = str((kb_context or {}).get("pack_id") or "").strip().upper()
        pack_map = {
            "PACK_A_AGENDA": "AGENDA",
            "PACK_B_SERVICOS": "SERVICOS",
            "PACK_C_PEDIDOS": "PEDIDOS",
            "PACK_D_STATUS": "STATUS",
        }
        if pack_id in pack_map:
            return pack_map[pack_id]
        return topic
    except Exception:
        return str(current_topic or "").strip().upper() or "OTHER"


def _build_kb_anchor_reply(
    *,
    operational_reference: str,
    reference_example: str,
    clarify_q: str = "",
    contract: Dict[str, Any] | None = None,
) -> str:
    """
    Fallback mínimo e alinhado ao princípio de IA soberana:
    usa o que o banco já trouxe, sem transformar reference_example em resposta final.
    """
    try:
        if not _contract_allows_scene_runtime(contract or {}):
            return str(clarify_q or "").strip()

        stable_scene = _stabilize_scene_base(str(operational_reference or "").strip())
        generated = _generate_micro_scene_with_model(
            operational_reference=operational_reference,
            contract=contract or {},
        )

        scene_text = str(generated or "").strip()
        if not scene_text and stable_scene:
            scene_text = _compose_grounded_scene_with_progression(
                operational_reference=operational_reference,
                contract=contract or {},
                reference_example=str(reference_example or "").strip(),
            )

        if not scene_text and stable_scene:
            scene_text = _compose_grounded_scene_with_progression(
                operational_reference=operational_reference,
                contract=contract or {},
                reference_example=str(reference_example or "").strip(),
            )

        scene_text = _sanitize_user_facing_reply(scene_text)
        scene_text = re.sub(r"\s{2,}", " ", scene_text).strip(" .")

        if scene_text:
            if _is_live_operational_reply(
                text=scene_text,
                operational_reference=operational_reference,
                reference_example=str(reference_example or "").strip(),
                contract=contract or {},
            ):
                return scene_text.rstrip(".") + "."

        rebuilt = _build_last_resort_operational_reply(
            operational_reference="",
            reference_example=str(reference_example or "").strip(),
            contract=contract or {},
            clarify_q=clarify_q,
        )
        if rebuilt:
            return rebuilt

        return str(clarify_q or "").strip()
    except Exception:
        return str(clarify_q or "").strip()


def _build_last_resort_operational_reply(
    *,
    operational_reference: str,
    reference_example: str,
    contract: Dict[str, Any] | None = None,
    clarify_q: str = "",
) -> str:
    """
    Último recurso canônico.
    Nunca devolve a cena-base crua.
    Só libera texto se a forma final já vier minimamente viva.
    """
    try:
        c = dict(contract or {})
        if not _contract_allows_scene_runtime(c):
            return str(clarify_q or "").strip()

        stable_scene = _stabilize_scene_base(str(operational_reference or "").strip())
        ex = str(reference_example or "").strip()

        if not stable_scene:
            return str(clarify_q or "").strip()

        rebuilt = _compose_grounded_scene_with_progression(
            operational_reference=operational_reference,
            contract=c,
            reference_example=ex,
        )
        rebuilt = _sanitize_user_facing_reply(rebuilt)
        rebuilt = re.sub(r"\s{2,}", " ", str(rebuilt or "")).strip(" .")

        if rebuilt and _is_live_operational_reply(
            text=rebuilt,
            operational_reference="",
            reference_example=ex,
            contract=c,
        ):
            return rebuilt.rstrip(".") + "."

        generated = _generate_micro_scene_with_model(
            operational_reference=operational_reference,
            contract=c,
        )
        generated = _sanitize_user_facing_reply(generated)
        generated = re.sub(r"\s{2,}", " ", str(generated or "")).strip(" .")

        if generated and "→" in generated:
            return generated.rstrip(".") + "."

        return str(clarify_q or "").strip()
    except Exception:
        return str(clarify_q or "").strip()

def _kb_get_segment_scene(kb_snapshot: str, segment_key: str) -> str:
    """
    Puxa a cena diretamente do banco novo para segmento/subsegmento.
    Prioridade:
    1) kb_subsegments_v1[segment_key].micro_scene
    2) kb_segments_v1[segment_key].micro_scene
    3) one_liner + ritual operacional resumido
    4) ritual operacional resumido
    """
    try:
        if not kb_snapshot or not segment_key:
            return ""
        obj = json.loads(kb_snapshot) if kb_snapshot and kb_snapshot.lstrip().startswith(("{", "[")) else None
        if not isinstance(obj, dict):
            return ""

        seg = str(segment_key or "").strip().lower()
        doc = {}

        kb_sub = obj.get("kb_subsegments_v1") or {}
        if isinstance(kb_sub, dict):
            d = kb_sub.get(seg) or {}
            if isinstance(d, dict) and d:
                doc = d

        if not doc:
            kb_seg = obj.get("kb_segments_v1") or {}
            if isinstance(kb_seg, dict):
                d = kb_seg.get(seg) or {}
                if isinstance(d, dict) and d:
                    doc = d

        if not isinstance(doc, dict) or not doc:
            return ""

        ms = str(doc.get("micro_scene") or "").strip()
        if ms:
            return ms

        one_liner = str(doc.get("one_liner") or "").strip()

        ritual = doc.get("operational_ritual") or []
        if isinstance(ritual, list):
            steps = [str(x).strip() for x in ritual if str(x).strip()]
            if one_liner and steps:
                return one_liner.rstrip(". ") + " → " + " → ".join(steps[:5])
            if steps:
                return " → ".join(steps[:5])

        if one_liner:
            return one_liner
        return ""
    except Exception:
        return ""




def _refresh_operational_anchor(
    *,
    kb_snapshot: str,
    kb_context: Dict[str, Any],
    effective_segment: str,
    selected_pack_id: str,
    operational_family: str,
) -> Dict[str, str]:
    """
    Refaz a leitura operacional do banco antes da composição final.
    Isso reduz deriva do texto e reforça a cena correta sem engessar wording.
    """
    try:
        seg = str(
            (kb_context or {}).get("effective_subsegment")
            or (kb_context or {}).get("subsegment_hint")
            or effective_segment
            or ""
        ).strip()
        pack_id = str(selected_pack_id or "").strip().upper()

        reference_example = str((kb_context or {}).get("segment_reference_example") or "").strip()
        practical_scene = str((kb_context or {}).get("operational_reference") or "").strip()
        micro_scene = str((kb_context or {}).get("pack_micro_scene") or "").strip()
        family = str(
            (kb_context or {}).get("operational_family")
            or operational_family
            or ""
        ).strip()

        if seg and not reference_example:
            reference_example = _kb_get_reference_example(kb_snapshot, seg, pack_id)

        if seg and not practical_scene:
            practical_scene = _kb_get_segment_scene(kb_snapshot, seg)

        if not practical_scene and micro_scene:
            practical_scene = micro_scene

        if not practical_scene and seg and pack_id:
            practical_scene = _compose_practical_scene(
                kb_snapshot=kb_snapshot,
                segment_key=seg,
                pack_id=pack_id,
            )

        return {
            "reference_example": str(reference_example or "").strip(),
            "operational_reference": str(practical_scene or "").strip(),
            "operational_family": str(family or "").strip(),
        }
    except Exception:
        return {
            "reference_example": str((kb_context or {}).get("segment_reference_example") or "").strip(),
            "operational_reference": str((kb_context or {}).get("operational_reference") or "").strip(),
            "operational_family": str((kb_context or {}).get("operational_family") or operational_family or "").strip(),
        }


def _find_kb_map_anywhere(obj: Any, target_key: str, max_depth: int = 4) -> Dict[str, Any]:
    """
    Procura um mapa do KB em qualquer nível razoável do snapshot.
    Resolve casos em que o snapshot não vem com kb_* na raiz direta.
    """
    try:
        if max_depth < 0:
            return {}

        if isinstance(obj, dict):
            direct = obj.get(target_key)
            if isinstance(direct, dict):
                return direct

            for _, v in obj.items():
                found = _find_kb_map_anywhere(v, target_key, max_depth=max_depth - 1)
                if isinstance(found, dict) and found:
                    return found

        elif isinstance(obj, list):
            for item in obj:
                found = _find_kb_map_anywhere(item, target_key, max_depth=max_depth - 1)
                if isinstance(found, dict) and found:
                    return found

        return {}
    except Exception:
        return {}


def _kb_lookup_operational_docs(
    *,
    kb_snapshot: str,
    effective_segment: str,
    kb_context: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Hidrata documentos reais do banco para fortalecer o contrato operacional.
    Prioridade:
    1) subsegmento
    2) archetype referenciado pelo subsegmento
    3) segmento macro
    """
    try:
        raw = str(kb_snapshot or "").strip()
        obj = None

        if raw.startswith("{") or raw.startswith("["):
            try:
                obj = json.loads(raw)
            except Exception:
                obj = None

        if not isinstance(obj, (dict, list)):
            logging.info(
                "[CONVERSATIONAL_FRONT][KB_LOOKUP] snapshot_not_json seg=%s",
                str(effective_segment or "").strip().lower(),
            )
            return {"subsegment_doc": {}, "segment_doc": {}, "archetype_doc": {}}

        seg_key = str(effective_segment or "").strip().lower()
        hinted_sub = str((kb_context or {}).get("subsegment_hint") or "").strip().lower()
        user_probe = " ".join(
            [
                str(effective_segment or "").strip(),
                str((kb_context or {}).get("segment_hint") or "").strip(),
                str((kb_context or {}).get("subsegment_hint") or "").strip(),
                str((kb_context or {}).get("segment_reference_example") or "").strip(),
                str((kb_context or {}).get("operational_reference") or "").strip(),
            ]
        ).strip()

        kb_sub = _find_kb_map_anywhere(obj, "kb_subsegments_v1")
        kb_seg = _find_kb_map_anywhere(obj, "kb_segments_v1")
        kb_arch = _find_kb_map_anywhere(obj, "kb_archetypes_v1")

        sub_doc: Dict[str, Any] = {}
        seg_doc: Dict[str, Any] = {}
        arch_doc: Dict[str, Any] = {}

        # 1) busca direta do subsegmento
        if seg_key and isinstance(kb_sub, dict):
            d = kb_sub.get(seg_key) or {}
            if isinstance(d, dict) and d:
                sub_doc = d

        # 2) fallback tolerante por chave normalizada
        if not sub_doc and seg_key and isinstance(kb_sub, dict):
            norm_target = seg_key.replace("-", "_").replace(" ", "_")
            for k, d in kb_sub.items():
                kk = str(k or "").strip().lower().replace("-", "_").replace(" ", "_")
                if not isinstance(d, dict):
                    continue
                if kk == norm_target:
                    sub_doc = d
                    break

        # 3) fallback tolerante por contenção
        if not sub_doc and seg_key and isinstance(kb_sub, dict):
            for k, d in kb_sub.items():
                kk = str(k or "").strip().lower()
                if not isinstance(d, dict):
                    continue
                if seg_key in kk or kk in seg_key:
                    sub_doc = d
                    break

        # 4) fallback estrutural por overlap de tokens
        if not sub_doc and seg_key and isinstance(kb_sub, dict):
            best_sub_key = _best_lookup_key_match(seg_key, list(kb_sub.keys()), min_score=2)
            if best_sub_key:
                d = kb_sub.get(best_sub_key) or {}
                if isinstance(d, dict) and d:
                    sub_doc = d

        # 5) se o effective_segment vier macro, tenta promover para subsegmento real
        if not sub_doc and isinstance(kb_sub, dict) and kb_sub:
            promoted_sub_key = ""

            if hinted_sub and hinted_sub in kb_sub:
                promoted_sub_key = hinted_sub

            if not promoted_sub_key and user_probe:
                best_sub_key = _best_doc_match(user_probe, kb_sub, min_score=2)
                if best_sub_key and "__" in str(best_sub_key):
                    promoted_sub_key = str(best_sub_key).strip().lower()

            if promoted_sub_key:
                d = kb_sub.get(promoted_sub_key) or {}
                if isinstance(d, dict) and d:
                    sub_doc = d
                    seg_key = promoted_sub_key

        segment_id = str(
            (sub_doc or {}).get("segment_id")
            or (kb_context or {}).get("segment_id")
            or ""
        ).strip().lower()

        if segment_id and isinstance(kb_seg, dict):
            d = kb_seg.get(segment_id) or {}
            if isinstance(d, dict) and d:
                seg_doc = d

        if not seg_doc and segment_id and isinstance(kb_seg, dict):
            norm_segment = segment_id.replace("-", "_").replace(" ", "_")
            for k, d in kb_seg.items():
                kk = str(k or "").strip().lower().replace("-", "_").replace(" ", "_")
                if not isinstance(d, dict):
                    continue
                if kk == norm_segment:
                    seg_doc = d
                    break
        if not seg_doc and segment_id and isinstance(kb_seg, dict):
            best_seg_key = _best_lookup_key_match(segment_id, list(kb_seg.keys()), min_score=2)
            if best_seg_key:
                d = kb_seg.get(best_seg_key) or {}
                if isinstance(d, dict) and d:
                    seg_doc = d

        archetype_id = str(
            (sub_doc or {}).get("archetype_id")
            or (kb_context or {}).get("archetype_id")
            or ""
        ).strip().lower()

        if archetype_id and isinstance(kb_arch, dict):
            d = kb_arch.get(archetype_id) or {}
            if isinstance(d, dict) and d:
                arch_doc = d

        if not arch_doc and archetype_id and isinstance(kb_arch, dict):
            norm_arch = archetype_id.replace("-", "_").replace(" ", "_")
            for k, d in kb_arch.items():
                kk = str(k or "").strip().lower().replace("-", "_").replace(" ", "_")
                if not isinstance(d, dict):
                    continue
                if kk == norm_arch:
                    arch_doc = d
                    break
        if not arch_doc and archetype_id and isinstance(kb_arch, dict):
            best_arch_key = _best_lookup_key_match(archetype_id, list(kb_arch.keys()), min_score=2)
            if best_arch_key:
                d = kb_arch.get(best_arch_key) or {}
                if isinstance(d, dict) and d:
                    arch_doc = d

        logging.info(
            "[CONVERSATIONAL_FRONT][KB_LOOKUP] seg=%s sub_keys=%s seg_keys=%s arch_keys=%s found_sub=%s found_seg=%s found_arch=%s segment_id=%s archetype_id=%s",
            seg_key,
            len(kb_sub or {}),
            len(kb_seg or {}),
            len(kb_arch or {}),
            bool(sub_doc),
            bool(seg_doc),
            bool(arch_doc),
            segment_id,
            archetype_id,
        )

        return {
            "subsegment_doc": sub_doc if isinstance(sub_doc, dict) else {},
            "segment_doc": seg_doc if isinstance(seg_doc, dict) else {},
            "archetype_doc": arch_doc if isinstance(arch_doc, dict) else {},
        }
    except Exception as e:
        logging.warning(
            "[CONVERSATIONAL_FRONT][KB_LOOKUP] error seg=%s err=%s",
            str(effective_segment or "").strip().lower(),
            e,
        )
        return {"subsegment_doc": {}, "segment_doc": {}, "archetype_doc": {}}

def _infer_segment_from_docs(
    *,
    user_text: str,
    kb_snapshot: str,
    kb_context: Dict[str, Any],
) -> str:
    """
    Tenta descobrir o melhor segmento/subsegmento usando o texto do usuário
    e as chaves reais do KB, com matching estrutural.
    """
    try:
        raw = str(kb_snapshot or "").strip()
        if not raw or not (raw.startswith("{") or raw.startswith("[")):
            return ""

        obj = json.loads(raw)
        if not isinstance(obj, (dict, list)):
            return ""

        kb_sub = _find_kb_map_anywhere(obj, "kb_subsegments_v1")
        kb_seg = _find_kb_map_anywhere(obj, "kb_segments_v1")

        hinted = str(
            (kb_context or {}).get("subsegment_hint")
            or (kb_context or {}).get("segment_hint")
            or ""
        ).strip()

        search_text = " ".join(
            [
                str(user_text or "").strip(),
                hinted,
            ]
        ).strip()

        if isinstance(kb_sub, dict) and kb_sub:
            keyword_sub = _keyword_doc_match(search_text, kb_sub)
            if keyword_sub:
                return str(keyword_sub).strip().lower()

            best_sub = _best_doc_match(search_text, kb_sub, min_score=2)
            if best_sub:
                best_doc = kb_sub.get(best_sub) or {}
                if _doc_identity_is_compatible_with_current_text(
                    user_text=user_text,
                    doc=best_doc if isinstance(best_doc, dict) else {},
                    doc_key=str(best_sub),
                    min_score=2,
                ):
                    return str(best_sub).strip().lower()

        if isinstance(kb_seg, dict) and kb_seg:
            keyword_seg = _keyword_doc_match(search_text, kb_seg)
            if keyword_seg:
                return str(keyword_seg).strip().lower()

            best_seg = _best_doc_match(search_text, kb_seg, min_score=2)
            if best_seg:
                best_doc = kb_seg.get(best_seg) or {}
                if _doc_identity_is_compatible_with_current_text(
                    user_text=user_text,
                    doc=best_doc if isinstance(best_doc, dict) else {},
                    doc_key=str(best_seg),
                    min_score=2,
                ):
                    return str(best_seg).strip().lower()

        candidates = []
        if isinstance(kb_sub, dict):
            candidates.extend([str(k).strip() for k in kb_sub.keys() if str(k).strip()])
        if isinstance(kb_seg, dict):
            candidates.extend([str(k).strip() for k in kb_seg.keys() if str(k).strip()])

        best = _best_lookup_key_match(search_text, candidates, min_score=2)
        return str(best or "").strip().lower() if best and not user_text else ""
    except Exception:
        return ""


def _merge_real_kb_operational_context(
    *,
    kb_context: Dict[str, Any],
    docs: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Enriquece kb_context com os docs reais do banco.
    Não inventa nada; só preenche lacunas.
    """
    try:
        ctx = dict(kb_context or {})
        sub_doc = (docs or {}).get("subsegment_doc") or {}
        seg_doc = (docs or {}).get("segment_doc") or {}
        use_seg = not bool(sub_doc)
        arch_doc = (docs or {}).get("archetype_doc") or {}
        subsegment_key = str((sub_doc or {}).get("id") or "").strip()
        if subsegment_key:
            ctx["subsegment_hint"] = subsegment_key
            ctx["effective_subsegment"] = subsegment_key

        def _pick(*vals: Any) -> str:
            for v in vals:
                s = str(v or "").strip()
                if s:
                    return s
            return ""

        segment_profile = dict(ctx.get("segment_profile") or {})

        archetype_id = _pick(
            ctx.get("archetype_id"),
            sub_doc.get("archetype_id"),
            arch_doc.get("id"),
        )
        if archetype_id:
            ctx["archetype_id"] = archetype_id

        segment_id = _pick(
            ctx.get("segment_id"),
            sub_doc.get("segment_id"),
            seg_doc.get("id"),
        )
        if segment_id:
            ctx["segment_id"] = segment_id

        primary_goal = _pick(
            segment_profile.get("primary_goal"),
            sub_doc.get("primary_goal"),
            arch_doc.get("primary_goal"),
            seg_doc.get("primary_goal"),
        )
        if primary_goal:
            segment_profile["primary_goal"] = primary_goal

        service_noun = _pick(
            segment_profile.get("service_noun"),
            sub_doc.get("service_noun"),
            arch_doc.get("service_noun"),
            seg_doc.get("customer_noun"),
        )
        if service_noun:
            segment_profile["service_noun"] = service_noun

        handoff_format = _pick(
            segment_profile.get("handoff_format"),
            sub_doc.get("handoff_format"),
            arch_doc.get("handoff_format"),
            seg_doc.get("handoff_format"),
        )
        if handoff_format:
            segment_profile["handoff_format"] = handoff_format

        customer_noun = _pick(
            segment_profile.get("customer_noun"),
            sub_doc.get("customer_noun"),
            arch_doc.get("customer_noun"),
            seg_doc.get("customer_noun"),
        )
        if customer_noun:
            segment_profile["customer_noun"] = customer_noun

        conversion_noun = _pick(
            segment_profile.get("conversion_noun"),
            sub_doc.get("conversion_noun"),
            arch_doc.get("conversion_noun"),
            seg_doc.get("conversion_noun"),
        )
        if conversion_noun:
            segment_profile["conversion_noun"] = conversion_noun

        operational_ritual = (
            segment_profile.get("operational_ritual")
            or sub_doc.get("operational_ritual")
            or arch_doc.get("operational_ritual")
            or seg_doc.get("operational_ritual")
            or []
        )
        cleaned_ritual = [str(x).strip() for x in operational_ritual if str(x).strip()] if isinstance(operational_ritual, list) else []

        if not cleaned_ritual:
            derived_scene = _pick(
                ctx.get("operational_reference"),
                sub_doc.get("micro_scene"),
                arch_doc.get("micro_scene"),
                seg_doc.get("micro_scene"),
            )
            cleaned_ritual = _derive_ritual_from_scene(derived_scene)

        if cleaned_ritual:
            segment_profile["operational_ritual"] = cleaned_ritual

        preferred_capabilities = (
            segment_profile.get("preferred_capabilities")
            or sub_doc.get("preferred_capabilities")
            or arch_doc.get("preferred_capabilities")
            or seg_doc.get("preferred_capabilities")
            or []
        )
        if isinstance(preferred_capabilities, list):
            caps = [str(x).strip() for x in preferred_capabilities if str(x).strip()]
            if caps:
                segment_profile["preferred_capabilities"] = caps

        common_intents = (
            segment_profile.get("common_intents")
            or sub_doc.get("common_intents")
            or arch_doc.get("common_intents")
            or seg_doc.get("common_intents")
            or []
        )
        if isinstance(common_intents, list):
            intents = [str(x).strip() for x in common_intents if str(x).strip()]
            if intents:
                segment_profile["common_intents"] = intents

        catalog_groups = (
            segment_profile.get("catalog_groups")
            or sub_doc.get("catalog_groups")
            or arch_doc.get("catalog_groups")
            or seg_doc.get("catalog_groups")
            or []
        )
        if isinstance(catalog_groups, list):
            groups = [str(x).strip() for x in catalog_groups if str(x).strip()]
            if groups:
                segment_profile["catalog_groups"] = groups

        operational_rules = (
            segment_profile.get("operational_rules")
            or sub_doc.get("operational_rules")
            or arch_doc.get("operational_rules")
            or seg_doc.get("operational_rules")
            or {}
        )
        if isinstance(operational_rules, dict) and operational_rules:
            segment_profile["operational_rules"] = operational_rules

        if segment_profile:
            ctx["segment_profile"] = segment_profile

        if not str(ctx.get("segment_reference_example") or "").strip():
            one_liner = _pick(
                sub_doc.get("one_liner"),
                arch_doc.get("one_liner"),
                (seg_doc.get("one_liner") if use_seg else ""),
            )
            if one_liner:
                ctx["segment_reference_example"] = one_liner

        if not str(ctx.get("operational_reference") or "").strip():
            micro_scene = _pick(
                sub_doc.get("micro_scene_conversational"),
                arch_doc.get("micro_scene_conversational"),
                (seg_doc.get("micro_scene_conversational") if use_seg else ""),
                sub_doc.get("micro_scene"),
                arch_doc.get("micro_scene"),
                (seg_doc.get("micro_scene") if use_seg else ""),
                sub_doc.get("direct_scene"),
                arch_doc.get("direct_scene"),
                (seg_doc.get("direct_scene") if use_seg else ""),
                sub_doc.get("runtime_long_text"),
                arch_doc.get("runtime_long_text"),
                (seg_doc.get("runtime_long_text") if use_seg else ""),
            )
            if micro_scene:
                ctx["operational_reference"] = micro_scene

        if not str(ctx.get("operational_family") or "").strip():
            family = _pick(
                sub_doc.get("conversation_mode"),
                arch_doc.get("conversation_mode"),
                seg_doc.get("conversation_mode"),
            )
            if family:
                ctx["operational_family"] = family

        return ctx
    except Exception:
        return dict(kb_context or {})



def _build_operational_contract(
    *,
    kb_snapshot: str,
    kb_context: Dict[str, Any],
    effective_segment: str,
    operational_reference: str,
    reference_example: str,
    operational_family: str,
    topic: str,
) -> Dict[str, Any]:
    """
    Constrói um contrato auditável do trilho operacional.
    Não é frase pronta; é estrutura de governança.
    """
    try:
        docs = _kb_lookup_operational_docs(
            kb_snapshot=kb_snapshot,
                        effective_segment=effective_segment,
            kb_context=kb_context if isinstance(kb_context, dict) else {},
        )

        sub_doc = (docs or {}).get("subsegment_doc") or {}
        seg_doc = (docs or {}).get("segment_doc") or {}
        arch_doc = (docs or {}).get("archetype_doc") or {}
        segment_profile = (kb_context or {}).get("segment_profile") or {}
        use_seg = not bool(sub_doc)
        use_profile = not bool(sub_doc)

        def _pick_str(*vals: Any) -> str:
            for v in vals:
                s = str(v or "").strip()
                if s:
                    return s
            return ""

        archetype_id = _pick_str(
            (kb_context or {}).get("archetype_id"),
            (sub_doc or {}).get("archetype_id"),
            (arch_doc or {}).get("id"),
        ).lower()

        primary_goal = _pick_str(
            (segment_profile.get("primary_goal") if use_profile else ""),
            (sub_doc or {}).get("primary_goal"),
            (arch_doc or {}).get("primary_goal"),
            ((seg_doc or {}).get("primary_goal") if use_seg else ""),
        ).lower()

        service_noun = _pick_str(
            (segment_profile.get("service_noun") if use_profile else ""),
            (sub_doc or {}).get("service_noun"),
            (arch_doc or {}).get("service_noun"),
            ((seg_doc or {}).get("service_noun") if use_seg else ""),
        ).lower()

        handoff_format = _pick_str(
            segment_profile.get("handoff_format"),
            (sub_doc or {}).get("handoff_format"),
            (arch_doc or {}).get("handoff_format"),
            (seg_doc or {}).get("handoff_format"),
        ).lower()

        customer_noun = _pick_str(
            segment_profile.get("customer_noun"),
            segment_profile.get("customer_noun"),
            (sub_doc or {}).get("customer_noun"),
            (arch_doc or {}).get("customer_noun"),
            (seg_doc or {}).get("customer_noun"),
        ).lower()

        conversion_noun = _pick_str(
            (segment_profile.get("conversion_noun") if use_profile else ""),
            (sub_doc or {}).get("conversion_noun"),
            (arch_doc or {}).get("conversion_noun"),
            ((seg_doc or {}).get("conversion_noun") if use_seg else ""),
        ).lower()

        operational_ritual = (
            (segment_profile.get("operational_ritual") if use_profile else [])
            or (sub_doc or {}).get("operational_ritual")
            or (arch_doc or {}).get("operational_ritual")
            or ((seg_doc or {}).get("operational_ritual") if use_seg else [])
            or []
        )
        _is_hydrated = bool(sub_doc or arch_doc or (seg_doc if use_seg else {}))
        ritual_steps = []
        if _is_hydrated:
            ritual_steps = [str(x).strip() for x in operational_ritual if str(x).strip()] if isinstance(operational_ritual, list) else []

        if _is_hydrated and not ritual_steps:
            ritual_steps = _derive_ritual_from_scene(
                _pick_str(
                    operational_reference,
                    (sub_doc or {}).get("micro_scene"),
                    (arch_doc or {}).get("micro_scene"),
                    (seg_doc or {}).get("micro_scene"),
                )
            )

        preferred_capabilities = (
            (segment_profile.get("preferred_capabilities") if use_profile else [])
            or (sub_doc or {}).get("preferred_capabilities")
            or (arch_doc or {}).get("preferred_capabilities")
            or ((seg_doc or {}).get("preferred_capabilities") if use_seg else [])
            or []
        )
        capability_list = [str(x).strip() for x in preferred_capabilities if str(x).strip()] if isinstance(preferred_capabilities, list) else []

        common_intents = (
            (segment_profile.get("common_intents") if use_profile else [])
            or (sub_doc or {}).get("common_intents")
            or (arch_doc or {}).get("common_intents")
            or ((seg_doc or {}).get("common_intents") if use_seg else [])
            or []
        )
        intent_list = [str(x).strip() for x in common_intents if str(x).strip()] if isinstance(common_intents, list) else []

        catalog_groups = (
            (segment_profile.get("catalog_groups") if use_profile else [])
            or (sub_doc or {}).get("catalog_groups")
            or (arch_doc or {}).get("catalog_groups")
            or ((seg_doc or {}).get("catalog_groups") if use_seg else [])
            or []
        )
        group_list = [str(x).strip() for x in catalog_groups if str(x).strip()] if isinstance(catalog_groups, list) else []

        operational_rules = (
            (segment_profile.get("operational_rules") if use_profile else {})
            or (sub_doc or {}).get("operational_rules")
            or (arch_doc or {}).get("operational_rules")
            or ((seg_doc or {}).get("operational_rules") if use_seg else {})
            or {}
        )
        rule_map = operational_rules if isinstance(operational_rules, dict) else {}

        contract_family = _pick_str(
            operational_family,
            (kb_context or {}).get("operational_family"),
            (sub_doc or {}).get("conversation_mode"),
            (arch_doc or {}).get("conversation_mode"),
            (seg_doc or {}).get("conversation_mode"),
        ).lower()

        # exemplo/cena reais do banco
        has_reference_example = bool(
            str(reference_example or "").strip()
            or str((sub_doc or {}).get("one_liner") or "").strip()
            or str(((seg_doc or {}).get("one_liner") if use_seg else "") or "").strip()
            or str((arch_doc or {}).get("one_liner") or "").strip()
        )

        # ==========================================================
        # Cena operacional válida:
        # NÃO basta existir material global/runtime.
        # Precisa existir hidratação estrutural real.
        #
        # Isso evita promover PACK global institucional
        # para contrato operacional legítimo.
        # ==========================================================
        has_structural_contract = bool(
            sub_doc
            or arch_doc
            or (seg_doc if use_seg else {})
            or archetype_id
            or str(effective_segment or "").strip()
            or str((kb_context or {}).get("effective_subsegment") or "").strip()
            or str((kb_context or {}).get("subsegment_hint") or "").strip()
        )

        has_practical_scene = bool(
            has_structural_contract
            and (
                str(operational_reference or "").strip()
                or str((sub_doc or {}).get("micro_scene") or "").strip()
                or str((arch_doc or {}).get("micro_scene") or "").strip()
                or str(((seg_doc or {}).get("micro_scene") if use_seg else "") or "").strip()
            )
        )

        allowed_next_step = "none"

        archetype_to_next = {
            "comercio_consultivo_presencial": "visita_loja",
            "comercio_catalogo_direto": "reserva_ou_compra",
            "servico_tecnico_visita": "visita",
            "servico_agendado": "agendamento",
            "servico_agendado_com_encaixe": "agendamento",
            "alimentacao_pedido": "pedido",
        }

        family_to_next = {
            "agenda": "agendamento",
            "pedidos": "pedido",
        }

        if archetype_id in archetype_to_next:
            allowed_next_step = archetype_to_next[archetype_id]
        elif contract_family in family_to_next:
            allowed_next_step = family_to_next[contract_family]

        if not customer_noun:
            customer_noun = ""

        if not conversion_noun:
            conversion_noun = ""

        return {
            "segment": str(
                (sub_doc or {}).get("id")
                or (kb_context or {}).get("effective_subsegment")
                or (kb_context or {}).get("subsegment_hint")
                or effective_segment
                or ""
            ).strip(),
            "topic": str(topic or "").strip().upper(),
            "archetype_id": archetype_id,
            "primary_goal": primary_goal,
            "service_noun": service_noun,
            "customer_noun": customer_noun,
            "conversion_noun": conversion_noun,
            "handoff_format": handoff_format,
            "operational_family": contract_family,
            "operational_ritual": ritual_steps,
            "preferred_capabilities": capability_list,
            "common_intents": intent_list,
            "catalog_groups": group_list,
            "operational_rules": rule_map,
            "has_reference_example": has_reference_example,
            "has_practical_scene": has_practical_scene,
            "allowed_next_step": allowed_next_step,
            "hydrated_from_docs": bool(sub_doc or seg_doc or arch_doc),
            "micro_scene_conversational": _pick_str(
                (sub_doc or {}).get("micro_scene_conversational"),
                (arch_doc or {}).get("micro_scene_conversational"),
                ((seg_doc or {}).get("micro_scene_conversational") if use_seg else ""),
            ),
            "lead_refinement_question": _pick_str(
                (kb_context or {}).get("lead_refinement_question"),
                (sub_doc or {}).get("lead_refinement_question"),
                (sub_doc or {}).get("refinement_question"),
                (sub_doc or {}).get("business_refinement_question"),
                (arch_doc or {}).get("lead_refinement_question"),
                (arch_doc or {}).get("refinement_question"),
                ((seg_doc or {}).get("lead_refinement_question") if use_seg else ""),
                ((seg_doc or {}).get("refinement_question") if use_seg else ""),
            ),
            "micro_scene": _pick_str(
                (sub_doc or {}).get("micro_scene"),
                (arch_doc or {}).get("micro_scene"),
                ((seg_doc or {}).get("micro_scene") if use_seg else ""),
            ),
            "direct_scene": _pick_str(
                (sub_doc or {}).get("direct_scene"),
                (arch_doc or {}).get("direct_scene"),
                ((seg_doc or {}).get("direct_scene") if use_seg else ""),
            ),
            "runtime_long_text": _pick_str(
                (sub_doc or {}).get("runtime_long_text"),
                (arch_doc or {}).get("runtime_long_text"),
                ((seg_doc or {}).get("runtime_long_text") if use_seg else ""),
            ),
            "operational_reference": str(operational_reference or "").strip(),
            "reference_example": str(reference_example or "").strip(),
        }
    except Exception:
        return {
            "segment": str(
                (kb_context or {}).get("effective_subsegment")
                or (kb_context or {}).get("subsegment_hint")
                or effective_segment
                or ""
            ).strip(),
            "topic": str(topic or "").strip().upper(),
            "archetype_id": "",
            "primary_goal": "",
            "service_noun": "",
            "customer_noun": "",
            "conversion_noun": "",
            "handoff_format": "",
            "operational_family": str(operational_family or "").strip().lower(),
            "operational_ritual": [],
            "preferred_capabilities": [],
            "common_intents": [],
            "catalog_groups": [],
            "operational_rules": {},
            "has_reference_example": bool(str(reference_example or "").strip()),
            "has_practical_scene": bool(str(operational_reference or "").strip()),
            "allowed_next_step": "none",
            "hydrated_from_docs": False,
            "lead_refinement_question": "",
            "operational_reference": str(operational_reference or "").strip(),
            "reference_example": str(reference_example or "").strip(),
        }



def _clean_scene_text(text: str) -> str:
    try:
        t = str(text or "").strip()
        if not t:
            return ""
        t = re.sub(r"^\s*PACK_[A-Z_]+\s*", "", t, flags=re.I).strip()
        t = re.sub(r"^\s*Na prática:\s*", "", t, flags=re.I).strip()
        t = re.sub(r"\s*\|\s*Fluxo:.*$", "", t, flags=re.I).strip()
        t = re.sub(r"\s{2,}", " ", t).strip()
        return t.rstrip(". ")
    except Exception:
        return str(text or "").strip()



def _generate_style_intro_with_model(
    *,
    user_text: str,
    segment_hint: str,
    name_hint: str,
    state_summary: dict | None = None,
    contract: dict | None = None,
) -> str:
    """
    Gera uma única frase de abertura contextualizada.
    Escopo extremamente restrito para evitar regressão.
    """
    try:
        tone_hint = _resolve_tone_hint(state_summary, contract)

        system = f"""
Você é um assistente de WhatsApp.
Sua tarefa é escrever apenas a primeira frase da resposta.

PAPEL DA FRASE:
Servir como ponte curta antes da explicação principal.

PADRÃO:
1. Uma frase curta.
2. Linguagem simples de WhatsApp.
3. Reconhecer o tema da mensagem do cliente.
4. Iniciar a resposta com boas-vindas relacionadas ao tema.
5. Usar exatamente este estilo de comunicação: "{tone_hint}".

EXEMPLOS:
Contexto: Cliente pergunta "Como funciona para clínica?"
Saída: Que legal, para clínicas isso ajuda a organizar os atendimentos.

Contexto: Cliente diz "Quero saber o preço."
Saída: Claro, já te explico os valores de um jeito simples.

Contexto: Cliente diz "Sou advogado."
Saída: Perfeito, para advogado isso ajuda a organizar melhor o atendimento.
"""

        user = f"""
Mensagem do cliente:
{user_text}

Segmento:
{segment_hint}

Nome:
{name_hint}

Saída:
"""

        text = _call_openai_for_front(
            system=system,
            user=user,
            temperature=0.7,
            max_tokens=40,
        ).strip()

        text = str(text or "").strip().strip('"').strip("'").strip()
        text = re.sub(r"\s{2,}", " ", text).strip()

        if len(text) > 120:
            return ""

        return text

    except Exception:
        return ""


def _build_direct_sales_reply_with_model(
    *,
    user_text: str = "",
    core_text: str = "",
    name_hint: str = "",
    segment_hint: str = "",
    state_summary: dict | None = None,
    contract: Dict[str, Any] | None = None,
) -> str:
    """
    Monta a resposta DIRECT de vendas a partir do núcleo operacional compacto.
    Não reabre SCENE, não usa ritual operacional e não inventa fatos.
    O modelo só faz a camada conversacional: abertura, contexto do lead e fluidez.
    """
    try:
        core = str(core_text or "").strip()
        user = str(user_text or "").strip()

        if not core or not user:
            return ""

        system = """
Você escreve uma resposta de WhatsApp para um lead interessado no MEI Robô.

Use a mensagem do lead para reconhecer naturalmente, quando estiver explícito:
- nome;
- profissão, ramo ou segmento;
- contexto de uso.

Use o núcleo operacional como base factual.
Transforme o núcleo em uma explicação conversada, útil e comercial.
Mostre como o robô ajuda naquele contexto específico.
Preserve somente capacidades presentes no núcleo.
Não invente funcionalidades, horários, integrações ou promessas.
Não transforme em manual, tutorial, lista ou passo a passo.
Responda em português do Brasil, em 1 único parágrafo.
Tamanho ideal: 450 a 750 caracteres.
"""

        payload = f"""
Mensagem do lead:
{user}

Nome já conhecido:
{str(name_hint or "").strip()}

Segmento já conhecido:
{str(segment_hint or "").strip()}

Núcleo operacional seguro:
{core}

Resposta final:
"""

        text = _call_openai_for_front(
            system=system,
            user=payload,
            temperature=0.55,
            max_tokens=220,
        ).strip()

        text = str(text or "").strip().strip('"').strip("'").strip()
        text = re.sub(r"\s{2,}", " ", text).strip()

        if not text:
            return ""

        # DIRECT consultivo pode ser curto e humano.
        # A trava de 160 chars estava descartando wrappers válidos.
        if len(text) < 40:
            return ""

        if len(text) > 900:
            text = text[:900].rsplit(" ", 1)[0].strip()

        if _looks_like_technical_output(text):
            return ""

        # DIRECT é resposta consultiva de vendas.
        # Não aplicar aqui os validadores de forma operacional usados para SCENE.
        return text

    except Exception:
        return ""


def _extract_intro_hint_from_model_reply(*, intro_hint: str = "", core_text: str = "") -> str:
    """
    Reaproveita a abertura natural que o modelo já produziu no turno.
    Não cria frase pronta, não decide segmento e não reabre microcena.
    Apenas separa uma primeira frase curta do texto livre já gerado.
    """
    try:
        hint = str(intro_hint or "").strip()
        core = str(core_text or "").strip()

        if not hint:
            return ""

        hint = re.sub(r"\s{2,}", " ", hint).strip()
        core_norm = re.sub(r"\s{2,}", " ", core).strip().lower()
        hint_norm = hint.lower()

        if core_norm and (hint_norm == core_norm or hint_norm in core_norm):
            return ""

        first_block = re.split(r"\n\s*\n", hint, maxsplit=1)[0].strip()
        first_sentence = re.split(r"(?<=[\.\!\?])\s+", first_block, maxsplit=1)[0].strip()

        candidate = first_sentence or first_block
        candidate = re.sub(r"\s{2,}", " ", candidate).strip()

        if not candidate:
            return ""

        if len(candidate) < 8 or len(candidate) > 180:
            return ""

        if core_norm and candidate.lower() in core_norm:
            return ""

        return candidate

    except Exception:
        return ""

def _build_direct_scene_payload(
    contract: Dict[str, Any] | None,
    *,
    user_text: str = "",
    segment_hint: str = "",
    name_hint: str = "",
    state_summary: dict | None = None,
    intro_hint: str = "",
    use_human_wrapper: bool = False,
) -> str:
    try:
        c = dict(contract or {})
        # Direct Fulfillment:
        # prioriza o material mais específico já resolvido pelo KB.
        # Não reescreve a microcena por IA.
        # ==========================================================
        # FALLBACK GLOBAL:
        # usa SOMENTE núcleo compacto/institucional
        # para evitar retorno do proceduralismo.
        # ==========================================================
        if not bool(c.get("hydrated_from_docs")):
            if str(c.get("response_mode") or "").strip().upper() == "DIRECT":
                scene = (
                    c.get("direct_scene")
                    or c.get("runtime_long_text")
                    or c.get("runtime_short_reply")
                    or c.get("runtime_compact_reply")
                    or c.get("operational_reference")
                )
            else:
                scene = (
                    c.get("runtime_compact_reply")
                    or c.get("runtime_short_reply")
                    or c.get("operational_reference")
                )
        else:
            scene = (
                c.get("micro_scene_conversational")
                or c.get("micro_scene")
                or c.get("direct_scene")
                or c.get("runtime_long_text")
                or c.get("operational_reference")
                or c.get("pack_micro_scene")
                or c.get("runtime_short_reply")
                or c.get("reference_example")
            )

        raw_core = str(scene or "").strip()
        core = raw_core
        if not core:
            return ""

        core = re.sub(r"\s{2,}", " ", core).strip(" .")
        core = _humanize_scene_flow(core) or core
        core = re.sub(r"\s{2,}", " ", core).strip(" .")

        if core and not core.endswith((".", "!", "?")):
            core += "."

        # DIRECT global compacto:
        # antes de cair em intro curta + core seco, tenta montar a resposta
        # vencedora com base no user_text e no núcleo seguro.
        if (
            bool(c.get("global_pack_fallback"))
            and not bool(c.get("hydrated_from_docs"))
        ):
            rich_direct = _build_direct_sales_reply_with_model(
                user_text=user_text,
                core_text=core,
                name_hint=name_hint,
                segment_hint=segment_hint,
                state_summary=state_summary,
                contract=c,
            )

            if rich_direct:
                return rich_direct

        # 🔹 tentativa de gerar abertura via IA (leve)
        intro = _generate_style_intro_with_model(
            user_text=user_text,
            segment_hint=segment_hint,
            name_hint=name_hint,
            state_summary=state_summary,
            contract=c,
        )

        intro = str(intro or "").strip().strip('"').strip("'").strip()
        intro = re.sub(r"\s{2,}", " ", intro).strip()

        if not intro:
            intro = _extract_intro_hint_from_model_reply(
                intro_hint=intro_hint,
                core_text=core,
            )

        if not intro:
            if (
                bool(c.get("global_pack_fallback"))
                and not bool(c.get("hydrated_from_docs"))
            ):
                return ""
            final_text = core
        else:
            final_text = f"{intro}\n\n{core}"

        return final_text.strip()

    except Exception:
        return ""


def _expand_scene_steps(
    *,
    operational_reference: str,
    contract: Dict[str, Any] | None = None,
) -> list[str]:
    """
    Expande a cena em micro-etapas encadeadas.
    Não cria fatos novos; apenas reaproveita:
    - operational_reference
    - operational_ritual
    - reference_example
    """
    try:
        c = dict(contract or {})
        steps: list[str] = []

        ritual = c.get("operational_ritual") or []
        if isinstance(ritual, list):
            steps.extend([re.sub(r"\s{2,}", " ", str(x).strip(" .")) for x in ritual if str(x).strip()])

        if not steps:
            steps.extend(_split_scene_steps(operational_reference))

        reference_example = str(c.get("reference_example") or "").strip()
        if reference_example and not steps:
            ex_steps = _split_scene_steps(reference_example)
            if ex_steps:
                first_ex = ex_steps[0]
                if first_ex and first_ex.lower() not in {s.lower() for s in steps}:
                    steps.append(first_ex)

        cleaned: list[str] = []
        seen = set()
        for s in steps:
            ss = re.sub(r"\s{2,}", " ", str(s or "").strip(" ."))
            ss = _strip_scene_narrator(ss)
            if not ss:
                continue
            key = ss.lower()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(ss)

        return cleaned[:8]
    except Exception:
        return _split_scene_steps(operational_reference)


def _select_structured_scene_steps(
    *,
    operational_reference: str,
    contract: Dict[str, Any] | None = None,
    model_steps: list[str] | None = None,
) -> list[str]:
    """
    Seleciona uma sequência estrutural única para a microcena.
    Prioridade:
    1) steps do modelo
    2) ritual operacional
    3) cena-base quebrada em etapas
    """
    try:
        c = dict(contract or {})
        out: list[str] = []
        seen = set()

        sources: list[list[str]] = []

        if isinstance(model_steps, list):
            sources.append([str(x).strip() for x in model_steps if str(x).strip()])

        ritual = c.get("operational_ritual") or []
        if isinstance(ritual, list):
            sources.append([str(x).strip() for x in ritual if str(x).strip()])

        base_steps = _split_scene_steps(operational_reference)
        if base_steps:
            sources.append(base_steps)

        for group in sources:
            for raw in group:
                s = re.sub(r"\s{2,}", " ", str(raw or "").strip(" .,:;-"))
                s = _strip_scene_narrator(s)
                if not s:
                    continue
                key = re.sub(r"\W+", "", s).lower()
                if not key or key in seen:
                    continue
                seen.add(key)
                out.append(s)

        # garante que sempre tenta puxar do texto do usuário
        if len(out) < 3 and operational_reference:
            extra = _split_scene_steps(operational_reference)
            for s in extra:
                key = re.sub(r"\W+", "", s).lower()
                if key not in seen:
                    seen.add(key)
                    out.append(s)

        return out[:10]
    except Exception:
        return []


def _expand_structural_steps_from_contract_with_model(
    *,
    operational_reference: str,
    contract: Dict[str, Any] | None = None,
    reference_example: str = "",
) -> list[str]:
    """
    Expande a microcena em mais passos estruturais usando apenas
    o contrato operacional já resolvido.

    Não escreve resposta final.
    Não usa palavras-chave no código.
    Não usa frases prontas por segmento.
    """
    try:
        if _HAS_OPENAI_CLIENT and _client is None:
            return []

        c = dict(contract or {})

        base_steps = _select_structured_scene_steps(
            operational_reference="",
            contract=c,
            model_steps=None,
        )

        if len(base_steps) < 2:
            return []

        payload = {
            "segment": str(c.get("segment") or "").strip(),
            "topic": str(c.get("topic") or "").strip().upper(),
            "archetype_id": str(c.get("archetype_id") or "").strip(),
            "primary_goal": str(c.get("primary_goal") or "").strip(),
            "service_noun": str(c.get("service_noun") or "").strip(),
            "customer_noun": str(c.get("customer_noun") or "").strip(),
            "conversion_noun": str(c.get("conversion_noun") or "").strip(),
            "handoff_format": [],
            "operational_family": str(c.get("operational_family") or "").strip(),
            "operational_ritual": c.get("operational_ritual") or [],
            "preferred_capabilities": c.get("preferred_capabilities") or [],
            "common_intents": c.get("common_intents") or [],
            "catalog_groups": c.get("catalog_groups") or [],
            "allowed_next_step": str(c.get("allowed_next_step") or "").strip(),
            "operational_reference": str(operational_reference or "").strip(),
            "reference_example": str(reference_example or c.get("reference_example") or "").strip(),
            "base_steps": base_steps,
        }

        system = """Você ajusta uma mensagem para WhatsApp.

Siga esta sequência:

1. Comece com uma saudação.
2. Use o nome do lead se estiver disponível.
3. Mantenha toda a explicação operacional existente.
4. Continue a conversa já iniciada com o lead enquanto explica o funcionamento.
5. Se houver nome do lead, utilize naturalmente ao longo da resposta.
6. Se houver profissão, segmento ou contexto profissional, conecte a explicação ao cenário desse profissional de forma natural.
7. Explique o funcionamento de forma prática e operacional, sem perder continuidade conversacional.
8. A resposta deve soar como conversa consultiva no WhatsApp, não como documentação ou tutorial.
9. Organize o texto em fluxo contínuo.
10. Finalize com ponto.

Não remova informações.

Escreva em um único parágrafo.

Retorne somente o texto.
"""

        user_prompt = json.dumps(payload, ensure_ascii=False)

        if _HAS_OPENAI_CLIENT and _client is not None:
            resp = _client.chat.completions.create(
                model=MODEL,
                temperature=0.2,
                max_tokens=260,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_prompt},
                ],
            )
            raw = str(resp.choices[0].message.content or "").strip()
        else:
            resp = openai.ChatCompletion.create(
                model=MODEL,
                temperature=0.2,
                max_tokens=260,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_prompt},
                ],
            )
            raw = str(resp["choices"][0]["message"]["content"] or "").strip()

        obj = json.loads(raw)
        steps = obj.get("steps") or []
        if not isinstance(steps, list):
            return []

        out = []
        seen = set()

        
        for raw_step in steps:
            s = re.sub(r"\s{2,}", " ", str(raw_step or "").strip(" .,:;-"))
            if not s:
                continue
            
            key = re.sub(r"\W+", "", s).lower()
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(s)

        # remove steps semanticamente repetidos
        dedup = []
        seen_roots = set()

        for s in out:
            root = re.sub(r"(robô|cliente|atendimento|fluxo)\s+", "", s.lower())
            root = re.sub(r"\W+", "", root)

            if root in seen_roots:
                continue

            seen_roots.add(root)
            dedup.append(s)

        out = dedup

        # limita expansão excessiva sem progressão
        if len(out) > 8:
            out = out[:8]

        return out
    except Exception:
        return []


def _compose_grounded_scene_with_progression(
    *,
    operational_reference: str,
    contract: Dict[str, Any] | None = None,
    reference_example: str = "",
) -> str:
    """
    Monta microcena operacional a partir de estrutura.
    Não reaproveita prosa narrada como resposta final.
    """
    try:
        c = dict(contract or {})
        if not _contract_allows_scene_runtime(c):
            return ""

        stable_scene = _stabilize_scene_base(operational_reference)
        ex = str(reference_example or c.get("reference_example") or "").strip()

        model_expanded_steps = _expand_structural_steps_from_contract_with_model(
            operational_reference="",
            contract=c,
            reference_example=ex,
        )

        steps = _select_structured_scene_steps(
            operational_reference="",
            contract=c,
            model_steps=model_expanded_steps if model_expanded_steps else None,
        )

        ritual = c.get("operational_ritual") or []
        if isinstance(ritual, list):
            ritual_steps = [str(x).strip() for x in ritual if str(x).strip()]
            if len(ritual_steps) >= 3:
                steps = ritual_steps + steps

        cleaned: list[str] = []

        def _phase_signature(s: str) -> str:
            tokens = re.findall(r"\w+", s.lower())

            # pega só as 2 primeiras palavras relevantes
            core = [t for t in tokens if len(t) > 3][:2]
            return " ".join(core)

        def _semantic_key(text: str) -> str:
            tokens = re.findall(r"\w+", text.lower())
            # remove palavras comuns operacionais
            tokens = [t for t in tokens if t not in {"o", "a", "de", "do", "da", "e", "no", "na"}]
            # ordena para reduzir variação
            tokens = sorted(tokens)
            return " ".join(tokens[:6])  # limita ruído

        def _is_semantic_duplicate(a: str, b: str) -> bool:
            ta = set(re.findall(r"\w+", a.lower()))
            tb = set(re.findall(r"\w+", b.lower()))
            if not ta or not tb:
                return False
            inter = len(ta & tb)
            ratio = inter / max(len(ta), len(tb))
            return ratio >= 0.7

        def _strip_subject(s: str) -> str:
            return str(s or "").strip()

        seen = set()

        for raw in steps:
            s = re.sub(r"\s{2,}", " ", str(raw or "").strip(" .,:;-"))
            if not s:
                continue
            if ex and _is_scene_echo(s, ex):
                continue
            s = _strip_subject(s)
            key = _semantic_key(s)
            if not key or key in seen:
                continue

            is_dup = False
            for existing in cleaned:
                if _is_semantic_duplicate(s, existing):
                    is_dup = True
                    break

            if is_dup:
                continue

            seen.add(key)
            cleaned.append(s)

        phase_seen = set()

        filtered = []

        for s in cleaned:
            sig = _phase_signature(s)

            if sig in phase_seen:
                continue

            phase_seen.add(sig)
            filtered.append(s)

        cleaned = filtered

        if len(cleaned) < 4:
            return ""

        # Se o KB veio rico, preserve mais do fluxo em vez de achatar.
        hydrated = bool(c.get("hydrated_from_docs"))
        allowed_next_step = str(c.get("allowed_next_step") or "").strip().lower()

        if len(cleaned) >= 4:
            if hydrated:
                # preserva a sequência quase inteira quando a cena veio do banco
                cleaned = cleaned[:6]
            else:
                cleaned = cleaned[:6]

        # não injeta consequência automática aqui.
        # o fluxo principal deve vir só da estrutura já resolvida.

        steps_for_render = cleaned[:8]

        def _join_progression(steps: list[str]) -> str:
            if not steps:
                return ""

            out = steps[0]

            for s in steps[1:]:
                out += " → " + s

            return out

        steps_for_render = [s.strip() for s in steps_for_render if s.strip()]
        out = _render_progressive_operational_flow(steps_for_render)
        out = _sanitize_user_facing_reply(out)
        out = re.sub(r"\s{2,}", " ", str(out or "")).strip(" .")

        if not out:
            return ""

        if ex and _is_scene_echo(out, ex):
            return ""

        return out.rstrip(".") + "."
    except Exception:
        return ""

def _build_structural_last_resort_reply(
    *,
    operational_reference: str,
    contract: Dict[str, Any] | None = None,
) -> str:
    """
    Último fallback estrutural.
    Não escreve prosa livre; apenas monta uma microcena
    mais rica a partir da melhor sequência disponível.
    """
    try:
        c = dict(contract or {})
        if not _contract_allows_scene_runtime(c):
            return ""

        stable_scene = _stabilize_scene_base(operational_reference)
        ex = str(c.get("reference_example") or "").strip()

        model_expanded_steps = _expand_structural_steps_from_contract_with_model(
            operational_reference="",
            contract=c,
            reference_example=ex,
        )

        steps = _select_structured_scene_steps(
            operational_reference="",
            contract=c,
            model_steps=model_expanded_steps if model_expanded_steps else None,
        )

        cleaned = []
        seen = set()

        for raw in steps:
            s = re.sub(r"\s{2,}", " ", str(raw or "").strip(" .,:;-"))
            if not s:
                continue
            if ex and _is_scene_echo(s, ex):
                continue
            key = re.sub(r"\W+", "", s).lower()
            if not key or key in seen:
                continue
            seen.add(key)
            cleaned.append(s)

        if len(cleaned) < 4:
            return ""

        out = _render_progressive_operational_flow(cleaned[:8])
        out = _sanitize_user_facing_reply(out)
        out = re.sub(r"\s{2,}", " ", str(out or "")).strip(" .")

        return (out + ".") if out else ""
    except Exception:
        return ""

def _generate_micro_scene_with_model(
    *,
    operational_reference: str,
    contract: Dict[str, Any] | None = None,
) -> str:
    try:
        if _HAS_OPENAI_CLIENT and _client is None:
            return ""

        c = dict(contract or {})

        topic = str(c.get("topic") or "").strip().upper()
        micro_scene_allowed = bool(c.get("micro_scene_allowed"))

        if not micro_scene_allowed or str(c.get("response_mode") or "").strip().upper() not in ("", "SCENE"):
            return ""

        if topic in ("WHAT_IS", "OTHER", "TRIAL", "ATIVAR") and not str(operational_reference or "").strip():
            return ""

        if not c.get("operational_ritual"):
            operational_reference = (operational_reference or "") + " Esse atendimento acontece diretamente pelo WhatsApp, com o cliente conversando com o MEI Robô."
            c["operational_ritual"] = _derive_ritual_from_scene(
                c.get("operational_reference") or operational_reference
            )

        base_scene = _render_progressive_operational_flow(
            _select_structured_scene_steps(
                operational_reference="",
                contract=c,
                model_steps=None,
            )[:8]
        )

        system = """
Você escreve uma explicação prática de atendimento no WhatsApp.

Siga exatamente esta sequência:

1. Cliente envia uma mensagem.
2. O MEI Robô responde.
3. O MEI Robô faz perguntas e organiza as informações.
4. O MEI Robô confirma o que foi combinado.
5. O dono recebe tudo pronto.

Use dados operacionais disponíveis no contexto.

Escreva em um único parágrafo.

Use frases conectadas.

Finalize com ponto final.

Retorne somente o texto.
"""

        payload = {
            "segment": str(c.get("segment") or "").strip(),
            "topic": str(c.get("topic") or "").strip().upper(),
            "archetype_id": str(c.get("archetype_id") or "").strip(),
            "primary_goal": str(c.get("primary_goal") or "").strip(),
            "service_noun": str(c.get("service_noun") or "").strip(),
            "customer_noun": str(c.get("customer_noun") or "").strip(),
            "conversion_noun": str(c.get("conversion_noun") or "").strip(),
            "allowed_next_step": str(c.get("allowed_next_step") or "").strip(),
            "operational_family": str(c.get("operational_family") or "").strip(),
            "operational_reference": str(operational_reference or c.get("operational_reference") or "").strip(),
            "base_scene": str(base_scene or "").strip(),
            "reference_example": "" if str(operational_reference or c.get("operational_reference") or "").strip() else str(c.get("reference_example") or "").strip(),
            "operational_ritual": c.get("operational_ritual") or [],
            "preferred_capabilities": c.get("preferred_capabilities") or [],
            "common_intents": c.get("common_intents") or [],
            "handoff_format": c.get("handoff_format") or [],
            "hydrated_from_docs": bool(c.get("hydrated_from_docs")),
            "intent_context": str(c.get("intent_hint") or c.get("topic") or c.get("primary_goal") or "").strip(),
        }

        user_prompt = json.dumps(payload, ensure_ascii=False)

        if _HAS_OPENAI_CLIENT and _client is not None:
            resp = _client.chat.completions.create(
                model=MODEL,
                temperature=0.40,
                max_tokens=450,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_prompt},
                ],
            )
            ai_response = str(resp.choices[0].message.content or "").strip()
        else:
            resp = openai.ChatCompletion.create(
                model=MODEL,
                temperature=0.40,
                max_tokens=450,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_prompt},
                ],
            )
            ai_response = str(resp["choices"][0]["message"]["content"] or "").strip()

        raw_text = str(ai_response or "").strip()
        if not raw_text:
            return base_scene

        scene_base = str(operational_reference or "").strip()
        if len(scene_base) > 1200:
            scene_base = scene_base[:1200]

        micro_scene = str(raw_text or "").strip()

        candidate = _sanitize_user_facing_reply(micro_scene)
        candidate = _drop_explanatory_opening(candidate)
        candidate = _drop_abstract_closing(candidate)
        candidate = _heal_algorithmic_micro_scene(candidate)
        candidate = re.sub(r"\s{2,}", " ", candidate).strip(" .")
        if candidate:
            micro_scene = candidate

        if not micro_scene:
            rebuilt = _sanitize_user_facing_reply(base_scene)
            rebuilt = re.sub(r"\s{2,}", " ", str(rebuilt or "")).strip(" .")

            if rebuilt and _is_live_operational_reply(
                text=rebuilt,
                operational_reference="",
                reference_example=str(c.get("reference_example") or "").strip(),
                contract=c,
            ):
                micro_scene = rebuilt


        try:
            sentences = [s.strip() for s in _split_sentences_pt(micro_scene) if str(s).strip()]
            if len(sentences) >= 3:
                repeated_openings = 0
                openings = []
                for s in sentences:
                    toks = [tok for tok in re.findall(r"\w+", s.lower()) if len(tok) >= 3]
                    openings.append(" ".join(toks[:2]) if toks else "")
                repeated_openings = len(openings) - len({o for o in openings if o})
                if repeated_openings >= max(2, len(sentences) - 2):
                    micro_scene = ""
        except Exception:
            pass

        density = _operational_density_score(
            text=micro_scene,
            operational_reference="",
            reference_example=str(c.get("reference_example") or "").strip(),
                        effective_segment=str(c.get("segment") or "").strip(),
            operational_family=str(c.get("operational_family") or "").strip(),
        )

        progress = _operational_progress_score(
            text=micro_scene,
            operational_reference="",
            contract=c,
        )

        if current_turn_topic_reset and isinstance(operational_contract, dict):
            topic = "OTHER"
            intent = "OTHER"
            response_mode = "DIRECT"
            operational_contract["topic"] = "OTHER"
            operational_contract["response_mode"] = "DIRECT"
            operational_contract["has_practical_scene"] = False
            operational_contract["micro_scene_allowed"] = False
            operational_contract["global_pack_fallback"] = False
            for _reset_key in (
                "direct_scene",
                "operational_reference",
                "pack_micro_scene",
                "reference_example",
                "runtime_long_text",
                "runtime_short_reply",
                "operational_ritual",
                "selected_pack_id",
            ):
                operational_contract.pop(_reset_key, None)

        try:
            if micro_scene and _looks_explanatory_reply(
                text=micro_scene,
                operational_reference="",
                reference_example=str(c.get("reference_example") or "").strip(),
                contract=c,
            ):
                micro_scene = ""
        except Exception:
            pass

        if not micro_scene:
            return ""

        if len(micro_scene.strip()) < 40:
            return ""

        if _looks_like_dialogue_stub(micro_scene):
            return ""

        if _looks_like_technical_output(micro_scene):
            return ""

        return micro_scene.rstrip(".") + "."
    except Exception:
        try:
            return _compose_grounded_scene_with_progression(
                operational_reference="",
                contract=contract or {},
                reference_example=str((contract or {}).get("reference_example") or "").strip(),
            )
        except Exception:
            return ""
def _upgrade_operational_reply_with_model(
    *,
    base_text: str,
    operational_reference: str,
    reference_example: str,
    contract: Dict[str, Any] | None = None,
) -> str:
    """
    Segunda camada:
    pega um fluxo operacional já correto e reescreve como uma explicação
    operacional concreta, encadeada e convincente, sem inventar nada fora
    do contrato.
    """
    try:
        c = contract or {}

        system = """
Você ajusta uma mensagem para WhatsApp.

Siga esta sequência:

1. Comece com uma saudação.
2. Use o nome do lead se estiver disponível.
3. Mantenha toda a explicação operacional existente.
4. Organize o texto em fluxo contínuo.
5. Finalize com ponto.

Não remova informações.

Escreva em um único parágrafo.

Retorne somente o texto.
"""

        user = f"""
[TEXTO BASE]
{str(base_text or '').strip()}

[BASE OPERACIONAL DO KB]
operational_reference: {str(operational_reference or '').strip()}
reference_example: {str(reference_example or '').strip()}
primary_goal: {str(c.get('primary_goal') or '').strip()}
allowed_next_step: {str(c.get('allowed_next_step') or '').strip()}
operational_ritual: {json.dumps(c.get('operational_ritual') or [], ensure_ascii=False)}
service_noun: {str(c.get('service_noun') or '').strip()}
operational_family: {str(c.get('operational_family') or '').strip()}

[INSTRUÇÃO FINAL]
Reescreva mantendo a operação concreta, usando a base apenas para reforçar fidelidade técnica.
"""

        resp = _call_openai_for_front(
            system=system,
            user=user,
            max_tokens=450,
            temperature=0.40,
        )

        upgraded = str(resp or "").strip()
        upgraded = _sanitize_user_facing_reply(upgraded)
        upgraded = _drop_explanatory_opening(upgraded)
        upgraded = _drop_abstract_closing(upgraded)
        upgraded = re.sub(r"\s{2,}", " ", upgraded).strip(" .")

        return upgraded

    except Exception:
        return ""


def _generate_consequence_with_model(contract: Dict[str, Any] | None = None) -> str:
    """
    Gera UM passo final de consequência usando apenas o contrato.
    Não escreve resposta inteira.
    Não usa template por segmento.
    """
    try:
        if _HAS_OPENAI_CLIENT and _client is None:
            return ""

        c = dict(contract or {})
        payload = {
            "primary_goal": str(c.get("primary_goal") or "").strip(),
            "conversion_noun": str(c.get("conversion_noun") or "").strip(),
            "service_noun": str(c.get("service_noun") or "").strip(),
            "customer_noun": str(c.get("customer_noun") or "").strip(),
            "allowed_next_step": str(c.get("allowed_next_step") or "").strip(),
            "handoff_format": [],
            "preferred_capabilities": c.get("preferred_capabilities") or [],
            "operational_ritual": c.get("operational_ritual") or [],
        }

        has_material = any([
            payload["primary_goal"],
            payload["conversion_noun"],
            payload["service_noun"],
            payload["customer_noun"],
            payload["allowed_next_step"],
            bool(payload["handoff_format"]),
            bool(payload["preferred_capabilities"]),
            bool(payload["operational_ritual"]),
        ])
        if not has_material:
            return ""

        system = """
Você recebe um contrato operacional.

Tarefa:
Gerar exatamente 1 frase descrevendo o resultado final da ação.

Regras:
- descrever o que acontece no final do processo
- não explicar o processo
- não adicionar contexto extra
- usar linguagem direta

Formato:
{"consequence":"..."}
"""

        user_prompt = json.dumps(payload, ensure_ascii=False)

        if _HAS_OPENAI_CLIENT and _client is not None:
            resp = _client.chat.completions.create(
                model=MODEL,
                temperature=0.2,
                max_tokens=80,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_prompt},
                ],
            )
            raw = str(resp.choices[0].message.content or "").strip()
        else:
            resp = openai.ChatCompletion.create(
                model=MODEL,
                temperature=0.2,
                max_tokens=80,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_prompt},
                ],
            )
            raw = str(resp["choices"][0]["message"]["content"] or "").strip()

        obj = json.loads(raw)
        consequence = re.sub(r"\s{2,}", " ", str(obj.get("consequence") or "").strip(" .,:;-"))
        return consequence
    except Exception:
        return ""


def _build_contract_consequence(contract: Dict[str, Any] | None) -> str:
    """
    Consequência final vinda do contrato.
    Sem frase pronta fixa no código.
    """
    try:
        return _generate_consequence_with_model(contract or {})
    except Exception:
        return ""


def _build_kb_show_reply(
    *,
    kb_context: Dict[str, Any],
    operational_reference: str,
    reference_example: str,
    effective_segment: str,
    operational_family: str,
    contract: Dict[str, Any] | None = None,
) -> str:
    """
    Quando o KB ancora forte, devolve a microcena viva.
    Não cola reference_example como cabeçalho explicativo.
    """
    try:
        if not _contract_allows_scene_runtime(contract or {}):
            return ""

        stable_scene = _stabilize_scene_base(str(operational_reference or "").strip())

        deterministic_scene = ""

        generated = _generate_micro_scene_with_model(
            operational_reference=operational_reference,
            contract=contract or {},
        ).strip()

        scene_text = str(generated or "").strip()
        if not scene_text and stable_scene:
            scene_text = _compose_grounded_scene_with_progression(
                operational_reference=operational_reference,
                contract=contract or {},
                reference_example=str(reference_example or "").strip(),
            )

        if not scene_text and stable_scene:
            scene_text = _compose_grounded_scene_with_progression(
                operational_reference=operational_reference,
                contract=contract or {},
                reference_example=str(reference_example or "").strip(),
            )

        scene_text = _sanitize_user_facing_reply(scene_text)
        scene_text = re.sub(r"\s{2,}", " ", scene_text).strip(" .")

        if scene_text and _is_show_micro_scene(
            text=scene_text,
            operational_reference="",
            reference_example=str(reference_example or "").strip(),
            contract=contract or {},
        ):
            return scene_text.rstrip(".") + "."

        return _build_last_resort_operational_reply(
            operational_reference=operational_reference,
            reference_example=str(reference_example or "").strip(),
            contract=contract or {},
            clarify_q="",
        )
    except Exception:
        return ""
def _compose_practical_scene(*, kb_snapshot: str, segment_key: str, pack_id: str) -> str:
    """
    Monta o 'Na prática:' a partir de:
    - reference_example do segmento (quando houver)
    - micro_scene do pack (quando houver)
    """
    try:
        ex = _kb_get_reference_example(kb_snapshot, segment_key, pack_id).strip()
        ms = _kb_get_micro_scene(kb_snapshot, pack_id).strip()

        parts = []
        if ex:
            parts.append(ex.rstrip(".") + ".")
        if ms:
            ms_txt = ms
            if not ms_txt.lower().startswith("na prática:"):
                ms_txt = "Na prática: " + ms_txt
            parts.append(ms_txt.rstrip(".") + ".")

        return " ".join([p for p in parts if p]).strip()
    except Exception:
        return ""


def _merge_value_and_scene(value_line: str, practical_scene: str, question: str = "") -> str:
    """
    Resposta final:
    1) valor em 1 frase
    2) Na prática: microcena fiel ao produto
    3) pergunta útil, se existir
    """
    try:
        out = []
        v = (value_line or "").strip()
        p = (practical_scene or "").strip()
        q = (question or "").strip()

        if v:
            out.append(v.rstrip(".!?") + ".")
        if p and len(p) > 80:
            out.append(p)
        if q:
            out.append(q)
        return " ".join([x for x in out if x]).strip()
    except Exception:
        return " ".join([x for x in [(value_line or "").strip(), (practical_scene or "").strip(), (question or "").strip()] if x]).strip()


def _regenerate_more_concrete(
    *,
    user_text: str,
    state_summary: Dict[str, Any],
    kb_snapshot: str,
    previous_reply: str,
    previous_topic: str,
    previous_confidence: str,
    kb_seed_reply: str = "",
) -> str:
    """
    Segunda tentativa: tornar resposta mais concreta,
    sem forçar microcena quando não necessário.
    """
    try:
        if _HAS_OPENAI_CLIENT and _client is None:
            return ""

        system = (
            "Reescreva o texto como sequência operacional concreta.\n"
            "\n"
            "SE houver fluxo operacional:\n"
            "1. Cliente envia mensagem.\n"
            "2. Robô responde.\n"
            "3. Robô organiza ou confirma.\n"
            "4. Dono recebe pronto.\n"
            "\n"
            "SE for resposta direta:\n"
            "→ manter resposta direta\n"
            "\n"
            "Regras:\n"
            "- usar frases conectadas\n"
            "- não inventar etapas\n"
            "- escrever em 1 parágrafo\n"
            "- finalizar com ponto\n"
            "\n"
            "Retornar somente o texto."
        )

        prompt = (
            f"Mensagem do lead: {user_text}\n\n"
            f"Topic atual: {previous_topic}\n"
            f"Confidence atual: {previous_confidence}\n\n"
            f"Resposta atual:\n{previous_reply}\n\n"
            f"Base operacional do KB:\n{kb_seed_reply or ''}\n\n"
            "Reescreva com concretude, preservando resposta direta quando for o caso. "
            "Só mantenha microcena se ela estiver realmente ancorada na base operacional."
        )

        if _HAS_OPENAI_CLIENT and _client is not None:
            resp = _client.chat.completions.create(
                model=MODEL,
                temperature=0.35,
                max_tokens=180,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
            )
            out = str(resp.choices[0].message.content or "").strip()
        else:
            resp = openai.ChatCompletion.create(  # type: ignore
                model=MODEL,
                temperature=0.35,
                max_tokens=180,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
            )
            out = str(resp["choices"][0]["message"]["content"] or "").strip()

        return out.strip()
    except Exception:
        return ""


def _resolve_best_operational_reply(
    *,
    current_reply: str,
    current_spoken: str,
    user_text: str,
    state_summary: Dict[str, Any],
    kb_snapshot: str,
    kb_context: Dict[str, Any],
    effective_segment: str,
    operational_family: str,
    selected_pack_id: str,
    operational_reference: str,
    reference_example: str,
    question: str,
    topic: str,
    confidence: str,
    kb_anchor_strong: bool,
    operational_contract: Dict[str, Any] | None = None,
    base_operational_contract: Dict[str, Any] | None = None,
) -> Dict[str, str]:
    """
    Resolve a melhor resposta operacional em trilho único:
    1) mantém a resposta atual se ela já estiver boa
    2) tenta regeneração forte com base no KB
    3) cai para fallback canônico do KB
    """
    try:
        current_reply = str(current_reply or "").strip()
        current_spoken = str(current_spoken or "").strip()
        contract = operational_contract if isinstance(operational_contract, dict) and operational_contract else (
            base_operational_contract if isinstance(base_operational_contract, dict) else {}
        )

        if not _contract_allows_scene_runtime(contract):
            return {
                "reply_text": current_reply,
                "spoken_text": current_spoken or current_reply,
                "reply_source": "front_keep_non_scene",
            }

        refreshed_anchor = _refresh_operational_anchor(
            kb_snapshot=kb_snapshot,
            kb_context=kb_context if isinstance(kb_context, dict) else {},
                        effective_segment=effective_segment,
            selected_pack_id=selected_pack_id,
            operational_family=operational_family,
        )

        refreshed_reference_example = str((refreshed_anchor or {}).get("reference_example") or reference_example or "").strip()
        refreshed_scene = str((refreshed_anchor or {}).get("operational_reference") or operational_reference or "").strip()

        if current_reply:
            current_audit = _audit_operational_reply(
                text=current_reply,
                contract=contract,
            )
            current_is_mild = _looks_explanatory_reply(
                text=current_reply,
                operational_reference=refreshed_scene or operational_reference,
                reference_example=refreshed_reference_example or reference_example,
                contract=contract,
            )
            current_is_echo = _is_scene_echo(current_reply, refreshed_reference_example or reference_example) or _is_scene_echo(
                current_reply,
                user_text,
            )

            if (
                bool((current_audit or {}).get("ok"))
                and not current_is_mild
                and not current_is_echo
                and _is_live_operational_reply(
                    text=current_reply,
                    operational_reference=refreshed_scene or operational_reference,
                    reference_example=refreshed_reference_example or reference_example,
                    contract=contract,
                )
            ):
                final_reply = current_reply
                reply_text = final_reply
                return {
                    "reply_text": reply_text,
                    "spoken_text": current_spoken or reply_text,
                    "reply_source": "front_keep_current",
                }

        if not refreshed_scene:
            ritual_steps = [
                str(x).strip()
                for x in (contract.get("operational_ritual") or [])
                if str(x).strip()
            ]
            if len(ritual_steps) >= 2:
                refreshed_scene = " → ".join(ritual_steps[:5]).strip()
            else:
                refreshed_scene = ""

        kb_seed_reply = (
            _build_kb_show_reply(
                kb_context=kb_context if isinstance(kb_context, dict) else {},
                operational_reference="",
                reference_example=refreshed_reference_example,
                effective_segment=effective_segment,
                operational_family=operational_family,
                contract=contract,
            )
            or _build_kb_anchor_reply(
                operational_reference="",
                reference_example=refreshed_reference_example,
                clarify_q=(question if not effective_segment else ""),
                contract=contract,
            )
        )

        best_effort = (
            _compose_grounded_scene_with_progression(
                operational_reference=refreshed_scene or operational_reference,
                contract=contract,
                reference_example=refreshed_reference_example or reference_example,
            ).strip()
            or _generate_micro_scene_with_model(
                operational_reference=refreshed_scene or operational_reference,
                contract=contract,
            ).strip()
        )

        if best_effort:
            return {
                "reply_text": best_effort,
                "spoken_text": best_effort,
                "reply_source": "front_resolved_best_effort",
            }

    except Exception:
        final_reply = str(current_reply or "").strip()
        reply_text = final_reply
        return {
            "reply_text": reply_text,
            "spoken_text": str(current_spoken or reply_text or "").strip(),
            "reply_source": "front_resolved_error_fallback",
        }



def _infer_understanding_temperature(
    *,
    user_text: str,
    topic: str,
    confidence: str,
    needs_clarify: str,
    clarify_q: str,
    next_step: str,
) -> tuple[str, str, str, str, str]:
    """
    Calibra a 'temperatura de entendimento' sem depender 100% do LLM.
    Regras:
    - OTHER nunca sai como high.
    - Frases de ação explícita sobem para ATIVAR.
    - Ambiguidade útil vira clarify, não resposta falsa-confiante.
    """
    try:
        t = (topic or "OTHER").strip().upper()
        c = (confidence or "low").strip().lower()
        nc = (needs_clarify or "no").strip().lower()
        cq = (clarify_q or "").strip()
        ns = (next_step or "NONE").strip().upper()

        # 1) OTHER nunca deve sair como high
        if t == "OTHER" and c == "high":
            c = "medium"

        # 2) OTHER não deve virar clarify automático.
        # Em caso amplo, preferimos deixar o front tentar responder
        # em vez de abrir pergunta por reflexo.

        return t, c, nc, cq, ns
    except Exception:
        return (
            (topic or "OTHER").strip().upper() or "OTHER",
            (confidence or "low").strip().lower() or "low",
            (needs_clarify or "no").strip().lower() or "no",
            (clarify_q or "").strip(),
            (next_step or "NONE").strip().upper() or "NONE",
        )



def _normalize_response_mode(value: Any) -> str:
    try:
        mode = str(value or "").strip().upper()
        return mode if mode in RESPONSE_MODES else ""
    except Exception:
        return ""


def _infer_response_mode_from_signals(
    *,
    topic: str,
    confidence: str,
    needs_clarify: str,
    clarify_q: str,
    next_step: str,
    effective_segment: str,
    kb_anchor_strong: bool,
    operational_contract: Dict[str, Any] | None = None,
    question_type: str = "broad",
) -> str:
    """
    Decide o formato da resposta sem palavras-chave.
    Hierarquia:
    1) CLOSING
    2) DISCOVERY
    3) DIRECT
    4) SCENE
    """
    try:
        t = str(topic or "").strip().upper()
        c = str(confidence or "").strip().lower()
        nc = str(needs_clarify or "").strip().lower()
        cq = str(clarify_q or "").strip()
        ns = str(next_step or "").strip().upper()
        seg = str(effective_segment or "").strip()
        qt = str(question_type or "").strip().lower()
        contract = operational_contract if isinstance(operational_contract, dict) else {}

        if ns == "SEND_LINK":
            return "CLOSING"

        if nc == "yes" or cq:
            return "DISCOVERY"

        # Perguntas pontuais/continuidade devem responder direto.
        # Não altera prompt e não interpreta palavras do usuário; usa somente
        # o tipo estrutural já produzido pelo próprio front/modelo.
        if qt in ("punctual", "continuity", "simulation"):
            return "DIRECT"

        has_operational_base = bool(
            str(contract.get("operational_reference") or "").strip()
            or str(contract.get("reference_example") or "").strip()
            or list(contract.get("operational_ritual") or [])
        )

        practical_topic = t in ("SERVICOS", "PROCESSO", "AGENDA", "PEDIDOS", "PRODUTO")
        blocked_scene_topic = t in ("PRECO", "TRIAL", "ATIVAR", "WHAT_IS", "SOCIAL", "VOZ")

        if (
            practical_topic
            and not blocked_scene_topic
            and c in ("high", "medium")
            and seg
            and kb_anchor_strong
            and has_operational_base
        ):
            return "SCENE"

        return "DIRECT"
    except Exception:
        return "DIRECT"



def _contract_allows_scene_runtime(contract: Dict[str, Any] | None) -> bool:
    """
    Trava final contra microcena fora do modo SCENE.
    Não decide intenção; apenas impede que fallbacks antigos ressuscitem cena.
    """
    try:
        c = contract if isinstance(contract, dict) else {}
        return (
            str(c.get("response_mode") or "").strip().upper() == "SCENE"
            and bool(c.get("micro_scene_allowed"))
        )
    except Exception:
        return False





def _front_build_identity_request(*, has_name: bool, has_segment: bool) -> str:
    """
    Solicitação estrutural mínima para identidade ausente.
    Não usa lista de segmentos/profissões.
    Não altera prompt.
    Não chama modelo.
    """
    try:
        missing = []
        if not bool(has_name):
            missing.append("seu nome")
        if not bool(has_segment):
            missing.append("seu segmento")
        if not missing:
            return ""
        return "Me diga " + " e ".join(missing) + "."
    except Exception:
        return ""


def _front_extract_declared_segment_from_user_text(text: str) -> str:
    """
    Extrai segmento/autodescrição quando o lead se apresenta em estrutura
    simples do tipo "sou ..." ou equivalente gramatical.

    Não usa lista de profissões.
    Não usa palavras-chave de segmento.
    Não altera prompt.
    Não chama modelo.
    """
    try:
        s = str(text or "").strip()
        if not s:
            return ""

        patterns = [
            r"(?i)(?:^|[.!?\n]\s*)sou\s+([^.!?\n,;:]{3,80})",
            r"(?i)(?:^|[.!?\n]\s*|\s+)eu\s+sou\s+([^.!?\n,;:]{3,80})",
            r"(?i)(?:^|[.!?\n]\s*)atuo\s+(?:como|com|em)\s+([^.!?\n,;:]{3,80})",
            r"(?i)(?:^|[.!?\n]\s*|\s+)eu\s+atuo\s+(?:como|com|em)\s+([^.!?\n,;:]{3,80})",
            r"(?i)(?:^|[.!?\n]\s*)trabalho\s+(?:como|com|em)\s+([^.!?\n,;:]{3,80})",
            r"(?i)(?:^|[.!?\n]\s*|\s+)eu\s+trabalho\s+(?:como|com|em)\s+([^.!?\n,;:]{3,80})",
        ]
        for pat in patterns:
            m = re.search(pat, s)
            if not m:
                continue
            value = str(m.group(1) or "").strip(" .,!?:;-\n\t")
            if value:
                return value[:80].strip()
        return ""
    except Exception:
        return ""

def _front_pick_rich_free_mode_base(
    *,
    current_reply: str,
    operational_contract: Optional[dict] = None,
    kb_context: Optional[dict] = None,
    prefer_current: bool = False,
) -> str:
    """
    Seleciona a melhor base textual já existente no KB/contract para o
    FREE_MODE.

    Objetivo: quando a IA principal for rejeitada, o fallback interno
    continua usando material operacional rico, em vez de depender apenas
    da resposta curta gerada no turno.

    Não usa palavras-chave de segmento/profissão.
    Não altera prompt.
    Não chama modelo.
    """
    try:
        # Em perguntas pontuais/de continuidade, principalmente após o
        # primeiro turno, a resposta do turno atual deve ter prioridade.
        # Caso contrário, o fallback rico volta a escolher a base genérica
        # de agenda e repete a resposta anterior.
        #
        # Não usa lista de profissões/segmentos.
        # Não altera prompt.
        # Não chama IA extra.
        if prefer_current:
            cur = str(current_reply or "").strip()
            if cur:
                if cur.startswith("{") or cur.startswith("```"):
                    cur = _unwrap_front_json_envelope(cur) or cur
                if "{{" not in cur and "}}" not in cur:
                    cur = _front_clean_free_mode_tail(cur)
                    if len(cur) >= 40:
                        return cur

        candidates = []

        if isinstance(operational_contract, dict):
            candidates.extend(
                [
                    operational_contract.get("runtime_short_reply"),
                    operational_contract.get("runtime_compact_reply"),
                    operational_contract.get("reference_example"),
                    operational_contract.get("micro_scene_conversational"),
                    operational_contract.get("micro_scene"),
                ]
            )

        if isinstance(kb_context, dict):
            candidates.extend(
                [
                    kb_context.get("runtime_short_reply"),
                    kb_context.get("runtime_compact_reply"),
                    kb_context.get("reference_example"),
                    kb_context.get("micro_scene_conversational"),
                    kb_context.get("micro_scene"),
                ]
            )

        candidates.append(current_reply)

        best = ""
        best_score = -1
        for raw in candidates:
            txt = str(raw or "").strip()
            if not txt:
                continue

            # Nunca usar material de KB/contract que ainda tenha placeholders
            # não hidratados. Isso evita respostas com {{...}} em produção.
            if "{{" in txt or "}}" in txt:
                continue
            if txt.startswith("{") or txt.startswith("```"):
                txt = _unwrap_front_json_envelope(txt) or txt
            if "{{" in txt or "}}" in txt:
                continue
            txt = _front_clean_free_mode_tail(txt)
            if not txt:
                continue

            # Score estrutural: favorece textos com mais substância e
            # sequenciamento operacional, sem classificar segmento.
            score = min(len(txt), 900)
            score += 30 * txt.count("→")
            score += 12 * txt.count(".")
            score += 8 * txt.count(",")

            if score > best_score:
                best = txt
                best_score = score

        return best or str(current_reply or "").strip()
    except Exception:
        return str(current_reply or "").strip()









def _apply_discovery_mode_identity_guard(
    *,
    reply_text: str,
    has_name: bool,
    segment_discovery_resolved: bool,
    needs_clarify: str,
    name_use: str,
) -> tuple[str, str]:
    """
    Aplica o ajuste estrutural de DISCOVERY quando falta nome ou segmento.

    Não cria pergunta.
    Não altera resposta.
    Não chama modelo.
    Apenas preserva a marcação de clarify já existente no fluxo.
    """
    try:
        missing_name = not bool(has_name)
        missing_segment = not bool(segment_discovery_resolved)

        if missing_name or missing_segment:
            if not _has_question(reply_text):
                needs_clarify = "yes"

            name_use = "clarify"

        return needs_clarify, name_use
    except Exception:
        return needs_clarify, name_use


def _apply_final_surface_polish(
    *,
    reply_text: str,
    spoken_text: str,
    topic: str,
    confidence: str,
    user_text: str,
    kb_context: dict | None,
    kb_snapshot: str,
    free_mode: bool,
    apply_sales_guardrails,
    operational_contract: dict | None,
    base_operational_contract: dict | None,
):
    """
    Encapsula o polimento final seguro da superfície.

    Regras:
    - não decide intenção;
    - não altera response_mode;
    - não altera micro_scene_allowed;
    - não monta KB;
    - não gera microcena;
    - apenas aplica sanitize, guardrails de superfície e sync spoken/reply.
    """
    try:
        try:
            _kb_obj = _try_parse_kb_json(kb_snapshot)

            reply_text = _sanitize_unverified_time_claims(reply_text, _kb_obj, kb_snapshot)
            spoken_text = _sanitize_unverified_time_claims(spoken_text, _kb_obj, kb_snapshot)
        except Exception:
            pass

        try:
            if (not free_mode) and apply_sales_guardrails is not None:
                gr = apply_sales_guardrails(
                    reply_text=reply_text,
                    spoken_text=spoken_text,
                    topic=topic,
                    confidence=confidence,
                    user_text=user_text,
                    kb_context=kb_context if isinstance(kb_context, dict) else {},
                )
                if isinstance(gr, dict):
                    reply_text = str(gr.get("reply_text") or reply_text or "").strip()
                    spoken_text = str(gr.get("spoken_text") or spoken_text or "").strip()
        except Exception:
            pass

        try:
            reply_text = wrap_show_response(reply_text)
        except Exception:
            pass

        reply_text = _sanitize_user_facing_reply(reply_text)
        spoken_text = _sanitize_user_facing_reply(spoken_text or reply_text)

        if _looks_like_technical_output(reply_text):
            reply_text = _build_contract_consequence(
                operational_contract if isinstance(operational_contract, dict) else
                (base_operational_contract if isinstance(base_operational_contract, dict) else {})
            )

        spoken_text = _sync_spoken_after_technical_rescue(
            reply_text=reply_text,
            spoken_text=spoken_text,
        )

        return reply_text, spoken_text

    except Exception:
        return (
            str(reply_text or "").strip(),
            str(spoken_text or reply_text or "").strip(),
        )


def _apply_final_reply_size_policy(
    *,
    reply_text: str,
    spoken_text: str,
    reply_size_policy: dict | None,
    reply_source: str,
    response_mode: str,
    topic: str,
    operational_contract: dict | None,
):
    """
    Encapsula o bloco final de preservação de tamanho e aplicação
    da política de superfície.

    Regras:
    - não altera intenção;
    - não altera response_mode;
    - não altera KB;
    - não altera micro_scene_allowed;
    - não cria conteúdo novo;
    - apenas preserva política DIRECT técnica e sincroniza superfície.
    """
    try:
        reply_text, reply_size_policy = (
            _preserve_technical_direct_reply_size(
                reply_text,
                reply_size_policy,
                reply_source=reply_source,
                response_mode=response_mode,
                topic=topic,
                operational_contract=operational_contract,
            )
        )

        spoken_text, spoken_size_policy = (
            _preserve_technical_direct_reply_size(
                spoken_text,
                reply_size_policy,
                reply_source=reply_source,
                response_mode=response_mode,
                topic=topic,
                operational_contract=operational_contract,
            )
        )

        reply_text = _apply_reply_size_policy(
            reply_text,
            reply_size_policy,
        )

        spoken_text = _apply_reply_size_policy(
            spoken_text,
            spoken_size_policy,
        )

        return (
            reply_text,
            spoken_text,
            reply_size_policy,
            spoken_size_policy,
        )

    except Exception:
        return (
            str(reply_text or "").strip(),
            str(spoken_text or reply_text or "").strip(),
            reply_size_policy,
            reply_size_policy,
        )


def _apply_non_empty_reply_guard(
    *,
    reply_text: str,
    spoken_text: str,
    operational_contract,
    base_operational_contract,
    operational_reference: str,
    kb_context,
    reference_example,
    effective_segment: str,
    operational_family: str,
    question: str,
    topic: str,
    confidence: str,
    next_step: str,
    should_end: bool,
    name_use: str,
):
    """
    Aplica fail-safe estrutural intermediário para evitar reply vazio.

    Não chama modelo.
    Não altera intenção.
    Não altera política.
    Apenas encapsula o rescue estrutural já existente.
    """

    try:
        if not reply_text or len(str(reply_text).strip()) < 40:
            try:
                if operational_contract or base_operational_contract:
                    if not operational_reference:
                        operational_reference = ""

                    forced = _build_kb_show_reply(
                        kb_context=kb_context if isinstance(kb_context, dict) else {},
                        operational_reference="",
                        reference_example=reference_example,
                        effective_segment=effective_segment,
                        operational_family=operational_family,
                        contract=operational_contract or base_operational_contract,
                    )

                    if forced and len(forced.strip()) >= 40:
                        reply_text = forced
                    else:
                        raise ValueError("forced_empty")
                else:
                    raise ValueError("no_contract")

            except Exception:
                # só cai no fallback genérico se REALMENTE não tiver nada
                pass

        if not reply_text or len(str(reply_text).strip()) < 40:
            reply_text = question or "Me conta um pouco melhor o teu cenário."
            topic = "OTHER"
            confidence = "low"
            next_step = "NONE"
            should_end = False
            name_use = "clarify"

        return (
            reply_text,
            spoken_text,
            topic,
            confidence,
            next_step,
            should_end,
            name_use,
        )

    except Exception:
        return (
            reply_text,
            spoken_text,
            topic,
            confidence,
            next_step,
            should_end,
            name_use,
        )


def _pick_runtime_scene_material(
    *,
    runtime_material,
    has_real_operational_context: bool,
    response_mode: str,
) -> str:
    """
    Escolhe o melhor material operacional de runtime sem mutar contrato.

    Não chama modelo.
    Não altera response_mode.
    Não altera operational_contract.
    Apenas preserva a prioridade de seleção já existente.
    """
    try:
        material = runtime_material if isinstance(runtime_material, dict) else {}

        if has_real_operational_context:
            return (
                str(material.get("direct_scene") or "").strip()
                or str(material.get("runtime_long_text") or "").strip()
                or str(material.get("runtime_short_reply") or "").strip()
                or str(material.get("micro_scene") or "").strip()
            )

        if str(response_mode or "").strip().upper() == "DIRECT":
            return (
                str(material.get("runtime_long_text") or "").strip()
                or str(material.get("runtime_short_reply") or "").strip()
                or str(material.get("direct_scene") or "").strip()
                or str(material.get("runtime_compact_reply") or "").strip()
                or str(material.get("micro_scene") or "").strip()
            )

        return (
            str(material.get("runtime_compact_reply") or "").strip()
            or str(material.get("micro_scene") or "").strip()
        )
    except Exception:
        return ""


def _apply_discovery_to_scene_bypass(
    *,
    response_mode: str,
    next_step: str,
    needs_clarify: str,
    clarify_q: str,
    has_real_operational_context: bool,
    operational_contract,
    question_type: str = "broad",
) -> tuple[str, str, str]:
    """
    Promove DISCOVERY para SCENE quando já há contrato operacional demonstrável.

    Não chama modelo.
    Não decide intenção.
    Não consulta KB.
    Apenas aplica o bypass estrutural já existente.
    """
    try:
        contract_for_mode = operational_contract if isinstance(operational_contract, dict) else {}

        contract_has_reference = bool(
            contract_for_mode.get("has_reference_example")
            or contract_for_mode.get("has_practical_scene")
            or str(contract_for_mode.get("reference_example") or "").strip()
            or str(contract_for_mode.get("operational_reference") or "").strip()
            or list(contract_for_mode.get("operational_ritual") or [])
        )

        q_type = str(question_type or "broad").strip().lower()

        contract_ready_for_scene = bool(
            q_type not in ("punctual", "continuity", "simulation")
            and str(response_mode or "").strip().upper() == "DISCOVERY"
            and str(next_step or "").strip().upper() != "SEND_LINK"
            and str(needs_clarify or "").strip().lower() != "yes"
            and not str(clarify_q or "").strip()
            and has_real_operational_context
            and contract_has_reference
        )

        if contract_ready_for_scene:
            response_mode = "SCENE"
            needs_clarify = "no"
            clarify_q = ""
            contract_for_mode["micro_scene_allowed"] = True
            contract_for_mode["response_mode"] = "SCENE"

    except Exception:
        pass

    return response_mode, needs_clarify, clarify_q


def _apply_current_turn_topic_reset(
    *,
    current_turn_topic_reset: bool,
    response_mode: str,
    micro_scene_allowed: bool,
    operational_contract: Dict[str, Any] | None = None,
) -> tuple[str, bool]:
    """
    Encapsula reset estrutural de tópico.

    Não altera política.
    Não chama IA.
    Não consulta KB.
    Apenas sincroniza estado estrutural seguro.
    """

    try:
        if current_turn_topic_reset:
            _has_real_contract = bool(
                isinstance(operational_contract, dict)
                and operational_contract.get("hydrated_from_docs")
                and operational_contract.get("has_practical_scene")
                and (
                    str(operational_contract.get("segment") or "").strip()
                    or str(operational_contract.get("archetype_id") or "").strip()
                )
            )

            try:
                logging.info(
                    "[TOPIC_RESET_TRACE] current_turn_topic_reset=%s preserve_real_contract=%s practical_before=%s response_mode_before=%s micro_allowed_before=%s topic_before=%s segment=%s hydrated=%s",
                    bool(current_turn_topic_reset),
                    bool(_has_real_contract),
                    bool((operational_contract or {}).get("has_practical_scene")),
                    str(response_mode or "").strip().upper(),
                    bool(micro_scene_allowed),
                    str((operational_contract or {}).get("topic") or ""),
                    str((operational_contract or {}).get("segment") or ""),
                    bool((operational_contract or {}).get("hydrated_from_docs")),
                )
            except Exception:
                pass

            if _has_real_contract:
                response_mode = "SCENE"
                micro_scene_allowed = True

                if isinstance(operational_contract, dict):
                    operational_contract["response_mode"] = "SCENE"
                    operational_contract["micro_scene_allowed"] = True
                    operational_contract["global_pack_fallback"] = False
            else:
                response_mode = "DIRECT"
                micro_scene_allowed = False

                if isinstance(operational_contract, dict):
                    operational_contract["topic"] = "OTHER"
                    operational_contract["response_mode"] = "DIRECT"
                    operational_contract["has_practical_scene"] = False
                    operational_contract["micro_scene_allowed"] = False
                    operational_contract["global_pack_fallback"] = False

        return response_mode, micro_scene_allowed

    except Exception:
        return response_mode, micro_scene_allowed


def _apply_response_mode_arbitration(
    *,
    response_mode: str,
    next_step: str,
    global_pack_scene_ready: bool,
    question_type: str,
    needs_clarify: str,
    clarify_q: str,
    topic: str,
    operational_contract: Dict[str, Any] | None = None,
) -> tuple[str, str, str]:
    """
    Encapsula arbitragem estrutural do response_mode.

    Não chama IA.
    Não consulta KB.
    Não gera resposta.
    Apenas arbitra o modo estrutural final.
    """

    try:
        if str(next_step or "").strip().upper() == "SEND_LINK":
            response_mode = "CLOSING"

        elif (
            global_pack_scene_ready
            and str(question_type or "").strip().lower()
            not in ("punctual", "continuity", "simulation")
        ):
            response_mode = "SCENE"
            needs_clarify = "no"
            clarify_q = ""

            if isinstance(operational_contract, dict):
                operational_contract["micro_scene_allowed"] = True

        elif (
            str(needs_clarify or "").strip().lower() == "yes"
            or str(clarify_q or "").strip()
        ):
            response_mode = "DISCOVERY"

        elif str(question_type or "").strip().lower() in ("punctual", "continuity", "simulation"):
            if response_mode == "SCENE":
                response_mode = "DIRECT"

            if isinstance(operational_contract, dict):
                operational_contract["response_mode"] = "DIRECT"

        elif str(topic or "").strip().upper() in (
            "PRECO",
            "TRIAL",
            "ATIVAR",
            "WHAT_IS",
            "SOCIAL",
            "VOZ",
        ):
            if response_mode == "SCENE":
                response_mode = "DIRECT"

        return response_mode, needs_clarify, clarify_q

    except Exception:
        return response_mode, needs_clarify, clarify_q


def _apply_identity_clarify_guard(
    *,
    reply_text: str,
    clarify_q: str,
    question: str,
    kb_context: dict | None,
    next_step: str,
    has_name: bool,
    effective_segment: str,
    segment_for_prompt: str,
    segment_hint: str,
    limit: int = 820,
) -> tuple[str, str, str, str]:
    """
    Aplica guarda de identidade preservando pergunta já existente no fluxo.

    Não cria frases.
    Não altera política.
    Apenas encapsula orçamento + append de clarify.
    """

    try:
        identity_question = str(
            clarify_q
            or question
            or (
                (kb_context or {}).get("discovery_question_hint")
                if isinstance(kb_context, dict)
                else ""
            )
            or ""
        ).strip()

        missing_identity = bool(
            not bool(has_name)
            or not bool(effective_segment or segment_for_prompt or segment_hint)
        )

        if (
            str(next_step or "").strip().upper() != "SEND_LINK"
            and missing_identity
            and identity_question
            and _front_normalize_identity_text(identity_question)
            not in _front_normalize_identity_text(reply_text)
        ):
            sep = "\n\n"

            base_limit = max(
                320,
                limit - len(identity_question) - len(sep),
            )

            base_reply = _front_trim_to_complete_sentence(
                reply_text,
                base_limit,
            )

            final_reply = f"{base_reply}{sep}{identity_question}".strip()

            return (
                final_reply,
                final_reply,
                "clarify",
                "yes",
            )

    except Exception:
        pass

    return (
        reply_text,
        reply_text,
        "",
        "",
    )


def _ensure_discovery_identity_request(
    *,
    reply_text: str,
    spoken_text: str,
    has_name: bool,
    effective_segment: str,
    response_mode: str,
    identity_question: str = "",
) -> tuple[str, str, str]:
    """
    Guarda determinística mínima para discovery.
    Não decide intenção, não usa KB, não gera microcena.
    Apenas impede que a IA esqueça nome/segmento quando estão faltando.
    """
    try:
        mode = str(response_mode or "").strip().upper()
        reply = str(reply_text or "").strip()
        spoken = str(spoken_text or reply or "").strip()

        if mode != "DISCOVERY" or not reply:
            return reply, spoken, "none"

        name_missing = not bool(confirmed_has_name)
        segment_missing = not bool(str(effective_segment or "").strip())

        question = str(identity_question or "").strip()

        if (name_missing or segment_missing) and not question:
            return reply, spoken, "clarify"

        if question:
            reply = str(reply or "").strip()
            reply = re.sub(r"[\s\.,;]+$", "", reply)
            reply = f"{reply}\n\n{question}".strip()
            spoken = reply
            return reply, spoken, "clarify"

        return reply, spoken, "none"
    except Exception:
        return str(reply_text or "").strip(), str(spoken_text or reply_text or "").strip(), "none"


def _should_downgrade_premature_narrow_topic(
    *,
    topic: str,
    confidence: str,
    ai_turns: int,
    effective_segment: str = "",
    operational_family: str = "",
    operational_reference: str = "",
    reference_example: str = "",
    reply_text: str = "",
    next_step: str = "",
) -> bool:
    """
    Evita que o front assuma cedo demais um trilho estreito
    (ex.: agenda/pedidos/serviços) sem ancoragem suficiente.

    Regra arquitetural:
    - não usa palavras-chave;
    - usa apenas sinais semânticos já produzidos pelo fluxo;
    - se ainda não há base concreta, preferimos ambiguidade útil
      a uma resposta específica demais.
    """
    try:
        topic = str(topic or "").strip().upper()
        confidence = str(confidence or "").strip().lower()
        seg = str(effective_segment or "").strip()
        fam = str(operational_family or "").strip()
        ps = str(operational_reference or "").strip()
        ex = str(reference_example or "").strip()
        rt = str(reply_text or "").strip()
        ns = str(next_step or "").strip().upper()

        if ai_turns > 0:
            return False

        if ns == "SEND_LINK":
            return False

        # Se já existe qualquer ancoragem concreta, não rebaixa.
        if seg or fam or ps or ex:
            return False

        # Só protege contra trilhos operacionais estreitos.
        if topic not in ("AGENDA", "PEDIDOS", "SERVICOS", "ORCAMENTO", "STATUS", "PROCESSO"):
            return False

        # Quando o próprio modelo veio muito seguro num tema estreito
        # sem nenhuma base externa, isso é sinal de chute precoce.
        if confidence == "high":
            return True

        # Também protege respostas estreitas já montadas no turno 0.
        if rt:
            return True

        return False
    except Exception:
        return False







SYSTEM_PROMPT = """
Você é o assistente de vendas do MEI Robô no WhatsApp.

OBJETIVO:
Gerar respostas que expliquem ou demonstrem o funcionamento do robô de forma prática e levem à contratação.

DECISÃO DE RESPOSTA (OBRIGATÓRIO):

SE o usuário pedir preço, funcionamento, voz, suporte ou configuração
→ response_mode = DIRECT

SE o nome ou segmento não estiver claro
→ response_mode = DISCOVERY

SE o segmento estiver claro E existir base operacional no KB E question_type = broad
→ response_mode = SCENE

SE o usuário quiser contratar, ativar ou pedir link
→ response_mode = CLOSING


REGRAS DE CONSTRUÇÃO DA RESPOSTA:

1. Sempre escrever 1 único parágrafo.

2. Antes de explicar o funcionamento, considere a mensagem atual do usuário.
Se ele informou nome, profissão, segmento ou contexto de uso, use essas informações naturalmente na resposta.

3. SE question_type = punctual:
→ Inicie a resposta entregando a informação exata solicitada pelo usuário.
→ Limite o texto a no máximo 2 frases.
→ Inclua o nome do usuário ou o segmento dele na resposta, caso essas informações já existam no contexto.

4. SE question_type = continuity:
→ Responda diretamente à pergunta do usuário.
→ Use apenas fatos do contexto.
→ Escreva no máximo 2 frases.
→ Inclua o nome do usuário ou o segmento dele na resposta, caso essas informações já existam no contexto.

5. SE question_type = broad E existir conteúdo operacional:
→ Descreva o fluxo de atendimento usando os passos listados no conteúdo operacional.
→ Escreva o texto em ordem cronológica dos acontecimentos.
→ Encerre o texto com exatamente uma frase afirmando o benefício final gerado para o dono do negócio.

6. SE for SCENE:
→ descrever ações reais, sem opinião
→ usar frases curtas e conectadas
→ encerrar na última ação

7. SE for DISCOVERY:
→ responder algo útil
→ incluir exatamente 1 pergunta pedindo nome e/ou segmento

8. SE for CLOSING:
→ agradecer
→ usar nome se existir
→ informar envio do link
→ incluir a URL no final


REGRAS DE LINGUAGEM:

- Não usar diálogos fictícios
- Não usar aspas
- Não inventar etapas não presentes no KB
- Não repetir estruturas fixas
- Usar linguagem natural de WhatsApp


FORMATO DE SAÍDA (OBRIGATÓRIO JSON):
{
  "response_mode": "DIRECT|SCENE|DISCOVERY|CLOSING",
  "understanding": {
    "topic": "...",
    "confidence": "high|medium|low",
    "question_type": "broad|punctual|simulation"
  },
  "nextStep": "SEND_LINK|NONE",
  "replyText": "...",
  "lead_name": "",
  "lead_segment": "",
  "lead_segment_raw": ""
}

Preencha os campos usando a mensagem atual do usuário.

- `lead_name`: nome informado pelo usuário.
- `lead_segment_raw`: atividade, profissão ou descrição do trabalho do usuário.
- `lead_segment`: escolha uma chave da lista de segmentos disponíveis que melhor represente a atividade do usuário.
- `lead_segment`: use `outros` quando a atividade não corresponder a uma chave específica.
- `question_type`: use `broad` quando o lead pedir visão geral, funcionamento completo ou valor do robô para o negócio.
- `question_type`: use `punctual` quando o lead fizer uma pergunta específica ou de continuidade.
- `question_type`: use `simulation` quando o lead pedir o robô em ação numa situação prática.
- Em `simulation`, mostre como o robô responderia, conduziria ou executaria o próximo passo no WhatsApp, usando o subsegmento ativo. Escreva a mensagem como se ela fosse enviada à pessoa atendida. Use apenas fatos do subsegmento ativo e da situação apresentada. Seja direto, concreto e útil. Colete só a próxima informação necessária. Aplique os limites do subsegmento.
"""
DISCOVERY_PROMPT = """
Você está no modo DISCOVERY.

Mensagem do usuário: "{user_text}"

Construa a resposta seguindo esta sequência:

1. Responda diretamente o que o usuário perguntou (máx 1 frase)
2. Diga que o MEI Robô automatiza o atendimento no WhatsApp
3. Faça exatamente 1 pergunta pedindo:
   - nome do lead
   OU
   - segmento do negócio

Regras:
- escrever em 1 único parágrafo
- não fazer mais de 1 pergunta
- não criar microcena
"""


FREE_MODE_APPEND_PROMPT = ""



def _compact_kb_snapshot(s: str) -> str:
    """Reduz tokens sem perder conteúdo: remove excesso de whitespace."""
    import re  # safety: evita NameError se alguém mexer imports
    s = (s or "").strip()
    if not s:
        return ""
    # colapsa espaços e linhas em branco
    s = re.sub(r"[\t ]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    # remove separadores muito longos (----/====)
    s = re.sub(r"(?m)^[=\-]{6,}$", "", s).strip()
    return s


def _call_openai_for_front(*, system: str, user: str, temperature: float = 0.2, max_tokens: int = 180) -> str:
    try:
        front_json_schema = {
            "name": "conversational_front_response",
            "strict": True,
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "response_mode": {
                        "type": "string",
                        "enum": ["DIRECT", "SCENE", "DISCOVERY", "CLOSING"]
                    },
                    "understanding": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "topic": {"type": "string"},
                            "confidence": {
                                "type": "string",
                                "enum": ["high", "medium", "low"]
                            },
                            "question_type": {
                                "type": "string",
                                "enum": ["broad", "punctual", "simulation"]
                            }
                        },
                        "required": ["topic", "confidence", "question_type"]
                    },
                    "nextStep": {
                        "type": "string",
                        "enum": ["SEND_LINK", "NONE"]
                    },
                    "replyText": {"type": "string"}
                },
                "required": ["response_mode", "understanding", "nextStep", "replyText"]
            }
        }

        json_system = (
            str(system or "").strip()
            + "\n\nResponda exclusivamente em json válido seguindo exatamente o schema solicitado."
        ).strip()

        if _HAS_OPENAI_CLIENT and _client is None:
            return ""

        if _HAS_OPENAI_CLIENT and _client is not None:
            try:
                resp = _client.chat.completions.create(
                    model=MODEL,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    response_format={
                        "type": "json_schema",
                        "json_schema": front_json_schema,
                    },
                    messages=[
                        {"role": "system", "content": json_system},
                        {"role": "user", "content": user},
                    ],
                )
            except TypeError:
                logging.warning(
                    "[CONVERSATIONAL_FRONT][OPENAI_JSON_SCHEMA_UNSUPPORTED] usando chamada sem response_format"
                )
                resp = _client.chat.completions.create(
                    model=MODEL,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                )
            except Exception as e:
                logging.warning(
                    "[CONVERSATIONAL_FRONT][OPENAI_JSON_SCHEMA_FAIL] usando chamada sem response_format | err=%s",
                    e,
                )
                resp = _client.chat.completions.create(
                    model=MODEL,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                )
            return str(resp.choices[0].message.content or "").strip()

        try:
            resp = openai.ChatCompletion.create(
                model=MODEL,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format={
                    "type": "json_schema",
                    "json_schema": front_json_schema,
                },
                messages=[
                    {"role": "system", "content": json_system},
                    {"role": "user", "content": user},
                ],
            )
        except TypeError:
            logging.warning(
                "[CONVERSATIONAL_FRONT][OPENAI_JSON_SCHEMA_UNSUPPORTED_LEGACY] usando chamada sem response_format"
            )
            resp = openai.ChatCompletion.create(
                model=MODEL,
                temperature=temperature,
                max_tokens=max_tokens,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
        except Exception as e:
            logging.warning(
                "[CONVERSATIONAL_FRONT][OPENAI_JSON_SCHEMA_FAIL_LEGACY] usando chamada sem response_format | err=%s",
                e,
            )
            resp = openai.ChatCompletion.create(
                model=MODEL,
                temperature=temperature,
                max_tokens=max_tokens,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
        return str(resp["choices"][0]["message"]["content"] or "").strip()
    except Exception:
        return ""


def _prepare_kb_snapshot_buffers(kb_snapshot: str) -> tuple[str, str, bool]:
    """
    Se o snapshot vier em JSON válido (packs_v1), preserva a cópia completa
    para lookup/runtime interno e cria uma cópia curta só para o prompt.

    Isso evita quebrar o lookup do banco novo sem inflar tokens no modelo.
    """
    try:
        raw = str(kb_snapshot or "").strip()
        if not raw:
            return "", "", False

        json_ok = False
        if raw.startswith("{") or raw.startswith("["):
            try:
                parsed = json.loads(raw)
                json_ok = isinstance(parsed, (dict, list))
            except Exception:
                json_ok = False

        if json_ok:
            runtime_snapshot = raw
            prompt_snapshot = _compact_kb_snapshot(_truncate(raw, FRONT_KB_MAX_CHARS))
            return runtime_snapshot, prompt_snapshot, True

        runtime_snapshot = _truncate(raw, FRONT_KB_MAX_CHARS)
        prompt_snapshot = _compact_kb_snapshot(runtime_snapshot)
        return runtime_snapshot, prompt_snapshot, False
    except Exception:
        raw = _truncate(str(kb_snapshot or ""), FRONT_KB_MAX_CHARS)
        return raw, _compact_kb_snapshot(raw), False







def _kb_get_process_sla_text(kb: Dict[str, Any] | None, kb_snapshot_raw: str) -> str:
    """Retorna o texto de SLA/ativação vindo do KB (sem inventar)."""
    try:
        if isinstance(kb, dict):
            pf = kb.get("process_facts")
            if isinstance(pf, dict):
                t = str(pf.get("process_sla_text") or "").strip()
                if t:
                    return t
                t = str(pf.get("sla_setup") or "").strip()
                if t:
                    return t
            # fallback: algumas KBs guardam em outro nível
            ap = kb.get("answer_playbook_v1")
            if isinstance(ap, dict):
                pf2 = ap.get("process_facts")
                if isinstance(pf2, dict):
                    t = str(pf2.get("process_sla_text") or "").strip()
                    if t:
                        return t
                    t = str(pf2.get("sla_setup") or "").strip()
                    if t:
                        return t
    except Exception:
        pass

    # Heurística mínima: se o snapshot textual contiver um SLA explícito, preserva.
    try:
        s = (kb_snapshot_raw or "").lower()
        if "7 dias úteis" in s or "7 dias uteis" in s:
            return "até 7 dias úteis"
    except Exception:
        pass

    return ""


def _sanitize_unverified_time_claims(reply: str, kb: Dict[str, Any] | None, kb_snapshot_raw: str) -> str:
    """Bloqueia promessas de tempo não verificadas (minutos/horas/dias) e troca por SLA do KB ou linguagem segura."""
    import re

    r = str(reply or "").strip()
    if not r:
        return ""

    # Se o KB já contém o trecho de tempo usado, não mexe.
    kb_low = (kb_snapshot_raw or "").lower()
    r_low = r.lower()
    sla = _kb_get_process_sla_text(kb, kb_snapshot_raw)

    time_markers = (
        "minuto", "minutos", "hora", "horas", "hoje", "amanhã", "semana", "semanas",
        "em poucos minutos", "alguns minutos", "leva poucos minutos", "leva alguns minutos",
    )
    has_time = any(m in r_low for m in time_markers) or bool(re.search(r"\b\d+\s*(min|minutos|h|hora|horas|dia|dias|semana|semanas)\b", r_low))
    if not has_time:
        return r

    # Se a frase de tempo aparece no KB (mesma substring), aceita.
    try:
        # pega janelas pequenas para checar presença no KB
        m = re.search(r"(leva\s+[^\.\!\?]{0,40})", r_low)
        if m and m.group(1) and m.group(1) in kb_low:
            return r
    except Exception:
        pass

    # Troca por SLA do KB quando existir; senão, linguagem segura sem número.
    safe = (sla.strip() if sla else "")

    # Remove sentenças que prometem minutos/horas e injeta safe.
    parts = re.split(r"(?<=[\.\!\?])\s+", r)
    kept: list[str] = []
    removed = False
    for p in parts:
        pl = p.lower()
        if any(m in pl for m in time_markers) or re.search(r"\b\d+\s*(min|minutos|h|hora|horas|dia|dias|semana|semanas)\b", pl):
            removed = True
            continue
        kept.append(p)
    r2 = " ".join([k for k in kept if k.strip()]).strip()
    if removed:
        # Só injeta texto se houver SLA canônico real no KB.
        # Sem SLA explícito, apenas remove a promessa temporal.
        if safe:
            if r2:
                dot = r2.find(".")
                if 0 < dot < 220:
                    r2 = r2[: dot + 1] + f" {safe}." + r2[dot + 1 :]
                else:
                    r2 = f"{safe}. {r2}".strip()
            else:
                r2 = f"{safe}.".strip()
    return r2.strip()


def _upgrade_weak_question(reply: str, topic: str, intent: str) -> str:
    # IA TOTAL: não trocar pergunta da IA por CTA pronta.
    return str(reply or "").strip()

def _pick_pack_for_intent(intent: str, pack_id: str = "") -> str:
    p = (pack_id or "").strip().upper()
    if p:
        return p
    i = (intent or "").strip().upper()
    if i in ("AGENDA",):
        return "PACK_A_AGENDA"
    if i in ("SERVICOS", "WHAT_IS", "PRECO", "TRIAL"):
        return "PACK_B_SERVICOS"
    if i in ("PEDIDOS", "ORCAMENTO"):
        return "PACK_C_PEDIDOS"
    if i in ("STATUS", "PROCESSO"):
        return "PACK_D_STATUS"
    return ""






def _platform_kb_resolve_runtime(
    *,
    kb_obj: Dict[str, Any],
    kb_context: Dict[str, Any],
    user_text: str,
    current_topic: str = "",
    segment_hint: str = "",
) -> Dict[str, str]:
    """
    Resolve material operacional do platform_kb quando NÃO há KB segmentado hidratado.
    Não contém segmentos fixos nem palavras-chave próprias: usa apenas chaves e regras vindas do banco.
    """
    out: Dict[str, str] = {}
    try:
        if not isinstance(kb_obj, dict) or not kb_obj:
            return out

        topic = str(current_topic or "").strip().upper()

        if topic not in TOPICS or topic == "OTHER":
            topic = str(
                (kb_context or {}).get("topic")
                or (kb_context or {}).get("topic_hint")
                or (kb_context or {}).get("intent_hint")
                or ""
            ).strip().upper()

        if topic not in TOPICS or topic == "OTHER":
            text_norm = _normalize_lookup_key(user_text)
            rules = ((_platform_get_map(kb_obj, "routing_hints") or {}).get("intent_override_rules") or [])
            if isinstance(rules, list):
                for rule in rules:
                    if not isinstance(rule, dict):
                        continue
                    forced_topic = str(rule.get("force_topic") or "").strip().upper()
                    if forced_topic not in TOPICS:
                        continue
                    for trigger in (rule.get("when_any") or []):
                        trigger_norm = _normalize_lookup_key(str(trigger or ""))
                        if trigger_norm and trigger_norm in text_norm:
                            topic = forced_topic
                            break
                    if topic in TOPICS and topic != "OTHER":
                        break

        pack_id = _pick_pack_for_intent(topic)

        profile: Dict[str, Any] = {}
        profile_key = ""
        segment_map = _platform_get_map(kb_obj, "segment_value_map_v1")
        if isinstance(segment_map, dict):
            haystack = _normalize_lookup_key(
                " ".join([str(user_text or ""), str(segment_hint or "")]).strip()
            )
            for key, value in segment_map.items():
                key_norm = _normalize_lookup_key(str(key or ""))
                if key_norm and key_norm in haystack and isinstance(value, dict):
                    profile_key = str(key or "").strip()
                    profile = value
                    break

        packs = _platform_get_map(kb_obj, "value_packs_v1")
        preferred = [
            str(x or "").strip().upper()
            for x in ((profile or {}).get("preferred_packs") or [])
            if str(x or "").strip()
        ]
        blocked = {
            str(x or "").strip().upper()
            for x in ((profile or {}).get("do_not_use") or [])
            if str(x or "").strip()
        }

        if pack_id and pack_id in blocked:
            pack_id = ""

        if preferred:
            if not pack_id or pack_id not in preferred:
                for candidate in preferred:
                    if candidate and candidate not in blocked:
                        pack_id = candidate
                        break

        if not pack_id:
            pack_id = _pick_pack_for_intent(topic)

        tokens = ((profile or {}).get("tokens") or {}).get(pack_id) or {}
        example_line = _platform_apply_slots(
            str((tokens or {}).get("example_line") or "").strip(),
            packs.get(pack_id) if isinstance(packs, dict) else {},
            tokens,
        )

        micro_scene = ""
        micro_scene_conversational = ""
        runtime_short_reply = ""
        runtime_compact_reply = ""
        runtime_long_text = ""
        direct_scene = ""

        if isinstance(packs, dict) and pack_id:
            pack = packs.get(pack_id) or {}
            if isinstance(pack, dict):
                runtime_short = (pack.get("runtime_short") or {})
                runtime_long = (pack.get("runtime_long") or {})

                micro_scene = _platform_apply_slots(
                    str(runtime_short.get("micro_scene") or "").strip(),
                    pack,
                    tokens,
                )
                micro_scene_conversational = _platform_apply_slots(
                    str(runtime_short.get("micro_scene_conversational") or "").strip(),
                    pack,
                    tokens,
                )

                runtime_short_material = {
                    "value_one_liner": _platform_apply_slots(
                        str(runtime_short.get("value_one_liner") or "").strip(),
                        pack,
                        tokens,
                    ),
                    "bridge_line": _platform_apply_slots(
                        str(runtime_short.get("bridge_line") or "").strip(),
                        pack,
                        tokens,
                    ),
                    "micro_scene_conversational": micro_scene_conversational,
                    "micro_scene": micro_scene,
                }
                runtime_short_reply = _compose_pack_runtime_short_reply(runtime_short_material)
                runtime_compact_reply = _compose_pack_runtime_compact_reply(runtime_short_material)

                runtime_long_text = _platform_apply_slots(
                    str(runtime_long.get("text") or "").strip(),
                    pack,
                    tokens,
                )

                direct_scene = (
                    runtime_long_text
                    or runtime_short_reply
                    or micro_scene_conversational
                    or micro_scene
                )

        operational_reference = (
            direct_scene
            or example_line
            or runtime_long_text
            or runtime_short_reply
            or micro_scene_conversational
            or micro_scene
        )

        if topic in TOPICS and topic != "OTHER":
            out["topic"] = topic
        if pack_id:
            out["pack_id"] = pack_id
        if profile_key:
            out["platform_segment_key"] = profile_key
        if micro_scene_conversational or micro_scene:
            out["micro_scene"] = micro_scene_conversational or micro_scene
        if runtime_short_reply:
            out["runtime_short_reply"] = runtime_short_reply
        if runtime_compact_reply:
            out["runtime_compact_reply"] = runtime_compact_reply
        if runtime_long_text:
            out["runtime_long_text"] = runtime_long_text
        if direct_scene:
            out["direct_scene"] = direct_scene
        if example_line:
            out["reference_example"] = example_line
        if operational_reference:
            out["operational_reference"] = operational_reference

        return out
    except Exception:
        return out


def _platform_topic_from_kb_rules(kb_obj: Dict[str, Any], user_text: str) -> str:
    """
    Resolve topic usando regras do próprio platform_kb.
    Não contém palavras-chave próprias no código: apenas executa as regras cadastradas no banco.
    """
    try:
        text_norm = _normalize_lookup_key(user_text)
        rules = ((_platform_get_map(kb_obj or {}, "routing_hints") or {}).get("intent_override_rules") or [])
        if not isinstance(rules, list):
            return ""

        for rule in rules:
            if not isinstance(rule, dict):
                continue
            triggers = rule.get("when_any") or []
            forced_topic = str(rule.get("force_topic") or "").strip().upper()
            if not forced_topic:
                continue

            for item in triggers:
                item_norm = _normalize_lookup_key(str(item or ""))
                if item_norm and item_norm in text_norm:
                    return forced_topic
        return ""
    except Exception:
        return ""


def _platform_segment_profile_from_kb(
    kb_obj: Dict[str, Any],
    user_text: str,
    segment_candidate: str = "",
) -> tuple[str, Dict[str, Any]]:
    """
    Encontra perfil em segment_value_map_v1 sem assumir segmento do KB segmentado.
    Serve para casos como: o lead declara uma atividade que existe no platform_kb,
    mas não existe como documento operacional segmentado.
    """
    try:
        svm = _platform_get_map(kb_obj or {}, "segment_value_map_v1")
        if not isinstance(svm, dict):
            return "", {}

        text_norm = _normalize_lookup_key(
            " ".join([str(user_text or ""), str(segment_candidate or "")]).strip()
        )

        for key, profile in svm.items():
            key_raw = str(key or "").strip()
            key_norm = _normalize_lookup_key(key_raw)
            if key_norm and key_norm in text_norm and isinstance(profile, dict):
                return key_raw, profile

        return "", {}
    except Exception:
        return "", {}


def _platform_pack_from_profile(
    kb_obj: Dict[str, Any],
    topic: str,
    profile: Dict[str, Any],
    current_pack_id: str = "",
) -> str:
    """
    Escolhe pack usando topic + preferred_packs do platform_kb.
    Não altera fluxo segmentado: só é usado quando não há doc segmentado hidratado.
    """
    try:
        packs = _platform_get_map(kb_obj or {}, "value_packs_v1")
        if not isinstance(packs, dict):
            return ""

        current = str(current_pack_id or "").strip().upper()
        if current and current in packs:
            return current

        preferred = [
            str(x or "").strip().upper()
            for x in ((profile or {}).get("preferred_packs") or [])
            if str(x or "").strip()
        ]
        blocked = {
            str(x or "").strip().upper()
            for x in ((profile or {}).get("do_not_use") or [])
            if str(x or "").strip()
        }

        by_topic = _pick_pack_for_intent(str(topic or "").strip().upper())
        if by_topic and by_topic in packs and by_topic not in blocked:
            if not preferred or by_topic in preferred:
                return by_topic

        for pack_id in preferred:
            if pack_id in packs and pack_id not in blocked:
                return pack_id

        if by_topic and by_topic in packs:
            return by_topic

        return ""
    except Exception:
        return ""


def _platform_pack_material(
    kb_obj: Dict[str, Any],
    profile: Dict[str, Any],
    pack_id: str,
) -> Dict[str, str]:
    """
    Extrai material operacional do platform_kb.
    Prioriza material conversacional/narrativo do banco e usa a microcena curta
    apenas como último fallback.
    """
    try:
        pack_key = str(pack_id or "").strip().upper()
        if not pack_key:
            return {}

        packs = _platform_get_map(kb_obj or {}, "value_packs_v1")
        pack = packs.get(pack_key) or {}
        tokens = ((profile or {}).get("tokens") or {}).get(pack_key) or {}
        example_line = _platform_apply_slots(
            str((tokens or {}).get("example_line") or "").strip(),
            pack,
            tokens,
        )

        short = (pack.get("runtime_short") or {}) if isinstance(pack, dict) else {}
        long = (pack.get("runtime_long") or {}) if isinstance(pack, dict) else {}

        micro_scene = _platform_apply_slots(
            str(short.get("micro_scene") or "").strip(),
            pack,
            tokens,
        )
        micro_scene_conversational = _platform_apply_slots(
            str(short.get("micro_scene_conversational") or "").strip(),
            pack,
            tokens,
        )
        value_one_liner = _platform_apply_slots(
            str(short.get("value_one_liner") or "").strip(),
            pack,
            tokens,
        )
        bridge_line = _platform_apply_slots(
            str(short.get("bridge_line") or "").strip(),
            pack,
            tokens,
        )

        runtime_short_material = {
            "value_one_liner": value_one_liner,
            "bridge_line": bridge_line,
            "micro_scene_conversational": micro_scene_conversational,
            "micro_scene": micro_scene,
        }

        runtime_short_reply = _compose_pack_runtime_short_reply(runtime_short_material)
        runtime_compact_reply = _compose_pack_runtime_compact_reply(runtime_short_material)
        runtime_long_text = _platform_apply_slots(
            str(long.get("text") or "").strip(),
            pack,
            tokens,
        )

        direct_scene = (
            runtime_long_text
            or runtime_short_reply
            or micro_scene_conversational
            or micro_scene
        )

        if not profile or not profile.get("tokens"):
            operational_reference = runtime_compact_reply or value_one_liner or example_line
        else:
            operational_reference = (
                direct_scene
                or example_line
                or runtime_long_text
                or runtime_short_reply
                or micro_scene_conversational
                or micro_scene
            )

        material_source = ""
        if runtime_short_reply and direct_scene == runtime_short_reply:
            material_source = "runtime_short_reply"
        elif micro_scene_conversational and direct_scene == micro_scene_conversational:
            material_source = "micro_scene_conversational"
        elif runtime_long_text and direct_scene == runtime_long_text:
            material_source = "runtime_long_text"
        elif micro_scene and direct_scene == micro_scene:
            material_source = "micro_scene"

        return {
            "micro_scene": micro_scene_conversational or micro_scene,
            "runtime_short_reply": runtime_short_reply,
            "runtime_compact_reply": runtime_compact_reply,
            "runtime_long_text": runtime_long_text,
            "direct_scene": direct_scene,
            "reference_example": example_line,
            "operational_reference": operational_reference,
            "material_source": material_source,
        }
    except Exception:
        return {}


def _platform_get_map(kb_obj: Dict[str, Any], key: str) -> Dict[str, Any]:
    """
    Busca mapas do platform_kb na raiz, em answer_playbook_v1 ou em níveis internos.
    Não cria regra de segmento nem palavra-chave: só resolve a localização real do dado.
    """
    try:
        if not isinstance(kb_obj, dict) or not key:
            return {}

        direct = kb_obj.get(key)
        if isinstance(direct, dict):
            return direct

        ap = kb_obj.get("answer_playbook_v1")
        if isinstance(ap, dict):
            nested = ap.get(key)
            if isinstance(nested, dict):
                return nested

        found = _find_kb_map_anywhere(kb_obj, key, max_depth=5)
        return found if isinstance(found, dict) else {}
    except Exception:
        return {}



def _front_build_continuity_reply_from_platform_kb(
    *,
    current_reply: str,
    kb_obj: Dict[str, Any],
    topic: str = "",
    pack_id: str = "",
    user_name: str = "",
    ai_turns: int = 0,
    has_identity: bool = False,
    has_segment: bool = False,
    next_step: str = "",
    question_type: str = "broad",
) -> str:
    """
    Constrói resposta útil de continuidade a partir da platform_kb.

    Objetivo comercial:
    quando o lead faz uma pergunta de continuidade, a resposta precisa
    mostrar utilidade prática — painel, registro, filtros, resumo, acervo,
    orçamento, pedido, status, histórico — conforme o tema já resolvido.

    Fonte de verdade:
    somente campos já existentes na platform_kb.

    Não usa lista de profissões/segmentos.
    Não altera prompt.
    Não chama IA adicional.
    Não depende de ordem fixa dos turnos.
    """
    try:
        base = " ".join(str(current_reply or "").strip().split())
        q_type = str(question_type or "broad").strip().lower()
        is_continuity = q_type == "continuity"
        if not base:
            return ""

        if str(next_step or "").strip().upper() == "SEND_LINK":
            return base

        if not isinstance(kb_obj, dict) or not kb_obj:
            return base

        # Continuidade factual depende de contexto operacional/segmento.
        # O nome ajuda na humanização, mas não pode bloquear uma resposta
        # objetiva para pergunta pontual de follow-up.
        #
        # Escopo:
        # - não usa palavra-chave do usuário;
        # - não altera prompt;
        # - não chama IA adicional;
        # - mantém o segmento/contexto como guarda estrutural contra fatos genéricos.
        if not bool(has_segment):
            return base

        # Continuidade estrutural:
        # pode ocorrer no 2º turno, 3º turno ou no próprio turno em que o
        # lead já trouxe nome/segmento e fez pergunta prática.
        if not bool(int(ai_turns or 0) > 0 or str(user_name or "").strip() or has_segment):
            return base

        topic_u = str(topic or "").strip().upper()
        pack_u = str(pack_id or "").strip().upper() or _pick_pack_for_intent(topic_u)
        if not pack_u:
            return base

        packs = _platform_get_map(kb_obj, "value_packs_v1")
        pack = packs.get(pack_u) if isinstance(packs, dict) else {}
        if not isinstance(pack, dict):
            pack = {}

        process_facts = _platform_get_map(kb_obj, "process_facts")
        operational_capabilities = _platform_get_map(kb_obj, "operational_capabilities")
        value_blocks = _platform_get_map(kb_obj, "value_in_action_blocks")
        operational_flows = _platform_get_map(kb_obj, "operational_flows")
        operational_scenarios = _platform_get_map(kb_obj, "operational_value_scenarios")
        memory_positioning = _platform_get_map(kb_obj, "memory_positioning")
        product_truth = _platform_get_map(kb_obj, "product_truth_v1")

        def _clean_fact(v: Any, max_len: int = 420) -> str:
            try:
                if isinstance(v, list):
                    v = " ".join(str(x or "").strip() for x in v if str(x or "").strip())
                s = " ".join(str(v or "").strip().split())
                if not s:
                    return ""
                if "{{" in s or "}}" in s:
                    return ""
                return s[:max_len].strip(" ,;:-")
            except Exception:
                return ""

        def _block_text(key: str) -> str:
            try:
                b = value_blocks.get(key) if isinstance(value_blocks, dict) else {}
                if isinstance(b, dict):
                    return _clean_fact(b.get(f"{key}_text") or b.get("text") or b.get("scene") or "")
                return _clean_fact(b)
            except Exception:
                return ""

        def _pack_runtime_short() -> str:
            try:
                short = pack.get("runtime_short") if isinstance(pack, dict) else {}
                if not isinstance(short, dict):
                    return ""
                return _clean_fact(
                    short.get("value_one_liner")
                    or short.get("micro_scene_conversational")
                    or short.get("micro_scene")
                    or ""
                )
            except Exception:
                return ""

        facts: list[str] = []
        fallback_facts: list[str] = []

        if pack_u == "PACK_A_AGENDA":
            facts.extend([
                _clean_fact(process_facts.get("dashboard_agenda") if isinstance(process_facts, dict) else ""),
                _clean_fact(process_facts.get("daily_email_digest") if isinstance(process_facts, dict) else ""),
            ])
            fallback_facts.append(_pack_runtime_short())
        elif pack_u == "PACK_B_SERVICOS":
            facts.extend([
                _clean_fact(operational_capabilities.get("services_practice") if isinstance(operational_capabilities, dict) else ""),
                _clean_fact(product_truth.get("core_rule") if isinstance(product_truth, dict) else ""),
                _block_text("services_quote_scene"),
            ])

            # Fallback factual para continuidade de SERVICOS:
            # quando a platform_kb não traz services_practice/core_rule/services_quote_scene,
            # evita cair no runtime_short comercial e usa material operacional já hidratado
            # no próprio snapshot/segmento. Não usa palavra-chave do usuário, não chama IA
            # e não altera prompt.
            try:
                kb_sub = _platform_get_map(kb_obj, "kb_subsegments_v1")
                segment_candidates = []
                if isinstance(kb_sub, dict):
                    for _, doc in kb_sub.items():
                        if isinstance(doc, dict):
                            if str(doc.get("handoff_format") or "").strip() or doc.get("preferred_capabilities") or doc.get("operational_ritual"):
                                segment_candidates.append(doc)

                for doc in segment_candidates[:1]:
                    handoff = doc.get("handoff_format") or []
                    caps = doc.get("preferred_capabilities") or []
                    ritual = doc.get("operational_ritual") or []

                    if isinstance(handoff, list) and handoff:
                        fallback_facts.append(
                            "O atendimento fica registrado para a equipe continuar depois, com "
                            + ", ".join(str(x).strip().lower() for x in handoff[:4] if str(x).strip())
                            + "."
                        )

                    if isinstance(caps, list) and caps:
                        fallback_facts.append(
                            "Pelo histórico do atendimento, a equipe consegue retomar o interesse do cliente e dar sequência ao próximo passo."
                        )

                    if isinstance(ritual, list) and ritual:
                        fallback_facts.append(
                            "O robô organiza o interesse inicial, a dúvida principal e o encaminhamento necessário antes de passar para a equipe."
                        )
            except Exception:
                pass

            fallback_facts.append(_pack_runtime_short())
        elif pack_u == "PACK_C_PEDIDOS":
            facts.extend([
                _clean_fact(operational_capabilities.get("quotes_practice") if isinstance(operational_capabilities, dict) else ""),
                _block_text("services_quote_scene"),
            ])
            fallback_facts.append(_pack_runtime_short())
        elif pack_u == "PACK_D_STATUS":
            core = memory_positioning.get("core") if isinstance(memory_positioning, dict) else []
            if isinstance(core, list):
                facts.extend([_clean_fact(x) for x in core[:2]])
            facts.extend([
                _clean_fact(operational_flows.get("agenda_do_dia") if isinstance(operational_flows, dict) else ""),
            ])
            fallback_facts.append(_pack_runtime_short())
        else:
            fallback_facts.append(_pack_runtime_short())

        cleaned: list[str] = []
        seen = set()
        for f in facts:
            f = _clean_fact(f)
            if not f:
                continue
            key = _normalize_lookup_key(f[:120])
            if key and key not in seen:
                seen.add(key)
                cleaned.append(f)
            if len(cleaned) >= 3:
                break

        # Em continuidade, runtime_short é fallback final.
        # Ele costuma ser one-liner de abertura do pack; útil quando não há
        # outro material, mas fraco para responder pergunta pontual.
        if not cleaned:
            for f in fallback_facts:
                f = _clean_fact(f)
                if not f:
                    continue
                key = _normalize_lookup_key(f[:120])
                if key and key not in seen:
                    seen.add(key)
                    cleaned.append(f)
                if len(cleaned) >= 2:
                    break

        if not cleaned:
            return base

        # Continuidade factual da agenda:
        # quando a platform_kb já trouxe fatos estruturados específicos
        # sobre acompanhamento/visibilidade da agenda, eles devem vencer
        # o texto genérico aceito pela IA.
        #
        # Escopo seguro:
        # - só entra após as guardas de identidade, segmento e continuidade;
        # - só usa campos já existentes na própria platform_kb;
        # - não altera prompt, roteamento, microcena nem a primeira resposta.
        if pack_u == "PACK_A_AGENDA":
            agenda_direct: list[str] = []
            agenda_seen = set()
            for f in (
                process_facts.get("dashboard_agenda") if isinstance(process_facts, dict) else "",
                process_facts.get("daily_email_digest") if isinstance(process_facts, dict) else "",
            ):
                f = _clean_fact(f)
                if not f:
                    continue
                key = _normalize_lookup_key(f[:120])
                if key and key not in agenda_seen:
                    agenda_seen.add(key)
                    agenda_direct.append(f)

            if len(agenda_direct) >= 1:
                name = _front_sanitize_lead_name_candidate(user_name)
                prefix = f"{name}, " if name else ""
                useful = " ".join(agenda_direct).strip()
                useful = _front_trim_free_mode_sentence(f"{prefix}{useful}", 760)
                if is_continuity and useful and len(useful) >= 30:
                    return useful
                if useful and len(useful) >= 60:
                    return useful

        low_base = _normalize_lookup_key(base)
        overlap = 0
        for f in cleaned:
            probe = _normalize_lookup_key(" ".join(f.split()[:7]))
            if probe and probe in low_base:
                overlap += 1

        # Se a IA já trouxe pelo menos dois fatos úteis do KB, preserva.
        if overlap >= 2 and not is_continuity:
            return base

        # Evita piorar a resposta aceita pela IA com um fallback curto demais.
        useful_probe = " ".join(cleaned).strip()
        if len(useful_probe) < 220 and len(cleaned) < 2 and not is_continuity:
            return base

        name = _front_sanitize_lead_name_candidate(user_name)
        prefix = f"{name}, " if name else ""
        useful = " ".join(cleaned).strip()
        useful = _front_trim_free_mode_sentence(f"{prefix}{useful}", 760)
        return useful or base
    except Exception:
        return str(current_reply or "").strip()


def _resolve_canonical_topic(
    *,
    kb_snapshot_obj: Dict[str, Any],
    kb_context: Dict[str, Any],
    user_text: str,
    current_topic: str = "",
    last_intent: str = "",
    block_memory_topic_inheritance: bool = False,
) -> str:
    """
    Preserva a intenção do lead separada da resolução do KB.
    Falha de hidratação de segmento não pode rebaixar topic para OTHER.
    Não contém palavras-chave locais: usa apenas sinais já existentes e routing_hints do platform_kb.
    """
    try:
        current_t = str(current_topic or "").strip().upper()
        if block_memory_topic_inheritance and current_t == "OTHER":
            return "OTHER"

        for candidate in (
            current_topic,
            (kb_context or {}).get("topic"),
            (kb_context or {}).get("topic_hint"),
            (kb_context or {}).get("intent_hint"),
            last_intent,
        ):
            t = str(candidate or "").strip().upper()
            if t in TOPICS and t != "OTHER":
                return t

        routed = _platform_topic_from_kb_rules(kb_snapshot_obj, user_text)
        routed = str(routed or "").strip().upper()
        if routed in TOPICS and routed != "OTHER":
            return routed

        return ""
    except Exception:
        return ""

def _segment_reference_example(kb: Dict[str, Any], segment_key: str, pack_id: str) -> str:
    try:
        seg = (segment_key or "").strip().lower()
        if not seg:
            return ""
        kb_sub = (kb or {}).get("kb_subsegments_v1") or {}
        if isinstance(kb_sub, dict):
            d = kb_sub.get(seg) or {}
            if isinstance(d, dict):
                ex = str(d.get("one_liner") or "").strip()
                if ex:
                    return ex
        kb_seg = (kb or {}).get("kb_segments_v1") or {}
        if isinstance(kb_seg, dict):
            d = kb_seg.get(seg) or {}
            if isinstance(d, dict):
                ex = str(d.get("one_liner") or "").strip()
                if ex:
                    return ex
        svm = (kb or {}).get("segment_value_map_v1") or {}
        seg_obj = svm.get(seg) or svm.get(seg.lower()) or {}
        tokens = (seg_obj.get("tokens") or {})
        pack_obj = tokens.get((pack_id or "").strip().upper()) or {}
        ex = str(pack_obj.get("reference_example") or "").strip()
        return ex
    except Exception:
        return ""



def _pack_practical_add(pack_id: str) -> str:
    """Mantido por compatibilidade; microcena deve vir preferencialmente do KB."""
    return ""

def _segment_micro_flow(kb: Dict[str, Any], segment_key: str, intent: str, pack_id: str) -> str:
    """Gera um 'SHOW' curto: 1 frase de exemplo + 1 frase de micro-fluxo (sem tutorial)."""
    try:
        ex = _segment_reference_example(kb, segment_key, pack_id)
        if not ex:
            return ""        
        add = _pack_practical_add(pack_id)
        if add:
            return (ex.rstrip(".") + ". " + add).strip()
        return ex
    except Exception:
        return ""

# -----------------------------
# Função principal
# -----------------------------

def handle(*, user_text: str, state_summary: Dict[str, Any], kb_snapshot: str = "") -> Dict[str, Any]:
    """
    Entrada:
      - user_text: texto do usuário
      - state_summary: { ai_turns, is_lead, name_hint }

    Saída (contrato fixo):
      {
        replyText: str,
        understanding: { topic, confidence },
        nextStep: "NONE" | "SEND_LINK",
        shouldEnd: bool,
        nameUse: "none|greet|empathy|clarify",
        prefersText: bool
      }
    """

    ai_turns = int(state_summary.get("ai_turns") or 0)

    # ----------------------------------------------------------
    # BLINDAGEM ESTRUTURAL DO FLUXO
    # Nunca deixar parse/fail-safe depender de variável não inicializada.
    # ----------------------------------------------------------
    data: Dict[str, Any] = {}
    understanding: Dict[str, Any] = {}
    decider: Dict[str, Any] | None = None
    token_usage: Dict[str, Any] = {}
    structured_assembly_result: Dict[str, Any] = {}

    topic = "OTHER"
    intent = "OTHER"
    confidence = "low"
    needs_clarify = "no"
    clarify_q = ""
    next_step = "NONE"
    should_end = False
    name_use = "none"
    reply_text = ""
    spoken_text = ""
    response_mode = "DIRECT"
    question_type = "broad"
    _final_candidate = None
    inferred_lead_name = ""
    current_turn_lead_name = ""
    inferred_lead_segment = ""
    inferred_lead_segment_raw = ""

    last_intent = str(state_summary.get("last_intent") or "").strip().upper()
    upstream_topic_hint = str(
        state_summary.get("kb_topic")
        or state_summary.get("topic_hint")
        or state_summary.get("snapshot_topic")
        or state_summary.get("front_topic")
        or ""
    ).strip().upper()

    if upstream_topic_hint not in TOPICS:
        upstream_topic_hint = ""

    # Quando o wa_bot informa OTHER no turno atual, isso não significa
    # ausência de sinal: significa que o texto atual não confirmou o
    # tópico operacional anterior. A memória continua existindo, mas
    # não pode promover AGENDA/PEDIDOS/etc. neste turno.
    current_turn_topic_reset = bool(upstream_topic_hint == "OTHER")

    last_user_goal = str(state_summary.get("last_user_goal") or "").strip()
    segment_hint = str(state_summary.get("segment_hint") or "").strip()
    name_hint = str(state_summary.get("name_hint") or "").strip()
    name_hint = _front_sanitize_lead_name_candidate(
        name_hint,
        segment_refs=[
            segment_hint,
            state_summary.get("segment"),
            state_summary.get("segmentHint"),
            state_summary.get("leadSegmentRaw"),
        ],
    )
    lead_memory_summary = str(
        state_summary.get("lead_memory_summary") or ""
    ).strip()
    lead_memory_turns = int(
        state_summary.get("lead_memory_turns") or 0
    )
    last_topic = str(
        state_summary.get("last_topic") or ""
    ).strip()
    last_next_step = str(
        state_summary.get("last_next_step") or ""
    ).strip()

    # Sanitização leve: evita capturas inválidas de áudio
    if name_hint:
        tokens = name_hint.split()
        if len(tokens) > 2 or len(name_hint) > 20:
            name_hint = ""

    is_lead = bool(state_summary.get("is_lead") or False)
    msg_type = str(
        state_summary.get("msg_type")
        or state_summary.get("entry_type")
        or state_summary.get("message_type")
        or ""
    ).strip().lower()
    kb_snapshot, kb_compact, kb_snapshot_json_ok = _prepare_kb_snapshot_buffers(kb_snapshot)

    # ---------------------------------------------------------------
    # Memória conversacional persistida (best-effort)
    #
    # Informações já carregadas do Firestore são agregadas ao contexto
    # atual para preservar continuidade entre turnos.
    #
    # A decisão estratégica permanece sob responsabilidade da IA.
    # O código apenas fornece contexto estrutural adicional.
    # ---------------------------------------------------------------
    persistent_context_parts: list[str] = []

    if lead_memory_summary:
        persistent_context_parts.append(lead_memory_summary)

    if last_topic:
        persistent_context_parts.append(
            f"Tema recente: {last_topic}."
        )

    if last_next_step:
        persistent_context_parts.append(
            f"Próximo passo em andamento: {last_next_step}."
        )

    persistent_context = " ".join(
        part.strip()
        for part in persistent_context_parts
        if str(part or "").strip()
    ).strip()

    if persistent_context:
        if last_user_goal:
            last_user_goal = (
                f"{persistent_context} Objetivo atual: {last_user_goal}"
            ).strip()
        else:
            last_user_goal = persistent_context

    try:
        logging.info(
            "[CONVERSATIONAL_FRONT][LEAD_MEMORY] has_summary=%s turns=%s has_topic=%s has_next_step=%s",
            bool(lead_memory_summary),
            lead_memory_turns,
            bool(last_topic),
            bool(last_next_step),
        )
    except Exception:
        pass

    # 🔒 Snapshot em dict para regras determinísticas do platform_kb
    kb_snapshot_obj: Dict[str, Any] = {}
    try:
        if kb_snapshot and str(kb_snapshot).strip().startswith("{"):
            _parsed_kb_snapshot = json.loads(str(kb_snapshot))
            if isinstance(_parsed_kb_snapshot, dict):
                kb_snapshot_obj = _parsed_kb_snapshot
    except Exception:
        kb_snapshot_obj = {}

    try:
        logging.info(
            "[CONVERSATIONAL_FRONT][KB_SNAPSHOT_IN] runtime_chars=%s prompt_chars=%s json_ok=%s",
            len(kb_snapshot or ""),
            len(kb_compact or ""),
            kb_snapshot_json_ok,
        )
    except Exception:
        pass

    def _front_current_turn_segment_override_is_explicit(candidate: str) -> bool:
        """
        Permite troca de segmento persistido apenas quando o turno atual traz
        sinal explícito do novo segmento. Evita que uma pergunta curta de
        continuidade seja reclassificada por similaridade genérica do KB.
        """
        try:
            cand = _normalize_lookup_key(candidate)
            current_seg = _normalize_lookup_key(segment_hint)
            if not cand:
                return False
            if current_seg and (cand == current_seg or cand in current_seg or current_seg in cand):
                return True

            # Sinal estrutural pelo próprio nome/chave do segmento.
            if _lookup_token_overlap_score(user_text, str(candidate or "").replace("__", " ")) >= 2:
                return True

            if not isinstance(kb_snapshot_obj, dict):
                return False

            for map_name in ("kb_subsegments_v1", "segment_value_map_v1", "kb_segments_v1"):
                docs_map = _find_kb_map_anywhere(kb_snapshot_obj, map_name) or {}
                if not isinstance(docs_map, dict) or not docs_map:
                    continue

                explicit_match = _keyword_doc_match(user_text, docs_map)
                if explicit_match:
                    m = _normalize_lookup_key(explicit_match)
                    if m and (m == cand or m in cand or cand in m):
                        return True

            return False
        except Exception:
            return False

    # Nome confirmado:
    # has_name não pode ser recalculado a partir de inferência do LLM
    # no mesmo turno. Ele deve representar apenas dado já consolidado
    # vindo do estado/memória.
    #
    # Isso evita o padrão "Olá, clínico!" sem usar palavras-chave,
    # sem alterar prompt e sem bloquear a persistência futura de um
    # nome válido pelo fluxo próprio do wa_bot.py.
    has_name = bool(str(name_hint or "").strip())
    confirmed_has_name = has_name

    if not segment_hint and inferred_lead_segment:
        segment_hint = inferred_lead_segment

    # fast-path comercial removido:
    # intenção de ativação/link deve nascer do entendimento da IA
    # e/ou de sinais estruturados do KB/contexto, nunca de regex local.


    # kb_compact já foi preparado acima:
    # - snapshot completo para lookup/runtime

    # - snapshot curto para o prompt

    # Seletor de fatos do KB (menos tokens, menos "chute")
    kb_context: Dict[str, Any] = {}
    inferred_segment_for_kb = ""

    # ----------------------------------------------------------
    # Router semântico antecipado (antes do primeiro KB_LOOKUP)
    #
    # Objetivo:
    # Consolidar o segmento declarado no turno atual antes que o
    # resolver consulte o KB segmentado.
    #
    # Princípios preservados:
    # - sem palavras-chave hardcoded;
    # - sem alteração de prompts;
    # - sem chamada extra ao modelo;
    # - baixo risco de regressão.
    #
    # A função _infer_segment_from_text já utiliza apenas as
    # estruturas existentes no próprio KB snapshot.
    # ----------------------------------------------------------
    try:
        if (
            not inferred_segment_for_kb
            and user_text
            and kb_snapshot
        ):
            _early_segment = (
                _infer_segment_from_text(user_text, kb_snapshot) or ""
            ).strip()

            if _early_segment:
                inferred_segment_for_kb = _early_segment

                if (
                    segment_hint
                    and _normalize_lookup_key(_early_segment) != _normalize_lookup_key(segment_hint)
                    and not _front_current_turn_segment_override_is_explicit(_early_segment)
                ):
                    try:
                        logging.info(
                            "[SEGMENT_OVERRIDE_BLOCKED] stage=early inferred=%s preserved=%s",
                            str(_early_segment or ""),
                            str(segment_hint or ""),
                        )
                    except Exception:
                        pass
                    inferred_segment_for_kb = ""

                # Propaga imediatamente para o estado local
                # consumido pelo resolver apenas quando a troca for explícita.
                if inferred_segment_for_kb:
                    try:
                        state_summary["segmentHint"] = inferred_segment_for_kb
                    except Exception:
                        pass

                    try:
                        state_summary["leadSegmentRaw"] = inferred_segment_for_kb
                    except Exception:
                        pass
    except Exception:
        pass

    try:
        if FRONT_KB_RESOLVER_ENABLED and build_kb_context is not None:
            try:
                if not inferred_segment_for_kb:
                    inferred_segment_for_kb = _infer_segment_from_text(user_text, kb_snapshot)
                    if (
                        segment_hint
                        and inferred_segment_for_kb
                        and _normalize_lookup_key(inferred_segment_for_kb) != _normalize_lookup_key(segment_hint)
                        and not _front_current_turn_segment_override_is_explicit(inferred_segment_for_kb)
                    ):
                        try:
                            logging.info(
                                "[SEGMENT_OVERRIDE_BLOCKED] stage=resolver inferred=%s preserved=%s",
                                str(inferred_segment_for_kb or ""),
                                str(segment_hint or ""),
                            )
                        except Exception:
                            pass
                        inferred_segment_for_kb = ""
            except Exception:
                inferred_segment_for_kb = ""

            # ----------------------------------------------------------
            # FILTRO ESTRUTURAL PRÉ-KB (CRÍTICO)
            # Evita que inferência fraca contamine o lookup inicial
            # Não usa palavras-chave, apenas coerência estrutural
            # ----------------------------------------------------------
            try:
                if inferred_segment_for_kb:
                    _seg = str(inferred_segment_for_kb).strip()
                    _snap = str(kb_snapshot or "")

                    # só aceita se o segmento tiver presença estrutural no snapshot
                    # (não depende de texto do usuário, nem heurística artificial)
                    if _seg not in _snap:
                        inferred_segment_for_kb = ""
            except Exception:
                inferred_segment_for_kb = ""

            operational_family_hint = ""
            try:
                operational_family_hint = _infer_operational_family(user_text, segment_hint or inferred_segment_for_kb)
            except Exception:
                operational_family_hint = ""

            try:
                kb_context = build_kb_context(
                    kb_snapshot=kb_snapshot,
                    user_text=user_text,
                    last_intent=("" if current_turn_topic_reset else (last_intent or "")),
                    # Prioridade estrutural:
                    # o segmento inferido do turno atual vence memória/contexto antigo.
                    # Se não houver inferência nova, preserva continuidade com segment_hint.
                    segment_hint=(inferred_segment_for_kb or segment_hint or ""),
                    operational_family_hint=operational_family_hint,
                    # O tópico atual deve vir do turno atual, não da memória.
                    # last_intent continua disponível como memória em last_intent,
                    # mas não pode contaminar topic_hint.
                    topic_hint=(
                        str(upstream_topic_hint or "").strip().upper()
                        if str(upstream_topic_hint or "").strip().upper() != "OTHER"
                        else ""
                    ),
                )
            except TypeError:
                # compat com assinatura antiga
                kb_context = build_kb_context(
                    kb_snapshot=kb_snapshot,
                    user_text=user_text,
                    last_intent=(last_intent or ""),
                )

            # ----------------------------------------------------------
            # PROTEÇÃO PRÉ-LOOKUP (DEFINITIVA)
            # Impede que o resolver injete segmento incompatível
            # Atua antes de qualquer KB_LOOKUP / ENRICH
            # ----------------------------------------------------------
            try:
                if isinstance(kb_context, dict):
                    _seg = str(
                        kb_context.get("subsegment_hint")
                        or kb_context.get("effective_subsegment")
                        or ""
                    ).strip()

                    if _seg:
                        _snap = str(kb_snapshot or "")

                        # validação estrutural mínima: segmento precisa ter base real no snapshot
                        # e não pode ser apenas "melhor encaixe genérico"
                        if _seg not in _snap:
                            for k in (
                                "subsegment_hint",
                                "effective_subsegment",
                                "segment_hint",
                                "segment_id",
                                "archetype_id",
                                "segment_profile",
                                "operational_family",
                                "operational_reference",
                                "segment_reference_example",
                                "pack_micro_scene",
                            ):
                                kb_context.pop(k, None)

                            kb_context["segment_context_status"] = "cleared_incompatible_for_current_text"
            except Exception:
                pass

            kb_context = _clear_incompatible_kb_context_for_current_text(
                kb_snapshot=kb_snapshot,
                user_text=user_text,
                kb_context=kb_context if isinstance(kb_context, dict) else {},
                segment_hint=segment_hint,
            )

            # ----------------------------------------------------------
            # Curto-circuito estrutural do segmento inferido no turno
            #
            # Se _infer_segment_from_text() identificou um segmento a
            # partir do texto/STT atual, esse valor deve prevalecer sobre
            # qualquer contexto residual ou fallback por similaridade.
            #
            # Não há palavras-chave hardcoded.
            # Não altera prompts.
            # Não interfere quando nenhum segmento foi inferido.
            # ----------------------------------------------------------
            try:
                if (
                    not inferred_segment_for_kb
                    and user_text
                    and kb_snapshot
                ):
                    inferred_segment_for_kb = (
                        _infer_segment_from_text(user_text, kb_snapshot) or ""
                    ).strip()
                    if (
                        segment_hint
                        and inferred_segment_for_kb
                        and _normalize_lookup_key(inferred_segment_for_kb) != _normalize_lookup_key(segment_hint)
                        and not _front_current_turn_segment_override_is_explicit(inferred_segment_for_kb)
                    ):
                        try:
                            logging.info(
                                "[SEGMENT_OVERRIDE_BLOCKED] stage=short_circuit inferred=%s preserved=%s",
                                str(inferred_segment_for_kb or ""),
                                str(segment_hint or ""),
                            )
                        except Exception:
                            pass
                        inferred_segment_for_kb = ""
            except Exception:
                pass

            try:
                if inferred_segment_for_kb and isinstance(kb_context, dict):
                    _turn_seg = _normalize_lookup_key(inferred_segment_for_kb)
                    _resolved_seg = _normalize_lookup_key(
                        " ".join(
                            [
                                str(kb_context.get("subsegment_hint") or ""),
                                str(kb_context.get("effective_subsegment") or ""),
                                str(kb_context.get("segment_hint") or ""),
                                str(kb_context.get("segment_id") or ""),
                            ]
                        )
                    )

                    # Se o segmento inferido no turno atual divergir do
                    # segmento atualmente resolvido, limpamos apenas os
                    # campos derivados para forçar re-hidratação coerente.
                    if (
                        _turn_seg
                        and (
                            not _resolved_seg
                            or (
                                _turn_seg not in _resolved_seg
                                and _resolved_seg not in _turn_seg
                            )
                        )
                    ):
                        for k in (
                            "subsegment_hint",
                            "effective_subsegment",
                            "segment_id",
                            "archetype_id",
                            "segment_profile",
                            "operational_family",
                            "operational_reference",
                            "segment_reference_example",
                            "pack_micro_scene",
                            "micro_scene",
                            "micro_scene_conversational",
                            "reference_example",
                            "practical_scene",
                            "direct_scene",
                            "runtime_short_reply",
                            "runtime_long_text",
                        ):
                            kb_context.pop(k, None)

                        # Preserva soberania do segmento detectado no
                        # turno atual para o próximo lookup estrutural.
                        kb_context["segment_hint"] = inferred_segment_for_kb
                        kb_context["subsegment_hint"] = inferred_segment_for_kb
                        kb_context["effective_subsegment"] = inferred_segment_for_kb
                        kb_context["segment_context_status"] = (
                            "current_turn_segment_short_circuit"
                        )
            except Exception:
                pass
    except Exception:
        kb_context = {}

    segment_context_cleared = _kb_context_segment_was_cleared(
        kb_context if isinstance(kb_context, dict) else {}
    )

    operational_family = ""
    try:
        operational_family = str((kb_context or {}).get("operational_family", "") or "")
    except Exception:
        operational_family = ""

    micro_scene = ""

    # ----------------------------------------------------------
    # ✅ ARQUITETURA: Objeção de produto tem prioridade máxima
    # (TRIAL/GRÁTIS nunca pode ser engolido por PREÇO)
    # ----------------------------------------------------------
    force_trial = False
    try:
        if isinstance(kb_context, dict):
            ih = str(kb_context.get("intent_hint") or "").strip().upper()
            ob = str(kb_context.get("objection") or "").strip().upper()
            it = bool(kb_context.get("is_trial") is True)
            force_trial = it or (ih == "TRIAL") or (ob == "TRIAL")
    except Exception:
        force_trial = False

    # Lead hint opcional: evita o modelo chutar profissão quando não sabemos segmento
    try:
        if segment_hint and isinstance(kb_context, dict):
            kb_context["segment_hint"] = segment_hint
    except Exception:
        pass

    inferred_segment = ""
    try:
        # O texto atual deve sempre ter chance de declarar/alterar o segmento.
        # Não usa palavras-chave novas; reaproveita a inferência semântica já existente.
        inferred_segment = _infer_segment_from_text(user_text, kb_snapshot)
        if (
            segment_hint
            and inferred_segment
            and _normalize_lookup_key(inferred_segment) != _normalize_lookup_key(segment_hint)
            and not _front_current_turn_segment_override_is_explicit(inferred_segment)
        ):
            try:
                logging.info(
                    "[SEGMENT_OVERRIDE_BLOCKED] stage=effective inferred=%s preserved=%s",
                    str(inferred_segment or ""),
                    str(segment_hint or ""),
                )
            except Exception:
                pass
            inferred_segment = ""
    except Exception:
        inferred_segment = ""

    sticky_segment_hint = (
        str(state_summary.get("subsegment_hint") or "").strip()
        or str(state_summary.get("kb_segment_hint") or "").strip()
        or str(state_summary.get("kb_subsegment_hint") or "").strip()
        or str(state_summary.get("segment_from_kb") or "").strip()
        or str(state_summary.get("segment_hint") or "").strip()
        or str(state_summary.get("effective_segment") or "").strip()
        or str(state_summary.get("last_effective_segment") or "").strip()
        or str(state_summary.get("last_segment_hint") or "").strip()
    )

    kb_segment_hint = ""
    try:
        if isinstance(kb_context, dict):
            kb_segment_hint = str(
                kb_context.get("subsegment_hint")
                or kb_context.get("segment_hint")
                or ""
            ).strip()
    except Exception:
        kb_segment_hint = ""

    effective_segment = (
        # 1) Presente: o que foi inferido da mensagem atual.
        str(inferred_segment or "").strip()
        # 2) KB já resolvido neste turno — somente se não foi limpo por incompatibilidade.
        or (str((kb_context or {}).get("subsegment_hint") or "").strip() if not segment_context_cleared else "")
        # 3) Contexto explícito atual.
        or str(segment_hint or "").strip()
        or (str(kb_segment_hint or "").strip() if not segment_context_cleared else "")
        # 4) Memória anterior só como fallback — não usar quando o turno atual limpou contrato incompatível.
        or (str(sticky_segment_hint or "").strip() if not segment_context_cleared else "")
    )

    # ----------------------------------------------------------
    # SEGMENTO PARA PROMPT vs SEGMENTO PARA RUNTIME
    # O runtime pode manter sticky/contexto para lookup interno,
    # mas o prompt inicial não deve tratar isso como segmento
    # confirmado se o turno atual ainda não confirmou intenção.
    # Evita ancoragem prematura sem apagar a memória operacional.
    # ----------------------------------------------------------
    segment_confirmed_for_prompt = False
    try:
        if inferred_segment:
            segment_confirmed_for_prompt = True
        elif segment_hint:
            segment_confirmed_for_prompt = True
    except Exception:
        segment_confirmed_for_prompt = False

    segment_for_prompt = str(effective_segment or "").strip() if segment_confirmed_for_prompt else ""

    # se ainda estivermos num macro conhecido, tenta promover para subsegmento real
    try:
        if effective_segment and "__" not in effective_segment and not segment_context_cleared:
            promoted_segment = _infer_segment_from_docs(
                user_text=user_text,
                kb_snapshot=kb_snapshot,
                kb_context=kb_context if isinstance(kb_context, dict) else {},
            )
            if promoted_segment and "__" in str(promoted_segment):
                effective_segment = str(promoted_segment).strip()
    except Exception:
        pass

    # ----------------------------------------------------------
    # SEGUNDA INFERÊNCIA DE SEGMENTO
    # Quando a primeira inferência vier fraca, tenta casar o texto
    # com as chaves reais do KB antes da hidratação principal.
    # ----------------------------------------------------------
    try:
        if segment_context_cleared:
            inferred_from_docs = ""
        else:
            inferred_from_docs = _infer_segment_from_docs(
                user_text=user_text,
                kb_snapshot=kb_snapshot,
                kb_context=kb_context if isinstance(kb_context, dict) else {},
            )
        if inferred_from_docs:
            inferred_from_docs = str(inferred_from_docs).strip()
            if (
                segment_hint
                and inferred_from_docs
                and _normalize_lookup_key(inferred_from_docs) != _normalize_lookup_key(segment_hint)
                and not _front_current_turn_segment_override_is_explicit(inferred_from_docs)
            ):
                try:
                    logging.info(
                        "[SEGMENT_OVERRIDE_BLOCKED] stage=docs inferred=%s preserved=%s",
                        str(inferred_from_docs or ""),
                        str(segment_hint or ""),
                    )
                except Exception:
                    pass
                inferred_from_docs = ""

            # sempre promove subsegmento sobre macro quando a troca for explícita.
            if inferred_from_docs and "__" in inferred_from_docs:
                effective_segment = inferred_from_docs
            elif inferred_from_docs and not effective_segment:
                effective_segment = inferred_from_docs
    except Exception:
        pass

    # ----------------------------------------------------------
    # HIDRATAÇÃO REAL DO CONTEXTO OPERACIONAL
    # Usa os docs reais do banco para preencher lacunas antes de
    # qualquer refresh de âncora ou montagem de contrato.
    # ----------------------------------------------------------
    if segment_context_cleared:
        effective_segment = str(inferred_segment or segment_hint or "").strip()
        if isinstance(kb_context, dict):
            for key in (
                "subsegment_hint",
                "effective_subsegment",
                "segment_hint",
                "segment_id",
                "archetype_id",
                "segment_profile",
                "operational_family",
                "operational_reference",
                "segment_reference_example",
            ):
                kb_context.pop(key, None)

    try:
        real_kb_docs = _kb_lookup_operational_docs(
            kb_snapshot=kb_snapshot,
                        effective_segment=effective_segment,
            kb_context=kb_context if isinstance(kb_context, dict) else {},
        )
        kb_context = _merge_real_kb_operational_context(
            kb_context=kb_context if isinstance(kb_context, dict) else {},
            docs=real_kb_docs,
        )

        try:
            logging.info(
                "[SEGMENT_TRACE] "
                "segment_hint=%s "
                "inferred_segment_for_kb=%s "
                "effective_segment=%s "
                "sticky_segment_hint=%s "
                "segment_context_cleared=%s",
                str(segment_hint or ""),
                str(inferred_segment_for_kb or ""),
                str(effective_segment or ""),
                str(sticky_segment_hint or ""),
                bool(segment_context_cleared),
            )
        except Exception:
            pass

        logging.info(
            "[CONVERSATIONAL_FRONT][KB_CTX_ENRICH] seg=%s archetype=%s segment_id=%s example=%s scene=%s family=%s",
            str(effective_segment or "").strip(),
            str((kb_context or {}).get("archetype_id") or "").strip(),
            str((kb_context or {}).get("segment_id") or "").strip(),
            bool(str((kb_context or {}).get("segment_reference_example") or "").strip()),
            bool(str((kb_context or {}).get("operational_reference") or "").strip()),
            str((kb_context or {}).get("operational_family") or "").strip(),
        )
    except Exception:
        pass

    real_kb_docs = real_kb_docs if 'real_kb_docs' in locals() else {}
    segment_docs_hydrated = False
    try:
        segment_docs_hydrated = bool(
            isinstance(real_kb_docs, dict)
            and (
                real_kb_docs.get("subsegment_doc")
                or real_kb_docs.get("segment_doc")
                or real_kb_docs.get("archetype_doc")
            )
        )
    except Exception:
        segment_docs_hydrated = False

    platform_segment_key = ""
    platform_segment_profile: Dict[str, Any] = {}
    try:
        platform_segment_key, platform_segment_profile = _platform_segment_profile_from_kb(
            kb_snapshot_obj,
            user_text,
                        effective_segment,
        )
    except Exception:
        platform_segment_key, platform_segment_profile = "", {}

    platform_kb_mode = bool(
        not segment_docs_hydrated
        and isinstance(kb_snapshot_obj, dict)
        and kb_snapshot_obj
    )

    try:
        logging.info(
            "[HYDRATION_TRACE] "
            "segment_docs_hydrated=%s "
            "platform_kb_mode=%s "
            "effective_segment=%s "
            "real_sub=%s real_seg=%s real_arch=%s",
            bool(segment_docs_hydrated),
            bool(platform_kb_mode),
            str(effective_segment or ""),
            bool(isinstance(real_kb_docs, dict) and real_kb_docs.get("subsegment_doc")),
            bool(isinstance(real_kb_docs, dict) and real_kb_docs.get("segment_doc")),
            bool(isinstance(real_kb_docs, dict) and real_kb_docs.get("archetype_doc")),
        )
    except Exception:
        pass

    if platform_kb_mode:
        # Se não há documento segmentado hidratado, o segmento não deve bloquear o platform_kb.
        segment_for_prompt = ""
        if isinstance(kb_context, dict):
            kb_context["platform_kb_mode"] = True
            if platform_segment_key:
                kb_context["platform_segment_key"] = platform_segment_key

    # ----------------------------------------------------------
    # RE-HIDRATAÇÃO ASSISTIDA
    # Se ainda veio magro, tenta mais uma vez com o melhor segmento
    # inferido a partir do texto + snapshot real.
    # ----------------------------------------------------------
    try:
        docs_hydrated = bool(
            isinstance(real_kb_docs, dict)
            and (
                real_kb_docs.get("subsegment_doc")
                or real_kb_docs.get("segment_doc")
                or real_kb_docs.get("archetype_doc")
            )
        )

        if not docs_hydrated and not segment_context_cleared:
            reinforced_segment = _infer_segment_from_docs(
                user_text=user_text,
                kb_snapshot=kb_snapshot,
                kb_context=kb_context if isinstance(kb_context, dict) else {},
            )

            if reinforced_segment and reinforced_segment != effective_segment:
                effective_segment = str(reinforced_segment).strip()

                real_kb_docs = _kb_lookup_operational_docs(
                    kb_snapshot=kb_snapshot,
                    effective_segment=effective_segment,
                    kb_context=kb_context if isinstance(kb_context, dict) else {},
                )
                kb_context = _merge_real_kb_operational_context(
                    kb_context=kb_context if isinstance(kb_context, dict) else {},
                    docs=real_kb_docs,
                )
    except Exception:
        pass

    try:
        if effective_segment and isinstance(kb_context, dict) and not segment_context_cleared:
            if "__" in str(effective_segment):
                kb_context["subsegment_hint"] = str(effective_segment).strip()
            else:
                kb_context["segment_hint"] = str(effective_segment).strip()
            kb_context["needs_segment_discovery"] = not bool(segment_for_prompt)
    except Exception:
        pass

    has_lead_name = bool(str(name_hint or "").strip())

    has_segment_context = bool(
        str(effective_segment or "").strip()
        or str(segment_hint or "").strip()
        or str(platform_segment_key or "").strip()
    )

    discovery_resolved = bool(
        has_lead_name and has_segment_context
    )

    try:
        logging.info(
            "[DISCOVERY_TRACE] "
            "operational_family=%s "
            "operational_reference=%s "
            "reference_example=%s "
            "effective_segment=%s "
            "discovery_resolved=%s",
            str(operational_family or ""),
            bool(str(operational_reference or "").strip()),
            bool(str(reference_example or "").strip()),
            str(effective_segment or ""),
            bool(discovery_resolved),
        )
    except Exception:
        pass

    try:
        if (
            not str((kb_context or {}).get("discovery_question_hint") or "").strip()
            and not operational_reference
            and not reference_example
            and not operational_family
        ):
            kb_context["discovery_question_hint"] = ""
    except Exception:
        pass

    question = ""
    preferred_discovery_question = str(
        (kb_context or {}).get("discovery_question_hint")
        or (kb_context or {}).get("segment_question_preferred")
        or ""
    ).strip()
    if not effective_segment and preferred_discovery_question:
        question = preferred_discovery_question

    # ----------------------------------------------------------
    # PLATFORM_KB RUNTIME
    # Só entra quando NÃO houve hidratação real de KB segmentado.
    # Mantém intacto o fluxo de segmentos já existentes.
    # ----------------------------------------------------------
    platform_kb_mode = False
    platform_runtime: Dict[str, str] = {}
    try:
        docs_hydrated_now = bool(
            isinstance(real_kb_docs, dict)
            and (
                real_kb_docs.get("subsegment_doc")
                or real_kb_docs.get("segment_doc")
                or real_kb_docs.get("archetype_doc")
            )
        )

        platform_kb_mode = bool(
            not docs_hydrated_now
            and isinstance(kb_snapshot_obj, dict)
            and bool(kb_snapshot_obj)
        )

        if platform_kb_mode:
            platform_runtime = _platform_kb_resolve_runtime(
                kb_obj=kb_snapshot_obj,
                kb_context=kb_context if isinstance(kb_context, dict) else {},
                user_text=user_text,
                current_topic=(upstream_topic_hint or last_intent),
                segment_hint=effective_segment or segment_hint,
            )

            if platform_runtime and isinstance(kb_context, dict):
                kb_context["platform_kb_mode"] = True
                for _k, _v in platform_runtime.items():
                    if _v:
                        kb_context[_k] = _v
                if platform_runtime.get("topic") and not current_turn_topic_reset:
                    kb_context["intent_hint"] = platform_runtime["topic"]
    except Exception:
        platform_kb_mode = False
        platform_runtime = {}

    # ----------------------------------------------------------
    # CANONICAL TOPIC
    # Intenção do lead é separada da resolução do KB.
    # Se o KB segmentado não hidratou, a intenção válida deve guiar o platform_kb.
    # ----------------------------------------------------------
    canonical_topic = ""
    try:
        canonical_topic = _resolve_canonical_topic(
            kb_snapshot_obj=kb_snapshot_obj,
            kb_context=kb_context if isinstance(kb_context, dict) else {},
            user_text=user_text,
            current_topic=str(
                upstream_topic_hint
                or (platform_runtime or {}).get("topic")
                or ""
            ),
            # Se o turno atual veio como OTHER, não promover memória antiga
            # para tópico canônico. Isso evita OTHER -> AGENDA por herança.
            last_intent=(
                ""
                if str(upstream_topic_hint or "").strip().upper() == "OTHER"
                else (upstream_topic_hint or last_intent)
            ),
            block_memory_topic_inheritance=(
                str(upstream_topic_hint or "").strip().upper() == "OTHER"
            ),
        )

        if (
            str(upstream_topic_hint or "").strip().upper() == "OTHER"
            and canonical_topic != "OTHER"
        ):
            canonical_topic = "OTHER"

        if canonical_topic and platform_kb_mode and isinstance(kb_context, dict):
            kb_context["topic"] = canonical_topic
            kb_context["intent_hint"] = canonical_topic
    except Exception:
        canonical_topic = ""

    free_mode = bool(is_lead and ai_turns <= FRONT_FREE_MODE_MAX_TURNS)
    try:
        if isinstance(kb_context, dict):
            kb_context["free_mode"] = free_mode
    except Exception:
        pass

    kb_section = ""
    try:
        if kb_context:
            kb_section = "KB Context (selected facts):\n" + json.dumps(kb_context, ensure_ascii=False)
    except Exception:
        kb_section = ""

    selected_pack_id = str((kb_context or {}).get("pack_id") or "").strip().upper()
    if not selected_pack_id and platform_runtime:
        selected_pack_id = str(platform_runtime.get("pack_id") or "").strip().upper()
    if not selected_pack_id:
        selected_pack_id = _pick_pack_for_intent(
            str((kb_context or {}).get("intent_hint") or last_intent or "").strip().upper()
        )
    if not selected_pack_id and segment_context_cleared:
        selected_pack_id = _pick_pack_for_intent(
            str((kb_context or {}).get("topic") or (kb_context or {}).get("topic_hint") or last_intent or "").strip().upper()
        )
    direct_scene = str((kb_context or {}).get("direct_scene") or "").strip()
    runtime_long_text = str((kb_context or {}).get("runtime_long_text") or "").strip()
    runtime_short_reply = str((kb_context or {}).get("runtime_short_reply") or "").strip()
    micro_scene = str((kb_context or {}).get("pack_micro_scene") or "").strip()
    operational_reference = str((kb_context or {}).get("operational_reference") or "").strip()
    reference_example = str((kb_context or {}).get("segment_reference_example") or "").strip()

    if platform_runtime:
        direct_scene = str(platform_runtime.get("direct_scene") or direct_scene or "").strip()
        runtime_long_text = str(platform_runtime.get("runtime_long_text") or runtime_long_text or "").strip()
        runtime_short_reply = str(platform_runtime.get("runtime_short_reply") or runtime_short_reply or "").strip()
        micro_scene = str(platform_runtime.get("micro_scene") or micro_scene or "").strip()
        operational_reference = str(
            direct_scene
            or platform_runtime.get("operational_reference")
            or operational_reference
            or ""
        ).strip()
        reference_example = str(platform_runtime.get("reference_example") or reference_example or "").strip()

    if selected_pack_id and not micro_scene:
        micro_scene = _kb_get_micro_scene(kb_snapshot, selected_pack_id)
    if selected_pack_id and not reference_example:
        reference_example = _kb_get_reference_example(kb_snapshot, effective_segment, selected_pack_id)
    if effective_segment and not operational_reference:
        operational_reference = _kb_get_segment_scene(kb_snapshot, effective_segment)
    if not operational_reference and (direct_scene or runtime_long_text or runtime_short_reply or micro_scene):
        operational_reference = (
            direct_scene
            or runtime_long_text
            or runtime_short_reply
            or micro_scene
        )

    platform_topic_hint = ""
    try:
        if platform_kb_mode:
            platform_topic_hint = "" if current_turn_topic_reset else _platform_topic_from_kb_rules(kb_snapshot_obj, user_text)
            if platform_topic_hint and not current_turn_topic_reset:
                kb_context["topic"] = platform_topic_hint
                kb_context["intent_hint"] = platform_topic_hint

            selected_pack_id = _platform_pack_from_profile(
                kb_snapshot_obj,
                "" if current_turn_topic_reset else (platform_topic_hint or str((kb_context or {}).get("intent_hint") or last_intent or "")),
                platform_segment_profile,
                selected_pack_id,
            )

            platform_material = _platform_pack_material(
                kb_snapshot_obj,
                platform_segment_profile,
                selected_pack_id,
            )

            if platform_material:
                micro_scene = str(platform_material.get("micro_scene") or micro_scene or "").strip()
                runtime_short_reply = str(platform_material.get("runtime_short_reply") or "").strip()
                runtime_long_text = str(platform_material.get("runtime_long_text") or "").strip()
                direct_scene = str(platform_material.get("direct_scene") or "").strip()
                reference_example = str(platform_material.get("reference_example") or reference_example or "").strip()
                operational_reference = str(platform_material.get("operational_reference") or operational_reference or "").strip()

                kb_context["pack_id"] = selected_pack_id
                kb_context["pack_micro_scene"] = micro_scene
                if runtime_short_reply:
                    kb_context["runtime_short_reply"] = runtime_short_reply
                if runtime_long_text:
                    kb_context["runtime_long_text"] = runtime_long_text
                if direct_scene:
                    kb_context["direct_scene"] = direct_scene
                if platform_material.get("material_source"):
                    kb_context["material_source"] = platform_material["material_source"]
                kb_context["segment_reference_example"] = reference_example
                kb_context["operational_reference"] = operational_reference
                kb_context["hydrated_from_platform_kb"] = True
    except Exception:
        pass

    # ----------------------------------------------------------
    # REFRESH DA ÂNCORA OPERACIONAL
    # Antes da resposta final, revisitamos o banco para reforçar
    # a melhor cena e o melhor exemplo disponível.
    # ----------------------------------------------------------
    refreshed_anchor = _refresh_operational_anchor(
        kb_snapshot=kb_snapshot,
        kb_context=kb_context if isinstance(kb_context, dict) else {},
        effective_segment=effective_segment,
        selected_pack_id=selected_pack_id,
        operational_family=operational_family,
    )
    reference_example = str((refreshed_anchor or {}).get("reference_example") or reference_example or "").strip()
    operational_reference = str((refreshed_anchor or {}).get("operational_reference") or operational_reference or "").strip()
    operational_family = str((refreshed_anchor or {}).get("operational_family") or operational_family or "").strip()

    # o reference_example só nasce de cena real do KB; nunca do relato do usuário
    if not reference_example and operational_reference and not _is_scene_echo(operational_reference, user_text):
        derived_steps = _split_scene_steps(operational_reference)
        if len(derived_steps) >= 2:
            reference_example = str(derived_steps[0] or "").strip()

    # ----------------------------------------------------------
    # CONTRATO OPERACIONAL BASE (consolidado cedo)
    # A partir daqui, toda microcena/rebuild/regeneração deve usar
    # a mesma base operacional consolidada.
    # ----------------------------------------------------------
    base_operational_contract = _build_operational_contract(
        kb_snapshot=kb_snapshot,
        kb_context=kb_context if isinstance(kb_context, dict) else {},
        effective_segment=effective_segment,
        operational_reference=operational_reference,
        reference_example=reference_example,
        operational_family=operational_family,
        topic=(canonical_topic or "OTHER"),
    )

    # ----------------------------------------------------------
    # PRIORIDADE DO KB (nova arquitetura)
    # Se já temos material suficiente do banco, usamos isso
    # como base da resposta e deixamos a IA apenas adaptar.
    # ----------------------------------------------------------
    kb_anchor_available = bool(
        operational_reference
        or reference_example
        or operational_family
        or selected_pack_id
    )
    kb_anchor_strong = False

    system_prompt = SYSTEM_PROMPT
    if free_mode:
        pass
    family_hint = _build_free_mode_family_hint(user_text, effective_segment)
    scene_hint_block = ""
    user_scene_block = ""

    try:
        if not operational_family:
            operational_family = str(
                _infer_operational_family(user_text, effective_segment)
                or ""
            ).strip()
    except Exception:
        operational_family = operational_family or ""

    kb_anchor_available = bool(
        operational_reference
        or reference_example
        or operational_family
        or selected_pack_id
    )

    reply_size_policy = _resolve_reply_size_policy(
        ai_turns=ai_turns,
        msg_type=msg_type,
        response_mode=response_mode,
        next_step=next_step,
        topic=(canonical_topic or topic or upstream_topic_hint),
        kb_rich=bool(kb_anchor_available),
        confidence=confidence,
        needs_clarify=needs_clarify,
        clarify_q=clarify_q,
        effective_segment=effective_segment,
        question_type=question_type,
    )

    real_scene_for_anchor = operational_reference if not _is_scene_echo(operational_reference, user_text) else ""
    real_example_for_anchor = reference_example if not _is_scene_echo(reference_example, user_text) else ""

    kb_anchor_strong = _has_strong_kb_anchor(
        kb_context=kb_context if isinstance(kb_context, dict) else {},
        effective_segment=effective_segment,
        operational_family=operational_family,
        operational_reference=real_scene_for_anchor,
        reference_example=real_example_for_anchor,
        selected_pack_id=selected_pack_id,
    )

    # Etapa 1 — não empurrar cena do KB no entendimento inicial do turno.
    # A IA entende primeiro; microcena só entra depois, se a própria IA
    # realmente cair num trilho prático.
    allow_scene_prompting = bool(
        free_mode
        and kb_anchor_strong
        and effective_segment
        and (
            str(operational_reference or "").strip()
            or str(reference_example or "").strip()
            or bool((base_operational_contract or {}).get("operational_ritual"))
        )
    )

    if allow_scene_prompting:
        scene_hint_block = _build_scene_hint_block(
            family_hint=family_hint,
            micro_scene=micro_scene,
            reference_example=reference_example,
            operational_reference=operational_reference,
        )
        if scene_hint_block:
            system_prompt += "\n" + scene_hint_block + "\n"

        user_scene_block = _build_user_scene_block(
            operational_reference=operational_reference,
            reference_example=reference_example,
            kb_section=kb_section,
            kb_compact=kb_compact,
        )
    else:
        # Mantém os fatos selecionados do KB, mas sem empurrar cena
        # antes da decisão soberana do modelo.
        # ARQUITETURA: NÃO vazar KB antes da confirmação de segmento
        if segment_for_prompt:
            user_scene_block = kb_section
        elif platform_kb_mode and (operational_reference or reference_example or micro_scene):
            user_scene_block = (
                "[BASE OPERACIONAL DO PLATFORM_KB]\n"
                + (f"topic_hint: {platform_topic_hint}\n" if platform_topic_hint else "")
                + (f"pack_id: {selected_pack_id}\n" if selected_pack_id else "")
                + (f"operational_reference: {operational_reference}\n" if operational_reference else "")
                + (f"reference_example: {reference_example}\n" if reference_example else "")
            )
        else:
            user_scene_block = ""

    kb_show_reply_seed = ""
    kb_forced_topic = ""
    if not operational_reference:
        operational_reference = ""

    allow_kb_payload_scene = bool(
        free_mode
        and allow_scene_prompting
        and (
            str(operational_reference or "").strip()
            or str(reference_example or "").strip()
        )
    )

    signup_url = str((kb_context or {}).get("signup_url") or os.getenv("FRONTEND_BASE") or "https://www.meirobo.com.br").strip()

    user_payload = (
        f"[MENSAGEM DO USUÁRIO]\n{user_text}\n\n"
        f"[ESTADO]\n"
        f"turno={ai_turns}\n"
        f"is_lead={'true' if is_lead else 'false'}\n"
        f"has_name={'true' if has_name else 'false'}\n"
        + (f"name_hint={name_hint}\n" if has_name else "")
        + (f"lead_name_from_current_turn={inferred_lead_name}\n" if inferred_lead_name else "")
        + (f"lead_segment_from_current_turn={inferred_lead_segment}\n" if inferred_lead_segment else "")
        + f"signup_url={signup_url}\n"
        + (f"segment_hint={segment_for_prompt}\n" if segment_for_prompt else "")
        + (
            "context_from_current_message=use_if_user_provided_name_profession_segment_or_use_case\n"
        )
        + (f"operational_family={operational_family}\n" if segment_for_prompt and operational_family else "")
        + (
            "segment_context_status=unconfirmed_context_only\n"
            if effective_segment and not segment_for_prompt else ""
        )
        + f"last_intent={last_intent or 'NONE'}\n"
        + f"last_user_goal={last_user_goal or 'NONE'}\n\n"
        + (
            "[BASE OPERACIONAL DO KB]\n"
            + (
                f"operational_reference: {str(operational_reference or '').strip()}\n"
                f"reference_example: {str(reference_example or '').strip()}\n"
                if (
                    allow_kb_payload_scene
                    and bool((operational_contract if 'operational_contract' in locals() else base_operational_contract if 'base_operational_contract' in locals() else {}).get("hydrated_from_docs"))
                ) else ""
            )
            + f"primary_goal: {str((operational_contract if 'operational_contract' in locals() else base_operational_contract if 'base_operational_contract' in locals() else {}).get('primary_goal') or '').strip()}\n"
            + f"allowed_next_step: {str((operational_contract if 'operational_contract' in locals() else base_operational_contract if 'base_operational_contract' in locals() else {}).get('allowed_next_step') or '').strip()}\n"
            + f"operational_ritual: {json.dumps(((operational_contract if 'operational_contract' in locals() else base_operational_contract if 'base_operational_contract' in locals() else {}).get('operational_ritual') or []) if bool((operational_contract if 'operational_contract' in locals() else base_operational_contract if 'base_operational_contract' in locals() else {}).get('hydrated_from_docs')) else [], ensure_ascii=False)}\n\n"
            if (
                (segment_for_prompt or platform_kb_mode)
                and bool((operational_contract if 'operational_contract' in locals() else base_operational_contract if 'base_operational_contract' in locals() else {}).get("hydrated_from_docs"))
                and (
                    (
                        allow_kb_payload_scene
                        and (
                            str(operational_reference or '').strip()
                            or str(reference_example or '').strip()
                        )
                    )
                    or ((operational_contract if 'operational_contract' in locals() else base_operational_contract if 'base_operational_contract' in locals() else {}).get('primary_goal'))
                    or ((operational_contract if 'operational_contract' in locals() else base_operational_contract if 'base_operational_contract' in locals() else {}).get('allowed_next_step'))
                    or ((operational_contract if 'operational_contract' in locals() else base_operational_contract if 'base_operational_contract' in locals() else {}).get('operational_ritual'))
                )
            )
            else ""
        )
        + (user_scene_block + "\n\n" if user_scene_block else "")
        + (
            "[PLATFORM PRICING FACTS]\n"
            + _front_build_price_facts_block()
            + "\n\n"
            if str((kb_context or {}).get("intent_hint") or "").strip().upper() == "PRECO"
            and _front_build_price_facts_block()
            else ""
        )
    )

    # ----------------------------------------------------------
    # Se o KB já trouxe cena operacional, reforçamos isso
    # para evitar improviso genérico do modelo.
    # ----------------------------------------------------------
    if kb_anchor_available:
        system_prompt += (
            "\n\nREGRA ADICIONAL:\n"
            "Se o KB trouxer archetype, ritual, capabilities, cena ou exemplo, use isso como referência factual e operacional.\n"
            "Você continua soberano para entender a intenção do lead e decidir se este turno pede explicação, discovery, demonstração prática ou encaminhamento.\n"
            "Não force microcena quando a pergunta for institucional, ampla, exploratória ou lateral.\n"
            "Quando o segmento estiver claro e a IA entender que vale demonstrar na prática, use o KB para mostrar valor real no dia a dia.\nSe o segmento ainda não estiver claro, a IA pode conduzir a conversa para descobrir isso antes de demonstrar.\n"
            "Em vendas, nunca responda como se o lead fosse o cliente final do segmento; fale com o dono/profissional e mostre o cliente dele sendo atendido pelo MEI Robô no WhatsApp.\n"
            "Evite trocar por outro tipo de fluxo quando a ancoragem do KB estiver clara e a intenção já estiver prática.\n"
        )

    system_prompt_json = (
        str(system_prompt or "").strip()
        + "\n\nResponda exclusivamente em json válido."
    ).strip()

    messages = [
        {"role": "system", "content": system_prompt_json},
        {"role": "user", "content": user_payload},
    ]

    try:
        # ----------------------------------------------------------
        # Chamada ao modelo (compat: SDK novo e antigo)
        # ----------------------------------------------------------
        _policy_max_tokens = int((reply_size_policy or {}).get("max_tokens") or FRONT_ANSWER_MAX_TOKENS)
        # O modelo agora devolve envelope JSON + replyText.
        # A política de tamanho continua valendo para o texto final,
        # mas a chamada precisa de folga para fechar o JSON.
        _json_call_max_tokens = min(
            FRONT_ANSWER_MAX_TOKENS,
            max(260, _policy_max_tokens + 160),
        )

        # -------------------------------------------------
        # RESERVA DE TOKENS PARA RESPOSTAS TÉCNICAS DIRECT
        #
        # Telemetria observada:
        # - output_tokens ≈ 118–121
        # - replyText limpo ≈ 659 caracteres
        # - texto técnico desejado ≈ 700–820 caracteres
        #
        # Isso indica exaustão de tokens na geração estruturada.
        # O envelope JSON consome parte da saída, e o modelo
        # interrompe a frase antes de concluir o conteúdo.
        #
        # Esta alteração atua somente em DIRECT técnico vindo da
        # platform_kb/global packs (AGENDA, SERVICOS, PEDIDOS,
        # STATUS, PROCESSO, ORCAMENTO), aumentando o orçamento de
        # saída para permitir que o GPT-4o mini conclua a resposta
        # e feche o JSON corretamente.
        #
        # Não altera:
        # - prompts;
        # - regras gerais de tamanho;
        # - áudio;
        # - DISCOVERY / SCENE / CLOSING.
        # -------------------------------------------------
        try:
            _contract_probe = (
                base_operational_contract
                if isinstance(base_operational_contract, dict)
                else {}
            )
            _topic_probe = str(topic or canonical_topic or "").strip().upper()
            _mode_probe = str(response_mode or "").strip().upper()

            _technical_direct_budget = bool(
                _mode_probe == "DIRECT"
                and _topic_probe in (
                    "AGENDA",
                    "SERVICOS",
                    "PEDIDOS",
                    "STATUS",
                    "PROCESSO",
                    "ORCAMENTO",
                )
                and (
                    _contract_probe.get("hydrated_from_platform_kb")
                    or _contract_probe.get("global_pack_fallback")
                )
            )

            if _technical_direct_budget:
                _json_call_max_tokens = max(_json_call_max_tokens, 420)
        except Exception:
            pass

        if _HAS_OPENAI_CLIENT and _client is not None:
            req_kwargs = {
                "model": MODEL,
                "temperature": TEMPERATURE,
                "max_tokens": _json_call_max_tokens,
                "messages": messages,
            }

            req_kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": _front_response_json_schema(),
            }

            resp = _client.chat.completions.create(**req_kwargs)
            raw = str(resp.choices[0].message.content or "").strip()
            # usage no SDK novo
            token_usage = {}
            try:
                u = getattr(resp, "usage", None)
                if u:
                    token_usage = {
                        "input_tokens": int(getattr(u, "prompt_tokens", 0) or 0),
                        "output_tokens": int(getattr(u, "completion_tokens", 0) or 0),
                        "total_tokens": int(getattr(u, "total_tokens", 0) or 0),
                    }
            except Exception:
                token_usage = {}
        else:
            # SDK antigo (openai<1.x)
            resp = openai.ChatCompletion.create(  # type: ignore
                model=MODEL,
                temperature=TEMPERATURE,
                max_tokens=_json_call_max_tokens,
                messages=messages,
                response_format={
                    "type": "json_schema",
                    "json_schema": _front_response_json_schema(),
                },
            )
            raw = (resp["choices"][0]["message"]["content"] or "").strip()
            # usage no SDK antigo
            token_usage = {}
            try:
                u = resp.get("usage") or {}
                token_usage = {
                    "input_tokens": int(u.get("prompt_tokens") or 0),
                    "output_tokens": int(u.get("completion_tokens") or 0),
                    "total_tokens": int(u.get("total_tokens") or 0),
                }
            except Exception:
                token_usage = {}


        # raw já foi preenchido acima (compat)

        # ----------------------------------------------------------
        # FREE MODE: a IA pode responder em texto livre.
        # Só tentamos JSON se houver cara de objeto JSON.
        # ----------------------------------------------------------
        raw_json = raw
        cleaned = str(raw or "").strip()
        json_fail_safe_used = False

        if free_mode:
            looks_like_json = cleaned.startswith("{") or cleaned.startswith("```json") or cleaned.startswith("```")

            if not looks_like_json:
                preferred_topic_hint = _preferred_topic_from_kb(
                    kb_context=kb_context if isinstance(kb_context, dict) else {},
                    current_topic="OTHER",
                )
                if kb_forced_topic and kb_forced_topic in TOPICS:
                    preferred_topic_hint = kb_forced_topic

                free_text_payload = _parse_free_mode_text_response(
                    cleaned,
                    topic_hint=preferred_topic_hint,
                    confidence_hint=("high" if kb_anchor_strong else "medium"),
                )
                if free_text_payload and str(free_text_payload.get("replyText") or "").strip():
                    data = free_text_payload
                else:
                    raw_text_candidate = _sanitize_user_facing_reply(cleaned)
                    raw_text_candidate = re.sub(r"\s{2,}", " ", raw_text_candidate).strip()

                    if raw_text_candidate:
                        data = {
                            "response_mode": "DIRECT",
                            "replyText": raw_text_candidate,
                            "spokenText": raw_text_candidate,
                            "understanding": {
                                "topic": preferred_topic_hint if preferred_topic_hint in TOPICS else "OTHER",
                                "confidence": ("high" if kb_anchor_strong else "medium"),
                            },
                            "nextStep": "NONE",
                            "shouldEnd": False,
                            "nameUse": "none",
                            "prefersText": False,
                            "replySource": "front_raw_fallback",
                        }
                    else:
                        data = {}
            else:
                try:
                    cleaned = re.sub(r"^```json\s*", "", cleaned, flags=re.I)
                    cleaned = re.sub(r"^```\s*", "", cleaned, flags=re.I)
                    cleaned = re.sub(r"\s*```$", "", cleaned)

                    m = re.search(r"\{[\s\S]*\}", cleaned, flags=re.DOTALL)
                    if m:
                        raw_json = m.group(0)
                    else:
                        raw_json = cleaned

                    data = json.loads(raw_json)
                except Exception:
                    repaired = re.sub(r",(\s*[}\]])", r"\1", raw_json)
                    try:
                        data = json.loads(repaired)
                        raw_json = repaired
                    except Exception as e:
                        logging.warning(
                            "[CONVERSATIONAL_FRONT][JSON_FAIL_SAFE] usando resposta textual da IA | err=%s",
                            e,
                        )
                        json_fail_safe_used = True

                        # Preserva o texto bruto da IA para o fallback.
                        try:
                            data = {"reply": str(raw or "").strip()}
                        except Exception:
                            data = {"reply": ""}

                        # Mesmo com JSON inválido, tenta preservar nome e segmento que
                        # o próprio modelo já tentou devolver no payload textual.
                        try:
                            data = _merge_identity_fields_from_raw_ai_payload(data, raw or raw_json or "")
                        except Exception as e:
                            logging.warning("[CONVERSATIONAL_FRONT][IDENTITY_SALVAGE_FAIL] %s", e)

                        salvaged = {}
                        try:
                            salvaged = _salvage_free_mode_payload(repaired or raw_json or raw)
                        except Exception:
                            salvaged = {}

                        if salvaged and str((salvaged or {}).get("replyText") or "").strip():
                            data = _merge_identity_fields_from_raw_ai_payload(salvaged, raw or raw_json or "")
                        else:
                            preferred_topic_hint = _preferred_topic_from_kb(
                                kb_context=kb_context if isinstance(kb_context, dict) else {},
                                current_topic="OTHER",
                            )
                            if kb_forced_topic and kb_forced_topic in TOPICS:
                                preferred_topic_hint = kb_forced_topic

                            free_text_payload = _parse_free_mode_text_response(
                                str(raw or ""),
                                topic_hint=preferred_topic_hint,
                                confidence_hint=("high" if kb_anchor_strong else "medium"),
                            )
                            if free_text_payload and str(free_text_payload.get("replyText") or "").strip():
                                data = _merge_identity_fields_from_raw_ai_payload(free_text_payload, raw or raw_json or "")
                            else:
                                raw_text_candidate = ""
                                if not (
                                    str(raw or "").lstrip().startswith("{")
                                    or str(raw or "").lstrip().startswith("```")
                                ):
                                    raw_text_candidate = _sanitize_user_facing_reply(str(raw or ""))
                                raw_text_candidate = re.sub(r"\s{2,}", " ", raw_text_candidate).strip()

                                if raw_text_candidate:
                                    data = {
                                        "response_mode": "DIRECT",
                                        "replyText": raw_text_candidate,
                                        "spokenText": raw_text_candidate,
                                        "understanding": {
                                            "topic": preferred_topic_hint if preferred_topic_hint in TOPICS else "OTHER",
                                            "confidence": ("high" if kb_anchor_strong else "medium"),
                                        },
                                        "nextStep": "NONE",
                                        "shouldEnd": False,
                                        "nameUse": "none",
                                        "prefersText": False,
                                        "replySource": "front_raw_fallback",
                                    }
                                    data = _merge_identity_fields_from_raw_ai_payload(data, raw or raw_json or "")
                                else:
                                    data = {}
        else:
            # Fora do free_mode, mantém protocolo JSON.
            try:
                cleaned = re.sub(r"^```json\s*", "", cleaned, flags=re.I)
                cleaned = re.sub(r"^```\s*", "", cleaned, flags=re.I)
                cleaned = re.sub(r"\s*```$", "", cleaned)

                m = re.search(r"\{[\s\S]*\}", cleaned, flags=re.DOTALL)
                if m:
                    raw_json = m.group(0)
                else:
                    raw_json = cleaned

                data = json.loads(raw_json)
            except Exception:
                repaired = re.sub(r",(\s*[}\]])", r"\1", raw_json)
                try:
                    data = json.loads(repaired)
                    raw_json = repaired
                except Exception as e:
                    logging.warning(
                        "[CONVERSATIONAL_FRONT][JSON_FAIL_SAFE] usando resposta textual da IA | err=%s",
                        e,
                    )
                    json_fail_safe_used = True
                    data = {}

        # ----------------------------------------------------------
        # Blindagem pós-parse/fail-safe:
        # se qualquer fallback sobrescreveu data, reanexa nome/segmento
        # inferidos da mensagem atual antes do parse canônico.
        # ----------------------------------------------------------
        try:
            if isinstance(data, dict):
                data = _merge_identity_fields_from_raw_ai_payload(data, raw or raw_json or "")
        except Exception as e:
            logging.warning("[CONVERSATIONAL_FRONT][IDENTITY_POST_PARSE_FAIL] %s", e)

        # ----------------------------------------------------------
        # Parse canônico do decider (packs_v1): por padrão pode vir sem replyText final.
        # ----------------------------------------------------------
        understanding = data.get("understanding") or {}

        response_mode = _normalize_response_mode(
            data.get("response_mode")
            or data.get("responseMode")
            or understanding.get("response_mode")
            or understanding.get("responseMode")
        )

        raw_intent = str(
            data.get("intent")
            or understanding.get("intent")
            or understanding.get("topic")
            or ""
        ).strip().upper()

        intent = raw_intent or "OTHER"

        confidence = str(
            data.get("confidence")
            or understanding.get("confidence")
            or "low"
        ).strip().lower()

        question_type = str(
            data.get("question_type")
            or understanding.get("question_type")
            or "broad"
        ).strip().lower()

        if question_type not in ("broad", "punctual", "continuity", "simulation"):
            question_type = "broad"

        try:
            logging.info(
                "[QUESTION_TYPE_TRACE] ai_turns=%s raw_data_qt=%s raw_understanding_qt=%s final_qt=%s response_mode=%s topic=%s user_text=%s",
                ai_turns,
                str(data.get("question_type") or ""),
                str(understanding.get("question_type") or ""),
                str(question_type or ""),
                str(response_mode or ""),
                str(topic or intent or ""),
                str(user_text or "")[:160],
            )
        except Exception:
            pass

        # ----------------------------------------------------------
        # Trava estrutural contra topic bleeding.
        #
        # Continuidade factual deve continuar existindo para perguntas
        # pontuais/continuity, mas uma pergunta ampla em turno posterior
        # não deve herdar automaticamente o tópico anterior quando o
        # próprio modelo/roteamento não confirmou esse tópico.
        #
        # Não usa palavra-chave de assunto, não lista segmentos e não
        # altera prompt: só combina sinais estruturais já existentes.
        # ----------------------------------------------------------
        try:
            raw_topic_signal = str(
                data.get("topic")
                or understanding.get("topic")
                or raw_intent
                or ""
            ).strip().upper()

            upstream_topic_signal = str(upstream_topic_hint or "").strip().upper()

            _front_topic_pivot_detected = bool(
                int(ai_turns or 0) > 0
                and question_type == "broad"
                and upstream_topic_signal in ("", "OTHER")
                and (
                    (
                        raw_topic_signal
                        and raw_topic_signal not in TOPICS
                        and raw_topic_signal != "OTHER"
                    )
                    or (
                        intent == "OTHER"
                        and confidence in ("high", "medium")
                    )
                )
            )
        except Exception:
            _front_topic_pivot_detected = False

        needs_clarify = str(
            data.get("needsClarify")
            or understanding.get("needsClarify")
            or "no"
        ).strip().lower()

        inferred_lead_name = str(
            data.get("lead_name")
            or data.get("leadName")
            or ""
        ).strip()

        # Fallback estrutural seguro para nome do lead no turno atual.
        # Atua quando o JSON quebra e o campo leadName não vem do modelo.
        # Não usa lista de nomes nem frases prontas de resposta.
        try:
            if not inferred_lead_name:
                _turn_name = _extract_lead_name_from_current_turn(user_text)
                if _turn_name:
                    inferred_lead_name = _turn_name
                    data["lead_name"] = _turn_name
                    data["leadName"] = _turn_name
        except Exception as e:
            logging.warning("[CONVERSATIONAL_FRONT][LEAD_NAME_FALLBACK_FAIL] %s", e)

        inferred_lead_segment = str(
            data.get("lead_segment")
            or data.get("leadSegment")
            or ""
        ).strip()

        inferred_lead_segment_raw = str(
            data.get("lead_segment_raw")
            or data.get("leadSegmentRaw")
            or ""
        ).strip()

        # Fallback estrutural seguro para atividade/profissão do lead.
        # Usado quando o JSON do modelo quebra e não entrega leadSegmentRaw.
        # Não usa lista de profissões nem mapeamento por palavra-chave de segmento.
        try:
            if not inferred_lead_segment_raw:
                _ut = str(user_text or "").strip()
                _m = re.search(
                    r"(?i)\b(?:trabalho com|trabalho na área de|trabalho como|atuo com|atuo na área de|atuo como)\s+([a-zÀ-ÿ][a-zÀ-ÿ\s]{2,40}?)(?:\.|,| e | para | como |$)",
                    _ut,
                )
                if _m:
                    _raw_activity = re.sub(r"\s{2,}", " ", _m.group(1)).strip()
                    if (
                        _raw_activity
                        and _raw_activity.lower() != str(inferred_lead_name or "").strip().lower()
                    ):
                        inferred_lead_segment_raw = _raw_activity
                        data["lead_segment_raw"] = _raw_activity
                        data["leadSegmentRaw"] = _raw_activity
        except Exception as e:
            logging.warning("[CONVERSATIONAL_FRONT][LEAD_SEGMENT_RAW_FALLBACK_FAIL] %s", e)


        if not inferred_lead_segment_raw and inferred_lead_segment:
            inferred_lead_segment_raw = inferred_lead_segment

        try:
            if inferred_lead_segment_raw:
                if not segment_hint:
                    segment_hint = inferred_lead_segment_raw

                if isinstance(operational_contract, dict) and not str(
                    operational_contract.get("segment") or ""
                ).strip():
                    operational_contract["segment"] = inferred_lead_segment_raw
        except Exception:
            pass

        # ----------------------------------------------------------
        # Hidratação pós-parse do turno atual.
        # O modelo só retorna lead_name/lead_segment depois da chamada.
        # Portanto, name_hint/segment_hint precisam ser atualizados aqui,
        # antes do cálculo de has_name/has_segment_context e antes do retorno.
        # ----------------------------------------------------------
        try:
            if inferred_lead_segment and not segment_hint:
                segment_hint = inferred_lead_segment

            if inferred_lead_segment_raw and not segment_hint:
                segment_hint = inferred_lead_segment_raw

            if not segment_hint:
                _declared_segment = _front_extract_declared_segment_from_user_text(user_text)
                if _declared_segment:
                    segment_hint = _declared_segment
                    inferred_lead_segment_raw = inferred_lead_segment_raw or _declared_segment
                    inferred_lead_segment = inferred_lead_segment or _declared_segment

            try:
                if isinstance(operational_contract, dict):
                    if inferred_lead_segment_raw and not str(operational_contract.get("segment") or "").strip():
                        operational_contract["segment"] = inferred_lead_segment_raw
                    elif inferred_lead_segment and not str(operational_contract.get("segment") or "").strip():
                        operational_contract["segment"] = inferred_lead_segment
            except Exception:
                pass

            # Nome do turno atual:
            # o lead pode informar o nome em qualquer ordem da conversa.
            # Se o nome foi dito neste turno e passou pela sanitização
            # estrutural, ele já deve contar como identidade resolvida
            # para este retorno e sair no payload para persistência.
            #
            # Não usa lista de nomes, profissões ou segmentos.
            # Não altera prompt.
            # Não chama IA adicional.
            current_turn_lead_name = _front_sanitize_lead_name_candidate(
                inferred_lead_name,
                segment_refs=[
                    segment_hint,
                    inferred_lead_segment_raw,
                    inferred_lead_segment,
                    state_summary.get("segment"),
                    state_summary.get("segmentHint"),
                    state_summary.get("leadSegmentRaw"),
                ],
            )

            # Quando o modelo devolve um leadName inválido (ex.: atividade/segmento)
            # no mesmo inbound consolidado, o fallback anterior não roda porque
            # inferred_lead_name não está vazio. Ainda assim, o usuário pode ter
            # informado o nome no próprio texto.
            #
            # Aqui não usamos lista de nomes, profissão ou segmento; apenas
            # reaproveitamos o extrator estrutural já existente e validamos o
            # resultado contra os mesmos segment_refs. Não altera prompt.
            if not current_turn_lead_name:
                try:
                    _turn_name = _extract_lead_name_from_current_turn(user_text)
                    _turn_name = _front_sanitize_lead_name_candidate(
                        _turn_name,
                        segment_refs=[
                            segment_hint,
                            inferred_lead_segment_raw,
                            inferred_lead_segment,
                            state_summary.get("segment"),
                            state_summary.get("segmentHint"),
                            state_summary.get("leadSegmentRaw"),
                        ],
                    )
                    if _turn_name:
                        current_turn_lead_name = _turn_name
                        inferred_lead_name = _turn_name
                        data["lead_name"] = _turn_name
                        data["leadName"] = _turn_name
                        if isinstance(understanding, dict):
                            understanding["lead_name"] = _turn_name
                            understanding["leadName"] = _turn_name
                except Exception:
                    pass
            if current_turn_lead_name and not name_hint:
                name_hint = current_turn_lead_name

            has_name = bool(confirmed_has_name or current_turn_lead_name)
            has_lead_name = has_name

            if str(segment_hint or "").strip():
                has_segment_context = True
                discovery_resolved = bool(has_name and has_segment_context)

        except Exception:
            pass

        clarify_q = str(
            data.get("clarifyQuestion")
            or understanding.get("clarifyQuestion")
            or ""
        ).strip()

        pack_profile = str(data.get("packProfile") or understanding.get("packProfile") or "generic").strip()
        render_mode = str(data.get("renderMode") or understanding.get("renderMode") or "short").strip().lower()
        segment_key = str(data.get("segmentKey") or understanding.get("segmentKey") or "").strip()
        segment_conf = str(data.get("segmentConfidence") or understanding.get("segmentConfidence") or "low").strip().lower()
        should_ask_segment = str(data.get("shouldAskSegment") or "no").strip().lower()
        pack_id = str(data.get("packId") or (data.get("decider") or {}).get("packId") or "").strip()

        # ----------------------------------------------------------
        # Continuidade do turno atual:
        # o modelo pode ter reconhecido nome/segmento na própria fala
        # antes disso existir no state_summary.
        # Não cria frase, não usa palavra-chave, só consome sinais estruturados.
        # ----------------------------------------------------------
        try:
            _name_use_probe = str(
                data.get("nameUse")
                or understanding.get("nameUse")
                or understanding.get("name_use")
                or ""
            ).strip().lower()

            if not has_name:
                has_lead_name = False

            current_turn_segment_resolved = bool(
                str(segment_key or "").strip()
                and segment_conf in ("high", "medium")
                and should_ask_segment != "yes"
            )

            if current_turn_segment_resolved:
                has_segment_context = True

            discovery_resolved = bool(has_name and has_segment_context)

        except Exception:
            current_turn_segment_resolved = False

        # Back-compat: alguns retornos antigos ainda vêm com replyText/spokenText
        reply_text = str(
            data.get("replyText")
            or data.get("mensagem")
            or ""
        ).strip()
        spoken_text = str(data.get("spokenText") or "").strip()

        payload_reply_source = str(data.get("replySource") or "").strip()
        if payload_reply_source:
            reply_source = payload_reply_source

        if free_mode and reply_text and not spoken_text:
            spoken_text = reply_text

        if free_mode and not reply_text:
            raw_text_candidate = ""
            if not (
                str(raw or "").lstrip().startswith("{")
                or str(raw or "").lstrip().startswith("```")
            ):
                raw_text_candidate = _sanitize_user_facing_reply(str(raw or ""))
            raw_text_candidate = re.sub(r"\s{2,}", " ", raw_text_candidate).strip()

            if raw_text_candidate:
                reply_text = raw_text_candidate
                if not spoken_text:
                    spoken_text = raw_text_candidate
                if not str(reply_source or "").strip():
                    reply_source = "front_raw_fallback"

        # Compat: topic é o intent (mantém contrato anterior)
        topic = intent
        if topic not in TOPICS:
            topic = "OTHER"

        # Se não há KB segmentado hidratado, OTHER do modelo não pode apagar
        # a intenção já resolvida pelo platform_kb.
        try:
            if (
                platform_kb_mode
                and canonical_topic
                and canonical_topic in TOPICS
                and canonical_topic != "OTHER"
                and topic == "OTHER"
                and not current_turn_topic_reset
                and not _front_topic_pivot_detected
            ):
                topic = canonical_topic
                intent = canonical_topic
                if confidence not in ("high", "medium"):
                    confidence = "medium"
        except Exception:
            pass

        # 🔒 Aplicação determinística de sinais do platform_kb
        # Só atua sem KB segmentado hidratado.
        forced_topic = ""
        try:
            if current_turn_topic_reset:
                selected_pack_id = ""
                operational_reference = ""
                reference_example = ""
                micro_scene = ""
                direct_scene = ""
                runtime_short_reply = ""
                runtime_long_text = ""
                if isinstance(kb_context, dict):
                    for _reset_key in (
                        "pack_id",
                        "pack_micro_scene",
                        "micro_scene",
                        "micro_scene_conversational",
                        "reference_example",
                        "segment_reference_example",
                        "operational_reference",
                        "direct_scene",
                        "runtime_short_reply",
                        "runtime_long_text",
                        "operational_ritual",
                        "has_practical_scene",
                        "micro_scene_allowed",
                    ):
                        kb_context.pop(_reset_key, None)

            if platform_kb_mode and not current_turn_topic_reset:
                forced_topic = str((platform_runtime or {}).get("topic") or "").strip().upper()
                if (
                    forced_topic in TOPICS
                    and forced_topic != "OTHER"
                    and not current_turn_topic_reset
                    and not _front_topic_pivot_detected
                ):
                    topic = forced_topic
                    intent = forced_topic
        except Exception:
            forced_topic = ""

        next_step = str(data.get("nextStep") or data.get("next_step") or "NONE").strip().upper()
        if next_step not in ("NONE", "SEND_LINK"):
            next_step = "NONE"

        should_end = bool(data.get("shouldEnd")) or bool(data.get("should_end"))

        # 🔒 Seleção de pack baseada em topic (fallback inteligente via platform_kb)
        try:
            _packs = (kb_snapshot_obj.get("value_packs_v1") or {})

            if not segment_for_prompt:
                if topic == "AGENDA" and "PACK_A_AGENDA" in _packs:
                    selected_pack_id = "PACK_A_AGENDA"
                elif topic == "PRICING" and "PACK_B_SERVICOS" in _packs:
                    selected_pack_id = "PACK_B_SERVICOS"
                elif topic == "PROCESS" and "PACK_D_STATUS" in _packs:
                    selected_pack_id = "PACK_D_STATUS"
        except Exception:
            pass


        # ----------------------------------------------------------
        # Temperatura de entendimento (heurística local)
        # - evita OTHER + high
        # - sobe intenção de ação explícita para ATIVAR
        # - força clarify quando a frase ficou ambígua
        # ----------------------------------------------------------
        topic, confidence, needs_clarify, clarify_q, next_step = _infer_understanding_temperature(
            user_text=user_text,
            topic=topic,
            confidence=confidence,
            needs_clarify=needs_clarify,
            clarify_q=clarify_q,
            next_step=next_step,
        )

        # ----------------------------------------------------------
        # Continuidade conversacional:
        # se nome e segmento já foram obtidos,
        # não repetir descoberta.
        # ----------------------------------------------------------
        if discovery_resolved:
            needs_clarify = "no"
            clarify_q = ""
            if should_ask_segment == "yes":
                should_ask_segment = "no"

        try:
            if (
                platform_kb_mode
                and canonical_topic
                and canonical_topic in TOPICS
                and canonical_topic != "OTHER"
                and topic == "OTHER"
                and not current_turn_topic_reset
                and not _front_topic_pivot_detected
            ):
                topic = canonical_topic
                intent = canonical_topic
                if confidence not in ("high", "medium"):
                    confidence = "medium"
        except Exception:
            pass

        try:
            if (
                platform_kb_mode
                and forced_topic in TOPICS
                and forced_topic != "OTHER"
                and not _front_topic_pivot_detected
            ):
                topic = forced_topic
                intent = forced_topic
                if confidence not in ("high", "medium"):
                    confidence = "medium"
        except Exception:
            pass

        try:
            preferred_topic = _preferred_topic_from_kb(
                kb_context=kb_context if isinstance(kb_context, dict) else {},
                current_topic=topic,
            )
            if (
                topic in ("OTHER", "")
                and preferred_topic in TOPICS
                and preferred_topic not in ("OTHER", "")
                and not current_turn_topic_reset
                and not _front_topic_pivot_detected
            ):
                topic = preferred_topic
                if confidence not in ("high", "medium"):
                    confidence = "medium"
        except Exception:
            pass

        try:
            if platform_kb_mode:
                selected_pack_id = _platform_pack_from_profile(
                    kb_snapshot_obj,
                    topic,
                    platform_segment_profile,
                    selected_pack_id,
                )

                platform_material = _platform_pack_material(
                    kb_snapshot_obj,
                    platform_segment_profile,
                    selected_pack_id,
                )

                if platform_material:
                    micro_scene = str(platform_material.get("micro_scene") or micro_scene or "").strip()
                    runtime_short_reply = str(platform_material.get("runtime_short_reply") or "").strip()
                    runtime_long_text = str(platform_material.get("runtime_long_text") or "").strip()
                    direct_scene = str(platform_material.get("direct_scene") or "").strip()
                    reference_example = str(platform_material.get("reference_example") or reference_example or "").strip()
                    operational_reference = str(platform_material.get("operational_reference") or operational_reference or "").strip()
        except Exception:
            pass

        operational_contract = _build_operational_contract(
            kb_snapshot=kb_snapshot,
            kb_context=kb_context if isinstance(kb_context, dict) else {},
                        effective_segment=effective_segment,
            operational_reference=operational_reference,
            reference_example=reference_example,
            operational_family=operational_family,
            topic=topic,
        )

        try:
            if isinstance(operational_contract, dict):
                logging.info(
                    "[PRACTICAL_SCENE_TRACE] stage=after_build value=%s hydrated=%s segment=%s has_micro_scene=%s has_micro_scene_conversational=%s has_pack_micro_scene=%s has_operational_reference=%s",
                    bool(operational_contract.get("has_practical_scene")),
                    bool(operational_contract.get("hydrated_from_docs")),
                    str(operational_contract.get("segment") or ""),
                    bool(str(operational_contract.get("micro_scene") or "").strip()),
                    bool(str(operational_contract.get("micro_scene_conversational") or "").strip()),
                    bool(str(operational_contract.get("pack_micro_scene") or "").strip()),
                    bool(str(operational_contract.get("operational_reference") or "").strip()),
                )
        except Exception:
            pass

        try:
            if platform_kb_mode and isinstance(operational_contract, dict):
                if (
                    canonical_topic
                    and canonical_topic in TOPICS
                    and canonical_topic != "OTHER"
                    and not _front_topic_pivot_detected
                ):
                    operational_contract["topic"] = canonical_topic
                    topic = canonical_topic
                    intent = canonical_topic

                _platform_runtime_operational_allowed = bool(
                    operational_contract.get("hydrated_from_docs")
                    or str(operational_contract.get("archetype_id") or "").strip()
                )

                if platform_runtime:
                    if platform_runtime.get("pack_id"):
                        operational_contract["selected_pack_id"] = platform_runtime["pack_id"]
                    if platform_runtime.get("platform_segment_key"):
                        operational_contract["platform_segment_key"] = platform_runtime["platform_segment_key"]
                    if _platform_runtime_operational_allowed and platform_runtime.get("direct_scene"):
                        operational_contract["direct_scene"] = platform_runtime["direct_scene"]
                    if _platform_runtime_operational_allowed and platform_runtime.get("runtime_long_text"):
                        operational_contract["runtime_long_text"] = platform_runtime["runtime_long_text"]
                    if _platform_runtime_operational_allowed and platform_runtime.get("runtime_short_reply"):
                        operational_contract["runtime_short_reply"] = platform_runtime["runtime_short_reply"]
                    elif (not _platform_runtime_operational_allowed) and platform_runtime.get("runtime_compact_reply"):
                        operational_contract["runtime_short_reply"] = platform_runtime["runtime_compact_reply"]
                    if _platform_runtime_operational_allowed and operational_reference:
                        operational_contract["operational_reference"] = operational_reference
                    if _platform_runtime_operational_allowed and reference_example:
                        operational_contract["reference_example"] = reference_example
                        operational_contract["has_reference_example"] = True
                    if _platform_runtime_operational_allowed and micro_scene:
                        operational_contract["pack_micro_scene"] = micro_scene
                        operational_contract["has_practical_scene"] = True
                    try:
                        logging.info(
                            "[PRACTICAL_SCENE_TRACE] stage=after_platform_runtime value=%s allowed=%s has_micro_scene_var=%s has_pack_micro_scene=%s has_operational_reference=%s",
                            bool(operational_contract.get("has_practical_scene")),
                            bool(_platform_runtime_operational_allowed),
                            bool(str(micro_scene or "").strip()),
                            bool(str(operational_contract.get("pack_micro_scene") or "").strip()),
                            bool(str(operational_contract.get("operational_reference") or "").strip()),
                        )
                    except Exception:
                        pass
                    if platform_runtime.get("material_source"):
                        operational_contract["material_source"] = platform_runtime["material_source"]

                    operational_contract["hydrated_from_platform_kb"] = True
                    operational_contract["global_pack_fallback"] = True
        except Exception:
            pass

        # ----------------------------------------------------------
        # SANEAMENTO FINAL DO CONTRATO OPERACIONAL
        #
        # IMPORTANTE:
        # Mesmo que o kb_context tenha sido limpo anteriormente,
        # o operational_contract pode já ter sido montado com um
        # subsegmento escolhido por similaridade (ex.: ótica).
        #
        # Se a identidade estrutural desse contrato não for compatível
        # com o texto atual do lead, o contrato é descartado aqui,
        # imediatamente antes de qualquer decisão de SCENE/microcena.
        #
        # Princípios preservados:
        # - sem palavras-chave hardcoded;
        # - sem regex de linguagem;
        # - sem alteração de prompts;
        # - sem nova chamada ao modelo.
        # ----------------------------------------------------------
        try:
            _contract_segment_ok = True

            if (
                isinstance(operational_contract, dict)
                and str(operational_contract.get("segment") or "").strip()
                and str(user_text or "").strip()
            ):
                _contract_segment = str(operational_contract.get("segment") or "").strip()
                _persisted_segment = str(segment_hint or sticky_segment_hint or "").strip()

                if (
                    _persisted_segment
                    and _normalize_lookup_key(_contract_segment) == _normalize_lookup_key(_persisted_segment)
                ):
                    _contract_segment_ok = True
                else:
                    _contract_segment_ok = _doc_identity_is_compatible_with_current_text(
                        user_text=user_text,
                        doc=operational_contract,
                        doc_key=_contract_segment,
                        min_score=2,
                    )

            if not _contract_segment_ok:
                operational_contract = {}
                base_operational_contract = {}

                operational_reference = ""
                reference_example = ""
                operational_family = ""
                selected_pack_id = ""

                try:
                    if isinstance(kb_context, dict):
                        kb_context["segment_context_status"] = (
                            "final_contract_rejected_as_incompatible"
                        )
                except Exception:
                    pass
        except Exception:
            pass

        # ----------------------------------------------------------
        # SANEAMENTO FINAL DOS DOCUMENTOS OPERACIONAIS
        #
        # O contrato pode ter sido esvaziado, mas o assembly estruturado
        # ainda recebe real_kb_docs. Se subsegment_doc/segment_doc mantiver
        # o documento incompatível, a resposta final ainda pode sair com
        # microcena do segmento errado.
        #
        # Esta validação é genérica:
        # - não usa palavras-chave de segmento;
        # - não interpreta expressões do usuário;
        # - não altera prompt;
        # - não cria chamada nova ao modelo;
        # - funciona para qualquer segmento/subsegmento escolhido por
        #   similaridade indevida.
        # ----------------------------------------------------------
        try:
            _docs_segment_ok = True
            _selected_doc = {}
            _selected_key = ""

            if isinstance(real_kb_docs, dict):
                _selected_doc = (
                    real_kb_docs.get("subsegment_doc")
                    or real_kb_docs.get("segment_doc")
                    or {}
                )

            if isinstance(_selected_doc, dict) and _selected_doc:
                _selected_key = str(
                    _selected_doc.get("id")
                    or _selected_doc.get("subsegment_id")
                    or _selected_doc.get("segment_id")
                    or ""
                ).strip()

                if str(user_text or "").strip():
                    _selected_key_norm = _normalize_lookup_key(_selected_key)
                    _persisted_norm = _normalize_lookup_key(
                        segment_hint or sticky_segment_hint or ""
                    )

                    if (
                        _persisted_norm
                        and _selected_key_norm
                        and (
                            _persisted_norm == _selected_key_norm
                            or _persisted_norm in _selected_key_norm
                            or _selected_key_norm in _persisted_norm
                        )
                    ):
                        _docs_segment_ok = True
                    else:
                        _docs_segment_ok = _doc_identity_is_compatible_with_current_text(
                            user_text=user_text,
                            doc=_selected_doc,
                            doc_key=_selected_key,
                            min_score=2,
                        )

            if not _docs_segment_ok:
                real_kb_docs = {
                    "subsegment_doc": {},
                    "segment_doc": {},
                    "archetype_doc": {},
                }

                try:
                    hydrated_from_docs = False
                    found_sub = False
                    found_seg = False
                    found_arch = False
                    effective_segment = ""
                    segment_for_prompt = ""
                except Exception:
                    pass

                try:
                    if isinstance(kb_context, dict):
                        for key in (
                            "subsegment_hint",
                            "effective_subsegment",
                            "segment_hint",
                            "segment_id",
                            "archetype_id",
                            "segment_profile",
                            "operational_family",
                            "operational_reference",
                            "segment_reference_example",
                            "pack_micro_scene",
                            "micro_scene",
                            "micro_scene_conversational",
                            "reference_example",
                            "practical_scene",
                            "direct_scene",
                            "runtime_short_reply",
                            "runtime_long_text",
                            "has_reference_example",
                            "has_practical_scene",
                            "hydrated_from_docs",
                            "micro_scene_allowed",
                        ):
                            kb_context.pop(key, None)

                        kb_context["segment_context_status"] = (
                            "final_docs_rejected_as_incompatible"
                        )
                except Exception:
                    pass

                try:
                    operational_contract = {}
                    base_operational_contract = {}
                    operational_reference = ""
                    reference_example = ""
                    operational_family = ""
                    selected_pack_id = ""
                except Exception:
                    pass
        except Exception:
            pass

        has_real_operational_context = False
        try:
            _op_gate_doc_key = str((operational_contract if isinstance(operational_contract, dict) else {}).get("segment") or "")
            _op_gate_identity_score = 0
            try:
                if isinstance(operational_contract, dict):
                    _op_gate_identity_doc = {
                        "id": operational_contract.get("id"),
                        "name": operational_contract.get("name"),
                        "title": operational_contract.get("title"),
                        "label": operational_contract.get("label"),
                        "keywords": operational_contract.get("keywords"),
                        "one_liner": operational_contract.get("one_liner"),
                        "segment": operational_contract.get("segment"),
                        "segment_id": operational_contract.get("segment_id"),
                        "subsegment": operational_contract.get("subsegment"),
                        "subsegment_id": operational_contract.get("subsegment_id"),
                        "archetype_id": operational_contract.get("archetype_id"),
                        "service_noun": operational_contract.get("service_noun"),
                        "customer_noun": operational_contract.get("customer_noun"),
                    }
                    _op_gate_identity_score = _score_query_against_doc(
                        str(user_text or ""),
                        _op_gate_identity_doc,
                        _op_gate_doc_key,
                    )
            except Exception:
                _op_gate_identity_score = -1

            # ==========================================================
            # GATE ESTRUTURAL OPERACIONAL
            #
            # IMPORTANTE:
            # Tópico global / PACK fallback / inferência parcial
            # NÃO podem promover modo operacional.
            #
            # Contexto operacional real exige:
            # - hidratação real de docs
            # E
            # - identidade estrutural válida
            #
            # Isso evita:
            # - tutorial operacional global
            # - SCENE indevido
            # - operational_ritual sem contrato
            # - vazamento do PACK_A_AGENDA
            #
            # Sem destruir:
            # - fallback institucional
            # - runtime consultivo
            # - fluidez do GPT 4.0 mini
            # ==========================================================
            _contract_matches_persisted_segment_for_gate = False
            try:
                _gate_contract_segment = str(operational_contract.get("segment") or "").strip()
                _gate_persisted_segment = str(segment_hint or sticky_segment_hint or "").strip()
                if (
                    _gate_contract_segment
                    and _gate_persisted_segment
                    and _normalize_lookup_key(_gate_contract_segment) == _normalize_lookup_key(_gate_persisted_segment)
                ):
                    _contract_matches_persisted_segment_for_gate = True
            except Exception:
                _contract_matches_persisted_segment_for_gate = False

            has_real_operational_context = bool(
                isinstance(operational_contract, dict)
                and bool(operational_contract.get("hydrated_from_docs"))
                and (
                    str(operational_contract.get("segment") or "").strip()
                    or str(operational_contract.get("archetype_id") or "").strip()
                )
                and (
                    _contract_matches_persisted_segment_for_gate
                    or _doc_identity_is_compatible_with_current_text(
                        user_text=user_text,
                        doc=operational_contract,
                        doc_key=str(operational_contract.get("segment") or ""),
                        min_score=2,
                    )
                )
            )
            try:
                logging.info(
                    "[OPERATIONAL_CONTEXT_GATE] hydrated=%s segment=%s archetype=%s doc_key=%s identity_score=%s min_score=2 compatible=%s has_micro_scene_conversational=%s has_micro_scene=%s has_direct_scene=%s has_runtime_short=%s has_operational_reference=%s has_real=%s",
                    bool((operational_contract if isinstance(operational_contract, dict) else {}).get("hydrated_from_docs")),
                    str((operational_contract if isinstance(operational_contract, dict) else {}).get("segment") or ""),
                    str((operational_contract if isinstance(operational_contract, dict) else {}).get("archetype_id") or ""),
                    _op_gate_doc_key,
                    _op_gate_identity_score,
                    bool(_op_gate_identity_score >= 2),
                    bool(str((operational_contract if isinstance(operational_contract, dict) else {}).get("micro_scene_conversational") or "").strip()),
                    bool(str((operational_contract if isinstance(operational_contract, dict) else {}).get("micro_scene") or "").strip()),
                    bool(str((operational_contract if isinstance(operational_contract, dict) else {}).get("direct_scene") or "").strip()),
                    bool(str((operational_contract if isinstance(operational_contract, dict) else {}).get("runtime_short_reply") or "").strip()),
                    bool(str((operational_contract if isinstance(operational_contract, dict) else {}).get("operational_reference") or "").strip()),
                    bool(has_real_operational_context),
                )
            except Exception:
                pass
        except Exception:
            has_real_operational_context = False

        try:
            if isinstance(operational_contract, dict):
                operational_contract["has_practical_scene"] = bool(
                    has_real_operational_context
                    and (
                        str(operational_contract.get("operational_reference") or "").strip()
                        or str(operational_contract.get("direct_scene") or "").strip()
                        or str(operational_contract.get("runtime_short_reply") or "").strip()
                        or str(operational_contract.get("pack_micro_scene") or "").strip()
                        or str(operational_contract.get("micro_scene") or "").strip()
                        or str(operational_contract.get("micro_scene_conversational") or "").strip()
                    )
                )
                try:
                    logging.info(
                        "[PRACTICAL_SCENE_TRACE] stage=after_9133 value=%s has_real=%s has_operational_reference=%s has_direct_scene=%s has_runtime_short=%s has_pack_micro_scene=%s has_micro_scene=%s",
                        bool(operational_contract.get("has_practical_scene")),
                        bool(has_real_operational_context),
                        bool(str(operational_contract.get("operational_reference") or "").strip()),
                        bool(str(operational_contract.get("direct_scene") or "").strip()),
                        bool(str(operational_contract.get("runtime_short_reply") or "").strip()),
                        bool(str(operational_contract.get("pack_micro_scene") or "").strip()),
                        bool(str(operational_contract.get("micro_scene") or "").strip()),
                    )
                except Exception:
                    pass
        except Exception:
            pass

        if not has_real_operational_context:
            operational_contract["has_practical_scene"] = False
            operational_contract["micro_scene_allowed"] = False
            operational_contract["response_mode"] = "DIRECT"

        # =========================================================
        # RUNTIME RESPONSE ORCHESTRATION
        # =========================================================
        # Responsável por:
        # - selecionar material operacional em runtime;
        # - arbitrar DIRECT / DISCOVERY / SCENE / CLOSING;
        # - controlar micro_scene_allowed;
        # - reforçar material tardio do platform_kb;
        # - preparar contrato antes do pipeline final.
        #
        # NÃO deve:
        # - gerar texto final sozinho;
        # - aplicar polish final;
        # - substituir o FINAL PIPELINE.
        # =========================================================

        # Runtime material selection:
        # reforça o melhor material operacional do pack selecionado.
        # Mantém a microcena curta apenas como fallback final.
        try:
            if selected_pack_id:
                _runtime_material = _platform_pack_material(
                    kb_snapshot_obj,
                    platform_segment_profile if isinstance(platform_segment_profile, dict) else {},
                    selected_pack_id,
                )
                _scene = _pick_runtime_scene_material(
                    runtime_material=_runtime_material,
                    has_real_operational_context=has_real_operational_context,
                    response_mode=response_mode,
                )

                if _scene:
                    operational_contract["direct_scene"] = _scene
                    operational_contract["response_mode"] = str(response_mode or "").strip().upper()
                    if has_real_operational_context and _runtime_material.get("runtime_long_text"):
                        operational_contract["runtime_long_text"] = _runtime_material["runtime_long_text"]
                    elif not has_real_operational_context:
                        operational_contract.pop("runtime_long_text", None)

                    if has_real_operational_context and _runtime_material.get("runtime_short_reply"):
                        operational_contract["runtime_short_reply"] = _runtime_material["runtime_short_reply"]
                    elif not has_real_operational_context:
                        if (
                            response_mode == "DIRECT"
                            and hydrated_from_docs
                            and (
                                found_seg
                                or found_sub
                                or found_arch
                                or operational_contract.get("has_practical_scene")
                            )
                            and _runtime_material.get("runtime_short_reply")
                        ):
                            operational_contract["runtime_short_reply"] = _runtime_material["runtime_short_reply"]
                        elif _runtime_material.get("runtime_compact_reply"):
                            operational_contract["runtime_short_reply"] = _runtime_material["runtime_compact_reply"]

                    operational_contract["has_practical_scene"] = bool(has_real_operational_context)
                    try:
                        logging.info(
                            "[PRACTICAL_SCENE_TRACE] stage=after_9208 value=%s has_real=%s has_scene=%s has_pack_micro_scene=%s has_operational_reference=%s",
                            bool(operational_contract.get("has_practical_scene")),
                            bool(has_real_operational_context),
                            bool(str(_scene or "").strip()),
                            bool(str(operational_contract.get("pack_micro_scene") or "").strip()),
                            bool(str(operational_contract.get("operational_reference") or "").strip()),
                        )
                    except Exception:
                        pass
        except Exception:
            pass

        micro_scene_allowed = bool(
            (operational_contract or {}).get("micro_scene_allowed")
        )

        (
            response_mode,
            micro_scene_allowed,
        ) = _apply_current_turn_topic_reset(
            current_turn_topic_reset=current_turn_topic_reset,
            response_mode=response_mode,
            micro_scene_allowed=micro_scene_allowed,
            operational_contract=operational_contract,
        )

        global_pack_scene_ready = False
        try:
            global_pack_scene_ready = bool(
                free_mode
                and has_real_operational_context
                and selected_pack_id
                and (
                    str(operational_reference or "").strip()
                    or str(reference_example or "").strip()
                    or str(micro_scene or "").strip()
                )
                and not segment_for_prompt
                and str(topic or "").strip().upper() in ("AGENDA", "PEDIDOS", "ORCAMENTO", "SERVICOS", "STATUS", "PROCESSO", "PRODUTO")
                and str(confidence or "").strip().lower() in ("high", "medium")
                and str(next_step or "").strip().upper() != "SEND_LINK"
            )
            if isinstance(operational_contract, dict):
                operational_contract["global_pack_fallback"] = global_pack_scene_ready
        except Exception:
            global_pack_scene_ready = False

        if not response_mode:
            response_mode = _infer_response_mode_from_signals(
                topic=topic,
                confidence=confidence,
                needs_clarify=needs_clarify,
                clarify_q=clarify_q,
                next_step=next_step,
                effective_segment=segment_for_prompt,
                kb_anchor_strong=kb_anchor_strong,
                operational_contract=operational_contract,
                question_type=question_type,
            )

        # ---------------------------------------------------------
        # Response mode arbitration:
        # o código pode rebaixar/elevar o modo quando sinais estruturais
        # fortes contradizem o JSON do modelo.
        # ---------------------------------------------------------
        (
            response_mode,
            needs_clarify,
            clarify_q,
        ) = _apply_response_mode_arbitration(
            response_mode=response_mode,
            next_step=next_step,
            global_pack_scene_ready=global_pack_scene_ready,
            question_type=question_type,
            needs_clarify=needs_clarify,
            clarify_q=clarify_q,
            topic=topic,
            operational_contract=operational_contract,
        )

        # ---------------------------------------------------------------
        # Bypass estrutural de DISCOVERY com contrato operacional hidratado
        # ---------------------------------------------------------------
        (
            response_mode,
            needs_clarify,
            clarify_q,
        ) = _apply_discovery_to_scene_bypass(
            response_mode=response_mode,
            next_step=next_step,
            needs_clarify=needs_clarify,
            clarify_q=clarify_q,
            has_real_operational_context=has_real_operational_context,
            operational_contract=operational_contract,
            question_type=question_type,
        )

        try:
            reply_size_policy = _resolve_reply_size_policy(
                ai_turns=ai_turns,
                msg_type=msg_type,
                response_mode=response_mode,
                next_step=next_step,
                topic=(canonical_topic or topic or upstream_topic_hint),
                kb_rich=bool(kb_anchor_available or kb_anchor_strong),
                confidence=confidence,
                needs_clarify=needs_clarify,
                clarify_q=clarify_q,
                effective_segment=effective_segment,
                question_type=question_type,
            )
        except Exception:
            reply_size_policy = _resolve_reply_size_policy(
                ai_turns=ai_turns,
                msg_type=msg_type,
                response_mode=response_mode,
                next_step=next_step,
                topic=(topic or upstream_topic_hint),
                kb_rich=False,
                confidence=confidence,
                needs_clarify=needs_clarify,
                clarify_q=clarify_q,
                effective_segment=effective_segment,
                question_type=question_type,
            )

        # ----------------------------------------------------------
        # GATE SOBERANO DE MICROCENA / KB OPERACIONAL
        # response_mode decide o formato; microcena só existe em SCENE.
        # ----------------------------------------------------------
        micro_scene_allowed = False

        try:
            contract_has_operational_base = bool(
                str((operational_contract or {}).get("operational_reference") or "").strip()
                or str((operational_contract or {}).get("reference_example") or "").strip()
                or list((operational_contract or {}).get("operational_ritual") or [])
            )
            contract_hydrated_scene_ready = bool(
                str((operational_contract or {}).get("response_mode") or "").strip().upper() == "SCENE"
                and bool((operational_contract or {}).get("hydrated_from_docs"))
                and contract_has_operational_base
            )

            try:
                logging.info(
                    "[SCENE_CONTRACT_TRACE] response_mode=%s has_real=%s practical=%s hydrated=%s contract_base=%s kb_anchor=%s global_pack=%s segment=%s",
                    str(response_mode or "").strip().upper(),
                    bool(has_real_operational_context),
                    bool((operational_contract or {}).get("has_practical_scene")),
                    bool((operational_contract or {}).get("hydrated_from_docs")),
                    bool(contract_has_operational_base),
                    bool(kb_anchor_strong),
                    bool(global_pack_scene_ready),
                    str(segment_for_prompt or "").strip(),
                )
            except Exception:
                pass

            if (
                response_mode == "SCENE"
                and (
                    (
                        segment_for_prompt
                        and kb_anchor_strong
                    )
                    or global_pack_scene_ready
                    or contract_hydrated_scene_ready
                )
                and contract_has_operational_base
            ):
                micro_scene_allowed = True

            if response_mode in ("DIRECT", "DISCOVERY", "CLOSING"):
                micro_scene_allowed = False

        except Exception:
            micro_scene_allowed = False

        try:
            if isinstance(operational_contract, dict):
                operational_contract["micro_scene_allowed"] = micro_scene_allowed
                operational_contract["response_mode"] = response_mode
            if isinstance(base_operational_contract, dict):
                base_operational_contract["micro_scene_allowed"] = micro_scene_allowed
                base_operational_contract["response_mode"] = response_mode
        except Exception:
            pass

        try:
            if isinstance(operational_contract, dict):
                operational_contract["user_context"] = str(user_text or "").strip()
        except Exception:
            pass

        has_structured_scene = (
            (operational_contract or {}).get("direct_scene")
            or (operational_contract or {}).get("runtime_long_text")
            or (operational_contract or {}).get("runtime_short_reply")
            or (operational_contract or {}).get("pack_micro_scene")
            or (operational_contract or {}).get("reference_example")
            or (operational_contract or {}).get("operational_reference")
        )

        # ==========================================================
        # Wrapper humano:
        # agora também permitido para fallback DIRECT compacto.
        #
        # IMPORTANTE:
        # NÃO reabre SCENE procedural.
        # Apenas reutiliza a camada humana já existente.
        # ==========================================================
        _is_broad_question = str(question_type or "").strip().lower() not in ("punctual", "continuity", "simulation")

        use_direct_scene = bool(
            has_structured_scene
            and (
                (
                    has_real_operational_context
                    and response_mode == "SCENE"
                    and (operational_contract or {}).get("micro_scene_allowed")
                )
                or
                (
                    not has_real_operational_context
                    and bool((operational_contract or {}).get("global_pack_fallback"))
                    and bool(
                        (operational_contract or {}).get("runtime_compact_reply")
                        or (operational_contract or {}).get("runtime_short_reply")
                    )
                    and _is_broad_question
                )
            )
        )

        allow_scene_runtime = bool(
            has_real_operational_context
            and response_mode == "SCENE"
            and micro_scene_allowed
        )

        if not isinstance(operational_contract, dict) or not operational_contract:
            operational_contract = base_operational_contract if 'base_operational_contract' in locals() else {}

        # ---------------------------------------------------------
        # Late KB reinforcement:
        # antes do retorno direto, garante que o contrato use
        # o melhor material já cadastrado no platform_kb, em vez da microcena curta.
        # Não cria conteúdo, não detecta profissão por palavra local e não mexe em prompt.
        try:
            if (
                platform_kb_mode
                and not current_turn_topic_reset
                and isinstance(operational_contract, dict)
                and selected_pack_id
                and str(next_step or "").strip().upper() != "SEND_LINK"
            ):
                _late_material = _platform_pack_material(
                    kb_snapshot_obj,
                    platform_segment_profile if isinstance(platform_segment_profile, dict) else {},
                    selected_pack_id,
                )

                _late_direct_scene = str(_late_material.get("direct_scene") or "").strip()
                _late_runtime_long = str(_late_material.get("runtime_long_text") or "").strip()
                _late_runtime_short = str(_late_material.get("runtime_short_reply") or "").strip()
                _late_micro_scene = str(_late_material.get("micro_scene") or "").strip()
                _late_reference = str(_late_material.get("reference_example") or "").strip()
                _late_material_source = str(_late_material.get("material_source") or "").strip()

                _late_compact = str(_late_material.get("runtime_compact_reply") or "").strip()

                if has_real_operational_context:
                    _best_scene = (
                        _late_direct_scene
                        or _late_runtime_long
                        or _late_runtime_short
                        or _late_micro_scene
                    )
                else:
                    if response_mode == "DIRECT":
                        _best_scene = (
                            _late_runtime_long
                            or _late_runtime_short
                            or _late_direct_scene
                            or _late_compact
                        )
                    else:
                        _best_scene = _late_compact

                if _best_scene:
                    operational_contract["selected_pack_id"] = selected_pack_id
                    operational_contract["hydrated_from_platform_kb"] = True
                    operational_contract["global_pack_fallback"] = True
                    if has_real_operational_context:
                        operational_contract["direct_scene"] = _best_scene
                        operational_contract["operational_reference"] = _best_scene
                    else:
                        operational_contract.pop("direct_scene", None)
                        operational_contract.pop("operational_reference", None)
                        operational_contract.pop("pack_micro_scene", None)
                        operational_contract.pop("runtime_long_text", None)
                        # Mantém limpeza do proceduralismo pesado
                        operational_contract.pop("operational_ritual", None)

                        # ==========================================================
                        # Mantém núcleo compacto humanizável.
                        # NÃO destrói runtime curto leve.
                        # ==========================================================
                        if operational_contract.get("runtime_short_reply"):
                            operational_contract["runtime_compact_reply"] = (
                                operational_contract.get("runtime_compact_reply")
                                or operational_contract.get("runtime_short_reply")
                            )

                        operational_contract["runtime_short_reply"] = _best_scene
                        operational_contract["has_practical_scene"] = False
                        operational_contract["micro_scene_allowed"] = False
                        operational_contract["response_mode"] = "DIRECT"
                    if _late_material_source:
                        operational_contract["material_source"] = _late_material_source
                    operational_contract["has_practical_scene"] = bool(
                        has_real_operational_context
                        and (
                            _late_direct_scene
                            or _late_runtime_short
                            or _late_micro_scene
                            or _best_scene
                        )
                    )

                    if platform_segment_key:
                        operational_contract["platform_segment_key"] = platform_segment_key
                    if has_real_operational_context and _late_runtime_long:
                        operational_contract["runtime_long_text"] = _late_runtime_long
                    if has_real_operational_context and _late_runtime_short:
                        operational_contract["runtime_short_reply"] = _late_runtime_short
                    if has_real_operational_context and _late_reference:
                        operational_contract["reference_example"] = _late_reference
                        operational_contract["has_reference_example"] = True

                    try:
                        logging.info(
                            "[SCENE_GATE_TRACE] question_type=%s has_real=%s response_mode_before=%s practical=%s hydrated=%s segment=%s",
                            str(question_type or "").strip().lower(),
                            bool(has_real_operational_context),
                            str(response_mode or "").strip().upper(),
                            bool(operational_contract.get("has_practical_scene")),
                            bool(operational_contract.get("hydrated_from_docs")),
                            str(operational_contract.get("segment") or "").strip(),
                        )
                    except Exception:
                        pass

                    if has_real_operational_context and str(question_type or "").strip().lower() not in ("punctual", "continuity", "simulation"):
                        response_mode = "SCENE"
                        micro_scene_allowed = True
                        operational_contract["micro_scene_allowed"] = True
                        operational_contract["response_mode"] = "SCENE"
                    else:
                        if response_mode == "SCENE":
                            response_mode = "DIRECT"
                        micro_scene_allowed = False
                        operational_contract["micro_scene_allowed"] = False
                        operational_contract["response_mode"] = "DIRECT"
        except Exception:
            pass

        # ----------------------------------------------------------
        # GUARDA DO JSON_FAIL_SAFE
        #
        # Quando o modelo quebra o JSON, a resposta textual livre pode vir
        # humanizada, mas resumir o núcleo operacional do KB.
        #
        # Neste caso, sem mexer em prompt e sem inferir segmento por texto,
        # usamos o material operacional já resolvido no contrato como base
        # factual e reaplicamos a camada existente de humanização.
        # ----------------------------------------------------------
        try:
            if (
                bool(json_fail_safe_used)
                and free_mode
                and platform_kb_mode
                and str(response_mode or "").strip().upper() == "DIRECT"
                and str(next_step or "").strip().upper() != "SEND_LINK"
                and isinstance(operational_contract, dict)
            ):
                _safe_core = (
                    str(operational_contract.get("direct_scene") or "").strip()
                    or str(operational_contract.get("runtime_long_text") or "").strip()
                    or str(operational_contract.get("runtime_short_reply") or "").strip()
                    or str(operational_contract.get("runtime_compact_reply") or "").strip()
                    or str(operational_contract.get("operational_reference") or "").strip()
                )

                if _safe_core:
                    _safe_lead_name = _front_sanitize_lead_name_candidate(
                        _front_sanitize_lead_name_candidate(
                inferred_lead_name or name_hint,
                segment_refs=[
                    segment_hint,
                    inferred_lead_segment_raw,
                    inferred_lead_segment,
                ],
            ) or "",
                        segment_refs=[
                            inferred_lead_segment_raw,
                            inferred_lead_segment,
                            segment_hint,
                            operational_contract.get("segment"),
                            operational_contract.get("platform_segment_key"),
                        ],
                    )

                    _safe_segment_raw = str(
                        inferred_lead_segment_raw
                        or inferred_lead_segment
                        or segment_hint
                        or operational_contract.get("segment")
                        or operational_contract.get("platform_segment_key")
                        or ""
                    ).strip()

                    _safe_reply = _humanize_reply_with_lead_context(
                        reply=_safe_core,
                        lead_name=_safe_lead_name if has_name else "",
                        lead_segment_raw=_safe_segment_raw,
                    )

                    _safe_reply = _sanitize_user_facing_reply(
                        str(_safe_reply or "").strip()
                    )

                    if _safe_reply:
                        reply_text = _safe_reply
                        spoken_text = _safe_reply
                        reply_source = "front_json_fail_safe_kb_core"
        except Exception:
            pass

        # 🔒 GARANTIA DE CONTRATO MÍNIMO (sem frase pronta de venda)
        try:
            _has_operational = bool(
                str(operational_contract.get("operational_reference") or "").strip()
                or list(operational_contract.get("operational_ritual") or [])
            )

            if not _has_operational:
                operational_contract["global_pack_fallback"] = bool(platform_kb_mode)
            elif (
                platform_kb_mode
                and isinstance(operational_contract, dict)
                and not bool(operational_contract.get("hydrated_from_docs"))
            ):
                operational_contract["global_pack_fallback"] = True
                operational_contract["has_practical_scene"] = False
                operational_contract["micro_scene_allowed"] = False
        except Exception:
            pass

        try:
            if (
                isinstance(operational_contract, dict)
                and isinstance(base_operational_contract, dict)
                and not str(operational_contract.get("operational_reference") or "").strip()
                and not list(operational_contract.get("operational_ritual") or [])
            ):
                base_ritual = [
                    str(x).strip()
                    for x in (base_operational_contract.get("operational_ritual") or [])
                    if str(x).strip()
                ]
                if base_ritual:
                    operational_contract["operational_ritual"] = base_ritual[:5]
        except Exception:
            pass


        # Guard semântico:
        # se o modelo escolheu cedo demais um trilho estreito sem ancoragem real,
        # rebaixa para ambiguidade útil e permite UMA pergunta.
        if (
            (not kb_anchor_strong)
            and confidence == "low"
            and _should_downgrade_premature_narrow_topic(
            topic=topic,
            confidence=confidence,
            ai_turns=ai_turns,
                        effective_segment=segment_for_prompt,
            operational_family=operational_family,
            operational_reference="",
            reference_example=reference_example,
            reply_text=reply_text,
            next_step=next_step,
        )):
            topic = "OTHER"
            confidence = "medium"
            needs_clarify = "yes"
            next_step = "NONE"
            if not clarify_q:
                clarify_q = str(question or "").strip()

        # ----------------------------------------------------------
        # ✅ ARQUITETURA: aplica prioridade TRIAL (policy gate)
        # Se o KB marcou TRIAL, o front NÃO deixa o LLM cair em PREÇO.
        # ----------------------------------------------------------
        if force_trial:
            intent = "TRIAL"
            topic = "TRIAL"
            response_mode = "DIRECT"
            # Nunca fechar/mandar link em TRIAL
            next_step = "NONE"
            should_end = False
            # Evita linguagem que soa como "trial disfarçado"
            try:
                for bad in ("experimentar", "teste", "testar", "trial"):
                    if bad in (reply_text or "").lower():
                        # não apaga a frase "não oferece teste grátis"; só remove "experimentar/testar planos"
                        reply_text = re.sub(r"\b(experimentar|testar)\b[^\.\!\?]{0,80}", "", reply_text, flags=re.I).strip()
                        spoken_text = re.sub(r"\b(experimentar|testar)\b[^\.\!\?]{0,80}", "", spoken_text, flags=re.I).strip()
                        break
            except Exception:
                pass

        # name_use: só 4 valores no contrato
        name_use = str(data.get("nameUse") or "none").strip().lower()
        if name_use not in ("none", "greet", "empathy", "clarify"):
            name_use = "none"

        # ----------------------------------------------------------
        # PREÇO CANÔNICO DA PLATAFORMA
        # Sem keyword matching local:
        # usa apenas o topic já decidido pela IA.
        # ----------------------------------------------------------
        try:
            price_context_active = any([
                str(topic or "").strip().upper() == "PRECO",
                str(last_intent or "").strip().upper() == "PRECO",
                str((kb_context or {}).get("intent_hint") or "").strip().upper() == "PRECO",
            ])
            if price_context_active:
                needs_price_repair = (
                    (not str(reply_text or "").strip())
                    or ("r$" not in str(reply_text or "").lower())
                )
                if needs_price_repair:
                    repaired_price_reply = _front_repair_price_reply(
                        reply_text=reply_text,
                        name_hint=name_hint,
                    )
                    if str(repaired_price_reply or "").strip():
                        reply_text = repaired_price_reply
                        if not spoken_text:
                            spoken_text = repaired_price_reply
                        reply_source = "front_platform_pricing"
                        confidence = "high"
        except Exception:
            pass

        # Se for decider-only, seguimos para fail-safe.
        # Nos primeiros turnos (free_mode), a prioridade é a IA falar com texto próprio.
        decider_only = False
        decider = None
        reply_source = "front"
        if (not free_mode) and next_step != "SEND_LINK":
            decider_only = True
            decider = {
                "response_mode": response_mode,
                "intent": intent,
                "confidence": confidence,
                "needsClarify": needs_clarify,
                "clarifyQuestion": clarify_q,
                "packProfile": pack_profile,
                "renderMode": render_mode,
                "segmentKey": segment_key,
                "segmentConfidence": segment_conf,
                "shouldAskSegment": should_ask_segment,
            }
            # NOTE: fora do free_mode ainda pode seguir para render/Fail-safe.
            # ---------------------------------------------------------
            # LIMITE SEGURO DA MONTAGEM DETERMINÍSTICA NO FREE_MODE
            # ---------------------------------------------------------
            # Para respostas técnicas de texto, queremos manter robustez
            # comercial/operacional (~700–800 chars úteis).
            # Para áudio, mantemos menor para evitar TTS longo.
            # ---------------------------------------------------------
            try:
                if str(reply_source or "").strip() == "front_structured_python_assembly":
                    _structured_policy = dict(reply_size_policy or {})
                    _is_audio_policy = bool(_structured_policy.get("is_audio"))

                    if _is_audio_policy:
                        _structured_policy["max_chars"] = min(
                            int(_structured_policy.get("max_chars") or 520),
                            520,
                        )
                        _structured_policy["target_chars"] = min(
                            int(_structured_policy.get("target_chars") or 430),
                            430,
                        )
                    else:
                        _structured_policy["max_chars"] = min(
                            int(_structured_policy.get("max_chars") or 800),
                            800,
                        )
                        _structured_policy["target_chars"] = min(
                            int(_structured_policy.get("target_chars") or 740),
                            740,
                        )

                    reply_text = _apply_reply_size_policy(reply_text, _structured_policy)
                    spoken_text = _apply_reply_size_policy(
                        spoken_text or reply_text,
                        _structured_policy,
                    )
                    reply_size_policy = _structured_policy
            except Exception:
                pass

            out = {
                "response_mode": response_mode,
                "replyText": "",
                "spokenText": "",
                "understanding": {
                    "topic": topic,
                    "intent": intent,
                    "response_mode": response_mode,
                    "confidence": confidence,
                    "question_type": question_type,
                    "needsClarify": needs_clarify,
                    "clarifyQuestion": clarify_q,
                    "packProfile": pack_profile,
                    "renderMode": render_mode,
                    "segmentKey": segment_key,
                    "segmentConfidence": segment_conf,
                    "shouldAskSegment": should_ask_segment,
                },
                "decider": decider,
                "nextStep": "NONE",
                "shouldEnd": False,
                "nameUse": ("clarify" if needs_clarify == "yes" or should_ask_segment == "yes" else "none"),
                "prefersText": False,
                "replySource": "front_decider",
                "kbSnapshotSizeChars": len(kb_snapshot or ""),
                "tokenUsage": token_usage or {},
            }
            reply_source = "front_decider"

        # IMPORTANTE:
        # daqui para frente usamos a confidence já recalibrada pela heurística local.
        if confidence not in ("high", "medium", "low"):
            confidence = "low"

        segment_discovery_resolved = bool(
            has_segment_context
            or str(segment_for_prompt or "").strip()
            or (
                str(segment_key or "").strip()
                and segment_conf in ("high", "medium")
                and should_ask_segment != "yes"
            )
        )

        discovery_resolved = bool(has_name and segment_discovery_resolved)

        if discovery_resolved:
            needs_clarify = "no"
            clarify_q = ""
            should_ask_segment = "no"

            if response_mode == "DISCOVERY":
                response_mode = "DIRECT"
                try:
                    if isinstance(operational_contract, dict):
                        operational_contract["response_mode"] = response_mode
                    if isinstance(base_operational_contract, dict):
                        base_operational_contract["response_mode"] = response_mode
                except Exception:
                    pass

        
        # ----------------------------------------------------------
        # ✅ "TOM DO LINK": o link é uma AÇÃO (fechar) — não uma palavra.
        # Regras:
        # 1) Nunca mandar link em pergunta de "grátis/trial".
        # 2) Pode mandar link se o usuário pedir explicitamente.
        # 3) Pode mandar link se o LLM decidiu SEND_LINK com confiança alta
        #    e o lead já está claramente pronto (ex.: depois de 2+ turnos), mesmo sem dizer "link".
        # ----------------------------------------------------------
        is_trial = bool(force_trial)

        if is_trial and next_step == "SEND_LINK":
            next_step = "NONE"

        # IA Soberana: Se a IA decidiu SEND_LINK com confiança alta, liberamos mesmo no turno 0.
        allow_send_link = (
            next_step == "SEND_LINK"
            and (not is_trial)
            and confidence == "high"
            and needs_clarify != "yes"
        )

        if allow_send_link:
            response_mode = "CLOSING"
            base = str((kb_context or {}).get("signup_url") or "").strip()
            if not base:
                base = (os.getenv("FRONTEND_BASE") or "https://www.meirobo.com.br").strip()

            # Preserva o texto gerado pela IA e apenas injeta o link se faltar
            reply_text = str(reply_text or "").strip()
            if base not in reply_text:
                if reply_text:
                    qpos = reply_text.find("?")
                    if qpos != -1:
                        reply_text = (reply_text[: qpos]).rstrip()
                    if not reply_text.endswith((".", "!", ":")):
                        reply_text += "."
                    reply_text = f"{reply_text}\n{base}"
                else:
                    reply_text = base

            spoken_text = reply_text

            needs_clarify = "no"
            confidence = "high"
            intent = "SIGNUP_LINK"
            next_step = "SEND_LINK"

        elif next_step == "SEND_LINK" and not allow_send_link:
            # Bloqueia SEND_LINK automático quando não houve pedido explícito / sinais fortes
            next_step = "NONE"
            if response_mode == "CLOSING":
                response_mode = "DIRECT"
            should_end = False



        # ----------------------------------------------------------
        # GARANTIA DE DISCOVERY ANTES DE QUALQUER DIRECT RETURN
        # Mantém a cena direta, mas não deixa o turno 0 sair sem nome.
        # ----------------------------------------------------------
        try:
            identity_discovery_required = bool(
                ai_turns == 0
                and is_lead
                and not has_name
                and not discovery_resolved
                and str(next_step or "").strip().upper() != "SEND_LINK"
            )

            if identity_discovery_required:
                try:
                    logging.info(
                        "[IDENTITY_DISCOVERY_REQUIRED] ai_turns=%s has_name=%s discovery_resolved=%s response_mode_before=%s hydrated=%s practical=%s segment=%s",
                        ai_turns,
                        has_name,
                        discovery_resolved,
                        str(response_mode or "").strip().upper(),
                        bool((operational_contract or {}).get("hydrated_from_docs")),
                        bool((operational_contract or {}).get("has_practical_scene")),
                        str(
                            effective_segment
                            or segment_for_prompt
                            or segment_hint
                            or ""
                        ).strip(),
                    )
                except Exception:
                    pass

                # Preserva SCENE real/hidratado.
                # A descoberta de identidade deve ser anexada ao final,
                # não substituir a cena prática já qualificada.
                if (
                    str(response_mode or "").strip().upper() == "SCENE"
                    and isinstance(operational_contract, dict)
                    and bool(operational_contract.get("hydrated_from_docs"))
                    and bool(operational_contract.get("has_practical_scene"))
                ):
                    needs_clarify = "yes"
                    name_use = "clarify"
                    try:
                        operational_contract["identity_discovery_required"] = True
                    except Exception:
                        pass
                else:
                    response_mode = "DISCOVERY"
                    needs_clarify = "yes"
                    name_use = "clarify"

                if isinstance(kb_context, dict):
                    kb_context["needs_name_discovery"] = True
        except Exception:
            identity_discovery_required = False

        if use_direct_scene:
            use_human_wrapper = bool(
                response_mode == "DIRECT"
                and (operational_contract or {}).get("global_pack_fallback")
                and not (operational_contract or {}).get("hydrated_from_docs")
            )

            direct_text = _build_direct_scene_payload(
                contract=operational_contract,
                user_text=user_text,
                segment_hint=(
                    operational_contract.get("platform_segment_key")
                    or segment_hint
                    or ""
                ),
                name_hint=name_hint,
                state_summary=state_summary,
                intro_hint=reply_text,
                use_human_wrapper=use_human_wrapper,
            )

            if direct_text:
                direct_spoken = direct_text
                try:
                    direct_text, direct_spoken, _identity_name_use = _ensure_discovery_identity_request(
                        reply_text=direct_text,
                        spoken_text=direct_spoken,
                        has_name=has_name,
                        effective_segment=effective_segment or segment_for_prompt,
                        response_mode=response_mode,
                        identity_question=clarify_q or question,
                    )
                    if _identity_name_use == "clarify":
                        name_use = "clarify"
                        needs_clarify = "yes"
                except Exception:
                    direct_spoken = direct_text

                # Para SCENE com contrato segmentado hidratado, o direct_scene
                # não deve encerrar o fluxo cedo. Ele serve como candidato
                # inicial, mas a resposta ainda precisa passar pelas camadas
                # de validação/enriquecimento operacional.
                try:
                    _continue_after_direct_scene = bool(
                        str(response_mode or "").strip().upper() == "SCENE"
                        and isinstance(operational_contract, dict)
                        and bool(operational_contract.get("hydrated_from_docs"))
                    )
                except Exception:
                    _continue_after_direct_scene = False

                if _continue_after_direct_scene:
                    reply_text = direct_text
                    spoken_text = direct_spoken
                    reply_source = "front_direct_scene"
                else:
                    return {
                        "response_mode": response_mode,
                        "replyText": direct_text,
                        "spokenText": direct_spoken,
                        "understanding": {
                            "topic": topic,
                            "intent": intent,
                            "response_mode": response_mode,
                            "confidence": confidence,
                            "question_type": question_type,
                            "needsClarify": needs_clarify,
                            "clarifyQuestion": clarify_q,
                            "packProfile": pack_profile,
                            "renderMode": render_mode,
                            "segmentKey": segment_key,
                            "segmentConfidence": segment_conf,
                            "shouldAskSegment": should_ask_segment,
                            "leadSegmentRaw": inferred_lead_segment_raw,
                        },
                        "nextStep": next_step,
                        "leadName": (
                            _front_sanitize_lead_name_candidate(
                                name_hint,
                                segment_refs=[
                                    segment_hint,
                                    inferred_lead_segment_raw,
                                    inferred_lead_segment,
                                ],
                            )
                            if has_name else ""
                        ),
                        "segmentHint": segment_hint,
                        "leadSegmentRaw": inferred_lead_segment_raw,
                        "shouldEnd": should_end,
                        "nameUse": name_use,
                        "prefersText": False,
                        "replySource": "front_direct_scene",
                        "kbSnapshotSizeChars": len(kb_snapshot or ""),
                        "tokenUsage": token_usage if isinstance(token_usage, dict) else {},
                        "operationalContract": operational_contract if isinstance(operational_contract, dict) else {},
                    }

        # ----------------------------------------------------------
        # FREE MODE: nos primeiros turnos do lead, a IA responde direto.
        # Preserva fast-path de link e guardrails leves, mas pula pack_engine
        # e remontagens rígidas de microcena/template.
        # ----------------------------------------------------------
        if free_mode and next_step != "SEND_LINK":
            if _needs_discovery_question(
                topic,
                confidence,
                operational_family,
                ai_turns,
                effective_segment=effective_segment,
                needs_clarify=needs_clarify,
                clarify_q=clarify_q,
                operational_reference="",
                reference_example=reference_example,
                reply_text=reply_text,
            ):
                discovery_q = ""
                try:
                    discovery_q = str((kb_context or {}).get("discovery_question_hint", "") or "").strip()
                except Exception:
                    discovery_q = ""

                if not discovery_q:
                    try:
                        # só cria discovery se realmente não houver trilho operacional suficiente
                        has_anchor = bool(operational_reference or reference_example or operational_family)
                        if not has_anchor:
                            discovery_q = str(clarify_q or "").strip()
                    except Exception:
                        pass

                return {
                    "response_mode": "DISCOVERY",
                    "replyText": discovery_q,
                    "spokenText": discovery_q,
                    "understanding": {
                        "topic": "OTHER",
                        "intent": "DISCOVERY",
                        "confidence": confidence,
                        "question_type": question_type,
                    },
                    "nextStep": "DISCOVERY",
                    "shouldEnd": False,
                    "nameUse": "clarify",
                    "prefersText": False,
                    "replySource": "front_discovery",
                    "kbSnapshotSizeChars": len(kb_snapshot or ""),
                    "tokenUsage": token_usage if isinstance(token_usage, dict) else {},
                }

            generated = ""
            if (
                response_mode == "SCENE"
                and next_step != "SEND_LINK"
                and bool((operational_contract if 'operational_contract' in locals() else {}).get("micro_scene_allowed"))
            ):
                generated = _generate_micro_scene_with_model(
                    operational_reference=operational_reference,
                    contract=operational_contract if 'operational_contract' in locals() else {},
                ).strip()

            if generated:
                generated_live = _is_live_operational_reply(
                    text=generated,
                    operational_reference="",
                    reference_example=reference_example,
                    contract=operational_contract if 'operational_contract' in locals() else {},
                )

                generated_show = _is_show_micro_scene(
                    text=generated,
                    operational_reference="",
                    reference_example=reference_example,
                    contract=operational_contract if 'operational_contract' in locals() else {},
                )

                # ============================================================
                # SEGUNDA CAMADA REMOVIDA
                # Mantém a resposta gerada sem rewrite final.
                # ============================================================
                if generated:
                    upgraded = ""
                    upgraded_live = False
                    upgraded_show = False

                    _upgrade_contract_strong = bool(
                        ((operational_contract if 'operational_contract' in locals() else {}) or {}).get("hydrated_from_docs")
                        and str(reference_example or "").strip()
                        and str((((operational_contract if 'operational_contract' in locals() else {}) or {}).get("operational_reference") or "")).strip()
                    )

                    if upgraded and len(str(upgraded).strip()) > 40:
                        if _upgrade_contract_strong:
                            # Contrato forte: preservar a primeira microcena boa.
                            # Upgrade só entra se elevar de fato (SHOW quando antes não era).
                            keep_upgraded = bool(
                                upgraded_show and not generated_show
                            )
                        else:
                            # Sem contrato forte: ainda permitimos upgrade,
                            # mas removemos completamente o incentivo por tamanho.
                            keep_upgraded = bool(
                                (upgraded_show and not generated_show)
                                or (upgraded_live and not generated_live)
                            )

                        if keep_upgraded:
                            generated = upgraded
                            generated_live = upgraded_live
                            generated_show = upgraded_show

                structured = ""
                structured_live = False
                structured_show = False

                # fallback estrutural só entra se a IA principal falhar de verdade
                if allow_scene_runtime and (not generated or len(str(generated).strip()) < 40):
                    structured = _compose_grounded_scene_with_progression(
                        operational_reference="",
                        contract=operational_contract if 'operational_contract' in locals() else {},
                        reference_example=reference_example,
                    )

                    if not structured:
                        structured = _build_structural_last_resort_reply(
                            operational_reference="",
                            contract=operational_contract if 'operational_contract' in locals() else {},
                        )

                    if structured:
                        structured_live = _is_live_operational_reply(
                            text=structured,
                            operational_reference="",
                            reference_example=reference_example,
                            contract=operational_contract if 'operational_contract' in locals() else {},
                        )
                        structured_show = _is_show_micro_scene(
                            text=structured,
                            operational_reference="",
                            reference_example=reference_example,
                            contract=operational_contract if 'operational_contract' in locals() else {},
                        )

                # ==========================================================
                # Gate estrutural do worker operacional
                #
                # IMPORTANTE:
                # O payload institucional/global continua existindo
                # como contexto consultivo para o GPT.
                #
                # Porém o worker operacional NÃO pode ser promovido
                # sem autorização estrutural do contrato.
                #
                # Isso evita:
                # - tutorial operacional global
                # - fluxo procedural indevido
                # - vazamento do PACK fallback
                #
                # Sem destruir:
                # - runtime_short_reply
                # - operational_reference
                # - bridge_line
                # - fallback institucional
                # ==========================================================
                operational_upgrade_allowed = bool(
                    (
                        operational_contract.get("has_practical_scene")
                        if isinstance(operational_contract, dict)
                        else False
                    )
                    and (
                        operational_contract.get("hydrated_from_docs")
                        if isinstance(operational_contract, dict)
                        else False
                    )
                )

                if generated_show and operational_upgrade_allowed:
                    reply_text = generated
                    spoken_text = generated
                    reply_source = "front_ia_soberana"
                elif generated and operational_upgrade_allowed:
                    reply_text = generated
                    spoken_text = generated
                    reply_source = "front_operational_upgrade"
                elif allow_scene_runtime and structured_show:
                    reply_text = structured
                    spoken_text = structured
                    reply_source = "front_fallback_structural"
                elif allow_scene_runtime and structured_live and not _contract_strong:
                    reply_text = structured
                    spoken_text = structured
                    reply_source = "front_fallback_structural"
                elif allow_scene_runtime and structured_live and _contract_strong:
                    forced_scene = (
                        _compose_grounded_scene_with_progression(
                            operational_reference="",
                            contract=operational_contract if 'operational_contract' in locals() else {},
                            reference_example=reference_example,
                        ).strip()
                        or _build_structural_last_resort_reply(
                            operational_reference="",
                            contract=operational_contract if 'operational_contract' in locals() else {},
                        ).strip()
                    )
                    if forced_scene:
                        reply_text = forced_scene
                        spoken_text = forced_scene
                        reply_source = "front_fallback_structural"
                    else:
                        reply_text = structured
                        spoken_text = structured
                        reply_source = "front_fallback_structural"

                elif (
                    response_mode == "DIRECT"
                    and str(reply_text or "").strip()
                    and len(str(reply_text or "").strip()) >= 40
                ):
                    # DIRECT consultivo:
                    # preserva a resposta soberana já gerada pela IA
                    # e impede queda no empty fallback do free_mode.
                    spoken_text = str(reply_text or "").strip()

                    if not str(reply_source or "").strip():
                        reply_source = "front_ia_soberana"

                else:
                    reply_text = str(question or clarify_q or "").strip()
                    spoken_text = reply_text
                    reply_source = "front_free_mode_empty"

            allow_kb_runtime_fallback = bool(
                allow_scene_runtime
                and response_mode == "SCENE"
                and kb_anchor_strong
                and bool((operational_contract if 'operational_contract' in locals() else {}).get("micro_scene_allowed"))
            )

            kb_reply = ""
            if allow_kb_runtime_fallback:
                kb_reply = _build_kb_anchor_reply(
                    operational_reference="",
                    reference_example=reference_example,
                    clarify_q=(question if not effective_segment else ""),
                    contract=operational_contract if 'operational_contract' in locals() else (base_operational_contract if 'base_operational_contract' in locals() else {}),
                )

            if allow_kb_runtime_fallback and kb_reply:
                try:
                    rescue_needed = (
                        (not str(reply_text or "").strip())
                        or _looks_like_technical_output(reply_text)
                    )
                    if rescue_needed:
                        reply_text = kb_show_reply_seed or kb_reply
                    if _looks_like_technical_output(spoken_text) or not str(spoken_text or "").strip():
                        spoken_text = kb_show_reply_seed or kb_reply
                    if rescue_needed:
                        reply_source = "front_free_mode_fallback"
                        should_end = False
                        if next_step != "SEND_LINK":
                            next_step = "NONE"
                except Exception:
                    pass
            elif not reply_text:
                reply_text = kb_reply
                if not reply_text and question and not effective_segment:
                    reply_text = question
                if not spoken_text:
                    spoken_text = reply_text
                reply_source = "front_free_mode_fallback"

            try:
                operational_reply = bool(
                    str(topic or "").upper() in ("PEDIDOS", "SERVICOS", "PROCESSO", "STATUS", "AGENDA")
                    and "na prática:" in str(reply_text or "").lower()
                )
            except Exception:
                operational_reply = False

            if operational_reply and next_step != "SEND_LINK":
                should_end = False

            reply_text = _apply_reply_size_policy(reply_text, reply_size_policy)
            spoken_text = _apply_reply_size_policy((spoken_text or reply_text or ""), reply_size_policy)

            try:
                _reply_before_sanitize = str(reply_text or "").strip()
                _spoken_before_sanitize = str(spoken_text or "").strip()
                _kb_obj = _try_parse_kb_json(kb_snapshot)
                reply_text = _sanitize_unverified_time_claims(reply_text, _kb_obj, kb_snapshot)
                spoken_text = _sanitize_unverified_time_claims(spoken_text, _kb_obj, kb_snapshot)

                # Nunca deixar o saneamento burocrático matar a resposta de vitrine.
                if _looks_like_bureaucratic_stub(reply_text):
                    kb_fallback = ""
                    if allow_kb_runtime_fallback:
                        kb_fallback = _build_kb_anchor_reply(
                            operational_reference="",
                            reference_example=reference_example,
                            clarify_q=(question if not effective_segment else ""),
                            contract=operational_contract if 'operational_contract' in locals() else (base_operational_contract if 'base_operational_contract' in locals() else {}),
                        )
                    reply_text = (
                        kb_fallback
                        or _reply_before_sanitize
                        or question
                        or "Hoje no WhatsApp, o que você precisa responder ou organizar manualmente para os clientes?"
                    )
                if _looks_like_bureaucratic_stub(spoken_text):
                    kb_fallback = ""
                    if allow_kb_runtime_fallback:
                        kb_fallback = _build_kb_anchor_reply(
                            operational_reference="",
                            reference_example=reference_example,
                            clarify_q=(question if not effective_segment else ""),
                            contract=operational_contract if 'operational_contract' in locals() else (base_operational_contract if 'base_operational_contract' in locals() else {}),
                        )
                    spoken_text = (
                        kb_fallback
                        or _spoken_before_sanitize
                        or reply_text
                    )
            except Exception:
                pass

            try:
                reply_text = _de_genericize_free_mode_text(reply_text)
                spoken_text = _de_genericize_free_mode_text(spoken_text)
            except Exception:
                pass

            reply_text = str(reply_text or "").strip()

            ia_locked = False
            try:
                if (
                    str(reply_source or "").strip() == "front_ia_soberana"
                    and (ia_accepted or _is_show_micro_scene(
                        text=reply_text,
                        operational_reference="",
                        reference_example=reference_example,
                        contract=operational_contract if 'operational_contract' in locals() else {},
                    ))
                ):
                    ia_locked = True
            except Exception:
                ia_locked = False

            if not ia_locked:
                try:
                    grounded_scene = str(operational_reference or "").strip()
                    grounded_ritual = [
                        str(x).strip()
                        for x in ((operational_contract if 'operational_contract' in locals() else {}) or {}).get("operational_ritual", [])
                        if str(x).strip()
                    ]

                    # não reconstruir estruturalmente quando já existe resposta
                    reply_text = str(reply_text or "").strip()
                    spoken_text = str(spoken_text or reply_text).strip()
                except Exception:
                    pass

                try:
                    if (
                        reply_text
                        and len(reply_text.strip()) >= 60
                        and _is_show_micro_scene(
                            text=reply_text,
                            operational_reference="",
                            reference_example=reference_example,
                            contract=operational_contract if 'operational_contract' in locals() else {},
                        )
                    ):
                        _final_candidate = reply_text.strip()
                except Exception:
                    pass

            # ----------------------------------------------------------
            # COMPOSIÇÃO OPERACIONAL
            # A IA cria a resposta; o front apenas organiza a narrativa
            # para manter a cena operacional clara.
            # ----------------------------------------------------------
            if not ia_locked and response_mode == "SCENE":
                try:
                    composed_reply = _compose_operational_reply(
                        reply_text=reply_text,
                        operational_reference="",
                        reference_example=reference_example,
                        operational_family=operational_family,
                        contract=operational_contract if 'operational_contract' in locals() else {},
                    )
                    if composed_reply:
                        reply_text = composed_reply
                        if not spoken_text:
                            spoken_text = composed_reply
                except Exception:
                    pass

                try:
                    final_live = _is_live_operational_reply(
                        text=reply_text,
                        operational_reference="",
                        reference_example=reference_example,
                        contract=operational_contract if 'operational_contract' in locals() else {},
                    )
                    if final_live and reply_text:
                        _final_candidate = str(reply_text).strip()
                except Exception:
                    pass

            try:
                logging.info(
                    "[CONVERSATIONAL_FRONT][IA_SOVEREIGN_CHECK] source=%s live=%s chars=%s",
                    str(reply_source or "").strip(),
                    bool(
                        True if ia_accepted else _is_live_operational_reply(
                            text=reply_text,
                            operational_reference="",
                            reference_example=reference_example,
                            contract=operational_contract if 'operational_contract' in locals() else {},
                        )
                    ),
                    len(str(reply_text or "")),
                )
            except Exception:
                pass

            try:
                reply_text = wrap_show_response(reply_text)
            except Exception:
                pass

            try:
                if allow_kb_runtime_fallback and kb_reply:
                    rescue_needed = (
                        (not str(reply_text or "").strip())
                        or _looks_like_technical_output(reply_text)
                    )
                    if rescue_needed:
                        reply_text = kb_show_reply_seed or kb_reply
                    if _looks_like_technical_output(spoken_text) or not str(spoken_text or "").strip():
                        spoken_text = kb_show_reply_seed or kb_reply
                    if rescue_needed:
                        reply_source = "front_free_mode_fallback"
                        should_end = False
                        if next_step != "SEND_LINK":
                            next_step = "NONE"
            except Exception:
                pass

            # Etapa 4:
            # não reabrir rebuild tardio depois que a resolução principal já ocorreu.
            # daqui em diante, só aceitamos rescue mínimo de saída vazia/técnica.

            try:
                # IA TOTAL: não remontar pergunta, não injetar proposta, não trocar fechamento.
                # Só aplica a política de perguntas abolidas e uma higiene mínima.
                if reply_text and ("?" in reply_text):
                    if not _should_allow_question(
                        user_text=user_text,
                        kb_context=kb_context if isinstance(kb_context, dict) else {},
                        reply_text=reply_text,
                        understanding={"topic": topic, "confidence": confidence},
                        decider=decider if isinstance(decider, dict) else {},
                    ):
                        reply_text = _strip_trailing_question(reply_text)
                if spoken_text and ("?" in spoken_text):
                    if not _should_allow_question(
                        user_text=user_text,
                        kb_context=kb_context if isinstance(kb_context, dict) else {},
                        reply_text=spoken_text,
                        understanding={"topic": topic, "confidence": confidence},
                        decider=decider if isinstance(decider, dict) else {},
                    ):
                        spoken_text = _strip_trailing_question(spoken_text)
                reply_text = re.sub(r"\s{2,}", " ", str(reply_text or "")).strip(" \n")
                spoken_text = re.sub(r"\s{2,}", " ", str(spoken_text or "")).strip(" \n")
            except Exception:
                pass

            reply_text = _sanitize_user_facing_reply(reply_text)
            spoken_text = _sanitize_user_facing_reply(spoken_text or reply_text)

            reply_text = _apply_reply_size_policy(reply_text, reply_size_policy)
            spoken_text = _apply_reply_size_policy(spoken_text, reply_size_policy)

            if _looks_like_technical_output(reply_text):
                fallback_specific = ""
                if allow_scene_runtime:
                    fallback_specific = _build_kb_anchor_reply(
                        operational_reference="",
                        reference_example=reference_example,
                        clarify_q=(question if not effective_segment else ""),
                        contract=operational_contract if 'operational_contract' in locals() else (base_operational_contract if 'base_operational_contract' in locals() else {}),
                    )
                reply_text = fallback_specific or _build_contract_consequence(
                    operational_contract if 'operational_contract' in locals() else
                    (base_operational_contract if 'base_operational_contract' in locals() else {})
                )

            spoken_text = _sync_spoken_after_technical_rescue(
                reply_text=reply_text,
                spoken_text=spoken_text,
            )


            # 🔒 GUARDA FINAL — impedir saída vazia ou fallback burro
            try:
                _rt = str(reply_text or "").strip()

                if allow_scene_runtime and (not _rt or len(_rt) < 40):
                    forced = ""

                    if operational_contract:
                        forced = _build_kb_show_reply(
                            kb_context=kb_context if isinstance(kb_context, dict) else {},
                            operational_reference="",
                            reference_example=reference_example,
                            effective_segment=effective_segment,
                            operational_family=operational_family,
                            contract=operational_contract,
                        )

                    if (not forced or len(forced.strip()) < 40) and base_operational_contract:
                        forced = _build_kb_show_reply(
                            kb_context=kb_context if isinstance(kb_context, dict) else {},
                            operational_reference="",
                            reference_example=reference_example,
                            effective_segment=effective_segment,
                            operational_family=operational_family,
                            contract=base_operational_contract,
                        )

                    if not forced or len(forced.strip()) < 40:
                        forced = _build_kb_anchor_reply(
                            operational_reference="",
                            reference_example=reference_example,
                            clarify_q="",
                            contract=operational_contract if operational_contract else base_operational_contract,
                        )

                    if forced and len(forced.strip()) >= 40:
                        reply_text = forced
                        if not spoken_text or len(str(spoken_text or "").strip()) < 40:
                            spoken_text = forced
            except Exception:
                pass

            # 🧠 restaura melhor versão se degradou no meio do fluxo
            try:
                if (_final_candidate 
                    and (not reply_text or len(reply_text.strip()) < 40)):
                    reply_text = _final_candidate
            except Exception:
                pass

            if allow_scene_runtime and not str(reply_text or "").strip():
                steps = _split_scene_steps(user_text)

                if len(steps) >= 2:
                    rebuilt = _render_progressive_operational_flow(steps[:6])
                else:
                    rebuilt = ""

                if rebuilt:
                    reply_text = rebuilt
                    spoken_text = rebuilt
                    reply_source = "front_from_user_flow"

            try:
                logger.info(
                    "[IA_SOVEREIGN_CHECK] source=%s is_live=%s len=%s",
                    reply_source,
                    True if ia_accepted else _is_live_operational_reply(
                        text=reply_text,
                        operational_reference="",
                        reference_example=reference_example,
                        contract=operational_contract if 'operational_contract' in locals() else {},
                    ),
                    len(reply_text or ""),
                )
            except Exception:
                pass

            ia_live = bool(
                _is_live_operational_reply(
                    text=reply_text,
                    operational_reference="",
                    reference_example=reference_example,
                    contract=operational_contract if 'operational_contract' in locals() else {},
                )
            )

            ia_density = _operational_density_score(
                text=reply_text,
                operational_reference="",
                reference_example=reference_example,
                effective_segment=str((operational_contract if 'operational_contract' in locals() else {}).get("segment") or "").strip(),
                operational_family=str((operational_contract if 'operational_contract' in locals() else {}).get("operational_family") or "").strip(),
            )

            ia_text = str(reply_text or "").strip()

            ia_show = bool(
                _is_show_micro_scene(
                    text=ia_text,
                    operational_reference="",
                    reference_example=reference_example,
                    contract=operational_contract if 'operational_contract' in locals() else {},
                )
            )

            ia_live_final = bool(
                _is_live_operational_reply(
                    text=ia_text,
                    operational_reference="",
                    reference_example=reference_example,
                    contract=operational_contract if 'operational_contract' in locals() else {},
                )
            )

            _contract_strong = bool(
                (operational_contract if 'operational_contract' in locals() else {}).get("hydrated_from_docs")
                and reference_example
                and str(((operational_contract if 'operational_contract' in locals() else {}) or {}).get("operational_reference") or "").strip()
            )

            _contract_allows_operational_output = bool(
                isinstance((operational_contract if 'operational_contract' in locals() else {}), dict)
                and (operational_contract if 'operational_contract' in locals() else {}).get("hydrated_from_docs")
                and (operational_contract if 'operational_contract' in locals() else {}).get("has_practical_scene")
            )

            _not_explanatory = not _looks_explanatory_reply(
                text=str(reply_text or ""),
                operational_reference="",
                reference_example=reference_example,
                contract=operational_contract if 'operational_contract' in locals() else {},
            )

            _source_now = str(reply_source or "").strip()

            if response_mode == "DIRECT":
                accepted = bool(
                    _source_now in (
                        "front",
                        "front_free_mode",
                        "front_ia_soberana",
                        "front_direct_scene",
                        "front_keep_current",
                    )
                    and len(str(reply_text or "").strip()) >= 40
                    and not _looks_like_technical_output(reply_text)
                )
            else:
                if _contract_strong or _contract_allows_operational_output:
                    accepted = bool(ia_show)
                else:
                    accepted = bool(
                        _source_now == "front_ia_soberana"
                        and ia_live_final
                        and _not_explanatory
                    )

            ia_accepted = accepted

            # ---------------------------------------------------------
            # INTERCEPTAÇÃO DE CONTINUIDADE
            # Quando a pergunta é de continuidade, a IA pode responder
            # com um texto genérico mais longo, mesmo com o roteamento
            # correto. Neste ponto, reconstruímos a resposta usando os
            # fatos objetivos da platform_kb (ex.: process_facts) e
            # preservamos a classificação semântica já feita pela IA.
            # ---------------------------------------------------------
            _qt = str(question_type or "").strip().lower()

            _has_scene_contract_for_continuity = bool(
                isinstance(operational_contract, dict)
                and str(operational_contract.get("response_mode") or "").strip().upper() == "SCENE"
                and bool(operational_contract.get("hydrated_from_docs"))
                and bool(operational_contract.get("has_practical_scene"))
            )

            _should_force_continuity = (
                _qt == "continuity"
                and not _has_scene_contract_for_continuity
            )

            if _should_force_continuity:
                _continuity_current_reply = str(reply_text or "").strip()
                _continuity_reply = _front_build_continuity_reply_from_platform_kb(
                    current_reply=_continuity_current_reply,
                    kb_obj=kb_snapshot_obj if isinstance(kb_snapshot_obj, dict) else {},
                    topic=topic,
                    pack_id=selected_pack_id,
                    user_name=inferred_lead_name or name_hint,
                    ai_turns=ai_turns,
                    has_identity=(
                        has_name
                        or bool(inferred_lead_name or name_hint)
                    ),
                    has_segment=bool(
                        effective_segment
                        or segment_hint
                        or inferred_lead_segment_raw
                        or inferred_lead_segment
                    ),
                    next_step=next_step,
                    question_type=question_type,
                )
                if (
                    _continuity_reply
                    and len(_continuity_reply) >= 30
                    and _continuity_reply != _continuity_current_reply
                ):
                    reply_text = _continuity_reply
                    spoken_text = _continuity_reply
                    reply_source = "front_continuity_facts"
                    accepted = True
                    ia_accepted = True

            if accepted:
                final_reply = str(reply_text or "").strip()
                final_spoken = str(spoken_text or final_reply).strip()
                reply_text = final_reply
                spoken_text = final_spoken
                if reply_source != "front_continuity_facts":
                    reply_source = "front_ia_soberana"

            if not accepted:
                current_text = str(reply_text or "").strip()

                current_show = bool(
                    current_text and _is_show_micro_scene(
                        text=current_text,
                        operational_reference="",
                        reference_example=reference_example,
                        contract=operational_contract if 'operational_contract' in locals() else {},
                    )
                )

                current_live = bool(
                    current_text and _is_live_operational_reply(
                        text=current_text,
                        operational_reference="",
                        reference_example=reference_example,
                        contract=operational_contract if 'operational_contract' in locals() else {},
                    )
                )

                current_is_mild = _looks_explanatory_reply(
                    text=current_text,
                    operational_reference="",
                    reference_example=reference_example,
                    contract=operational_contract if 'operational_contract' in locals() else {},
                )

                _current_not_explanatory = not _looks_explanatory_reply(
                    text=current_text,
                    operational_reference="",
                    reference_example=reference_example,
                    contract=operational_contract if 'operational_contract' in locals() else {},
                )

                if response_mode == "DIRECT":
                    _accept_current = bool(
                        len(str(current_text or "").strip()) >= 40
                        and not _looks_like_technical_output(current_text)
                    )
                elif _contract_strong or _contract_allows_operational_output:
                    _accept_current = bool(current_show)
                elif int(ai_turns or 0) > 0:
                    _accept_current = bool(
                        len(str(current_text or "").strip()) >= 60
                        and not _looks_like_technical_output(current_text)
                    )
                else:
                    _accept_current = bool(
                        current_live
                        and _current_not_explanatory
                        and str(reply_source or "").strip() == "front_ia_soberana"
                    )

                if _accept_current:
                    accepted = True
                    if (
                        (_contract_strong or _contract_allows_operational_output)
                        and str(reply_source or "").strip() not in ("front_ia_soberana", "front_operational_upgrade")
                    ):
                        reply_source = "front_operational_upgrade"
                else:
                    fallback = ""
                    if (
                        (not current_text)
                        or len(current_text) < 40
                        or _looks_like_technical_output(current_text)
                        or (_contract_strong and current_is_mild)
                    ):
                        fallback = (
                            _compose_grounded_scene_with_progression(
                                operational_reference="",
                                contract=operational_contract if 'operational_contract' in locals() else {},
                                reference_example=reference_example,
                            ).strip()
                            or _build_structural_last_resort_reply(
                                operational_reference="",
                                contract=operational_contract if 'operational_contract' in locals() else {},
                            ).strip()
                        )

                    if fallback:
                        reply_text = fallback
                        spoken_text = fallback
                        reply_source = "front_fallback_structural"

            # ---------------------------------------------------------
            # STRUCTURED ASSEMBLY DENTRO DO FREE_MODE
            # ---------------------------------------------------------
            # O FREE_MODE retorna antes do caminho final comum.
            # Portanto, quando a flag está ativa, o montador determinístico
            # precisa assumir aqui, antes do out/return do FREE_MODE.
            # Não altera prompt, não detecta segmento por palavra-chave
            # e usa somente KB/contrato já resolvidos.
            # ---------------------------------------------------------
            try:
                _oc_for_assembly = operational_contract if isinstance(operational_contract, dict) else {}
                _pack_for_assembly = str(
                    selected_pack_id
                    or _oc_for_assembly.get("selected_pack_id")
                    or ""
                ).strip().upper()

                structured_assembly_result = _front_build_structured_assembly_reply(
                    current_reply=reply_text,
                    real_kb_docs=real_kb_docs if 'real_kb_docs' in locals() else {},
                    kb_snapshot_obj=kb_snapshot_obj if isinstance(kb_snapshot_obj, dict) else {},
                    platform_segment_profile=platform_segment_profile if isinstance(platform_segment_profile, dict) else {},
                    selected_pack_id=_pack_for_assembly,
                    response_mode=response_mode,
                    next_step=next_step,
                    ai_turns=ai_turns,
                    lead_name=(
                    _front_sanitize_lead_name_candidate(
                        inferred_lead_name or name_hint,
                        segment_refs=[
                            segment_hint,
                            inferred_lead_segment_raw,
                            inferred_lead_segment,
                        ],
                    )
                    if has_name else ""
                ),
                    lead_segment_raw=inferred_lead_segment_raw or inferred_lead_segment or segment_hint,
                    question_type=question_type,
                )

                if structured_assembly_result and structured_assembly_result.get("replyText"):
                    _reply_source_before_structured_assembly = str(reply_source or "").strip()
                    reply_text = str(structured_assembly_result.get("replyText") or "").strip()
                    spoken_text = str(structured_assembly_result.get("spokenText") or reply_text).strip()
                    reply_source = "front_structured_python_assembly"
                    accepted = True
                    ia_accepted = True
                    try:
                        logging.info(
                            "[STRUCTURED_ASSEMBLY_OWNERSHIP] phase=free_mode previous_source=%s final_source=%s mode=%s question_type=%s",
                            _reply_source_before_structured_assembly,
                            str(reply_source or "").strip(),
                            str(response_mode or "").strip().upper(),
                            str(question_type or "").strip().lower(),
                        )
                    except Exception:
                        pass
            except Exception:
                structured_assembly_result = {}

            logging.info(
                "[IA_FINAL_DECISION] source=%s accepted=%s len=%s live=%s density=%s",
                str(reply_source or "").strip(),
                accepted,
                len(str(reply_text or "")),
                ia_live if 'ia_live' in locals() else None,
                ia_density if 'ia_density' in locals() else None,
            )

            try:
                if response_mode == "DISCOVERY":
                    spoken_text = str(spoken_text or reply_text or "").strip()
                else:
                    spoken_text = _strip_trailing_question(spoken_text or reply_text)
            except Exception:
                spoken_text = str(spoken_text or reply_text or "").strip()

            # --- GARANTIA DE DISCOVERY ANTES DO EARLY RETURN ---
            if response_mode == "DISCOVERY":
                missing_name = not bool(has_name)

                if missing_name:
                    if not _has_question(reply_text):
                        needs_clarify = "yes"

                    name_use = "clarify"
            # ---------------------------------------------------------

            # 🔒 Garantir no máximo 1 pergunta válida (policy)
            try:
                if "?" in reply_text:
                    parts = reply_text.split("?")
                    if len(parts) > 2:
                        reply_text = parts[0].strip() + "?"
                        spoken_text = reply_text
            except Exception:
                pass

            # ---------------------------------------------------------
            # HUMANIZAÇÃO FINAL DO FREE_MODE / DIRECT
            # ---------------------------------------------------------
            # O free_mode retorna cedo. Quando o JSON quebra e cai em
            # JSON_FAIL_SAFE, a resposta pode estar boa operacionalmente,
            # mas ainda sair sem nome/cumprimento/contexto do lead.
            #
            # Aqui não inferimos profissão por palavra-chave e não mexemos
            # em prompt. Apenas usamos os sinais estruturados já capturados
            # no próprio turno e aplicamos a camada existente de humanização.
            # ---------------------------------------------------------
            try:
                _context_lead_name = str(
                    inferred_lead_name
                    or name_hint
                    or ""
                ).strip()

                _context_segment_raw = str(
                    inferred_lead_segment_raw
                    or inferred_lead_segment
                    or segment_hint
                    or ""
                ).strip()

                if _context_segment_raw and not str(segment_hint or "").strip():
                    segment_hint = _context_segment_raw

                if (
                    isinstance(operational_contract, dict)
                    and _context_segment_raw
                    and not str(operational_contract.get("segment") or "").strip()
                ):
                    operational_contract["segment"] = _context_segment_raw

                _context_lead_name = _front_sanitize_lead_name_candidate(
                    _context_lead_name,
                    segment_refs=[
                        _context_segment_raw,
                        segment_hint,
                        inferred_lead_segment_raw,
                        inferred_lead_segment,
                    ],
                )

                if reply_text and _context_lead_name:
                    reply_text = _humanize_reply_with_lead_context(
                        reply=reply_text,
                        lead_name=_context_lead_name if has_name else "",
                        lead_segment_raw=_context_segment_raw,
                    )
                    spoken_text = reply_text
            except Exception:
                pass

            # ---------------------------------------------------------
            # ACABAMENTO FINAL DA MONTAGEM ESTRUTURADA
            # ---------------------------------------------------------
            # Mantém resposta técnica robusta em texto, menor em áudio,
            # e evita saída cortada no meio de palavra/frase.
            # ---------------------------------------------------------
            try:
                if str(reply_source or "").strip() == "front_structured_python_assembly":
                    _rsp = reply_size_policy if isinstance(reply_size_policy, dict) else {}
                    _is_audio_policy = bool(_rsp.get("is_audio"))
                    _contract = operational_contract if isinstance(operational_contract, dict) else {}
                    _mode = str(response_mode or "").strip().upper()
                    _topic = str(topic or "").strip().upper()

                    _technical_direct_platform_kb = bool(
                        not _is_audio_policy
                        and _mode == "DIRECT"
                        and _topic in (
                            "AGENDA",
                            "SERVICOS",
                            "PEDIDOS",
                            "STATUS",
                            "PROCESSO",
                            "ORCAMENTO",
                        )
                        and (
                            _contract.get("hydrated_from_platform_kb")
                            or _contract.get("global_pack_fallback")
                        )
                    )

                    if _technical_direct_platform_kb:
                        reply_text = _front_finalize_reply_surface(
                            reply_text,
                            has_name=bool(has_name),
                            max_chars=820,
                            ensure_punctuation=False,
                        )

                        spoken_text = _front_finalize_reply_surface(
                            spoken_text or reply_text,
                            has_name=bool(has_name),
                            max_chars=820,
                            ensure_punctuation=False,
                        )

                        # Cópia preservada para o retorno técnico DIRECT.
                        # Precisa nascer exatamente neste ramo, pois é aqui
                        # que o texto técnico foi validado e limitado sem
                        # perder o trecho operacional importante.
                        _technical_direct_preserved_reply_text = str(
                            reply_text or ""
                        ).strip()
                        _technical_direct_preserved_spoken_text = str(
                            spoken_text or reply_text or ""
                        ).strip()

                        try:
                            logging.info(
                                "[FRONT_STRUCTURED_FINAL_TRIM] mode=technical_direct topic=%s reply_len=%s",
                                _topic,
                                len(reply_text or ""),
                            )
                        except Exception:
                            pass
                    else:
                        _max_structured_chars = 520 if _is_audio_policy else 800



                        reply_text = _front_trim_to_complete_sentence(
                            reply_text,
                            _max_structured_chars,
                        )
                        spoken_text = _front_trim_to_complete_sentence(
                            spoken_text or reply_text,
                            520 if _is_audio_policy else _max_structured_chars,
                        )
            except Exception:
                pass

            # ---------------------------------------------------------
            # Guarda final de identidade sem frase pronta.
            # Usa somente pergunta já produzida pela IA/KB.
            # ---------------------------------------------------------
            try:
                _identity_question = str(
                    clarify_q
                    or question
                    or ((kb_context or {}).get("discovery_question_hint") if isinstance(kb_context, dict) else "")
                    or ""
                ).strip()

                if (
                    str(next_step or "").strip().upper() != "SEND_LINK"
                    and (not bool(has_name) or not bool(effective_segment or segment_for_prompt or segment_hint))
                    and _identity_question
                    and "?" not in str(reply_text or "")
                ):
                    reply_text = f"{str(reply_text or '').rstrip()}\n\n{_identity_question}".strip()
                    spoken_text = reply_text
                    name_use = "clarify"
                    needs_clarify = "yes"
            except Exception:
                pass

            out = {
                "response_mode": response_mode,
                "replyText": reply_text,
                "spokenText": spoken_text,
                "understanding": {
                    "topic": topic,
                    "intent": topic,
                    "confidence": confidence,
                    "question_type": question_type,
                    "needsClarify": needs_clarify,
                    "clarifyQuestion": clarify_q,
                    "leadName": name_hint if has_name else "",
                    "segmentHint": segment_hint,
                    "leadSegmentRaw": inferred_lead_segment_raw or inferred_lead_segment or segment_hint,
                },
                "nextStep": next_step,
                "shouldEnd": should_end,
                "nameUse": name_use,
                "prefersText": (next_step == "SEND_LINK"),
                "replySource": (reply_source or "front_free_mode"),
                "kbSnapshotSizeChars": len(kb_snapshot or ""),
                "tokenUsage": token_usage,
                "replySizePolicy": reply_size_policy if isinstance(reply_size_policy, dict) else {},
                "operationalContract": operational_contract if 'operational_contract' in locals() else {},
                "leadName": (
                    _front_sanitize_lead_name_candidate(
                        name_hint,
                        segment_refs=[
                            segment_hint,
                            inferred_lead_segment_raw,
                            inferred_lead_segment,
                        ],
                    )
                    if has_name else ""
                ),
                "segmentHint": segment_hint,
            }

            if decider_only and isinstance(decider, dict):
                out["decider"] = decider

            try:
                am = out.get("aiMeta") or {}
                if not isinstance(am, dict):
                    am = {}
                rsp = reply_size_policy if isinstance(reply_size_policy, dict) else {}
                am["replySizePolicy"] = str(rsp.get("label") or "")
                am["replyTargetChars"] = int(rsp.get("target_chars") or 0)
                am["replyMaxChars"] = int(rsp.get("max_chars") or 0)
                am["replyIsAudioPolicy"] = bool(rsp.get("is_audio"))
                am["replyTechnicalNeed"] = bool(rsp.get("technical_need"))
                am["structuredAssemblyEnabled"] = bool(FRONT_STRUCTURED_ASSEMBLY_ENABLED)
                sar = structured_assembly_result if isinstance(structured_assembly_result, dict) else {}
                if sar:
                    am["assemblyMode"] = str(sar.get("assemblyMode") or "")
                    am["contentSourceType"] = str(sar.get("contentSourceType") or "")
                    am["contentSourceId"] = str(sar.get("contentSourceId") or "")
                    am["materialSource"] = str(sar.get("materialSource") or "")
                out["aiMeta"] = am
            except Exception:
                pass

            # ---------------------------------------------------------
            # SAÍDA FINAL DO FREE_MODE PARA DIRECT TÉCNICO
            # ---------------------------------------------------------
            # Diagnóstico em produção:
            # - FRONT_STRUCTURED_FINAL_TRIM preserva ~813 chars;
            # - wa_bot.py recebe ~649 chars;
            # - portanto a perda ocorre no retorno sanitizado do FREE_MODE.
            #
            # Para este caso específico, o texto já foi montado, aceito e
            # higienizado. Então devolvemos o payload diretamente, aplicando
            # apenas a blindagem de envelope JSON se ela for realmente
            # necessária.
            #
            # Preserva pilares:
            # - não altera prompts;
            # - não libera microcena;
            # - não altera política geral de tamanho;
            # - não afeta áudio;
            # - atua só em DIRECT técnico vindo da platform_kb.
            # ---------------------------------------------------------
            try:
                _contract = (
                    operational_contract
                    if isinstance(operational_contract, dict)
                    else {}
                )
                _rsp = reply_size_policy if isinstance(reply_size_policy, dict) else {}
                _is_audio_policy = bool(_rsp.get("is_audio"))
                _source = str(reply_source or "").strip()
                _mode = str(response_mode or "").strip().upper()
                _topic = str(topic or "").strip().upper()

                _is_technical_direct_exit = bool(
                    not _is_audio_policy
                    and _source == "front_structured_python_assembly"
                    and _mode == "DIRECT"
                    and _topic in (
                        "AGENDA",
                        "SERVICOS",
                        "PEDIDOS",
                        "STATUS",
                        "PROCESSO",
                        "ORCAMENTO",
                    )
                    and (
                        _contract.get("hydrated_from_platform_kb")
                        or _contract.get("global_pack_fallback")
                    )
                    and isinstance(reply_text, str)
                    and len(reply_text.strip()) >= 700
                )

                if _is_technical_direct_exit:
                    _preserved_reply = str(
                        locals().get("_technical_direct_preserved_reply_text")
                        or ""
                    ).strip()
                    _preserved_spoken = str(
                        locals().get("_technical_direct_preserved_spoken_text")
                        or ""
                    ).strip()

                    _reply_probe = (
                        _preserved_reply
                        if len(_preserved_reply) >= 700
                        else str(reply_text or "").strip()
                    )
                    _spoken_probe = (
                        _preserved_spoken
                        if len(_preserved_spoken) >= 700
                        else str(spoken_text or _reply_probe or "").strip()
                    )

                    if len(_preserved_reply) >= 700:
                        _safe_preserved_reply = _preserved_reply
                        _safe_preserved_spoken = _preserved_spoken or _preserved_reply

                        # -------------------------------------------------
                        # Se o texto preservado ainda estiver envelopado em
                        # JSON, devemos extrair replyText. Porém, se o texto
                        # extraído vier muito menor, isso indica que o campo
                        # interno já estava truncado. Nesse caso, NÃO usamos
                        # o conteúdo extraído e também NÃO devolvemos o JSON
                        # bruto. Em vez disso, removemos estruturalmente o
                        # envelope preservando apenas o conteúdo textual.
                        # -------------------------------------------------
                        if _safe_preserved_reply.startswith("{") or _safe_preserved_reply.startswith("```"):
                            _unwrapped_reply = (
                                _unwrap_front_json_envelope(_safe_preserved_reply)
                                or ""
                            ).strip()

                            if len(_unwrapped_reply) >= max(700, int(len(_preserved_reply) * 0.90)):
                                _safe_preserved_reply = _unwrapped_reply
                            else:
                                _m = re.search(
                                    r'"replyText"\s*:\s*"(.*)',
                                    _safe_preserved_reply,
                                    re.DOTALL,
                                )
                                if _m:
                                    _candidate = str(_m.group(1) or "")
                                    _candidate = re.sub(
                                        r'"?\s*}\s*$',
                                        "",
                                        _candidate,
                                        flags=re.DOTALL,
                                    ).strip()
                                    if _candidate:
                                        _safe_preserved_reply = _candidate

                        if _safe_preserved_spoken.startswith("{") or _safe_preserved_spoken.startswith("```"):
                            _unwrapped_spoken = (
                                _unwrap_front_json_envelope(_safe_preserved_spoken)
                                or ""
                            ).strip()

                            if len(_unwrapped_spoken) >= max(700, int(len(_preserved_spoken) * 0.90)):
                                _safe_preserved_spoken = _unwrapped_spoken
                            else:
                                _m = re.search(
                                    r'"replyText"\s*:\s*"(.*)',
                                    _safe_preserved_spoken,
                                    re.DOTALL,
                                )
                                if _m:
                                    _candidate = str(_m.group(1) or "")
                                    _candidate = re.sub(
                                        r'"?\s*}\s*$',
                                        "",
                                        _candidate,
                                        flags=re.DOTALL,
                                    ).strip()
                                    if _candidate:
                                        _safe_preserved_spoken = _candidate
                                    else:
                                        _safe_preserved_spoken = _safe_preserved_reply
                                else:
                                    _safe_preserved_spoken = _safe_preserved_reply

                        # -------------------------------------------------
                        # Guarda final antes do retorno técnico antecipado.
                        # Este ramo retorna antes do caminho comum; portanto
                        # precisa aplicar aqui a proteção contra vocativo
                        # nominal quando has_name=False.
                        #
                        # Não usa palavra-chave, não altera prompt,
                        # não chama modelo e não muda arquitetura.
                        # -------------------------------------------------
                        try:
                            _safe_preserved_reply = _front_remove_unsafe_nominal_opening(
                                _safe_preserved_reply,
                                has_name=has_name,
                            )
                            _safe_preserved_spoken = _front_remove_unsafe_nominal_opening(
                                _safe_preserved_spoken or _safe_preserved_reply,
                                has_name=has_name,
                            )
                        except Exception:
                            pass

                        # -------------------------------------------------
                        # Guarda de identidade no mesmo ramo antecipado.
                        # Usa somente pergunta já existente no fluxo
                        # (clarify_q/question/discovery_question_hint).
                        # Não cria frase pronta no código.
                        # -------------------------------------------------
                        try:
                            (
                                _safe_preserved_reply,
                                _safe_preserved_spoken,
                                _name_use_guard,
                                _needs_clarify_guard,
                            ) = _apply_identity_clarify_guard(
                                reply_text=_safe_preserved_reply,
                                clarify_q=clarify_q,
                                question=question,
                                kb_context=kb_context,
                                next_step=next_step,
                                has_name=has_name,
                                effective_segment=effective_segment,
                                segment_for_prompt=segment_for_prompt,
                                segment_hint=segment_hint,
                                limit=820,
                            )

                            if _name_use_guard:
                                name_use = _name_use_guard

                            if _needs_clarify_guard:
                                needs_clarify = _needs_clarify_guard

                        except Exception:
                            pass

                        try:
                            _safe_preserved_reply = _front_remove_unsafe_nominal_opening(
                                _safe_preserved_reply,
                                has_name=has_name,
                            )
                            _safe_preserved_spoken = _front_remove_unsafe_nominal_opening(
                                _safe_preserved_spoken or _safe_preserved_reply,
                                has_name=has_name,
                            )
                        except Exception:
                            pass

                        try:
                            (
                                _safe_preserved_reply,
                                _safe_preserved_spoken,
                                _name_use_guard,
                                _needs_clarify_guard,
                            ) = _apply_identity_clarify_guard(
                                reply_text=_safe_preserved_reply,
                                clarify_q=clarify_q,
                                question=question,
                                kb_context=kb_context,
                                next_step=next_step,
                                has_name=has_name,
                                effective_segment=effective_segment,
                                segment_for_prompt=segment_for_prompt,
                                segment_hint=segment_hint,
                                limit=820,
                            )

                            if _name_use_guard:
                                name_use = _name_use_guard

                            if _needs_clarify_guard:
                                needs_clarify = _needs_clarify_guard

                        except Exception:
                            pass

                        out["replyText"] = _front_finalize_reply_surface(
                            _safe_preserved_reply,
                            has_name=bool(has_name),
                            max_chars=820,
                        )

                        out["spokenText"] = _front_finalize_reply_surface(
                            _safe_preserved_spoken or out["replyText"],
                            has_name=bool(has_name),
                            max_chars=820,
                        )
                    else:
                        if _reply_probe.startswith("{") or _reply_probe.startswith("```"):
                            _reply_probe = _unwrap_front_json_envelope(_reply_probe) or _reply_probe

                        if _spoken_probe.startswith("{") or _spoken_probe.startswith("```"):
                            _spoken_probe = _unwrap_front_json_envelope(_spoken_probe) or _reply_probe

                        try:
                            _reply_probe = _front_remove_unsafe_nominal_opening(
                                _reply_probe,
                                has_name=has_name,
                            )
                            _spoken_probe = _front_remove_unsafe_nominal_opening(
                                _spoken_probe or _reply_probe,
                                has_name=has_name,
                            )
                        except Exception:
                            pass

                        try:
                            _reply_probe = _front_remove_unsafe_nominal_opening(
                                _reply_probe,
                                has_name=has_name,
                            )
                            _spoken_probe = _front_remove_unsafe_nominal_opening(
                                _spoken_probe or _reply_probe,
                                has_name=has_name,
                            )
                        except Exception:
                            pass

                        out["replyText"] = _front_finalize_reply_surface(
                            _reply_probe,
                            has_name=bool(has_name),
                            max_chars=820,
                            ensure_punctuation=False,
                        )

                        out["spokenText"] = _front_finalize_reply_surface(
                            _spoken_probe or out["replyText"],
                            has_name=bool(has_name),
                            max_chars=820,
                            ensure_punctuation=False,
                        )

                    # -------------------------------------------------
                    # Interceptação factual antes do retorno técnico
                    # antecipado.
                    #
                    # Com o buffer temporal, uma pergunta pontual pode vir
                    # dentro do primeiro inbound consolidado junto com
                    # saudação, nome e segmento. Nessa situação, o modelo
                    # pode classificar o conjunto como broad, mas o front já
                    # possui sinais estruturais suficientes para tentar a
                    # resposta factual curta.
                    #
                    # Escopo:
                    # - não usa palavra-chave do usuário;
                    # - não altera prompt;
                    # - não usa regex;
                    # - não cria frase pronta;
                    # - reaproveita facts da KB via função existente.
                    # -------------------------------------------------
                    try:
                        _qt = str(question_type or "").strip().lower()
                        # -------------------------------------------------
                        # No retorno técnico antecipado, a IA já montou
                        # toda a resposta. Aqui podemos tentar continuidade
                        # factual somente como refinamento estrutural final.
                        #
                        # Regras:
                        # - respeitar perguntas amplas (broad);
                        # - permitir factual curta em perguntas objetivas;
                        # - sem depender de tema específico;
                        # - sem regex/palavras-chave;
                        # - sem matar microcenas cedo demais.
                        # -------------------------------------------------
                        _reply_len = len(str(out.get("replyText") or "").strip())

                        _has_process_facts = bool(
                            isinstance(kb_snapshot_obj, dict)
                            and kb_snapshot_obj.get("process_facts")
                        )

                        _should_force_continuity = (
                            _qt == "continuity"
                            and _reply_len < 420
                        )

                        if _should_force_continuity:
                            _continuity_current_reply = str(out.get("replyText") or "").strip()
                            _continuity_reply = _front_build_continuity_reply_from_platform_kb(
                                current_reply=_continuity_current_reply,
                                kb_obj=kb_snapshot_obj if isinstance(kb_snapshot_obj, dict) else {},
                                topic=topic,
                                pack_id=selected_pack_id if "selected_pack_id" in locals() else "",
                                user_name=inferred_lead_name or name_hint,
                                ai_turns=ai_turns,
                                has_identity=(
                                    has_name
                                    or bool(inferred_lead_name or name_hint)
                                ),
                                has_segment=bool(
                                    effective_segment
                                    or segment_hint
                                    or inferred_lead_segment_raw
                                    or inferred_lead_segment
                                ),
                                next_step=next_step,
                                question_type=question_type,
                            )
                            if (
                                _continuity_reply
                                and len(_continuity_reply) >= 30
                                and _continuity_reply != _continuity_current_reply
                            ):
                                out["replyText"] = _continuity_reply
                                out["spokenText"] = _continuity_reply
                                out["replySource"] = "front_continuity_facts"
                                logging.info(
                                    "[FREE_MODE_TECH_DIRECT_CONTINUITY_FACTS] topic=%s question_type=%s reply_len=%s",
                                    str(topic or "").strip().upper(),
                                    _qt,
                                    len(_continuity_reply),
                                )
                    except Exception:
                        pass

                    try:
                        out = _sanitize_front_result_payload(out)

                        logging.info(
                            "[FREE_MODE_TECH_DIRECT_RETURN] topic=%s reply_len=%s spoken_len=%s preserved_len=%s",
                            _topic,
                            len(str(out.get("replyText") or "")),
                            len(str(out.get("spokenText") or "")),
                            len(_preserved_reply or ""),
                        )
                    except Exception:
                        pass

                    return out
            except Exception:
                pass

            logging.info(
                "[CONVERSATIONAL_FRONT][FREE_MODE] ai_turns=%s topic=%s canonical_topic=%s upstream_topic_hint=%s platform_kb_mode=%s confidence=%s nextStep=%s shouldEnd=%s kbChars=%s tok=%s source=%s contract=%s docs=%s hydrated=%s",
                ai_turns,
                topic,
                canonical_topic if 'canonical_topic' in locals() else "",
                upstream_topic_hint if 'upstream_topic_hint' in locals() else "",
                platform_kb_mode if 'platform_kb_mode' in locals() else False,
                confidence,
                next_step,
                should_end,
                len(kb_snapshot or ""),
                token_usage or {},
                (reply_source or "front_free_mode"),
                operational_contract if 'operational_contract' in locals() else {},
                real_kb_docs if 'real_kb_docs' in locals() else {},
                bool((operational_contract or {}).get("hydrated_from_docs")) if 'operational_contract' in locals() and isinstance(operational_contract, dict) else False,
            )
            # ---------------------------------------------------------
            # FREE_MODE fallback final guard
            #
            # Este é o segundo ramo de saída do free_mode:
            # ocorre quando a resposta estruturada não foi aceita e o
            # fluxo não entrou no FREE_MODE_TECH_DIRECT_RETURN.
            #
            # Antes ele retornava direto, sem passar pelas mesmas guardas
            # do ramo técnico. Isso permitia regressões como:
            # - vocativo nominal sem nome confirmado;
            # - pergunta aberta fora dos critérios;
            # - corte por tamanho sem fechamento limpo;
            # - replyText/spokenText divergentes.
            #
            # Não cria frase pronta.
            # Não usa palavra-chave.
            # Não altera prompt.
            # Não chama modelo.
            # ---------------------------------------------------------
            try:
                out = _sanitize_front_result_payload(out)

                _free_reply = str(out.get("replyText") or reply_text or "").strip()
                _free_spoken = str(out.get("spokenText") or spoken_text or _free_reply or "").strip()

                if _free_reply.startswith("{") or _free_reply.startswith("```"):
                    _free_reply = _unwrap_front_json_envelope(_free_reply) or _free_reply

                if _free_spoken.startswith("{") or _free_spoken.startswith("```"):
                    _free_spoken = _unwrap_front_json_envelope(_free_spoken) or _free_reply

                _is_broad_question_fallback = str(question_type or "").strip().lower() not in ("punctual", "continuity", "simulation")
                _prefer_current_reply = bool(
                    (int(ai_turns or 0) > 0 and len(str(_free_reply or "").strip()) >= 60)
                    or not _is_broad_question_fallback
                )

                _free_reply = _front_pick_rich_free_mode_base(
                    current_reply=_free_reply,
                    operational_contract=operational_contract if isinstance(operational_contract, dict) else {},
                    kb_context=kb_context if isinstance(kb_context, dict) else {},
                    prefer_current=_prefer_current_reply,
                )
                _free_spoken = _free_reply


                _free_reply = _front_remove_unsafe_nominal_opening(
                    _free_reply,
                    has_name=has_name,
                )
                _free_spoken = _front_remove_unsafe_nominal_opening(
                    _free_spoken or _free_reply,
                    has_name=has_name,
                )


                _continuity_topic = str(
                    (canonical_topic if 'canonical_topic' in locals() else "")
                    or topic
                    or upstream_topic_hint
                    or ""
                ).strip().upper()
                _continuity_pack_id = str(
                    selected_pack_id if 'selected_pack_id' in locals() else ""
                ).strip().upper()
                if not _continuity_pack_id:
                    _continuity_pack_id = _pick_pack_for_intent(_continuity_topic)

                # -----------------------------------------------------
                # Identidade estrutural para continuidade
                #
                # No turno em que o lead informa o nome e já faz uma
                # pergunta prática, `has_name` pode ainda estar falso,
                # porque a persistência só será consolidada depois.
                #
                # Para o helper de continuidade, o que importa é se já
                # existe nome sanitizado neste turno ou em estado válido.
                # Isso evita perder a resposta rica da KB exatamente no
                # segundo turno, sem aceitar segmento como nome.
                # -----------------------------------------------------
                try:
                    _continuity_safe_name = _front_sanitize_lead_name_candidate(
                        name_hint or current_turn_lead_name or inferred_lead_name,
                        segment_refs=[
                            segment_hint,
                            inferred_lead_segment_raw,
                            inferred_lead_segment,
                        ],
                    )
                except Exception:
                    _continuity_safe_name = ""

                _continuity_has_identity = bool(
                    has_name
                    or str(_continuity_safe_name or "").strip()
                )

                _continuity_has_segment = bool(
                    effective_segment
                    or segment_for_prompt
                    or segment_hint
                    or inferred_lead_segment_raw
                    or inferred_lead_segment
                )

                _continuity_question_type = str(question_type or "").strip().lower()

                _has_scene_contract_for_final_continuity = bool(
                    str(reply_source or "").strip() == "front_structured_python_assembly"
                    or (
                        isinstance(operational_contract, dict)
                        and str(operational_contract.get("response_mode") or "").strip().upper() == "SCENE"
                        and bool(operational_contract.get("hydrated_from_docs"))
                        and bool(operational_contract.get("has_practical_scene"))
                    )
                )

                _apply_final_continuity = (
                    _continuity_question_type in ("punctual", "continuity", "simulation")
                    and not _has_scene_contract_for_final_continuity
                )
                _continuity_reply_built = False

                _free_reply_before_continuity = str(_free_reply or "").strip()

                if _apply_final_continuity:
                    _free_reply = _front_build_continuity_reply_from_platform_kb(
                        current_reply=_free_reply,
                        kb_obj=kb_snapshot_obj if isinstance(kb_snapshot_obj, dict) else {},
                        topic=_continuity_topic,
                        pack_id=_continuity_pack_id,
                        user_name=_continuity_safe_name,
                        ai_turns=int(ai_turns or 0),
                        has_identity=_continuity_has_identity,
                        has_segment=_continuity_has_segment,
                        next_step=next_step,
                        question_type=question_type,
                    )

                    _continuity_reply_built = bool(
                        str(_free_reply or "").strip()
                        and str(_free_reply or "").strip() != _free_reply_before_continuity
                    )

                    _free_spoken = _front_build_continuity_reply_from_platform_kb(
                        current_reply=_free_spoken or _free_reply,
                        kb_obj=kb_snapshot_obj if isinstance(kb_snapshot_obj, dict) else {},
                        topic=_continuity_topic,
                        pack_id=_continuity_pack_id,
                        user_name=_continuity_safe_name,
                        ai_turns=int(ai_turns or 0),
                        has_identity=_continuity_has_identity,
                        has_segment=_continuity_has_segment,
                        next_step=next_step,
                        question_type=question_type,
                    )
                # -------------------------------------------------------
                # Separação estrutural:
                #
                # Identidade humana do lead e contexto operacional de
                # segmento possuem impactos diferentes no pipeline.
                #
                # Nome ausente:
                # - exige clarification;
                # - impede continuidade segura;
                # - impede persistência confiável.
                #
                # Segmento ausente:
                # - reduz enriquecimento operacional;
                # - reduz microcena/contexto;
                # - mas NÃO invalida identidade já resolvida.
                #
                # Mantém:
                # - discovery progressivo;
                # - IA soberana;
                # - continuidade incremental;
                # - proteção contra vocativo inseguro.
                # -------------------------------------------------------

                _missing_identity = bool(
                    not bool(_continuity_has_identity)
                )

                _missing_segment_context = bool(
                    not bool(_continuity_has_segment)
                )

                _has_segment_for_identity = bool(
                    effective_segment or segment_for_prompt or segment_hint
                )

                if not _has_segment_for_identity:
                    _declared_segment = _front_extract_declared_segment_from_user_text(user_text)
                    if _declared_segment:
                        segment_hint = segment_hint or _declared_segment
                        inferred_lead_segment_raw = inferred_lead_segment_raw or _declared_segment
                        inferred_lead_segment = inferred_lead_segment or _declared_segment
                        _has_segment_for_identity = True
                        _missing_identity = bool(not bool(has_name))

                # Neste ramo, pergunta aberta comercial não é identidade.
                # Só aceitamos pergunta existente se ela pedir nome.
                _identity_question = ""
                _open_question_tails = []
                try:
                    _candidate_identity_question = str(
                        clarify_q
                        or question
                        or ""
                    ).strip()

                    if _candidate_identity_question:
                        _open_question_tails.append(_candidate_identity_question)

                    if _front_identity_request_is_valid(_candidate_identity_question):
                        _identity_question = _candidate_identity_question

                    if isinstance(kb_context, dict):
                        for _k in (
                            "discovery_question_hint",
                            "segment_question_preferred",
                            "question",
                            "clarify_q",
                        ):
                            _v = str(kb_context.get(_k) or "").strip()
                            if _v:
                                _open_question_tails.append(_v)

                        _kb_identity_question = str(
                            kb_context.get("identity_question_hint")
                            or ""
                        ).strip()
                        if (
                            not _identity_question
                            and _front_identity_request_is_valid(_kb_identity_question)
                        ):
                            _identity_question = _kb_identity_question

                    if _missing_identity and not _identity_question:
                        _identity_question = _front_build_identity_request(
                            has_name=has_name,
                            has_segment=_has_segment_for_identity,
                        )
                except Exception:
                    _identity_question = ""

                _free_reply = _front_remove_known_open_question_tail(
                    _free_reply,
                    _open_question_tails,
                )
                _free_spoken = _front_remove_known_open_question_tail(
                    _free_spoken,
                    _open_question_tails,
                )

                _free_reply = _front_clean_free_mode_tail(_free_reply)
                _free_spoken = _front_clean_free_mode_tail(_free_spoken)

                # Remove pergunta aberta que tenha escapado no free_mode,
                # preservando perguntas apenas quando forem exatamente a
                # pergunta de identidade já existente no fluxo.
                if "?" in _free_reply:
                    _norm_reply = _front_normalize_identity_text(_free_reply)
                    _norm_identity = _front_normalize_identity_text(_identity_question)
                    if not (_norm_identity and _norm_identity in _norm_reply):
                        _free_reply = _strip_trailing_question(_free_reply)
                        _free_spoken = _strip_trailing_question(_free_spoken)
                        _free_reply = _front_clean_free_mode_tail(_free_reply)
                        _free_spoken = _front_clean_free_mode_tail(_free_spoken)

                # Cumprimento seguro no ramo regressivo.
                # Não usa vocativo nominal, não depende do LLM e não cria
                # novo ritual comercial no código.
                #
                # Quando a resposta veio do structured assembly em SCENE real,
                # reaplica o ritual de primeiro contato já existente neste arquivo
                # no ponto em que ele não será substituído pela montagem estruturada.
                _structured_scene_first_contact = False
                try:
                    _allow_safe_greeting = int(ai_turns or 0) <= 0
                    _assembly_source_type = str(
                        (structured_assembly_result or {}).get("contentSourceType")
                        or ""
                    ).strip()

                    _reply_source_now = str(reply_source or "").strip()
                    _response_mode_now = str(response_mode or "").strip().upper()
                    _contract_now = (
                        operational_contract
                        if isinstance(operational_contract, dict)
                        else {}
                    )

                    _structured_scene_first_contact = bool(
                        _missing_identity
                        and bool(_identity_question)
                        and not bool(has_name)
                        and bool(_contract_now.get("hydrated_from_docs"))
                        and bool(_contract_now.get("has_practical_scene"))
                        and bool(_contract_now.get("micro_scene_conversational"))
                        and (
                            _reply_source_now == "front_structured_python_assembly"
                            or _reply_source_now == "front_free_mode_fallback"
                        )
                    )

                    if _structured_scene_first_contact:
                        _scene_body = str(
                            _contract_now.get("micro_scene_conversational")
                            or _free_reply
                            or ""
                        ).strip()
                        _scene_body = re.sub(
                            r"(?i)^\s*ol[áa][!.]?\s*",
                            "",
                            _scene_body,
                        ).strip()

                        if _scene_body:
                            _free_reply = (
                                "Olá! Obrigado pelo contato.\n\n"
                                f"{_scene_body}"
                            ).strip()
                            _free_spoken = _free_reply
                    elif _allow_safe_greeting:
                        if _free_reply and not re.match(r"(?i)^\s*ol[áa]\b", _free_reply):
                            _free_reply = f"Olá. {_free_reply}".strip()
                        if _free_spoken and not re.match(r"(?i)^\s*ol[áa]\b", _free_spoken):
                            _free_spoken = f"Olá. {_free_spoken}".strip()
                except Exception:
                    pass

                if (
                    _structured_scene_first_contact
                    and _identity_question
                    and isinstance(operational_contract, dict)
                ):
                    try:
                        _lead_refinement_question = str(
                            operational_contract.get("lead_refinement_question")
                            or ""
                        ).strip()
                        if _lead_refinement_question:
                            _identity_base = re.sub(
                                r"[\s.?!]+$",
                                "",
                                str(_identity_question or "").strip(),
                            )
                            _refinement_tail = re.sub(
                                r"^[\s,.;:!?]+|[\s.?!]+$",
                                "",
                                _lead_refinement_question,
                            )
                            if _identity_base and _refinement_tail:
                                _identity_question = (
                                    f"{_identity_base} e {_refinement_tail}."
                                ).strip()
                    except Exception:
                        pass

                if (
                    str(next_step or "").strip().upper() != "SEND_LINK"
                    and _missing_identity
                    and _identity_question
                    and not _front_has_identity_request_tail(
                        _free_reply,
                        _identity_question,
                    )
                ):
                    _limit = 1200 if _structured_scene_first_contact else 820
                    _sep = "\n\n"
                    _base_limit = max(
                        320,
                        _limit - len(_identity_question) - len(_sep),
                    )
                    _base_reply = _front_trim_free_mode_sentence(
                        _free_reply,
                        _base_limit,
                    )
                    _free_reply = f"{_base_reply}{_sep}{_identity_question}".strip()
                    _free_spoken = _free_reply
                    name_use = "clarify"
                    needs_clarify = "yes"

                _free_reply_limit = 1200 if _structured_scene_first_contact else 820
                out["replyText"] = _front_trim_free_mode_sentence(
                    _free_reply,
                    _free_reply_limit,
                )

                try:
                    _spoken_limit = 820
                    _spoken_source = _free_spoken or out["replyText"]

                    # -------------------------------------------------------
                    # Preservação estrutural de respostas de continuidade
                    #
                    # Quando já temos:
                    # - identidade validada (nome e segmento conhecidos),
                    # - pergunta de clarificação inexistente,
                    # - turno posterior ao primeiro,
                    # - resposta rica já construída a partir da platform_kb,
                    #
                    # o pipeline de áudio não deve substituir esse conteúdo
                    # por uma versão curta/genérica baseada em runtime_short.
                    #
                    # Neste caso, o áudio usa como base o próprio replyText
                    # final, aplicando apenas corte de tamanho.
                    #
                    # Regras:
                    # - sem palavras-chave;
                    # - sem alteração de prompt;
                    # - sem IA adicional;
                    # - impacto apenas na compactação do spokenText.
                    # -------------------------------------------------------
                    try:
                        _preserve_continuity_reply = bool(
                            int(ai_turns or 0) > 0
                            and not _missing_identity
                            and not bool(_identity_question)
                            and (
                                bool(_continuity_reply_built)
                                or len(str(out.get("replyText") or "").strip()) >= 400
                            )
                            and bool(
                                _continuity_pack_id
                                or (
                                    isinstance(kb_snapshot_obj, dict)
                                    and bool(kb_snapshot_obj.get("value_packs_v1"))
                                )
                            )
                        )

                        if _preserve_continuity_reply:
                            _spoken_source = str(
                                out.get("replyText") or _spoken_source or ""
                            ).strip()
                    except Exception:
                        pass

                    if isinstance(reply_size_policy, dict) and bool(reply_size_policy.get("is_audio")):
                        _spoken_limit = int(
                            reply_size_policy.get("max_chars")
                            or reply_size_policy.get("target_chars")
                            or 460
                        )
                        _spoken_limit = max(280, min(_spoken_limit, 520))

                    # Continuidade útil não deve ser recompactada para o
                    # limite curto padrão de áudio. O texto já foi montado
                    # por KB estruturada e será cortado em frase completa.
                    try:
                        if bool(_preserve_continuity_reply):
                            _spoken_limit = max(int(_spoken_limit or 0), 700)
                            _spoken_limit = min(_spoken_limit, 760)
                    except Exception:
                        pass

                    # Para áudio, a pergunta de identidade não pode ser
                    # sacrificada pelo corte compacto. Primeiro cortamos a
                    # base, depois anexamos a pergunta já calculada pelo fluxo.
                    if (
                        isinstance(reply_size_policy, dict)
                        and bool(reply_size_policy.get("is_audio"))
                        and _missing_identity
                        and _identity_question
                    ):
                        _sep = " "
                        _base_limit = max(
                            220,
                            int(_spoken_limit) - len(_identity_question) - len(_sep),
                        )
                        _spoken_source = _front_remove_known_open_question_tail(
                            str(_spoken_source or ""),
                            [_identity_question],
                        )
                        _spoken_base = _front_trim_free_mode_sentence(
                            _spoken_source,
                            _base_limit,
                        )
                        out["spokenText"] = _front_trim_free_mode_sentence(
                            f"{_spoken_base}{_sep}{_identity_question}".strip(),
                            _spoken_limit,
                        )
                    else:
                        out["spokenText"] = _front_trim_free_mode_sentence(
                            _spoken_source,
                            _spoken_limit,
                        )
                except Exception:
                    out["spokenText"] = _front_trim_free_mode_sentence(
                        _free_spoken or out["replyText"],
                        460,
                    )

                # Identidade no retorno:
                # se o nome veio do turno atual e foi sanitizado, ele pode
                # sair para o wa_bot persistir. Caso contrário, seguimos
                # bloqueando hipóteses não validadas.
                _safe_payload_name = _front_sanitize_lead_name_candidate(
                    name_hint or current_turn_lead_name or inferred_lead_name,
                    segment_refs=[
                        segment_hint,
                        inferred_lead_segment_raw,
                        inferred_lead_segment,
                    ],
                )

                if not bool(_safe_payload_name):
                    out["leadName"] = ""
                    out["name_hint"] = ""
                    try:
                        _u = out.get("understanding")
                        if isinstance(_u, dict):
                            _u["leadName"] = ""
                            _u["name_hint"] = ""
                            _u["lead_name"] = ""
                    except Exception:
                        pass
                else:
                    out["leadName"] = _safe_payload_name
                    out["name_hint"] = _safe_payload_name
                    try:
                        _u = out.get("understanding")
                        if isinstance(_u, dict):
                            _u["leadName"] = _safe_payload_name
                            _u["name_hint"] = _safe_payload_name
                            _u["lead_name"] = _safe_payload_name
                    except Exception:
                        pass

                try:
                    if not _missing_identity and not _identity_question:
                        out["needsClarify"] = "no"
                        out["clarifyQuestion"] = ""
                        try:
                            _u = out.get("understanding")
                            if isinstance(_u, dict):
                                _u["needsClarify"] = "no"
                                _u["clarifyQuestion"] = ""
                        except Exception:
                            pass

                    # question_type preservado conforme decisão anterior do pipeline.
                except Exception:
                    pass

                try:
                    if _missing_identity and _identity_question:
                        out["needsClarify"] = "yes"
                        out["clarifyQuestion"] = _identity_question
                        _u = out.get("understanding")
                        if isinstance(_u, dict):
                            _u["needsClarify"] = "yes"
                            _u["clarifyQuestion"] = _identity_question
                except Exception:
                    pass

                if out["replyText"] and out["replyText"][-1] not in ".!?":
                    out["replyText"] = out["replyText"].rstrip() + "."

                if out["spokenText"] and out["spokenText"][-1] not in ".!?":
                    out["spokenText"] = out["spokenText"].rstrip() + "."

                out = _sanitize_front_result_payload(out)

                logging.info(
                    "[FREE_MODE_FINAL_GUARD] topic=%s reply_len=%s spoken_len=%s missing_identity=%s identity_question=%s",
                    topic,
                    len(str(out.get("replyText") or "")),
                    len(str(out.get("spokenText") or "")),
                    _missing_identity,
                    bool(_identity_question),
                )
            except Exception:
                out = _sanitize_front_result_payload(out)

            return out



# ✅ packs_v1: fora do free_mode, ainda pode renderizar reply via Pack Engine quando o LLM devolver só o decider.
        try:
            # heurística leve: "como funciona" às vezes cai em OTHER; tratamos como WHAT_IS.
            _ut = (user_text or "").strip().lower()
            if intent == "OTHER" and ("como funciona" in _ut or "como que funciona" in _ut or "funciona" in _ut or "o que é" in _ut or "o que eh" in _ut):
                intent = "WHAT_IS"
                topic = "WHAT_IS"

            if not reply_text:
                _kb = None
                try:
                    if kb_snapshot and str(kb_snapshot).strip().startswith("{"):
                        _kb = json.loads(str(kb_snapshot))
                except Exception:
                    _kb = None

                if isinstance(_kb, dict) and (
                    _kb.get("value_packs_v1")
                    or _kb.get("answer_playbook_v1")
                    or _kb.get("kb_segments_v1")
                    or _kb.get("kb_subsegments_v1")
                    or _kb.get("kb_archetypes_v1")
                ):
                    try:
                        from services.pack_engine import render_pack_reply  # type: ignore
                        rend = render_pack_reply(
                            kb=_kb,
                            intent=intent or "WHAT_IS",
                            segment=((segment_key or effective_segment) or None),
                            pack_id=(pack_id or None),
                            render_mode=(render_mode or "short"),
                        ) or {}
                        if rend.get("ok") and str(rend.get("replyText") or "").strip():
                            reply_text = str(rend.get("replyText") or "").strip()
                            if not spoken_text and str(rend.get("spokenText") or "").strip():
                                spoken_text = str(rend.get("spokenText") or "").strip()
                            reply_source = "pack_engine"
                            pack_id = str(rend.get("packId") or pack_id or "").strip()
                            segment_key = str(rend.get("segmentKey") or segment_key or effective_segment or "").strip()
                            render_mode = str(rend.get("renderMode") or render_mode or "short").strip().lower()
                    except Exception:
                        pass

            # fallback humano (sem depender do Firestore) quando ainda ficar vazio
            if not reply_text and (intent in ("WHAT_IS", "OTHER")):
                reply_text = (
                    "O MEI Robô vira um atendente no seu WhatsApp: responde cliente, organiza agenda, orçamento e pedido sem te prender no celular. "
                    "Na prática: o cliente chama, o robô conduz o básico, confirma por escrito e adianta seu atendimento sem conversa perdida."
                )
                if question:
                    reply_text = f"{reply_text} {question}"

            # IA TOTAL: só compõe cena externa se o modelo NÃO respondeu.
            # Se reply_text já existe, ele é dono da fala.
            try:
                if next_step != 'SEND_LINK' and (not reply_text):
                    _seg = (segment_key or '').strip() or effective_segment or _infer_segment_from_text(user_text, kb_snapshot)
                    _pack = _pick_pack_for_intent(intent, pack_id)
                    if _pack and intent in ("WHAT_IS", "AGENDA", "SERVICOS", "PEDIDOS", "ORCAMENTO", "STATUS", "PROCESSO"):
                        practical_scene = ""
                        if _seg:
                            practical_scene = _compose_practical_scene(
                                kb_snapshot=kb_snapshot,
                                segment_key=_seg,
                                pack_id=_pack,
                            )

                        # Só usa microcena se já houver contexto claro
                        if practical_scene and intent in ("WHAT_IS", "PROCESSO"):
                            value_line = _extract_value_line(reply_text)
                            reply_text = _merge_value_and_scene(value_line, practical_scene, question)

                        if not practical_scene:
                            ms = _kb_get_micro_scene(kb_snapshot, _pack)
                            if ms:
                                practical_scene = ms if ms.lower().startswith("na prática:") else f"Na prática: {ms}"
                        # NÃO inventar microcena se não veio do contexto real
                        if not practical_scene:
                            practical_scene = ""

                        value_line = _extract_value_line(reply_text)
                        if not value_line:
                            value_line = "O MEI Robô atende seus clientes no WhatsApp e adianta seu trabalho sem te prender no celular"

                        ask_tail = ""
                        if not _seg:
                            ask_tail = question
                        elif not has_name and ai_turns >= 1:
                            ask_tail = question

                        if practical_scene:
                            reply_text = _merge_value_and_scene(value_line, practical_scene, ask_tail)
                        else:
                            reply_text = f"{value_line} {ask_tail}".strip()
                        if not spoken_text:
                            spoken_text = reply_text
                        else:
                            spoken_value_line = _extract_value_line(spoken_text)
                            if practical_scene:
                                spoken_text = _merge_value_and_scene(spoken_value_line, practical_scene, ask_tail)
                            else:
                                spoken_text = f"{spoken_value_line} {ask_tail}".strip()
                        reply_source = 'scene_composed'
            except Exception:
                pass
        except Exception:
            pass

        # Se a decisão foi clarificar, respeita a pergunta curta antes do fail-safe genérico.
        if not reply_text and needs_clarify == "yes" and clarify_q:
            if question and not effective_segment:
                reply_text = question
                if not spoken_text:
                    spoken_text = question
            else:
                reply_text = clarify_q
                if not spoken_text:
                    spoken_text = clarify_q
            reply_source = "front_clarify"

        (
            reply_text,
            spoken_text,
            topic,
            confidence,
            next_step,
            should_end,
            name_use,
        ) = _apply_non_empty_reply_guard(
            reply_text=reply_text,
            spoken_text=spoken_text,
            operational_contract=operational_contract,
            base_operational_contract=base_operational_contract,
            operational_reference=operational_reference,
            kb_context=kb_context,
            reference_example=reference_example,
            effective_segment=effective_segment,
            operational_family=operational_family,
            question=question,
            topic=topic,
            confidence=confidence,
            next_step=next_step,
            should_end=should_end,
            name_use=name_use,
        )

        # ✅ Produto: SEND_LINK = venda fechada (link-only, sem pergunta)
        try:
            if next_step == "SEND_LINK":
                should_end = True
                url = (os.getenv("FRONTEND_BASE") or "https://www.meirobo.com.br").strip()
                rt0 = (reply_text or "").strip()
                # IA Soberana: apenas garante que o link está presente, sem reescrever com frase pronta
                if ("http://" not in rt0) and ("https://" not in rt0):
                    if rt0:
                        qpos = rt0.find("?")
                        if qpos != -1:
                            rt0 = (rt0[: qpos]).rstrip()
                        if not rt0.endswith((".", "!", ":")):
                            rt0 += "."
                        reply_text = f"{rt0}\n{url}"
                    else:
                        reply_text = url
                st0 = (spoken_text or reply_text or "").strip()
                spoken_text = st0
        except Exception:
            pass

        # =========================================================
        # FINAL PIPELINE — POST-PROCESSAMENTO DO FRONT
        # =========================================================
        # Daqui para baixo o front prepara a superfície final da resposta.
        # Não deve decidir intenção, segmento, prompt ou KB.
        # A ordem dos blocos abaixo é sensível e deve ser preservada.
        # =========================================================

        front_reply_before_post = reply_text
        front_spoken_before_post = spoken_text

        # Corte final:
        # quando o contrato veio hidratado do KB, faz só limpeza leve.
        hydrated_contract = bool(
            (operational_contract if 'operational_contract' in locals() else {}).get("hydrated_from_docs")
            or (base_operational_contract if 'base_operational_contract' in locals() else {}).get("hydrated_from_docs")
            or kb_anchor_strong
        )

        reply_text = _sanitize_user_facing_reply(reply_text)
        spoken_text = _sanitize_user_facing_reply(spoken_text or reply_text)

        try:
            _contract_for_direct = (
                operational_contract if 'operational_contract' in locals() and isinstance(operational_contract, dict)
                else base_operational_contract if 'base_operational_contract' in locals() and isinstance(base_operational_contract, dict)
                else {}
            )

            _valid_real_scene = bool(
                str(response_mode or "").strip().upper() == "SCENE"
                and isinstance(_contract_for_direct, dict)
                and bool(_contract_for_direct.get("micro_scene_allowed"))
                and bool(_contract_for_direct.get("hydrated_from_docs"))
                and bool(_contract_for_direct.get("has_practical_scene"))
            )

            _valid_compact_fallback = bool(
                isinstance(_contract_for_direct, dict)
                and not bool(_contract_for_direct.get("hydrated_from_docs"))
                and bool(_contract_for_direct.get("global_pack_fallback"))
                and bool(
                    _contract_for_direct.get("runtime_compact_reply")
                    or _contract_for_direct.get("runtime_short_reply")
                )
            )

            _should_run_late_payload = True

            # Exceção segura:
            # Em DIRECT, quando a IA já entendeu o segmento mas não existe doc
            # estruturado hidratado, o fallback global do platform_kb pode ser
            # mais operacional do que a resposta livre curta da IA.
            #
            # Mantém os pilares:
            # - IA decide intenção/segmento/modo.
            # - Código cumpre usando material já presente no KB.
            # - Sem palavras-chave hardcoded.
            # - Sem nova chamada ao modelo.
            # - Sem afetar SCENE com doc estruturado.
            _allow_direct_global_fallback_payload = bool(
                str(response_mode or "").strip().upper() == "DIRECT"
                and isinstance(_contract_for_direct, dict)
                and not bool(_contract_for_direct.get("hydrated_from_docs"))
                and bool(_contract_for_direct.get("global_pack_fallback"))
                and bool(_contract_for_direct.get("platform_segment_key"))
                and bool(
                    _contract_for_direct.get("runtime_compact_reply")
                    or _contract_for_direct.get("runtime_short_reply")
                )
                and len(str(reply_text or "").strip()) < 260
            )

            if (
                str(response_mode or "").strip().upper() == "DIRECT"
                and bool(ia_accepted)
                and str(reply_text or "").strip()
                and not _allow_direct_global_fallback_payload
            ):
                _should_run_late_payload = False

            if (_valid_real_scene or _valid_compact_fallback) and _should_run_late_payload:
                use_human_wrapper = bool(
                    str(response_mode or "").strip().upper() == "DIRECT"
                    and _contract_for_direct.get("global_pack_fallback")
                    and not _contract_for_direct.get("hydrated_from_docs")
                )

                _direct_payload = _build_direct_scene_payload(
                    _contract_for_direct,
                    user_text=user_text,
                    segment_hint=(
                        _contract_for_direct.get("platform_segment_key")
                        or segment_hint
                        or ""
                    ),
                    name_hint=name_hint,
                    state_summary=state_summary,
                    intro_hint=reply_text,
                    use_human_wrapper=use_human_wrapper,
                )
                if _direct_payload:
                    reply_text = _direct_payload
                    spoken_text = _direct_payload
                    reply_source = "front_direct_scene"

            _source_for_exit = str(reply_source or "").strip()
            _raw_scene_exit = bool(
                has_real_operational_context
                and str(response_mode or "").strip().upper() == "SCENE"
                and isinstance(_contract_for_direct, dict)
                and bool(_contract_for_direct.get("hydrated_from_docs"))
                and bool(_contract_for_direct.get("has_practical_scene"))
                and str(reply_text or "").strip()
                and (
                    _source_for_exit in ("front_fallback_structural", "front_direct_scene", "front_resolved_best_effort")
                    or bool(re.search(r"\s(?:→|->|=>|\|)\s", str(reply_text or "")))
                    or _looks_like_structural_scene_payload(reply_text)
                )
            )

            if _raw_scene_exit:
                _upgraded_exit = _upgrade_operational_reply_with_model(
                    base_text=str(reply_text or "").strip(),
                    operational_reference=str(operational_reference or "").strip(),
                    reference_example=str(reference_example or "").strip(),
                    contract=_contract_for_direct if isinstance(_contract_for_direct, dict) else {},
                )
                if _upgraded_exit and not _looks_like_structural_scene_payload(_upgraded_exit):
                    reply_text = _upgraded_exit
                    spoken_text = _upgraded_exit
                    reply_source = "front_operational_upgrade"
                else:
                    _humanized_exit = _humanize_scene_flow(reply_text)
                    if (
                        _humanized_exit
                        and _humanized_exit != str(reply_text or "").strip()
                        and not _looks_like_structural_scene_payload(_humanized_exit)
                    ):
                        reply_text = _humanized_exit
                        spoken_text = _humanized_exit
        except Exception:
            pass

        try:
            if ai_turns == 0 and is_lead and not has_name and str(next_step or "").strip().upper() != "SEND_LINK":
                if isinstance(kb_context, dict):
                    kb_context["needs_name_discovery"] = True

                if reply_text and "?" not in reply_text:
                    reply_text = reply_text.rstrip(" .") + ". Como posso te chamar?"
                    spoken_text = reply_text
                    name_use = "clarify"
        except Exception:
            pass

        if not hydrated_contract:
            (
                reply_text,
                spoken_text,
                reply_size_policy,
                spoken_size_policy,
            ) = _apply_final_reply_size_policy(
                reply_text=reply_text,
                spoken_text=spoken_text,
                reply_size_policy=reply_size_policy,
                reply_source=reply_source,
                response_mode=response_mode,
                topic=topic,
                operational_contract=operational_contract,
            )

        # Regra de produto: perguntas foram abolidas, salvo exceções controladas.
        if reply_text and ("?" in reply_text):
            try:
                if not _should_allow_question(
                    user_text=user_text,
                    kb_context=kb_context if isinstance(kb_context, dict) else {},
                    reply_text=reply_text,
                    understanding={
                        **(understanding if isinstance(understanding, dict) else {}),
                        "response_mode": response_mode,
                    },
                    decider={
                        **(decider if isinstance(decider, dict) else {}),
                        "response_mode": response_mode,
                    },
                ):
                    reply_text = _strip_trailing_question(reply_text)
                    try:
                        debug_info = debug_info if isinstance(debug_info, dict) else {}
                        debug_info["question_stripped_by_policy"] = True
                    except Exception:
                        pass
            except Exception:
                pass

        if spoken_text and ("?" in spoken_text):
            try:
                if not _should_allow_question(
                    user_text=user_text,
                    kb_context=kb_context if isinstance(kb_context, dict) else {},
                    reply_text=spoken_text,
                    understanding={
                        **(understanding if isinstance(understanding, dict) else {}),
                        "response_mode": response_mode,
                    },
                    decider={
                        **(decider if isinstance(decider, dict) else {}),
                        "response_mode": response_mode,
                    },
                ):
                    spoken_text = _strip_trailing_question(spoken_text)
            except Exception:
                pass



        # =========================================================
        # FINAL SURFACE POLISH — SANITIZE / GUARDRAILS / SPOKEN SYNC
        # =========================================================
        reply_text, spoken_text = _apply_final_surface_polish(
            reply_text=reply_text,
            spoken_text=spoken_text,
            topic=topic,
            confidence=confidence,
            user_text=user_text,
            kb_context=kb_context if isinstance(kb_context, dict) else {},
            kb_snapshot=kb_snapshot,
            free_mode=free_mode,
            apply_sales_guardrails=apply_sales_guardrails,
            operational_contract=operational_contract if 'operational_contract' in locals() else {},
            base_operational_contract=base_operational_contract if 'base_operational_contract' in locals() else {},
        )


        # =========================================================
        # FINAL GUARD — impedir saída vazia ou fallback burro
        # =========================================================
        try:
            _rt = str(reply_text or "").strip()
            allow_final_kb_show = bool(
                (operational_contract if 'operational_contract' in locals() else {}).get("micro_scene_allowed")
                or (base_operational_contract if 'base_operational_contract' in locals() else {}).get("micro_scene_allowed")
            )

            if not _rt or len(_rt) < 40:
                if allow_final_kb_show and operational_contract:
                    if not operational_reference:
                        operational_reference = ""
                    forced = _build_kb_show_reply(
                        kb_context=kb_context if isinstance(kb_context, dict) else {},
                        operational_reference="",
                        reference_example=reference_example,
                        effective_segment=effective_segment,
                        operational_family=operational_family,
                        contract=operational_contract,
                    )
                    if forced and len(forced.strip()) >= 40:
                        reply_text = forced
                elif allow_final_kb_show and base_operational_contract:
                    if not operational_reference:
                        operational_reference = ""
                    forced = _build_kb_show_reply(
                        kb_context=kb_context if isinstance(kb_context, dict) else {},
                        operational_reference="",
                        reference_example=reference_example,
                        effective_segment=effective_segment,
                        operational_family=operational_family,
                        contract=base_operational_contract,
                    )
                    if forced and len(forced.strip()) >= 40:
                        reply_text = forced
        except Exception:
            pass

        # 🧠 restaura melhor versão se degradou no meio do fluxo
        reply_text = _restore_final_candidate_if_degraded(
            reply_text=reply_text,
            final_candidate=_final_candidate,
        )

        # =========================================================
        # RESPONSE MODE CONTROL PIPELINE
        # =========================================================
        # Responsável por:
        # - acabamento estrutural por modo
        # - sincronização final de superfície
        # - DISCOVERY identity guard
        #
        # NÃO deve:
        # - decidir intenção
        # - montar KB
        # - gerar microcena
        # - alterar política
        #
        # response_mode:
        # - DIRECT
        # - DISCOVERY
        # - SCENE
        # - CLOSING
        # =========================================================
        try:
            response_mode = _normalize_response_mode(response_mode) or "DIRECT"

            reply_text, spoken_text = _apply_response_mode_surface(
                response_mode=response_mode,
                reply_text=reply_text,
                spoken_text=spoken_text,
            )

            if response_mode == "DISCOVERY":
                (
                    needs_clarify,
                    name_use,
                ) = _apply_discovery_mode_identity_guard(
                    reply_text=reply_text,
                    has_name=has_name,
                    segment_discovery_resolved=segment_discovery_resolved,
                    needs_clarify=needs_clarify,
                    name_use=name_use,
                )
        except Exception:
            pass

        # 🔒 última garantia: não sair com resposta fraca quando há contexto
        try:
            if not reply_text or len(reply_text.strip()) < 40:
                allow_final_kb_show = bool(
                    (operational_contract if 'operational_contract' in locals() else {}).get("micro_scene_allowed")
                    or (base_operational_contract if 'base_operational_contract' in locals() else {}).get("micro_scene_allowed")
                )

                forced = ""
                if allow_final_kb_show:
                    forced = (
                        kb_show_reply_seed
                        or _build_kb_show_reply(
                            kb_context=kb_context if isinstance(kb_context, dict) else {},
                            operational_reference="",
                            reference_example=reference_example,
                            effective_segment=effective_segment,
                            operational_family=operational_family,
                            contract=operational_contract if 'operational_contract' in locals() else (base_operational_contract if 'base_operational_contract' in locals() else {}),
                        )
                    )

                if not forced and allow_scene_runtime:
                    forced = _build_kb_anchor_reply(
                        operational_reference="",
                        reference_example=reference_example,
                        clarify_q="",
                        contract=operational_contract if 'operational_contract' in locals() else (base_operational_contract if 'base_operational_contract' in locals() else {}),
                    )

                if forced and len(forced.strip()) >= 40:
                    reply_text = forced
                    spoken_text = forced
        except Exception:
            pass

        # ----------------------------------------------------------
        # GUARDA FINAL ABSOLUTA (POST-GENERATION ENFORCEMENT)
        # ----------------------------------------------------------
        if response_mode == "DISCOVERY":
            missing_name = not bool(has_name)

            if missing_name:
                if not _has_question(reply_text):
                    needs_clarify = "yes"

                name_use = "clarify"

        spoken_text = str(spoken_text or reply_text or "").strip()

        # 🔒 Garantir no máximo 1 pergunta válida (policy)
        try:
            if "?" in reply_text:
                parts = reply_text.split("?")
                if len(parts) > 2:
                    reply_text = parts[0].strip() + "?"
                    spoken_text = reply_text
        except Exception:
            pass

        # Blindagem final antes de montar o retorno:
        # se o texto ainda for o envelope JSON, entrega só o replyText interno.
        try:
            reply_text = _unwrap_front_json_envelope(reply_text)
            spoken_text = _unwrap_front_json_envelope(spoken_text or reply_text) or reply_text
        except Exception:
            pass


        if ai_turns == 0 and reply_text:
            if not has_name:
                reply_text = "Obrigado pelo contato! " + reply_text

        if FRONT_TRACE_ENABLED:
            logging.info({
                "mode": response_mode,
                "has_name": has_name,
                "segment": segment_for_prompt,
                "clarify": needs_clarify
            })

        structured_assembly_result: Dict[str, Any] = {}
        try:
            structured_assembly_result = _front_build_structured_assembly_reply(
                current_reply=reply_text,
                real_kb_docs=real_kb_docs if 'real_kb_docs' in locals() else {},
                kb_snapshot_obj=kb_snapshot_obj if isinstance(kb_snapshot_obj, dict) else {},
                platform_segment_profile=platform_segment_profile if isinstance(platform_segment_profile, dict) else {},
                selected_pack_id=selected_pack_id if 'selected_pack_id' in locals() else "",
                response_mode=response_mode,
                next_step=next_step,
                ai_turns=ai_turns,
                lead_name=(
                    _front_sanitize_lead_name_candidate(
                        inferred_lead_name or name_hint,
                        segment_refs=[
                            segment_hint,
                            inferred_lead_segment_raw,
                            inferred_lead_segment,
                        ],
                    )
                    if has_name else ""
                ),
                lead_segment_raw=inferred_lead_segment_raw or inferred_lead_segment or segment_hint,
                question_type=question_type,
            )

            if structured_assembly_result and structured_assembly_result.get("replyText"):
                _reply_source_before_structured_assembly = str(reply_source or "").strip()
                reply_text = str(structured_assembly_result.get("replyText") or "").strip()
                spoken_text = str(structured_assembly_result.get("spokenText") or reply_text).strip()
                reply_source = "front_structured_python_assembly"
                try:
                    logging.info(
                        "[STRUCTURED_ASSEMBLY_OWNERSHIP] phase=common_path previous_source=%s final_source=%s mode=%s question_type=%s",
                        _reply_source_before_structured_assembly,
                        str(reply_source or "").strip(),
                        str(response_mode or "").strip().upper(),
                        str(question_type or "").strip().lower(),
                    )
                except Exception:
                    pass
        except Exception:
            structured_assembly_result = {}

        try:
            reply_text = _humanize_reply_with_lead_context(
                reply=reply_text,
                lead_name=(
                    _front_sanitize_lead_name_candidate(
                        inferred_lead_name or name_hint,
                        segment_refs=[
                            segment_hint,
                            inferred_lead_segment_raw,
                            inferred_lead_segment,
                        ],
                    )
                    if has_name else ""
                ),
                lead_segment_raw=inferred_lead_segment_raw or inferred_lead_segment or segment_hint,
            )
            spoken_text = reply_text
        except Exception:
            pass

        try:
            reply_text = _front_remove_unsafe_nominal_opening(reply_text, has_name=has_name)
            spoken_text = _front_remove_unsafe_nominal_opening(spoken_text or reply_text, has_name=has_name)
        except Exception:
            pass


        try:
            reply_text, reply_size_policy = (
                _preserve_technical_direct_reply_size(
                    reply_text,
                    reply_size_policy,
                    reply_source=reply_source,
                    response_mode=response_mode,
                    topic=topic,
                    operational_contract=operational_contract,
                )
            )
        except Exception:
            pass

        # -----------------------------------------------------------------
        # PRESERVAÇÃO FINAL DO TEXTO JÁ VALIDADO
        #
        # Diagnóstico confirmado em produção:
        # - IA_FINAL_DECISION accepted=True len≈855
        # - FRONT_STRUCTURED_FINAL_TRIM reply_len≈819
        # - WA_BOT recebe apenas ≈656
        #
        # Portanto, algum passo entre o trim técnico e a montagem final do
        # objeto de saída ainda substitui ou reprocessa o texto.
        #
        # Neste ponto, imediatamente antes do retorno efetivo, forçamos o uso
        # do texto já preparado em reply_text/spoken_text e aplicamos apenas
        # um corte seguro em limite de palavra.
        #
        # Regras preservadas:
        # - não altera prompts;
        # - não libera microcena;
        # - não afeta áudio;
        # - atua somente em DIRECT técnico vindo da platform_kb.
        # -----------------------------------------------------------------
        try:
            _contract = (
                operational_contract
                if isinstance(operational_contract, dict)
                else {}
            )

            _source = str(reply_source or "").strip()
            _mode = str(response_mode or "").strip().upper()
            _topic = str(topic or "").strip().upper()

            _is_platform_runtime = bool(
                _contract.get("hydrated_from_platform_kb")
                or _contract.get("global_pack_fallback")
            )

            _is_technical_direct = bool(
                _source == "front_structured_python_assembly"
                and _mode == "DIRECT"
                and _topic in (
                    "AGENDA",
                    "SERVICOS",
                    "PEDIDOS",
                    "STATUS",
                    "PROCESSO",
                    "ORCAMENTO",
                )
                and _is_platform_runtime
            )

            if _is_technical_direct:
                reply_text = _front_finalize_reply_surface(
                    reply_text,
                    has_name=bool(has_name),
                    max_chars=780,
                    ensure_punctuation=False,
                )

                spoken_text = _front_finalize_reply_surface(
                    spoken_text or reply_text,
                    has_name=bool(has_name),
                    max_chars=780,
                    ensure_punctuation=False,
                )

                try:
                    logging.info(
                        "[FINAL_REPLY_OVERRIDE] "
                        "topic=%s source=%s reply_len=%s spoken_len=%s",
                        _topic,
                        _source,
                        len(reply_text or ""),
                        len(spoken_text or ""),
                    )
                except Exception:
                    pass

                # Se o segmento foi declarado no turno atual, permita que ele
                # saia no payload como segmento, nunca como nome. Isso ajuda o
                # próximo turno a manter contexto sem criar vocativo indevido.
                try:
                    _declared_segment_for_payload = str(
                        segment_hint
                        or inferred_lead_segment_raw
                        or inferred_lead_segment
                        or ""
                    ).strip()
                    if _declared_segment_for_payload:
                        out["leadSegmentRaw"] = _declared_segment_for_payload
                        out["segmentHint"] = _declared_segment_for_payload
                        _u = out.get("understanding")
                        if isinstance(_u, dict):
                            _u["leadSegmentRaw"] = _declared_segment_for_payload
                            _u["segmentHint"] = _declared_segment_for_payload
                except Exception:
                    pass
        except Exception:
            pass

        out = {
            "response_mode": response_mode,
            "replyText": reply_text,
            "spokenText": spoken_text,
            "understanding": {
                "topic": topic,
                # Harmoniza com o resto do pipeline (sales_lead/outbox)
                "intent": topic,
                "confidence": confidence,
                "needsClarify": needs_clarify,
                "clarifyQuestion": clarify_q,
                "response_mode": response_mode,
                "leadSegmentRaw": inferred_lead_segment_raw,
            },
            "nextStep": next_step,
            "leadName": (
                _front_sanitize_lead_name_candidate(
                    name_hint or current_turn_lead_name or inferred_lead_name,
                    segment_refs=[
                        segment_hint,
                        inferred_lead_segment_raw,
                        inferred_lead_segment,
                    ],
                )
                if has_name else ""
            ),
            "segmentHint": segment_hint,
            "leadSegmentRaw": inferred_lead_segment_raw,
            "shouldEnd": should_end,
            "nameUse": name_use,
            # ✅ Regra canônica: texto só quando for SEND_LINK (link copiável).
            # Caso contrário, o worker decide o canal (entra áudio -> sai áudio).
            "prefersText": (next_step == "SEND_LINK"),
            # Auditoria: quem respondeu
            "replySource": (reply_source or "front"),
            # Probe leve do snapshot (ajuda a ver se o front "passou fome")
            "kbSnapshotSizeChars": len(kb_snapshot or ""),
            # Telemetria de custo (best-effort)
            "tokenUsage": token_usage,
            "replySizePolicy": reply_size_policy if isinstance(reply_size_policy, dict) else {},
        }

        # Mantém o decider no retorno quando existir (p/ roteamento/auditoria downstream).
        if decider_only and isinstance(decider, dict):
            out["decider"] = decider

        try:
            am = out.get("aiMeta") or {}
            if not isinstance(am, dict):
                am = {}
            rsp = reply_size_policy if isinstance(reply_size_policy, dict) else {}
            am["replySizePolicy"] = str(rsp.get("label") or "")
            am["replyTargetChars"] = int(rsp.get("target_chars") or 0)
            am["replyMaxChars"] = int(rsp.get("max_chars") or 0)
            am["replyIsAudioPolicy"] = bool(rsp.get("is_audio"))
            am["replyTechnicalNeed"] = bool(rsp.get("technical_need"))
            out["aiMeta"] = am
        except Exception:
            pass

        # -----------------------------
        # Observabilidade leve
        # -----------------------------
        logging.info(
            "[CONVERSATIONAL_FRONT] ai_turns=%s topic=%s confidence=%s nextStep=%s shouldEnd=%s kbChars=%s tok=%s",
            ai_turns,
            topic,
            confidence,
            next_step,
            should_end,
            len(kb_snapshot or ""),
            token_usage or {},
        )

        if not reply_text:
            reply_text = question or "Me conta um pouco melhor o teu cenário."
            should_end = False
            out["replyText"] = reply_text
            out["spokenText"] = reply_text
            out["shouldEnd"] = should_end

        # ------------------------------------------------------------
        # FRONT FAILSAFE
        # garante que o conversational_front nunca devolva reply vazio
        # evitando que o WA_BOT caia no box_decider
        # ------------------------------------------------------------
        if (not reply_text) or (not str(reply_text).strip()) or _looks_like_technical_output(reply_text):
            logging.warning(
                "[CONVERSATIONAL_FRONT][FAILSAFE_REPLY] reply vazio detectado, usando pergunta de descoberta"
            )

            reply_text = (
                question
                or clarify_q
                or "Me conta um pouco melhor o teu cenário."
            )

            should_end = False
            next_step = "DISCOVERY"
            out["replyText"] = reply_text
            out["spokenText"] = reply_text
            out["shouldEnd"] = should_end
            out["nextStep"] = next_step

        try:
            if ai_turns == 0:
                txt = str(out.get("replyText") or reply_text or "").strip()
                greetings = (
                    "obrigado",
                    "obrigada",
                    "olá",
                    "ola",
                    "oi",
                    "tudo bem",
                    "maravilha",
                    "perfeito",
                    "entendi",
                    "certo",
                )
                if txt and not txt.lower().startswith(greetings):
                    txt = txt[0].upper() + txt[1:]
                    reply_text = f"Obrigado pelo contato! {txt}"
                    spoken_text = reply_text
                    out["replyText"] = reply_text
                    out["spokenText"] = spoken_text
        except Exception:
            pass


        # Última trava antes de devolver ao wa_bot.py.
        # Nunca permitir envelope JSON como mensagem final.
        try:
            final_reply = _unwrap_front_json_envelope(out.get("replyText") or reply_text)
            final_spoken = _unwrap_front_json_envelope(out.get("spokenText") or spoken_text or final_reply)

            if final_reply:
                reply_text = final_reply
                spoken_text = final_spoken or final_reply
                out["replyText"] = reply_text
                out["spokenText"] = spoken_text
            elif _looks_like_technical_output(out.get("replyText") or reply_text):
                reply_text = question or "Me conta um pouco melhor o teu cenário."
                spoken_text = reply_text
                out["replyText"] = reply_text
                out["spokenText"] = spoken_text
                out["shouldEnd"] = False
        except Exception:
            pass

        result = _sanitize_front_result_payload(out)

        # Blindagem final:
        # Garante que o objeto retornado carregue exatamente os textos já
        # sanitizados e validados no pipeline, impedindo que qualquer envelope
        # JSON bruto anteriormente armazenado em `result` seja propagado para
        # persistência ou envio ao WhatsApp.
        try:
            if isinstance(result, dict):
                final_reply = _unwrap_front_json_envelope(result.get("replyText") or reply_text)
                final_spoken = _unwrap_front_json_envelope(result.get("spokenText") or spoken_text or final_reply)

                if final_reply:
                    result["replyText"] = final_reply
                    result["spokenText"] = final_spoken or final_reply
        except Exception:
            pass

        return result

    except Exception as e:
        # Fail-safe absoluto: nunca quebrar o fluxo
        logging.exception("[CONVERSATIONAL_FRONT] erro, fallback silencioso: %s | user_text=%r", e, user_text)

        if free_mode:
            kb_fallback = ""
            try:
                kb_fallback = (
                    _build_kb_show_reply(
                        kb_context=kb_context if isinstance(kb_context, dict) else {},
                        operational_reference="" if 'operational_reference' in locals() else "",
                        reference_example=reference_example if 'reference_example' in locals() else "",
                        effective_segment=effective_segment if 'effective_segment' in locals() else "",
                        operational_family=operational_family if 'operational_family' in locals() else "",
                        contract=operational_contract if 'operational_contract' in locals() else (base_operational_contract if 'base_operational_contract' in locals() else {}),
                    )
                    or _build_kb_anchor_reply(
                        operational_reference="" if 'operational_reference' in locals() else "",
                        reference_example=reference_example if 'reference_example' in locals() else "",
                        clarify_q=question if 'question' in locals() else "",
                        contract=operational_contract if 'operational_contract' in locals() else (base_operational_contract if 'base_operational_contract' in locals() else {}),
                    )
                )
            except Exception:
                kb_fallback = ""

            if kb_fallback:
                reply_text = kb_fallback
            elif question:
                reply_text = question
            else:
                reply_text = (
                    question
                    or clarify_q
                    or "Me conta um pouco melhor o teu cenário."
                )
            if _looks_like_technical_output(reply_text):
                reply_text = (
                    question
                    or clarify_q
                    or "Me conta um pouco melhor o teu cenário."
                )
            spoken_text = reply_text
        else:
            reply_text = "Me conta um pouquinho melhor o que você quer resolver?"
            spoken_text = reply_text

        error_out = {
            "replyText": reply_text,
            "spokenText": spoken_text,
            "understanding": {
                "topic": "OTHER",
                "confidence": "low",
            },
            "nextStep": "NONE",
            "shouldEnd": False,
            "nameUse": "clarify",
            # ✅ Em erro, NÃO forçar texto: deixa o worker decidir canal (entra áudio -> sai áudio).
            "prefersText": False,
            "replySource": "front_error",
            "kbSnapshotSizeChars": len((kb_snapshot or "")),
            "tokenUsage": {},
        }
