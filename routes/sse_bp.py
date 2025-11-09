# routes/sse_bp.py
import os, json, time, threading
from flask import Blueprint, Response, request, abort
import redis

SSE_ENABLED = os.getenv("SSE_ENABLED", "0") == "1"
REDIS_URL = os.getenv("REDIS_URL", "").strip()
SSE_ALLOWED_ORIGINS = os.getenv("SSE_ALLOWED_ORIGINS", "*")

sse_bp = Blueprint("sse_bp", __name__, url_prefix="/api/sse")

_redis = None
def get_redis():
    global _redis
    if _redis is None and REDIS_URL:
        _redis = redis.from_url(REDIS_URL, decode_responses=True)
    return _redis

# === util: CORS leve para SSE
def _sse_headers():
    return {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",  # evita buffering em proxies
        "Access-Control-Allow-Origin": SSE_ALLOWED_ORIGINS if SSE_ALLOWED_ORIGINS else "*",
    }

# === util: valida o ID token Firebase e retorna (uid, email)
def _verify_id_token(id_token: str):
    """
    IMPORTANTE:
    1) Substitua o import abaixo pelo helper que você JÁ usa no backend
       para validar Bearer (o mesmo do /api/auth/check-verification).
    2) Mantive um fallback 401 caso o helper não exista.
    """
    try:
        # Exemplo: from services.auth import verify_id_token  # <- troque para o seu
        from services.auth import verify_id_token  # TODO: ajuste para o seu caminho real
        payload = verify_id_token(id_token)
        uid = payload.get("uid") or payload.get("user_id")
        email = payload.get("email")
        if not uid:
            raise ValueError("uid_missing")
        return uid, (email or "")
    except Exception:
        abort(401, description="invalid token")

def _channel_for(uid: str):
    return f"user:{uid}:email_verified"

@sse_bp.route("/verify", methods=["GET"])
def sse_verify():
    # Guardas de segurança / configuração
    if not SSE_ENABLED:
        abort(503, description="SSE disabled")
    if not REDIS_URL:
        abort(503, description="Redis not configured")

    # Token via query (?token=) ou Authorization (fallback)
    token = request.args.get("token", "").strip()
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth.split(" ", 1)[1].strip()
    if not token:
        abort(401, description="missing token")

    uid, email = _verify_id_token(token)
    r = get_redis()
    if not r:
        abort(503, description="redis unavailable")

    chan = _channel_for(uid)

    def gen():
        pubsub = r.pubsub()
        pubsub.subscribe(chan)
        last_ping = time.time()

        # Envia um hello inicial para destravar proxies
        yield "event: hello\ndata: {}\n\n"

        try:
            while True:
                msg = pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                now = time.time()

                # Heartbeat a cada 15s
                if now - last_ping >= 15:
                    last_ping = now
                    yield ": keep-alive\n\n"

                if not msg:
                    continue

                # Quando alguém publicar no canal, entregamos e encerramos
                # Esperado: {"verified": true}
                data = msg.get("data")
                try:
                    obj = json.loads(data) if isinstance(data, str) else {"ok": True}
                except Exception:
                    obj = {"ok": True}
                yield f"event: verified\ndata: {json.dumps(obj)}\n\n"
                break
        finally:
            try:
                pubsub.close()
            except Exception:
                pass

    return Response(gen(), headers=_sse_headers())
