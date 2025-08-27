# services/wa_bot.py
# Lógica do bot WhatsApp (texto + áudio com STT), isolada do app.py

import os
import json
import requests
import unicodedata
from services import db as dbsvc

DB = dbsvc.db

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
    return None

# ---------- Firestore (preços) ----------
def load_prices(uid: str):
    doc = DB.collection("profissionais").document(uid).get()
    root = doc.to_dict() if doc.exists else {}
    map_items = []
    if root and isinstance(root.get("precos"), dict):
        for nome, it in (root.get("precos") or {}).items():
            if isinstance(it, dict) and it.get("ativo", True):
                item = {"nome": nome, "nomeLower": (nome or "").lower()}
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
    # 1) tentar services.audio_processing com nomes variados
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

    # 2) fallback OpenAI Whisper (se habilitado e houver chave)
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

# ---------- Processamento ----------
def process_change(value: dict, send_text, uid_default: str, app_tag: str):
    # mensagens
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
            kw = _detect_keyword(body)
            if kw == "precos":
                items, dbg = load_prices(uid_default)
                reply = format_prices_reply(uid_default, items, dbg)
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
                # 1) info
                info = requests.get(
                    f"https://graph.facebook.com/{gv}/{media_id}",
                    headers={"Authorization": f"Bearer {token}"}, timeout=15
                ).json()
                media_url = info.get("url")
                print(f"[WA_BOT][AUDIO] media_id={media_id} url={bool(media_url)}", flush=True)
                if not media_url:
                    send_text(to_msisdn, fallback_text(app_tag, "audio:sem-url"))
                    continue
                # 2) download
                r = requests.get(media_url, headers={"Authorization": f"Bearer {token}"}, timeout=30)
                audio_bytes = r.content or b""
                print(f"[WA_BOT][AUDIO] bytes={len(audio_bytes)}", flush=True)
                if not audio_bytes:
                    send_text(to_msisdn, fallback_text(app_tag, "audio:bytes=0"))
                    continue
                # 3) STT
                mt = (audio.get("mime_type") or "audio/ogg").split(";")[0].strip()
                text = stt_transcribe(audio_bytes, mime_type=mt, language="pt-BR")
                text_norm = _strip_accents_lower(text)
                print(f"[WA_BOT][AUDIO][STT] '{text_norm}'", flush=True)
                # 4) detecção
                kw = _detect_keyword(text_norm)
                if kw == "precos":
                    items, dbg = load_prices(uid_default)
                    reply = format_prices_reply(uid_default, items, dbg)
                    send_text(to_msisdn, reply)
                else:
                    send_text(to_msisdn, fallback_text(app_tag, f"audio:kw-nok::{text_norm[:30]}"))
            except Exception as e:
                print("[WA_BOT][AUDIO][ERROR]", repr(e), flush=True)
                send_text(to_msisdn, fallback_text(app_tag, "audio:error"))
            continue

        # OUTROS TIPOS -> fallback
        if to_msisdn:
            send_text(to_msisdn, fallback_text(app_tag, "wa_bot:default"))

    # statuses (log)
    for st in value.get("statuses", []):
        print(f"[WA_BOT][STATUS] id={st.get('id')} status={st.get('status')} ts={st.get('timestamp')} recipient={st.get('recipient_id')} errors={st.get('errors')}", flush=True)
