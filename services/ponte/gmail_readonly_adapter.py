import re
from typing import Any, Dict, List, Optional

from services.ponte.marketplace_parser import parse_marketplace_text


GMAIL_READONLY_CHANNEL = "gmail_readonly"
DEFAULT_BODY_TEXT_LIMIT = 4000


GMAIL_READONLY_PERMISSION_OVERRIDES = {
    "can_read_gmail_real": True,
    "can_search_gmail": True,
    "can_read_email_metadata": True,
    "can_read_email_text": True,
    "can_send_email": False,
    "can_create_gmail_draft": False,
    "can_forward_email": False,
    "can_archive_email": False,
    "can_delete_email": False,
    "can_mark_read": False,
    "can_apply_label": False,
    "can_download_attachment": False,
    "can_open_link": False,
    "can_open_workana": False,
    "can_login_platform": False,
    "can_click": False,
    "can_type": False,
    "can_submit_proposal": False,
    "can_send_message": False,
    "can_write_firestore": False,
    "can_deploy": False,
    "requires_human_approval": True,
    "dry_run": True,
}


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def limit_body_text(body_text: Any, max_chars: int = DEFAULT_BODY_TEXT_LIMIT) -> str:
    text = _text(body_text)
    if max_chars < 0:
        max_chars = 0
    return text[:max_chars]


def extract_link_candidates_as_text_only(*parts: Any) -> List[str]:
    combined = "\n".join(_text(part) for part in parts if _text(part))
    links = re.findall(r"https?://[^\s<>\")]+", combined)
    return list(dict.fromkeys(links))


def detect_platform_from_gmail_email(email: Dict[str, Any]) -> str:
    sender = _text(email.get("sender")).lower()
    subject = _text(email.get("subject")).lower()
    snippet = _text(email.get("snippet")).lower()
    body = _text(email.get("body_text")).lower()

    combined = "\n".join([sender, subject, snippet, body])

    if "workana" in combined:
        return "workana"

    if "upwork" in combined or "freelancer" in combined:
        return "international_platform_01"

    return "unknown_marketplace"


def normalize_gmail_email_dict(
    email: Dict[str, Any],
    *,
    max_body_chars: int = DEFAULT_BODY_TEXT_LIMIT,
) -> Dict[str, Any]:
    subject = _text(email.get("subject"))
    sender = _text(email.get("sender"))
    snippet = _text(email.get("snippet"))
    body_text_limited = limit_body_text(email.get("body_text"), max_chars=max_body_chars)

    return {
        "gmail_message_id": _text(email.get("message_id")),
        "gmail_thread_id": _text(email.get("thread_id")),
        "sender": sender,
        "subject": subject,
        "date": _text(email.get("date")),
        "snippet": snippet,
        "body_text_limited": body_text_limited,
        "has_attachment": bool(email.get("has_attachment", False)),
        "link_candidates_as_text_only": extract_link_candidates_as_text_only(
            subject,
            snippet,
            body_text_limited,
        ),
    }


def build_raw_text_for_ponte_from_gmail(normalized_email: Dict[str, Any]) -> str:
    subject = _text(normalized_email.get("subject"))
    sender = _text(normalized_email.get("sender"))
    snippet = _text(normalized_email.get("snippet"))
    body = _text(normalized_email.get("body_text_limited"))

    body_lower = body.lower()
    has_explicit_title = "titulo:" in body_lower or "title:" in body_lower

    lines = [
        f"Email_Message_ID: {_text(normalized_email.get('gmail_message_id'))}",
        f"Email_Thread_ID: {_text(normalized_email.get('gmail_thread_id'))}",
        f"From: {sender}",
        f"Date: {_text(normalized_email.get('date'))}",
    ]

    if subject and not has_explicit_title:
        lines.append(f"Titulo: {subject}")
    elif subject:
        lines.append(f"Subject: {subject}")

    if snippet:
        lines.append(f"Resumo: {snippet}")

    if body:
        lines.append(body)

    links = normalized_email.get("link_candidates_as_text_only") or []
    for link in links:
        lines.append(f"Link: {link}")

    return "\n".join(line for line in lines if _text(line))


def gmail_email_to_ponte_event(
    email: Dict[str, Any],
    *,
    source_platform: Optional[str] = None,
    max_body_chars: int = DEFAULT_BODY_TEXT_LIMIT,
) -> Dict[str, Any]:
    normalized = normalize_gmail_email_dict(email, max_body_chars=max_body_chars)
    platform = source_platform or detect_platform_from_gmail_email(email)
    raw_text = build_raw_text_for_ponte_from_gmail(normalized)

    event = parse_marketplace_text(
        raw_text,
        source_platform=platform,
        source_channel=GMAIL_READONLY_CHANNEL,
    )

    event["source_channel"] = GMAIL_READONLY_CHANNEL
    event["external_thread_id"] = normalized["gmail_thread_id"]
    event["external_contact_id"] = normalized["sender"]
    event["gmail_readonly"] = normalized

    policy = dict(event.get("permission_policy") or {})
    policy.update(GMAIL_READONLY_PERMISSION_OVERRIDES)
    event["permission_policy"] = policy

    return event
