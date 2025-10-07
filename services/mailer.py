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
    to=None,
    subject: str = "",
    text: str | None = None,
    from_email: str | None = None,
    html: str | None = None,
    bcc=None,
    reply_to: str | None = None,
    disable_click_tracking: bool = False,  # << permite desligar tracking por chamada (ex.: digest)
    **kw,  # <- engole params inesperados sem quebrar
):
    """
    Envia e-mail via SendGrid HTTP API.
    Aceita aliases: body_text/body_html e ignora kwargs extras.
    """

    # ---- Normalização de aliases (evita TypeError na rota) ----
    # Permite body_text/body_html (rota pode usar esses nomes)
    if text is None:
        text = kw.pop("body_text", None)
    if html is None:
        html = kw.pop("body_html", None)
    # Permite 'sender' ou 'from' como alias de from_email
    if from_email is None:
        from_email = kw.pop("sender", None) or kw.pop("from", None)

    provider = (os.environ.get("EMAIL_PROVIDER") or "").strip().lower()
    if provider != "sendgrid":
        raise ProviderNotSupported(f"unsupported provider: {provider!r}")

    api_key = os.environ.get("SENDGRID_API_KEY")
    if not api_key:
        raise MissingConfig("SENDGRID_API_KEY ausente no ambiente do servidor")

    # prioriza from_email explícito; senão EMAIL_SENDER, depois EMAIL_FROM
    from_env = (from_email or os.environ.get("EMAIL_SENDER") or os.environ.get("EMAIL_FROM") or "").strip()
    if not from_env:
        raise MissingConfig("EMAIL_SENDER/EMAIL_FROM ausente(s) no ambiente do servidor")

    # Suporte a "Nome <email@dominio>" no EMAIL_FROM
    from_name, from_addr = None, from_env
    if "<" in from_env and ">" in from_env:
        try:
            name_part = from_env.split("<", 1)[0].strip().strip('"').strip()
            addr_part = from_env.split("<", 1)[1].split(">", 1)[0].strip()
            if "@" in addr_part:
                from_name, from_addr = (name_part or None), addr_part
        except Exception:
            pass
    if "@" not in from_addr:
        # se ainda ficou inválido, cai no EMAIL_SENDER (que você já tem)
        fallback = (os.environ.get("EMAIL_SENDER") or "").strip()
        if "@" in fallback:
            from_name, from_addr = None, fallback
        else:
            raise MissingConfig("Remetente inválido; verifique EMAIL_SENDER/EMAIL_FROM")

    to_list = _norm_emails(to)
    if not to_list:
        raise MailerError("destinatário inválido")

    bcc_list = _norm_emails(bcc)

    # --- Blindagem: remove duplicados (to ∩ bcc) para evitar erro 400 do SendGrid
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
    }
    if from_name:
        payload["from"]["name"] = from_name
    if reply_to:
        payload["reply_to"] = {"email": reply_to}

    # ---- Click-tracking OFF (por chamada OU via ENV global) ----
    # - Por chamada: disable_click_tracking=True (ideal p/ digest)
    # - Global temporário: DISABLE_CLICK_TRACKING=1
    if disable_click_tracking or (os.getenv("DISABLE_CLICK_TRACKING", "0") == "1"):
        payload["tracking_settings"] = {
            "click_tracking": {"enable": False, "enable_text": False}
        }

    # ---- Envio via SendGrid ----
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

    # Sucesso padrão do SendGrid é 202 (Accepted)
    if status not in (200, 202):
        raise MailerError(f"sendgrid_unexpected_status_{status}")

    return True
