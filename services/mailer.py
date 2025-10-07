# services/mailer.py
# Mailer mínimo para SendGrid via HTTP API (sem dependências externas)

import os, json
from urllib import request as ulreq
from urllib.error import HTTPError, URLError
from typing import Iterable, Union

class MailerError(RuntimeError): ...
class ProviderNotSupported(MailerError): ...
class MissingConfig(MailerError): ...

def _norm_emails(x: Union[str, Iterable[str]] | None) -> list[str]:
    if not x:
        return []
    if isinstance(x, str):
        # aceita "a@b,c@d ; e@f"
        parts = [p.strip() for p in x.replace(";", ",").split(",")]
        return [p for p in parts if p]
    return [str(p).strip() for p in x if str(p).strip()]

def send_email(
    *,
    to: Union[str, Iterable[str]],
    subject: str,
    text: str,
    from_email: str | None = None,
    html: str | None = None,
    bcc: Union[str, Iterable[str]] | None = None,
    reply_to: str | None = None,
):
    """
    Envia e-mail via SendGrid HTTP API.
    Mantém compatibilidade com a versão anterior e aceita bcc/reply_to.
    """
    provider = (os.environ.get("EMAIL_PROVIDER") or "").strip().lower()
    if provider != "sendgrid":
        raise ProviderNotSupported(f"unsupported provider: {provider!r}")

    api_key = os.environ.get("SENDGRID_API_KEY")
    if not api_key:
        raise MissingConfig("SENDGRID_API_KEY ausente no ambiente do servidor")

    # prioriza from_email explícito; senão usa EMAIL_SENDER, depois EMAIL_FROM
    from_email = (from_email or os.environ.get("EMAIL_SENDER") or os.environ.get("EMAIL_FROM") or "").strip()
    if not from_email:
        raise MissingConfig("EMAIL_SENDER/EMAIL_FROM ausente(s) no ambiente do servidor")

    to_list = _norm_emails(to)
    if not to_list:
        raise MailerError("destinatário inválido")

    bcc_list = _norm_emails(bcc)

    # monta personalização (to + opcional bcc)
    personalization = {"to": [{"email": e} for e in to_list]}
    if bcc_list:
        personalization["bcc"] = [{"email": e} for e in bcc_list]

    content = [{"type": "text/plain", "value": text or ""}]
    if html:
        content.append({"type": "text/html", "value": html})

    payload: dict = {
        "personalizations": [personalization],
        "from": {"email": from_email},
        "subject": subject,
        "content": content,
    }
    if reply_to:
        payload["reply_to"] = {"email": reply_to}

    data = json.dumps(payload).encode("utf-8")
    req = ulreq.Request(
        "https://api.sendgrid.com/v3/mail/send",
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        # timeout explícito para robustez
        with ulreq.urlopen(req, timeout=20) as resp:
            status = resp.getcode()
    except HTTPError as e:
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        raise MailerError(f"sendgrid_http_error_{e.code}: {body[:500]}") from e
    except URLError as e:
        raise MailerError(f"sendgrid_url_error: {e.reason}") from e
    except Exception as e:
        raise MailerError(f"sendgrid_request_failed: {e}") from e

    # sucesso típico: 202 Accepted (às vezes 200)
    if status not in (200, 202):
        raise MailerError(f"sendgrid_status_{status}")

    return True
