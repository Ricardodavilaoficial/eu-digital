# routes/agenda_digest.py
# GET /api/agenda/digest?dry_run=true|false&date=YYYY-MM-DD&tz=America/Sao_Paulo
# - Auth: Bearer padrão do projeto OU header X-Debug-UID quando ALLOW_DEBUG_UID=1
# - Dry-run: retorna JSON com itens reais do dia + preview_html/text
# - Envio real: usa services.mailer.send_email (se disponível)
# - Personalização por ENV:
#     EMAIL_SENDER            (obrigatória p/ envio real)
#     EMAIL_REPLY_TO          (opcional)
#     DIGEST_LOGO_URL         (opcional)
#     DIGEST_BRAND_COLOR      (opcional, ex: #128C7E)
#     DIGEST_SIGNOFF          (opcional, ex: "Bom trabalho hoje! 🚀")
#     DIGEST_BCC              (opcional; múltiplos separados por vírgula)

import os
import logging
from datetime import datetime, timedelta

import pytz
from flask import Blueprint, request, jsonify

try:
    from services.db import db
except Exception:
    db = None

agenda_digest_bp = Blueprint("agenda_digest_bp", __name__, url_prefix="/api/agenda")

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


# ---------------- Repo & Mailer ----------------
_list_events_for = None
try:
    from services.agenda_repo import list_events_for as _list_events_for
except Exception:
    _list_events_for = None

_send_email = None
try:
    from services.mailer import send_email as _send_email
except Exception:
    _send_email = None


# ---------------- Helpers ----------------
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
    # date_str: 'YYYY-MM-DD'
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
        "segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"
    ]
    data_curta = dt.strftime("%d/%m")
    data_extenso = f"{dias_sem[dt.weekday()]}, {dt.day} de {meses[dt.month - 1]} de {dt.year}"
    return data_curta, data_extenso


def _fmt_item_line(it) -> str:
    nome = (it.get("cliente") or {}).get("nome") or "(Sem nome)"
    wa = (it.get("cliente") or {}).get("whatsapp") or ""
    hhmm = it.get("hhmm") or "??:??"
    svc = it.get("service_id") or "serviço"
    note_in = it.get("notes_internal") or ""
    tail = f" → obs: {note_in}" if note_in else ""
    wa_tail = f" [{wa}]" if wa else ""
    return f"{hhmm} — {svc} — {nome}{wa_tail}{tail}"


def _build_preview(uid, items, date_str, tz):
    # Cabeçalho humanizado (sem "(tz)")
    header = f"Agenda de hoje — {date_str}"
    if items:
        linhas = [_fmt_item_line(it) for it in items]
        summary = f"{len(items)} compromisso(s):\n" + "\n".join(linhas)
    else:
        summary = "Sem compromissos para hoje."

    return {
        "header": header,
        "summary": summary,
        "count": len(items),
        "items": items,  # inclui notes_internal
    }


def _build_email_bodies(nome_profissional, url_agenda, items, date_str, tz):
    brand = os.getenv("DIGEST_BRAND_COLOR", "#128C7E")
    logo = os.getenv("DIGEST_LOGO_URL", "").strip()
    signoff = os.getenv("DIGEST_SIGNOFF", "Bom trabalho hoje! 🚀")
    data_curta, data_extenso = _br_date_formats(date_str, tz)

    # Texto puro
    if items:
        linhas = [f"- {_fmt_item_line(it)}" for it in items]
        blocos = "\n".join(linhas)
    else:
        blocos = "- (sem compromissos para hoje)"

    text_subject = f"🗓️ Sua agenda de hoje — {data_curta}"
    text_body = (
        f"Bom dia, {nome_profissional}!\n\n"
        f"Aqui está sua agenda de hoje ({data_extenso}):\n\n"
        f"{blocos}\n\n"
        f"Abrir minha agenda: {url_agenda}\n\n"
        f"{signoff}\n"
        f"— MEI Robô"
    )

    # HTML
    # Observação: mantivemos layout simples e compatível com clientes de e-mail.
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
              <h2 style="margin:0 0 8px 0;color:{brand};font-size:22px;">🗓️ Agenda de hoje — {data_curta}</h2>
              <p style="margin:0 0 16px 0;">Bom dia, <strong>{nome_profissional}</strong>!</p>
              <ul style="list-style:none;padding-left:0;margin:0 0 16px 0;">
                {''.join(f'<li style="margin:0 0 8px 0;">{_fmt_item_line(it)}</li>' for it in items) if items else '<li style="margin:0 0 8px 0;">(sem compromissos para hoje)</li>'}
              </ul>
              <p style="margin:16px 0;">
                <a href="{url_agenda}"
                   style="display:inline-block;background:{brand};color:#fff;text-decoration:none;padding:10px 16px;border-radius:8px;">
                   Abrir minha agenda
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

    return text_subject, text_body, html_body


def _split_emails(value: str):
    if not value:
        return None
    # suporta lista com vírgulas e espaços
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
        logging.exception("[agenda_digest] falha ao ler nome do profissional para uid=%s", uid)
    return "MEI"


# ---------------- Route ----------------
@agenda_digest_bp.route("/digest", methods=["GET"])
def digest_get():
    uid = _require_uid(request)
    if not uid:
        return jsonify({"erro": "Auth obrigatório"}), 401

    # Query params
    dry_run = _parse_bool(request.args.get("dry_run"), default=True)
    tz = (request.args.get("tz") or request.args.get("timezone") or "America/Sao_Paulo").strip()
    date_str = (request.args.get("date") or "").strip() or _today_str_tz(tz)

    # Coleta eventos reais do dia (se repo disponível)
    items = []
    if _list_events_for:
        try:
            items = _list_events_for(uid, date_str, tz) or []
        except Exception:
            logging.exception("[agenda_digest] falha ao listar eventos")
            items = []
    else:
        logging.warning("[agenda_digest] agenda_repo.list_events_for indisponível")

    # Monta preview (humanizado)
    preview = _build_preview(uid, items, date_str, tz)

    # Corpos de e-mail (texto/HTML)
    nome_profissional = _get_profissional_name(uid)
    url_agenda = os.getenv("DIGEST_AGENDA_URL", "https://meirobo.com.br/pages/agenda.html?source=email-digest")
    subject, body_text, body_html = _build_email_bodies(
        nome_profissional, url_agenda, items, date_str, tz
    )

    # Log útil no Render
    logging.info("[agenda_digest] uid=%s dry_run=%s date=%s tz=%s count=%s",
                 uid, dry_run, date_str, tz, len(items))

    # Dry-run prévia
    if dry_run:
        return jsonify({
            "ok": True,
            "dry_run": True,
            "date": date_str,
            "tz": tz,
            "preview": preview,
            "preview_text": body_text,
            "preview_html": body_html,
        })

    # Envio real (se solicitado e possível)
    if not _send_email:
        return jsonify({
            "ok": False,
            "dry_run": False,
            "date": date_str,
            "error": "mailer_not_available",
            "detail": "services.mailer.send_email não encontrado."
        }), 501

    email_from = os.environ.get("EMAIL_SENDER") or os.environ.get("EMAIL_FROM") or ""
    if not email_from:
        return jsonify({
            "ok": False,
            "dry_run": False,
            "date": date_str,
            "error": "email_env_missing",
            "detail": "Configure EMAIL_SENDER para envio real."
        }), 400

    # destinatário obrigatório para envio real
    to_email = request.args.get("to") or request.headers.get("X-Digest-To")
    if not to_email:
        return jsonify({
            "ok": False,
            "dry_run": False,
            "date": date_str,
            "error": "recipient_missing",
            "detail": "Informe destinatário via ?to=email@dominio ou header X-Digest-To."
        }), 400

    # BCC (env ou header)
    bcc_header = request.headers.get("X-Digest-Bcc", "")
    bcc_env = os.getenv("DIGEST_BCC", "")
    bcc_list = _split_emails(bcc_header) or _split_emails(bcc_env)

    reply_to = os.getenv("EMAIL_REPLY_TO", "").strip() or None

    try:
        # Primeiro tenta com html/bcc/reply_to se o mailer aceitar
        _send_email(
            to=to_email,
            subject=subject,
            text=body_text,
            html=body_html,
            from_email=email_from,
            bcc=bcc_list,
            reply_to=reply_to,
            disable_click_tracking=True  # <<< patch: link direto (sem reescrita) só no digest
        )
    except TypeError:
        # Fallback: algumas implementações aceitam apenas texto
        _send_email(
            to=to_email,
            subject=subject,
            text=body_text,
            from_email=email_from
        )
    except Exception as e:
        logging.exception("[agenda_digest] send failed: %s", e)
        return jsonify({"ok": False, "dry_run": False, "date": date_str, "error": "send_failed", "detail": str(e)}), 500

    logging.info("[agenda_digest] sent to=%s bcc=%s", to_email, bcc_list)
    return jsonify({
        "ok": True,
        "dry_run": False,
        "date": date_str,
        "sent_to": to_email,
        "bcc": bcc_list
    })
