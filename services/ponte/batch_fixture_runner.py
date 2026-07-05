import argparse
from pathlib import Path

from services.ponte.audit_log import build_audit_record
from services.ponte.marketplace_parser import parse_marketplace_text
from services.ponte.opportunity_classifier import classify_event
from services.ponte.proposal_drafter import draft_proposal


HUMAN_REVIEW_STATUS = "aguardando_revisao_humana"


def infer_platform_from_fixture(path):
    name = Path(path).name.lower()
    if "workana" in name:
        return "workana"
    if "international" in name:
        return "international_platform_01"
    return "unknown_marketplace"


def build_review_item(fixture_path, source_platform=None):
    fixture_path = Path(fixture_path)
    source_platform = source_platform or infer_platform_from_fixture(fixture_path)
    raw = fixture_path.read_text(encoding="utf-8")

    event = parse_marketplace_text(
        raw,
        source_platform=source_platform,
        source_channel="fixture_txt",
    )
    event = classify_event(event)
    draft = draft_proposal(event)
    audit = build_audit_record(event, draft=draft)

    extracted = event.get("extracted") or {}
    classification = event.get("classification") or {}
    policy = event.get("permission_policy") or {}

    return {
        "fixture": str(fixture_path),
        "source_platform": event.get("source_platform"),
        "source_language": event.get("source_language"),
        "source_currency": event.get("source_currency"),
        "title": extracted.get("opportunity_title") or "(nao informado)",
        "fit_score": classification.get("fit_score"),
        "fit_level": classification.get("fit_level"),
        "recommended_action": classification.get("recommended_action"),
        "review_status": HUMAN_REVIEW_STATUS,
        "dedupe_key": event.get("dedupe_key"),
        "state_key": event.get("state_key"),
        "risk_flags": event.get("risk_flags") or [],
        "dry_run": bool(policy.get("dry_run", True)),
        "requires_human_approval": bool(policy.get("requires_human_approval", True)),
        "can_submit_proposal": bool(policy.get("can_submit_proposal", False)),
        "can_send_message": bool(policy.get("can_send_message", False)),
        "draft_language": draft.get("draft_language"),
        "draft_text": draft.get("draft_text"),
        "audit": audit,
    }


def build_review_queue(fixtures_dir):
    fixtures_dir = Path(fixtures_dir)
    items = []
    for fixture in sorted(fixtures_dir.rglob("*.txt")):
        items.append(build_review_item(fixture))
    return items


def format_review_queue(items):
    if not items:
        return "Nenhuma fixture encontrada para revisao.\n"

    lines = [
        "PROJETO PONTE / MEI ROBO WEB",
        "FILA LOCAL DE REVISAO HUMANA",
        "MODO: DRY-RUN / READ-ONLY",
        "",
        "Resumo:",
        f"Total de oportunidades: {len(items)}",
        "",
    ]

    for index, item in enumerate(items, start=1):
        risk = ", ".join(item["risk_flags"]) if item["risk_flags"] else "nenhum"
        lines.extend(
            [
                f"{index}. {item['source_platform']} | {item['source_language']} | {item['source_currency']}",
                f"   Titulo: {item['title']}",
                f"   Score: {item['fit_score']} | Nivel: {item['fit_level']} | Acao: {item['recommended_action']}",
                f"   Status: {item['review_status']}",
                f"   Riscos: {risk}",
                f"   Dedupe: {item['dedupe_key']}",
                f"   dry_run: {item['dry_run']} | human_approval: {item['requires_human_approval']}",
                f"   can_submit_proposal: {item['can_submit_proposal']} | can_send_message: {item['can_send_message']}",
                "",
            ]
        )

    lines.extend(
        [
            "RESULTADO",
            "Esta fila e apenas local, offline e read-only.",
            "Nenhuma proposta foi enviada.",
            "Nenhum chat foi aberto.",
            "Nenhum link foi clicado.",
            "Nenhum Gmail real foi acessado.",
            "Nenhuma plataforma real foi acessada.",
        ]
    )

    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description="Build Ponte local human review queue from fixtures.")
    parser.add_argument("fixtures_dir", help="Directory containing .txt fixtures")
    args = parser.parse_args()

    items = build_review_queue(args.fixtures_dir)
    print(format_review_queue(items))


if __name__ == "__main__":
    main()
