import unittest

from services.ponte.gmail_readonly_adapter import (
    GMAIL_READONLY_CHANNEL,
    build_raw_text_for_ponte_from_gmail,
    detect_platform_from_gmail_email,
    gmail_email_to_ponte_event,
    normalize_gmail_email_dict,
)
from services.ponte.opportunity_classifier import classify_event
from services.ponte.proposal_drafter import draft_proposal


WORKANA_EMAIL = {
    "message_id": "gmail-msg-001",
    "thread_id": "gmail-thread-001",
    "sender": "Workana <notificacoes@workana.example>",
    "subject": "Nova oportunidade Workana",
    "date": "2026-07-05",
    "snippet": "Cliente busca automacao com IA para WhatsApp e CRM.",
    "body_text": """
Titulo: Criar automacao para atendimento via WhatsApp
Categoria: Programacao e tecnologia
Orcamento: R$ 1500 - R$ 3000
Prazo: 30 dias
Descricao: Preciso de um sistema em Python para responder clientes, organizar leads, automatizar atendimento comercial via WhatsApp com IA, CRM e controle humano.
Habilidades: Python, WhatsApp, IA, automacao, CRM, web
Cliente: Empresa local
Link: https://workana.example/project/002
""",
    "has_attachment": True,
}


class PonteGmailReadonlyAdapterTests(unittest.TestCase):
    def test_detect_platform_from_gmail_email(self):
        self.assertEqual(detect_platform_from_gmail_email(WORKANA_EMAIL), "workana")
        self.assertEqual(
            detect_platform_from_gmail_email(
                {
                    "sender": "alerts@example.com",
                    "subject": "New Upwork project",
                    "body_text": "AI assistant project",
                }
            ),
            "international_platform_01",
        )
        self.assertEqual(detect_platform_from_gmail_email({}), "unknown_marketplace")

    def test_normalize_email_limits_body_and_keeps_links_as_text_only(self):
        email = dict(WORKANA_EMAIL)
        email["body_text"] = "Descricao: " + ("abc " * 2000) + " https://workana.example/project/999"

        normalized = normalize_gmail_email_dict(email, max_body_chars=80)

        self.assertLessEqual(len(normalized["body_text_limited"]), 80)
        self.assertTrue(normalized["has_attachment"])
        self.assertIn("gmail-msg-001", normalized["gmail_message_id"])
        self.assertIsInstance(normalized["link_candidates_as_text_only"], list)

    def test_build_raw_text_preserves_explicit_body_title(self):
        normalized = normalize_gmail_email_dict(WORKANA_EMAIL)
        raw = build_raw_text_for_ponte_from_gmail(normalized)

        self.assertIn("Subject: Nova oportunidade Workana", raw)
        self.assertIn("Titulo: Criar automacao para atendimento via WhatsApp", raw)
        self.assertIn("Email_Thread_ID: gmail-thread-001", raw)

    def test_local_gmail_email_dict_converts_to_ponte_event(self):
        event = gmail_email_to_ponte_event(WORKANA_EMAIL)

        self.assertEqual(event["source_platform"], "workana")
        self.assertEqual(event["source_channel"], GMAIL_READONLY_CHANNEL)
        self.assertEqual(event["external_thread_id"], "gmail-thread-001")
        self.assertEqual(event["external_contact_id"], "Workana <notificacoes@workana.example>")

        extracted = event.get("extracted") or {}
        self.assertEqual(
            extracted.get("opportunity_title"),
            "Criar automacao para atendimento via WhatsApp",
        )

        gmail_meta = event.get("gmail_readonly") or {}
        self.assertTrue(gmail_meta["has_attachment"])
        self.assertIn("https://workana.example/project/002", gmail_meta["link_candidates_as_text_only"])

    def test_gmail_readonly_policy_blocks_external_actions(self):
        event = gmail_email_to_ponte_event(WORKANA_EMAIL)
        policy = event.get("permission_policy") or {}

        self.assertTrue(policy["can_read_gmail_real"])
        self.assertTrue(policy["can_read_email_metadata"])
        self.assertTrue(policy["can_read_email_text"])
        self.assertFalse(policy["can_send_email"])
        self.assertFalse(policy["can_create_gmail_draft"])
        self.assertFalse(policy["can_download_attachment"])
        self.assertFalse(policy["can_open_link"])
        self.assertFalse(policy["can_open_workana"])
        self.assertFalse(policy["can_submit_proposal"])
        self.assertFalse(policy["can_send_message"])
        self.assertTrue(policy["requires_human_approval"])
        self.assertTrue(policy["dry_run"])

    def test_gmail_event_runs_through_classifier_and_draft(self):
        event = gmail_email_to_ponte_event(WORKANA_EMAIL)
        event = classify_event(event)
        draft = draft_proposal(event)

        classification = event.get("classification") or {}
        self.assertEqual(classification["fit_level"], "alto")
        self.assertEqual(classification["recommended_action"], "preparar_proposta")
        self.assertTrue(draft["requires_human_approval"])
        self.assertTrue(draft["dry_run"])


if __name__ == "__main__":
    unittest.main()
