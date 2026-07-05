import hashlib
import re
from datetime import datetime, timezone

from .permission_policy import get_default_policy


def _clean_text(value):
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def stable_hash(value, size=16):
    raw = _clean_text(value).lower().encode("utf-8", errors="ignore")
    return hashlib.sha256(raw).hexdigest()[:size]


def build_dedupe_key(
    *,
    source_platform,
    project_link="",
    platform_project_id="",
    opportunity_title="",
    description="",
    raw_subject="",
    received_date="",
):
    source_platform = _clean_text(source_platform).lower() or "unknown"

    if _clean_text(platform_project_id):
        basis = f"{source_platform}|project_id|{platform_project_id}"
    elif _clean_text(project_link):
        basis = f"{source_platform}|link|{project_link}"
    else:
        basis = "|".join(
            [
                source_platform,
                _clean_text(raw_subject),
                _clean_text(opportunity_title),
                _clean_text(description),
                _clean_text(received_date),
            ]
        )

    return stable_hash(basis, size=24)


def build_opportunity_event(
    *,
    raw_text,
    raw_subject="",
    source_platform="workana",
    source_channel="fixture_txt",
    source_language="pt-BR",
    source_country="BR",
    source_currency="BRL",
    extracted=None,
    received_at=None,
):
    extracted = dict(extracted or {})
    received_at = received_at or datetime.now(timezone.utc).isoformat()

    dedupe_key = build_dedupe_key(
        source_platform=source_platform,
        project_link=extracted.get("project_link", ""),
        platform_project_id=extracted.get("platform_project_id", ""),
        opportunity_title=extracted.get("opportunity_title", ""),
        description=extracted.get("description", ""),
        raw_subject=raw_subject,
        received_date=received_at[:10],
    )

    event_id = stable_hash(f"{source_platform}|{source_channel}|{dedupe_key}|{received_at}", size=24)

    return {
        "event_id": event_id,
        "event_type": "marketplace_opportunity",
        "source_platform": source_platform,
        "source_channel": source_channel,
        "source_language": source_language,
        "source_country": source_country,
        "source_currency": source_currency,
        "received_at": received_at,
        "external_opportunity_id": extracted.get("platform_project_id", ""),
        "external_thread_id": extracted.get("platform_project_id", "") or dedupe_key,
        "external_contact_id": extracted.get("client_context", "") or source_platform,
        "state_key": f"ponte:{source_platform}:{source_channel}:{dedupe_key}",
        "dedupe_key": dedupe_key,
        "raw_subject": raw_subject,
        "raw_text": raw_text,
        "raw_html_available": False,
        "links": extracted.get("links", []),
        "extracted": extracted,
        "classification": {},
        "risk_flags": [],
        "permission_policy": get_default_policy(),
        "processing_status": "parsed_offline",
    }
