# services/wa_bot.py
# Lógica do bot WhatsApp (texto + áudio com STT) + preços, agendar e reagendar
# Sessão/slot-filling leve (Firestore) + normalizador PT-BR (meses, números por extenso, 'e meia',
# períodos (manhã/tarde/noite), dias da semana, 'amanhã/semana que vem').

import os
import re
import json
import requests
import unicodedata
from services.openai import nlu_intent as nlu
from datetime import datetime, timedelta, timezone
from services import db as dbsvc

DB = dbsvc.db
SP_TZ = timezone(timedelta(hours=-3))  # America/Sao_Paulo (sem DST)

# ========== Utils básicos ==========
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

def fallback_text(app_tag: str, context: str) -> str:
    return f"[FALLBACK] MEI Robo PROD :: {app_tag} :: {context}\nDigite 'precos' para ver a lista."

def _detect_keyword(body: str):
    t = _strip_accents_lower(body)
    if any(k in t for k in ["preco","precos","preços","tabela","lista","valores",
                            "servico","servicos","serviço","serviços"]):
        return "precos"
    if "agendar" in t or "agenda " in t or "marcar" in t or "agendamento" in t or "reservar" in t:
        return "agendar"
    if any(k in t for k in ["reagendar","remarcar","mudar horario","mudar horário","trocar horario","trocar horário"]):
        return "reagendar"
    if any(k in t for k in ["cancelar","limpar","resetar","apagar conversa","apagar sessão","apagar sessao"]):
        return "cancelar"
    return None

# ========== Preços ==========
def load_prices(uid: str):
    """Retorna (items, debug). Cada item: id/nome/nomeLower/duracaoMin|duracao/preco|valor/ativo."""
    doc = DB.collection("profissionais").document(uid).get()
    root = doc.to_dict() if doc.exists else {}
    map_items = []
    if root and isinstance(root.get("precos"), dict):
        for nome, it in (root.get("precos") or {}).items():
            if isinstance(it, dict) and it.get("ativo", True):
                nomeLower = (nome or "").strip().lower()
                item = {"id": f"map:{nomeLower}", "nome": nome, "nomeLower": nomeLower}
                item.update(it)
                map_items.append(item)

    ps_items = []
    try:
        q = (DB.collection("profissionais").document(uid)
                .collection("produtosEServicos")
                .where("ativo", "==", True).stream())
        for d in q:
            obj = d.to_dict() or {}
            if obj.get("ativo", True):
                obj["id"] = d.id
                obj["nomeLower"] = obj.get("nomeLower") or (obj.get("nome", "") or "").lower()
                ps_items.append(obj)
    except Exception as e:
        print(f"[prices] erro lendo subcol produtosEServicos: {e}", flush=True)

    dedup = {}
    for it in map_items + ps_items:
        key = (it.get("nomeLower") or "").strip()
        if key and key not in dedup:
            dedup[key] = it

    items = sorted(dedup.values(), key=lambda x: x.get("nomeLower",""))
    debug = {"map_count": len(map_items), "ps_count": len(ps_items), "total": len(items)}
    return items, debug

def format_prices_reply(uid: str, items, debug):
    lines = [f"[DEBUG] uid={uid} map={debug['map_count']} prodServ={debug['ps_count']} total={debug['total']}"]
    if not items:
        lines.append("⚠️ Nenhum serviço ativo encontrado.")
        return "\n".join(lines)
    for it in items[:12]:
        nome = it.get("nome") or it.get("nomeLower") or "serviço"
        dur = it.get("duracaoMin") or it.get("duracao") or "?"
        val = it.get("preco") or it.get("valor") or "?"
        lines.append(f"- {nome} — {dur}min — R${val}")
    return "\n".join(lines)

def _choose_service(items, text_norm: str):
    """Escolhe serviço pela melhor ocorrência; se só 1, usa direto."""
    if not items:
        return None
    if len(items) == 1:
        return items[0]
    best = None
    best_len = 0
    for it in items:
        alias = (it.get("nomeLower") or it.get("nome") or "").lower()
        alias_norm = _strip_accents_lower(alias)
        if alias_norm and alias_norm in text_norm and len(alias_norm) > best_len:
            best = it
            best_len = len(alias_norm)
    return best

# ========== STT ==========
def stt_transcribe(audio_bytes: bytes, mime_type: str = "audio/ogg", language: str = "pt-BR") -> str:
    # 1) tentar services.audio_processing com nomes comuns
    try:
        import inspect
        import services.audio_processing as ap
        for name in ["transcribe_audio_bytes","transcribe_audio","stt_transcribe",
                     "speech_to_text","stt_bytes","transcrever_audio_bytes","transcrever_audio"]:
            f = getattr(ap, name, None)
            if not callable(f):
                continue
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
                            sig = inspect.signature(f)
                            kwargs = {}
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

    # 2) Whisper (opcional)
    try:
        if os.getenv("ENABLE_STT_OPENAI","true").lower() in ("1","true","yes"):
            api_key = os.getenv("OPENAI_API_KEY")
            if api_key and audio_bytes:
                lang = "pt" if language.lower().startswith("pt") else language.split("-")[0]
                files = {"file": ("audio.ogg", audio_bytes, mime_type or "audio/ogg")}
                data = {"model": "whisper-1", "language": lang}
                headers = {"Authorization": f"Bearer {api_key}"}
                resp = requests.post("https://api.openai.com/v1/audio/transcriptions",
                                     headers=headers, files=files, data=data, timeout=60)
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

# ========== Normalizador PT-BR de data/hora ==========
_MONTHS = {
    "jan":1,"janeiro":1,"fev":2,"fevereiro":2,"mar":3,"marco":3,"março":3,
    "abr":4,"abril":4,"mai":5,"maio":5,"jun":6,"junho":6,"jul":7,"julho":7,
    "ago":8,"agosto":8,"set":9,"setembro":9,"out":10,"outubro":10,"nov":11,"novembro":11,
    "dez":12,"dezembro":12,
}
_UNITS = {
    "zero":0,"um":1,"uma":1,"primeiro":1,"dois":2,"duas":2,"tres":3,"três":3,"quatro":4,
    "cinco":5,"seis":6,"sete":7,"oito":8,"nove":9,"dez":10,"onze":11,"doze":12,"treze":13,
    "catorze":14,"quatorze":14,"quinze":15,"dezesseis":16,"desesseis":16,"dezessete":17,"desessete":17,
    "dezoito":18,"dezenove":19,
}
_TENS = {"vinte":20,"trinta":30,"quarenta":40,"cinquenta":50}
_WEEKDAYS = {
    "segunda":0,"segunda-feira":0,
    "terca":1,"terça":1,"terça-feira":1,"terca-feira":1,
    "quarta":2,"quarta-feira":2,
    "quinta":3,"quinta-feira":3,
    "sexta":4,"sexta-feira":4,
    "sabado":5,"sábado":5,
    "domingo":6,
}

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
    if not m:
        return None
    d_raw = m.group("d")
    month_raw = m.group("m")
    mm = _MONTHS.get(month_raw)
    if not mm:
        return None
    if d_raw.isdigit():
        dd = int(d_raw)
    else:
        dd = _words_to_int_pt(d_raw)
    if not dd:
        return None
    return dd, mm

def _extract_time_from_words(t: str):
    # especiais
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
        hh = int(m.group("h"))
        mi = int(m.group("m")) if m.group("m") else 0
        if re.search(rf"\b{hh}\s+e\s+meia\b", t): mi = 30
        if period in ("tarde","noite") and 1 <= hh <= 11:
            hh += 12
        return hh, mi

    m2 = re.search(r"\b(?:as|às)?\s*([a-z]+)(?:\s*e\s*meia)?\s*(?:horas?)?", t)
    if m2:
        word = m2.group(1)
        hh = _words_to_int_pt(word)
        if hh is not None:
            mi = 30 if re.search(r"\b"+re.escape(word)+r"\s*e\s*meia\b", t) else 0
            if period in ("tarde","noite") and 1 <= hh <= 11:
                hh += 12
            return hh, mi

    return None

def _weekday_to_date(next_text: str, weekday_word: str):
    """Converte 'terça' (e variações) para a próxima data útil (ou 'próxima'/'semana que vem')."""
    if weekday_word not in _WEEKDAYS:
        return None
    today = datetime.now(SP_TZ).date()
    wd_target = _WEEKDAYS[weekday_word]
    wd_today = today.weekday()  # Monday=0
    delta = (wd_target - wd_today) % 7
    if delta == 0:
        delta = 7  # mesma semana -> próxima ocorrência
    # 'próxima' ou 'semana que vem' força pular uma semana
    if re.search(r"\bproxim[aoa]|\bsemana\s+que\s+vem", next_text):
        delta += 7
    return today + timedelta(days=delta)

def _normalize_datetime_pt(t: str) -> str:
    """Se não houver dd/mm hh:mm, tenta extrair por palavras e ANEXA ' dd/mm hh:mm' ao texto original."""
    if re.search(r"\b\d{1,2}[\/\.]\d{1,2}\b", t) and re.search(r"\b\d{1,2}[:h]\d{2}\b", t):
        return t

    base_now = datetime.now(SP_TZ)
    dd = mm = None

    # 'depois de amanha' / 'amanha'
    if "depois de amanha" in t:
        base = base_now + timedelta(days=2)
        dd, mm = base.day, base.month
    elif "amanha" in t:
        base = base_now + timedelta(days=1)
        dd, mm = base.day, base.month

    # dia da semana
    if dd is None:
        for w in sorted(_WEEKDAYS.keys(), key=len, reverse=True):
            if re.search(rf"\b{re.escape(w)}\b", t):
                d = _weekday_to_date(t, w)
                if d:
                    dd, mm = d.day, d.month
                    break

    # 'dia <x> de <mes>'
    if dd is None:
        dm = _extract_day_month_from_words(t)
        if dm:
            dd, mm = dm

    # hora
    hh = mi = None
    hm = re.search(r"\b(\d{1,2})[:h](\d{2})\b", t)
    if hm:
        hh, mi = int(hm.group(1)), int(hm.group(2))
        if re.search(r"\b(tarde|noite)\b", t) and 1 <= hh <= 11:
            hh += 12
    else:
        ht = _extract_time_from_words(t)
        if ht:
            hh, mi = ht

    if dd and mm and hh is not None and mi is not None:
        return f"{t} {dd:02d}/{mm:02d} {hh:02d}:{mi:02d}"
    return t

# ========== Parse dd/mm hh:mm ==========
def _parse_datetime_br(text_norm: str):
    d = re.search(r"(\b\d{1,2})[\/\.-](\d{1,2})(?:[\/\.-](\d{2,4}))?", text_norm)
    h = re.search(r"(\b\d{1,2})[:h](\d{2})", text_norm)
    if not d or not h:
        return None
    day = int(d.group(1)); month = int(d.group(2))
    year = d.group(3)
    year = int(year) + (2000 if year and len(year) == 2 else 0) if year else datetime.now(SP_TZ).year
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
        print(f"[WA_BOT][SESS] get erro: {e}", flush=True)
        sess = {}
    # expiração 30 min
    try:
        ts_str = sess.get("updatedAt") or sess.get("createdAt")
        if ts_str:
            ts = datetime.fromisoformat(ts_str.replace("Z","+00:00"))
            if datetime.now(SP_TZ) - ts > timedelta(minutes=30):
                _clear_session(uid, wa_id)
                return {}
    except Exception:
        pass
    return sess or {}

def _save_session(uid: str, wa_id: str, sess: dict):
    now = datetime.now(SP_TZ).isoformat()
    sess = {**(sess or {}), "updatedAt": now}
    if "createdAt" not in sess:
        sess["createdAt"] = now
    try:
        _sess_ref(uid, wa_id).set(sess)
    except Exception as e:
        print(f"[WA_BOT][SESS] save erro: {e}", flush=True)

def _clear_session(uid: str, wa_id: str):
    try:
        _sess_ref(uid, wa_id).delete()
    except Exception as e:
        print(f"[WA_BOT][SESS] clear erro: {e}", flush=True)

# ========== Construção/salvamento do agendamento ==========
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

    dur = int(svc.get("duracaoMin") or svc.get("duracao") or 60)
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
        "preco": svc.get("preco") or svc.get("valor"),
        "dataHora": dt.isoformat(),
        "inicio": dt.isoformat(),
        "fim": fim.isoformat(),
        "observacoes": (body_text or "")[:500],
        "createdAt": datetime.now(SP_TZ).isoformat(),
    }

    saved_id = None
    try:
        import services.schedule as sched
        ok, motivo, conflito = sched.validar_agendamento_v1(uid_default, ag)
        if not ok:
            return False, f"Não foi possível agendar: {motivo}"
        saved_id = sched.salvar_agendamento(uid_default, ag)
        if isinstance(saved_id, dict):
            saved_id = saved_id.get("id") or saved_id.get("ag_id")
    except Exception as e:
        print(f"[WA_BOT][AGENDA] validar/salvar via services.schedule falhou: {e}", flush=True)
        try:
            ref = DB.collection(f"profissionais/{uid_default}/agendamentos").document()
            ref.set(ag)
            saved_id = ref.id
        except Exception as e2:
            print(f"[WA_BOT][AGENDA][FALLBACK_SAVE] erro: {e2}", flush=True)
            return False, "Tive um problema ao salvar seu agendamento. Pode tentar novamente em instantes?"

    dia = dt.strftime("%d/%m"); hora = dt.strftime("%H:%M")
    preco = ag.get("preco")
    preco_txt = f" — R${preco}" if preco not in (None, "", "?") else ""
    sid = f" (id {saved_id})" if saved_id else ""
    return True, f"✅ Agendamento solicitado: {ag['servicoNome']} em {dia} às {hora}{preco_txt}.{sid}\nSe precisar alterar, responda: reagendar <dd/mm> <hh:mm>"

def _resolve_cliente_id(uid_default: str, wa_id: str, to_msisdn: str) -> str:
    try:
        if wa_id:
            q = (DB.collection(f"profissionais/{uid_default}/clientes")
                   .where("waId", "==", wa_id).limit(1).stream())
            for d in q:
                return d.id
    except Exception as e:
        print(f"[WA_BOT][AGENDA] lookup cliente por waId falhou: {e}", flush=True)
    return wa_id or to_msisdn or "anon"

def _find_target_agendamento(uid: str, cliente_id: str, wa_id: str, telefone: str):
    estados = ["solicitado", "confirmado"]
    candidatos = []
    try:
        q = (DB.collection(f"profissionais/{uid}/agendamentos")
               .where("clienteId", "==", cliente_id)
               .where("estado", "in", estados).limit(10).stream())
        for d in q:
            obj = d.to_dict() or {}; obj["_id"] = d.id; candidatos.append(obj)
    except Exception as e:
        print(f"[WA_BOT][AGENDA] query por clienteId falhou: {e}", flush=True)

    if not candidatos and wa_id:
        try:
            q = (DB.collection(f"profissionais/{uid}/agendamentos")
                   .where("clienteWaId", "==", wa_id)
                   .where("estado", "in", estados).limit(10).stream())
            for d in q:
                obj = d.to_dict() or {}; obj["_id"] = d.id; candidatos.append(obj)
        except Exception as e:
            print(f"[WA_BOT][AGENDA] query por clienteWaId falhou: {e}", flush=True)

    if not candidatos and telefone:
        try:
            q = (DB.collection(f"profissionais/{uid}/agendamentos")
                   .where("telefone", "==", telefone)
                   .where("estado", "in", estados).limit(10).stream())
            for d in q:
                obj = d.to_dict() or {}; obj["_id"] = d.id; candidatos.append(obj)
        except Exception as e:
            print(f"[WA_BOT][AGENDA] query por telefone falhou: {e}", flush=True)

    if not candidatos:
        return None

    def _iso_or_none(s):
        try: return datetime.fromisoformat(s.replace("Z","+00:00"))
        except Exception: return None

    candidatos.sort(key=lambda x: _iso_or_none(x.get("createdAt") or x.get("inicio")) or datetime.min.replace(tzinfo=SP_TZ), reverse=True)
    return candidatos[0]

# ========== Fluxos de alto nível ==========
def _agendar_fluxo(value: dict, to_msisdn: str, uid_default: str, app_tag: str, body_text: str, text_norm: str, items, sess: dict, wa_id: str):
    """Slot-filling: tenta preencher serviço e data/hora a partir de texto + sessão e agenda."""
    # serviço
    svc = None
    if sess.get("servicoId") or sess.get("servicoNome"):
        # recuperar serviço por nomeLower/id
        for it in items:
            if it.get("id") == sess.get("servicoId") or it.get("nomeLower") == sess.get("servicoNome"):
                svc = it; break
    if not svc:
        svc = _choose_service(items, text_norm)

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
        if ok:
            _clear_session(uid_default, wa_id)
        return msg

    # Atualizar sessão e perguntar o que falta
    new_sess = {
        "intent": "agendar",
        "servicoId": svc.get("id") if svc else None,
        "servicoNome": (svc.get("nomeLower") or svc.get("nome")) if svc else None,
        "dataHora": dt.isoformat() if dt else None,
    }
    _save_session(uid_default, wa_id, new_sess)

    if not have_svc and not have_dt:
        return "Vamos agendar! Qual serviço você quer e para quando? Ex.: Pitch na terça às 10h"
    if not have_svc:
        nomes = ", ".join([it.get("nome") or it.get("nomeLower") for it in items[:5]]) or "o serviço"
        return f"Certo. Para qual serviço? Tenho: {nomes}."
    return "Perfeito. Qual data e horário? Ex.: 01/09 14:00, ou 'terça 10h', ou 'semana que vem sexta 9:30'."

def _reagendar_fluxo(value: dict, to_msisdn: str, uid_default: str, app_tag: str, body_text: str, text_norm: str, sess: dict, wa_id: str):
    text_norm2 = _normalize_datetime_pt(text_norm)
    dt = _parse_datetime_br(text_norm2)
    if not dt and sess.get("dataHora"):
        try: dt = datetime.fromisoformat(sess["dataHora"])
        except Exception: dt = None

    if not dt:
        _save_session(uid_default, wa_id, {"intent": "reagendar"})
        return "Qual nova data e horário? Ex.: 02/09 10:00, ou 'quarta 15h'."

    # encontrar alvo e reagendar
    wa = ""; 
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
        import services.schedule as sched
        body = {"acao": "reagendar", "dataHora": dt.isoformat()}
        sched.atualizar_estado_agendamento(uid_default, ag_id, body)
    except Exception as e:
        print(f"[WA_BOT][AGENDA][REAGENDAR] erro: {e}", flush=True)
        return "Não consegui reagendar agora. Pode tentar novamente em instantes?"

    _clear_session(uid_default, wa_id)
    dia = dt.strftime("%d/%m"); hora = dt.strftime("%H:%M")
    nome = alvo.get("servicoNome") or "serviço"
    return f"✅ Reagendamento solicitado: {nome} para {dia} às {hora} (id {ag_id})"

# ========== Processamento principal ==========
def process_change(value: dict, send_text, uid_default: str, app_tag: str):
    for msg in value.get("messages", []):
        from_number = msg.get("from")
        if not from_number:
            contacts = value.get("contacts", [])
            if contacts and isinstance(contacts, list):
                from_number = contacts[0].get("wa_id")
        msg_type = msg.get("type")
        msg_id = msg.get("id")
        print(f"[WA_BOT][MESSAGE] id={msg_id} type={msg_type} from={from_number}", flush=True)

        to_msisdn = _normalize_br_msisdn(from_number or "")
        wa_id = from_number or to_msisdn

        # ---------- TEXTO ----------
        if msg_type == "text":
            body = (msg.get("text") or {}).get("body", "")
            text_norm = _strip_accents_lower(body)
            kw = _detect_keyword(body)

            # comandos rápidos
            if kw == "cancelar":
                _clear_session(uid_default, wa_id)
                send_text(to_msisdn, "Ok, limpei nossa conversa. Se quiser recomeçar, diga 'agendar' ou 'precos'.")
                continue

            if kw == "precos":
                items, dbg = load_prices(uid_default)
                send_text(to_msisdn, format_prices_reply(uid_default, items, dbg))
                continue

            # obter sessão
            sess = _get_session(uid_default, wa_id)

            if kw == "agendar":
                items, _ = load_prices(uid_default)
                reply = _agendar_fluxo(value, to_msisdn, uid_default, app_tag, body, text_norm, items, sess, wa_id)
                send_text(to_msisdn, reply)
                continue

            if kw == "reagendar":
                reply = _reagendar_fluxo(value, to_msisdn, uid_default, app_tag, body, text_norm, sess, wa_id)
                send_text(to_msisdn, reply)
                continue

            # Sem keyword explícita: se há sessão pendente, tentar preencher slots
            if sess.get("intent") in ("agendar","reagendar"):
                if sess["intent"] == "agendar":
                    items, _ = load_prices(uid_default)
                    reply = _agendar_fluxo(value, to_msisdn, uid_default, app_tag, body, text_norm, items, sess, wa_id)
                    send_text(to_msisdn, reply)
                    continue
                else:
                    reply = _reagendar_fluxo(value, to_msisdn, uid_default, app_tag, body, text_norm, sess, wa_id)
                    send_text(to_msisdn, reply)
                    continue

            # fallback conversacional
            send_text(to_msisdn, fallback_text(app_tag, "wa_bot:text-default"))
            continue

        # ---------- ÁUDIO ----------
        if msg_type == "audio":
            token = os.getenv("WHATSAPP_TOKEN")
            gv = os.getenv("GRAPH_VERSION", "v22.0")
            audio = msg.get("audio") or {}
            media_id = audio.get("id")
            try:
                if not media_id:
                    send_text(to_msisdn, fallback_text(app_tag, "audio:sem-media_id")); continue
                info = requests.get(
                    f"https://graph.facebook.com/{gv}/{media_id}",
                    headers={"Authorization": f"Bearer {token}"}, timeout=15
                ).json()
                media_url = info.get("url")
                if not media_url:
                    send_text(to_msisdn, fallback_text(app_tag, "audio:sem-url")); continue
                r = requests.get(media_url, headers={"Authorization": f"Bearer {token}"}, timeout=30)
                audio_bytes = r.content or b""
                if not audio_bytes:
                    send_text(to_msisdn, fallback_text(app_tag, "audio:bytes=0")); continue

                mt = (audio.get("mime_type") or "audio/ogg").split(";")[0].strip()
                text = stt_transcribe(audio_bytes, mime_type=mt, language="pt-BR")
                text_norm = _strip_accents_lower(text)
                print(f"[WA_BOT][AUDIO][STT] '{text_norm}'", flush=True)

                kw = _detect_keyword(text_norm)
                sess = _get_session(uid_default, wa_id)

                if kw == "cancelar":
                    _clear_session(uid_default, wa_id)
                    send_text(to_msisdn, "Ok, limpei nossa conversa. Se quiser recomeçar, diga 'agendar' ou 'precos'.")
                    continue

                if kw == "precos":
                    items, dbg = load_prices(uid_default)
                    send_text(to_msisdn, format_prices_reply(uid_default, items, dbg))
                    continue

                if kw == "agendar" or (sess.get("intent") == "agendar"):
                    items, _ = load_prices(uid_default)
                    reply = _agendar_fluxo(value, to_msisdn, uid_default, app_tag, text, text_norm, items, sess, wa_id)
                    send_text(to_msisdn, reply)
                    continue

                if kw == "reagendar" or (sess.get("intent") == "reagendar"):
                    reply = _reagendar_fluxo(value, to_msisdn, uid_default, app_tag, text, text_norm, sess, wa_id)
                    send_text(to_msisdn, reply)
                    continue

                send_text(to_msisdn, fallback_text(app_tag, f"audio:kw-nok::{text_norm[:30]}"))

            except Exception as e:
                print("[WA_BOT][AUDIO][ERROR]", repr(e), flush=True)
                send_text(to_msisdn, fallback_text(app_tag, "audio:error"))
            continue

        # ---------- Outros tipos ----------
        if to_msisdn:
            send_text(to_msisdn, fallback_text(app_tag, "wa_bot:default"))

    # statuses (log)
    for st in value.get("statuses", []):
        print(f"[WA_BOT][STATUS] id={st.get('id')} status={st.get('status')} ts={st.get('timestamp')} recipient={st.get('recipient_id')} errors={st.get('errors')}", flush=True)
