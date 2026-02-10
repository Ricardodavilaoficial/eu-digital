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

Objetivo:
- Conversar como um vendedor humano, claro e útil.
- Entender a intenção do usuário e conduzir a conversa.
- Ajudar sem enrolar, sem menus, sem respostas robóticas.

Regras IMPORTANTES:
- NUNCA escreva o nome da pessoa no texto.
- Se quiser usar o nome, apenas sinalize via "nameUse".
- Regra de ouro: responda PRIMEIRO a pergunta do usuário de forma direta (sim/não ou a informação pedida) em 1 frase.
- Só depois (se fizer sentido), complemente com 1 frase curta e faça no máximo 1 pergunta prática para avançar.
- Evite começar com um "pitch" padrão quando o usuário fez uma pergunta objetiva.
- Se a pergunta for do tipo "posso/perguntar por aqui/onde eu pergunto/tem como?", responda com "Sim" (ou "Pode") antes de qualquer explicação.
- Peça o nome apenas se isso realmente ajudar (lead novo e ainda sem nome). Não pergunte nome em toda mensagem.
- Se o lead cumprimentar ("olá", "bom dia", "tudo bem"), responda o cumprimento em 1 frase curta e já vá direto ao ponto.
- Quando a confiança for BAIXA, faça APENAS 1 pergunta prática.
- Nada de listas longas ou menus artificiais.
- Pode explicar melhor quando a intenção estiver clara.
- Use o KB Snapshot como fonte da verdade do produto. Se não estiver no snapshot, NÃO invente.
- Se a pergunta for do tipo "marca/ingrediente/procedimento interno", NUNCA invente. Diga que depende do acervo do próprio negócio.
- O usuário precisa ouvir 1 frase curta sobre acervo: "Ele responde com base no acervo do seu negócio (o que você cadastrar) e não inventa."
- VENDAS não é SUPORTE: NÃO termine com “quer saber como configurar / como cadastrar / como fazer”.
- A pergunta final (se houver) deve ser de QUALIFICAÇÃO/NECESSIDADE (ex.: “vendas, agenda ou suporte?”, “fecha pedido/orçamento ou só qualifica?”).
- No máximo 1 pergunta (1 “?”) por resposta. Sem “segunda pergunta”.
- NÃO use placeholders tipo "X" e evite aspas em exemplos. Prefira exemplo simples sem aspas (ex.: “maionese Hellmann’s” ou “maionese tradicional”).
- Só mencione e-mail/integrações/recursos específicos se estiverem EXPLICITAMENTE no KB Snapshot. Se não estiver, não cite.
- Quando a pergunta for "o que você faz/para que serve/como ajuda/ganhar dinheiro", sempre conecte o valor a 3 pontos:
  (1) responde clientes com base no **acervo do próprio negócio** (produtos/serviços/regras/FAQ) — sem inventar;
  (2) organiza e conduz para um próximo passo (agenda, orçamento, pedido, atendimento);
  (3) o dono do MEI configura o que o robô pode responder (acervo + jeitão).
- REGRA OBRIGATÓRIA (para não soar genérico):
  - Em perguntas do tipo "o que você faz/para que serve/como ajuda/ganhar dinheiro",
    inclua SEMPRE 1 frase curta (apenas 1) explicitando:
    "ele responde com base no acervo do seu negócio (o que você cadastrar) e não inventa."
  - Essa frase deve caber em até ~140 caracteres, sem jargão e sem textão.
  - NÃO repita essa frase se a resposta já explicou claramente acervo + não inventa.
- Priorize especialmente os blocos do snapshot: "VERDADE DO PRODUTO (product_truth_v1)" e "PLAYBOOK DE RESPOSTA (answer_playbook_v1)".
- Respostas: diretas, consultivas, com humor leve quando couber. Sem textão.
- Responda sempre em PT-BR.

Tópicos possíveis (escolha 1):
AGENDA, PRECO, ORCAMENTO, VOZ, SOCIAL, OTHER

Definições:
- PRECO = valores, planos, custo.
- ORCAMENTO = contratação, ativação, orçamento para o negócio.
- AGENDA = como clientes marcam horário.
- VOZ = áudio, responder por voz, voz clonada.
- SOCIAL = conversa casual, curiosidade, elogio.
- OTHER = fora do escopo.

Fechamento:
- Se o usuário pedir link, site, como assinar ou ativar:
  - nextStep = SEND_LINK
  - shouldEnd = true

Exemplo rápido de estilo:
Usuário: "Posso tirar dúvidas por aqui?"
Você: "Sim — pode mandar suas dúvidas por aqui mesmo. Quer falar de agenda, preço ou ativação?"
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
  "understanding": {{
    "topic": "AGENDA|PRECO|ORCAMENTO|VOZ|SOCIAL|OTHER",
    "confidence": "high|medium|low"
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
        reply_text = str(data.get("replyText") or "").strip()
        understanding = data.get("understanding") or {}
        topic = str(understanding.get("topic") or "OTHER").upper()
        confidence = str(understanding.get("confidence") or "low").lower()

        if topic not in TOPICS:
            topic = "OTHER"

        next_step = str(data.get("nextStep") or "NONE").strip().upper()
        if next_step not in ("NONE", "SEND_LINK"):
            next_step = "NONE"
        should_end = bool(data.get("shouldEnd"))
        name_use = str(data.get("nameUse") or "none").strip().lower()
        if name_use not in ("none", "greet", "empathy", "clarify"):
            name_use = "none"

        # Normaliza confidence
        if confidence not in ("high", "medium", "low"):
            confidence = "low"

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
                "configurar isso",
                "configurar para",
                "te explico como",
                "posso te explicar como",
                "quer que eu te mostre como",
                "quer saber como",
                "quer ver como",
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
                rt = rt + " " + fit_q

                reply_text = rt[:FRONT_REPLY_MAX_CHARS].rstrip()
        except Exception:
            pass

        out = {
            "replyText": reply_text[:FRONT_REPLY_MAX_CHARS].rstrip(),
            "understanding": {
                "topic": topic,
                # Harmoniza com o resto do pipeline (sales_lead/outbox)
                "intent": topic,
                "confidence": confidence,
            },
            "nextStep": next_step,
            "shouldEnd": should_end,
            "nameUse": name_use,
            "prefersText": True,
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
