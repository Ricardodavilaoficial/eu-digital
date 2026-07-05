import unittest
from pathlib import Path

from services.ponte.batch_fixture_runner import (
    HUMAN_REVIEW_STATUS,
    build_review_queue,
    format_review_queue,
    infer_platform_from_fixture,
)


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "ponte"


class PonteBatchFixtureRunnerTests(unittest.TestCase):
    def test_infer_platform_from_fixture_name(self):
        self.assertEqual(infer_platform_from_fixture("workana_email_001.txt"), "workana")
        self.assertEqual(
            infer_platform_from_fixture("international_platform_001.txt"),
            "international_platform_01",
        )
        self.assertEqual(infer_platform_from_fixture("unknown.txt"), "unknown_marketplace")

    def test_build_review_queue_from_local_fixtures(self):
        items = build_review_queue(FIXTURES)

        self.assertGreaterEqual(len(items), 2)
        platforms = {item["source_platform"] for item in items}
        self.assertIn("workana", platforms)
        self.assertIn("international_platform_01", platforms)

        for item in items:
            self.assertEqual(item["review_status"], HUMAN_REVIEW_STATUS)
            self.assertTrue(item["dry_run"])
            self.assertTrue(item["requires_human_approval"])
            self.assertFalse(item["can_submit_proposal"])
            self.assertFalse(item["can_send_message"])
            self.assertIn(item["fit_level"], ["alto", "medio", "baixo", "rejeitar"])

    def test_format_review_queue_contains_safety_markers(self):
        items = build_review_queue(FIXTURES)
        output = format_review_queue(items)

        self.assertIn("FILA LOCAL DE REVISAO HUMANA", output)
        self.assertIn("MODO: DRY-RUN / READ-ONLY", output)
        self.assertIn("aguardando_revisao_humana", output)
        self.assertIn("Nenhuma proposta foi enviada.", output)
        self.assertIn("Nenhum Gmail real foi acessado.", output)
        self.assertIn("Nenhuma plataforma real foi acessada.", output)
        self.assertIn("can_submit_proposal: False", output)
        self.assertIn("can_send_message: False", output)


if __name__ == "__main__":
    unittest.main()
