import unittest

from services.ponte.marketplace_parser import parse_marketplace_text
from services.ponte.opportunity_classifier import classify_event


class PonteOpportunityClassifierSafetyTests(unittest.TestCase):
    def test_risky_credentials_opportunity_is_not_high_fit(self):
        raw = """
Titulo: Automacao de atendimento com IA e WhatsApp
Categoria: Programacao e tecnologia
Orcamento: R$ 3000
Prazo: 15 dias
Descricao: Preciso de automacao com IA, CRM, WhatsApp e web. O sistema deve usar senha e credenciais para acessar contas de clientes.
Habilidades: Python, IA, automacao, WhatsApp, CRM, web
Link: https://workana.example/project/risky
"""
        event = parse_marketplace_text(raw, source_platform="workana")
        event = classify_event(event)

        self.assertIn("termos_de_risco", event["risk_flags"])
        self.assertLessEqual(event["classification"]["fit_score"], 54)
        self.assertNotEqual(event["classification"]["fit_level"], "alto")
        self.assertNotEqual(event["classification"]["recommended_action"], "preparar_proposta")

    def test_low_fit_urgent_cheap_project_is_rejected(self):
        raw = """
Titulo: Fazer logo simples hoje
Categoria: Design
Orcamento: barato
Prazo: hoje
Descricao: Preciso copiar uma arte simples e fazer muito barato.
Habilidades: design
Link: https://workana.example/project/lowfit
"""
        event = parse_marketplace_text(raw, source_platform="workana")
        event = classify_event(event)

        self.assertIn("termos_de_risco", event["risk_flags"])
        self.assertEqual(event["classification"]["fit_level"], "rejeitar")
        self.assertEqual(event["classification"]["recommended_action"], "ignorar")


if __name__ == "__main__":
    unittest.main()
