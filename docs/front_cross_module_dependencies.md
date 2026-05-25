# Front Cross Module Dependency Audit

Objetivo: detectar micro-clusters coesos para extração segura.

## front_utils

### _normalize_response_mode
- lines: 6
- called_by: _salvage_free_mode_payload, handle
- calls: str, strip, upper
- globals: none
- raises: False

### _clean_scene_text
- lines: 12
- called_by: none
- calls: rstrip, str, strip, sub
- globals: none
- raises: False

### _tokenize_lookup_text
- lines: 16
- called_by: _infer_segment_from_text, _lookup_token_overlap_score
- calls: _normalize_lookup_key, findall, len, replace
- globals: none
- raises: False

### _de_genericize_free_mode_text
- lines: 16
- called_by: handle
- calls: str, strip, sub
- globals: none
- raises: False

### _collect_doc_texts
- lines: 18
- called_by: _score_query_against_doc
- calls: _iter_doc_text_fragments, add, append, isinstance, lower, set, str, strip, sub
- globals: none
- raises: False

### _normalize_lookup_key
- lines: 20
- called_by: _front_build_continuity_reply_from_platform_kb, _infer_segment_from_text, _keyword_doc_match, _lookup_token_overlap_score, _platform_kb_resolve_runtime, _platform_segment_profile_from_kb, _platform_topic_from_kb_rules, _tokenize_lookup_text, handle
- calls: items, lower, replace, str, strip, sub
- globals: none
- raises: False

### _split_user_operational_clauses
- lines: 30
- called_by: _build_user_operational_seed
- calls: append, len, replace, split, str, strip, sub
- globals: none
- raises: False

### _front_extract_declared_segment_from_user_text
- lines: 33
- called_by: handle
- calls: group, search, str, strip
- globals: none
- raises: False

### _iter_doc_text_fragments
- lines: 34
- called_by: _collect_doc_texts, _iter_doc_text_fragments
- calls: _iter_doc_text_fragments, isinstance, items, lower, str, strip
- globals: none
- raises: False

### _kb_get_process_sla_text
- lines: 35
- called_by: _sanitize_unverified_time_claims
- calls: get, isinstance, lower, str, strip
- globals: none
- raises: False

### _lookup_token_overlap_score
- lines: 38
- called_by: _best_lookup_key_match, _score_query_against_doc
- calls: _base, _normalize_lookup_key, _tokenize_lookup_text, endswith, intersection, len, max, replace, set, str, strip
- globals: none
- raises: False

### _parse_free_mode_text_response
- lines: 47
- called_by: handle
- calls: _sanitize_user_facing_reply, lower, str, strip, sub, upper
- globals: none
- raises: False

### _doc_identity_is_compatible_with_current_text
- lines: 54
- called_by: _clear_incompatible_kb_context_for_current_text, _infer_segment_from_docs, handle
- calls: _score_query_against_doc, get, int, isinstance, str, strip
- globals: none
- raises: False

### _humanize_reply_with_lead_context
- lines: 76
- called_by: _front_build_structured_assembly_reply, handle
- calls: _call_openai_for_front, _reply_has_lead_context, _sanitize_user_facing_reply, lower, str, strip, sub
- globals: none
- raises: False

### _clear_incompatible_kb_context_for_current_text
- lines: 87
- called_by: handle
- calls: _doc_identity_is_compatible_with_current_text, _find_kb_map_anywhere, dict, get, isinstance, loads, lower, pop, startswith, str, strip
- globals: none
- raises: False

### _infer_segment_from_text
- lines: 126
- called_by: handle
- calls: _best_doc_match, _find_kb_map_anywhere, _key_matches_text, _keyword_doc_match, _norm, _normalize_lookup_key, _tokenize_lookup_text, any, append, commonprefix, dumps, extend, isinstance, items, keys, len, loads, lower, lstrip, replace, startswith, str, strip
- globals: none
- raises: False

### _merge_real_kb_operational_context
- lines: 199
- called_by: handle
- calls: _derive_ritual_from_scene, _pick, bool, dict, get, isinstance, str, strip
- globals: none
- raises: False

## front_guards

### _drop_explanatory_opening
- lines: 14
- called_by: _generate_micro_scene_with_model, _upgrade_operational_reply_with_model
- calls: _looks_explanatory_sentence, _split_sentences_pt, join, str, strip
- globals: none
- raises: False

## front_assembly

### _build_free_mode_family_hint
- lines: 6
- called_by: handle
- calls: none
- globals: none
- raises: False

### _build_contract_consequence
- lines: 9
- called_by: handle
- calls: _generate_consequence_with_model
- globals: none
- raises: False

### _reply_mentions_name_request
- lines: 10
- called_by: _front_identity_request_is_valid
- calls: bool, lower, search, str, strip
- globals: none
- raises: False

### _segment_micro_flow
- lines: 12
- called_by: none
- calls: _pack_practical_add, _segment_reference_example, rstrip, strip
- globals: none
- raises: False

### _contract_allows_scene_runtime
- lines: 13
- called_by: _build_kb_anchor_reply, _build_kb_show_reply, _build_last_resort_operational_reply, _build_structural_last_resort_reply, _compose_grounded_scene_with_progression, _resolve_best_operational_reply
- calls: bool, get, isinstance, str, strip, upper
- globals: none
- raises: False

### _drop_abstract_closing
- lines: 14
- called_by: _generate_micro_scene_with_model, _upgrade_operational_reply_with_model
- calls: _looks_explanatory_sentence, _split_sentences_pt, join, len, str, strip
- globals: none
- raises: False

### _compose_pack_runtime_short_reply
- lines: 17
- called_by: _platform_kb_resolve_runtime, _platform_pack_material
- calls: append, get, isinstance, join, rstrip, str, strip
- globals: none
- raises: False

### _front_build_identity_request
- lines: 18
- called_by: handle
- calls: append, bool, join
- globals: none
- raises: False

### _compose_practical_scene
- lines: 22
- called_by: _refresh_operational_anchor, handle
- calls: _kb_get_micro_scene, _kb_get_reference_example, append, join, lower, rstrip, startswith, strip
- globals: none
- raises: False

### _merge_value_and_scene
- lines: 22
- called_by: handle
- calls: append, join, len, rstrip, strip
- globals: none
- raises: False

### _resolve_tone_hint
- lines: 31
- called_by: _generate_style_intro_with_model
- calls: get, isinstance, str, strip
- globals: none
- raises: False

### _build_user_operational_seed
- lines: 33
- called_by: none
- calls: _split_user_operational_clauses, add, append, join, len, lower, set, str, strip, sub
- globals: none
- raises: False

### _build_scene_hint_block
- lines: 35
- called_by: handle
- calls: append, join, str, strip
- globals: none
- raises: False

### _build_user_scene_block
- lines: 35
- called_by: handle
- calls: append, join, str, strip
- globals: none
- raises: False

### _extract_intro_hint_from_model_reply
- lines: 39
- called_by: _build_direct_scene_payload
- calls: len, lower, split, str, strip, sub
- globals: none
- raises: False

### _kb_get_micro_scene
- lines: 40
- called_by: _compose_practical_scene, handle
- calls: get, isinstance, loads, lstrip, startswith, str, strip, upper
- globals: none
- raises: False

### _expand_scene_steps
- lines: 47
- called_by: none
- calls: _split_scene_steps, _strip_scene_narrator, add, append, dict, extend, get, isinstance, lower, set, str, strip, sub
- globals: none
- raises: False

### _build_last_resort_operational_reply
- lines: 52
- called_by: _build_kb_anchor_reply, _build_kb_show_reply
- calls: _compose_grounded_scene_with_progression, _contract_allows_scene_runtime, _generate_micro_scene_with_model, _is_live_operational_reply, _sanitize_user_facing_reply, _stabilize_scene_base, dict, rstrip, str, strip, sub
- globals: none
- raises: False

### _front_build_price_facts_block
- lines: 53
- called_by: handle
- calls: _front_fmt_brl_from_cents, _front_get_platform_pricing, append, get, isinstance, join, str, strip
- globals: none
- raises: False

### _select_structured_scene_steps
- lines: 55
- called_by: _build_structural_last_resort_reply, _compose_grounded_scene_with_progression, _expand_structural_steps_from_contract_with_model, _generate_micro_scene_with_model
- calls: _split_scene_steps, _strip_scene_narrator, add, append, dict, get, isinstance, len, lower, set, str, strip, sub
- globals: none
- raises: False

### _build_structural_last_resort_reply
- lines: 55
- called_by: handle
- calls: _contract_allows_scene_runtime, _expand_structural_steps_from_contract_with_model, _is_scene_echo, _render_progressive_operational_flow, _sanitize_user_facing_reply, _select_structured_scene_steps, _stabilize_scene_base, add, append, dict, get, len, lower, set, str, strip, sub
- globals: none
- raises: False

### _build_kb_anchor_reply
- lines: 60
- called_by: _resolve_best_operational_reply, handle
- calls: _build_last_resort_operational_reply, _compose_grounded_scene_with_progression, _contract_allows_scene_runtime, _generate_micro_scene_with_model, _is_live_operational_reply, _sanitize_user_facing_reply, _stabilize_scene_base, rstrip, str, strip, sub
- globals: none
- raises: False

### _build_kb_show_reply
- lines: 60
- called_by: _resolve_best_operational_reply, handle
- calls: _build_last_resort_operational_reply, _compose_grounded_scene_with_progression, _contract_allows_scene_runtime, _generate_micro_scene_with_model, _is_show_micro_scene, _sanitize_user_facing_reply, _stabilize_scene_base, rstrip, str, strip, sub
- globals: none
- raises: False

### _compose_pack_runtime_compact_reply
- lines: 63
- called_by: _platform_kb_resolve_runtime, _platform_pack_material
- calls: append, get, isinstance, join, replace, rstrip, str, strip, sub
- globals: none
- raises: False

### _front_repair_price_reply
- lines: 67
- called_by: handle
- calls: _front_fmt_brl_from_cents, _front_get_platform_pricing, append, get, isinstance, join, str, strip
- globals: none
- raises: False

### _upgrade_operational_reply_with_model
- lines: 68
- called_by: handle
- calls: _call_openai_for_front, _drop_abstract_closing, _drop_explanatory_opening, _sanitize_user_facing_reply, dumps, get, str, strip, sub
- globals: none
- raises: False

### _generate_style_intro_with_model
- lines: 70
- called_by: _build_direct_scene_payload
- calls: _call_openai_for_front, _resolve_tone_hint, len, str, strip, sub
- globals: none
- raises: False

### _build_direct_sales_reply_with_model
- lines: 85
- called_by: _build_direct_scene_payload
- calls: _call_openai_for_front, _looks_like_technical_output, len, rsplit, str, strip, sub
- globals: none
- raises: False

### _build_direct_scene_payload
- lines: 110
- called_by: handle
- calls: _build_direct_sales_reply_with_model, _extract_intro_hint_from_model_reply, _generate_style_intro_with_model, _humanize_scene_flow, bool, dict, endswith, get, str, strip, sub, upper
- globals: none
- raises: False

### _resolve_best_operational_reply
- lines: 141
- called_by: none
- calls: _audit_operational_reply, _build_kb_anchor_reply, _build_kb_show_reply, _compose_grounded_scene_with_progression, _contract_allows_scene_runtime, _generate_micro_scene_with_model, _is_live_operational_reply, _is_scene_echo, _looks_explanatory_reply, _refresh_operational_anchor, bool, get, isinstance, join, len, str, strip
- globals: none
- raises: False

### _front_build_structured_assembly_reply
- lines: 142
- called_by: handle
- calls: _front_platform_pack_content, _front_structured_doc_content, _humanize_reply_with_lead_context, _sanitize_user_facing_reply, _unwrap_front_json_envelope, bool, get, info, int, isinstance, len, lower, min, str, strip, upper
- globals: none
- raises: False

### _compose_grounded_scene_with_progression
- lines: 149
- called_by: _build_kb_anchor_reply, _build_kb_show_reply, _build_last_resort_operational_reply, _generate_micro_scene_with_model, _resolve_best_operational_reply, handle
- calls: _contract_allows_scene_runtime, _expand_structural_steps_from_contract_with_model, _is_scene_echo, _is_semantic_duplicate, _phase_signature, _render_progressive_operational_flow, _sanitize_user_facing_reply, _select_structured_scene_steps, _semantic_key, _stabilize_scene_base, _strip_subject, add, append, bool, dict, findall, get, isinstance, join, len, lower, max, rstrip, set, sorted, str, strip, sub
- globals: none
- raises: False

### _generate_micro_scene_with_model
- lines: 215
- called_by: _build_kb_anchor_reply, _build_kb_show_reply, _build_last_resort_operational_reply, _resolve_best_operational_reply, handle
- calls: _compose_grounded_scene_with_progression, _derive_ritual_from_scene, _drop_abstract_closing, _drop_explanatory_opening, _heal_algorithmic_micro_scene, _is_live_operational_reply, _looks_explanatory_reply, _looks_like_dialogue_stub, _looks_like_technical_output, _operational_density_score, _operational_progress_score, _render_progressive_operational_flow, _sanitize_user_facing_reply, _select_structured_scene_steps, _split_sentences_pt, append, bool, create, dict, dumps, findall, get, isinstance, join, len, lower, max, pop, rstrip, str, strip, sub, upper
- globals: none
- raises: False

### _front_build_continuity_reply_from_platform_kb
- lines: 233
- called_by: handle
- calls: _block_text, _clean_fact, _front_sanitize_lead_name_candidate, _front_trim_free_mode_sentence, _normalize_lookup_key, _pack_runtime_short, _pick_pack_for_intent, _platform_get_map, add, append, bool, extend, get, int, isinstance, join, len, set, split, str, strip, upper
- globals: none
- raises: False

### _build_operational_contract
- lines: 282
- called_by: handle
- calls: _derive_ritual_from_scene, _kb_lookup_operational_docs, _pick_str, bool, get, isinstance, lower, str, strip, upper
- globals: none
- raises: False

## front_kb

### _compact_kb_snapshot
- lines: 12
- called_by: _prepare_kb_snapshot_buffers
- calls: strip, sub
- globals: none
- raises: False

### _kb_context_segment_was_cleared
- lines: 13
- called_by: handle
- calls: get, str, strip
- globals: none
- raises: False

### _front_get_platform_pricing
- lines: 17
- called_by: _front_build_price_facts_block, _front_repair_price_reply
- calls: _front_fs_client, collection, document, get, isinstance, to_dict
- globals: none
- raises: False

### _best_lookup_key_match
- lines: 21
- called_by: _infer_segment_from_docs, _kb_lookup_operational_docs
- calls: _lookup_token_overlap_score, str, strip
- globals: none
- raises: False

### _platform_get_map
- lines: 23
- called_by: _front_build_continuity_reply_from_platform_kb, _platform_kb_resolve_runtime, _platform_pack_from_profile, _platform_pack_material, _platform_segment_profile_from_kb, _platform_topic_from_kb_rules
- calls: _find_kb_map_anywhere, get, isinstance
- globals: none
- raises: False

### _best_doc_match
- lines: 25
- called_by: _infer_segment_from_docs, _infer_segment_from_text, _kb_lookup_operational_docs
- calls: _score_query_against_doc, isinstance, items, str, strip
- globals: none
- raises: False

### _kb_get_pack_runtime_short
- lines: 25
- called_by: none
- calls: get, isinstance, loads, lstrip, startswith, str, strip, upper
- globals: none
- raises: False

### _platform_topic_from_kb_rules
- lines: 26
- called_by: _resolve_canonical_topic, handle
- calls: _normalize_lookup_key, _platform_get_map, get, isinstance, str, strip, upper
- globals: none
- raises: False

### _segment_reference_example
- lines: 27
- called_by: _segment_micro_flow
- calls: get, isinstance, lower, str, strip, upper
- globals: none
- raises: False

### _find_kb_map_anywhere
- lines: 28
- called_by: _clear_incompatible_kb_context_for_current_text, _find_kb_map_anywhere, _infer_segment_from_docs, _infer_segment_from_text, _kb_lookup_operational_docs, _platform_get_map
- calls: _find_kb_map_anywhere, get, isinstance, items
- globals: none
- raises: False

### _platform_segment_profile_from_kb
- lines: 28
- called_by: handle
- calls: _normalize_lookup_key, _platform_get_map, isinstance, items, join, str, strip
- globals: none
- raises: False

### _score_query_against_doc
- lines: 30
- called_by: _best_doc_match, _doc_identity_is_compatible_with_current_text
- calls: _collect_doc_texts, _lookup_token_overlap_score, append, get, isinstance, max, str, strip
- globals: none
- raises: False

### _prepare_kb_snapshot_buffers
- lines: 31
- called_by: handle
- calls: _compact_kb_snapshot, _truncate, isinstance, loads, startswith, str, strip
- globals: none
- raises: False

### _has_strong_kb_anchor
- lines: 33
- called_by: handle
- calls: get, str, strip
- globals: none
- raises: False

### _platform_apply_slots
- lines: 35
- called_by: _platform_kb_resolve_runtime, _platform_pack_material
- calls: get, isinstance, items, replace, str, strip, sub
- globals: none
- raises: False

### _keyword_doc_match
- lines: 38
- called_by: _infer_segment_from_docs, _infer_segment_from_text
- calls: _normalize_lookup_key, escape, get, isinstance, items, len, replace, search, str, strip, sub
- globals: none
- raises: False

### _platform_pack_from_profile
- lines: 45
- called_by: handle
- calls: _pick_pack_for_intent, _platform_get_map, get, isinstance, str, strip, upper
- globals: none
- raises: False

### _kb_get_segment_scene
- lines: 54
- called_by: _refresh_operational_anchor, handle
- calls: get, isinstance, join, loads, lower, lstrip, rstrip, startswith, str, strip
- globals: none
- raises: False

### _preferred_topic_from_kb
- lines: 61
- called_by: handle
- calls: get, lower, str, strip, upper
- globals: none
- raises: False

### _infer_segment_from_docs
- lines: 77
- called_by: handle
- calls: _best_doc_match, _best_lookup_key_match, _doc_identity_is_compatible_with_current_text, _find_kb_map_anywhere, _keyword_doc_match, extend, get, isinstance, join, keys, loads, lower, startswith, str, strip
- globals: none
- raises: False

### _front_platform_pack_content
- lines: 85
- called_by: _front_build_structured_assembly_reply
- calls: _front_first_text, _platform_pack_material, append, get, isinstance, join, str, strip, upper
- globals: none
- raises: False

### _front_structured_doc_content
- lines: 86
- called_by: _front_build_structured_assembly_reply
- calls: _front_first_text, append, bool, get, isinstance, join, strip
- globals: none
- raises: False

### _kb_get_reference_example
- lines: 88
- called_by: _compose_practical_scene, _refresh_operational_anchor, handle
- calls: endswith, find, get, group, isinstance, len, loads, lower, lstrip, search, splitlines, startswith, str, strip, sub
- globals: none
- raises: False

### _platform_pack_material
- lines: 104
- called_by: _front_platform_pack_content, handle
- calls: _compose_pack_runtime_compact_reply, _compose_pack_runtime_short_reply, _platform_apply_slots, _platform_get_map, get, isinstance, str, strip, upper
- globals: none
- raises: False

### _platform_kb_resolve_runtime
- lines: 180
- called_by: handle
- calls: _compose_pack_runtime_compact_reply, _compose_pack_runtime_short_reply, _normalize_lookup_key, _pick_pack_for_intent, _platform_apply_slots, _platform_get_map, get, isinstance, items, join, str, strip, upper
- globals: none
- raises: False

### _kb_lookup_operational_docs
- lines: 182
- called_by: _build_operational_contract, handle
- calls: _best_doc_match, _best_lookup_key_match, _find_kb_map_anywhere, bool, get, info, isinstance, items, join, keys, len, list, loads, lower, replace, startswith, str, strip, warning
- globals: none
- raises: False
