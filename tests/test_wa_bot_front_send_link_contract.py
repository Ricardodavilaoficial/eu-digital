from __future__ import annotations

import unittest
from unittest.mock import patch

from services import wa_bot


class WaBotFrontSendLinkContractTests(unittest.TestCase):
    @staticmethod
    def _front_payload(
        *,
        reply_text: str,
        response_mode: str,
        next_step: str,
        intent: str,
        prefers_text: bool,
    ) -> dict:
        return {
            "replyText": reply_text,
            "spokenText": reply_text,
            "response_mode": response_mode,
            "nextStep": next_step,
            "shouldEnd": next_step == "SEND_LINK",
            "prefersText": prefers_text,
            "replySource": "front",
            "leadName": "José",
            "understanding": {
                "topic": "ATIVAR",
                "intent": intent,
                "confidence": "high",
                "question_type": "punctual",
                "nextStep": next_step,
            },
            "operationalContract": {
                "hydrated_from_platform_kb": True,
                "response_mode": response_mode,
            },
        }

    def _run_reply_to_text(
        self,
        *,
        user_text: str,
        front_payload: dict,
    ) -> dict:
        kb_sources = {
            "kb": {
                "answer_playbook_v1": {
                    "runtime_selector_v1": {
                        "mode": "packs_v1",
                    }
                }
            }
        }

        ctx = {
            "waKey": "test-wa-send-link-contract",
            "wa_id": "5511999999999",
            "from_e164": "+5511999999999",
            "msg_type": "text",
            "ai_turns": 0,
            "uid_owner": "",
        }

        with (
            patch.object(
                wa_bot,
                "CONVERSATIONAL_FRONT",
                True,
            ),
            patch.object(
                wa_bot,
                "MAX_AI_TURNS",
                5,
            ),
            patch.object(
                wa_bot,
                "_load_institutional_lead_memory",
                return_value={},
            ),
            patch.object(
                wa_bot,
                "_save_institutional_lead_memory",
                return_value=None,
            ),
            patch.object(
                wa_bot,
                "_fetch_front_kb_sources",
                return_value=kb_sources,
            ),
            patch.object(
                wa_bot,
                "_build_front_kb_snapshot",
                return_value="{}",
            ),
            patch(
                "services.speaker_state.get_speaker_state",
                return_value={"ai_turns": 0},
            ),
            patch(
                "services.speaker_state.is_force_operational",
                return_value=False,
            ),
            patch(
                "services.speaker_state.bump_ai_turns",
                return_value=None,
            ),
            patch(
                "services.conversational_front.handle",
                return_value=dict(front_payload),
            ),
        ):
            result = wa_bot.reply_to_text(
                "",
                user_text,
                ctx,
            )

        self.assertIsInstance(result, dict)
        self.assertEqual(
            result.get("route"),
            "conversational_front",
            msg=(
                "O teste não atravessou o caminho real "
                "de sucesso do conversational front."
            ),
        )
        return result

    def test_direct_none_with_activation_intent_is_authoritative(
        self,
    ) -> None:
        informative_reply = (
            "A ativação acontece após a confirmação do pagamento "
            "e a configuração das informações essenciais da empresa."
        )

        result = self._run_reply_to_text(
            user_text=(
                "Existe algum link explicando como funciona "
                "a ativação?"
            ),
            front_payload=self._front_payload(
                reply_text=informative_reply,
                response_mode="DIRECT",
                next_step="NONE",
                intent="ATIVAR",
                prefers_text=False,
            ),
        )

        reply = str(
            result.get("replyText") or ""
        ).strip()
        spoken = str(
            result.get("spokenText") or ""
        ).strip()

        self.assertEqual(
            result.get("planNextStep"),
            "NONE",
            msg=(
                "O wa_bot ressuscitou SEND_LINK apesar de "
                "o front ter autorizado explicitamente NONE."
            ),
        )

        self.assertFalse(
            bool(result.get("prefersText")),
            msg=(
                "Uma resposta DIRECT informativa foi "
                "convertida indevidamente em texto-only."
            ),
        )

        self.assertNotIn(
            "http://",
            reply.lower(),
        )
        self.assertNotIn(
            "https://",
            reply.lower(),
        )

        self.assertEqual(
            reply,
            informative_reply,
            msg=(
                "O corpo informativo do front foi "
                "substituído por uma mensagem de fechamento."
            ),
        )

        self.assertEqual(
            spoken,
            informative_reply,
            msg=(
                "A superfície falável da resposta "
                "informativa não foi preservada."
            ),
        )

    def test_authorized_closing_does_not_require_link_words(
        self,
    ) -> None:
        closing_reply = (
            "Perfeito, José. Podemos concluir a contratação agora."
        )

        result = self._run_reply_to_text(
            user_text=(
                "Quero concluir a contratação agora."
            ),
            front_payload=self._front_payload(
                reply_text=closing_reply,
                response_mode="CLOSING",
                next_step="SEND_LINK",
                intent="SIGNUP_LINK",
                prefers_text=True,
            ),
        )

        reply = str(
            result.get("replyText") or ""
        ).strip()

        self.assertEqual(
            result.get("planNextStep"),
            "SEND_LINK",
            msg=(
                "O wa_bot desautorizou um CLOSING legítimo "
                "porque o usuário não escreveu link/site/url."
            ),
        )

        self.assertTrue(
            bool(result.get("prefersText")),
        )

        self.assertTrue(
            ("http://" in reply.lower())
            or ("https://" in reply.lower()),
            msg=(
                "O fechamento semanticamente autorizado "
                "não recebeu a URL de contratação."
            ),
        )


if __name__ == "__main__":
    unittest.main()