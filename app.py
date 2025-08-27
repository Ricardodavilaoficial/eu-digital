# app.py — entrypoint para runtime Python do Render (produção)
# Webhook Meta + auto-reply + handler "precos" (texto) consultando Firestore
# + ÁUDIO: STT -> mesma detecção de 'precos' e listagem dinâmica

import os
import json
import logging
import traceback
import requests
import re
import hashlib
import unicodedata
from flask import Flask, jsonify, request, send_from_directory

print("[boot] app.py raiz carregado ✅", flush=True)

# -------- logging básico --------
logging.basicConfig(level=logging.INFO)

# Serve arquivos estáticos da pasta /public como raiz do site
app = Flask(__name__, static_folder="public", static_url_path="/")
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024  # 25 MB

# --- DEBUG: fingerprint seguro do token em runtime ---
def _token_fingerprint(tok: str):
    if not tok:
        return {"present": False, "length": 0, "sha256_12": None}
    sha12 = hashlib.sha256(tok.encode("utf-8")).hexdigest()[:12]
    return {"present": True, "length": len(tok), "sha256_12": sha12}

@app.get("/__wa_debug")
def __wa_debug():
    fp = _token_fingerprint(os.getenv("WHATSAPP_TOKEN", ""))
    return jsonify({
        "graph_version": os.getenv("GRAPH_VERSION", "v22.0"),
        "phone_number_id": os.getenv("PHONE_NUMBER_ID"),
        "token_fingerprint": fp,
        "pid": os.getpid(),
    }), 200

# CORS apenas para /api/*
try:
    from flask_cors import CORS
    CORS(app, resources={r"/api/*": {"origins": "*"}}, supports_credentials=True)
    print("[init] CORS habilitado para /api/*")
except Exception as e:
    print(f"[warn] flask-cors indisponível: {e}")

# -------------------------
# Registro de Blueprints
# -------------------------
def _register_bp(bp, name: str):
    try:
        app.register_blueprint(bp)
        print(f"[bp] Registrado: {name}")
    except Exception as e:
        print(f"[bp][erro] Falhou ao registrar {name}: {e}")
        traceback.print_exc()

try:
    from routes.routes import routes
    _register_bp(routes, "routes")
except Exception as e:
    print(f"[bp][erro] import routes: {e}")
    traceback.print_exc()

try:
    from routes.teste_eleven_route import teste_eleven_route
    _register_bp(teste_eleven_route, "teste_eleven_route")
except Exception as e:
    print(f"[bp][erro] import teste_eleven_route: {e}")
    traceback.print_exc()

try:
    from routes.cupons import cupons_bp
    _register_bp(cupons_bp, "cupons_bp")
except Exception as e:
    print(f"[bp][erro] import cupons_bp: {e}")
    traceback.print_exc()

try:
    from routes.core_api import core_api
    _register_bp(core_api, "core_api")
except Exception as e:
    print(f"[bp][erro] import core_api: {e}")
    traceback.print_exc()

try:
    from routes.configuracao import config_bp
    _register_bp(config_bp, "config_bp (/api/configuracao)")
except Exception as e:
    print(f"[bp][warn] config_bp não registrado: {e}")
    traceback.print_exc()

try:
    from routes.importar_precos import importar_bp
    _register_bp(importar_bp, "importar_bp (/api/importar-precos)")
except Exception as e:
    print(f"[bp][warn] importar_bp não registrado: {e}")
    traceback.print_exc()

try:
    from routes.seed import seed_bp
    _register_bp(seed_bp, "seed_bp (/_seed/profissional)")
except Exception as e:
    print(f"[bp][warn] seed_bp não registrado: {e}")
    traceback.print_exc()

# -------------------------
# Healthcheck e Debug
# -------------------------
@app.route("/health", methods=["GET"])
def health():
    return jsonify(
        ok=True,
        service="mei-robo-prod",
        has_whatsapp_token=bool(os.getenv("WHATSAPP_TOKEN")),
        has_phone_number_id=bool(os.getenv("PHONE_NUMBER_ID")),
        graph_version=os.getenv("GRAPH_VERSION", "v22.0"),
    )

@app.route("/__routes", methods=["GET"])
def list_routes():
    rules = []
    for r in app.url_map.iter_rules():
        methods = sorted(list(r.methods - {"HEAD", "OPTIONS"}))
        rules.append({"rule": str(r), "endpoint": r.endpoint, "methods": methods})
    return jsonify(routes=rules, count=len(rules))

# --- Firestore helpers ---
from services import db as dbsvc
DB = dbsvc.db

def _only_digits(s: str) -> str:
    return "".join(ch for ch in str(s or "") if ch.isdigit())

def _normalize_br_msisdn(wa_id: str) -> str:
    if not wa_id:
        return ""
    digits = _only_digits(wa_id)
    if digits.startswith("55") and len(digits) == 12:
        digits = digits[:4] + "9" + digits[4:]
    return digits

# Tag e UID default
APP_TAG = os.getenv("APP_TAG", "2025-08-27")
UID_DEFAULT = os.getenv("UID_DEFAULT", "ricardo-prod-uid")

def fallback_text(context: str) -> str:
    return f"[FALLBACK] MEI Robo PROD :: {APP_TAG} :: {context}\nDigite 'precos' para ver a lista."

# --- Texto -> keyword normalizado ---
def _strip_accents_lower(s: str) -> str:
    s = s or ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return s.lower().strip()

def _detect_keyword(body: str):
    t = _strip_accents_lower(body)
    # aceita variações: preco, preços, servico(s), tabela, lista, valores
    if any(k in t for k in ["preco", "precos", "preços", "tabela", "lista", "valores"]):
        return "precos"
    if any(k in t for k in ["servico", "servicos", "serviço", "serviços"]):
        return "precos"
    return None

# --- Carrega preços de 2 fontes do Firestore ---
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

    # dedup por nomeLower (prioriza map)
    dedup = {}
    for it in map_items + ps_items:
        key = (it.get("nomeLower") or "").strip()
        if key and key not in dedup:
            dedup[key] = it

    items = sorted(dedup.values(), key=lambda x: x.get("nomeLower",""))
    debug = {
        "uid": uid,
        "map_count": len(map_items),
        "ps_count": len(ps_items),
        "total": len(items)
    }
    return items, debug

def format_prices_reply(items, debug):
    lines = [f"[DEBUG] uid={debug['uid']} map={debug['map_count']} prodServ={debug['ps_count']} total={debug['total']}"]
    if not items:
        lines.append("⚠️ Nenhum serviço ativo encontrado.")
        return "\n".join(lines)
    for it in items[:12]:
        nome = it.get("nome") or it.get("nomeLower") or "serviço"
        dur = it.get("duracaoMin") or it.get("duracao") or "?"
        val = it.get("preco") or it.get("valor") or "?"
        lines.append(f"- {nome} — {dur}min — R${val}")
    return "\n".join(lines)

def _send_text(to: str, body: str):
    to_digits = _only_digits(to)
    token = os.getenv("WHATSAPP_TOKEN")
    pnid = os.getenv("PHONE_NUMBER_ID")
    gv = os.getenv("GRAPH_VERSION", "v22.0")
    if not token or not pnid:
        print("[ERROR] CONFIG: Missing WHATSAPP_TOKEN or PHONE_NUMBER_ID", flush=True)
        return False, {"error": "missing_whatsapp_config"}

    url = f"https://graph.facebook.com/{gv}/{pnid}/messages"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {"messaging_product": "whatsapp", "to": to_digits, "type": "text", "text": {"body": body}}
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=15)
        try:
            resp_json = r.json()
        except Exception:
            resp_json = {"raw": r.text}
        print(f"[WHATSAPP][OUTBOUND] to={to_digits} status={r.status_code} resp={json.dumps(resp_json, ensure_ascii=False)[:800]}", flush=True)
        return r.ok, resp_json
    except Exception as e:
        print("[ERROR] SEND]:", repr(e), flush=True)
        return False, {"error": repr(e)}

# --- STT helper: tenta vários nomes em services.audio_processing; fallback para OpenAI Whisper ---
def stt_transcribe(audio_bytes: bytes, mime_type: str = "audio/ogg", language: str = "pt-BR") -> str:
    # 1) tentar services.audio_processing com vários nomes de função
    try:
        import inspect
        import services.audio_processing as ap
        candidates = [
            "transcribe_audio_bytes", "transcribe_audio", "stt_transcribe",
            "speech_to_text", "stt_bytes", "transcrever_audio_bytes", "transcrever_audio"
        ]
        for name in candidates:
            f = getattr(ap, name, None)
            if not callable(f):
                continue
            try:
                # tentativas de chamada com assinaturas diferentes
                try:
                    text = f(audio_bytes, mime_type=mime_type, language=language)
                except TypeError:
                    try:
                        text = f(audio_bytes, language=language)
                    except TypeError:
                        try:
                            text = f(audio_bytes)
                        except TypeError:
                            # última cartada: inspeciona e mapeia kwargs suportados
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

    # 2) fallback OpenAI Whisper (se OPENAI_API_KEY estiver setado)
    try:
        api_key = os.getenv("OPENAI_API_KEY")
        if api_key and audio_bytes:
            # normalizar idioma: pt-BR -> pt
            lang = "pt" if language.lower().startswith("pt") else language.split("-")[0]
            files = {
                "file": ("audio.ogg", audio_bytes, mime_type or "audio/ogg"),
            }
            data = {
                "model": "whisper-1",
                "language": lang
            }
            headers = {"Authorization": f"Bearer {api_key}"}
            resp = requests.post("https://api.openai.com/v1/audio/transcriptions",
                                 headers=headers, files=files, data=data, timeout=60)
            js = {}
            try:
                js = resp.json()
            except Exception:
                pass
            text = (js.get("text") if isinstance(js, dict) else "") or ""
            text = text.strip()
            print(f"[STT] openai whisper status={resp.status_code} text='{text[:120]}'", flush=True)
            return text
    except Exception as e:
        print(f"[STT] openai whisper erro: {e}", flush=True)

    # 3) sem STT
    print("[STT] nenhum backend retornou transcrição", flush=True)
    return ""

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "meirobo123")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
GRAPH_VERSION = os.getenv("GRAPH_VERSION", "v22.0")

@app.get("/webhook")
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        print("[WEBHOOK][VERIFY] success", flush=True)
        return str(challenge or "OK"), 200
    print(f"[WEBHOOK][VERIFY] fail mode={mode} token={token}", flush=True)
    return "Forbidden", 403

@app.post("/webhook")
def receive_webhook():
    # 0) Headers para debug
    try:
        ct = request.content_type or "<none>"
        clen = request.content_length
        sig = request.headers.get("X-Hub-Signature-256")
        print(f"[WEBHOOK][CT] {ct} | len={clen} | has_sig256={bool(sig)}", flush=True)
    except Exception:
        pass

    # 1) RAW
    try:
        raw = request.get_data(cache=True, as_text=True) or ""
        if raw:
            print(f"[WEBHOOK][RAW] {raw[:800]}", flush=True)
        raw_clean = raw.lstrip("\ufeff").strip()
    except Exception as e:
        raw, raw_clean = "", ""
        print("[WEBHOOK][RAW][ERROR]", repr(e), flush=True)

    data = {}

    # 2) Parse JSON
    if raw_clean:
        try:
            data = json.loads(raw_clean)
        except Exception as e:
            print("[WEBHOOK][PARSE][raw][ERROR]", repr(e), flush=True)

    if not data:
        try:
            data = request.get_json(force=True, silent=True) or {}
        except Exception as e:
            print("[WEBHOOK][PARSE][flask][ERROR]", repr(e), flush=True)

    if not data and request.form:
        entry = request.form.get("entry")
        if entry:
            try:
                data = {"entry": json.loads(entry)}
            except Exception as e:
                print("[WEBHOOK][PARSE][form][ERROR]", repr(e), flush=True)

    # 5) Fallback regex
    if not data and raw_clean:
        m = re.search(r'"from"\s*:\s*"([^"]+)"', raw_clean)
        if m:
            from_number = m.group(1)
            to_msisdn = _normalize_br_msisdn(from_number)
            print(f"[WEBHOOK][FALLBACK][regex] from={from_number} -> {to_msisdn}", flush=True)
            _send_text(to_msisdn, fallback_text("path=app.py:regex"))
            return "EVENT_RECEIVED", 200

    # 6) Log do payload interpretado
    try:
        print("[WEBHOOK][INCOMING]", json.dumps(data, ensure_ascii=False)[:1200], flush=True)
        logging.getLogger().info("[WEBHOOK][INCOMING] %s", json.dumps(data, ensure_ascii=False)[:1200])
    except Exception:
        print("[WEBHOOK][INCOMING] (non-json-printable)", flush=True)

    # 7) Processamento normal
    try:
        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})

                # --- mensagens ---
                for msg in value.get("messages", []):
                    from_number = msg.get("from")
                    if not from_number:
                        contacts = value.get("contacts", [])
                        if contacts and isinstance(contacts, list):
                            from_number = contacts[0].get("wa_id")
                    msg_type = msg.get("type")
                    msg_id = msg.get("id")
                    print(f"[WEBHOOK][MESSAGE] id={msg_id} type={msg_type} from={from_number}", flush=True)

                    to_msisdn = _normalize_br_msisdn(from_number or "")

                    # TEXTO
                    if msg_type == "text":
                        body = (msg.get("text") or {}).get("body", "")
                        kw = _detect_keyword(body)
                        if kw == "precos":
                            uid = UID_DEFAULT  # foco: profissional oficial
                            items, dbg = load_prices(uid)
                            dbg["uid"] = uid
                            reply = format_prices_reply(items, dbg)
                            _send_text(to_msisdn, reply)
                            continue

                    # ÁUDIO -> STT -> mesma detecção
                    elif msg_type == "audio":
                        token = os.getenv("WHATSAPP_TOKEN")
                        gv = os.getenv("GRAPH_VERSION", "v22.0")
                        audio = msg.get("audio") or {}
                        media_id = audio.get("id")
                        try:
                            if not media_id:
                                print("[AUDIO] sem media_id", flush=True)
                                _send_text(to_msisdn, fallback_text("audio:sem-media_id"))
                                continue

                            # 1) obter URL do media
                            info = requests.get(
                                f"https://graph.facebook.com/{gv}/{media_id}",
                                headers={"Authorization": f"Bearer {token}"}, timeout=15
                            ).json()
                            media_url = info.get("url")
                            print(f"[AUDIO] media_id={media_id} url={bool(media_url)}", flush=True)
                            if not media_url:
                                _send_text(to_msisdn, fallback_text("audio:sem-url"))
                                continue

                            # 2) baixar bytes
                            r = requests.get(media_url, headers={"Authorization": f"Bearer {token}"}, timeout=30)
                            audio_bytes = r.content or b""
                            print(f"[AUDIO] bytes={len(audio_bytes)}", flush=True)
                            if not audio_bytes:
                                _send_text(to_msisdn, fallback_text("audio:bytes=0"))
                                continue

                            # 3) transcrever (pt-BR)
                            mt = (audio.get("mime_type") or "audio/ogg").split(";")[0].strip()
                            text = stt_transcribe(audio_bytes, mime_type=mt, language="pt-BR")
                            text_norm = _strip_accents_lower(text)
                            print(f"[AUDIO][STT] '{text_norm}'", flush=True)

                            # 4) detectar keyword e responder
                            kw = _detect_keyword(text_norm)
                            if kw == "precos":
                                uid = UID_DEFAULT
                                items, dbg = load_prices(uid)
                                dbg["uid"] = uid
                                reply = format_prices_reply(items, dbg)
                                _send_text(to_msisdn, reply)
                            else:
                                _send_text(to_msisdn, fallback_text(f"audio:kw-nok::{text_norm[:30]}"))

                        except Exception as e:
                            print("[AUDIO][ERROR]", repr(e), flush=True)
                            _send_text(to_msisdn, fallback_text("audio:error"))

                    # Demais casos (ou não reconheceu keyword) -> fallback etiquetado
                    else:
                        if to_msisdn:
                            _send_text(to_msisdn, fallback_text("path=app.py:default"))

                # --- statuses ---
                for st in value.get("statuses", []):
                    print(f"[WEBHOOK][STATUS] id={st.get('id')} status={st.get('status')} ts={st.get('timestamp')} recipient={st.get('recipient_id')} errors={st.get('errors')}", flush=True)

    except Exception as e:
        print("[ERROR] HANDLER:", repr(e), flush=True)

    return "EVENT_RECEIVED", 200

# -------------------------
# API utilitária de envio
# -------------------------
@app.route("/api/send-text", methods=["GET", "POST"])
def api_send_text():
    if request.method == "GET":
        to = request.args.get("to", "")
        body = request.args.get("body", "")
    else:
        data = request.get_json(silent=True) or {}
        to = data.get("to", "")
        body = data.get("body", "")

    if not to or not body:
        return {"ok": False, "error": "missing_to_or_body"}, 400

    to_norm = _normalize_br_msisdn(to)
    print(f"[API][SEND_TEXT] to={to} normalized={to_norm} body_preview={body[:80]}", flush=True)
    ok, resp = _send_text(to_norm, body)
    return ({"ok": True, "resp": resp}, 200) if ok else ({"ok": False, "resp": resp}, 500)

@app.route("/", methods=["GET"])
def index():
    return app.send_static_file("index.html")

@app.route("/<path:path>", methods=["GET"])
def static_proxy(path):
    return send_from_directory(app.static_folder, path)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=True)
