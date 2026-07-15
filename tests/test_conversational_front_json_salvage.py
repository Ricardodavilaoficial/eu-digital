from __future__ import annotations

import unittest

from services import conversational_front as front


class LenientFrontJsonTextSalvageTests(
    unittest.TestCase
):
    def test_valid_text_remains_unchanged(self) -> None:
        raw = (
            '{"replyText":"Direct answer preserved.",'
            '"nextStep":"NONE"}'
        )

        result = front._extract_lenient_json_text_field(
            raw,
            "replyText",
        )

        self.assertEqual(
            result,
            "Direct answer preserved.",
        )

    def test_unescaped_internal_quotes_are_preserved(
        self,
    ) -> None:
        raw = (
            '{"replyText":"The request was marked '
            '"urgent" and kept intact.",'
            '"nextStep":"NONE"}'
        )

        result = front._extract_lenient_json_text_field(
            raw,
            "replyText",
        )

        self.assertEqual(
            result,
            'The request was marked "urgent" '
            "and kept intact.",
        )

    def test_internal_quote_before_comma_is_preserved(
        self,
    ) -> None:
        raw = (
            '{"replyText":"The answer was "yes", '
            'then the data arrived.",'
            '"nextStep":"NONE"}'
        )

        result = front._extract_lenient_json_text_field(
            raw,
            "replyText",
        )

        self.assertEqual(
            result,
            'The answer was "yes", '
            "then the data arrived.",
        )

    def test_truncated_text_is_recovered(self) -> None:
        raw = (
            '{"replyText":"Response preserved '
            'without closing'
        )

        result = front._extract_lenient_json_text_field(
            raw,
            "replyText",
        )

        self.assertEqual(
            result,
            "Response preserved without closing",
        )

    def test_salvage_recovers_reply_and_spoken_text(
        self,
    ) -> None:
        raw = (
            '{"response_mode":"DIRECT",'
            '"understanding":{'
            '"topic":"OTHER",'
            '"confidence":"medium",'
            '"question_type":"punctual"},'
            '"nextStep":"NONE",'
            '"replyText":"Answer with "emphasis" '
            'preserved.",'
            '"spokenText":"Spoken "version" '
            'preserved."}'
        )

        result = front._salvage_free_mode_payload(raw)

        self.assertEqual(
            result["replyText"],
            'Answer with "emphasis" preserved.',
        )
        self.assertEqual(
            result["spokenText"],
            'Spoken "version" preserved.',
        )
        self.assertEqual(
            result["response_mode"],
            "DIRECT",
        )
        self.assertEqual(
            result["nextStep"],
            "NONE",
        )
        self.assertEqual(
            result["understanding"]["question_type"],
            "punctual",
        )

    def test_missing_comma_after_reply_is_not_leaked(
        self,
    ) -> None:
        raw = (
            '{"response_mode":"DIRECT",'
            '"replyText":"Direct answer preserved."'
            '"nextStep":"SEND_LINK"}'
        )

        result = front._salvage_free_mode_payload(raw)

        self.assertEqual(
            result["replyText"],
            "Direct answer preserved.",
        )
        self.assertEqual(
            result["spokenText"],
            "Direct answer preserved.",
        )
        self.assertEqual(
            result["nextStep"],
            "SEND_LINK",
        )

    def test_missing_comma_after_spoken_is_not_leaked(
        self,
    ) -> None:
        raw = (
            '{"response_mode":"DIRECT",'
            '"replyText":"Written answer preserved.",'
            '"spokenText":"Spoken answer preserved."'
            '"nextStep":"SEND_LINK"}'
        )

        result = front._salvage_free_mode_payload(raw)

        self.assertEqual(
            result["replyText"],
            "Written answer preserved.",
        )
        self.assertEqual(
            result["spokenText"],
            "Spoken answer preserved.",
        )
        self.assertEqual(
            result["nextStep"],
            "SEND_LINK",
        )

    def test_properly_escaped_quotes_are_decoded(
        self,
    ) -> None:
        raw = (
            '{"response_mode":"DIRECT",'
            '"replyText":"Answer with \\"quoted\\" '
            'value.","nextStep":"NONE"}'
        )

        result = front._salvage_free_mode_payload(raw)

        self.assertEqual(
            result["replyText"],
            'Answer with "quoted" value.',
        )
        self.assertEqual(
            result["spokenText"],
            'Answer with "quoted" value.',
        )
        self.assertEqual(
            result["nextStep"],
            "NONE",
        )

    def test_mensagem_alias_remains_supported(
        self,
    ) -> None:
        raw = (
            '{"response_mode":"DIRECT",'
            '"mensagem":"Fallback with "internal" '
            'quotes.","nextStep":"NONE"}'
        )

        result = front._salvage_free_mode_payload(raw)

        self.assertEqual(
            result["replyText"],
            'Fallback with "internal" quotes.',
        )
        self.assertEqual(
            result["spokenText"],
            'Fallback with "internal" quotes.',
        )
        self.assertEqual(
            result["response_mode"],
            "DIRECT",
        )

    def test_structural_fields_keep_strict_extractor(
        self,
    ) -> None:
        raw = (
            '{"response_mode":"DIRECT",'
            '"nextStep":"SEND_LINK",'
            '"lead_name":"NameTest",'
            '"lead_segment":"segment_test"}'
        )

        self.assertEqual(
            front._extract_json_string_field(
                raw,
                "response_mode",
            ),
            "DIRECT",
        )
        self.assertEqual(
            front._extract_json_string_field(
                raw,
                "nextStep",
            ),
            "SEND_LINK",
        )
        self.assertEqual(
            front._extract_json_string_field(
                raw,
                "lead_name",
            ),
            "NameTest",
        )
        self.assertEqual(
            front._extract_json_string_field(
                raw,
                "lead_segment",
            ),
            "segment_test",
        )


if __name__ == "__main__":
    unittest.main()
