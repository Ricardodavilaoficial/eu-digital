# routes/orcamentos_digest.py
# GET /api/orcamentos/digest?dry_run=true|false&date=YYYY-MM-DD&tz=America/Sao_Paulo
# - Auth: Bearer padrão do projeto OU header X-Debug-UID quando ALLOW_DEBUG_UID=1
# - Dry-run: retorna JSON com itens reais do dia + preview_html/text
# - Envio real: usa services.mailer.send_email (se disponível)
# - Personalização por ENV (reutiliza os mesmos da agenda):
#     EMAIL_SENDER            (obrigatória p/ envio real)
#     EMAIL_REPLY_TO          (opcional)
#     DIGEST_LOGO_URL         (opcional)
#     DIGEST_BRAND_COLOR      (opcional, ex: #128C7E)
#     DIGEST_SIGNOFF          (opcional, ex: "Bom trabalho hoje! 🚀")
#     DIGEST_BCC              (opcional; múltiplos separados por vírgula)
#
# Observação:
# - Este digest é DIÁRIO: agrupa todos os orçamentos do dia para o MEI.
# - Para Cliente Zero vamos chamar em dry_run via curl; depois, com e-mail ligado, dry_run=false.

import os
import logging
from datetime import datetime, timedelta

import pytz
from flask import Blueprint, request, jsonify

try:
    from services.db import db
except Exception:
    db = None

orcamentos_digest_bp = Blueprint("orcamentos_digest_bp", __name__, url_prefix="/api/orcamentos")

# ---------------- Auth guard ----------------
_uid_from_bearer = None
try:
    from services.auth import get_uid_from_bearer as _uid_from_bearer
except Exception:
    _uid_from_bearer = None


def _require_uid(req):
    # 1) Produção: Bearer normal
    if _uid_from_bearer:
        try:
            uid = _uid_from_bearer(req)
            if uid:
                return uid
        except Exception:
            pass
    # 2) DEV: X-Debug-UID quando ALLOW_DEBUG_UID=1
    if os.getenv("ALLOW_DEBUG_UID", "0") == "1":
        dbg = req.headers.get("X-Debug-UID")
        if dbg:
            return dbg
    return None


# ---------------- Mailer ----------------
_send_email = None
try:
    from services.mailer import send_email as _send_email
except Exception:
    _send_email = None


# ---------------- Helpers genéricos ----------------
def _parse_bool(val, default=False):
    if val is None:
        return default
    s = str(val).strip().lower()
    return s in ("1", "true", "yes", "on")


def _today_str_tz(tz: str) -> str:
    try:
        zone = pytz.timezone(tz)
        return datetime.now(zone).strftime("%Y-%m-%d")
    except Exception:
        # fallback: -3h (BR) aproximado
        return (datetime.utcnow() - timedelta(hours=3)).strftime("%Y-%m-%d")


def _br_date_formats(date_str, tz):
    """
    date_str: 'YYYY-MM-DD'
    Retorna:
      - data_curta: 'DD/MM/AAAA'
      - data_extenso: 'quarta-feira, 26 de novembro de 2025'
    """
    try:
        y, m, d = [int(x) for x in date_str.split("-")]
        zone = pytz.timezone(tz)
        dt = zone.localize(datetime(y, m, d))
    except Exception:
        dt = datetime.utcnow()
    meses = [
        "janeiro", "fevereiro", "março", "abril", "maio", "junho",
        "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"
    ]
    dias_sem = [
        "segunda-feira", "terça-feira", "quarta-feira", "quinta-feira",
        "sexta-feira", "sábado", "domingo"
    ]
    data_curta = dt.strftime("%d/%m/%Y")
    data_extenso = f"{dias_sem[dt.weekday()]}, {dt.day} de {meses[dt.month - 1]} de {dt.year}"
    return dt, data_curta, data_extenso


def _fmt_moeda(valor: float, moeda: str = "BRL") -> str:
    # Por enquanto só BRL; se um dia tiver outra moeda, a gente trata.
    v = float(valor or 0.0)
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _split_emails(value: str):
    if not value:
        return None
    parts = [p.strip() for p in value.split(",") if p.strip()]
    return parts or None


def _get_profissional_name(uid: str) -> str:
    """
    Busca o nome do profissional em profissionais/{uid}.
    Fallback seguro: "MEI" se não encontrar nada.
    """
    if not db or not uid:
        return "MEI"
    try:
        doc = db.collection("profissionais").document(uid).get()
        if doc and doc.exists:
            data = doc.to_dict() or {}
            nome = (data.get("nome") or "").strip()
            if nome:
                return nome
    except Exception:
        logging.exception("[orcamentos_digest] falha ao ler nome do profissional para uid=%s", uid)
    return "MEI"


# ---------------- Repo de orçamentos ----------------
def _list_orcamentos_for(uid: str, date_str: str, tz: str):
    """
    Lista orçamentos do dia (janelinha do tz informado) em:
      profissionais/{uid}/orcamentos
    Campos usados:
      - numero
      - total
      - moeda
      - canalEnvio / canal
      - origem
      - clienteNome / cliente.nome
      - createdAt
    """
    if not db or not uid:
        logging.warning("[orcamentos_digest] db ou uid ausente")
        return []

    try:
        zone = pytz.timezone(tz)
    except Exception:
        zone = pytz.timezone("America/Sao_Paulo")

    try:
        y, m, d = [int(x) for x in date_str.split("-")]
        local_start = zone.localize(datetime(y, m, d, 0, 0, 0))
    except Exception:
        # fallback: hoje na tz
        local_start = zone.localize(datetime.now(zone).replace(hour=0, minute=0, second=0, microsecond=0))

    local_end = local_start + timedelta(days=1)

    start_utc = local_start.astimezone(pytz.UTC)
    end_utc = local_end.astimezone(pytz.UTC)

    col = (
        db.collection("profissionais")
        .document(uid)
        .collection("orcamentos")
    )

    try:
        # createdAt: Timestamp
        q = (
            col.where("createdAt", ">=", start_utc)
               .where("createdAt", "<", end_utc)
               .order_by("createdAt")
        )
        docs = list(q.stream())
    except Exception:
        # se der pau, tenta sem filtro (últimos 50) só pra não quebrar
        logging.exception("[orcamentos_digest] falha na query com filtro de data; tentando fallback")
        try:
            docs = list(col.order_by("createdAt", direction="DESCENDING").limit(50).stream())
        except Exception:
            logging.exception("[orcamentos_digest] fallback também falhou")
            return []

    items = []
    for doc in docs:
        d = doc.to_dict() or {}
        created = d.get("createdAt")
        if hasattr(created, "isoformat"):
            created_iso = created.isoformat()
        else:
            created_iso = str(created) if created else None

        cliente_nome = d.get("clienteNome") or (d.get("cliente") or {}).get("nome") or ""
        cliente_tipo = d.get("clienteTipo") or (d.get("cliente") or {}).get("tipo") or ""
        canal = d.get("canalEnvio") or d.get("canal") or "whatsapp"
        origem = d.get("origem") or "manual"
        numero = d.get("numero") or doc.id
        total = float(d.get("total") or 0.0)
        moeda = d.get("moeda") or "BRL"

        items.append({
            "id": doc.id,
            "numero": numero,
            "clienteNome": cliente_nome,
            "clienteTipo": cliente_tipo,
            "canal": canal,
            "origem": origem,
            "total": total,
            "total_fmt": _fmt_moeda(total, moeda),
            "moeda": moeda,
            "createdAt": created_iso,
        })

    return items


# ---------------- Formatação de linhas & preview ----------------
def _fmt_item_line(it) -> str:
    numero = it.get("numero") or it.get("id") or "ORC"
    cliente = it.get("clienteNome") or "Cliente"
    canal = it.get("canal") or "whatsapp"
    origem = it.get("origem") or "manual"
    total_fmt = it.get("total_fmt") or _fmt_moeda(it.get("total") or 0.0)
    return f"{numero} — {cliente} — {total_fmt} ({canal}, {origem})"


def _build_preview(items, date_str_br, date_extenso):
    if items:
        linhas = [_fmt_item_line(it) for it in items]
        summary = f"{len(items)} orçamento(s):\n" + "\n".join(linhas)
    else:
        summary = "Sem orçamentos para hoje."

    header = f"Orçamentos de hoje — {date_str_br}"
    return {
        "header": header,
        "summary": summary,
        "count": len(items),
        "items": items,
        "date_extenso": date_extenso,
    }


def _build_email_bodies(nome_profissional, url_orcamentos, items, date_str, tz):
    # date_str é YYYY-MM-DD
    _dt, data_curta_br, data_extenso = _br_date_formats(date_str, tz)

    brand = os.getenv("DIGEST_BRAND_COLOR", "#128C7E")
    logo = os.getenv("DIGEST_LOGO_URL", "").strip()
    signoff = os.getenv("DIGEST_SIGNOFF", "Bom trabalho hoje! 🚀")

    # Texto puro
    if items:
        linhas = [f"- {_fmt_item_line(it)}" for it in items]
        blocos = "\n".join(linhas)
    else:
        blocos = "- (sem orçamentos para hoje)"

    text_subject = f"🧾 Seus orçamentos de hoje — {data_curta_br}"
    text_body = (
        f"Olá, {nome_profissional}!\n\n"
        f"Aqui estão seus orçamentos de hoje ({data_extenso}):\n\n"
        f"{blocos}\n\n"
        f"Abrir a tela de orçamentos: {url_orcamentos}\n\n"
        f"{signoff}\n"
        f"— MEI Robô"
    )

    # HTML simples compatível com clientes de e-mail
    itens_html = (
        "".join(f'<li style="margin:0 0 8px 0;">{_fmt_item_line(it)}</li>' for it in items)
        if items else '<li style="margin:0 0 8px 0;">(sem orçamentos para hoje)</li>'
    )

    html_body = f"""<!DOCTYPE html>
<html lang="pt-BR">
  <body style="margin:0;background:#f6f7f9;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f6f7f9;">
      <tr><td align="center" style="padding:24px;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:640px;background:#fff;border-radius:12px;padding:24px;font-family:Arial,Helvetica,sans-serif;color:#222;">
          <tr>
            <td style="text-align:center;padding-bottom:16px;">
              {f'<img src="{logo}" alt="MEI Robô" style="height:40px;display:inline-block;">' if logo else ''}
            </td>
          </tr>
          <tr>
            <td>
              <h2 style="margin:0 0 8px 0;color:{brand};font-size:22px;">🧾 Orçamentos de hoje — {data_curta_br}</h2>
              <p style="margin:0 0 16px 0;">Olá, <strong>{nome_profissional}</strong>!</p>
              <ul style="list-style:none;padding-left:0;margin:0 0 16px 0;">
                {itens_html}
              </ul>
              <p style="margin:16px 0;">
                <a href="{url_orcamentos}"
                   style="display:inline-block;background:{brand};color:#fff;text-decoration:none;padding:10px 16px;border-radius:8px;">
                   Abrir tela de orçamentos
                </a>
              </p>
              <p style="margin:16px 0 8px 0;color:#333;">{signoff}</p>
              <hr style="border:none;border-top:1px solid #eee;margin:16px 0;">
              <p style="margin:0;color:#999;font-size:12px;">
                Recebeu este e-mail porque seu MEI Robô está ativo. Precisa de ajuda? Responda para {os.getenv("EMAIL_REPLY_TO","suporte@fujicadobrasil.com.br")}.
              </p>
            </td>
          </tr>
        </table>
        <div style="max-width:640px;margin-top:12px;color:#9aa0a6;font-size:11px;font-family:Arial,Helvetica,sans-serif;">
          © {datetime.now().year} MEI Robô — Todos os direitos reservados.
        </div>
      </td></tr>
    </table>
  </body>
</html>"""

    return text_subject, text_body, html_body, data_curta_br, data_extenso


# ---------------- Route ----------------
@orcamentos_digest_bp.route("/digest", methods=["GET"])
def orcamentos_digest():
    uid = _require_uid(request)
    if not uid:
        return jsonify({"erro": "Auth obrigatório"}), 401

    dry_run = _parse_bool(request.args.get("dry_run"), default=True)
    tz = (request.args.get("tz") or request.args.get("timezone") or "America/Sao_Paulo").strip()
    date_str = (request.args.get("date") or "").strip() or _today_str_tz(tz)

    # Carrega orçamentos reais do dia
    items = _list_orcamentos_for(uid, date_str, tz)
    total = sum(float(it.get("total") or 0.0) for it in items)
    total_fmt = _fmt_moeda(total)

    # Info de data para preview/e-mail
    _dt, data_curta_br, data_extenso = _br_date_formats(date_str, tz)

    preview = _build_preview(items, data_curta_br, data_extenso)

    nome_profissional = _get_profissional_name(uid)
    url_orcamentos = os.getenv(
        "DIGEST_ORCAMENTOS_URL",
        "https://meirobo.com.br/pages/orcamentos.html?source=email-digest",
    )
    subject, body_text, body_html, data_curta_br, data_extenso = _build_email_bodies(
        nome_profissional, url_orcamentos, items, date_str, tz
    )

    logging.info(
        "[orcamentos_digest] uid=%s dry_run=%s date=%s tz=%s count=%s total=%s",
        uid, dry_run, date_str, tz, len(items), total
    )

    # DRY RUN → só mostra o que seria enviado
    if dry_run:
        return jsonify({
            "ok": True,
            "dry_run": True,
            "reason": "dry_run",
            "date": data_curta_br,       # mantém formato pt-BR, ex: 26/11/2025
            "tz": tz,
            "count": len(items),
            "items": items,
            "total": total,
            "total_fmt": total_fmt,
            "email_sent": False,
            "preview": preview,
            "preview_text": body_text,
            "preview_html": body_html,
        })

    # Envio real de e-mail
    if not _send_email:
        return jsonify({
            "ok": False,
            "dry_run": False,
            "reason": "mailer_not_available",
            "date": data_curta_br,
            "tz": tz,
            "error": "mailer_not_available",
            "detail": "services.mailer.send_email não encontrado."
        }), 501

    email_from = os.environ.get("EMAIL_SENDER") or os.environ.get("EMAIL_FROM") or ""
    if not email_from:
        return jsonify({
            "ok": False,
            "dry_run": False,
            "reason": "email_env_missing",
            "date": data_curta_br,
            "tz": tz,
            "error": "email_env_missing",
            "detail": "Configure EMAIL_SENDER para envio real."
        }), 400

    # destinatário: ?to=email@dominio ou header X-Digest-To
    to_email = request.args.get("to") or request.headers.get("X-Digest-To")
    if not to_email:
        return jsonify({
            "ok": False,
            "dry_run": False,
            "reason": "recipient_missing",
            "date": data_curta_br,
            "tz": tz,
            "error": "recipient_missing",
            "detail": "Informe destinatário via ?to=email@dominio ou header X-Digest-To."
        }), 400

    # BCC (env ou header)
    bcc_header = request.headers.get("X-Digest-Bcc", "")
    bcc_env = os.getenv("DIGEST_BCC", "")
    bcc_list = _split_emails(bcc_header) or _split_emails(bcc_env)

    reply_to = os.getenv("EMAIL_REPLY_TO", "").strip() or None

    try:
        _send_email(
            to=to_email,
            subject=subject,
            text=body_text,
            html=body_html,
            from_email=email_from,
            bcc=bcc_list,
            reply_to=reply_to,
            disable_click_tracking=True,  # igual agenda: link direto
        )
    except TypeError:
        # fallback simples
        _send_email(
            to=to_email,
            subject=subject,
            text=body_text,
            from_email=email_from,
        )
    except Exception as e:
        logging.exception("[orcamentos_digest] send failed: %s", e)
        return jsonify({
            "ok": False,
            "dry_run": False,
            "reason": "send_failed",
            "date": data_curta_br,
            "tz": tz,
            "error": "send_failed",
            "detail": str(e),
        }), 500

    logging.info("[orcamentos_digest] sent to=%s bcc=%s", to_email, bcc_list)
    return jsonify({
        "ok": True,
        "dry_run": False,
        "reason": "sent",
        "date": data_curta_br,
        "tz": tz,
        "count": len(items),
        "total": total,
        "total_fmt": total_fmt,
        "sent_to": to_email,
        "bcc": bcc_list,
        "email_sent": True,
    })
