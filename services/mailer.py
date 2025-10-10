# services/mailer.py
# Mailer mínimo para SendGrid via HTTP API (sem dependências externas)

import os, json
from urllib import request as ulreq
from urllib.error import HTTPError, URLError
from typing import Iterable, Union

class MailerError(RuntimeError): ...
class ProviderNotSupported(MailerError): ...
class MissingConfig(MailerError): ...

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

    provider = (os.environ.get("EMAIL_PROVIDER") or "").strip().lower()
    if provider != "sendgrid":
        raise ProviderNotSupported(f"unsupported provider: {provider!r}")

    api_key = os.environ.get("SENDGRID_API_KEY")
    if not api_key:
        raise MissingConfig("SENDGRID_API_KEY ausente no ambiente do servidor")

    from_env = (from_email or os.environ.get("EMAIL_SENDER") or os.environ.get("EMAIL_FROM") or "").strip()
    if not from_env:
        raise MissingConfig("EMAIL_SENDER/EMAIL_FROM ausente(s) no ambiente do servidor")

    from_name, from_addr = _parse_from(from_env)
    if "@" not in from_addr:
        fallback = (os.environ.get("EMAIL_SENDER") or "").strip()
        fn2_name, fn2_addr = _parse_from(fallback)
        if "@" in fn2_addr:
            from_name, from_addr = fn2_name, fn2_addr
        else:
            raise MissingConfig("Remetente inválido; verifique EMAIL_SENDER/EMAIL_FROM")

    to_list = _norm_emails(to)
    if not to_list:
        raise MailerError("destinatário inválido")

    bcc_list = _norm_emails(bcc)
    to_lower = {e.lower() for e in to_list}
    bcc_list = [e for e in bcc_list if e.lower() not in to_lower]

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

    reply_to = reply_to or os.environ.get("EMAIL_REPLY_TO")
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
