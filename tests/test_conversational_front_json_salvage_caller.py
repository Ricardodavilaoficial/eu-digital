from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from services import conversational_front as front


class FrontJsonSalvageCallerIntegrationTests(
    unittest.TestCase
):
    def test_handle_passes_full_raw_to_salvage_when_outer_json_is_truncated(
        self,
    ) -> None:
        direct_answer = (
            "A ativação começa depois que o cadastro e as configurações "
            "essenciais da empresa são concluídos. A equipe valida os dados, "
            "o número que será utilizado e as informações necessárias para "
            "o atendimento. Em seguida, o ambiente é preparado, as regras "
            "configuradas são conferidas e o funcionamento é validado antes "
            "da liberação. Assim, o profissional começa a usar o MEI Robô "
            "com o atendimento alinhado ao seu negócio e às informações "
            "cadastradas."
        )

        # Estrutura sanitizada baseada no incidente real:
        # - o objeto understanding possui fechamento interno;
        # - o objeto JSON externo fica truncado;
        # - replyText existe depois do último '}' disponível;
        # - finish_reason é length.
        raw = (
            '{"response_mode":"DIRECT",'
            '"understanding":{'
            '"topic":"ORCAMENTO",'
            '"confidence":"medium",'
            '"question_type":"punctual"},'
            '"nextStep":"NONE",'
            f'"replyText":"{direct_answer}'
        )

        self.assertIn('"replyText"', raw)
        self.assertFalse(raw.rstrip().endswith("}"))

        fake_response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=raw,
                    ),
                    finish_reason="length",
                )
            ],
            usage=SimpleNamespace(
                prompt_tokens=4939,
                completion_tokens=310,
                total_tokens=5249,
            ),
        )

        fake_client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=lambda **_kwargs: fake_response,
                )
            )
        )

        salvage_inputs: list[str] = []
        real_salvage = front._salvage_free_mode_payload

        def recording_salvage(source: str):
            source_text = str(source or "")
            salvage_inputs.append(source_text)
            return real_salvage(source_text)

        state_summary = {
            "ai_turns": 0,
            "is_lead": True,
            "msg_type": "text",
            "snapshot_topic": "ORCAMENTO",
            "last_intent": "",
            "last_user_goal": "",
            "lead_memory_turns": 0,
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
                fake_client,
            ),
            patch.object(
                front,
                "_salvage_free_mode_payload",
                side_effect=recording_salvage,
            ),
        ):
            result = front.handle(
                user_text=(
                    "Sou José, advogado. "
                    "Como funciona a ativação?"
                ),
                state_summary=state_summary,
                kb_snapshot="{}",
            )

        self.assertIsInstance(result, dict)

        self.assertTrue(
            salvage_inputs,
            msg=(
                "The malformed JSON path did not call "
                "_salvage_free_mode_payload()."
            ),
        )

        selected_source = salvage_inputs[0]
        selected_has_reply = (
            '"replyText"' in selected_source
        )

        # Esta é a prova de integração.
        # No commit 12aab6a, espera-se que falhe porque o caller
        # entrega o recorte 'repaired', anterior a replyText.
        self.assertTrue(
            selected_source == raw,
            msg=(
                "Caller did not pass the full raw response to salvage. "
                f"selected_len={len(selected_source)} "
                f"raw_len={len(raw)} "
                f"selected_has_reply={selected_has_reply} "
                f"selected_tail={selected_source[-100:]!r}"
            ),
        )

        recovered = real_salvage(selected_source)

        self.assertEqual(
            recovered.get("replyText"),
            direct_answer,
        )

        self.assertEqual(
            recovered.get("spokenText"),
            direct_answer,
        )

        final_reply = str(
            result.get("replyText") or ""
        ).strip()
        final_spoken = str(
            result.get("spokenText") or ""
        ).strip()

        activation_core = (
            "A ativação começa depois que o cadastro "
            "e as configurações essenciais da empresa "
            "são concluídos."
        )

        self.assertTrue(
            final_reply,
            msg="handle() returned an empty replyText.",
        )
        self.assertTrue(
            final_spoken,
            msg="handle() returned an empty spokenText.",
        )

        self.assertIn(
            activation_core,
            final_reply,
            msg=(
                "The final reply lost the recovered "
                "activation answer."
            ),
        )
        self.assertIn(
            activation_core,
            final_spoken,
            msg=(
                "The final spoken text lost the recovered "
                "activation answer."
            ),
        )

        self.assertNotIn(
            "Veja um exemplo prático:",
            final_reply,
            msg=(
                "A later layer replaced the current answer "
                "with a broad micro-scene."
            ),
        )


    def test_valid_json_direct_bypasses_salvage_and_preserves_activation(
        self,
    ) -> None:
        direct_answer = (
            "Ricardo, que bom falar com você e conhecer sua atuação "
            "na advocacia. A ativação começa depois que o cadastro e "
            "as configurações essenciais da empresa são concluídos. "
            "Em seguida, os dados e as regras de atendimento são "
            "validados antes da liberação do ambiente."
        )

        raw = json.dumps(
            {
                "response_mode": "DIRECT",
                "understanding": {
                    "topic": "ORCAMENTO",
                    "confidence": "high",
                    "question_type": "punctual",
                },
                "nextStep": "NONE",
                "replyText": direct_answer,
            },
            ensure_ascii=False,
        )

        fake_response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=raw,
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

        fake_client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=lambda **_kwargs: fake_response,
                )
            )
        )

        state_summary = {
            "ai_turns": 0,
            "is_lead": True,
            "msg_type": "text",
            "snapshot_topic": "ORCAMENTO",
            "lead_memory_turns": 0,
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
                fake_client,
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
                user_text=(
                    "Meu nome é Ricardo, sou advogado. "
                    "Como funciona a ativação?"
                ),
                state_summary=state_summary,
                kb_snapshot="{}",
            )

        final_reply = str(
            result.get("replyText") or ""
        ).strip()
        final_spoken = str(
            result.get("spokenText") or ""
        ).strip()

        self.assertIn(
            "A ativação começa depois que o cadastro",
            final_reply,
        )
        self.assertIn(
            "A ativação começa depois que o cadastro",
            final_spoken,
        )
        self.assertNotIn(
            "Veja um exemplo prático:",
            final_reply,
        )

    def test_valid_json_scene_bypasses_salvage_and_preserves_requested_scene(
        self,
    ) -> None:
        scene_answer = (
            "Veja um exemplo prático: quando um cliente chama no "
            "WhatsApp, o MEI Robô acolhe o contato, organiza o relato "
            "inicial e encaminha as informações necessárias para o "
            "profissional continuar o atendimento."
        )

        raw = json.dumps(
            {
                "response_mode": "SCENE",
                "understanding": {
                    "topic": "ORCAMENTO",
                    "confidence": "high",
                    "question_type": "broad",
                },
                "nextStep": "NONE",
                "replyText": scene_answer,
            },
            ensure_ascii=False,
        )

        fake_response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=raw,
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

        fake_client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=lambda **_kwargs: fake_response,
                )
            )
        )

        state_summary = {
            "ai_turns": 1,
            "is_lead": True,
            "msg_type": "text",
            "snapshot_topic": "ORCAMENTO",
            "name_hint": "Ricardo",
            "segment_hint": (
                "servicos_profissionais__advocacia_individual"
            ),
            "lead_memory_turns": 1,
            "lead_memory_summary": (
                "Ricardo atua na advocacia."
            ),
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
                fake_client,
            ),
            patch.object(
                front,
                "_salvage_free_mode_payload",
                side_effect=AssertionError(
                    "Valid SCENE JSON must not enter salvage."
                ),
            ),
        ):
            result = front.handle(
                user_text=(
                    "Mostre um exemplo prático de como o "
                    "MEI Robô atenderia meus clientes."
                ),
                state_summary=state_summary,
                kb_snapshot="{}",
            )

        final_reply = str(
            result.get("replyText") or ""
        ).strip()

        self.assertIn(
            "Veja um exemplo prático:",
            final_reply,
        )
        self.assertIn(
            "organiza o relato inicial",
            final_reply,
        )


if __name__ == "__main__":
    unittest.main()
