# -*- coding: utf-8 -*-
from flask import Blueprint, jsonify, request, g
from services.auth import auth_required, admin_required
from services.db import get_doc, update_doc, db
from services.coupons import criar_cupom, find_cupom_by_codigo, validar_consumir_cupom
from services.schedule import validar_agendamento_v1, salvar_agendamento, atualizar_estado_agendamento

core_api = Blueprint("core_api", __name__)

@core_api.get("/licencas/status")
@auth_required
def licenca_status():
    uid = g.user.uid
    prof = get_doc(f"profissionais/{uid}") or {}
    plano = prof.get("plano", {"status": "bloqueado"})
    return jsonify(plano), 200

@core_api.post("/licencas/ativar-cupom")
@auth_required
def ativar_cupom():
    uid = g.user.uid
    data = request.get_json() or {}
    codigo = (data.get("codigo") or "").strip().upper()
    cupom = find_cupom_by_codigo(codigo)
    ok, msg, plano = validar_consumir_cupom(cupom, uid)
    if not ok:
        return jsonify({"erro": msg}), 400
    update_doc(f"profissionais/{uid}", {"plano": plano})
    return jsonify({"status": "ativo", "origem": "cupom"}), 200

@core_api.get("/agendamentos")
@auth_required
def listar_agendamentos():
    docs = db.collection(f"profissionais/{g.user.uid}/agendamentos").order_by("dataHora").stream()
    out = []
    for d in docs:
        o = d.to_dict()
        o["id"] = d.id
        out.append(o)
    return jsonify(out), 200

@core_api.post("/agendamentos")
@auth_required
def criar_agendamento():
    data = request.get_json() or {}
    ok, msg, ag = validar_agendamento_v1(g.user.uid, data)
    if not ok:
        return jsonify({"erro": msg}), 400
    ag = salvar_agendamento(g.user.uid, ag)
    return jsonify(ag), 201

@core_api.patch("/agendamentos/<ag_id>")
@auth_required
def atualizar_agendamento_route(ag_id):
    body = request.get_json() or {}
    try:
        ag = atualizar_estado_agendamento(g.user.uid, ag_id, body)
    except Exception as e:
        return jsonify({"erro": str(e)}), 400
    return jsonify(ag), 200
