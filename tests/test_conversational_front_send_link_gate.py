from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from services import conversational_front as front


class FrontSendLinkGateIntegrationTests(unittest.TestCase):
    @staticmethod
    def _fake_client(
        raw: str,
        plain_reply: str,
    ):
        def create(**kwargs):
            messages = kwargs.get("messages") or []

            system_text = ""
            if messages and isinstance(messages[0], dict):
                system_text = str(
                    messages[0].get("content") or ""
                )

            # O handle possui mais de uma chamada estruturada.
            # A principal contém também o contrato de identidade.
            is_main_json_call = bool(
                "FORMATO DE SAÍDA (OBRIGATÓRIO JSON)"
                in system_text
                and '"lead_name": ""'
                in system_text
                and '"lead_segment": ""'
                in system_text
            )

            selected_content = (
                raw
                if is_main_json_call
                else plain_reply
            )

            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=selected_content,
                        ),
                        finish_reason="stop",
                    )
                ],
                usage=SimpleNamespace(
                    prompt_tokens=100,
                    completion_tokens=100,
                    total_tokens=200,
                ),
            )

        return SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=create,
                )
            )
        )

    def _run_handle(
        self,
        *,
        user_text: str,
        response_mode: str,
        confidence: str = "high",
        ai_turns: int = 0,
        lead_memory_turns: int = 0,
        ai_reply: str = "",
    ) -> dict:
        informative_reply = str(
            ai_reply
            or (
                "A ativação do MEI Robô acontece depois da confirmação "
                "do pagamento e da configuração das informações essenciais "
                "da empresa. O ambiente é preparado e validado antes da "
                "liberação para uso."
            )
        )

        raw = json.dumps(
            {
                "response_mode": response_mode,
                "understanding": {
                    "topic": "OTHER",
                    "confidence": confidence,
                    "question_type": "punctual",
                },
                "nextStep": "SEND_LINK",
                "replyText": informative_reply,
                "lead_name": "José",
                "lead_segment": (
                    "servicos_profissionais__advocacia_individual"
                ),
                "lead_segment_raw": "advogado",
            },
            ensure_ascii=False,
        )

        state_summary = {
            "ai_turns": int(ai_turns),
            "is_lead": True,
            "msg_type": "text",
            "snapshot_topic": "ORCAMENTO",
            "last_intent": "",
            "last_user_goal": "",
            "lead_memory_turns": int(
                lead_memory_turns
            ),
            "lead_memory_summary": "",
        }

        with (
            patch.object(
                front,
                "_HAS_OPENAI_CLIENT",
                True,
            ),
            patch.object(
                front,
                "_client",
                self._fake_client(
                    raw,
                    informative_reply,
                ),
            ),
            patch.object(
                front,
                "FRONT_KB_RESOLVER_ENABLED",
                True,
            ),
            patch.object(
                front,
                "build_kb_context",
                return_value={
                    # Deliberadamente falso:
                    # o gate novo não deve depender de regex.
                    "wants_link_explicit": False,
                },
            ),
            patch.object(
                front,
                "_salvage_free_mode_payload",
                side_effect=AssertionError(
                    "Valid JSON must not enter salvage."
                ),
            ),
        ):
            result = front.handle(
                user_text=user_text,
                state_summary=state_summary,
                kb_snapshot="{}",
            )

        self.assertIsInstance(result, dict)
        return result

    def test_direct_informative_question_does_not_close(
        self,
    ) -> None:
        result = self._run_handle(
            user_text=(
                "Sou José, advogado. "
                "Como funciona a ativação?"
            ),
            response_mode="DIRECT",
            confidence="high",
            ai_turns=0,
            lead_memory_turns=0,
        )

        reply = str(
            result.get("replyText") or ""
        ).strip()
        spoken = str(
            result.get("spokenText") or ""
        ).strip()

        self.assertEqual(
            result.get("nextStep"),
            "NONE",
            msg=(
                "Uma resposta DIRECT informativa foi promovida "
                "indevidamente para SEND_LINK."
            ),
        )

        self.assertEqual(
            result.get("response_mode"),
            "DIRECT",
        )

        self.assertFalse(
            bool(result.get("prefersText")),
        )

        self.assertFalse(
            bool(result.get("shouldEnd")),
        )

        self.assertNotIn(
            "http://",
            reply.lower(),
        )
        self.assertNotIn(
            "https://",
            reply.lower(),
        )

        self.assertNotIn(
            '{"response_mode"',
            reply,
        )

        self.assertIn(
            "ativação",
            reply.casefold(),
        )
        self.assertIn(
            "ativação",
            spoken.casefold(),
        )

    def test_closing_high_confidence_works_on_first_turn(
        self,
    ) -> None:
        result = self._run_handle(
            user_text=(
                "Sou José, advogado e quero prosseguir "
                "com a contratação agora."
            ),
            response_mode="CLOSING",
            confidence="high",
            ai_turns=0,
            lead_memory_turns=0,
        )

        reply = str(
            result.get("replyText") or ""
        ).strip()
        spoken = str(
            result.get("spokenText") or ""
        ).strip()

        self.assertEqual(
            result.get("nextStep"),
            "SEND_LINK",
            msg=(
                "Um fechamento estrutural legítimo foi "
                "bloqueado no primeiro turno."
            ),
        )

        self.assertEqual(
            result.get("response_mode"),
            "CLOSING",
        )

        self.assertTrue(
            bool(result.get("prefersText")),
        )

        self.assertTrue(
            ("http://" in reply.lower())
            or ("https://" in reply.lower()),
            msg=(
                "O fechamento legítimo não recebeu "
                "o endereço de contratação."
            ),
        )

        self.assertEqual(
            reply,
            spoken,
            msg=(
                "replyText e spokenText divergiram "
                "nos fatos essenciais do fechamento."
            ),
        )

        self.assertNotIn(
            '{"response_mode"',
            reply,
        )

    def test_direct_downgrade_removes_preexisting_platform_url(
        self,
    ) -> None:
        result = self._run_handle(
            user_text=(
                "Sou José, advogado. "
                "Como funciona a ativação?"
            ),
            response_mode="DIRECT",
            confidence="high",
            ai_reply=(
                "Olá. A ativação ocorre após a confirmação. "
                "https://www.meirobo.com.br."
            ),
        )

        reply = str(
            result.get("replyText") or ""
        ).strip()
        spoken = str(
            result.get("spokenText") or ""
        ).strip()

        self.assertEqual(
            result.get("response_mode"),
            "DIRECT",
        )
        self.assertEqual(
            result.get("nextStep"),
            "NONE",
        )
        self.assertNotIn(
            "meirobo.com.br",
            reply.casefold(),
        )
        self.assertNotIn(
            "meirobo.com.br",
            spoken.casefold(),
        )
        self.assertIn(
            "A ativação ocorre após a confirmação.",
            reply,
        )
        self.assertIn(
            "A ativação ocorre após a confirmação.",
            spoken,
        )

    def test_closing_preserves_preexisting_platform_url(
        self,
    ) -> None:
        result = self._run_handle(
            user_text=(
                "Sou José, advogado e quero prosseguir "
                "com a contratação agora."
            ),
            response_mode="CLOSING",
            confidence="high",
            ai_reply=(
                "Perfeito. Vamos concluir a contratação. "
                "https://www.meirobo.com.br."
            ),
        )

        self.assertEqual(
            result.get("response_mode"),
            "CLOSING",
        )
        self.assertEqual(
            result.get("nextStep"),
            "SEND_LINK",
        )
        self.assertIn(
            "https://www.meirobo.com.br",
            str(result.get("replyText") or ""),
        )
        self.assertIn(
            "https://www.meirobo.com.br",
            str(result.get("spokenText") or ""),
        )

    def test_direct_downgrade_preserves_unrelated_url(
        self,
    ) -> None:
        result = self._run_handle(
            user_text=(
                "Sou José, advogado. "
                "Como funciona a ativação?"
            ),
            response_mode="DIRECT",
            confidence="high",
            ai_reply=(
                "A documentação está em "
                "https://docs.example.com/manual. "
                "https://www.meirobo.com.br."
            ),
        )

        reply = str(
            result.get("replyText") or ""
        )
        spoken = str(
            result.get("spokenText") or ""
        )

        self.assertEqual(
            result.get("nextStep"),
            "NONE",
        )
        self.assertIn(
            "https://docs.example.com/manual",
            reply,
        )
        self.assertIn(
            "https://docs.example.com/manual",
            spoken,
        )
        self.assertNotIn(
            "meirobo.com.br",
            reply.casefold(),
        )
        self.assertNotIn(
            "meirobo.com.br",
            spoken.casefold(),
        )

    def test_arbitration_preserves_direct_with_send_link(
        self,
    ) -> None:
        (
            response_mode,
            needs_clarify,
            clarify_q,
        ) = front._apply_response_mode_arbitration(
            response_mode="DIRECT",
            next_step="SEND_LINK",
            global_pack_scene_ready=False,
            question_type="punctual",
            needs_clarify="no",
            clarify_q="",
            topic="OTHER",
            operational_contract={},
        )

        self.assertEqual(
            response_mode,
            "DIRECT",
            msg=(
                "A arbitragem voltou a transformar "
                "SEND_LINK em CLOSING automaticamente."
            ),
        )

        self.assertEqual(
            needs_clarify,
            "no",
        )

        self.assertEqual(
            clarify_q,
            "",
        )

    def test_missing_mode_with_punctual_send_link_is_direct(
        self,
    ) -> None:
        response_mode = (
            front._infer_response_mode_from_signals(
                topic="OTHER",
                confidence="high",
                needs_clarify="no",
                clarify_q="",
                next_step="SEND_LINK",
                effective_segment="",
                kb_anchor_strong=False,
                operational_contract={},
                question_type="punctual",
            )
        )

        self.assertEqual(
            response_mode,
            "DIRECT",
            msg=(
                "O fallback de modo voltou a inferir "
                "CLOSING somente por existir SEND_LINK."
            ),
        )


if __name__ == "__main__":
    unittest.main()
