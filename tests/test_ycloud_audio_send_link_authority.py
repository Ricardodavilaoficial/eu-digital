from __future__ import annotations

import unittest
from unittest.mock import patch

from routes import ycloud_tasks_bp as tasks


class YCloudAudioSendLinkAuthorityTests(unittest.TestCase):
    def test_send_link_plain_text_does_not_satisfy_and_fallback_sends_url(
        self,
    ) -> None:
        calls = []

        def send_text(to_e164: str, text: str):
            calls.append((to_e164, text))
            return True, {"ok": True}

        with patch.dict(
            "os.environ",
            {"FRONTEND_BASE": "https://contrato.example.com"},
            clear=False,
        ):
            attempted_plain, sent_plain, _ = (
                tasks._attempt_send_link_text_delivery(
                    send_text_fn=send_text,
                    to_e164="+5511999999999",
                    text="Fechado. Vou encaminhar a contratação.",
                    delivery_next_step="SEND_LINK",
                    already_sent=False,
                )
            )
            fallback = tasks._ensure_send_link_in_reply(
                "Fechado. Vou encaminhar a contratação.",
                "SEND_LINK",
            )
            attempted_link, sent_link, _ = (
                tasks._attempt_send_link_text_delivery(
                    send_text_fn=send_text,
                    to_e164="+5511999999999",
                    text=fallback,
                    delivery_next_step="SEND_LINK",
                    already_sent=sent_plain,
                )
            )

        self.assertFalse(attempted_plain)
        self.assertFalse(sent_plain)
        self.assertTrue(attempted_link)
        self.assertTrue(sent_link)
        self.assertEqual(len(calls), 1)
        self.assertIn(
            "https://contrato.example.com",
            calls[0][1],
        )

    def test_external_url_does_not_satisfy_send_link(
        self,
    ) -> None:
        calls = []

        def send_text(to_e164: str, text: str):
            calls.append((to_e164, text))
            return True, {"ok": True}

        with patch.dict(
            "os.environ",
            {"FRONTEND_BASE": "https://contrato.example.com"},
            clear=False,
        ):
            attempted, sent, _ = (
                tasks._attempt_send_link_text_delivery(
                    send_text_fn=send_text,
                    to_e164="+5511999999999",
                    text="Veja https://docs.example.com/manual",
                    delivery_next_step="SEND_LINK",
                    already_sent=False,
                )
            )
            materialized = tasks._ensure_send_link_in_reply(
                "Veja https://docs.example.com/manual",
                "SEND_LINK",
            )

        self.assertFalse(attempted)
        self.assertFalse(sent)
        self.assertEqual(calls, [])
        self.assertFalse(
            tasks._text_contains_send_link_platform_url(
                "https://evil.example/?next=https://contrato.example.com"
            )
        )
        self.assertIn(
            "https://docs.example.com/manual",
            materialized,
        )
        self.assertIn(
            "https://contrato.example.com",
            materialized,
        )

    def test_own_url_provider_success_satisfies_without_duplicate(
        self,
    ) -> None:
        calls = []

        def send_text(to_e164: str, text: str):
            calls.append((to_e164, text))
            return True, {"ok": True}

        with patch.dict(
            "os.environ",
            {"FRONTEND_BASE": "https://contrato.example.com"},
            clear=False,
        ):
            attempted_1, sent_1, _ = (
                tasks._attempt_send_link_text_delivery(
                    send_text_fn=send_text,
                    to_e164="+5511999999999",
                    text="https://contrato.example.com",
                    delivery_next_step="SEND_LINK",
                    already_sent=False,
                )
            )
            attempted_2, sent_2, _ = (
                tasks._attempt_send_link_text_delivery(
                    send_text_fn=send_text,
                    to_e164="+5511999999999",
                    text="https://contrato.example.com",
                    delivery_next_step="SEND_LINK",
                    already_sent=sent_1,
                )
            )

        self.assertTrue(attempted_1)
        self.assertTrue(sent_1)
        self.assertFalse(attempted_2)
        self.assertTrue(sent_2)
        self.assertEqual(len(calls), 1)

    def test_ack_and_definitive_link_failure_returns_pending(
        self,
    ) -> None:
        results = iter((False, False))

        def send_text(to_e164: str, text: str):
            return next(results), {"ok": False}

        attempted_1, sent_1, _ = (
            tasks._attempt_send_link_text_delivery(
                send_text_fn=send_text,
                to_e164="+5511999999999",
                text="https://www.meirobo.com.br",
                delivery_next_step="SEND_LINK",
                already_sent=False,
            )
        )
        attempted_2, sent_2, _ = (
            tasks._attempt_send_link_text_delivery(
                send_text_fn=send_text,
                to_e164="+5511999999999",
                text="https://www.meirobo.com.br",
                delivery_next_step="SEND_LINK",
                already_sent=sent_1,
            )
        )
        response = tasks._build_worker_delivery_response(
            delivery_next_step="SEND_LINK",
            sent_ok=True,
            link_text_sent=sent_2,
        )

        self.assertTrue(attempted_1)
        self.assertTrue(attempted_2)
        self.assertFalse(sent_1)
        self.assertFalse(sent_2)
        self.assertFalse(response.get("sent"))
        self.assertTrue(response.get("outboundSent"))
        self.assertTrue(response.get("partial"))
        self.assertFalse(response.get("linkTextSent"))
        self.assertTrue(response.get("sendLinkPending"))

    def test_ack_and_retry_exception_returns_pending_without_audio_repeat(
        self,
    ) -> None:
        audio_calls = 1
        text_calls = 0

        def send_text(to_e164: str, text: str):
            nonlocal text_calls
            text_calls += 1
            if text_calls == 1:
                return False, {"ok": False}
            raise RuntimeError("provider unavailable")

        _, sent_1, _ = tasks._attempt_send_link_text_delivery(
            send_text_fn=send_text,
            to_e164="+5511999999999",
            text="https://www.meirobo.com.br",
            delivery_next_step="SEND_LINK",
            already_sent=False,
        )
        with self.assertRaises(RuntimeError):
            tasks._attempt_send_link_text_delivery(
                send_text_fn=send_text,
                to_e164="+5511999999999",
                text="https://www.meirobo.com.br",
                delivery_next_step="SEND_LINK",
                already_sent=sent_1,
            )

        response = tasks._build_worker_delivery_response(
            delivery_next_step="SEND_LINK",
            sent_ok=True,
            link_text_sent=False,
        )

        self.assertEqual(audio_calls, 1)
        self.assertEqual(text_calls, 2)
        self.assertFalse(response.get("sent"))
        self.assertTrue(response.get("partial"))
        self.assertTrue(response.get("sendLinkPending"))

    def test_legacy_linkless_closure_materializes_own_url(
        self,
    ) -> None:
        authority = tasks._resolve_sales_send_link_authority(
            plan_next_step="CTA",
            understanding={},
            legacy_close_signal=True,
            transcript_close_signal=False,
            explicit_link_request=False,
        )
        with patch.dict(
            "os.environ",
            {"FRONTEND_BASE": "https://contrato.example.com"},
            clear=False,
        ):
            payload = tasks._ensure_send_link_in_reply(
                "Perfeito. Vamos concluir.",
                str(authority.get("delivery_next_step") or ""),
            )

        self.assertEqual(
            authority.get("delivery_next_step"),
            "SEND_LINK",
        )
        self.assertIn(
            "https://contrato.example.com",
            payload,
        )

    def test_none_response_has_no_send_link_pending_state(
        self,
    ) -> None:
        response = tasks._build_worker_delivery_response(
            delivery_next_step="NONE",
            sent_ok=True,
            link_text_sent=False,
        )

        self.assertTrue(response.get("sent"))
        self.assertNotIn("sendLinkPending", response)
        self.assertNotIn("linkTextSent", response)

    def test_plan_none_blocks_all_link_resurrection(
        self,
    ) -> None:
        result = tasks._resolve_sales_send_link_authority(
            plan_next_step="NONE",
            understanding={
                "next_step": "SEND_LINK",
                "intent": "ACTIVATE",
            },
            legacy_close_signal=True,
            transcript_close_signal=True,
            explicit_link_request=True,
        )

        self.assertEqual(
            result.get("effective_next_step"),
            "NONE",
        )
        self.assertTrue(
            bool(result.get("has_structural_decision")),
        )
        self.assertFalse(
            bool(result.get("send_link_authorized")),
        )
        self.assertFalse(
            bool(result.get("close_signal")),
        )
        self.assertFalse(
            bool(result.get("allow_explicit_cta")),
        )
        self.assertFalse(
            bool(result.get("append_link")),
        )

    def test_plan_send_link_authorizes_audio_plus_text(
        self,
    ) -> None:
        result = tasks._resolve_sales_send_link_authority(
            plan_next_step="SEND_LINK",
            understanding={
                "next_step": "NONE",
                "intent": "OTHER",
            },
            legacy_close_signal=False,
            transcript_close_signal=False,
            explicit_link_request=False,
        )

        self.assertEqual(
            result.get("effective_next_step"),
            "SEND_LINK",
        )
        self.assertTrue(
            bool(result.get("has_structural_decision")),
        )
        self.assertTrue(
            bool(result.get("send_link_authorized")),
        )
        self.assertTrue(
            bool(result.get("close_signal")),
        )
        self.assertTrue(
            bool(result.get("append_link")),
        )
        self.assertFalse(
            bool(result.get("allow_explicit_cta")),
        )

    def test_understanding_none_is_secondary_authority(
        self,
    ) -> None:
        result = tasks._resolve_sales_send_link_authority(
            plan_next_step="",
            understanding={
                "next_step": "NONE",
                "intent": "SIGNUP_LINK",
            },
            legacy_close_signal=True,
            transcript_close_signal=True,
            explicit_link_request=True,
        )

        self.assertEqual(
            result.get("effective_next_step"),
            "NONE",
        )
        self.assertTrue(
            bool(result.get("has_structural_decision")),
        )
        self.assertFalse(
            bool(result.get("send_link_authorized")),
        )
        self.assertFalse(
            bool(result.get("close_signal")),
        )
        self.assertFalse(
            bool(result.get("allow_explicit_cta")),
        )

    def test_understanding_send_link_is_secondary_authority(
        self,
    ) -> None:
        result = tasks._resolve_sales_send_link_authority(
            plan_next_step="UNKNOWN",
            understanding={
                "next_step": "SEND_LINK",
                "intent": "OTHER",
            },
            legacy_close_signal=False,
            transcript_close_signal=False,
            explicit_link_request=False,
        )

        self.assertEqual(
            result.get("effective_next_step"),
            "SEND_LINK",
        )
        self.assertTrue(
            bool(result.get("send_link_authorized")),
        )
        self.assertTrue(
            bool(result.get("close_signal")),
        )
        self.assertTrue(
            bool(result.get("append_link")),
        )

    def test_legacy_signals_work_without_structural_decision(
        self,
    ) -> None:
        result = tasks._resolve_sales_send_link_authority(
            plan_next_step="",
            understanding={
                "intent": "ACTIVATE",
            },
            legacy_close_signal=True,
            transcript_close_signal=False,
            explicit_link_request=False,
        )

        self.assertEqual(
            result.get("effective_next_step"),
            "",
        )
        self.assertFalse(
            bool(result.get("has_structural_decision")),
        )
        self.assertFalse(
            bool(result.get("send_link_authorized")),
        )
        self.assertTrue(
            bool(result.get("close_signal")),
        )
        self.assertTrue(
            bool(result.get("append_link")),
        )

    def test_delivery_next_step_matches_outbound_authority(
        self,
    ) -> None:
        cases = (
            (
                "plan_none",
                {
                    "plan_next_step": "NONE",
                    "understanding": {
                        "next_step": "SEND_LINK",
                        "intent": "ACTIVATE",
                    },
                    "legacy_close_signal": True,
                    "transcript_close_signal": True,
                    "explicit_link_request": True,
                },
                "NONE",
            ),
            (
                "plan_send_link",
                {
                    "plan_next_step": "SEND_LINK",
                    "understanding": {
                        "next_step": "NONE",
                    },
                    "legacy_close_signal": False,
                    "transcript_close_signal": False,
                    "explicit_link_request": False,
                },
                "SEND_LINK",
            ),
            (
                "legacy_close",
                {
                    "plan_next_step": "",
                    "understanding": {
                        "intent": "ACTIVATE",
                    },
                    "legacy_close_signal": True,
                    "transcript_close_signal": False,
                    "explicit_link_request": False,
                },
                "SEND_LINK",
            ),
            (
                "explicit_cta_only",
                {
                    "plan_next_step": "",
                    "understanding": {},
                    "legacy_close_signal": False,
                    "transcript_close_signal": False,
                    "explicit_link_request": True,
                },
                "",
            ),
        )

        for (
            label,
            payload,
            expected,
        ) in cases:
            with self.subTest(
                label=label,
            ):
                result = (
                    tasks
                    ._resolve_sales_send_link_authority(
                        **payload
                    )
                )

                self.assertEqual(
                    result.get(
                        "delivery_next_step"
                    ),
                    expected,
                )

    def test_explicit_cta_only_works_without_structural_decision(
        self,
    ) -> None:
        result = tasks._resolve_sales_send_link_authority(
            plan_next_step="",
            understanding={},
            legacy_close_signal=False,
            transcript_close_signal=False,
            explicit_link_request=True,
        )

        self.assertFalse(
            bool(result.get("has_structural_decision")),
        )
        self.assertFalse(
            bool(result.get("send_link_authorized")),
        )
        self.assertFalse(
            bool(result.get("close_signal")),
        )
        self.assertTrue(
            bool(result.get("allow_explicit_cta")),
        )
        self.assertFalse(
            bool(result.get("append_link")),
        )

    def test_audio_ack_ok_and_link_failure_retries_only_text(
        self,
    ) -> None:
        calls = {
            "audio": 0,
            "text": 0,
        }
        text_results = iter(
            (False, True),
        )

        def send_audio(
            to_e164: str,
            audio_url: str,
        ):
            calls["audio"] += 1
            return True, {"ok": True}

        def send_text(
            to_e164: str,
            text: str,
        ):
            calls["text"] += 1
            return next(text_results), {"ok": True}

        audio_ok, _ = send_audio(
            "+5511999999999",
            "https://audio.invalid/ack.mp3",
        )
        self.assertTrue(audio_ok)

        attempted_1, sent_1, _ = (
            tasks._attempt_send_link_text_delivery(
                send_text_fn=send_text,
                to_e164="+5511999999999",
                text="https://www.meirobo.com.br",
                delivery_next_step="SEND_LINK",
                already_sent=False,
            )
        )
        attempted_2, sent_2, _ = (
            tasks._attempt_send_link_text_delivery(
                send_text_fn=send_text,
                to_e164="+5511999999999",
                text="https://www.meirobo.com.br",
                delivery_next_step="SEND_LINK",
                already_sent=sent_1,
            )
        )

        self.assertTrue(attempted_1)
        self.assertFalse(sent_1)
        self.assertTrue(attempted_2)
        self.assertTrue(sent_2)
        self.assertEqual(calls["audio"], 1)
        self.assertEqual(calls["text"], 2)

    def test_successful_link_text_prevents_retry_and_duplication(
        self,
    ) -> None:
        text_calls = []

        def send_text(
            to_e164: str,
            text: str,
        ):
            text_calls.append(
                (to_e164, text),
            )
            return True, {"ok": True}

        attempted_1, sent_1, _ = (
            tasks._attempt_send_link_text_delivery(
                send_text_fn=send_text,
                to_e164="+5511999999999",
                text="https://www.meirobo.com.br",
                delivery_next_step="SEND_LINK",
                already_sent=False,
            )
        )
        attempted_2, sent_2, _ = (
            tasks._attempt_send_link_text_delivery(
                send_text_fn=send_text,
                to_e164="+5511999999999",
                text="https://www.meirobo.com.br",
                delivery_next_step="SEND_LINK",
                already_sent=sent_1,
            )
        )

        self.assertTrue(attempted_1)
        self.assertTrue(sent_1)
        self.assertFalse(attempted_2)
        self.assertTrue(sent_2)
        self.assertEqual(len(text_calls), 1)

    def test_plan_none_never_attempts_link_text_or_retry(
        self,
    ) -> None:
        text_calls = []

        def send_text(
            to_e164: str,
            text: str,
        ):
            text_calls.append(
                (to_e164, text),
            )
            return True, {"ok": True}

        attempted, sent, _ = (
            tasks._attempt_send_link_text_delivery(
                send_text_fn=send_text,
                to_e164="+5511999999999",
                text="https://www.meirobo.com.br",
                delivery_next_step="NONE",
                already_sent=False,
            )
        )

        self.assertFalse(attempted)
        self.assertFalse(sent)
        self.assertEqual(text_calls, [])

    def test_legacy_authorized_delivery_retries_without_duplicate(
        self,
    ) -> None:
        authority = (
            tasks._resolve_sales_send_link_authority(
                plan_next_step="",
                understanding={
                    "intent": "ACTIVATE",
                },
                legacy_close_signal=True,
                transcript_close_signal=False,
                explicit_link_request=False,
            )
        )
        delivery_next_step = str(
            authority.get("delivery_next_step")
            or ""
        )
        text_calls = []

        def send_text(
            to_e164: str,
            text: str,
        ):
            text_calls.append(
                (to_e164, text),
            )
            return True, {"ok": True}

        attempted_1, sent_1, _ = (
            tasks._attempt_send_link_text_delivery(
                send_text_fn=send_text,
                to_e164="+5511999999999",
                text="https://www.meirobo.com.br",
                delivery_next_step=(
                    delivery_next_step
                ),
                already_sent=False,
            )
        )
        attempted_2, sent_2, _ = (
            tasks._attempt_send_link_text_delivery(
                send_text_fn=send_text,
                to_e164="+5511999999999",
                text="https://www.meirobo.com.br",
                delivery_next_step=(
                    delivery_next_step
                ),
                already_sent=sent_1,
            )
        )

        self.assertEqual(
            delivery_next_step,
            "SEND_LINK",
        )
        self.assertTrue(attempted_1)
        self.assertTrue(sent_1)
        self.assertFalse(attempted_2)
        self.assertTrue(sent_2)
        self.assertEqual(len(text_calls), 1)


if __name__ == "__main__":
    unittest.main()
