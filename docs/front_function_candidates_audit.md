# Front Function Candidates Audit

Critério: candidatas pequenas, sem chamada direta por handle, sem global/nonlocal, e sem nomes perigosos.

## _resolve_tone_hint
- lines: 31
- called_by: _generate_style_intro_with_model
- calls: get, isinstance, str, strip

## _front_fmt_brl_from_cents
- lines: 8
- called_by: _front_build_price_facts_block, _front_repair_price_reply
- calls: int

## _tokenize_lookup_text
- lines: 16
- called_by: _infer_segment_from_text, _lookup_token_overlap_score
- calls: _normalize_lookup_key, findall, len, replace

## _lookup_token_overlap_score
- lines: 38
- called_by: _best_lookup_key_match, _score_query_against_doc
- calls: _base, _normalize_lookup_key, _tokenize_lookup_text, endswith, intersection, len, max, replace, set, str, strip

## _best_lookup_key_match
- lines: 21
- called_by: _infer_segment_from_docs, _kb_lookup_operational_docs
- calls: _lookup_token_overlap_score, str, strip

## _iter_doc_text_fragments
- lines: 34
- called_by: _collect_doc_texts, _iter_doc_text_fragments
- calls: _iter_doc_text_fragments, isinstance, items, lower, str, strip

## _collect_doc_texts
- lines: 18
- called_by: _score_query_against_doc
- calls: _iter_doc_text_fragments, add, append, isinstance, lower, set, str, strip, sub

## _score_query_against_doc
- lines: 30
- called_by: _best_doc_match, _doc_identity_is_compatible_with_current_text
- calls: _collect_doc_texts, _lookup_token_overlap_score, append, get, isinstance, max, str, strip

## _best_doc_match
- lines: 25
- called_by: _infer_segment_from_docs, _infer_segment_from_text, _kb_lookup_operational_docs
- calls: _score_query_against_doc, isinstance, items, str, strip

## _keyword_doc_match
- lines: 38
- called_by: _infer_segment_from_docs, _infer_segment_from_text
- calls: _normalize_lookup_key, escape, get, isinstance, items, len, replace, search, str, strip, sub

## _family_to_pack_id
- lines: 13
- called_by: none
- calls: lower, str, strip

## _stable_variant_index
- lines: 11
- called_by: none
- calls: ord, str, strip

## _split_user_operational_clauses
- lines: 30
- called_by: _build_user_operational_seed
- calls: append, len, replace, split, str, strip, sub

## _build_user_operational_seed
- lines: 33
- called_by: none
- calls: _split_user_operational_clauses, add, append, join, len, lower, set, str, strip, sub

## build_dynamic_context_frame
- lines: 16
- called_by: none
- calls: none

## _clean_scene_text
- lines: 12
- called_by: none
- calls: rstrip, str, strip, sub

## _drop_explanatory_opening
- lines: 14
- called_by: _generate_micro_scene_with_model, _upgrade_operational_reply_with_model
- calls: _looks_explanatory_sentence, _split_sentences_pt, join, str, strip

## _drop_abstract_closing
- lines: 14
- called_by: _generate_micro_scene_with_model, _upgrade_operational_reply_with_model
- calls: _looks_explanatory_sentence, _split_sentences_pt, join, len, str, strip

## _upgrade_weak_question
- lines: 3
- called_by: none
- calls: str, strip

## _segment_reference_example
- lines: 27
- called_by: _segment_micro_flow
- calls: get, isinstance, lower, str, strip, upper

## _pack_practical_add
- lines: 3
- called_by: _segment_micro_flow
- calls: none

## _segment_micro_flow
- lines: 12
- called_by: none
- calls: _pack_practical_add, _segment_reference_example, rstrip, strip
