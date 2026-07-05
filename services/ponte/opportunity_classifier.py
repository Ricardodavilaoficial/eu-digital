import re
import unicodedata


POSITIVE_TERMS = [
    # Portuguese / MEI Robo context
    "mei robo",
    "whatsapp",
    "chatbot",
    "atendimento",
    "automacao",
    "automacao de atendimento",
    "ia",
    "inteligencia artificial",
    "crm",
    "gmail",
    "python",
    "web",
    "navegador",
    "playwright",
    "integracao",
    "lead",
    "vendas",

    # English / international marketplace context
    "ai",
    "assistant",
    "customer support",
    "customer service",
    "browser automation",
    "web automation",
    "automation",
    "draft replies",
    "human approval",
    "approval",
    "crm",
    "python",
    "workflow",
    "workflows",
    "classify customer requests",
]

RISK_TERMS = [
    "urgente",
    "hoje",
    "barato",
    "sem pagar",
    "copiar",
    "scraping agressivo",
    "senha",
    "credenciais",
    "dados sensiveis",
]


def _normalize(value):
    value = value or ""
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", value.lower()).strip()


def classify_event(event):
    event = dict(event)
    extracted = dict(event.get("extracted") or {})
    joined = " ".join(
        [
            extracted.get("opportunity_title", ""),
            extracted.get("category", ""),
            extracted.get("description", ""),
            extracted.get("required_skills", ""),
        ]
    )
    text = _normalize(joined)

    score = 35
    positive_hits = []
    for term in POSITIVE_TERMS:
        if term in text and term not in positive_hits:
            positive_hits.append(term)

    risk_hits = []
    for term in RISK_TERMS:
        if term in text and term not in risk_hits:
            risk_hits.append(term)

    score += min(45, len(positive_hits) * 8)

    unclear_points = extracted.get("unclear_points") or []
    score -= min(25, len(unclear_points) * 5)
    score -= min(30, len(risk_hits) * 10)

    score = max(0, min(100, score))

    # Safety guard: opportunities with explicit risk terms must remain under
    # manual review, even when they also contain attractive technical terms.
    if risk_hits:
        score = min(score, 54)

    if score >= 75:
        fit_level = "alto"
        recommended_action = "preparar_proposta"
    elif score >= 55:
        fit_level = "medio"
        recommended_action = "revisar_manualmente"
    elif score >= 35:
        fit_level = "baixo"
        recommended_action = "coletar_mais_contexto"
    else:
        fit_level = "rejeitar"
        recommended_action = "ignorar"

    risk_flags = []
    if unclear_points:
        risk_flags.append("dados_incompletos")
    if risk_hits:
        risk_flags.append("termos_de_risco")
    if not extracted.get("project_link"):
        risk_flags.append("sem_link")

    classification = {
        "fit_score": score,
        "fit_level": fit_level,
        "fit_reason": "Termos aderentes: " + (", ".join(positive_hits) if positive_hits else "nenhum forte detectado"),
        "opportunity_type": "marketplace_capture",
        "commercial_potential": "medio" if score >= 55 else "baixo",
        "delivery_risk": "medio" if unclear_points else "baixo",
        "reputation_risk": "medio" if risk_hits else "baixo",
        "recommended_action": recommended_action,
    }

    event["classification"] = classification
    event["risk_flags"] = risk_flags
    event["processing_status"] = "classified_offline"
    return event
