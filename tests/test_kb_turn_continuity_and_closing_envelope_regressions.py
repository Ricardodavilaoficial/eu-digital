from __future__ import annotations

import json
import re
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from services import conversational_front as front
from services import wa_bot


PERSISTED_SUBSEGMENT = "servicos_profissionais__advocacia_individual"
PERSISTED_SEGMENT = "servicos_profissionais"
PERSISTED_ARCHETYPE = "servico_consultivo_profissional"
CURRENT_SUBSEGMENT = "comercio_varejista__loja_oculos"
CURRENT_SEGMENT = "comercio_varejista"
CURRENT_ARCHETYPE = "comercio_local"


def _runtime_block(label: str) -> dict:
    return {
        "summary": f"{label} " + ("contexto operacional " * 35),
        "response_rules": [
            f"{label} regra {index} " + ("detalhe " * 20)
            for index in range(5)
        ],
    }


def _subsegment_doc(
    doc_id: str,
    segment_id: str,
    archetype_id: str,
) -> dict:
    # Nomes e IDs abaixo são dados de fixture, não gatilhos de produção.
    return {
        "id": doc_id,
        "segment_id": segment_id,
        "archetype_id": archetype_id,
        "name": doc_id.replace("__", " ").replace("_", " "),
        "description": "descrição de fixture " + ("detalhe " * 70),
        "one_liner": "linha operacional " + ("contexto " * 30),
        "keywords": [doc_id.replace("__", " ").replace("_", " ")],
        "commercial_runtime": _runtime_block(f"comercial {doc_id}"),
        "operational_runtime": _runtime_block(f"operacional {doc_id}"),
        "behavior_components": _runtime_block(f"comportamento {doc_id}"),
        "enabled": True,
    }


def _kb_sources() -> dict:
    segments = {
        PERSISTED_SEGMENT: {
            "id": PERSISTED_SEGMENT,
            "name": "Serviços profissionais",
            "description": "segmento persistido " + ("detalhe " * 60),
        },
        CURRENT_SEGMENT: {
            "id": CURRENT_SEGMENT,
            "name": "Comércio varejista",
            "description": "segmento atual " + ("detalhe " * 60),
        },
        "servicos_locais": {
            "id": "servicos_locais",
            "name": "Serviços locais",
            "description": "fixture " + ("detalhe " * 60),
        },
        "saude": {
            "id": "saude",
            "name": "Saúde",
            "description": "fixture " + ("detalhe " * 60),
        },
    }

    subsegments = {
        PERSISTED_SUBSEGMENT: _subsegment_doc(
            PERSISTED_SUBSEGMENT,
            PERSISTED_SEGMENT,
            PERSISTED_ARCHETYPE,
        ),
        CURRENT_SUBSEGMENT: _subsegment_doc(
            CURRENT_SUBSEGMENT,
            CURRENT_SEGMENT,
            CURRENT_ARCHETYPE,
        ),
    }
    for index in range(7):
        doc_id = f"fixture_segmento__atividade_{index}"
        subsegments[doc_id] = _subsegment_doc(
            doc_id,
            "servicos_locais",
            f"fixture_arquetipo_{index % 3}",
        )

    archetypes = {
        PERSISTED_ARCHETYPE: {
            "id": PERSISTED_ARCHETYPE,
            "name": "Serviço consultivo",
            "description": "arquétipo persistido " + ("detalhe " * 60),
        },
        CURRENT_ARCHETYPE: {
            "id": CURRENT_ARCHETYPE,
            "name": "Comércio local",
            "description": "arquétipo atual " + ("detalhe " * 60),
        },
    }
    for index in range(3):
        archetypes[f"fixture_arquetipo_{index}"] = {
            "id": f"fixture_arquetipo_{index}",
            "name": f"Arquétipo fixture {index}",
            "description": "fixture " + ("detalhe " * 60),
        }

    value_packs = {
        f"PACK_FIXTURE_{index}": {
            "label": f"Pack fixture {index}",
            "runtime_short": {
                "value_one_liner": "valor global " + ("contexto " * 30),
                "bridge_line": "ponte global " + ("contexto " * 20),
            },
        }
        for index in range(4)
    }

    return {
        "kb": {
            "answer_playbook_v1": {
                "runtime_selector_v1": {"mode": "packs_v1"},
            },
            "value_packs_v1": value_packs,
            "process_facts": {
                "activation": "fato global " + ("contexto " * 25),
            },
        },
        "pricing": {},
        "segments": segments,
        "subsegments": subsegments,
        "archetypes": archetypes,
    }


class KbTurnContinuityRegressionTests(unittest.TestCase):
    def _capture_snapshot(
        self,
        *,
        user_text: str,
        persisted_segment: str = "",
        msg_type: str = "text",
    ) -> tuple[dict, dict]:
        captured: dict = {}
        memory = {}
        if persisted_segment:
            memory = {
                "segment": persisted_segment,
                "segment_hint": persisted_segment,
                "lead_memory_summary": "Contexto persistido da fixture.",
                "lead_memory_turns": 1,
            }

        def fake_front_handle(**kwargs):
            captured["snapshot"] = json.loads(kwargs.get("kb_snapshot") or "{}")
            captured["state_summary"] = dict(kwargs.get("state_summary") or {})
            return {
                "response_mode": "DIRECT",
                "replyText": "Resposta controlada da fixture.",
                "spokenText": "Resposta controlada da fixture.",
                "understanding": {
                    "topic": "OTHER",
                    "confidence": "high",
                    "question_type": "continuity",
                },
                "nextStep": "NONE",
                "shouldEnd": False,
                "prefersText": False,
                "replySource": "front",
                "segmentHint": persisted_segment,
                "operationalContract": {
                    "hydrated_from_platform_kb": True,
                    "response_mode": "DIRECT",
                },
            }

        ctx = {
            "waKey": "fixture-kb-continuity",
            "wa_id": "5511999999999",
            "from_e164": "+5511999999999",
            "msg_type": msg_type,
            "ai_turns": 1,
            "uid_owner": "",
        }

        with (
            patch.object(wa_bot, "CONVERSATIONAL_FRONT", True),
            patch.object(wa_bot, "MAX_AI_TURNS", 5),
            patch.object(
                wa_bot,
                "_load_institutional_lead_memory",
                return_value=memory,
            ),
            patch.object(
                wa_bot,
                "_save_institutional_lead_memory",
                return_value=None,
            ),
            patch.object(
                wa_bot,
                "_fetch_front_kb_sources",
                side_effect=lambda *args, **kwargs: _kb_sources(),
            ),
            patch(
                "services.speaker_state.get_speaker_state",
                return_value={"ai_turns": 1},
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
                side_effect=fake_front_handle,
            ),
        ):
            result = wa_bot.reply_to_text("", user_text, ctx)

        self.assertEqual(result.get("route"), "conversational_front")
        self.assertEqual(
            captured.get("state_summary", {}).get("segment_hint"),
            persisted_segment,
            msg="A fixture não conseguiu carregar o segmento persistido.",
        )
        return captured["snapshot"], captured["state_summary"]

    def _assert_snapshot_has_chain(
        self,
        snapshot: dict,
        *,
        subsegment_id: str,
        segment_id: str,
        archetype_id: str,
    ) -> None:
        missing = []
        if subsegment_id not in (snapshot.get("kb_subsegments_v1") or {}):
            missing.append(f"subsegment:{subsegment_id}")
        if segment_id not in (snapshot.get("kb_segments_v1") or {}):
            missing.append(f"segment:{segment_id}")
        if archetype_id not in (snapshot.get("kb_archetypes_v1") or {}):
            missing.append(f"archetype:{archetype_id}")
        self.assertEqual(
            missing,
            [],
            msg="O pruning perdeu a cadeia persistida: " + ", ".join(missing),
        )

    def test_persisted_segment_survives_informative_followup(self) -> None:
        snapshot, _ = self._capture_snapshot(
            user_text="Entendi. Como funciona a ativação depois do pagamento?",
            persisted_segment=PERSISTED_SUBSEGMENT,
        )

        self._assert_snapshot_has_chain(
            snapshot,
            subsegment_id=PERSISTED_SUBSEGMENT,
            segment_id=PERSISTED_SEGMENT,
            archetype_id=PERSISTED_ARCHETYPE,
        )

    def test_persisted_segment_survives_multi_objective_followup(self) -> None:
        snapshot, _ = self._capture_snapshot(
            user_text=(
                "Ainda tenho uma dúvida sobre o funcionamento e talvez "
                "eu queira contratar depois de entender esse ponto."
            ),
            persisted_segment=PERSISTED_SUBSEGMENT,
        )

        self._assert_snapshot_has_chain(
            snapshot,
            subsegment_id=PERSISTED_SUBSEGMENT,
            segment_id=PERSISTED_SEGMENT,
            archetype_id=PERSISTED_ARCHETYPE,
        )

    def test_explicit_current_segment_overrides_persisted_segment(self) -> None:
        snapshot, _ = self._capture_snapshot(
            user_text=(
                "Mudei de atividade e agora tenho uma loja de óculos. "
                "Como isso funcionaria no atendimento?"
            ),
            persisted_segment=PERSISTED_SUBSEGMENT,
        )

        self._assert_snapshot_has_chain(
            snapshot,
            subsegment_id=CURRENT_SUBSEGMENT,
            segment_id=CURRENT_SEGMENT,
            archetype_id=CURRENT_ARCHETYPE,
        )
        self.assertNotIn(
            PERSISTED_SUBSEGMENT,
            snapshot.get("kb_subsegments_v1") or {},
            msg="O segmento persistido contaminou uma mudança explícita.",
        )

    def test_no_current_or_persisted_segment_keeps_global_kb(self) -> None:
        snapshot, state_summary = self._capture_snapshot(
            user_text="Pode explicar melhor como isso funciona?",
        )

        self.assertFalse(state_summary.get("segment_hint"))
        self.assertEqual(snapshot.get("kb_segments_v1") or {}, {})
        self.assertEqual(snapshot.get("kb_subsegments_v1") or {}, {})
        self.assertEqual(snapshot.get("kb_archetypes_v1") or {}, {})
        self.assertTrue(
            snapshot.get("value_packs_v1"),
            msg="O modo global perdeu também os packs globais.",
        )

    def test_persisted_segment_survives_transcribed_audio_followup(self) -> None:
        snapshot, _ = self._capture_snapshot(
            user_text="Queria entender como funciona a ativação na prática.",
            persisted_segment=PERSISTED_SUBSEGMENT,
            msg_type="audio",
        )

        self._assert_snapshot_has_chain(
            snapshot,
            subsegment_id=PERSISTED_SUBSEGMENT,
            segment_id=PERSISTED_SEGMENT,
            archetype_id=PERSISTED_ARCHETYPE,
        )


class ClosingEnvelopeRegressionTests(unittest.TestCase):
    @staticmethod
    def _fake_client(raw: str, plain_reply: str):
        def create(**kwargs):
            messages = kwargs.get("messages") or []
            system_text = ""
            if messages and isinstance(messages[0], dict):
                system_text = str(messages[0].get("content") or "")
            is_main_json_call = bool(
                "FORMATO DE SAÍDA (OBRIGATÓRIO JSON)" in system_text
                and '"lead_name": ""' in system_text
                and '"lead_segment": ""' in system_text
            )
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=raw if is_main_json_call else plain_reply,
                        ),
                        finish_reason="stop",
                    )
                ],
                usage=SimpleNamespace(
                    prompt_tokens=100,
                    completion_tokens=80,
                    total_tokens=180,
                ),
            )

        return SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=create),
            )
        )

    def _common_closing_front_result(self) -> dict:
        closing_reply = "Perfeito. Vamos concluir a contratação agora."
        raw = json.dumps(
            {
                "response_mode": "CLOSING",
                "understanding": {
                    "topic": "ORCAMENTO",
                    "confidence": "high",
                    "question_type": "punctual",
                },
                "nextStep": "SEND_LINK",
                "replyText": closing_reply,
                "lead_name": "José",
                "lead_segment": PERSISTED_SUBSEGMENT,
                "lead_segment_raw": "profissão da fixture",
            },
            ensure_ascii=False,
        )
        state_summary = {
            "ai_turns": 1,
            "is_lead": True,
            "msg_type": "text",
            "segment_hint": PERSISTED_SUBSEGMENT,
            "subsegment_hint": PERSISTED_SUBSEGMENT,
            "lead_memory_turns": 1,
            "lead_memory_summary": "Contexto persistido da fixture.",
        }

        with (
            patch.object(front, "_HAS_OPENAI_CLIENT", True),
            patch.object(front, "_client", self._fake_client(raw, closing_reply)),
            patch.object(front, "FRONT_KB_RESOLVER_ENABLED", True),
            patch.object(
                front,
                "build_kb_context",
                return_value={"wants_link_explicit": True},
            ),
            patch.object(
                front,
                "_salvage_free_mode_payload",
                side_effect=AssertionError("Valid JSON must not enter salvage."),
            ),
        ):
            result = front.handle(
                user_text="Entendi. Quero assinar agora. Pode me mandar o link?",
                state_summary=state_summary,
                kb_snapshot="{}",
            )

        self.assertEqual(result.get("response_mode"), "CLOSING")
        self.assertEqual(result.get("nextStep"), "SEND_LINK")
        return result

    def _run_wa_bot_with_front_payload(self, front_payload: dict) -> dict:
        kb_sources = {
            "kb": {
                "answer_playbook_v1": {
                    "runtime_selector_v1": {"mode": "packs_v1"},
                }
            }
        }
        ctx = {
            "waKey": "fixture-closing-envelope",
            "wa_id": "5511888888888",
            "from_e164": "+5511888888888",
            "msg_type": "text",
            "ai_turns": 1,
            "uid_owner": "",
        }
        with (
            patch.object(wa_bot, "CONVERSATIONAL_FRONT", True),
            patch.object(wa_bot, "MAX_AI_TURNS", 5),
            patch.object(
                wa_bot,
                "_load_institutional_lead_memory",
                return_value={"segment_hint": PERSISTED_SUBSEGMENT},
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
            patch.object(wa_bot, "_build_front_kb_snapshot", return_value="{}"),
            patch(
                "services.speaker_state.get_speaker_state",
                return_value={"ai_turns": 1},
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
            return wa_bot.reply_to_text(
                "",
                "Entendi. Quero assinar agora. Pode me mandar o link?",
                ctx,
            )

    def test_common_closing_return_contains_operational_contract(self) -> None:
        result = self._common_closing_front_result()
        contract = result.get("operationalContract")

        self.assertIsInstance(
            contract,
            dict,
            msg="O retorno comum CLOSING omitiu operationalContract.",
        )
        self.assertEqual(
            (contract or {}).get("response_mode"),
            "CLOSING",
            msg="operationalContract não espelha response_mode=CLOSING.",
        )

    def test_wa_bot_accepts_common_closing_envelope_without_rescue(self) -> None:
        front_payload = self._common_closing_front_result()

        with self.assertLogs(level="INFO") as captured:
            result = self._run_wa_bot_with_front_payload(front_payload)

        front_reply_logs = [
            line
            for line in captured.output
            if "[WA_BOT][FRONT_REPLY_IN]" in line
        ]
        self.assertTrue(front_reply_logs)
        self.assertEqual(
            result.get("replySource"),
            "front",
            msg="O envelope CLOSING entrou em rescue ou fallback inesperado.",
        )
        self.assertTrue(
            str(result.get("replyText") or "").strip(),
            msg="O envelope CLOSING válido perdeu a resposta do front.",
        )
        self.assertIn(
            "valid=True",
            front_reply_logs[-1],
            msg="O wa_bot rejeitou um envelope CLOSING+SEND_LINK válido.",
        )
        self.assertIn("mode=CLOSING", front_reply_logs[-1])
        self.assertEqual(result.get("planNextStep"), "SEND_LINK")

    def test_send_link_contract_remains_single_and_nonempty(self) -> None:
        front_payload = self._common_closing_front_result()
        result = self._run_wa_bot_with_front_payload(front_payload)
        reply = str(result.get("replyText") or "").strip()

        self.assertEqual(result.get("planNextStep"), "SEND_LINK")
        self.assertTrue(reply)
        self.assertEqual(
            len(re.findall(r"https?://[^\s]+", reply)),
            1,
            msg="O contrato SEND_LINK deveria expor exatamente uma URL.",
        )

    def test_none_contract_is_not_changed_by_envelope_validation(self) -> None:
        payload = {
            "response_mode": "DIRECT",
            "replyText": "A ativação acontece após a configuração.",
            "spokenText": "A ativação acontece após a configuração.",
            "understanding": {
                "topic": "ATIVAR",
                "intent": "ATIVAR",
                "confidence": "high",
                "nextStep": "NONE",
            },
            "nextStep": "NONE",
            "shouldEnd": False,
            "prefersText": False,
            "replySource": "front",
        }
        result = self._run_wa_bot_with_front_payload(payload)

        self.assertEqual(result.get("planNextStep"), "NONE")
        self.assertFalse(result.get("prefersText"))
        self.assertNotRegex(str(result.get("replyText") or ""), r"https?://")


if __name__ == "__main__":
    unittest.main()
