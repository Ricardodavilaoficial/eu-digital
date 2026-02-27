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
from typing import Dict, Any
import json

try:
    from services.pack_engine import render_pack_reply  # type: ignore
except Exception:
    render_pack_reply = None  # type: ignore

import os
try:
    # SDK novo (openai>=1.x)
    from openai import OpenAI  # type: ignore
    _HAS_OPENAI_CLIENT = True
except Exception:
    OpenAI = None  # type: ignore
    _HAS_OPENAI_CLIENT = False
import openai  # compat SDK antigo

# -----------------------------
# Configuração fixa (produto)
# -----------------------------
MODEL = "gpt-4o-mini"
TEMPERATURE = 0.5
FRONT_ANSWER_MAX_TOKENS = int(os.getenv("FRONT_ANSWER_MAX_TOKENS", "260") or 260)  # saída do modelo
FRONT_KB_MAX_CHARS = int(os.getenv("FRONT_KB_MAX_CHARS", "2500") or 2500)          # entrada (snapshot)
FRONT_REPLY_MAX_CHARS = int(os.getenv("FRONT_REPLY_MAX_CHARS", "900") or 900)      # corte final (anti-textão)

_client = OpenAI() if _HAS_OPENAI_CLIENT else None
# -----------------------------
# Enum fechado de tópicos
# -----------------------------
TOPICS = {
    "AGENDA",
    "PRECO",
    "ORCAMENTO",
    "VOZ",
    "SOCIAL",
    "OTHER",
}

# -----------------------------
# Prompt base (alma do vendedor)
# -----------------------------
SYSTEM_PROMPT = """
Você é o MEI Robô em modo VENDAS institucional.

Seu trabalho aqui é DECIDIR (e não palestrar):
- Entender a intenção do lead.
- Escolher QUAL "perfil de valor" se aplica (agenda / serviços / pedidos / status).
- Sugerir se é caso de perguntar algo (no máximo 1 pergunta) ou encerrar.

⚠️ IMPORTANTE
- No modo packs_v1, você NÃO deve escrever a resposta final (replyText/spokenText) — isso será renderizado de forma determinística pelo backend.
- Exceção: se a intenção for SEND_LINK (lead pediu para assinar / link), você PODE devolver replyText/spokenText curto.

Saída: responda APENAS em JSON, sem texto fora, sem markdown.
Schema:
{
  "intent": "WHAT_IS|PRICE|PROCESS|ACTIVATE|SCHEDULE|SERVICES|ORDERS|STATUS|OTHER",
  "confidence": "low|medium|high",
  "needsClarify": "yes|no",
  "clarifyQuestion": "string (se needsClarify=yes, máx 1 pergunta, sem textão)",
  "packProfile": "by_schedule|by_orders|by_status|by_tech_service|generic",
  "renderMode": "short|long",
  "segmentKey": "string (opcional; só se tiver boa certeza)",
  "segmentConfidence": "low|medium|high",
  "shouldAskSegment": "yes|no",
  "nextStep": "NONE|SEND_LINK",
  "shouldEnd": true|false
}

Regras IMPORTANTES:
- Nunca mais de 1 pergunta.
- Se a pergunta do lead for objetiva, classifique o intent corretamente (ex.: prazo/ativação nunca é WHAT_IS).
- Só sugerir segmentKey se estiver realmente seguro; se não, use shouldAskSegment=yes apenas quando for necessário para dar exemplo certeiro.
- renderMode: short por padrão; long só quando: lead pediu para explicar melhor / lead muito engajado / primeira vez que identificou segmento.
"""

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

    last_intent = str(state_summary.get("last_intent") or "").strip().upper()
    last_user_goal = str(state_summary.get("last_user_goal") or "").strip()
    name_hint = str(state_summary.get("name_hint") or "").strip()
    is_lead = bool(state_summary.get("is_lead") or False)
    kb_snapshot = (kb_snapshot or "").strip()
    if kb_snapshot:
        kb_snapshot = kb_snapshot[:FRONT_KB_MAX_CHARS]

    # Sinal simples para o modelo: já sabemos o nome?
    has_name = bool(name_hint)

    # ----------------------------------------------------------
    # FAST-PATH: intenção explícita de ASSINAR / LINK / ATIVAR
    # Regra: se o usuário já quer assinar ou pede o link, não faça perguntas.
    # ----------------------------------------------------------
    try:
        import re
        ut_low = (user_text or "").strip().lower()
        wants_link = bool(re.search(r"\b(link|site|assinar|assinatura|contratar|contrato|ativar|ativação|ativacao|quero\s+assinar|como\s+assina|como\s+assinar|onde\s+assina|onde\s+assinar|manda\s+o\s+link|me\s+manda\s+o\s+link|me\s+manda\s+o\s+site)\b", ut_low))
        if wants_link:
            base = (os.getenv("FRONTEND_BASE") or "https://www.meirobo.com.br").strip()
            # Texto: com URL copiável
            reply_text = f"Perfeito. Aqui está o link pra assinar agora:\n{base}"
            # Áudio: humanizado, sem falar URL; usa nome se já existir
            if has_name:
                spoken_text = f"Fechado, {name_hint}. Te enviei o link no texto agora pra você copiar e assinar."
            else:
                spoken_text = "Fechado. Te enviei o link no texto agora pra você copiar e assinar."
            return {
                "replyText": reply_text[:FRONT_REPLY_MAX_CHARS].rstrip(),
                "spokenText": spoken_text[:FRONT_REPLY_MAX_CHARS].rstrip(),
                "understanding": {"topic": "ORCAMENTO", "intent": "ORCAMENTO", "confidence": "high"},
                "nextStep": "SEND_LINK",
                "shouldEnd": True,
                "nameUse": "none",
                "prefersText": True,
                "replySource": "front",
                "kbSnapshotSizeChars": len(kb_snapshot or ""),
                "tokenUsage": {},
            }
    except Exception:
        pass


    # Mensagens curtas para controle de custo
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"""
Mensagem do usuário:
\"\"\"{user_text}\"\"\"

Turno atual: {ai_turns}

Contexto curto (se existir; não invente):
- is_lead: {"true" if is_lead else "false"}
- has_name: {"true" if has_name else "false"}
- last_intent: {last_intent or "NONE"}
- last_user_goal: {last_user_goal or "NONE"}

KB Snapshot (fonte da verdade, compacto; não invente fora disso):
\"\"\"
{kb_snapshot}
\"\"\"

Responda em JSON ESTRITO (sem texto fora do JSON) no formato:

{{
  "replyText": "...",
  "spokenText": "... (opcional)",
  "understanding": {{
    "topic": "AGENDA|SERVICOS|PEDIDOS|STATUS|PRECO|PROCESSO|ATIVAR|OTHER",
    "confidence": "high|medium|low"
  }},
  "decider": {{
    "intent": "WHAT_IS|AGENDA|SERVICOS|PEDIDOS|STATUS|PRECO|PROCESSO|ATIVAR|OTHER",
    "segment": "string (opcional)",
    "packId": "PACK_A_AGENDA|PACK_B_SERVICOS|PACK_C_PEDIDOS|PACK_D_STATUS (opcional)",
    "renderMode": "short|long",
    "questionType": "none|clarify|name|segment|link_permission"
  }},
  "nextStep": "NONE|SEND_LINK",
  "shouldEnd": true|false,
  "nameUse": "none|greet|empathy|clarify"
}}
""",
        },
    ]

    try:
        # ----------------------------------------------------------
        # Chamada ao modelo (compat: SDK novo e antigo)
        # ----------------------------------------------------------
        if _HAS_OPENAI_CLIENT and _client is not None:
            resp = _client.chat.completions.create(
                model=MODEL,
                temperature=TEMPERATURE,
                max_tokens=FRONT_ANSWER_MAX_TOKENS,
                messages=messages,
            )
            raw = resp.choices[0].message.content.strip()
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
                max_tokens=FRONT_ANSWER_MAX_TOKENS,
                messages=messages,
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
        # -----------------------------
        # Parse seguro do JSON
        # -----------------------------
        import json
        import re

        # Alguns modelos devolvem JSON com texto extra ou em bloco ```json ...```.
        # Extraímos o primeiro objeto { ... } para reduzir fallback por parse.
        raw_json = raw
        try:
            m = re.search(r"\{.*\}", raw, flags=re.DOTALL)
            if m:
                raw_json = m.group(0)
        except Exception:
            raw_json = raw

        data = json.loads(raw_json)

        # ----------------------------------------------------------
        # Decider JSON (packs_v1): por padrão NÃO gera replyText final.
        # Exceção: SEND_LINK pode trazer replyText/spokenText curto.
        # ----------------------------------------------------------
        understanding = data.get("understanding") or {}

        intent = str(
            data.get("intent")
            or understanding.get("intent")
            or understanding.get("topic")
            or "OTHER"
        ).strip().upper()

        confidence = str(
            data.get("confidence")
            or understanding.get("confidence")
            or "low"
        ).strip().lower()

        needs_clarify = str(
            data.get("needsClarify")
            or understanding.get("needsClarify")
            or "no"
        ).strip().lower()

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

        # Back-compat: alguns retornos antigos ainda vêm com replyText/spokenText
        reply_text = str(data.get("replyText") or "").strip()
        spoken_text = str(data.get("spokenText") or "").strip()

        # Compat: topic é o intent (mantém contrato anterior)
        topic = intent
        if topic not in TOPICS:
            topic = "OTHER"

        next_step = str(data.get("nextStep") or data.get("next_step") or "NONE").strip().upper()
        if next_step not in ("NONE", "SEND_LINK"):
            next_step = "NONE"

        should_end = bool(data.get("shouldEnd")) or bool(data.get("should_end"))

        # name_use: só 4 valores no contrato
        name_use = str(data.get("nameUse") or "none").strip().lower()
        if name_use not in ("none", "greet", "empathy", "clarify"):
            name_use = "none"

        # Se for decider-only (padrão), devolve sem replyText e deixa o backend renderizar o pack.
        if next_step != "SEND_LINK":
            decider = {
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
            return {
                "replyText": "",
                "spokenText": "",
                "understanding": {
                    "topic": topic,
                    "intent": intent,
                    "confidence": confidence,
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


        # Normaliza confidence
        confidence = str(understanding.get("confidence") or "low").strip().lower()
        if confidence not in ("high", "medium", "low"):
            confidence = "low"

        # ----------------------------------------------------------
        # ✅ Regra canônica de VENDAS:
        # Se o cliente pediu LINK (nextStep=SEND_LINK), o negócio já está fechado.
        # Então: manda o link e encerra, sem CTA extra.
        # ----------------------------------------------------------
        if next_step == "SEND_LINK":
            base = (os.getenv("FRONTEND_BASE") or "https://www.meirobo.com.br").strip()
            reply_text = f"Perfeito. Aqui está o link pra assinar agora:\n{base}"
            # Áudio: não falar URL; usa nome no agradecimento se já tiver
            if has_name:
                spoken_text = f"Fechado, {name_hint}. Obrigado pelo contato — te enviei o link no texto agora pra você assinar sem fidelidade."
            else:
                spoken_text = "Fechado. Obrigado pelo contato — te enviei o link no texto agora pra você assinar sem fidelidade."
            should_end = True


        # Fail-safe: nunca devolver reply vazio (evita saída "muda" em produção)
        if not reply_text:
            reply_text = "Sim — pode mandar suas dúvidas por aqui mesmo. Quer falar de agenda, preço ou ativação?"
            topic = "OTHER"
            confidence = "low"
            next_step = "NONE"
            should_end = False
            name_use = "clarify"

        # -----------------------------
        # Pós-processo “Vendas, sem mini-suporte”
        # -----------------------------
        try:
            import re

            # 1) no máximo 1 pergunta
            if reply_text.count("?") > 1:
                first_q = reply_text.find("?")
                # mantém até a primeira pergunta; o resto vira ponto final (sem novas perguntas)
                reply_text = (reply_text[: first_q + 1]).strip()

            # 2) mata “como configurar / como cadastrar” (vira qualificação)
            if re.search(r"\bcomo\s+configurar\b|\bcomo\s+cadastrar\b|\bpasso\s+a\s+passo\b", reply_text, re.IGNORECASE):
                if topic == "AGENDA":
                    reply_text = re.sub(
                        r"(?i)\s*Você gostaria.*$",
                        " Você atende por hora marcada ou também faz encaixe?",
                        reply_text
                    ).strip()
                elif topic in ("ORCAMENTO", "PRICE", "PRECO"):
                    reply_text = re.sub(
                        r"(?i)\s*Você gostaria.*$",
                        " Você quer que o robô já leve o cliente pro orçamento/pedido, ou primeiro só qualifique?",
                        reply_text
                    ).strip()
                else:
                    reply_text = re.sub(
                        r"(?i)\s*Você gostaria.*$",
                        " Hoje sua prioridade é vender mais, organizar agenda ou tirar dúvidas dos clientes?",
                        reply_text
                    ).strip()

            # 3) não inventa “email/e-mail” se não existir no KB snapshot
            kb_low = (kb_snapshot or "").lower()
            if re.search(r"\be-?mail\b", reply_text, re.IGNORECASE) and ("email" not in kb_low) and ("e-mail" not in kb_low):
                # remove sentenças que citam email
                parts = re.split(r"(?<=[\.\!\?])\s+", reply_text)
                parts = [p for p in parts if not re.search(r"\be-?mail\b", p, re.IGNORECASE)]
                reply_text = " ".join(parts).strip()

        except Exception:
            pass

        # ✅ Produto: SEND_LINK = venda fechada (link-only, sem pergunta)
        try:
            if next_step == "SEND_LINK":
                should_end = True
                url = (os.getenv("FRONTEND_BASE") or "https://www.meirobo.com.br").strip()
                rt0 = (reply_text or "").strip()
                if ("http://" not in rt0) and ("https://" not in rt0):
                    reply_text = f"Perfeito. Aqui está o link pra assinar agora:\n{url}"
                else:
                    qpos = rt0.find("?")
                    if qpos != -1:
                        reply_text = (rt0[: qpos]).rstrip()
                st0 = (spoken_text or reply_text or "").strip()
                qpos2 = st0.find("?")
                if qpos2 != -1:
                    st0 = (st0[: qpos2]).rstrip()
                spoken_text = st0
        except Exception:
            pass

        # ----------------------------------------------------------
        # Enforcements de produto (anti-resposta genérica)
        # ----------------------------------------------------------
        try:
            ut = (user_text or "").strip().lower()

            # Perguntas "macro" onde a resposta precisa ter a âncora do produto
            is_macro = False
            try:
                # heurística simples e barata (sem NLP pesado)
                macro_hits = (
                    "ganhar dinheiro",
                    "como ajuda",
                    "como pode ajudar",
                    "o que você faz",
                    "oq vc faz",
                    "o que o robô faz",
                    "pra que serve",
                    "para que serve",
                    "serve pra que",
                    "serve para que",
                    "como funciona",
                    "me explica",
                )
                is_macro = any(h in ut for h in macro_hits)
            except Exception:
                is_macro = False

            if is_macro:
                rt_low = (reply_text or "").lower()
                has_acervo = ("acervo" in rt_low)
                has_no_invent = (("não inventa" in rt_low) or ("nao inventa" in rt_low))

                # Insere 1 frase curta obrigatória se estiver faltando
                if (not has_acervo) or (not has_no_invent):
                    acervo_line = "Ele responde com base no acervo do seu negócio (o que você cadastrar) e não inventa."

                    # evita repetição se já estiver bem próximo por variação
                    if acervo_line.lower() not in rt_low:
                        # Insere depois da primeira frase (ou no começo se não achar pontuação)
                        inserted = False
                        for sep in (". ", " — ", "? ", "! "):
                            idx = reply_text.find(sep)
                            if idx > 0 and idx < 220:
                                cut = idx + len(sep)
                                reply_text = reply_text[:cut] + acervo_line + " " + reply_text[cut:]
                                inserted = True
                                break
                        if not inserted:
                            reply_text = acervo_line + " " + reply_text

                        reply_text = reply_text[:FRONT_REPLY_MAX_CHARS].rstrip()
        except Exception:
            pass


        # ----------------------------------------------------------
        # Enforcement VENDEDOR: bloquear "como configurar" no fechamento
        # (evita virar suporte; fecha com pergunta de necessidade/encaixe)
        # ----------------------------------------------------------
        try:
            rt = (reply_text or "").strip()
            rt_low = rt.lower()

            # Se a resposta termina/contém um convite de "configurar/ensinar como",
            # trocamos por uma fit question curta, baseada no tópico/intent.
            bad_close_markers = (
                "como configurar",
                "como cadastrar",
                "como colocar",
                "como adicionar",
                "como fazer",
                "como funciona por dentro",
                "passo a passo",
                "configurar isso",
                "cadastrar isso",
                "te explico como",
                "quer aprender como",
                "quer ver como",
                "quer saber mais",
                "saber mais",
                "saber mais sobre",
                "você gostaria de saber mais",
                "voce gostaria de saber mais",
                "quer entender melhor",
                "posso te mostrar",
                "posso te explicar",
                "cadastrar isso",
                "você gostaria de saber como cadastrar",
                "voce gostaria de saber como cadastrar",
            )
            has_bad_close = any(m in rt_low for m in bad_close_markers)

            def _pick_fit_question(_topic: str, _intent: str) -> str:
                t = (_topic or "").strip().upper()
                i = (_intent or "").strip().upper()
                # AGENDA
                if t == "AGENDA" or i == "AGENDA":
                    return "Você quer que ele marque horários e confirme presença, ou só organize e te avise?"
                # ORÇAMENTO / VENDAS
                if t in ("ORCAMENTO", "PRECOS", "PRECO") or i in ("ORCAMENTO", "PRECOS", "PRECO"):
                    return "Você quer que ele responda e já leve pro orçamento/pedido, ou só qualifique o cliente primeiro?"
                # SUPORTE (tópico/intent pode variar; deixamos um genérico vendedor)
                if t in ("SUPORTE", "TECNOLOGIA", "TECNICO") or i in ("SUPORTE", "TECNICO"):
                    return "Seu gargalo hoje é mais tirar dúvidas rápidas, resolver problemas, ou orientar o cliente passo a passo?"
                # DEFAULT (macro)
                return "Hoje, seu gargalo é mais responder rápido, organizar agenda, ou transformar conversa em venda?"

            if has_bad_close:
                intent_hint = (last_intent or topic or "").strip()
                fit_q = _pick_fit_question(topic, intent_hint)

                # Remove a última pergunta "ruim" se ela estiver no fim
                # Heurística: corta a partir do último "?" e substitui.
                qpos = rt.rfind("?")
                if qpos > 0:
                    base = rt[: qpos + 1].strip()
                    # Se a última pergunta é "ruim", removemos ela inteira
                    base_low = base.lower()
                    if any(m in base_low[-220:] for m in bad_close_markers):
                        # mantém tudo antes da última pergunta
                        keep = rt[: rt.rfind("?")].strip()
                        # fallback seguro: se ficou vazio, não corta
                        if len(keep) >= 20:
                            rt = keep

                # Garante terminar com a fit question (uma só)
                rt = rt.rstrip()
                if not rt.endswith((".", "!", "?")):
                    rt += "."
                # 🛑 Regra: no máximo 1 pergunta. Se já existe "?" no texto, não anexa fit_q.
                if "?" not in rt:
                    rt = rt + " " + fit_q

                # Higiene: aspas e “quotes” atrapalham no WhatsApp e no TTS
                rt = rt.replace('"', "").replace("“", "").replace("”", "").replace("‘", "").replace("’", "")

                reply_text = rt[:FRONT_REPLY_MAX_CHARS].rstrip()

                # spokenText separado: mesma ideia, mas mais "falável" (sem aspas)
                spoken_text = reply_text.replace('"', "").replace("“", "").replace("”", "").replace("‘", "").replace("’", "")
        except Exception:
            pass
        # Corte final (anti-textão)
        reply_text = reply_text[:FRONT_REPLY_MAX_CHARS].rstrip()
        spoken_text = (spoken_text or "")[:FRONT_REPLY_MAX_CHARS].rstrip()

        # ✅ Normalização: se tiver "Você quer/Quer" mas faltou "?", corrige.
        # Isso evita o wa_bot achar que "não tem pergunta" e adicionar outra.
        try:
            import re
            def _fix_missing_qmark(s: str) -> str:
                s = (s or "").strip()
                if not s:
                    return s
                if "?" in s:
                    return s
                if re.search(r"\b(você\s+quer|quer)\b", s, re.IGNORECASE):
                    # se termina com ponto, troca por interrogação
                    if s.endswith("."):
                        return s[:-1].rstrip() + "?"
                    # senão, só garante "?" no fim
                    return s.rstrip("! ") + "?"
                return s
            reply_text = _fix_missing_qmark(reply_text)
            spoken_text = _fix_missing_qmark(spoken_text)
        except Exception:
            pass

        # fallback hard: no máximo 1 pergunta em cada canal (texto/voz)
        try:
            if (reply_text or "").count("?") > 1:
                qpos = reply_text.find("?")
                if qpos != -1:
                    reply_text = reply_text[: qpos + 1].strip()
            if (spoken_text or "").count("?") > 1:
                qpos2 = spoken_text.find("?")
                if qpos2 != -1:
                    spoken_text = spoken_text[: qpos2 + 1].strip()
        except Exception:
            pass


        out = {
            "replyText": reply_text,
            "spokenText": spoken_text,
            "understanding": {
                "topic": topic,
                # Harmoniza com o resto do pipeline (sales_lead/outbox)
                "intent": topic,
                "confidence": confidence,
            },
            "nextStep": next_step,
            "shouldEnd": should_end,
            "nameUse": name_use,
            # ✅ Regra canônica: texto só quando for SEND_LINK (link copiável).
            # Caso contrário, o worker decide o canal (entra áudio -> sai áudio).
            "prefersText": (next_step == "SEND_LINK"),
            # Auditoria: quem respondeu
            "replySource": "front",
            # Probe leve do snapshot (ajuda a ver se o front "passou fome")
            "kbSnapshotSizeChars": len(kb_snapshot or ""),
            # Telemetria de custo (best-effort)
            "tokenUsage": token_usage,
        }

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

        return out

    except Exception as e:
        # Fail-safe absoluto: nunca quebrar o fluxo
        logging.exception("[CONVERSATIONAL_FRONT] erro, fallback silencioso: %s", e)

        return {
            "replyText": "Me conta um pouquinho melhor o que você quer resolver?",
            "understanding": {
                "topic": "OTHER",
                "confidence": "low",
            },
            "nextStep": "NONE",
            "shouldEnd": False,
            "nameUse": "clarify",
            "prefersText": True,
        }
