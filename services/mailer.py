# services/mailer.py
# Mailer mínimo para SendGrid via HTTP API (sem dependências externas)

import os, json, time
from urllib import request as ulreq
from urllib.error import HTTPError, URLError
from typing import Iterable, Union

# SMTP fallback (Google Workspace / Gmail SMTP)
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

class MailerError(RuntimeError): ...
class ProviderNotSupported(MailerError): ...
class MissingConfig(MailerError): ...

# -----------------------
# Cooldown / circuit breaker (SendGrid -> SMTP)
# -----------------------
_SENDGRID_DISABLED_UNTIL_TS: float = 0.0

def _cooldown_seconds() -> int:
    try:
        return int(os.getenv("EMAIL_FAILOVER_COOLDOWN_SECONDS", "300"))
    except Exception:
        return 300

def _now() -> float:
    return time.time()

def _is_sendgrid_in_cooldown() -> bool:
    try:
        return _now() < float(_SENDGRID_DISABLED_UNTIL_TS or 0.0)
    except Exception:
        return False

def _set_sendgrid_cooldown(reason: str = "") -> None:
    global _SENDGRID_DISABLED_UNTIL_TS
    _SENDGRID_DISABLED_UNTIL_TS = _now() + float(_cooldown_seconds())

def _clear_sendgrid_cooldown() -> None:
    global _SENDGRID_DISABLED_UNTIL_TS
    _SENDGRID_DISABLED_UNTIL_TS = 0.0

def _failover_enabled() -> bool:
    return (os.getenv("EMAIL_FAILOVER_ENABLED", "1") or "1").strip().lower() in ("1", "true", "yes", "on")

def _smtp_timeout() -> int:
    try:
        return int(os.getenv("SMTP_TIMEOUT", "20"))
    except Exception:
        return 20

# -----------------------
# Helpers internos
# -----------------------
def _norm_emails(x: Union[str, Iterable[str]] | None) -> list[str]:
    if not x:
        return []
    if isinstance(x, str):
        parts = [p.strip() for p in x.replace(";", ",").split(",")]
        return [p for p in parts if p]
    return [str(p).strip() for p in x if str(p).strip()]

def _parse_from(s: str) -> tuple[str | None, str]:
    s = (s or "").strip()
    if "<" in s and ">" in s:
        try:
            name_part = s.split("<", 1)[0].strip().strip('"').strip()
            addr_part = s.split("<", 1)[1].split(">", 1)[0].strip()
            if "@" in addr_part:
                return (name_part or None), addr_part
        except Exception:
            pass
    return (None, s)


# -----------------------
# SMTP sender (fallback)
# -----------------------
def _send_smtp(
    *,
    to_list: list[str],
    subject: str,
    text: str | None,
    html: str | None,
    from_env: str,
    bcc_list: list[str],
    reply_to: str | None,
) -> bool:
    host = (os.getenv("SMTP_HOST") or "smtp.gmail.com").strip()
    port_raw = (os.getenv("SMTP_PORT") or "587").strip()
    try:
        port = int(port_raw)
    except Exception:
        port = 587

    user = (os.getenv("SMTP_USER") or "").strip()
    password = (os.getenv("SMTP_PASS") or "").strip()

    from_name, from_addr = _parse_from(from_env)
    if "@" not in (from_addr or ""):
        raise MissingConfig("Remetente inválido; verifique EMAIL_SENDER/EMAIL_FROM")

    if not to_list:
        raise MailerError("destinatário inválido")

    # Monta MIME
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject or ""
    msg["From"] = f'{from_name} <{from_addr}>' if from_name else from_addr
    msg["To"] = ", ".join(to_list)
    if reply_to:
        msg["Reply-To"] = reply_to

    # Headers mínimos “transacionais”
    msg["Auto-Submitted"] = "auto-generated"
    msg["X-Purpose"] = "transactional"

    # Corpo: sempre tenta incluir text; html é opcional
    body_text = text if text is not None else ""
    msg.attach(MIMEText(body_text, "plain", "utf-8"))
    if html:
        msg.attach(MIMEText(html, "html", "utf-8"))

    recipients = list(to_list)
    if bcc_list:
        # BCC não vai no header (pra não vazar); só no envelope
        recipients.extend([e for e in bcc_list if e and e.lower() not in {x.lower() for x in to_list}])

    timeout = _smtp_timeout()

    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=timeout) as server:
                if user and password:
                    server.login(user, password)
                server.sendmail(from_addr, recipients, msg.as_string())
        else:
            with smtplib.SMTP(host, port, timeout=timeout) as server:
                try:
                    server.ehlo()
                except Exception:
                    pass
                try:
                    server.starttls()
                    try:
                        server.ehlo()
                    except Exception:
                        pass
                except Exception:
                    # alguns relays podem estar sem TLS; se for o caso, segue (ou configure corretamente)
                    pass
                if user and password:
                    server.login(user, password)
                server.sendmail(from_addr, recipients, msg.as_string())
    except Exception as e:
        raise MailerError(f"smtp_failed: {e}") from e

    return True

# -----------------------
# SendGrid sender (primary)
# -----------------------
def _send_sendgrid(
    *,
    api_key: str,
    to_list: list[str],
    subject: str,
    text: str | None,
    html: str | None,
    from_env: str,
    bcc_list: list[str],
    reply_to: str | None,
    disable_click_tracking: bool,
) -> bool:
    from_name, from_addr = _parse_from(from_env)
    if "@" not in from_addr:
        fallback = (os.environ.get("EMAIL_SENDER") or "").strip()
        fn2_name, fn2_addr = _parse_from(fallback)
        if "@" in fn2_addr:
            from_name, from_addr = fn2_name, fn2_addr
        else:
            raise MissingConfig("Remetente inválido; verifique EMAIL_SENDER/EMAIL_FROM")

    personalization = {"to": [{"email": e} for e in to_list]}
    if bcc_list:
        personalization["bcc"] = [{"email": e} for e in bcc_list]

    content = [{"type": "text/plain", "value": text or ""}]
    if html:
        content.append({"type": "text/html", "value": html})

    payload: dict = {
        "personalizations": [personalization],
        "from": {"email": from_addr},
        "subject": subject,
        "content": content,
        "headers": {
            "X-Purpose": "transactional",
            "Auto-Submitted": "auto-generated",
        },
    }
    if from_name:
        payload["from"]["name"] = from_name

    if reply_to:
        payload["reply_to"] = {"email": reply_to}
        payload["headers"]["List-Unsubscribe"] = f"<mailto:{reply_to}>"

    if disable_click_tracking or (os.getenv("DISABLE_CLICK_TRACKING", "0") == "1"):
        payload["tracking_settings"] = {
            "click_tracking": {"enable": False, "enable_text": False}
        }

    req = ulreq.Request(
        "https://api.sendgrid.com/v3/mail/send",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with ulreq.urlopen(req, timeout=20) as resp:
            status = getattr(resp, "status", resp.getcode())
    except HTTPError as e:
        try:
            detail = e.read().decode("utf-8", "ignore")[:500]
        except Exception:
            detail = ""
        raise MailerError(f"sendgrid_status_{e.code}: {detail}") from e
    except URLError as e:
        raise MailerError(f"sendgrid_connection_error: {e.reason}") from e
    except Exception as e:
        raise MailerError(f"sendgrid_request_failed: {e}") from e

    if status not in (200, 202):
        raise MailerError(f"sendgrid_unexpected_status_{status}")

    return True

# -----------------------
# Envio genérico (mantido)
# -----------------------
def send_email(
    *,
    to=None,
    subject: str = "",
    text: str | None = None,
    from_email: str | None = None,
    html: str | None = None,
    bcc=None,
    reply_to: str | None = None,
    disable_click_tracking: bool = False,  # << ideal p/ verificação
    **kw,
):
    """
    Envia e-mail via SendGrid HTTP API.
    Aceita aliases: body_text/body_html e ignora kwargs extras.
    """
    if text is None:
        text = kw.pop("body_text", None)
    if html is None:
        html = kw.pop("body_html", None)
    if from_email is None:
        from_email = kw.pop("sender", None) or kw.pop("from", None)

    from_env = (from_email or os.environ.get("EMAIL_SENDER") or os.environ.get("EMAIL_FROM") or "").strip()
    if not from_env:
        raise MissingConfig("EMAIL_SENDER/EMAIL_FROM ausente(s) no ambiente do servidor")

    to_list = _norm_emails(to)
    if not to_list:
        raise MailerError("destinatário inválido")

    bcc_list = _norm_emails(bcc)
    to_lower = {e.lower() for e in to_list}
    bcc_list = [e for e in bcc_list if e.lower() not in to_lower]

    reply_to = reply_to or os.environ.get("EMAIL_REPLY_TO")
    provider = (os.environ.get("EMAIL_PROVIDER") or "sendgrid").strip().lower()
    fallback_provider = (os.environ.get("EMAIL_FALLBACK_PROVIDER") or "smtp").strip().lower()

    # Se o modo principal for SMTP, envia direto por SMTP (sem tentar SendGrid)
    if provider == "smtp":
        return _send_smtp(
            to_list=to_list,
            subject=subject,
            text=text,
            html=html,
            from_env=from_env,
            bcc_list=bcc_list,
            reply_to=reply_to,
        )

    if provider != "sendgrid":
        raise ProviderNotSupported(f"unsupported provider: {provider!r}")

    # 1) PRIMARY: SendGrid (com cooldown)
    api_key = os.environ.get("SENDGRID_API_KEY")
    if api_key and not _is_sendgrid_in_cooldown():
        try:
            ok = _send_sendgrid(
                api_key=api_key,
                to_list=to_list,
                subject=subject,
                text=text,
                html=html,
                from_env=from_env,
                bcc_list=bcc_list,
                reply_to=reply_to,
                disable_click_tracking=disable_click_tracking,
            )
            if ok:
                _clear_sendgrid_cooldown()
                return True
        except Exception:
            # qualquer falha em SendGrid → entra em cooldown e tenta fallback (se habilitado)
            _set_sendgrid_cooldown("sendgrid_failed")
    else:
        # Sem api_key OU em cooldown → pula direto pro fallback
        if not api_key:
            _set_sendgrid_cooldown("missing_api_key")

    # 2) FALLBACK: SMTP (catch-all) — não quebra o fluxo se SendGrid caiu (fatura/cartão/etc.)
    if _failover_enabled() and fallback_provider == "smtp":
        return _send_smtp(
            to_list=to_list,
            subject=subject,
            text=text,
            html=html,
            from_env=from_env,
            bcc_list=bcc_list,
            reply_to=reply_to,
        )

    # Se fallback estiver desabilitado, mantém comportamento “falha”
    raise MailerError("sendgrid_unavailable_and_failover_disabled")

# -----------------------
# Verificação de e-mail
# -----------------------
def _html_verify(verify_url: str, user_email: str) -> str:
    return f"""
<div style="font-family:system-ui,-apple-system,Segoe UI,Roboto;max-width:520px;margin:auto;padding:24px;border:1px solid #eee;border-radius:12px">
  <img src="https://www.meirobo.com.br/assets/icon-180.png" alt="MEI Robô" width="48" height="48" style="opacity:.95">
  <h2 style="margin:12px 0 8px">Só falta confirmar seu e-mail</h2>
  <p style="color:#444;margin:0 0 16px">Clique no botão abaixo para ativar sua conta:</p>
  <p style="margin:20px 0">
    <a href="{verify_url}" style="display:inline-block;background:#23d366;color:#0a0a0a;text-decoration:none;font-weight:700;padding:12px 18px;border-radius:10px">
      Confirmar meu e-mail
    </a>
  </p>
  <p style="font-size:12px;color:#666;margin-top:18px">
    Se o botão não funcionar, copie e cole este link no navegador:<br>
    <span style="word-break:break-all">{verify_url}</span>
  </p>
</div>
"""

def generate_firebase_verify_link(user_email: str, continue_url: str = "https://www.meirobo.com.br/verify-email.html") -> str:
    """
    Gera o link oficial do Firebase para verificação de e-mail.
    Requer firebase_admin inicializado pelo app.
    """
    try:
        from firebase_admin import auth
    except Exception as e:
        raise MissingConfig("firebase_admin não disponível para gerar link de verificação") from e

    settings = auth.ActionCodeSettings(
        url=continue_url,
        handle_code_in_app=False,
    )
    return auth.generate_email_verification_link(user_email, settings)

def send_verification_email(user_email: str, verify_url: str | None = None, *, continue_url: str = "https://www.meirobo.com.br/verify-email.html") -> bool:
    """
    Envia um e-mail de verificação (botão) via SendGrid usando as variáveis de ambiente existentes.
    - Se verify_url não for informado, gera via Firebase Admin.
    - Desliga click-tracking nesta mensagem para reduzir chance de SPAM.
    """
    if not verify_url:
        verify_url = generate_firebase_verify_link(user_email, continue_url=continue_url)

    html = _html_verify(verify_url, user_email)
    subj = "Confirme seu e-mail para começar no MEI Robô"

    return send_email(
        to=user_email,
        subject=subj,
        html=html,
        text=f"Confirme seu e-mail acessando: {verify_url}",
        reply_to=os.environ.get("EMAIL_REPLY_TO"),
        disable_click_tracking=True,
    )
