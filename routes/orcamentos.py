# routes/orcamentos.py
# Blueprint oficial de Orçamentos do MEI Robô
#
# Rotas:
#   GET  /api/orcamentos        -> lista orçamentos do profissional logado
#   POST /api/orcamentos        -> cria um orçamento (manual ou bot)
#
# Armazenamento:
#   profissionais/{uid}/orcamentos/{orcId}
#
# Obs:
# - NÃO duplica CNPJ/nome/logo do MEI: isso continua em profissionais/{uid} e config/orcamentos.
# - Guarda só o "evento" do orçamento + um snapshot leve do cliente.

import os
from datetime import timedelta
from google.cloud import storage

from datetime import datetime, timezone
import random

from flask import Blueprint, request, jsonify, g

from services.db import db  # mesmo client usado em app.py

orcamentos_bp = Blueprint("orcamentos_bp", __name__, url_prefix="/api/orcamentos")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_uid():
    """
    Usa g.uid preenchido pelo app.before_request (_inject_uid_from_bearer).
    """
    uid = getattr(g, "uid", None)
    if not uid:
        return None, (jsonify({"ok": False, "error": "unauthenticated"}), 401)
    return uid, None


def _parse_date_param(name: str):
    """
    Lê ?de=YYYY-MM-DD / ?ate=YYYY-MM-DD e devolve datetime.date ou None.
    """
    raw = (request.args.get(name) or "").strip()
    if not raw:
        return None
    try:
        # formato simples YYYY-MM-DD
        y, m, d = [int(x) for x in raw.split("-")]
        return datetime(y, m, d, tzinfo=timezone.utc).date()
    except Exception:
        return None


def _safe_float(v, default=0.0):
    try:
        return float(v)
    except Exception:
        return default


@orcamentos_bp.route("", methods=["GET"])
def listar_orcamentos():
    """
    Lista orçamentos do profissional logado.

    Query params (opcionais):
      - de=YYYY-MM-DD
      - ate=YYYY-MM-DD
      - ordenar=recentes|antigos|maior|menor
      - limit=50 (padrão)
    """
    uid, err = _require_uid()
    if err:
        return err

    try:
        try:
            limit = int(request.args.get("limit", "50") or "50")
        except Exception:
            limit = 50
        if limit <= 0 or limit > 200:
            limit = 50

        data_de = _parse_date_param("de")
        data_ate = _parse_date_param("ate")
        ordenar = (request.args.get("ordenar") or "recentes").strip().lower()

        col = db.collection("profissionais").document(uid).collection("orcamentos")
        # Buscamos um lote moderado e ordenamos/filtramos em memória
        query = col.limit(limit)
        docs = list(query.stream())

        items = []
        for doc in docs:
            d = doc.to_dict() or {}
            created_at = d.get("createdAt") or d.get("created_at")  # tolerante a variações
            numero = d.get("numero") or doc.id
            total = _safe_float(d.get("total"), 0.0)
            cliente_nome = d.get("clienteNome") or (d.get("cliente") or {}).get("nome") or ""
            cliente_tipo = d.get("clienteTipo") or (d.get("cliente") or {}).get("tipo") or ""
            origem = (d.get("origem") or "manual").lower()

            # Filtro por data (se houver createdAt em ISO)
            if created_at and (data_de or data_ate):
                try:
                    dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                    dia = dt.date()
                except Exception:
                    dia = None

                if dia:
                    if data_de and dia < data_de:
                        continue
                    if data_ate and dia > data_ate:
                        continue

            items.append({
                "id": doc.id,
                "numero": numero,
                "createdAt": created_at,
                "total": total,
                "moeda": d.get("moeda") or "BRL",
                "origem": origem,
                "clienteNome": cliente_nome,
                "clienteTipo": cliente_tipo,
            })

        # Ordenação em memória
        if ordenar == "antigos":
            items.sort(key=lambda x: x.get("createdAt") or "")
        elif ordenar == "maior":
            items.sort(key=lambda x: x.get("total") or 0.0, reverse=True)
        elif ordenar == "menor":
            items.sort(key=lambda x: x.get("total") or 0.0)
        else:  # "recentes" (default)
            items.sort(key=lambda x: x.get("createdAt") or "", reverse=True)

        return jsonify({"ok": True, "items": items}), 200

    except Exception as e:
        # Evita derrubar o app em caso de erro de Firestore
        return jsonify({"ok": False, "error": "internal_error", "detail": str(e)}), 500


def _gera_numero_if_needed(data: dict) -> str:
    """
    Gera número de orçamento se não vier nenhum.
    Formato: ORC-YYYY-XXXXX (rand simples, suficiente p/ v1.0)
    """
    num = (data.get("numero") or "").strip()
    if num:
        return num
    ano = datetime.now().year
    seq = random.randint(10000, 99999)
    return f"ORC-{ano}-{seq:05d}"


def _calcula_total(itens):
    total = 0.0
    for it in itens or []:
        preco = _safe_float(it.get("preco"), 0.0)
        qtd = _safe_float(it.get("qtd"), 0.0) or 0.0
        total += preco * qtd
    return total


@orcamentos_bp.route("", methods=["POST"])
def criar_orcamento():
    """
    Cria um orçamento (manual ou bot).

    Body esperado (mínimo):
    {
      "origem": "manual" | "bot",
      "numero": "ORC-2025-00001" (opcional, se não vier o backend gera),
      "clienteId": "abc123" (opcional, se veio de clientes/{clienteId}),
      "cliente": {
        "tipo": "condominio" | "pf" | "pj" | "outro",
        "nome": "...",
        "contato": "...",
        "telefone": "...",
        "email": "...",
        "obs": "..."
      },
      "itens": [
        {"codigo": "...", "nome": "...", "preco": 100.0, "qtd": 1, "duracaoMin": 30},
        ...
      ],
      "mensagemEnvio": "...",
      "infoAdicionais": "...",
      "canalEnvio": "whatsapp" | "email" | "impresso"
    }
    """
    uid, err = _require_uid()
    if err:
        return err

    data = request.get_json(silent=True) or {}

    try:
        origem = (data.get("origem") or "manual").strip().lower()
        if origem not in {"manual", "bot"}:
            origem = "manual"

        numero = _gera_numero_if_needed(data)
        cliente = data.get("cliente") or {}
        cliente_id = (data.get("clienteId") or "").strip()

        # Itens
        itens = data.get("itens") or []
        # Normaliza itens minimamente
        norm_itens = []
        for it in itens:
            if not isinstance(it, dict):
                continue
            norm_itens.append({
                "codigo": (it.get("codigo") or "").strip(),
                "nome": (it.get("nome") or "").strip(),
                "preco": _safe_float(it.get("preco"), 0.0),
                "qtd": _safe_float(it.get("qtd"), 0.0) or 0.0,
                "duracaoMin": _safe_float(it.get("duracaoMin"), 0.0),
            })

        total = _calcula_total(norm_itens)
        created_at = _now_iso()

        doc = {
            "numero": numero,
            "origem": origem,
            "createdAt": created_at,
            "total": total,
            "moeda": data.get("moeda") or "BRL",
            "clienteId": cliente_id or None,
            "clienteTipo": (cliente.get("tipo") or "").strip(),
            "clienteNome": (cliente.get("nome") or "").strip(),
            "clienteContato": (cliente.get("contato") or "").strip(),
            "clienteTelefone": (cliente.get("telefone") or "").strip(),
            "clienteEmail": (cliente.get("email") or "").strip(),
            "clienteObs": (cliente.get("obs") or "").strip(),
            "cliente": cliente,  # snapshot leve, opcional
            "itens": norm_itens,
            "mensagemEnvio": data.get("mensagemEnvio") or "",
            "infoAdicionais": data.get("infoAdicionais") or "",
            "canalEnvio": (data.get("canalEnvio") or "").strip().lower() or None,
            "status": (data.get("status") or "enviado").strip().lower(),
        }

        col = db.collection("profissionais").document(uid).collection("orcamentos")
        # Se veio um orcId específico, usamos; se não, document() gera ID.
        orc_id = (data.get("id") or "").strip()
        if orc_id:
            ref = col.document(orc_id)
        else:
            ref = col.document()
            orc_id = ref.id

        ref.set(doc, merge=False)

        return jsonify({
            "ok": True,
            "id": orc_id,
            "numero": numero,
            "total": total,
            "moeda": doc["moeda"],
            "createdAt": created_at,
            "origem": origem,
        }), 201

    except Exception as e:
        return jsonify({"ok": False, "error": "internal_error", "detail": str(e)}), 500


@orcamentos_bp.route("/timbrado", methods=["POST", "OPTIONS"])
def upload_timbrado():
    # Preflight CORS
    if request.method == "OPTIONS":
        return ("", 204)

    uid, err = _require_uid()
    if err:
        return err

    # form-data
    kind = (request.form.get("kind") or "").strip().lower()
    f = request.files.get("file")

    if kind not in ("logo", "assinatura", "carimbo", "avatar"):
        return jsonify({"ok": False, "error": "invalid_kind"}), 400
    if not f:
        return jsonify({"ok": False, "error": "missing_file"}), 400

    # Extensão/mime conservador
    filename = (f.filename or "").lower()
    ext = "png"
    if "." in filename:
        ext = filename.rsplit(".", 1)[-1].strip() or "png"
    if ext not in ("png", "jpg", "jpeg", "webp"):
        return jsonify({"ok": False, "error": "invalid_ext"}), 400

    content_type = f.mimetype or "application/octet-stream"
    if content_type not in ("image/png", "image/jpeg", "image/webp", "application/octet-stream"):
        return jsonify({"ok": False, "error": "invalid_mime"}), 400

    # 1 por MEI (substitui sempre)
    bucket_name = os.environ["STORAGE_BUCKET"]
    object_path = f"profissionais/{uid}/orcamentos/{kind}.{ext}"

    try:
        client = storage.Client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(object_path)
        blob.upload_from_file(f.stream, content_type=content_type)

        expires = int(os.environ.get("SIGNED_URL_EXPIRES_SECONDS", "900") or "900")
        signed_url = blob.generate_signed_url(
            expiration=timedelta(seconds=expires),
            method="GET",
            version="v4",
        )

        return jsonify({
            "ok": True,
            "path": object_path,
            "signedUrl": signed_url,
        }), 200

    except Exception as e:
        return jsonify({"ok": False, "error": "upload_failed", "detail": str(e)}), 500

