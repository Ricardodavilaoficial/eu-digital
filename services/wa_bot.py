# services/wa_bot.py
# Bot WhatsApp do MEI Robô
# - NLU leve "sempre on"
# - Preços: consolida de 3 fontes (doc.precos [map/lista], coleção /precos, coleção /produtosEServicos)
# - Profissão + até 2 especializações: sinônimos e matching por contexto
# - Cache de respostas de preço (quanto custa X?)
# - FAQ fixos via profissionais/{uid}/faq/{endereco|horarios|telefone|pix}
# - Agendar/Reagendar com regras (sem fim de semana; +2 dias) e integração schedule se existir
# - Budget Guard: gate de áudio e LLM, contagem de custos
# - Mensagens de fallback diagnosticadas

import os
import re
import json
import logging
import requests
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

# --- DB helpers (tolerante a ausências) ---
try:
    from services.db import get_doc, list_collection
    from services import db as dbsvc  # Lazy client p/ writes/sessions
    DB = dbsvc.db
except Exception as e:
    logging.exception("[wa_bot] services.db indisponível: %s", e)
    def get_doc(_): return None
    def list_collection(_col, limit=10): return []
    class _FakeDB:
        def collection(self, *_a, **_k): raise RuntimeError("DB indisponível")
    DB = _FakeDB()

# --- NLU leve ---
try:
    from services.openai.nlu_intent import extract_intent  # retorna {intent, serviceName, dateText, timeText}
except Exception as e:
    logging.exception("[wa_bot] nlu_intent indisponível: %s", e)
    def extract_intent(text: str) -> Dict[str, Optional[str]]:
        t = (text or "").lower()
        if re.search(r"\b(preço|preços|tabela|valor|valores|serviço|serviços)\b", t): return {"intent":"precos","serviceName":None,"dateText":None,"timeText":None}
        if re.search(r"\b(agendar|agenda|marcar|agendamento|reservar)\b", t):
            mdate = re.search(r"(\d{1,2}/\d{1,2})", t)
            mtime = re.search(r"(\d{1,2}:\d{2})", t)
            return {"intent":"agendar","serviceName":None,"dateText": mdate.group(1) if mdate else None,"timeText": mtime.group(1) if mtime else None}
        if re.search(r"\b(reagendar|remarcar|mudar\s+hor[aó]rio|trocar\s+hor[aó]rio)\b", t): return {"intent":"reagendar","serviceName":None,"dateText":None,"timeText":None}
        if re.search(r"\b(endereç|localiza|maps?)\b", t): return {"intent":"localizacao","serviceName":None,"dateText":None,"timeText":None}
        if re.search(r"\b(hor[aá]rio|funciona)\b", t): return {"intent":"horarios","serviceName":None,"dateText":None,"timeText":None}
        if re.search(r"\b(telefone|whats|contato)\b", t): return {"intent":"telefone","serviceName":None,"dateText":None,"timeText":None}
        if re.search(r"\b(pix|pagamento|pagar)\b", t): return {"intent":"pagamento","serviceName":None,"dateText":None,"timeText":None}
        return {"intent":"fallback","serviceName":None,"dateText":None,"timeText":None}

# --- Budget Guard ---
try:
    from services.budget_guard import budget_fingerprint, charge, can_use_audio, can_use_gpt4o
except Exception as e:
    logging.exception("[wa_bot] budget_guard indisponível: %s", e)
    def budget_fingerprint(): return {"can_audio": True, "can_gpt4o": False}
    def charge(*args, **kwargs): pass
    def can_use_audio(): return True
    def can_use_gpt4o(): return False

# --- Cache de respostas de preço ---
try:
    from services.answers_cache import is_price_question, get as cache_get, put as cache_put
except Exception as e:
    logging.exception("[wa_bot] answers_cache indisponível: %s", e)
    def is_price_question(text: str) -> bool:
        return bool(re.search(r"\b(quanto|preço|valor|custa|tá|ta)\b", text or "", re.I))
    def cache_get(_k): return None
    def cache_put(_k, _v): pass

# --- Schedule (regras de negócio/CRUD) ---
try:
    from services.schedule import can_book, save_booking, validar_agendamento_v1, salvar_agendamento, atualizar_estado_agendamento
except Exception as e:
    logging.exception("[wa_bot] schedule indisponível: %s", e)
    def can_book(date_str, time_str, tz="America/Sao_Paulo"):
        # fallback: mínimo +2 dias e sem fim de semana
        try:
            dd, mm = [int(x) for x in re.findall(r"\d{1,2}", date_str)[:2]]
            hh, mi = [int(x) for x in re.findall(r"\d{1,2}", time_str)[:2]]
            tzinfo = timezone(timedelta(hours=-3))
            now = datetime.now(tzinfo)
            year = now.year
            dt = datetime(year, mm, dd, hh, mi, tzinfo=tzinfo)
            if (dt.date() - now.date()).days < 2:
                return (False, "Preciso de pelo menos 2 dias de antecedência.")
            if dt.weekday() >= 5:
                return (False, "Não atendemos em fins de semana.")
            return (True, None)
        except Exception:
            return (False, "Data/hora inválida.")
    def save_booking(uid, serviceName, dateText, timeText):
        return {"servico": serviceName or "serviço", "data": dateText, "hora": timeText}
    def validar_agendamento_v1(uid, ag): return (True, None, None)
    def salvar_agendamento(uid, ag): return {"id":"fake"}
    def atualizar_estado_agendamento(uid, ag_id, body): return True

# --- Constantes / TZ ---
SP_TZ = timezone(timedelta(hours=-3))  # America/Sao_Paulo (sem DST)
GRAPH_VERSION_DEFAULT = os.getenv("GRAPH_VERSION", "v23.0")

# ========== Utils ==========
def _only_digits(s: str) -> str:
    return "".join(ch for ch in str(s or "") if ch.isdigit())

def _normalize_br_msisdn(wa_id: str) -> str:
    if not wa_id:
        return ""
    digits = _only_digits(wa_id)
    if digits.startswith("55") and len(digits) == 12:
        digits = digits[:4] + "9" + digits[4:]
    return digits

def _strip_accents_lower(s: str) -> str:
    s = s or ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return s.lower().strip()

def _format_brl(v: Any) -> str:
    if isinstance(v, (int, float)):
        s = f"R${v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return s
    if isinstance(v, str) and not v.strip().lower().startswith("r$"):
        return f"R$ {v}"
    return str(v)

def fallback_text(app_tag: str, context: str) -> str:
    return f"[FALLBACK] MEI Robo PROD :: {app_tag} :: {context}\nDigite 'precos' para ver a lista."

def _pick_phone(value: Dict) -> str:
    try:
        return (value.get("messages", [{}])[0] or {}).get("from") or (value.get("contacts", [{}])[0] or {}).get("wa_id") or ""
    except Exception:
        return ""

# ========== Profissão & especializações ==========
def _load_prof_context(uid: str) -> Dict[str, Any]:
    """Lê profissionais/{uid} e retorna {profissao, especializacoes[], aliases(Optional map)}."""
    prof = get_doc(f"profissionais/{uid}") or {}
    prof_context = {
        "profissao": (prof.get("profissao") or "").strip().lower(),
        "especializacoes": [],
        "aliases": {},
    }
    # especializações podem vir em lista ou campos separados
    if isinstance(prof.get("especializacoes"), list):
        prof_context["especializacoes"] = [str(x).strip().lower() for x in prof["especializacoes"] if x]
    else:
        for key in ("especializacao1","especializacao2"):
            v = prof.get(key)
            if v: prof_context["especializacoes"].append(str(v).strip().lower())

    # aliases custom (opcional): profissionais/{uid}/aliases (doc) ou campo 'aliases' no doc raiz
    custom_aliases = {}
    doc_aliases = get_doc(f"profissionais/{uid}/aliases")
    if isinstance(doc_aliases, dict) and doc_aliases:
        custom_aliases = doc_aliases  # { "baixar a melena": "Corte Masculino", ... }
    elif isinstance(prof.get("aliases"), dict):
        custom_aliases = prof["aliases"]
    prof_context["aliases"] = custom_aliases
    return prof_context

def _profession_synonyms(profissao: str, especializacoes: List[str]) -> Dict[str, List[str]]:
    """
    Mapa de sinônimos por profissão → serviço(s) alvo.
    Pode ser expandido; também é complementado por aliases custom do Firestore.
    """
    p = (profissao or "").lower()
    espec = set((especializacoes or []))

    base: Dict[str, List[str]] = {}

    # Barbeiro / cabelereiro
    if "barbeiro" in p or "cabele" in p:
        base.update({
            "corte": ["corte masculino","corte feminino","corte"],
            "barba": ["barba"],
            "sombra": ["sobrancelha","design de sobrancelha","sobrancelha masculina"],
            "baixar a melena": ["corte masculino"],
            "pezinho": ["acabamento","pezinho"],
            "tintura": ["coloração","tintura"],
        })

    # Dentista
    if "dent" in p:
        base.update({
            "limpeza": ["profilaxia","limpeza"],
            "clareamento": ["clareamento dental","clareamento"],
            "canal": ["tratamento de canal","endodontia"],
            "aparelho": ["ortodontia","avaliação ortodôntica"],
            "restauração": ["restauração","resina"],
        })

    # Pet (banho e tosa)
    if "pet" in p or "tosa" in p or "banho" in p:
        base.update({
            "banho": ["banho"],
            "tosa": ["tosa","tosa higiênica","tosa completa"],
            "unha": ["corte de unha","unha"],
            "higiene": ["higienização","limpeza"],
        })

    # Advogado
    if "advog" in p or "direito" in p:
        base.update({
            "consulta": ["consulta","consulta jurídica"],
            "contrato": ["revisão de contrato","elaboração de contrato"],
            "trabalhista": ["consulta trabalhista"],
            "civil": ["consulta cível"],
        })

    # Artesão / designer
    if "artes" in p or "artesã" in p or "designer" in p:
        base.update({
            "personalizado": ["produto personalizado","sob medida"],
            "aula": ["aula","mentoria criativa"],
            "reparo": ["conserto","reparo"],
        })

    # Especializações podem reforçar termos (exemplo simples)
    if "barba" in espec:
        base.setdefault("barba", ["barba"])
    if "clareamento" in espec:
        base.setdefault("clareamento", ["clareamento"])

    return base

# ========== Preços (agregador 3 fontes) ==========
def _normalize_item(it: Dict[str, Any]) -> Dict[str, Any]:
    """Padroniza campos nome, preco, duracaoMin e mantém extras."""
    nome = it.get("nome") or it.get("nomeLower") or it.get("_id") or "serviço"
    preco = it.get("preco", it.get("valor"))
    dur = it.get("duracaoMin", it.get("duracaoPadraoMin", it.get("duracao")))
    ativo = it.get("ativo", True)
    out = {**it}
    out["nome"] = str(nome)
    out["preco"] = preco
    if dur is not None: out["duracaoMin"] = dur
    out["ativo"] = ativo
    out["nomeLower"] = _strip_accents_lower(out["nome"])
    return out

def _load_prices(uid: str) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []

    # (A) Doc principal → campo 'precos'
    prof = get_doc(f"profissionais/{uid}") or {}
    precos = prof.get("precos")
    if isinstance(precos, dict):
        if "itens" in precos and isinstance(precos["itens"], list):
            for it in precos["itens"]:
                if not isinstance(it, dict): continue
                if it.get("ativo", True):
                    items.append(_normalize_item(it))
        else:
            # mapa simples: { "Corte masculino": 50, ... }
            for nome, valor in precos.items():
                items.append(_normalize_item({"nome": nome, "preco": valor, "ativo": True}))

    # (B) Coleção /precos
    try:
        col = list_collection(f"profissionais/{uid}/precos", limit=500)
        for it in col:
            if (it.get("ativo", True)):
                items.append(_normalize_item(it))
    except Exception as e:
        logging.info("[PRICES] erro lendo /precos: %s", e)

    # (C) Coleção /produtosEServicos
    try:
        col2 = list_collection(f"profissionais/{uid}/produtosEServicos", limit=500)
        for it in col2:
            if (it.get("ativo", True)):
                items.append(_normalize_item(it))
    except Exception as e:
        logging.info("[PRICES] erro lendo /produtosEServicos: %s", e)

    # Dedup por nomeLower (primeiro ganha)
    seen = set()
    uniq: List[Dict[str, Any]] = []
    for it in items:
        key = it.get("nomeLower","").strip()
        if not key or it.get("ativo") is False:
            continue
        if key in seen: 
            continue
        seen.add(key)
        uniq.append(it)

    return uniq

def _render_price_table(items: List[Dict[str, Any]], uid: str, debug_counts: Dict[str,int]) -> str:
    if not items:
        return "Ainda não tenho uma tabela de preços publicada. 🙏"
    lines = [f"[DEBUG] uid={uid} map={(debug_counts.get('map') or 0)} precos={(debug_counts.get('precos') or 0)} prodServ={(debug_counts.get('ps') or 0)} total={len(items)}"]
    for it in items[:20]:
        nome = it.get("nome","serviço")
        dur = it.get("duracaoMin") or "?"
        val = it.get("preco") if it.get("preco") not in (None,"") else "?"
        lines.append(f"• {nome} — {dur}min — {_format_brl(val)}")
    return "\n".join(lines)

def _count_sources(uid: str) -> Dict[str,int]:
    c = {"map":0,"precos":0,"ps":0}
    prof = get_doc(f"profissionais/{uid}") or {}
    precos = prof.get("precos")
    if isinstance(precos, dict):
        if "itens" in precos and isinstance(precos["itens"], list):
            c["map"] = len(precos["itens"])
        else:
            c["map"] = len(precos)
    try:
        c["precos"] = len(list_collection(f"profissionais/{uid}/precos", limit=500))
    except Exception:
        pass
    try:
        c["ps"] = len(list_collection(f"profissionais/{uid}/produtosEServicos", limit=500))
    except Exception:
        pass
    return c

def _match_by_synonyms(text: str, items: List[Dict[str, Any]], prof_ctx: Dict[str,Any]) -> Optional[Tuple[str, Any]]:
    """Tenta casar por sinônimos (profissão/especializações + aliases custom)."""
    t = _strip_accents_lower(text)
    # aliases custom do Firestore têm prioridade
    aliases_map: Dict[str,str] = prof_ctx.get("aliases") or {}
    for alias, target in aliases_map.items():
        if _strip_accents_lower(alias) in t:
            # busca item cujo nome contém target
            target_norm = _strip_accents_lower(str(target))
            for it in items:
                if target_norm and target_norm in it.get("nomeLower",""):
                    return it.get("nome"), it.get("preco")

    # sinônimos padrão por profissão
    syn = _profession_synonyms(prof_ctx.get("profissao",""), prof_ctx.get("especializacoes") or [])
    for alias, candidates in syn.items():
        if _strip_accents_lower(alias) in t:
            # encontra o primeiro candidato presente
            for cand in candidates:
                cand_norm = _strip_accents_lower(cand)
                for it in items:
                    if cand_norm in it.get("nomeLower",""):
                        return it.get("nome"), it.get("preco")
    return None

def _find_price(items: List[Dict[str, Any]], text: str, prof_ctx: Dict[str,Any]) -> Optional[Tuple[str, Any]]:
    # 1) sinônimos por profissão/aliases custom
    hit = _match_by_synonyms(text, items, prof_ctx)
    if hit: return hit

    # 2) heurística simples por tokens do nome
    t = _strip_accents_lower(text)
    for it in items:
        nome = it.get("nomeLower","")
        if not nome: continue
        # casa por palavra significativa (>=4 chars) do nome
        for tok in re.findall(r"[a-z0-9]{4,}", nome):
            if tok in t:
                return it.get("nome"), it.get("preco")

    # 3) fallback por termos comuns
    for key in ("corte","barba","banho","tosa","limpeza","clareamento","consulta","contrato"):
        if key in t:
            for it in items:
                if key in it.get("nomeLower",""):
                    return it.get("nome"), it.get("preco")
    return None

# ========== FAQ ==========
def _load_faq(uid: str, key: str) -> Optional[str]:
    doc = get_doc(f"profissionais/{uid}/faq/{key}")
    if not doc: return None
    # suporta variações: { variacoes: ["...", "..."] } ou { texto: "..." }
    if isinstance(doc.get("variacoes"), list) and doc["variacoes"]:
        # pick determinístico por dia-do-ano (parecer humano)
        idx = (datetime.now(SP_TZ).timetuple().tm_yday) % len(doc["variacoes"])
        return str(doc["variacoes"][idx])
    return doc.get("texto")

# ========== STT ==========
def stt_transcribe(audio_bytes: bytes, mime_type: str = "audio/ogg", language: str = "pt-BR") -> str:
    # 1) Tentar um backend interno, se existir
    try:
        import inspect
        import services.audio_processing as ap
        for name in ["transcribe_audio_bytes","transcribe_audio","stt_transcribe","speech_to_text","stt_bytes","transcrever_audio_bytes","transcrever_audio"]:
            f = getattr(ap, name, None)
            if not callable(f): continue
            try:
                try:
                    text = f(audio_bytes, mime_type=mime_type, language=language)
                except TypeError:
                    try:
                        text = f(audio_bytes, language=language)
                    except TypeError:
                        try:
                            text = f(audio_bytes)
                        except TypeError:
                            sig = inspect.signature(f); kwargs={}
                            if "mime_type" in sig.parameters: kwargs["mime_type"] = mime_type
                            if "language" in sig.parameters: kwargs["language"] = language
                            text = f(audio_bytes, **kwargs)
                text = (text or "").strip()
                if text:
                    print(f"[STT] services.audio_processing.{name}='{text[:120]}'", flush=True)
                    return text
            except Exception as e:
                print(f"[STT] {name} falhou: {e}", flush=True)
    except Exception as e:
        print(f"[STT] módulo services.audio_processing indisponível: {e}", flush=True)

    # 2) Whisper (OpenAI), se habilitado
    try:
        if os.getenv("ENABLE_STT_OPENAI","true").lower() in ("1","true","yes"):
            api_key = os.getenv("OPENAI_API_KEY")
            if api_key and audio_bytes:
                lang = "pt" if language.lower().startswith("pt") else language.split("-")[0]
                files = {"file": ("audio.ogg", audio_bytes, mime_type or "audio/ogg")}
                data = {"model": "whisper-1", "language": lang}
                headers = {"Authorization": f"Bearer {api_key}"}
                resp = requests.post("https://api.openai.com/v1/audio/transcriptions", headers=headers, files=files, data=data, timeout=60)
                js = {}
                try: js = resp.json()
                except Exception: pass
                text = (js.get("text") if isinstance(js, dict) else "") or ""
                text = text.strip()
                print(f"[STT] openai whisper status={resp.status_code} text='{text[:120]}'", flush=True)
                return text
    except Exception as e:
        print(f"[STT] openai whisper erro: {e}", flush=True)

    print("[STT] nenhum backend retornou transcrição", flush=True)
    return ""

# ========== Normalizador PT-BR (datas/horas) ==========
_MONTHS = {
    "jan":1,"janeiro":1,"fev":2,"fevereiro":2,"mar":3,"marco":3,"março":3,"abr":4,"abril":4,"mai":5,"maio":5,
    "jun":6,"junho":6,"jul":7,"julho":7,"ago":8,"agosto":8,"set":9,"setembro":9,"out":10,"outubro":10,"nov":11,"novembro":11,"dez":12,"dezembro":12,
}
_UNITS = {
    "zero":0,"um":1,"uma":1,"primeiro":1,"dois":2,"duas":2,"tres":3,"três":3,"quatro":4,"cinco":5,"seis":6,"sete":7,"oito":8,"nove":9,"dez":10,
    "onze":11,"doze":12,"treze":13,"catorze":14,"quatorze":14,"quinze":15,"dezesseis":16,"desesseis":16,"dezessete":17,"desessete":17,"dezoito":18,"dezenove":19,
}
_TENS = {"vinte":20,"trinta":30,"quarenta":40,"cinquenta":50}
_WEEKDAYS = {"segunda":0,"segunda-feira":0,"terca":1,"terça":1,"terça-feira":1,"terca-feira":1,"quarta":2,"quarta-feira":2,"quinta":3,"quinta-feira":3,"sexta":4,"sexta-feira":4,"sabado":5,"sábado":5,"domingo":6}

def _words_to_int_pt(s: str):
    if not s: return None
    s = s.strip()
    if s in _UNITS: return _UNITS[s]
    if s in _TENS: return _TENS[s]
    m = re.match(r"(vinte|trinta|quarenta|cinquenta)\s+e\s+([a-z]+)$", s)
    if m:
        tens = _TENS.get(m.group(1), 0)
        unit = _UNITS.get(m.group(2), 0)
        return tens + (unit or 0)
    return None

def _extract_day_month_from_words(t: str):
    m = re.search(r"(?:\bdia\s+)?(?P<d>(\d{1,2}|[a-z]+))\s+de\s+(?P<m>[a-z]{3,12})", t)
    if not m: return None
    d_raw = m.group("d"); month_raw = m.group("m")
    mm = _MONTHS.get(month_raw)
    if not mm: return None
    if d_raw.isdigit(): dd = int(d_raw)
    else: dd = _words_to_int_pt(d_raw)
    if not dd: return None
    return dd, mm

def _extract_time_from_words(t: str):
    if re.search(r"\bmeio\s+dia\b", t):
        mi = 30 if re.search(r"\bmeio\s+dia\s+e\s+meia\b", t) else 0
        return 12, mi
    if re.search(r"\bmeia\s+noite\b", t):
        mi = 30 if re.search(r"\bmeia\s+noite\s+e\s+meia\b", t) else 0
        return 0, mi
    period = None
    if re.search(r"\bda\s+manha\b|\bde\s+manha\b|\bmanh[ãa]\b", t): period = "manha"
    elif re.search(r"\bda\s+tarde\b|\bde\s+tarde\b|\btarde\b", t): period = "tarde"
    elif re.search(r"\bda\s+noite\b|\bde\s+noite\b|\bnoite\b", t): period = "noite"
    m = re.search(r"\b(?:as|às)?\s*(?P<h>\d{1,2})(?:[:h](?P<m>\d{2}))?\s*(?:horas?)?", t)
    if m:
        hh = int(m.group("h")); mi = int(m.group("m")) if m.group("m") else 0
        if re.search(rf"\b{hh}\s+e\s+meia\b", t): mi = 30
        if period in ("tarde","noite") and 1 <= hh <= 11: hh += 12
        return hh, mi
    m2 = re.search(r"\b(?:as|às)?\s*([a-z]+)(?:\s*e\s*meia)?\s*(?:horas?)?", t)
    if m2:
        word = m2.group(1)
        hh = _words_to_int_pt(word)
        if hh is not None:
            mi = 30 if re.search(r"\b"+re.escape(word)+r"\s*e\s*meia\b", t) else 0
            if period in ("tarde","noite") and 1 <= hh <= 11: hh += 12
            return hh, mi
    return None

def _weekday_to_date(next_text: str, weekday_word: str):
    if weekday_word not in _WEEKDAYS: return None
    today = datetime.now(SP_TZ).date()
    wd_target = _WEEKDAYS[weekday_word]; wd_today = today.weekday()
    delta = (wd_target - wd_today) % 7
    if delta == 0: delta = 7
    if re.search(r"\bproxim[aoa]|\bsemana\s+que\s+vem", next_text): delta += 7
    return today + timedelta(days=delta)

def _normalize_datetime_pt(t: str) -> str:
    if re.search(r"\b\d{1,2}[\/\.]\d{1,2}\b", t) and re.search(r"\b\d{1,2}[:h]\d{2}\b", t):
        return t
    base_now = datetime.now(SP_TZ); dd = mm = None
    if "depois de amanha" in t: base = base_now + timedelta(days=2); dd, mm = base.day, base.month
    elif "amanha" in t: base = base_now + timedelta(days=1); dd, mm = base.day, base.month
    if dd is None:
        for w in sorted(_WEEKDAYS.keys(), key=len, reverse=True):
            if re.search(rf"\b{re.escape(w)}\b", t):
                d = _weekday_to_date(t, w); 
                if d: dd, mm = d.day, d.month; break
    dm = _extract_day_month_from_words(t)
    if dd is None and dm: dd, mm = dm
    ht = _extract_time_from_words(t)
    if dd and mm and ht:
        hh, mi = ht
        return f"{t} {dd:02d}/{mm:02d} {hh:02d}:{mi:02d}"
    return t

def _parse_datetime_br(text_norm: str):
    d = re.search(r"(\b\d{1,2})[\/\.-](\d{1,2})(?:[\/\.-](\d{2,4}))?", text_norm)
    h = re.search(r"(\b\d{1,2})[:h](\d{2})", text_norm)
    if not d or not h: return None
    day = int(d.group(1)); month = int(d.group(2)); year_g = d.group(3)
    year = int(year_g) + (2000 if year_g and len(year_g) == 2 else 0) if year_g else datetime.now(SP_TZ).year
    hour = int(h.group(1)); minute = int(h.group(2))
    try:
        return datetime(year, month, day, hour, minute, tzinfo=SP_TZ)
    except Exception:
        return None

# ========== Sessão (Firestore) ==========
def _sess_ref(uid: str, wa_id: str):
    return DB.collection(f"profissionais/{uid}/sessions").document(wa_id)

def _get_session(uid: str, wa_id: str) -> dict:
    try:
        snap = _sess_ref(uid, wa_id).get()
        sess = snap.to_dict() if snap.exists else {}
    except Exception as e:
        print(f"[WA_BOT][SESS] get erro: {e}", flush=True); sess = {}
    try:
        ts_str = sess.get("updatedAt") or sess.get("createdAt")
        if ts_str:
            ts = datetime.fromisoformat(ts_str.replace("Z","+00:00"))
            if datetime.now(SP_TZ) - ts > timedelta(minutes=30):
                _clear_session(uid, wa_id); return {}
    except Exception:
        pass
    return sess or {}

def _save_session(uid: str, wa_id: str, sess: dict):
    now = datetime.now(SP_TZ).isoformat()
    sess = {**(sess or {}), "updatedAt": now}
    if "createdAt" not in sess: sess["createdAt"] = now
    try:
        _sess_ref(uid, wa_id).set(sess)
    except Exception as e:
        print(f"[WA_BOT][SESS] save erro: {e}", flush=True)

def _clear_session(uid: str, wa_id: str):
    try:
        _sess_ref(uid, wa_id).delete()
    except Exception as e:
        print(f"[WA_BOT][SESS] clear erro: {e}", flush=True)

# ========== Agendamento ==========
def _resolve_cliente_id(uid_default: str, wa_id: str, to_msisdn: str) -> str:
    try:
        if wa_id:
            q = (DB.collection(f"profissionais/{uid_default}/clientes").where("waId","==",wa_id).limit(1).stream())
            for d in q: return d.id
    except Exception as e:
        print(f"[WA_BOT][AGENDA] lookup cliente por waId falhou: {e}", flush=True)
    return wa_id or to_msisdn or "anon"

def _find_target_agendamento(uid: str, cliente_id: str, wa_id: str, telefone: str):
    estados = ["solicitado","confirmado"]; candidatos = []
    try:
        q = (DB.collection(f"profissionais/{uid}/agendamentos").where("clienteId","==",cliente_id).where("estado","in",estados).limit(10).stream())
        for d in q: obj = d.to_dict() or {}; obj["_id"] = d.id; candidatos.append(obj)
    except Exception as e:
        print(f"[WA_BOT][AGENDA] query por clienteId falhou: {e}", flush=True)
    if not candidatos and wa_id:
        try:
            q = (DB.collection(f"profissionais/{uid}/agendamentos").where("clienteWaId","==",wa_id).where("estado","in",estados).limit(10).stream())
            for d in q: obj = d.to_dict() or {}; obj["_id"] = d.id; candidatos.append(obj)
        except Exception as e:
            print(f"[WA_BOT][AGENDA] query por clienteWaId falhou: {e}", flush=True)
    if not candidatos and telefone:
        try:
            q = (DB.collection(f"profissionais/{uid}/agendamentos").where("telefone","==",telefone).where("estado","in",estados).limit(10).stream())
            for d in q: obj = d.to_dict() or {}; obj["_id"] = d.id; candidatos.append(obj)
        except Exception as e:
            print(f"[WA_BOT][AGENDA] query por telefone falhou: {e}", flush=True)
    if not candidatos: return None
    def _iso_or_none(s): 
        try: return datetime.fromisoformat(s.replace("Z","+00:00"))
        except Exception: return None
    candidatos.sort(key=lambda x: _iso_or_none(x.get("createdAt") or x.get("inicio")) or datetime.min.replace(tzinfo=SP_TZ), reverse=True)
    return candidatos[0]

def _build_and_save_agendamento(uid_default: str, value: dict, to_msisdn: str, svc: dict, dt: datetime, body_text: str):
    # dados do contato
    wa_id = ""; nome_contato = ""
    try:
        contacts = value.get("contacts") or []
        if contacts and isinstance(contacts, list):
            wa_id = contacts[0].get("wa_id") or ""
            prof = contacts[0].get("profile") or {}
            nome_contato = prof.get("name") or ""
    except Exception:
        pass

    dur = int(svc.get("duracaoMin") or 60)
    fim = dt + timedelta(minutes=dur)
    servico_id = svc.get("id") or f"map:{(svc.get('nomeLower') or svc.get('nome') or 'servico').strip().lower()}"
    cliente_id = _resolve_cliente_id(uid_default, wa_id, to_msisdn)

    ag = {
        "estado": "solicitado",
        "canal": "whatsapp",
        "clienteId": cliente_id,
        "clienteWaId": wa_id,
        "clienteNome": nome_contato,
        "telefone": to_msisdn,
        "servicoId": servico_id,
        "servicoNome": svc.get("nome") or svc.get("nomeLower"),
        "duracaoMin": dur,
        "preco": svc.get("preco"),
        "dataHora": dt.isoformat(),
        "inicio": dt.isoformat(),
        "fim": fim.isoformat(),
        "observacoes": (body_text or "")[:500],
        "createdAt": datetime.now(SP_TZ).isoformat(),
    }

    saved_id = None
    try:
        ok, motivo, _ = validar_agendamento_v1(uid_default, ag)
        if not ok:
            return False, f"Não foi possível agendar: {motivo}"
        saved_id = salvar_agendamento(uid_default, ag)
        if isinstance(saved_id, dict): saved_id = saved_id.get("id") or saved_id.get("ag_id")
    except Exception as e:
        print(f"[WA_BOT][AGENDA] salvar via schedule falhou: {e}", flush=True)
        try:
            ref = DB.collection(f"profissionais/{uid_default}/agendamentos").document()
            ref.set(ag); saved_id = ref.id
        except Exception as e2:
            print(f"[WA_BOT][AGENDA][FALLBACK_SAVE] erro: {e2}", flush=True)
            return False, "Tive um problema ao salvar seu agendamento. Pode tentar novamente em instantes?"

    dia = dt.strftime("%d/%m"); hora = dt.strftime("%H:%M")
    preco = ag.get("preco"); preco_txt = f" — {_format_brl(preco)}" if preco not in (None, "", "?") else ""
    sid = f" (id {saved_id})" if saved_id else ""
    return True, f"✅ Agendamento solicitado: {ag['servicoNome']} em {dia} às {hora}{preco_txt}.{sid}\nSe precisar alterar, responda: reagendar <dd/mm> <hh:mm>"

# ========== Fluxos de alto nível ==========
def _reply_prices(uid: str, to: str, send_text):
    counts = _count_sources(uid)
    items = _load_prices(uid)
    msg = _render_price_table(items, uid, counts)
    logging.info(f"[WHATSAPP][OUTBOUND] prices count={len(items)} map={counts.get('map')} precos={counts.get('precos')} ps={counts.get('ps')}")
    return send_text(to, msg)

def _reply_price_from_cache_or_data(uid: str, to: str, user_text: str, send_text):
    key = f"{uid}:price:{re.sub(r'\\s+', ' ', (user_text or '').strip().lower())[:120]}"
    cached = cache_get(key)
    if cached:
        logging.info("[CACHE] price hit")
        return send_text(to, cached)
    items = _load_prices(uid)
    prof_ctx = _load_prof_context(uid)
    found = _find_price(items, user_text or "", prof_ctx)
    if not found:
        return _reply_prices(uid, to, send_text)
    nome, valor = found
    resp = f"{nome}: {_format_brl(valor)} 😉"
    cache_put(key, resp)
    return send_text(to, resp)

def _reply_faq(uid: str, to: str, faq_key: str, send_text):
    ans = _load_faq(uid, faq_key)
    if not ans:
        return send_text(to, "Posso te ajudar com endereço, horários, telefone e Pix. O que você precisa?")
    return send_text(to, ans)

def _reply_schedule(uid: str, to: str, serviceName: Optional[str], dateText: str, timeText: str, send_text, value: dict, body_text: str):
    ok, reason = can_book(dateText, timeText)
    if not ok:
        return send_text(to, f"Não consegui agendar: {reason}")
    # tentar casar serviceName com a lista
    items = _load_prices(uid)
    svc = None
    if serviceName:
        s_norm = _strip_accents_lower(serviceName)
        for it in items:
            if s_norm in it.get("nomeLower",""):
                svc = it; break
    if not svc and items: svc = items[0]  # fallback educado
    # construir data/hora
    dt = None
    try:
        dd, mm = [int(x) for x in re.findall(r"\d{1,2}", dateText)[:2]]
        hh, mi = [int(x) for x in re.findall(r"\d{1,2}", timeText)[:2]]
        dt = datetime(datetime.now(SP_TZ).year, mm, dd, hh, mi, tzinfo=SP_TZ)
    except Exception:
        pass
    if not dt:
        return send_text(to, "Não entendi a data/hora. Pode enviar no formato 01/09 14:00?")
    ok2, msg = _build_and_save_agendamento(uid, value, to, svc or {"nome":"serviço"}, dt, body_text)
    return send_text(to, msg if ok2 else f"Não consegui agendar: {msg}")

def _agendar_fluxo(value: dict, to_msisdn: str, uid_default: str, app_tag: str, body_text: str, text_norm: str, items, sess: dict, wa_id: str):
    # serviço
    svc = None
    if sess.get("servicoId") or sess.get("servicoNome"):
        for it in items:
            if it.get("id") == sess.get("servicoId") or it.get("nomeLower") == (sess.get("servicoNome") or "").lower():
                svc = it; break
    if not svc:
        # procurar pelo texto
        prof_ctx = _load_prof_context(uid_default)
        hit = _find_price(items, text_norm, prof_ctx)
        if hit:
            # reconstruir it pelo nome
            name = _strip_accents_lower(hit[0])
            for it in items:
                if it.get("nomeLower") == name:
                    svc = it; break

    # data/hora
    text_norm2 = _normalize_datetime_pt(text_norm)
    dt = _parse_datetime_br(text_norm2)
    if not dt and sess.get("dataHora"):
        try: dt = datetime.fromisoformat(sess["dataHora"])
        except Exception: dt = None

    have_svc = svc is not None
    have_dt = dt is not None

    if have_svc and have_dt:
        ok, msg = _build_and_save_agendamento(uid_default, value, to_msisdn, svc, dt, body_text)
        if ok: _clear_session(uid_default, wa_id)
        return msg

    new_sess = {
        "intent": "agendar",
        "servicoId": svc.get("id") if svc else None,
        "servicoNome": (svc.get("nomeLower") or svc.get("nome")) if svc else None,
        "dataHora": dt.isoformat() if dt else None,
    }
    _save_session(uid_default, wa_id, new_sess)

    if not have_svc and not have_dt:
        nomes = ", ".join([it.get("nome") for it in items[:5]]) or "o serviço"
        return f"Vamos agendar! Qual serviço você quer ({nomes}...) e para quando? Ex.: 01/09 14:00"
    if not have_svc:
        nomes = ", ".join([it.get("nome") for it in items[:5]]) or "o serviço"
        return f"Certo. Para qual serviço? Tenho: {nomes}."
    return "Perfeito. Qual data e horário? Ex.: 01/09 14:00, ou 'terça 10h', ou 'semana que vem sexta 9:30'."

def _reagendar_fluxo(value: dict, to_msisdn: str, uid_default: str, app_tag: str, body_text: str, text_norm: str, sess: dict, wa_id: str):
    text_norm2 = _normalize_datetime_pt(text_norm)
    dt = _parse_datetime_br(text_norm2)
    if not dt and sess.get("dataHora"):
        try: dt = datetime.fromisoformat(sess["dataHora"])
        except Exception: dt = None
    if not dt:
        _save_session(uid_default, wa_id, {"intent":"reagendar"})
        return "Qual nova data e horário? Ex.: 02/09 10:00, ou 'quarta 15h'."

    wa = ""
    try:
        contacts = value.get("contacts") or []
        if contacts and isinstance(contacts, list):
            wa = contacts[0].get("wa_id") or ""
    except Exception:
        pass
    cliente_id = _resolve_cliente_id(uid_default, wa, to_msisdn)
    alvo = _find_target_agendamento(uid_default, cliente_id, wa, to_msisdn)
    if not alvo:
        return ("Não encontrei um agendamento ativo seu.\n"
                "Você pode enviar: reagendar <ID> <dd/mm> <hh:mm> (ID aparece na confirmação)")

    ag_id = alvo.get("_id")
    try:
        body = {"acao":"reagendar","dataHora": dt.isoformat()}
        atualizar_estado_agendamento(uid_default, ag_id, body)
    except Exception as e:
        print(f"[WA_BOT][AGENDA][REAGENDAR] erro: {e}", flush=True)
        return "Não consegui reagendar agora. Pode tentar novamente em instantes?"

    _clear_session(uid_default, wa_id)
    dia = dt.strftime("%d/%m"); hora = dt.strftime("%H:%M")
    nome = alvo.get("servicoNome") or "serviço"
    return f"✅ Reagendamento solicitado: {nome} para {dia} às {hora} (id {ag_id})"

# ========== Entrada principal ==========
def process_change(value: Dict[str, Any], send_text_fn, uid_default: str, app_tag: str):
    """
    value: payload 'change.value' da Meta
    send_text_fn: função injetada por app.py para enviar texto
    """
    messages = value.get("messages", [])
    if not messages:
        return

    for m in messages:
        to = m.get("from") or _pick_phone(value) or ""
        msg_type = m.get("type")
        text_in = ""

        # -------- Budget gate (áudio) ----------
        if msg_type == "audio":
            if not can_use_audio():
                logging.info("[BUDGET] audio blocked")
                send_text_fn(to, "🎧 Para economizar, estou respondendo por texto no momento. Pode me mandar em texto?")
                continue
            charge("stt_per_15s", float(os.getenv("STT_SECONDS_AVG", "15"))/15.0)
            # download + STT
            token = os.getenv("WHATSAPP_TOKEN")
            gv = GRAPH_VERSION_DEFAULT
            audio = m.get("audio") or {}
            media_id = audio.get("id")
            try:
                if not media_id:
                    send_text_fn(to, fallback_text(app_tag, "audio:sem-media_id")); continue
                info = requests.get(
                    f"https://graph.facebook.com/{gv}/{media_id}",
                    headers={"Authorization": f"Bearer {token}"}, timeout=15
                ).json()
                media_url = info.get("url")
                if not media_url:
                    send_text_fn(to, fallback_text(app_tag, "audio:sem-url")); continue
                r = requests.get(media_url, headers={"Authorization": f"Bearer {token}"}, timeout=30)
                audio_bytes = r.content or b""
                if not audio_bytes:
                    send_text_fn(to, fallback_text(app_tag, "audio:bytes=0")); continue
                mt = (audio.get("mime_type") or "audio/ogg").split(";")[0].strip()
                text_in = stt_transcribe(audio_bytes, mime_type=mt, language="pt-BR")
            except Exception as e:
                print("[WA_BOT][AUDIO][ERROR]", repr(e), flush=True)
                send_text_fn(to, fallback_text(app_tag, "audio:error"))
                continue

        elif msg_type == "text":
            text_in = (m.get("text") or {}).get("body", "")
        else:
            send_text_fn(to, "Recebi sua mensagem. Posso te enviar preços, horários, endereço ou agendar um horário.")
            continue

        # -------- NLU leve sempre-on ----------
        charge("nlp_mini", 1.0)
        nlu = extract_intent(text_in or "")
        intent = (nlu.get("intent") or "fallback").lower()
        serviceName = nlu.get("serviceName")
        dateText = nlu.get("dateText")
        timeText = nlu.get("timeText")

        text_norm = _strip_accents_lower(text_in)
        # comandos rápidos de sessão
        if re.search(r"\b(cancelar|limpar|resetar|apagar\s+(conversa|sess[aã]o))\b", text_norm):
            try:
                wa_id = m.get("from") or to
                _clear_session(uid_default, wa_id)
            except Exception: pass
            send_text_fn(to, "Ok, limpei nossa conversa. Se quiser recomeçar, diga 'agendar' ou 'precos'.")
            continue

        # -------- Roteamento de intents baratas ----------
        if intent == "precos":
            _reply_prices(uid_default, to, send_text_fn)
            continue

        if is_price_question(text_in):
            _reply_price_from_cache_or_data(uid_default, to, text_in, send_text_fn)
            continue

        if intent in ("localizacao","horarios","telefone","pagamento"):
            faq_map = {"localizacao":"endereco","horarios":"horarios","telefone":"telefone","pagamento":"pix"}
            _reply_faq(uid_default, to, faq_map[intent], send_text_fn)
            continue

        if intent == "agendar" and dateText and timeText:
            _reply_schedule(uid_default, to, serviceName, dateText, timeText, send_text_fn, value, text_in)
            continue

        if intent == "reagendar":
            wa_id = m.get("from") or to
            sess = _get_session(uid_default, wa_id)
            reply = _reagendar_fluxo(value, to, uid_default, app_tag, text_in, text_norm, sess, wa_id)
            send_text_fn(to, reply)
            continue

        # -------- Slot-filling de agendamento (sem palavras mágicas) ----------
        wa_id = m.get("from") or to
        sess = _get_session(uid_default, wa_id)
        if sess.get("intent") in ("agendar","reagendar"):
            if sess["intent"] == "agendar":
                items = _load_prices(uid_default)
                reply = _agendar_fluxo(value, to, uid_default, app_tag, text_in, text_norm, items, sess, wa_id)
                send_text_fn(to, reply)
                continue
            else:
                reply = _reagendar_fluxo(value, to, uid_default, app_tag, text_in, text_norm, sess, wa_id)
                send_text_fn(to, reply)
                continue

        # -------- Complexo? usar GPT-4o se permitido (degradável) ----------
        if can_use_gpt4o() and (os.getenv("USE_LLM_FOR_ALL","true").lower() == "true"):
            charge("gpt4o_msg", 1.0)
            send_text_fn(to, "Resposta detalhada (IA) 🤖 — (modo completo).")
        else:
            logging.info("[BUDGET] degraded to mini-only")
            send_text_fn(to, "Posso te ajudar com preços, agendamentos e informações rápidas. O que você precisa?")

    # statuses
    for st in value.get("statuses", []):
        print(f"[WA_BOT][STATUS] id={st.get('id')} status={st.get('status')} ts={st.get('timestamp')} recipient={st.get('recipient_id')} errors={st.get('errors')}", flush=True)
