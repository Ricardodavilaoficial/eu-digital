# services/mailer.py
# Mailer mínimo para SendGrid via HTTP API (sem dependências externas)

import os, json
from urllib import request as ulreq

class MailerError(RuntimeError): ...
class ProviderNotSupported(MailerError): ...
class MissingConfig(MailerError): ...

def send_email(*, to: str, subject: str, text: str, from_email: str | None = None, html: str | None = None):
    provider = (os.environ.get("EMAIL_PROVIDER") or "").strip().lower()
    if provider != "sendgrid":
        raise ProviderNotSupported(f"unsupported provider: {provider!r}")

    api_key = os.environ.get("SENDGRID_API_KEY")
    if not api_key:
        raise MissingConfig("SENDGRID_API_KEY ausente no ambiente do servidor")

    from_email = (from_email or os.environ.get("EMAIL_FROM") or "").strip()
    if not from_email:
        raise MissingConfig("EMAIL_FROM ausente no ambiente do servidor")

    if not to or "@" not in to:
        raise MailerError("destinatário inválido")

    payload = {
        "personalizations": [{"to": [{"email": to}]}],
        "from": {"email": from_email},
        "subject": subject,
        "content": [{"type": "text/plain", "value": text}],
    }
    if html:
        payload["content"].append({"type": "text/html", "value": html})

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
        with ulreq.urlopen(req) as resp:
            status = resp.getcode()
    except Exception as e:
        raise MailerError(f"sendgrid_request_failed: {e}") from e

    # SendGrid responde 202 Accepted em sucesso
    if status not in (200, 202):
        raise MailerError(f"sendgrid_status_{status}")

    return True
