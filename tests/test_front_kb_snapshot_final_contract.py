import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import services.wa_bot as w


class _Patch:
    def __init__(self, target, **values):
        self.target = target
        self.values = values
        self.old = {}

    def __enter__(self):
        for name, value in self.values.items():
            self.old[name] = getattr(self.target, name)
            setattr(self.target, name, value)
        return self

    def __exit__(self, exc_type, exc, tb):
        for name, value in self.old.items():
            setattr(self.target, name, value)
        return False


def _base_kb() -> dict:
    return {
        "answer_playbook_v1": {
            "runtime_selector_v1": {
                "mode": "packs_v1",
                "priority_order": [
                    "value_packs_v1",
                    "segment_value_map_v1",
                    "pack_selection_policy_v1",
                ],
                "fallback_allowed": True,
            },
            "pack_selection_policy_v1": {"max_packs_per_response": 1},
            "segment_template_v1": {"template": "x" * 800},
            "segment_value_map_v1": {
                "segmento_sintetico": {"tokens": {"OTHER": {"x": "y" * 800}}}
            },
        },
        "value_packs_v1": {
            "PACK_SYNTH": {
                "label": "Pacote sintético",
                "runtime_short": {
                    "value_one_liner": "Valor sintético vindo da fixture.",
                    "micro_scene_conversational": "Cena sintética vinda da fixture.",
                },
                "runtime_long": {"text": "z" * 4000},
            }
        },
        "process_facts": {"fact": "p" * 2000},
    }


def _selected_sources() -> dict:
    return {
        "kb": _base_kb(),
        "pricing": {"notes": "n" * 1000},
        "segments": {
            "segmento_sintetico": {
                "id": "segmento_sintetico",
                "name": "Segmento Sintético",
                "one_liner": "Linha sintética do segmento.",
            }
        },
        "archetypes": {
            "arquetipo_sintetico": {
                "id": "arquetipo_sintetico",
                "name": "Arquétipo Sintético",
                "one_liner": "Linha sintética do arquétipo.",
            }
        },
        "subsegments": {
            "segmento_sintetico__subalvo": {
                "id": "segmento_sintetico__subalvo",
                "name": "Subalvo Sintético",
                "segment_id": "segmento_sintetico",
                "archetype_id": "arquetipo_sintetico",
                "routing_identity_anchors": ["marcador alfa"],
                "routing_negative_anchors": ["marcador beta"],
                "one_liner": "Linha sintética do subalvo.",
                "micro_scene_conversational": (
                    "Microcena sintética extensa vinda da fixture para validar "
                    "que o contrato hidratável sobrevive até a string final."
                ),
                "snapshot_priority": {"keep": ["micro_scene_conversational"]},
                "commercial_runtime": {"summary": "Resumo sintético."},
                "operational_runtime": {"summary": "Operação sintética."},
            },
            "segmento_sintetico__outro": {
                "id": "segmento_sintetico__outro",
                "name": "Outro Subalvo Sintético",
                "segment_id": "segmento_sintetico",
                "archetype_id": "arquetipo_sintetico",
                "routing_identity_anchors": ["marcador beta"],
                "routing_negative_anchors": ["marcador alfa"],
            },
        },
    }


def _generic_sources() -> dict:
    return {
        "kb": {
            "answer_playbook_v1": {
                "runtime_selector_v1": {"mode": "packs_v1"},
            },
            "value_packs_v1": {
                "PACK_SYNTH": {
                    "label": "Pacote sintético",
                    "runtime_short": {
                        "value_one_liner": "Valor sintético vindo da fixture.",
                    },
                }
            },
        },
        "pricing": {},
        "segments": {},
        "archetypes": {},
        "subsegments": {},
    }


def _snapshot(sources: dict, text: str, limit: int = 1400) -> dict:
    with _Patch(
        w,
        _fetch_front_kb_sources=lambda: sources,
        FRONT_KB_MAX_CHARS_PACKS_V1=limit,
    ):
        raw = w._build_front_kb_snapshot("OTHER", user_text=text)
    data = json.loads(raw)
    assert "_protected_subsegment_ids" not in data
    return data


def test_final_snapshot_preserves_selected_subsegment_and_existing_parents():
    data = _snapshot(_selected_sources(), "mensagem com marcador alfa")

    subs = data.get("kb_subsegments_v1") or {}
    segs = data.get("kb_segments_v1") or {}
    archs = data.get("kb_archetypes_v1") or {}

    assert set(subs) == {"segmento_sintetico__subalvo"}
    sub_doc = subs["segmento_sintetico__subalvo"]
    assert sub_doc.get("micro_scene_conversational")
    assert sub_doc.get("segment_id") in segs
    assert sub_doc.get("archetype_id") in archs
    assert json.dumps(data, ensure_ascii=False, separators=(",", ":")) != "{}"


def test_final_snapshot_without_selected_subsegment_does_not_invent_one():
    data = _snapshot(_generic_sources(), "mensagem sem ancora compatível")

    assert data.get("kb_subsegments_v1") == {}
    assert data.get("value_packs_v1")


def main():
    test_final_snapshot_preserves_selected_subsegment_and_existing_parents()
    test_final_snapshot_without_selected_subsegment_does_not_invent_one()
    print("test_front_kb_snapshot_final_contract ok")


if __name__ == "__main__":
    main()
