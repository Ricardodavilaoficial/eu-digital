# routes/health.py
from flask import Blueprint, jsonify
import os, time

health_bp = Blueprint("health_bp", __name__, url_prefix="/api")

@health_bp.route("/health", methods=["GET"])
def health():
    # healthcheck simples, sem tocar em Firestore e sem exigir auth
    return jsonify({
        "ok": True,
        "service": "mei-robo-api",
        "ts": int(time.time()),
        "env": os.getenv("RENDER_SERVICE_NAME", "local")
    }), 200
