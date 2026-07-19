from __future__ import annotations

import ast
import unittest
from pathlib import Path
from typing import List, Set


ROOT = Path(__file__).resolve().parents[1]
ROUTE_PATH = ROOT / "routes" / "ycloud_tasks_bp.py"


class YCloudAudioSendLinkWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.full_source = ROUTE_PATH.read_text(
            encoding="utf-8",
        )

        tree = ast.parse(
            cls.full_source,
        )

        workers = [
            node
            for node in ast.walk(tree)
            if isinstance(
                node,
                (
                    ast.FunctionDef,
                    ast.AsyncFunctionDef,
                ),
            )
            and node.name
            == "_ycloud_inbound_worker_impl"
        ]

        if len(workers) != 1:
            raise AssertionError(
                "Esperava exatamente uma função "
                "_ycloud_inbound_worker_impl."
            )

        cls.worker = workers[0]

        cls.parents = {}

        for parent in ast.walk(cls.worker):
            for child in ast.iter_child_nodes(
                parent,
            ):
                cls.parents[child] = parent

    @classmethod
    def _source(
        cls,
        node: ast.AST,
    ) -> str:
        return (
            ast.get_source_segment(
                cls.full_source,
                node,
            )
            or ""
        )

    @classmethod
    def _assignment_values(
        cls,
        variable_name: str,
    ) -> List[ast.AST]:
        values: List[ast.AST] = []

        for node in ast.walk(cls.worker):
            if isinstance(node, ast.Assign):
                targets = node.targets

                if any(
                    isinstance(target, ast.Name)
                    and target.id == variable_name
                    for target in targets
                ):
                    values.append(
                        node.value,
                    )

            elif isinstance(
                node,
                ast.AnnAssign,
            ):
                target = node.target

                if (
                    isinstance(target, ast.Name)
                    and target.id == variable_name
                    and node.value is not None
                ):
                    values.append(
                        node.value,
                    )

        return values

    @classmethod
    def _authority_get_keys(
        cls,
    ) -> Set[str]:
        keys: Set[str] = set()

        for node in ast.walk(cls.worker):
            if not isinstance(node, ast.Call):
                continue

            func = node.func

            if not (
                isinstance(func, ast.Attribute)
                and func.attr == "get"
                and node.args
            ):
                continue

            first_arg = node.args[0]

            if not (
                isinstance(first_arg, ast.Constant)
                and isinstance(
                    first_arg.value,
                    str,
                )
            ):
                continue

            uses_authority = any(
                isinstance(inner, ast.Name)
                and inner.id
                == "_send_link_authority"
                for inner in ast.walk(
                    func.value,
                )
            )

            if uses_authority:
                keys.add(
                    first_arg.value,
                )

        return keys

    @classmethod
    def _route_guard_source(
        cls,
        route_name: str,
    ) -> str:
        matching_calls = []

        for node in ast.walk(cls.worker):
            if not isinstance(node, ast.Call):
                continue

            func = node.func

            if not (
                isinstance(func, ast.Name)
                and func.id
                == "_wa_log_outbox_deterministic"
            ):
                continue

            route_value = None

            for keyword in node.keywords:
                if keyword.arg != "route":
                    continue

                if isinstance(
                    keyword.value,
                    ast.Constant,
                ):
                    route_value = (
                        keyword.value.value
                    )

            if route_value == route_name:
                matching_calls.append(
                    node,
                )

        if len(matching_calls) != 1:
            raise AssertionError(
                f"Esperava exatamente uma chamada "
                f"para a rota {route_name!r}; "
                f"encontrei {len(matching_calls)}."
            )

        current = matching_calls[0]
        guards = []

        while current in cls.parents:
            current = cls.parents[current]

            if isinstance(current, ast.If):
                guards.append(
                    cls._source(
                        current.test,
                    )
                )

        return "\n".join(
            guards,
        )

    def test_worker_resolves_authority_once(
        self,
    ) -> None:
        calls = [
            node
            for node in ast.walk(
                self.worker,
            )
            if isinstance(node, ast.Call)
            and isinstance(
                node.func,
                ast.Name,
            )
            and node.func.id
            == "_resolve_sales_send_link_authority"
        ]

        self.assertEqual(
            len(calls),
            1,
            msg=(
                "O worker deve resolver a autoridade "
                "uma única vez por turno."
            ),
        )

    def test_authority_outputs_drive_runtime_gates(
        self,
    ) -> None:
        authority_keys = (
            self._authority_get_keys()
        )

        self.assertTrue(
            {
                "delivery_next_step",
                "send_link_authorized",
                "close_signal",
                "allow_explicit_cta",
            }.issubset(
                authority_keys,
            ),
            msg=(
                "Nem todos os gates consultam a "
                "autoridade estrutural."
            ),
        )

        force_values = (
            self._assignment_values(
                "force_send_link_text",
            )
        )

        self.assertTrue(
            any(
                "_send_link_authority"
                in self._source(value)
                and "send_link_authorized"
                in self._source(value)
                for value in force_values
            ),
            msg=(
                "force_send_link_text não está ligado "
                "a send_link_authorized."
            ),
        )

        global_values = (
            self._assignment_values(
                "close_heur_global",
            )
        )

        self.assertTrue(
            any(
                "_send_link_authority"
                in self._source(value)
                and "close_signal"
                in self._source(value)
                for value in global_values
            ),
            msg=(
                "close_heur_global não está ligado "
                "à autoridade."
            ),
        )

        close2_values = (
            self._assignment_values(
                "close_heur2",
            )
        )

        self.assertTrue(
            any(
                "_send_link_authority"
                in self._source(value)
                and "close_signal"
                in self._source(value)
                for value in close2_values
            ),
            msg=(
                "close_heur2 não está ligado "
                "à autoridade."
            ),
        )

        direct_close_assignments = 0

        for value in self._assignment_values(
            "is_close_signal",
        ):
            source = self._source(
                value,
            )

            if (
                "_send_link_authority"
                in source
                and "close_signal"
                in source
            ):
                direct_close_assignments += 1

        self.assertGreaterEqual(
            direct_close_assignments,
            2,
            msg=(
                "Os dois blocos principais de "
                "is_close_signal devem consultar "
                "a autoridade."
            ),
        )

    def test_fallback_and_telemetry_use_delivery_authority(
        self,
    ) -> None:
        delivery_values = (
            self._assignment_values(
                "_delivery_next_step",
            )
        )

        self.assertTrue(
            any(
                "_send_link_authority"
                in self._source(value)
                and "delivery_next_step"
                in self._source(value)
                for value in delivery_values
            ),
            msg=(
                "_delivery_next_step não está ligado "
                "à autoridade estrutural."
            ),
        )

        for variable_name in (
            "ia_next_step",
            "_ia_next",
        ):
            values = (
                self._assignment_values(
                    variable_name,
                )
            )

            self.assertTrue(
                any(
                    "_delivery_next_step"
                    in self._source(value)
                    for value in values
                ),
                msg=(
                    f"{variable_name} não usa "
                    "_delivery_next_step."
                ),
            )

            self.assertFalse(
                any(
                    "understanding"
                    in self._source(value)
                    and "next_step"
                    in self._source(value)
                    for value in values
                ),
                msg=(
                    f"{variable_name} ainda lê "
                    "understanding.next_step diretamente."
                ),
            )

        ensure_calls = [
            node
            for node in ast.walk(
                self.worker,
            )
            if isinstance(node, ast.Call)
            and isinstance(
                node.func,
                ast.Name,
            )
            and node.func.id
            == "_ensure_send_link_in_reply"
        ]

        second_arguments = [
            self._source(
                node.args[1],
            )
            for node in ensure_calls
            if len(node.args) >= 2
        ]

        self.assertIn(
            "_delivery_next_step",
            second_arguments,
            msg=(
                "O fallthrough não usa "
                "_delivery_next_step."
            ),
        )

        self.assertNotIn(
            "ia_next_step",
            second_arguments,
            msg=(
                "O fallthrough ainda depende do "
                "next step secundário antigo."
            ),
        )

    def test_every_link_send_path_has_guard(
        self,
    ) -> None:
        audio_plus_text = (
            self._route_guard_source(
                "send_text_audio_plus_text_link"
            )
        )

        self.assertIn(
            "audio_plus_text_link",
            audio_plus_text,
        )

        forced_link = (
            self._route_guard_source(
                "send_text_force_link"
            )
        )

        self.assertIn(
            "force_send_link_text",
            forced_link,
        )

        explicit_cta = (
            self._route_guard_source(
                "send_text_site_cta"
            )
        )

        self.assertIn(
            "allow_explicit_cta",
            explicit_cta,
        )

        self.assertIn(
            "explicit_link_request",
            explicit_cta,
        )

        close_after_audio = (
            self._route_guard_source(
                "send_text_close_after_audio"
            )
        )

        self.assertIn(
            "close_heur2",
            close_after_audio,
        )

    def test_send_link_retry_tracks_text_delivery_separately(
        self,
    ) -> None:
        worker_source = self._source(
            self.worker,
        )

        helper_calls = [
            node
            for node in ast.walk(
                self.worker,
            )
            if isinstance(node, ast.Call)
            and isinstance(
                node.func,
                ast.Name,
            )
            and node.func.id
            == "_attempt_send_link_text_delivery"
        ]

        self.assertGreaterEqual(
            len(helper_calls),
            4,
            msg=(
                "Os envios principal e fallback de link "
                "devem compartilhar o gate de entrega."
            ),
        )
        self.assertIn(
            "link_text_sent = False",
            worker_source,
        )
        self.assertIn(
            "_send_link_delivery_pending",
            worker_source,
        )
        self.assertIn(
            "and not link_text_sent",
            worker_source,
        )
        self.assertIn(
            "bool(sent_ok) and not (",
            worker_source,
            msg=(
                "O ACK não pode encerrar o fallthrough "
                "quando o texto SEND_LINK está pendente."
            ),
        )
        self.assertIn(
            "_rt_fallback",
            worker_source,
            msg=(
                "O fallthrough deve tentar apenas o texto "
                "pendente, sem repetir o áudio."
            ),
        )
        self.assertIn(
            "_text_contains_send_link_platform_url",
            worker_source,
            msg=(
                "Os envios genéricos precisam provar que o "
                "payload contém a URL própria antes de marcar "
                "link_text_sent."
            ),
        )

    def test_worker_reports_send_link_contract_state(
        self,
    ) -> None:
        worker_source = self._source(
            self.worker,
        )

        response_calls = [
            node
            for node in ast.walk(self.worker)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id
            == "_build_worker_delivery_response"
        ]

        self.assertGreaterEqual(
            len(response_calls),
            4,
            msg=(
                "Early return, retorno normal e fallthrough "
                "devem usar a mesma semântica de contrato."
            ),
        )
        self.assertIn(
            '"linkTextSent": bool(link_text_sent)',
            worker_source,
        )
        self.assertIn(
            '"sendLinkPending": bool(',
            worker_source,
        )
        self.assertIn(
            "_normal_send_link_pending",
            worker_source,
            msg=(
                "O retorno normal de áudio não pode encerrar "
                "SEND_LINK ainda pendente."
            ),
        )

    def test_parallel_legacy_resurrections_are_removed(
        self,
    ) -> None:
        worker_source = self._source(
            self.worker,
        )

        forbidden = (
            "close_words_g",
            "close_words2",
            'intent_final == "ACTIVATE"',
            '_intent == "ACTIVATE"',
            (
                'plan_next_step in '
                '("SEND_LINK", "CTA", "EXIT")'
            ),
        )

        for fragment in forbidden:
            with self.subTest(
                fragment=fragment,
            ):
                self.assertNotIn(
                    fragment,
                    worker_source,
                )


if __name__ == "__main__":
    unittest.main()
