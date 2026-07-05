import argparse
from pathlib import Path
from textwrap import dedent

from services.ponte.audit_log import build_audit_record
from services.ponte.marketplace_parser import parse_marketplace_text
from services.ponte.opportunity_classifier import classify_event
from services.ponte.proposal_drafter import draft_proposal


def _read_fixture(path):
    return Path(path).read_text(encoding="utf-8")


def _format_list(values):
    if not values:
        return "- nenhum"
    return "\n".join(f"- {item}" for item in values)


def build_report(fixture_path, source_platform):
    raw = _read_fixture(fixture_path)

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

    report = f"""
PROJETO PONTE / MEI ROBO WEB
RELATORIO OFFLINE DE OPORTUNIDADE
MODO: DRY-RUN / READ-ONLY

Arquivo:
{fixture_path}

Plataforma:
{event.get("source_platform")}

Canal:
{event.get("source_channel")}

Idioma:
{event.get("source_language")}

Pais:
{event.get("source_country")}

Moeda:
{event.get("source_currency")}

Event ID:
{event.get("event_id")}

Dedupe key:
{event.get("dedupe_key")}

State key:
{event.get("state_key")}

TITULO
{extracted.get("opportunity_title") or "(nao informado)"}

CATEGORIA
{extracted.get("category") or "(nao informada)"}

ORCAMENTO
{extracted.get("budget_raw") or "(nao informado)"}

PRAZO
{extracted.get("deadline_raw") or "(nao informado)"}

LINK
{extracted.get("project_link") or "(sem link)"}

DESCRICAO
{extracted.get("description") or "(nao informada)"}

HABILIDADES
{extracted.get("required_skills") or "(nao informadas)"}

PONTOS OBSCUROS
{_format_list(extracted.get("unclear_points") or [])}

CLASSIFICACAO
Score: {classification.get("fit_score")}
Nivel: {classification.get("fit_level")}
Acao recomendada: {classification.get("recommended_action")}
Potencial comercial: {classification.get("commercial_potential")}
Risco de entrega: {classification.get("delivery_risk")}
Risco reputacional: {classification.get("reputation_risk")}
Motivo: {classification.get("fit_reason")}

RISCOS
{_format_list(event.get("risk_flags") or [])}

POLITICA
dry_run: {policy.get("dry_run")}
requires_human_approval: {policy.get("requires_human_approval")}
can_submit_proposal: {policy.get("can_submit_proposal")}
can_send_message: {policy.get("can_send_message")}
can_read_gmail_real: {policy.get("can_read_gmail_real")}
can_open_platform_url: {policy.get("can_open_platform_url")}

RASCUNHO DE PROPOSTA
{draft.get("draft_text")}

AUDITORIA
status: {audit.get("status")}
draft_created: {audit.get("draft_created")}
blocked_actions:
{_format_list(audit.get("blocked_actions") or [])}

RESULTADO
Este relatorio e apenas local, offline e read-only.
Nenhuma proposta foi enviada.
Nenhum chat foi aberto.
Nenhum link foi clicado.
Nenhum Gmail real foi acessado.
Nenhuma plataforma real foi acessada.
Nenhum dado foi gravado em Firestore, Storage, agenda ou Cloud Run.
"""
    return dedent(report).strip() + "\n"


def main():
    parser = argparse.ArgumentParser(description="Run Ponte offline marketplace fixture report.")
    parser.add_argument("fixture", help="Path to fixture .txt file")
    parser.add_argument("--platform", default="workana", help="Source platform name")
    parser.add_argument("--out", default="", help="Optional output .txt path")
    args = parser.parse_args()

    report = build_report(args.fixture, args.platform)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report, encoding="utf-8")
        print(f"Relatorio salvo em: {out_path}")
    else:
        print(report)


if __name__ == "__main__":
    main()
