import unittest
from pathlib import Path

from services.ponte.audit_log import build_audit_record
from services.ponte.marketplace_parser import parse_marketplace_text
from services.ponte.opportunity_classifier import classify_event
from services.ponte.permission_policy import is_action_allowed
from services.ponte.proposal_drafter import draft_proposal


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "ponte"


class PonteMarketplaceParserTests(unittest.TestCase):
    def test_workana_fixture_parse_and_policy(self):
        raw = (FIXTURES / "workana_email_001.txt").read_text(encoding="utf-8")
        event = parse_marketplace_text(raw, source_platform="workana")

        self.assertEqual(event["event_type"], "marketplace_opportunity")
        self.assertEqual(event["source_platform"], "workana")
        self.assertEqual(event["source_channel"], "fixture_txt")
        self.assertEqual(event["source_language"], "pt-BR")
        self.assertIn("WhatsApp", event["extracted"]["opportunity_title"])
        self.assertIn("R$", event["extracted"]["budget_raw"])
        self.assertFalse(event["permission_policy"]["can_submit_proposal"])
        self.assertTrue(event["permission_policy"]["dry_run"])
        self.assertFalse(is_action_allowed("submit_proposal", event["permission_policy"]))

    def test_classification_draft_and_audit_are_offline(self):
        raw = (FIXTURES / "workana_email_001.txt").read_text(encoding="utf-8")
        event = parse_marketplace_text(raw, source_platform="workana")
        event = classify_event(event)
        draft = draft_proposal(event)
        audit = build_audit_record(event, draft=draft)

        self.assertGreaterEqual(event["classification"]["fit_score"], 55)
        self.assertIn(event["classification"]["recommended_action"], ["preparar_proposta", "revisar_manualmente"])
        self.assertTrue(draft["requires_human_approval"])
        self.assertTrue(draft["dry_run"])
        self.assertTrue(audit["dry_run"])
        self.assertIn("can_submit_proposal", audit["blocked_actions"])

    def test_international_fixture_uses_english_draft(self):
        raw = (FIXTURES / "international_platform_001.txt").read_text(encoding="utf-8")
        event = parse_marketplace_text(
            raw,
            source_platform="international_platform_01",
            source_channel="fixture_txt",
        )
        event = classify_event(event)
        draft = draft_proposal(event)

        self.assertEqual(event["source_language"], "en")
        self.assertEqual(event["source_currency"], "USD")
        self.assertEqual(draft["draft_language"], "en")
        self.assertIn("draft proposal", draft["draft_text"].lower())


if __name__ == "__main__":
    unittest.main()
