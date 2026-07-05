import re

from .opportunity_event import build_opportunity_event


LABELS = {
    "opportunity_title": ["titulo", "title", "projeto", "project"],
    "category": ["categoria", "category"],
    "budget_raw": ["orcamento", "budget", "valor"],
    "deadline_raw": ["prazo", "deadline"],
    "description": ["descricao", "description", "detalhes", "details"],
    "required_skills": ["habilidades", "skills", "tecnologias"],
    "client_context": ["cliente", "client"],
}


def _line_value(raw_text, labels):
    lines = raw_text.splitlines()
    for line in lines:
        stripped = line.strip()
        for label in labels:
            pattern = re.compile(rf"^{re.escape(label)}\s*:\s*(.+)$", re.IGNORECASE)
            match = pattern.search(stripped)
            if match:
                return match.group(1).strip()
    return ""


def _extract_links(raw_text):
    return re.findall(r"https?://[^\s<>\"]+", raw_text or "")


def _detect_language(raw_text):
    text = (raw_text or "").lower()
    english_markers = ["budget:", "deadline:", "description:", "skills:", "project:"]
    if any(marker in text for marker in english_markers):
        return "en"
    return "pt-BR"


def _detect_currency(raw_text):
    text = raw_text or ""
    if "US$" in text or "USD" in text.upper():
        return "USD"
    if "R$" in text or "BRL" in text.upper():
        return "BRL"
    return ""


def _detect_country(language, currency):
    if currency == "BRL" or language == "pt-BR":
        return "BR"
    if currency == "USD" or language == "en":
        return "US"
    return ""


def parse_marketplace_text(
    raw_text,
    *,
    raw_subject="",
    source_platform="workana",
    source_channel="fixture_txt",
):
    raw_text = raw_text or ""
    links = _extract_links(raw_text)
    language = _detect_language(raw_text)
    currency = _detect_currency(raw_text) or ("BRL" if language == "pt-BR" else "USD")
    country = _detect_country(language, currency)

    extracted = {}
    for field, labels in LABELS.items():
        extracted[field] = _line_value(raw_text, labels)

    extracted["links"] = links
    extracted["project_link"] = links[0] if links else ""
    extracted["platform_project_id"] = ""
    extracted["language"] = language
    extracted["country"] = country
    extracted["currency"] = currency
    extracted["subcategory"] = ""
    extracted["budget_min"] = None
    extracted["budget_max"] = None
    extracted["deadline_days"] = None
    extracted["urgency_level"] = ""
    extracted["complexity_level"] = ""
    extracted["estimated_effort"] = ""
    extracted["unclear_points"] = []

    if not extracted.get("opportunity_title"):
        extracted["unclear_points"].append("opportunity_title")
    if not extracted.get("description"):
        extracted["unclear_points"].append("description")
    if not extracted.get("budget_raw"):
        extracted["unclear_points"].append("budget_raw")
    if not extracted.get("deadline_raw"):
        extracted["unclear_points"].append("deadline_raw")

    return build_opportunity_event(
        raw_text=raw_text,
        raw_subject=raw_subject,
        source_platform=source_platform,
        source_channel=source_channel,
        source_language=language,
        source_country=country,
        source_currency=currency,
        extracted=extracted,
    )
