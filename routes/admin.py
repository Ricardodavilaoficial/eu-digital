# routes/admin.py
from flask import Blueprint, jsonify, request, make_response
from services.auth import admin_required

admin_bp = Blueprint("admin_bp", __name__)

ALLOWED_ORIGIN = "https://mei-robo-prod.web.app"

def _cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = ALLOWED_ORIGIN
    resp.headers["Vary"] = "Origin"
    return resp

@admin_bp.route("/admin/ping", methods=["OPTIONS"])
def admin_ping_preflight():
    # Preflight para permitir Authorization no GET
    resp = make_response("", 204)
    resp.headers["Access-Control-Allow-Origin"] = ALLOWED_ORIGIN
    resp.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
    resp.headers["Access-Control-Max-Age"] = "600"
    return resp

@admin_bp.route("/admin/ping", methods=["GET"])
@admin_required
def admin_ping():
    resp = jsonify({"ok": True, "role": "admin"})
    return _cors(resp)
