from flask import Blueprint, jsonify, request, current_app
from services.auth import auth_required, admin_required
from services.db import get_doc, set_doc, update_doc, db
from services.coupons import criar_cupom, find_cupom_by_codigo, validar_consumir_cupom
from services.schedule import validar_agendamento_v1, salvar_agendamento, atualizar_estado_agendamento

core_api = Blueprint("core_api", __name__)

def _err(where: str, e: Exception, code: int = 500):
    current_app.logger.exception(where)
    return jsonify({"erro": f"{where}: {str(e)}"}), code

@core_api.get("/healthz")
def healthz_core():
    return jsonify({"ok": True, "scope": "core_api"}), 200

# ---------- LICENÇAS ----------
@core_api.get("/licencas/status")
@auth_required
def licenca_status():
    try:
        from flask import g
        prof = get_doc(f"profissionais/{g.user.uid}") or {}
        plano = prof.get("plano", {"status": "bloqueado"})
        return jsonify(plano), 200
    except Exception as e:
        return _err("licenca_status", e)

@core_api.post("/licencas/ativar-cupom")
@auth_required
def ativar_cupom():
    try:
        from flask import g
        codigo = (request.json or {}).get("codigo", "").strip().upper()
        cupom = find_cupom_by_codigo(codigo)
        ok, msg, plano = validar_consumir_cupom(cupom, g.user.uid)
        if not ok:
            return jsonify({"erro": msg}), 400
        update_doc(f"profissionais/{g.user.uid}", {"plano": plano})
        return jsonify({"status": "ativo", "origem": "cupom"}), 200
    except Exception as e:
        return _err("ativar_cupom", e)

# ---------- ADMIN / CUPONS ----------
@core_api.post("/admin/cupons")
@admin_required
def admin_criar_cupom():
    try:
        from flask import g
        body = request.get_json() or {}
        cupom = criar_cupom(body, criado_por=g.user.uid)
        return jsonify(cupom), 201
    except Exception as e:
        return _err("admin_criar_cupom", e)

# ---------- AGENDA ----------
@core_api.get("/agendamentos")
@auth_required
def listar_agendamentos():
    try:
        from flask import g
        docs = db.collection(f"profissionais/{g.user.uid}/agendamentos").order_by("dataHora").stream()
        out = []
        for d in docs:
            o = d.to_dict(); o["id"] = d.id
            out.append(o)
        return jsonify(out), 200
    except Exception as e:
        return _err("listar_agendamentos", e)

@core_api.post("/agendamentos")
@auth_required
def criar_agendamento():
    try:
        from flask import g
        data = request.get_json() or {}
        ok, msg, ag = validar_agendamento_v1(g.user.uid, data)
        if not ok:
            return jsonify({"erro": msg}), 400
        ag = salvar_agendamento(g.user.uid, ag)
        return jsonify(ag), 201
    except Exception as e:
        return _err("criar_agendamento", e)

@core_api.patch("/agendamentos/<ag_id>")
@auth_required
def atualizar_agendamento_route(ag_id):
    try:
        from flask import g
        body = request.get_json() or {}
        ag = atualizar_estado_agendamento(g.user.uid, ag_id, body)
        return jsonify(ag), 200
    except Exception as e:
        return _err("atualizar_agendamento", e)
