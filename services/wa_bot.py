# services/wa_bot.py
# Lógica do bot WhatsApp (texto + áudio com STT) + preços, agendar e reagendar — isolada do app.py

import os
import re
import json
import requests
import unicodedata
from datetime import datetime, timedelta, timezone
from services import db as dbsvc

DB = dbsvc.db
SP_TZ = timezone(timedelta(hours=-3))  # America/Sao_Paulo (sem horário de verão)

# ---------- utils ----------
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
    if any(k in t for k in ["preco", "precos", "preços", "tabela", "lista", "valores",
                            "servico", "servicos", "serviço", "serviços"]):
        return "precos"
    if "agendar" in t or "agenda " in t or "marcar" in t or "agendamento" in t:
        return "agendar"
    if any(k in t for k in ["reagendar", "remarcar", "mudar horario", "mudar horário", "trocar horario", "trocar horário"]):
        return "reagendar"
    return None

# ---------- preços ----------
def load_prices(uid: str):
    """
    Retorna (items, debug) onde cada item tem:
      - id: doc.id da subcoleção ou 'map:<nomeLower>' do mapa raiz
      - nome / nomeLower / duracaoMin|duracao / preco|valor / ativo ...
    """
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

# ---------- STT ----------
def stt_transcribe(audio_bytes: bytes, mime_type: str = "audio/ogg", language: str = "pt-BR") -> str:
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

# ---------- helpers agenda ----------
def _parse_datetime_br(text_norm: str):
    d = re.search(r'(\b\d{1,2})[\/\.-](\d{1,2})(?:[\/\.-](\d{2,4}))?', text_norm)
    h = re.search(r'(\b\d{1,2})[:h](\d{2})', text_norm)
    if not d or not h:
        return None
    day = int(d.group(1))
    month = int(d.group(2))
    year = d.group(3)
    year = int(year) + (2000 if year and len(year) == 2 else 0) if year else datetime.now(SP_TZ).year
    hour = int(h.group(1))
    minute = int(h.group(2))
    try:
        dt = datetime(year, month, day, hour, minute, tzinfo=SP_TZ)
        return dt
    except Exception:
        return None

def _choose_service(items, text_norm: str):
    if not items:
        return None
    if len(items) == 1:
        return items[0]
    best = None
    best_len = 0
    for it in items:
        alias = (it.get("nomeLower") or it.get("nome") or "").lower()
        alias_norm = _strip_accents_lower(alias)
        if not alias_norm:
            continue
        if alias_norm in text_norm and len(alias_norm) > best_len:
            best = it
            best_len = len(alias_norm)
    return best

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
    """
    Busca o agendamento 'ativo' mais recente do cliente:
      1) por clienteId; fallback
      2) por clienteWaId; fallback
      3) por telefone
    Estados considerados: solicitado, confirmado
    """
    estados = ["solicitado", "confirmado"]
    candidatos = []

    try:
        q = (DB.collection(f"profissionais/{uid}/agendamentos")
               .where("clienteId", "==", cliente_id)
               .where("estado", "in", estados).limit(10).stream())
        for d in q:
            obj = d.to_dict() or {}
            obj["_id"] = d.id
            candidatos.append(obj)
    except Exception as e:
        print(f"[WA_BOT][AGENDA] query por clienteId falhou: {e}", flush=True)

    if not candidatos and wa_id:
        try:
            q = (DB.collection(f"profissionais/{uid}/agendamentos")
                   .where("clienteWaId", "==", wa_id)
                   .where("estado", "in", estados).limit(10).stream())
            for d in q:
                obj = d.to_dict() or {}
                obj["_id"] = d.id
                candidatos.append(obj)
        except Exception as e:
            print(f"[WA_BOT][AGENDA] query por clienteWaId falhou: {e}", flush=True)

    if not candidatos and telefone:
        try:
            q = (DB.collection(f"profissionais/{uid}/agendamentos")
                   .where("telefone", "==", telefone)
                   .where("estado", "in", estados).limit(10).stream())
            for d in q:
                obj = d.to_dict() or {}
                obj["_id"] = d.id
                candidatos.append(obj)
        except Exception as e:
            print(f"[WA_BOT][AGENDA] query por telefone falhou: {e}", flush=True)

    if not candidatos:
        return None

    # escolher o mais recente por createdAt (ou inicio)
    def _iso_or_none(s):
        try:
            return datetime.fromisoformat(s.replace("Z","+00:00"))
        except Exception:
            return None

    candidatos.sort(key=lambda x: _iso_or_none(x.get("createdAt") or x.get("inicio")) or datetime.min.replace(tzinfo=SP_TZ), reverse=True)
    return candidatos[0]

# ---------- fluxos ----------
def _agendar_por_texto(value: dict, to_msisdn: str, uid_default: str, app_tag: str, body_text: str, text_norm: str, items):
    svc = _choose_service(items, text_norm)
    if not svc:
        nomes = ", ".join([it.get("nome") or it.get("nomeLower") for it in items[:5]]) or "o serviço"
        return ("Para agendar, envie assim:\n"
                "agendar <serviço> <dd/mm> <hh:mm>\n"
                "Ex.: agendar Pitch 30/08 14:00\n\n"
                f"Serviços disponíveis: {nomes}")

    dt = _parse_datetime_br(text_norm)
    if not dt:
        return "Informe a data e hora assim: dd/mm hh:mm\nEx.: agendar Pitch 30/08 14:00"

    wa_id = ""
    nome_contato = ""
    try:
        contacts = value.get("contacts") or []
        if contacts and isinstance(contacts, list):
            wa_id = contacts[0].get("wa_id") or ""
            prof = contacts[0].get("profile") or {}
            nome_contato = prof.get("name") or ""
    except Exception:
        pass

    cliente_id = _resolve_cliente_id(uid_default, wa_id, to_msisdn)

    dur = int(svc.get("duracaoMin") or svc.get("duracao") or 60)
    fim = dt + timedelta(minutes=dur)
    servico_id = svc.get("id") or f"map:{(svc.get('nomeLower') or svc.get('nome') or 'servico').strip().lower()}"

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
            return f"Não foi possível agendar: {motivo}"
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
            return "Tive um problema ao salvar seu agendamento. Pode tentar novamente em instantes?"

    dia = dt.strftime("%d/%m")
    hora = dt.strftime("%H:%M")
    preco = ag.get("preco")
    preco_txt = f" — R${preco}" if preco not in (None, "", "?") else ""
    sid = f" (id {saved_id})" if saved_id else ""
    return (f"✅ Agendamento solicitado: {ag['servicoNome']} em {dia} às {hora}{preco_txt}.{sid}\n"
            f"Se precisar alterar, responda: reagendar <dd/mm> <hh:mm>")

def _reagendar_por_texto(value: dict, to_msisdn: str, uid_default: str, app_tag: str, body_text: str, text_norm: str):
    dt = _parse_datetime_br(text_norm)
    if not dt:
        return "Para reagendar, envie assim: reagendar <dd/mm> <hh:mm>"

    wa_id = ""
    try:
        contacts = value.get("contacts") or []
        if contacts and isinstance(contacts, list):
            wa_id = contacts[0].get("wa_id") or ""
    except Exception:
        pass

    cliente_id = _resolve_cliente_id(uid_default, wa_id, to_msisdn)
    alvo = _find_target_agendamento(uid_default, cliente_id, wa_id, to_msisdn)
    if not alvo:
        return ("Não encontrei um agendamento ativo seu.\n"
                "Você pode enviar: reagendar <ID> <dd/mm> <hh:mm> (ID aparece na mensagem de confirmação)")

    ag_id = alvo.get("_id")
    try:
        import services.schedule as sched
        body = {"acao": "reagendar", "dataHora": dt.isoformat()}
        sched.atualizar_estado_agendamento(uid_default, ag_id, body)
    except Exception as e:
        print(f"[WA_BOT][AGENDA][REAGENDAR] erro: {e}", flush=True)
        return "Não consegui reagendar agora. Pode tentar novamente em instantes?"

    dia = dt.strftime("%d/%m")
    hora = dt.strftime("%H:%M")
    nome = alvo.get("servicoNome") or "serviço"
    return f"✅ Reagendamento solicitado: {nome} para {dia} às {hora} (id {ag_id})"

# ---------- Processamento principal ----------
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

        # TEXTO
        if msg_type == "text":
            body = (msg.get("text") or {}).get("body", "")
            text_norm = _strip_accents_lower(body)
            kw = _detect_keyword(body)
            if kw == "precos":
                items, dbg = load_prices(uid_default)
                reply = format_prices_reply(uid_default, items, dbg)
                send_text(to_msisdn, reply)
                continue
            if kw == "agendar":
                items, _ = load_prices(uid_default)
                reply = _agendar_por_texto(value, to_msisdn, uid_default, app_tag, body, text_norm, items)
                send_text(to_msisdn, reply)
                continue
            if kw == "reagendar":
                reply = _reagendar_por_texto(value, to_msisdn, uid_default, app_tag, body, text_norm)
                send_text(to_msisdn, reply)
                continue
            send_text(to_msisdn, fallback_text(app_tag, "wa_bot:text-default"))
            continue

        # ÁUDIO
        if msg_type == "audio":
            token = os.getenv("WHATSAPP_TOKEN")
            gv = os.getenv("GRAPH_VERSION", "v22.0")
            audio = msg.get("audio") or {}
            media_id = audio.get("id")
            try:
                if not media_id:
                    print("[WA_BOT][AUDIO] sem media_id", flush=True)
                    send_text(to_msisdn, fallback_text(app_tag, "audio:sem-media_id"))
                    continue
                info = requests.get(
                    f"https://graph.facebook.com/{gv}/{media_id}",
                    headers={"Authorization": f"Bearer {token}"}, timeout=15
                ).json()
                media_url = info.get("url")
                print(f"[WA_BOT][AUDIO] media_id={media_id} url={bool(media_url)}", flush=True)
                if not media_url:
                    send_text(to_msisdn, fallback_text(app_tag, "audio:sem-url"))
                    continue
                r = requests.get(media_url, headers={"Authorization": f"Bearer {token}"}, timeout=30)
                audio_bytes = r.content or b""
                print(f"[WA_BOT][AUDIO] bytes={len(audio_bytes)}", flush=True)
                if not audio_bytes:
                    send_text(to_msisdn, fallback_text(app_tag, "audio:bytes=0"))
                    continue
                mt = (audio.get("mime_type") or "audio/ogg").split(";")[0].strip()
                text = stt_transcribe(audio_bytes, mime_type=mt, language="pt-BR")
                text_norm = _strip_accents_lower(text)
                print(f"[WA_BOT][AUDIO][STT] '{text_norm}'", flush=True)
                kw = _detect_keyword(text_norm)
                if kw == "precos":
                    items, dbg = load_prices(uid_default)
                    reply = format_prices_reply(uid_default, items, dbg)
                    send_text(to_msisdn, reply)
                elif kw == "agendar":
                    items, _ = load_prices(uid_default)
                    reply = _agendar_por_texto(value, to_msisdn, uid_default, app_tag, text, text_norm, items)
                    send_text(to_msisdn, reply)
                elif kw == "reagendar":
                    reply = _reagendar_por_texto(value, to_msisdn, uid_default, app_tag, text, text_norm)
                    send_text(to_msisdn, reply)
                else:
                    send_text(to_msisdn, fallback_text(app_tag, f"audio:kw-nok::{text_norm[:30]}"))
            except Exception as e:
                print("[WA_BOT][AUDIO][ERROR]", repr(e), flush=True)
                send_text(to_msisdn, fallback_text(app_tag, "audio:error"))
            continue

        # OUTROS TIPOS
        if to_msisdn:
            send_text(to_msisdn, fallback_text(app_tag, "wa_bot:default"))

    for st in value.get("statuses", []):
        print(f"[WA_BOT][STATUS] id={st.get('id')} status={st.get('status')} ts={st.get('timestamp')} recipient={st.get('recipient_id')} errors={st.get('errors')}", flush=True)
