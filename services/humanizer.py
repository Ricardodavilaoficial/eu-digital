# services/humanizer.py
# Gate de humanização de mensagens (não quebra fluxo atual)
# - remove IDs/hashes de saída
# - formata fala (áudio) para datas/horas/valores
# - variações leves (prontas para futura expansão)
# - preço único e lista de preços (texto x áudio)
# Controle por ENV: HUMANIZE_MODE=off|canary|on

from __future__ import annotations
import os, re
from datetime import datetime
from random import choice

MONTHS_PT = [
    "janeiro","fevereiro","março","abril","maio","junho",
    "julho","agosto","setembro","outubro","novembro","dezembro"
]

# ---------------------------
# Feature flag
# ---------------------------
def humanize_on() -> bool:
    return os.getenv("HUMANIZE_MODE", "off").lower() in ("canary", "on")

def humanize_full() -> bool:
    return os.getenv("HUMANIZE_MODE", "off").lower() == "on"

# ---------------------------
# Sanitização: tira rastros técnicos da mensagem
# ---------------------------
_ID_IN_PARENS = re.compile(r"\s*\((?:id|wamid)[^)]*\)", flags=re.I)
_HEXISH_TOKEN = re.compile(r"\b[A-Fa-f0-9]{10,}\b")
_LONG_ALNUM = re.compile(r"\b[A-Za-z0-9]{16,}\b")

def sanitize_text(msg: str) -> str:
    if not msg:
        return msg
    # remove "(id ...)" ou "(wamid ...)"
    m = _ID_IN_PARENS.sub("", msg)
    # remove tokens longos com cara de hash (sem pegar datas/preços)
    m = _HEXISH_TOKEN.sub("", m)
    m = _LONG_ALNUM.sub("", m)
    # limpa espaços e sobras de pontuação
    m = re.sub(r"\s{2,}", " ", m).strip()
    m = re.sub(r"[–—-]\s*$", "", m).strip()
    return m

# ---------------------------
# Helpers numéricos / BRL
# ---------------------------
_NUM_0_19 = [
    "zero","um","dois","três","quatro","cinco","seis","sete","oito","nove",
    "dez","onze","doze","treze","quatorze","quinze","dezesseis","dezessete","dezoito","dezenove"
]
_TENS = ["","", "vinte","trinta","quarenta","cinquenta","sessenta","setenta","oitenta","noventa"]
_HUNDREDS = ["","cento","duzentos","trezentos","quatrocentos","quinhentos","seiscentos","setecentos","oitocentos","novecentos"]

def _pt_number_to_words(n: int) -> str:
    # simples e suficiente para 0–999 (nossos preços usuais)
    if n < 0: n = abs(n)
    if n < 20: return _NUM_0_19[n]
    if n < 100:
        d, r = divmod(n, 10)
        if r == 0: return _TENS[d]
        return f"{_TENS[d]} e {_NUM_0_19[r]}"
    if n == 100: return "cem"
    c, r = divmod(n, 100)
    if r == 0: return _HUNDREDS[c]
    return f"{_HUNDREDS[c]} e {_pt_number_to_words(r)}"

def _amount_to_int(valor) -> int | None:
    try:
        if isinstance(valor, (int, float)):
            return int(round(float(valor)))
        s = str(valor).strip()
        s = s.replace("R$", "").replace(" ", "")
        # normaliza padrão BR "1.234,56" -> "1234.56"
        if "," in s and "." in s:
            s = s.replace(".", "").replace(",", ".")
        elif "," in s and "." not in s:
            s = s.replace(",", ".")
        return int(round(float(s)))
    except Exception:
        return None

def price_to_speech_brl(valor) -> str:
    v = _amount_to_int(valor)
    if v is None: return "um valor combinado"
    if v == 1: return "um real"
    return f"{_pt_number_to_words(v)} reais"

def hour_to_speech(hhmm: str) -> str:
    # "15:00" -> "três da tarde"; "10:30" -> "dez e meia da manhã"
    try:
        h, m = [int(x) for x in hhmm.split(":")[:2]]
    except Exception:
        return hhmm

    periodo = "da noite"
    if 5 <= h < 12: periodo = "da manhã"
    elif 12 <= h < 18: periodo = "da tarde"

    h12 = h
    if h == 0: h12 = 0
    elif h == 12: h12 = 12
    elif h > 12: h12 = h - 12

    hora_pal = _pt_number_to_words(h12 if h12 else 12)  # 0=>12
    if m == 0:
        if h == 12: return "meio-dia"
        if h == 0: return "meia-noite"
        return f"{hora_pal} {periodo}"
    if m == 30: return f"{hora_pal} e meia {periodo}"
    if m == 15: return f"{hora_pal} e quinze {periodo}"
    return f"{hora_pal} e {_pt_number_to_words(m)} {periodo}"

def date_to_speech(yyyy_mm_dd: str) -> str:
    # aceita "YYYY-MM-DD" ou "DD/MM[/YYYY]"
    d = None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d/%m"):
        try:
            d = datetime.strptime(yyyy_mm_dd, fmt)
            # se for dd/mm sem ano, usa o ano corrente
            if fmt == "%d/%m":
                d = d.replace(year=datetime.now().year)
            break
        except Exception:
            continue
    if not d: return yyyy_mm_dd
    dia = _pt_number_to_words(d.day)
    mes = MONTHS_PT[d.month - 1]
    return f"{dia} de {mes}"

# ---------------------------
# Microvariações (sem GPT por enquanto)
# ---------------------------
def _v(opts): return choice(opts)

def text_confirm_agenda(servico, data_str, hora_str):
    return _v([
        f"Prontinho! Agendei {servico} para {data_str} às {hora_str}. Qualquer coisa eu remarco pra você. 😉",
        f"Tudo certo! Ficou {servico} em {data_str}, às {hora_str}. Se precisar mudar, é só me chamar.",
        f"Feito! {servico} marcado para {data_str}, {hora_str}. Se preferir outro horário depois, eu ajusto."
    ])

def audio_confirm_agenda(servico, data_iso, hhmm):
    return _v([
        f"Perfeito! Já deixei marcado o seu {servico} para {date_to_speech(data_iso)}, às {hour_to_speech(hhmm)}. Se precisar mudar, é só me falar.",
        f"Combinado! O {servico} ficou reservado para {date_to_speech(data_iso)}, por volta de {hour_to_speech(hhmm)}. Qualquer ajuste eu faço por aqui.",
        f"Ótimo! {servico} ficou agendado para {date_to_speech(data_iso)} às {hour_to_speech(hhmm)}. Se quiser trocar depois, me chama."
    ])

def text_confirm_reagenda(servico, data_str, hora_str):
    return _v([
        f"Tudo certo, reagendei {servico} para {data_str}, às {hora_str}. Pode contar comigo!",
        f"Pronto! Mudei {servico} para {data_str}, {hora_str}. Qualquer coisa, ajustamos de novo.",
        f"Feito! {servico} agora está para {data_str} às {hora_str}. Se não puder, me avisa."
    ])

def audio_confirm_reagenda(servico, data_iso, hhmm):
    return _v([
        f"Já troquei pra você: {servico} ficou para {date_to_speech(data_iso)}, às {hour_to_speech(hhmm)}. Combinado?",
        f"Mudança feita! {servico} agora é {date_to_speech(data_iso)}, por volta de {hour_to_speech(hhmm)}. Qualquer coisa, eu ajusto.",
        f"Pronto, reagendei: {servico} ficou em {date_to_speech(data_iso)} às {hour_to_speech(hhmm)}. Se precisar, é só falar."
    ])

def text_prices(itens):
    # itens: lista de dicts {nome, duracaoMin, preco}
    linhas = []
    for i in itens[:20]:
        nome = i.get("nome","serviço")
        dur = i.get("duracaoMin")
        dur_txt = f"{dur}min" if dur not in (None,"","?") else "—"
        val = _amount_to_int(i.get("preco"))
        val_txt = f"R$ {val:d}" if val is not None else "a consultar"
        linhas.append(f"• {nome} — {dur_txt} — {val_txt}")
    return "Claro! Aqui vão alguns valores:\n" + "\n".join(linhas) + "\nQuer que eu reserve um horário pra você?"

def audio_prices(itens):
    nomes = []
    for i in itens[:8]:
        nome = i.get("nome","serviço")
        val_txt = price_to_speech_brl(i.get("preco"))
        nomes.append(f"{nome} fica em {val_txt}")
    if not nomes: return "Ainda não tenho uma tabela de valores publicada. Quer que eu veja pra você?"
    falado = ", ".join(nomes[:-1]) + (f" e {nomes[-1]}" if len(nomes) > 1 else nomes[0])
    return f"Vamos lá: {falado}. Quer que eu já separe um horário pra você?"

def text_price_single(nome, preco, duracaoMin=None):
    dur_txt = f" — {int(duracaoMin)}min" if isinstance(duracaoMin, (int, float)) else ""
    val = _amount_to_int(preco)
    if val is None:
        return f"{nome}:{dur_txt} — a consultar 😉"
    return f"{nome}{dur_txt} — R$ {val:d} 😉"

def audio_price_single(nome, preco, duracaoMin=None):
    falado = price_to_speech_brl(preco)
    return f"O {nome} fica em {falado}. Quer que eu já reserve um horário?"

def text_help():
    return "Posso te passar valores, endereço/horários ou já marcar um horário. O que você prefere?"

def audio_help():
    return "Eu posso te ajudar de três jeitos: te contando os valores, passando o endereço e horários ou já marcando um horário direto. O que você prefere fazer agora?"

def text_audio_error():
    return "Ops, não consegui entender bem o áudio. Quer tentar de novo ou me mandar por mensagem?"

def audio_audio_error():
    return "Não peguei direitinho o que você falou agora. Pode repetir o áudio ou, se preferir, me manda em texto que eu entendo rapidinho."

# ---------------------------
# API principal
# ---------------------------
def humanize(intent: str, payload: dict, mode: str = "text") -> str:
    """
    intent: 'confirm_agenda' | 'confirm_reagenda' | 'prices' | 'price_single' | 'help' | 'audio_error'
    payload:
      - servico, data (YYYY-MM-DD), data_str (06/09), hora (HH:MM)
      - itens: [{nome, duracaoMin, preco}]
      - nome, preco, duracaoMin (para price_single)
      - raw: fallback
    mode: 'text' | 'audio'
    """
    if not humanize_on():
        # fallback seguro: devolve raw se existir
        return sanitize_text(payload.get("raw",""))

    mode = (mode or "text").lower()

    if intent == "confirm_agenda":
        if mode == "audio":
            return audio_confirm_agenda(payload.get("servico",""), payload.get("data",""), payload.get("hora",""))
        return text_confirm_agenda(payload.get("servico",""), payload.get("data_str",""), payload.get("hora",""))

    if intent == "confirm_reagenda":
        if mode == "audio":
            return audio_confirm_reagenda(payload.get("servico",""), payload.get("data",""), payload.get("hora",""))
        return text_confirm_reagenda(payload.get("servico",""), payload.get("data_str",""), payload.get("hora",""))

    if intent == "prices":
        itens = payload.get("itens", [])
        if mode == "audio":
            return audio_prices(itens)
        return text_prices(itens)

    if intent == "price_single":
        nome = payload.get("nome","serviço")
        preco = payload.get("preco")
        dur = payload.get("duracaoMin")
        return audio_price_single(nome, preco, dur) if mode == "audio" else text_price_single(nome, preco, dur)

    if intent == "help":
        return audio_help() if mode == "audio" else text_help()

    if intent == "audio_error":
        return audio_audio_error() if mode == "audio" else text_audio_error()

    return sanitize_text(payload.get("raw",""))

# ---------------------------
# Preview util (para endpoint de teste)
# ---------------------------
def preview_sample(q: dict) -> dict:
    intent = q.get("intent","confirm_agenda")
    mode = q.get("mode","text")
    payload = {
        "servico": q.get("servico","Corte Masculino"),
        "data": q.get("data","2025-09-06"),
        "data_str": q.get("data_str","06/09"),
        "hora": q.get("hora","15:00"),
        "itens": q.get("itens", []),
        "nome": q.get("nome", "Corte Masculino"),
        "preco": q.get("preco", 50),
        "duracaoMin": q.get("duracaoMin", 30),
    }
    return {
        "intent": intent,
        "mode": mode,
        "sample": humanize(intent, payload, mode)
    }
