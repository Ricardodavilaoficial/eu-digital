import unittest

from services.ponte.whatsapp_web_local_adapter import (
    WHATSAPP_WEB_EVENT_TYPE,
    WHATSAPP_WEB_LOCAL_SIMULATION_CHANNEL,
    WHATSAPP_WEB_PLATFORM,
    build_base_vendedor_input,
    build_whatsapp_web_message_event,
    normalize_whatsapp_web_message,
    should_route_to_base_vendedor,
)


WHATSAPP_MESSAGE = {
    "client_authorization_ref": "cliente_piloto_autorizado_local",
    "chat_title": "Cliente Joao",
    "chat_type": "direct",
    "chat_identifier": "wa-chat-demo-001",
    "message_text": "Ola, voces fazem automacao para atendimento no WhatsApp?",
    "message_direction": "inbound",
    "message_timestamp": "2026-07-10T10:32:00-03:00",
    "message_index": 12,
    "sender_label": "Joao",
    "visible_phone_masked": "+55 ** *****-1234",
    "last_messages_context": [
        "Cliente: bom dia",
        "Operador: bom dia, como posso ajudar?",
        "Cliente: quero automatizar atendimento",
    ],
    "attachment_present": False,
    "audio_present": False,
    "unread_count": 1,
    "browser_session_id": "local-session-demo",
    "operator_note": "Mensagem simulada. Nao veio de WhatsApp real.",
}


class PonteWhatsappWebLocalAdapterTests(unittest.TestCase):
    def test_normalize_whatsapp_web_message_masks_chat_identifier(self):
        normalized = normalize_whatsapp_web_message(WHATSAPP_MESSAGE)

        self.assertEqual(normalized["chat_title"], "Cliente Joao")
        self.assertEqual(normalized["chat_type"], "direct")
        self.assertNotEqual(normalized["chat_identifier_hash"], "wa-chat-demo-001")
        self.assertEqual(len(normalized["chat_identifier_hash"]), 24)
        self.assertEqual(normalized["message_direction"], "inbound")
        self.assertEqual(normalized["unread_count"], 1)

    def test_build_whatsapp_web_message_event(self):
        event = build_whatsapp_web_message_event(WHATSAPP_MESSAGE)

        self.assertEqual(event["event_type"], WHATSAPP_WEB_EVENT_TYPE)
        self.assertEqual(event["source_platform"], WHATSAPP_WEB_PLATFORM)
        self.assertEqual(event["source_channel"], WHATSAPP_WEB_LOCAL_SIMULATION_CHANNEL)
        self.assertEqual(event["pilot_mode"], "LOCAL_SIMULATION")
        self.assertEqual(event["conversation_id"][:3], "ww:")
        self.assertEqual(len(event["dedupe_key"]), 24)
        self.assertTrue(event["route_to_base_vendedor"])

    def test_dedupe_key_is_stable_for_same_message(self):
        first = build_whatsapp_web_message_event(WHATSAPP_MESSAGE)
        second = build_whatsapp_web_message_event(WHATSAPP_MESSAGE)

        self.assertEqual(first["dedupe_key"], second["dedupe_key"])
        self.assertEqual(first["conversation_id"], second["conversation_id"])

    def test_policy_blocks_real_whatsapp_actions(self):
        event = build_whatsapp_web_message_event(WHATSAPP_MESSAGE)
        policy = event["permission_policy"]

        self.assertFalse(policy["can_read_whatsapp_web_real"])
        self.assertFalse(policy["can_open_browser"])
        self.assertFalse(policy["can_click"])
        self.assertFalse(policy["can_type"])
        self.assertFalse(policy["can_send_message"])
        self.assertFalse(policy["can_download_media"])
        self.assertFalse(policy["can_open_link"])
        self.assertTrue(policy["can_process_local_simulation"])
        self.assertTrue(policy["can_generate_suggested_reply"])
        self.assertTrue(policy["can_build_review_queue"])
        self.assertTrue(policy["requires_human_approval"])
        self.assertTrue(policy["dry_run"])

    def test_outbound_or_empty_messages_do_not_route_to_base_vendedor(self):
        outbound = dict(WHATSAPP_MESSAGE)
        outbound["message_direction"] = "outbound"
        outbound_event = build_whatsapp_web_message_event(outbound)
        self.assertFalse(should_route_to_base_vendedor(outbound_event))

        empty = dict(WHATSAPP_MESSAGE)
        empty["message_text"] = "   "
        empty_event = build_whatsapp_web_message_event(empty)
        self.assertFalse(should_route_to_base_vendedor(empty_event))

    def test_build_base_vendedor_input_keeps_constraints(self):
        event = build_whatsapp_web_message_event(WHATSAPP_MESSAGE)
        payload = build_base_vendedor_input(event)

        self.assertEqual(payload["source"], "ponte_whatsapp_web")
        self.assertEqual(payload["conversation_id"], event["conversation_id"])
        self.assertIn("automacao", payload["message_text"])
        self.assertTrue(payload["constraints"]["dry_run"])
        self.assertTrue(payload["constraints"]["requires_human_approval"])
        self.assertFalse(payload["constraints"]["can_send_message"])


if __name__ == "__main__":
    unittest.main()
