import unittest
from pathlib import Path

from services.ponte.fixture_report_runner import build_report


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "ponte"


class PonteFixtureReportRunnerTests(unittest.TestCase):
    def test_workana_report_contains_safety_markers(self):
        fixture = FIXTURES / "workana_email_001.txt"
        report = build_report(str(fixture), "workana")

        self.assertIn("MODO: DRY-RUN / READ-ONLY", report)
        self.assertIn("Nenhuma proposta foi enviada.", report)
        self.assertIn("Nenhum Gmail real foi acessado.", report)
        self.assertIn("Nenhuma plataforma real foi acessada.", report)
        self.assertIn("can_submit_proposal: False", report)
        self.assertIn("can_send_message: False", report)
        self.assertIn("can_read_gmail_real: False", report)
        self.assertIn("requires_human_approval: True", report)

    def test_workana_report_contains_core_outputs(self):
        fixture = FIXTURES / "workana_email_001.txt"
        report = build_report(str(fixture), "workana")

        self.assertIn("Criar automacao para atendimento via WhatsApp", report)
        self.assertIn("CLASSIFICACAO", report)
        self.assertIn("RASCUNHO DE PROPOSTA", report)
        self.assertIn("AUDITORIA", report)
        self.assertIn("Dedupe key:", report)
        self.assertIn("State key:", report)

    def test_international_report_keeps_english_draft(self):
        fixture = FIXTURES / "international_platform_001.txt"
        report = build_report(str(fixture), "international_platform_01")

        self.assertIn("Idioma:\nen", report)
        self.assertIn("Moeda:\nUSD", report)
        self.assertIn("Hello, I read your project", report)
        self.assertIn("This is a draft proposal and should be reviewed before submission.", report)
        self.assertIn("can_submit_proposal: False", report)


if __name__ == "__main__":
    unittest.main()
