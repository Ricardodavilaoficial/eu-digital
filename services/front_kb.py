"""
Camada de KB do Conversational Front.

Este módulo será usado para isolar gradualmente funções relacionadas a:
- leitura/parsing de kb_snapshot;
- runtime de platform_kb;
- lookup de documentos operacionais;
- construção de contratos operacionais.

Regra desta fase:
- não alterar comportamento;
- não chamar rede;
- não acessar banco;
- mover apenas funções com dependências explícitas;
- preservar equivalência funcional.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict


def _try_parse_kb_json(kb_snapshot: str) -> Dict[str, Any] | None:
    try:
        raw = str(kb_snapshot or "").strip()
        if raw and (raw.startswith("{") or raw.startswith("[")):
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
    except Exception:
        return None
    return None


def _compose_pack_runtime_short_reply(material: dict) -> str:
    try:
        if not isinstance(material, dict):
            return ""
        value = str(material.get("value_one_liner") or "").strip()
        bridge = str(material.get("bridge_line") or "").strip()
        scene = str(material.get("micro_scene_conversational") or material.get("micro_scene") or "").strip()
        parts = []
        if value:
            parts.append(value.rstrip(".!?") + ".")
        if bridge:
            parts.append(bridge.rstrip(":") + ":")
        if scene:
            parts.append(scene.rstrip(".!?") + ".")
        return " ".join(parts).strip()
    except Exception:
        return ""


def _compose_pack_runtime_compact_reply(material: dict) -> str:
    """
    Versão compacta para fallback global sem contrato operacional real.
    Usa valor + ponte + microcena curta; evita cena conversacional longa/runtime_long.
    """
    try:
        if not isinstance(material, dict):
            return ""
        value = str(material.get("value_one_liner") or "").strip()
        bridge = str(material.get("bridge_line") or "").strip()
        scene = str(material.get("micro_scene") or "").strip()
        parts = []
        if value:
            parts.append(value.rstrip(".!?") + ".")
        if bridge:
            parts.append(bridge.rstrip(":") + ":")
        if scene:
            parts.append(scene.rstrip(".!?") + ".")

        compact_reply = str(" ".join(parts).strip() or "").strip()

        if compact_reply:
            compact_reply = re.sub(
                r'(?i)\bna prática[,:\s]*',
                '',
                compact_reply,
            ).strip()

            compact_reply = re.sub(
                r'(?i)\bfunciona assim[,:\s]*',
                '',
                compact_reply,
            ).strip()

            compact_reply = re.sub(
                r'\s{2,}',
                ' ',
                compact_reply,
            ).strip()

            compact_reply = compact_reply.replace(
                'Cliente pede horário →',
                'O cliente chama no WhatsApp e o robô'
            )

            compact_reply = compact_reply.replace(
                'o robô oferece só opções válidas',
                'consulta sua agenda e oferece os horários disponíveis'
            )

            compact_reply = compact_reply.replace(
                'confirma por escrito',
                'confirma tudo no WhatsApp'
            )

            compact_reply = compact_reply.replace(
                'fica no painel + resumo 06:30',
                'registra no painel da conta e organiza os atendimentos do dia'
            )

        return compact_reply
    except Exception:
        return ""


def _platform_apply_slots(text: str, pack: Dict[str, Any], tokens: Dict[str, Any]) -> str:
    """
    Aplica slots vindos do próprio platform_kb.
    Não decide segmento, não cria frase e não contém conteúdo comercial próprio.
    Apenas troca {{campo}} pelos valores/defaults cadastrados no banco.
    """
    try:
        out = str(text or "").strip()
        if not out:
            return ""

        values: Dict[str, str] = {}

        segment_slots = (pack or {}).get("segment_slots") or {}
        if isinstance(segment_slots, dict):
            for key, spec in segment_slots.items():
                if isinstance(spec, dict):
                    default_value = str(spec.get("default") or "").strip()
                    if default_value:
                        values[str(key)] = default_value

        if isinstance(tokens, dict):
            for key, value in tokens.items():
                if isinstance(value, (str, int, float)):
                    v = str(value or "").strip()
                    if v:
                        values[str(key)] = v

        for key, value in values.items():
            out = out.replace("{{" + str(key) + "}}", str(value))

        out = re.sub(r"\s{2,}", " ", out).strip()
        return out
    except Exception:
        return str(text or "").strip()

