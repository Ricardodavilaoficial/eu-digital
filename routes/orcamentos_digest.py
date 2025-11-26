# routes/orcamentos_digest.py
# Digest diário de orçamentos do MEI Robô
#
# GET /api/orcamentos/digest?dry_run=true|false&date=YYYY-MM-DD&tz=America/Sao_Paulo
#
# - Auth:
#     Authorization: Bearer <token Firebase>  OU
#     X-Debug-UID: <uid> quando ALLOW_DEBUG_UID=1
# - Lê profissionais/{uid}/orcamentos do dia informado
# - dry_run=true  -> só retorna JSON com o resumo (não envia e-mail)
# - dry_run=false -> envia e-mail se houver ao menos 1 orçamento no dia

import os
import logging
from datetime import datetime, timedelta, timezone

import pytz
from flask import Blueprint, request, jsonify, g
import base64
import json as _json

from services.db import db  # mesmo client do app principal

try:
    from services import mailer  # type: ignore
except Exception:  # pragma: no cover
    mailer = None  # type: ignore

orcamentos_digest_bp = Blueprint(
    "orcamentos_digest_bp",
    __name__,
    url_prefix="/api/orcamentos",
)

log = logging.getLogger(__name__)

ALLOW_DEBUG_UID = os.environ.get("ALLOW_DEBUG_UID", "0") == "1"
EMAIL_SENDER = os.environ.get("EMAIL_SENDER") or ""  # mesmo usado em agenda_digest
EMAIL_REPLY_TO = os.environ.get("EMAIL_REPLY_TO") or ""
DIGEST_BRAND_COLOR = os.environ.get("DIGEST_BRAND_COLOR") or "#128C7E"
DIGEST_SIGNOFF = os.environ.get("DIGEST_SIGNOFF") or "Bom trabalho hoje com seus clientes! 🚀"
DIGEST_BCC = os.environ.get("DIGEST_BCC") or ""


def _uid_from_bearer_fallback():
    """
    Decodifica o Firebase ID token direto do header Authorization (sem verificar assinatura).
    Serve como fallback se g.uid não estiver preenchido.
    """
    auth = (request.headers.get("Authorization") or "").strip()
    if not auth.lower().startswith("bearer "):
        return None
    tok = auth.split(" ", 1)[1].strip()
    parts = tok.split(".")
    if len(parts) < 2:
        return None
    try:
        pad = "=" * ((4 - len(parts[1]) % 4) % 4)
        payload = _json.loads(
            base64.urlsafe_b64decode((parts[1] + pad).encode("utf-8")).decode("utf-8")
        )
        return payload.get("user_id") or payload.get("uid") or payload.get("sub")
    except Exception:
        return None


def _require_uid():
    """
    Tenta primeiro g.uid (preenchido pelo app.before_request).
    Se não tiver, decodifica o Bearer localmente.
    """
    uid = getattr(g, "uid", None) or _uid_from_bearer_fallback()
    if not uid:
        return None, (jsonify({"ok": False, "error": "unauthenticated"}), 401)
    return uid, None


def _get_uid_from_request():
    """
    Resolve o UID a partir do X-Debug-UID (quando permitido) ou do helper _require_uid().
    Mantém compatibilidade com o uso atual deste módulo.
    """
    # Modo debug explícito (útil pra curl local)
    if ALLOW_DEBUG_UID:
        dbg = (request.headers.get("X-Debug-UID") or "").strip()
        if dbg:
            return dbg

    uid, err = _require_uid()
    if err is not None:
        return None
    return uid


def _parse_date(param_name: str, tz_str: str):
    """
    Lê ?date=YYYY-MM-DD (ou usa hoje no fuso informado) e devolve (dt_inicio, dt_fim, data_br).
    """
    tz = pytz.timezone(tz_str)
    raw = (request.args.get(param_name) or "").strip()
    if raw:
        try:
            y, m, d = [int(x) for x in raw.split("-")]
            base = tz.localize(datetime(y, m, d, 0, 0, 0))
        except Exception:
            base = tz.localize(datetime.now())
    else:
        base = tz.localize(datetime.now())

    inicio = base.replace(hour=0, minute=0, second=0, microsecond=0)
    fim = inicio + timedelta(days=1)

    data_br = inicio.strftime("%d/%m/%Y")
    return inicio, fim, data_br, tz


def _fmt_brl(v: float) -> str:
    try:
        s = f"{v:,.2f}"
    except Exception:
        s = "0.00"
    # 1,234.56 -> 1.234,56
    s = s.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {s}"


@orcamentos_digest_bp.route("/digest", methods=["GET"])
def orcamentos_digest():
    uid = _get_uid_from_request()
    if not uid:
        return jsonify({"ok": False, "error": "unauthenticated"}), 401

    dry_run = (request.args.get("dry_run") or "true").lower() == "true"
    tz_str = (request.args.get("tz") or "America/Sao_Paulo").strip() or "America/Sao_Paulo"

    try:
        dt_inicio, dt_fim, data_br, tz = _parse_date("date", tz_str)
    except Exception as e:
        return jsonify({"ok": False, "error": "bad_date", "detail": str(e)}), 400

    # Buscamos um lote razoável e filtramos em memória por data (como no listar_orcamentos)
    try:
        col = db.collection("profissionais").document(uid).collection("orcamentos")
        docs = list(col.limit(500).stream())
    except Exception as e:
        log.error("[orcamentos_digest] erro ao ler Firestore: %s", e)
        return jsonify({"ok": False, "error": "internal_error"}), 500

    itens = []
    total_dia = 0.0

    for doc in docs:
        d = doc.to_dict() or {}
        created_at = d.get("createdAt") or d.get("created_at")
        if not created_at:
            continue

        # createdAt vem em ISO (ex.: 2025-11-26T12:34:56+00:00)
        try:
            dt = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
            # Converte para o fuso do MEI pra comparar o "dia"
            dt_local = dt.astimezone(tz)
        except Exception:
            continue

        if not (dt_inicio <= dt_local < dt_fim):
            continue

        numero = d.get("numero") or doc.id
        cliente_nome = (
            d.get("clienteNome")
            or (d.get("cliente") or {}).get("nome")
            or ""
        )
        origem = (d.get("origem") or "manual").lower()
        canal = (d.get("canalEnvio") or "").lower() or "indefinido"
        total = float(d.get("total") or 0.0)

        total_dia += total

        itens.append(
            {
                "id": doc.id,
                "numero": numero,
                "clienteNome": cliente_nome,
                "origem": origem,
                "canal": canal,
                "total": total,
                "createdAt": created_at,
            }
        )

    itens.sort(key=lambda x: x.get("numero") or "")

    resumo = {
        "ok": True,
        "date": data_br,
        "tz": tz_str,
        "count": len(itens),
        "total": total_dia,
        "total_fmt": _fmt_brl(total_dia),
        "items": itens,
    }

    if dry_run or not EMAIL_SENDER or mailer is None:
        # Só preview, sem disparar e-mail
        resumo["email_sent"] = False
        resumo["reason"] = (
            "dry_run" if dry_run else "EMAIL_SENDER/mailer não configurados"
        )
        return jsonify(resumo), 200

    if not itens:
        resumo["email_sent"] = False
        resumo["reason"] = "sem_orcamentos_no_dia"
        return jsonify(resumo), 200

    # Monta texto simples; HTML pode vir depois se precisar
    linhas = []
    for it in itens:
        linhas.append(
            f"- {it['numero']} — {it['clienteNome'] or 'Cliente'} — "
            f"{_fmt_brl(it['total'])} — origem: {it['origem']} — canal: {it['canal']}"
        )

    body_text = (
        f"Resumo de orçamentos do dia {data_br}\n\n"
        f"Total de orçamentos: {len(itens)}\n"
        f"Somatório: {resumo['total_fmt']}\n\n"
        + "\n".join(linhas)
        + "\n\n"
        + DIGEST_SIGNOFF
    )

    subject = f"[MEI Robô] Resumo de orçamentos — {data_br}"

    to_email = d.get("emailDestino") if itens else None  # fallback frágil
    # Por enquanto, se não acharmos e-mail de destino, não enviamos nada
    if not to_email:
        resumo["email_sent"] = False
        resumo["reason"] = "email_destino_indefinido"
        return jsonify(resumo), 200

    try:
        mailer.send_email(
            to_email=to_email,
            subject=subject,
            text=body_text,
            html=None,  # manter simples no v1.0
            sender=EMAIL_SENDER,
            reply_to=EMAIL_REPLY_TO or None,
            bcc=[x.strip() for x in DIGEST_BCC.split(",") if x.strip()] or None,
        )
        resumo["email_sent"] = True
        resumo["reason"] = "ok"
    except Exception as e:  # pragma: no cover
        log.error("[orcamentos_digest] erro ao enviar e-mail: %s", e)
        resumo["email_sent"] = False
        resumo["reason"] = "erro_envio_email"
        resumo["error_detail"] = str(e)

    return jsonify(resumo), 200
