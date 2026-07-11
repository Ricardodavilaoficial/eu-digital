import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, List


WHATSAPP_WEB_PLATFORM = "whatsapp_web"
WHATSAPP_WEB_LOCAL_SIMULATION_CHANNEL = "local_simulation"
WHATSAPP_WEB_EVENT_TYPE = "whatsapp_web_message_event"
DEFAULT_MESSAGE_TEXT_LIMIT = 4000
DEFAULT_CONTEXT_LIMIT = 5


WHATSAPP_WEB_LOCAL_PERMISSION_POLICY = {
    "can_read_whatsapp_web_real": False,
    "can_open_browser": False,
    "can_click": False,
    "can_type": False,
    "can_send_message": False,
    "can_download_media": False,
    "can_open_link": False,
    "can_modify_contact": False,
    "can_delete_message": False,
    "can_write_firestore": False,
    "can_deploy": False,
    "can_process_local_simulation": True,
    "can_generate_suggested_reply": True,
    "can_build_review_queue": True,
    "requires_human_approval": True,
    "dry_run": True,
}


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def stable_hash(value: Any, length: int = 24) -> str:
    raw = _text(value)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return digest[:length]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def limit_text(value: Any, max_chars: int = DEFAULT_MESSAGE_TEXT_LIMIT) -> str:
    text = _text(value)
    if max_chars < 0:
        max_chars = 0
    return text[:max_chars]


def normalize_context(value: Any, max_items: int = DEFAULT_CONTEXT_LIMIT) -> List[str]:
    if not value:
        return []

    if isinstance(value, str):
        items = [value]
    else:
        try:
            items = list(value)
        except TypeError:
            items = [value]

    normalized = []
    for item in items:
        text = _text(item)
        if text:
            normalized.append(text)

    if max_items < 0:
        max_items = 0

    return normalized[-max_items:]


def normalize_whatsapp_web_message(
    message: Dict[str, Any],
    *,
    max_text_chars: int = DEFAULT_MESSAGE_TEXT_LIMIT,
    max_context_items: int = DEFAULT_CONTEXT_LIMIT,
) -> Dict[str, Any]:
    chat_title = _text(message.get("chat_title")) or "(chat_sem_titulo)"
    chat_type = _text(message.get("chat_type")) or "direct"
    raw_chat_identifier = _text(message.get("chat_identifier")) or chat_title

    chat_identifier_hash = stable_hash(raw_chat_identifier)
    message_text = limit_text(message.get("message_text"), max_chars=max_text_chars)
    message_direction = _text(message.get("message_direction")) or "inbound"
    message_timestamp = _text(message.get("message_timestamp"))
    message_index = _text(message.get("message_index"))

    return {
        "client_authorization_ref": _text(message.get("client_authorization_ref")),
        "chat_title": chat_title,
        "chat_type": chat_type,
        "chat_identifier_hash": chat_identifier_hash,
        "message_text": message_text,
        "message_direction": message_direction,
        "message_timestamp": message_timestamp,
        "message_index": message_index,
        "sender_label": _text(message.get("sender_label")),
        "visible_phone_masked": _text(message.get("visible_phone_masked")),
        "last_messages_context": normalize_context(
            message.get("last_messages_context"),
            max_items=max_context_items,
        ),
        "attachment_present": bool(message.get("attachment_present", False)),
        "audio_present": bool(message.get("audio_present", False)),
        "unread_count": int(message.get("unread_count") or 0),
        "browser_session_id": _text(message.get("browser_session_id")),
        "operator_note": _text(message.get("operator_note")),
    }


def build_conversation_id(normalized_message: Dict[str, Any]) -> str:
    return "ww:" + _text(normalized_message.get("chat_identifier_hash"))


def build_dedupe_key(normalized_message: Dict[str, Any]) -> str:
    base = "|".join(
        [
            WHATSAPP_WEB_PLATFORM,
            WHATSAPP_WEB_LOCAL_SIMULATION_CHANNEL,
            _text(normalized_message.get("chat_identifier_hash")),
            _text(normalized_message.get("message_timestamp")),
            _text(normalized_message.get("message_index")),
            _text(normalized_message.get("message_direction")),
            _text(normalized_message.get("message_text")),
        ]
    )
    return stable_hash(base)


def should_route_to_base_vendedor(event: Dict[str, Any]) -> bool:
    if _text(event.get("message_direction")).lower() != "inbound":
        return False
    if not _text(event.get("message_text")):
        return False
    return True


def build_whatsapp_web_message_event(
    message: Dict[str, Any],
    *,
    pilot_mode: str = "LOCAL_SIMULATION",
) -> Dict[str, Any]:
    normalized = normalize_whatsapp_web_message(message)
    conversation_id = build_conversation_id(normalized)
    dedupe_key = build_dedupe_key(normalized)

    event = {
        "event_type": WHATSAPP_WEB_EVENT_TYPE,
        "source_platform": WHATSAPP_WEB_PLATFORM,
        "source_channel": WHATSAPP_WEB_LOCAL_SIMULATION_CHANNEL,
        "pilot_mode": pilot_mode,
        "client_authorization_ref": normalized["client_authorization_ref"],
        "chat_title": normalized["chat_title"],
        "chat_type": normalized["chat_type"],
        "chat_identifier_hash": normalized["chat_identifier_hash"],
        "message_text": normalized["message_text"],
        "message_direction": normalized["message_direction"],
        "message_timestamp": normalized["message_timestamp"],
        "message_index": normalized["message_index"],
        "conversation_id": conversation_id,
        "dedupe_key": dedupe_key,
        "received_at": utc_now_iso(),
        "sender_label": normalized["sender_label"],
        "visible_phone_masked": normalized["visible_phone_masked"],
        "last_messages_context": normalized["last_messages_context"],
        "attachment_present": normalized["attachment_present"],
        "audio_present": normalized["audio_present"],
        "unread_count": normalized["unread_count"],
        "browser_session_id": normalized["browser_session_id"],
        "operator_note": normalized["operator_note"],
        "requires_human_approval": True,
        "dry_run": True,
        "can_send_message": False,
        "permission_policy": dict(WHATSAPP_WEB_LOCAL_PERMISSION_POLICY),
    }

    event["route_to_base_vendedor"] = should_route_to_base_vendedor(event)
    return event


def build_base_vendedor_input(event: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "source": "ponte_whatsapp_web",
        "conversation_id": _text(event.get("conversation_id")),
        "message_text": _text(event.get("message_text")),
        "last_messages_context": event.get("last_messages_context") or [],
        "chat_type": _text(event.get("chat_type")),
        "constraints": {
            "dry_run": True,
            "requires_human_approval": True,
            "can_send_message": False,
            "pilot_mode": _text(event.get("pilot_mode")),
        },
    }
