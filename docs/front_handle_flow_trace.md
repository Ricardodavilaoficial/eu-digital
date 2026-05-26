# Handle Flow Trace

Objetivo: mapear fluxo estrutural do handle().

Relatório somente leitura.

[CALL] line=6305 fn=int 
[CALL] line=6305 fn=get 
[CALL] line=6335 fn=upper 
[CALL] line=6335 fn=strip 
[CALL] line=6335 fn=str 
[CALL] line=6335 fn=get 
[CALL] line=6336 fn=upper 
[CALL] line=6336 fn=strip 
[CALL] line=6336 fn=str 
[CALL] line=6337 fn=get 
[CALL] line=6338 fn=get 
[CALL] line=6339 fn=get 
[CALL] line=6340 fn=get 
[IF] line=6344 cond=upstream_topic_hint not in TOPICS
[CALL] line=6351 fn=bool 
[CALL] line=6353 fn=strip 
[CALL] line=6353 fn=str 
[CALL] line=6353 fn=get 
[CALL] line=6354 fn=strip 
[CALL] line=6354 fn=str 
[CALL] line=6354 fn=get 
[CALL] line=6355 fn=strip 
[CALL] line=6355 fn=str 
[CALL] line=6355 fn=get 
[CALL] line=6356 fn=_front_sanitize_lead_name_candidate 
[CALL] line=6360 fn=get 
[CALL] line=6361 fn=get 
[CALL] line=6362 fn=get 
[CALL] line=6365 fn=strip 
[CALL] line=6365 fn=str 
[CALL] line=6366 fn=get 
[CALL] line=6368 fn=int 
[CALL] line=6369 fn=get 
[CALL] line=6371 fn=strip 
[CALL] line=6371 fn=str 
[CALL] line=6372 fn=get 
[CALL] line=6374 fn=strip 
[CALL] line=6374 fn=str 
[CALL] line=6375 fn=get 
[IF] line=6379 cond=name_hint
[CALL] line=6380 fn=split 
[IF] line=6381 cond=len(tokens) > 2 or len(name_hint) > 20
[CALL] line=6381 fn=len 
[CALL] line=6381 fn=len 
[CALL] line=6384 fn=bool 
[CALL] line=6384 fn=get 
[CALL] line=6385 fn=lower 
[CALL] line=6385 fn=strip 
[CALL] line=6385 fn=str 
[CALL] line=6386 fn=get 
[CALL] line=6387 fn=get 
[CALL] line=6388 fn=get 
[CALL] line=6391 fn=_prepare_kb_snapshot_buffers TARGET
[IF] line=6404 cond=lead_memory_summary
[CALL] line=6405 fn=append 
[IF] line=6407 cond=last_topic
[CALL] line=6408 fn=append 
[IF] line=6412 cond=last_next_step
[CALL] line=6413 fn=append 
[CALL] line=6417 fn=strip 
[CALL] line=6417 fn=join 
[CALL] line=6418 fn=strip 
[CALL] line=6420 fn=strip 
[CALL] line=6420 fn=str 
[IF] line=6423 cond=persistent_context
[IF] line=6424 cond=last_user_goal
[CALL] line=6425 fn=strip 
[CALL] line=6432 fn=info 
[CALL] line=6434 fn=bool 
[CALL] line=6436 fn=bool 
[CALL] line=6437 fn=bool 
[IF] line=6445 cond=kb_snapshot and str(kb_snapshot).strip().startswith('{')
[CALL] line=6445 fn=startswith 
[CALL] line=6445 fn=strip 
[CALL] line=6445 fn=str 
[CALL] line=6446 fn=loads 
[CALL] line=6446 fn=str 
[IF] line=6447 cond=isinstance(_parsed_kb_snapshot, dict)
[CALL] line=6447 fn=isinstance 
[CALL] line=6453 fn=info 
[CALL] line=6455 fn=len 
[CALL] line=6456 fn=len 
[CALL] line=6470 fn=bool 
[CALL] line=6470 fn=strip 
[CALL] line=6470 fn=str 
[IF] line=6473 cond=not segment_hint and inferred_lead_segment
[IF] line=6507 cond=not inferred_segment_for_kb and user_text and kb_snapshot
[CALL] line=6512 fn=strip 
[CALL] line=6513 fn=_infer_segment_from_text TARGET
[IF] line=6516 cond=_early_segment
[IF] line=6534 cond=FRONT_KB_RESOLVER_ENABLED and build_kb_context is not None
[IF] line=6536 cond=not inferred_segment_for_kb
[CALL] line=6537 fn=_infer_segment_from_text TARGET
[IF] line=6547 cond=inferred_segment_for_kb
[CALL] line=6548 fn=strip 
[CALL] line=6548 fn=str 
[CALL] line=6549 fn=str 
[IF] line=6553 cond=_seg not in _snap
[CALL] line=6560 fn=_infer_operational_family 
[CALL] line=6565 fn=build_kb_context 
[CALL] line=6579 fn=upper 
[CALL] line=6579 fn=strip 
[CALL] line=6579 fn=str 
[CALL] line=6578 fn=upper 
[CALL] line=6578 fn=strip 
[CALL] line=6578 fn=str 
[CALL] line=6585 fn=build_kb_context 
[IF] line=6597 cond=isinstance(kb_context, dict)
[CALL] line=6597 fn=isinstance 
[CALL] line=6598 fn=strip 
[CALL] line=6598 fn=str 
[CALL] line=6599 fn=get 
[CALL] line=6600 fn=get 
[IF] line=6604 cond=_seg
[CALL] line=6605 fn=str 
[IF] line=6609 cond=_seg not in _snap
[CALL] line=6622 fn=pop 
[CALL] line=6628 fn=_clear_incompatible_kb_context_for_current_text 
[CALL] line=6631 fn=isinstance 
[IF] line=6646 cond=not inferred_segment_for_kb and user_text and kb_snapshot
[CALL] line=6651 fn=strip 
[CALL] line=6652 fn=_infer_segment_from_text TARGET
[IF] line=6658 cond=inferred_segment_for_kb and isinstance(kb_context, dict)
[CALL] line=6658 fn=isinstance 
[CALL] line=6659 fn=_normalize_lookup_key 
[CALL] line=6660 fn=_normalize_lookup_key 
[CALL] line=6661 fn=join 
[CALL] line=6663 fn=str 
[CALL] line=6663 fn=get 
[CALL] line=6664 fn=str 
[CALL] line=6664 fn=get 
[CALL] line=6665 fn=str 
[CALL] line=6665 fn=get 
[CALL] line=6666 fn=str 
[CALL] line=6666 fn=get 
[IF] line=6674 cond=_turn_seg and (not _resolved_seg or (_turn_seg not in _resolved_seg and _resolved_seg not in _turn_seg))
[CALL] line=6702 fn=pop 
[CALL] line=6717 fn=_kb_context_segment_was_cleared 
[CALL] line=6718 fn=isinstance 
[CALL] line=6723 fn=str 
[CALL] line=6723 fn=get 
[IF] line=6735 cond=isinstance(kb_context, dict)
[CALL] line=6735 fn=isinstance 
[CALL] line=6736 fn=upper 
[CALL] line=6736 fn=strip 
[CALL] line=6736 fn=str 
[CALL] line=6736 fn=get 
[CALL] line=6737 fn=upper 
[CALL] line=6737 fn=strip 
[CALL] line=6737 fn=str 
[CALL] line=6737 fn=get 
[CALL] line=6738 fn=bool 
[CALL] line=6738 fn=get 
[IF] line=6745 cond=segment_hint and isinstance(kb_context, dict)
[CALL] line=6745 fn=isinstance 
[CALL] line=6754 fn=_infer_segment_from_text TARGET
[CALL] line=6759 fn=strip 
[CALL] line=6759 fn=str 
[CALL] line=6759 fn=get 
[CALL] line=6760 fn=strip 
[CALL] line=6760 fn=str 
[CALL] line=6760 fn=get 
[CALL] line=6761 fn=strip 
[CALL] line=6761 fn=str 
[CALL] line=6761 fn=get 
[CALL] line=6762 fn=strip 
[CALL] line=6762 fn=str 
[CALL] line=6762 fn=get 
[CALL] line=6763 fn=strip 
[CALL] line=6763 fn=str 
[CALL] line=6763 fn=get 
[CALL] line=6764 fn=strip 
[CALL] line=6764 fn=str 
[CALL] line=6764 fn=get 
[CALL] line=6765 fn=strip 
[CALL] line=6765 fn=str 
[CALL] line=6765 fn=get 
[CALL] line=6766 fn=strip 
[CALL] line=6766 fn=str 
[CALL] line=6766 fn=get 
[IF] line=6771 cond=isinstance(kb_context, dict)
[CALL] line=6771 fn=isinstance 
[CALL] line=6772 fn=strip 
[CALL] line=6772 fn=str 
[CALL] line=6773 fn=get 
[CALL] line=6774 fn=get 
[CALL] line=6782 fn=strip 
[CALL] line=6782 fn=str 
[CALL] line=6784 fn=strip 
[CALL] line=6784 fn=str 
[CALL] line=6784 fn=get 
[CALL] line=6786 fn=strip 
[CALL] line=6786 fn=str 
[CALL] line=6787 fn=strip 
[CALL] line=6787 fn=str 
[CALL] line=6789 fn=strip 
[CALL] line=6789 fn=str 
[IF] line=6801 cond=inferred_segment
[IF] line=6803 cond=segment_hint
[CALL] line=6808 fn=strip 
[CALL] line=6808 fn=str 
[IF] line=6812 cond=effective_segment and '__' not in effective_segment and (not segment_context_cleared)
[CALL] line=6813 fn=_infer_segment_from_docs TARGET
[CALL] line=6816 fn=isinstance 
[IF] line=6818 cond=promoted_segment and '__' in str(promoted_segment)
[CALL] line=6818 fn=str 
[CALL] line=6819 fn=strip 
[CALL] line=6819 fn=str 
[IF] line=6829 cond=segment_context_cleared
[CALL] line=6832 fn=_infer_segment_from_docs TARGET
[CALL] line=6835 fn=isinstance 
[IF] line=6837 cond=inferred_from_docs
[CALL] line=6838 fn=strip 
[CALL] line=6838 fn=str 
[IF] line=6841 cond='__' in inferred_from_docs
[IF] line=6843 cond=not effective_segment
[IF] line=6853 cond=segment_context_cleared
[CALL] line=6854 fn=strip 
[CALL] line=6854 fn=str 
[IF] line=6855 cond=isinstance(kb_context, dict)
[CALL] line=6855 fn=isinstance 
[CALL] line=6867 fn=pop 
[CALL] line=6870 fn=_kb_lookup_operational_docs TARGET
[CALL] line=6873 fn=isinstance 
[CALL] line=6875 fn=_merge_real_kb_operational_context 
[CALL] line=6876 fn=isinstance 
[CALL] line=6879 fn=info 
[CALL] line=6881 fn=strip 
[CALL] line=6881 fn=str 
[CALL] line=6882 fn=strip 
[CALL] line=6882 fn=str 
[CALL] line=6882 fn=get 
[CALL] line=6883 fn=strip 
[CALL] line=6883 fn=str 
[CALL] line=6883 fn=get 
[CALL] line=6884 fn=bool 
[CALL] line=6884 fn=strip 
[CALL] line=6884 fn=str 
[CALL] line=6884 fn=get 
[CALL] line=6885 fn=bool 
[CALL] line=6885 fn=strip 
[CALL] line=6885 fn=str 
[CALL] line=6885 fn=get 
[CALL] line=6886 fn=strip 
[CALL] line=6886 fn=str 
[CALL] line=6886 fn=get 
[CALL] line=6891 fn=locals 
[CALL] line=6894 fn=bool 
[CALL] line=6895 fn=isinstance 
[CALL] line=6897 fn=get 
[CALL] line=6898 fn=get 
[CALL] line=6899 fn=get 
[CALL] line=6908 fn=_platform_segment_profile_from_kb 
[CALL] line=6916 fn=bool 
[CALL] line=6918 fn=isinstance 
[IF] line=6922 cond=platform_kb_mode
[IF] line=6925 cond=isinstance(kb_context, dict)
[CALL] line=6925 fn=isinstance 
[IF] line=6927 cond=platform_segment_key
[CALL] line=6936 fn=bool 
[CALL] line=6937 fn=isinstance 
[CALL] line=6939 fn=get 
[CALL] line=6940 fn=get 
[CALL] line=6941 fn=get 
[IF] line=6945 cond=not docs_hydrated and (not segment_context_cleared)
[CALL] line=6946 fn=_infer_segment_from_docs TARGET
[CALL] line=6949 fn=isinstance 
[IF] line=6952 cond=reinforced_segment and reinforced_segment != effective_segment
[CALL] line=6953 fn=strip 
[CALL] line=6953 fn=str 
[CALL] line=6955 fn=_kb_lookup_operational_docs TARGET
[CALL] line=6958 fn=isinstance 
[CALL] line=6960 fn=_merge_real_kb_operational_context 
[CALL] line=6961 fn=isinstance 
[IF] line=6968 cond=effective_segment and isinstance(kb_context, dict) and (not segment_context_cleared)
[CALL] line=6968 fn=isinstance 
[IF] line=6969 cond='__' in str(effective_segment)
[CALL] line=6969 fn=str 
[CALL] line=6970 fn=strip 
[CALL] line=6970 fn=str 
[CALL] line=6972 fn=strip 
[CALL] line=6972 fn=str 
[CALL] line=6973 fn=bool 
[CALL] line=6977 fn=bool 
[CALL] line=6977 fn=strip 
[CALL] line=6977 fn=str 
[CALL] line=6979 fn=bool 
[CALL] line=6980 fn=strip 
[CALL] line=6980 fn=str 
[CALL] line=6981 fn=strip 
[CALL] line=6981 fn=str 
[CALL] line=6982 fn=strip 
[CALL] line=6982 fn=str 
[CALL] line=6985 fn=bool 
[IF] line=6990 cond=not str((kb_context or {}).get('discovery_question_hint') or '').strip() and (not operational_reference) and (not reference_example) and (not operational_family)
[CALL] line=6991 fn=strip 
[CALL] line=6991 fn=str 
[CALL] line=6991 fn=get 
[CALL] line=7001 fn=strip 
[CALL] line=7001 fn=str 
[CALL] line=7002 fn=get 
[CALL] line=7003 fn=get 
[IF] line=7006 cond=not effective_segment and preferred_discovery_question
[CALL] line=7017 fn=bool 
[CALL] line=7018 fn=isinstance 
[CALL] line=7020 fn=get 
[CALL] line=7021 fn=get 
[CALL] line=7022 fn=get 
[CALL] line=7026 fn=bool 
[CALL] line=7028 fn=isinstance 
[CALL] line=7029 fn=bool 
[IF] line=7032 cond=platform_kb_mode
[CALL] line=7033 fn=_platform_kb_resolve_runtime TARGET
[CALL] line=7035 fn=isinstance 
[IF] line=7041 cond=platform_runtime and isinstance(kb_context, dict)
[CALL] line=7041 fn=isinstance 
[CALL] line=7043 fn=items 
[IF] line=7044 cond=_v
[IF] line=7046 cond=platform_runtime.get('topic') and (not current_turn_topic_reset)
[CALL] line=7046 fn=get 
[CALL] line=7059 fn=_resolve_canonical_topic 
[CALL] line=7061 fn=isinstance 
[CALL] line=7063 fn=str 
[CALL] line=7065 fn=get 
[CALL] line=7072 fn=upper 
[CALL] line=7072 fn=strip 
[CALL] line=7072 fn=str 
[CALL] line=7076 fn=upper 
[CALL] line=7076 fn=strip 
[CALL] line=7076 fn=str 
[IF] line=7080 cond=str(upstream_topic_hint or '').strip().upper() == 'OTHER' and canonical_topic != 'OTHER'
[CALL] line=7081 fn=upper 
[CALL] line=7081 fn=strip 
[CALL] line=7081 fn=str 
[IF] line=7086 cond=canonical_topic and platform_kb_mode and isinstance(kb_context, dict)
[CALL] line=7086 fn=isinstance 
[CALL] line=7092 fn=bool 
[IF] line=7094 cond=isinstance(kb_context, dict)
[CALL] line=7094 fn=isinstance 
[IF] line=7101 cond=kb_context
[CALL] line=7102 fn=dumps 
[CALL] line=7106 fn=upper 
[CALL] line=7106 fn=strip 
[CALL] line=7106 fn=str 
[CALL] line=7106 fn=get 
[IF] line=7107 cond=not selected_pack_id and platform_runtime
[CALL] line=7108 fn=upper 
[CALL] line=7108 fn=strip 
[CALL] line=7108 fn=str 
[CALL] line=7108 fn=get 
[IF] line=7109 cond=not selected_pack_id
[CALL] line=7110 fn=_pick_pack_for_intent 
[CALL] line=7111 fn=upper 
[CALL] line=7111 fn=strip 
[CALL] line=7111 fn=str 
[CALL] line=7111 fn=get 
[IF] line=7113 cond=not selected_pack_id and segment_context_cleared
[CALL] line=7114 fn=_pick_pack_for_intent 
[CALL] line=7115 fn=upper 
[CALL] line=7115 fn=strip 
[CALL] line=7115 fn=str 
[CALL] line=7115 fn=get 
[CALL] line=7115 fn=get 
[CALL] line=7117 fn=strip 
[CALL] line=7117 fn=str 
[CALL] line=7117 fn=get 
[CALL] line=7118 fn=strip 
[CALL] line=7118 fn=str 
[CALL] line=7118 fn=get 
[CALL] line=7119 fn=strip 
[CALL] line=7119 fn=str 
[CALL] line=7119 fn=get 
[CALL] line=7120 fn=strip 
[CALL] line=7120 fn=str 
[CALL] line=7120 fn=get 
[CALL] line=7121 fn=strip 
[CALL] line=7121 fn=str 
[CALL] line=7121 fn=get 
[CALL] line=7122 fn=strip 
[CALL] line=7122 fn=str 
[CALL] line=7122 fn=get 
[IF] line=7124 cond=platform_runtime
[CALL] line=7125 fn=strip 
[CALL] line=7125 fn=str 
[CALL] line=7125 fn=get 
[CALL] line=7126 fn=strip 
[CALL] line=7126 fn=str 
[CALL] line=7126 fn=get 
[CALL] line=7127 fn=strip 
[CALL] line=7127 fn=str 
[CALL] line=7127 fn=get 
[CALL] line=7128 fn=strip 
[CALL] line=7128 fn=str 
[CALL] line=7128 fn=get 
[CALL] line=7129 fn=strip 
[CALL] line=7129 fn=str 
[CALL] line=7131 fn=get 
[CALL] line=7135 fn=strip 
[CALL] line=7135 fn=str 
[CALL] line=7135 fn=get 
[IF] line=7137 cond=selected_pack_id and (not micro_scene)
[CALL] line=7138 fn=_kb_get_micro_scene 
[IF] line=7139 cond=selected_pack_id and (not reference_example)
[CALL] line=7140 fn=_kb_get_reference_example 
[IF] line=7141 cond=effective_segment and (not operational_reference)
[CALL] line=7142 fn=_kb_get_segment_scene 
[IF] line=7143 cond=not operational_reference and (direct_scene or runtime_long_text or runtime_short_reply or micro_scene)
[IF] line=7153 cond=platform_kb_mode
[CALL] line=7154 fn=_platform_topic_from_kb_rules 
[IF] line=7155 cond=platform_topic_hint and (not current_turn_topic_reset)
[CALL] line=7159 fn=_platform_pack_from_profile 
[CALL] line=7161 fn=str 
[CALL] line=7161 fn=get 
[CALL] line=7166 fn=_platform_pack_material 
[IF] line=7172 cond=platform_material
[CALL] line=7173 fn=strip 
[CALL] line=7173 fn=str 
[CALL] line=7173 fn=get 
[CALL] line=7174 fn=strip 
[CALL] line=7174 fn=str 
[CALL] line=7174 fn=get 
[CALL] line=7175 fn=strip 
[CALL] line=7175 fn=str 
[CALL] line=7175 fn=get 
[CALL] line=7176 fn=strip 
[CALL] line=7176 fn=str 
[CALL] line=7176 fn=get 
[CALL] line=7177 fn=strip 
[CALL] line=7177 fn=str 
[CALL] line=7177 fn=get 
[CALL] line=7178 fn=strip 
[CALL] line=7178 fn=str 
[CALL] line=7178 fn=get 
[IF] line=7182 cond=runtime_short_reply
[IF] line=7184 cond=runtime_long_text
[IF] line=7186 cond=direct_scene
[IF] line=7188 cond=platform_material.get('material_source')
[CALL] line=7188 fn=get 
[CALL] line=7201 fn=_refresh_operational_anchor 
[CALL] line=7203 fn=isinstance 
[CALL] line=7208 fn=strip 
[CALL] line=7208 fn=str 
[CALL] line=7208 fn=get 
[CALL] line=7209 fn=strip 
[CALL] line=7209 fn=str 
[CALL] line=7209 fn=get 
[CALL] line=7210 fn=strip 
[CALL] line=7210 fn=str 
[CALL] line=7210 fn=get 
[IF] line=7213 cond=not reference_example and operational_reference and (not _is_scene_echo(operational_reference, user_text))
[CALL] line=7213 fn=_is_scene_echo 
[CALL] line=7214 fn=_split_scene_steps 
[IF] line=7215 cond=len(derived_steps) >= 2
[CALL] line=7215 fn=len 
[CALL] line=7216 fn=strip 
[CALL] line=7216 fn=str 
[CALL] line=7223 fn=_build_operational_contract TARGET
[CALL] line=7225 fn=isinstance 
[CALL] line=7238 fn=bool 
[IF] line=7247 cond=free_mode
[CALL] line=7249 fn=_build_free_mode_family_hint 
[IF] line=7254 cond=not operational_family
[CALL] line=7255 fn=strip 
[CALL] line=7255 fn=str 
[CALL] line=7256 fn=_infer_operational_family 
[CALL] line=7262 fn=bool 
[CALL] line=7269 fn=_resolve_reply_size_policy 
[CALL] line=7275 fn=bool 
[CALL] line=7283 fn=_is_scene_echo 
[CALL] line=7284 fn=_is_scene_echo 
[CALL] line=7286 fn=_has_strong_kb_anchor 
[CALL] line=7287 fn=isinstance 
[CALL] line=7298 fn=bool 
[CALL] line=7303 fn=strip 
[CALL] line=7303 fn=str 
[CALL] line=7304 fn=strip 
[CALL] line=7304 fn=str 
[CALL] line=7305 fn=bool 
[CALL] line=7305 fn=get 
[IF] line=7309 cond=allow_scene_prompting
[CALL] line=7310 fn=_build_scene_hint_block 
[IF] line=7316 cond=scene_hint_block
[CALL] line=7319 fn=_build_user_scene_block 
[IF] line=7329 cond=segment_for_prompt
[IF] line=7331 cond=platform_kb_mode and (operational_reference or reference_example or micro_scene)
[IF] line=7344 cond=not operational_reference
[CALL] line=7347 fn=bool 
[CALL] line=7351 fn=strip 
[CALL] line=7351 fn=str 
[CALL] line=7352 fn=strip 
[CALL] line=7352 fn=str 
[CALL] line=7356 fn=strip 
[CALL] line=7356 fn=str 
[CALL] line=7356 fn=get 
[CALL] line=7356 fn=getenv 
[CALL] line=7394 fn=bool 
[CALL] line=7394 fn=get 
[CALL] line=7394 fn=locals 
[CALL] line=7394 fn=locals 
[CALL] line=7399 fn=strip 
[CALL] line=7399 fn=str 
[CALL] line=7400 fn=strip 
[CALL] line=7400 fn=str 
[CALL] line=7403 fn=get 
[CALL] line=7403 fn=locals 
[CALL] line=7403 fn=locals 
[CALL] line=7404 fn=get 
[CALL] line=7404 fn=locals 
[CALL] line=7404 fn=locals 
[CALL] line=7405 fn=get 
[CALL] line=7405 fn=locals 
[CALL] line=7405 fn=locals 
[CALL] line=7386 fn=bool 
[CALL] line=7386 fn=get 
[CALL] line=7386 fn=locals 
[CALL] line=7386 fn=locals 
[CALL] line=7382 fn=strip 
[CALL] line=7382 fn=str 
[CALL] line=7383 fn=strip 
[CALL] line=7383 fn=str 
[CALL] line=7389 fn=strip 
[CALL] line=7389 fn=str 
[CALL] line=7389 fn=get 
[CALL] line=7389 fn=locals 
[CALL] line=7389 fn=locals 
[CALL] line=7390 fn=strip 
[CALL] line=7390 fn=str 
[CALL] line=7390 fn=get 
[CALL] line=7390 fn=locals 
[CALL] line=7390 fn=locals 
[CALL] line=7391 fn=dumps 
[CALL] line=7391 fn=bool 
[CALL] line=7391 fn=get 
[CALL] line=7391 fn=locals 
[CALL] line=7391 fn=locals 
[CALL] line=7391 fn=get 
[CALL] line=7391 fn=locals 
[CALL] line=7391 fn=locals 
[CALL] line=7415 fn=upper 
[CALL] line=7415 fn=strip 
[CALL] line=7415 fn=str 
[CALL] line=7415 fn=get 
[CALL] line=7416 fn=_front_build_price_facts_block 
[CALL] line=7413 fn=_front_build_price_facts_block 
[IF] line=7425 cond=kb_anchor_available
[CALL] line=7436 fn=strip 
[CALL] line=7437 fn=strip 
[CALL] line=7437 fn=str 
[CALL] line=7450 fn=int 
[CALL] line=7450 fn=get 
[CALL] line=7454 fn=min 
[CALL] line=7456 fn=max 
[CALL] line=7486 fn=isinstance 
[CALL] line=7489 fn=upper 
[CALL] line=7489 fn=strip 
[CALL] line=7489 fn=str 
[CALL] line=7490 fn=upper 
[CALL] line=7490 fn=strip 
[CALL] line=7490 fn=str 
[CALL] line=7492 fn=bool 
[CALL] line=7503 fn=get 
[CALL] line=7504 fn=get 
[IF] line=7508 cond=_technical_direct_budget
[CALL] line=7509 fn=max 
[IF] line=7513 cond=_HAS_OPENAI_CLIENT and _client is not None
[CALL] line=7523 fn=_front_response_json_schema 
[CALL] line=7526 fn=create 
[CALL] line=7527 fn=strip 
[CALL] line=7527 fn=str 
[CALL] line=7531 fn=getattr 
[IF] line=7532 cond=u
[CALL] line=7534 fn=int 
[CALL] line=7534 fn=getattr 
[CALL] line=7535 fn=int 
[CALL] line=7535 fn=getattr 
[CALL] line=7536 fn=int 
[CALL] line=7536 fn=getattr 
[CALL] line=7542 fn=create 
[CALL] line=7549 fn=_front_response_json_schema 
[CALL] line=7552 fn=strip 
[CALL] line=7556 fn=get 
[CALL] line=7558 fn=int 
[CALL] line=7558 fn=get 
[CALL] line=7559 fn=int 
[CALL] line=7559 fn=get 
[CALL] line=7560 fn=int 
[CALL] line=7560 fn=get 
[CALL] line=7573 fn=strip 
[CALL] line=7573 fn=str 
[IF] line=7576 cond=free_mode
[CALL] line=7577 fn=startswith 
[CALL] line=7577 fn=startswith 
[CALL] line=7577 fn=startswith 
[IF] line=7579 cond=not looks_like_json
[CALL] line=7580 fn=_preferred_topic_from_kb 
[CALL] line=7581 fn=isinstance 
[IF] line=7584 cond=kb_forced_topic and kb_forced_topic in TOPICS
[CALL] line=7587 fn=_parse_free_mode_text_response 
[IF] line=7592 cond=free_text_payload and str(free_text_payload.get('replyText') or '').strip()
[CALL] line=7592 fn=strip 
[CALL] line=7592 fn=str 
[CALL] line=7592 fn=get 
[CALL] line=7595 fn=_sanitize_user_facing_reply 
[CALL] line=7596 fn=strip 
[CALL] line=7596 fn=sub 
[IF] line=7598 cond=raw_text_candidate
[CALL] line=7617 fn=sub 
[CALL] line=7618 fn=sub 
[CALL] line=7619 fn=sub 
[CALL] line=7621 fn=search 
[IF] line=7622 cond=m
[CALL] line=7623 fn=group 
[CALL] line=7627 fn=loads 
[CALL] line=7629 fn=sub 
[CALL] line=7631 fn=loads 
[CALL] line=7634 fn=warning 
[CALL] line=7642 fn=strip 
[CALL] line=7642 fn=str 
[CALL] line=7649 fn=_merge_identity_fields_from_raw_ai_payload 
[CALL] line=7651 fn=warning 
[CALL] line=7655 fn=_salvage_free_mode_payload 
[IF] line=7659 cond=salvaged and str((salvaged or {}).get('replyText') or '').strip()
[CALL] line=7659 fn=strip 
[CALL] line=7659 fn=str 
[CALL] line=7659 fn=get 
[CALL] line=7660 fn=_merge_identity_fields_from_raw_ai_payload 
[CALL] line=7662 fn=_preferred_topic_from_kb 
[CALL] line=7663 fn=isinstance 
[IF] line=7666 cond=kb_forced_topic and kb_forced_topic in TOPICS
[CALL] line=7669 fn=_parse_free_mode_text_response 
[CALL] line=7670 fn=str 
[IF] line=7674 cond=free_text_payload and str(free_text_payload.get('replyText') or '').strip()
[CALL] line=7674 fn=strip 
[CALL] line=7674 fn=str 
[CALL] line=7674 fn=get 
[CALL] line=7675 fn=_merge_identity_fields_from_raw_ai_payload 
[IF] line=7678 cond=not (str(raw or '').lstrip().startswith('{') or str(raw or '').lstrip().startswith('```'))
[CALL] line=7679 fn=startswith 
[CALL] line=7679 fn=lstrip 
[CALL] line=7679 fn=str 
[CALL] line=7680 fn=startswith 
[CALL] line=7680 fn=lstrip 
[CALL] line=7680 fn=str 
[CALL] line=7682 fn=_sanitize_user_facing_reply 
[CALL] line=7682 fn=str 
[CALL] line=7683 fn=strip 
[CALL] line=7683 fn=sub 
[IF] line=7685 cond=raw_text_candidate
[CALL] line=7700 fn=_merge_identity_fields_from_raw_ai_payload 
[CALL] line=7706 fn=sub 
[CALL] line=7707 fn=sub 
[CALL] line=7708 fn=sub 
[CALL] line=7710 fn=search 
[IF] line=7711 cond=m
[CALL] line=7712 fn=group 
[CALL] line=7716 fn=loads 
[CALL] line=7718 fn=sub 
[CALL] line=7720 fn=loads 
[CALL] line=7723 fn=warning 
[IF] line=7736 cond=isinstance(data, dict)
[CALL] line=7736 fn=isinstance 
[CALL] line=7737 fn=_merge_identity_fields_from_raw_ai_payload 
[CALL] line=7739 fn=warning 
[CALL] line=7744 fn=get 
[CALL] line=7746 fn=_normalize_response_mode 
[CALL] line=7747 fn=get 
[CALL] line=7748 fn=get 
[CALL] line=7749 fn=get 
[CALL] line=7750 fn=get 
[CALL] line=7753 fn=upper 
[CALL] line=7753 fn=strip 
[CALL] line=7753 fn=str 
[CALL] line=7754 fn=get 
[CALL] line=7755 fn=get 
[CALL] line=7756 fn=get 
[CALL] line=7762 fn=lower 
[CALL] line=7762 fn=strip 
[CALL] line=7762 fn=str 
[CALL] line=7763 fn=get 
[CALL] line=7764 fn=get 
[CALL] line=7768 fn=lower 
[CALL] line=7768 fn=strip 
[CALL] line=7768 fn=str 
[CALL] line=7769 fn=get 
[CALL] line=7770 fn=get 
[IF] line=7774 cond=question_type not in ('broad', 'punctual', 'continuity')
[CALL] line=7789 fn=upper 
[CALL] line=7789 fn=strip 
[CALL] line=7789 fn=str 
[CALL] line=7790 fn=get 
[CALL] line=7791 fn=get 
[CALL] line=7796 fn=upper 
[CALL] line=7796 fn=strip 
[CALL] line=7796 fn=str 
[CALL] line=7798 fn=bool 
[CALL] line=7799 fn=int 
[CALL] line=7817 fn=lower 
[CALL] line=7817 fn=strip 
[CALL] line=7817 fn=str 
[CALL] line=7818 fn=get 
[CALL] line=7819 fn=get 
[CALL] line=7823 fn=strip 
[CALL] line=7823 fn=str 
[CALL] line=7824 fn=get 
[CALL] line=7825 fn=get 
[IF] line=7833 cond=not inferred_lead_name
[CALL] line=7834 fn=_extract_lead_name_from_current_turn 
[IF] line=7835 cond=_turn_name
[CALL] line=7840 fn=warning 
[CALL] line=7842 fn=strip 
[CALL] line=7842 fn=str 
[CALL] line=7843 fn=get 
[CALL] line=7844 fn=get 
[CALL] line=7848 fn=strip 
[CALL] line=7848 fn=str 
[CALL] line=7849 fn=get 
[CALL] line=7850 fn=get 
[IF] line=7858 cond=not inferred_lead_segment_raw
[CALL] line=7859 fn=strip 
[CALL] line=7859 fn=str 
[CALL] line=7860 fn=search 
[IF] line=7864 cond=_m
[CALL] line=7865 fn=strip 
[CALL] line=7865 fn=sub 
[CALL] line=7865 fn=group 
[IF] line=7866 cond=_raw_activity and _raw_activity.lower() != str(inferred_lead_name or '').strip().lower()
[CALL] line=7868 fn=lower 
[CALL] line=7868 fn=lower 
[CALL] line=7868 fn=strip 
[CALL] line=7868 fn=str 
[CALL] line=7874 fn=warning 
[IF] line=7877 cond=not inferred_lead_segment_raw and inferred_lead_segment
[IF] line=7881 cond=inferred_lead_segment_raw
[IF] line=7882 cond=not segment_hint
[IF] line=7885 cond=isinstance(operational_contract, dict) and (not str(operational_contract.get('segment') or '').strip())
[CALL] line=7885 fn=isinstance 
[CALL] line=7885 fn=strip 
[CALL] line=7885 fn=str 
[CALL] line=7886 fn=get 
[IF] line=7899 cond=inferred_lead_segment and (not segment_hint)
[IF] line=7902 cond=inferred_lead_segment_raw and (not segment_hint)
[IF] line=7905 cond=not segment_hint
[CALL] line=7906 fn=_front_extract_declared_segment_from_user_text 
[IF] line=7907 cond=_declared_segment
[IF] line=7913 cond=isinstance(operational_contract, dict)
[CALL] line=7913 fn=isinstance 
[IF] line=7914 cond=inferred_lead_segment_raw and (not str(operational_contract.get('segment') or '').strip())
[CALL] line=7914 fn=strip 
[CALL] line=7914 fn=str 
[CALL] line=7914 fn=get 
[IF] line=7916 cond=inferred_lead_segment and (not str(operational_contract.get('segment') or '').strip())
[CALL] line=7916 fn=strip 
[CALL] line=7916 fn=str 
[CALL] line=7916 fn=get 
[CALL] line=7930 fn=_front_sanitize_lead_name_candidate 
[CALL] line=7936 fn=get 
[CALL] line=7937 fn=get 
[CALL] line=7938 fn=get 
[IF] line=7950 cond=not current_turn_lead_name
[CALL] line=7952 fn=_extract_lead_name_from_current_turn 
[CALL] line=7953 fn=_front_sanitize_lead_name_candidate 
[CALL] line=7959 fn=get 
[CALL] line=7960 fn=get 
[CALL] line=7961 fn=get 
[IF] line=7964 cond=_turn_name
[IF] line=7969 cond=isinstance(understanding, dict)
[CALL] line=7969 fn=isinstance 
[IF] line=7974 cond=current_turn_lead_name and (not name_hint)
[CALL] line=7977 fn=bool 
[IF] line=7980 cond=str(segment_hint or '').strip()
[CALL] line=7980 fn=strip 
[CALL] line=7980 fn=str 
[CALL] line=7982 fn=bool 
[CALL] line=7987 fn=strip 
[CALL] line=7987 fn=str 
[CALL] line=7988 fn=get 
[CALL] line=7989 fn=get 
[CALL] line=7993 fn=strip 
[CALL] line=7993 fn=str 
[CALL] line=7993 fn=get 
[CALL] line=7993 fn=get 
[CALL] line=7994 fn=lower 
[CALL] line=7994 fn=strip 
[CALL] line=7994 fn=str 
[CALL] line=7994 fn=get 
[CALL] line=7994 fn=get 
[CALL] line=7995 fn=strip 
[CALL] line=7995 fn=str 
[CALL] line=7995 fn=get 
[CALL] line=7995 fn=get 
[CALL] line=7996 fn=lower 
[CALL] line=7996 fn=strip 
[CALL] line=7996 fn=str 
[CALL] line=7996 fn=get 
[CALL] line=7996 fn=get 
[CALL] line=7997 fn=lower 
[CALL] line=7997 fn=strip 
[CALL] line=7997 fn=str 
[CALL] line=7997 fn=get 
[CALL] line=7998 fn=strip 
[CALL] line=7998 fn=str 
[CALL] line=7998 fn=get 
[CALL] line=7998 fn=get 
[CALL] line=7998 fn=get 
[CALL] line=8007 fn=lower 
[CALL] line=8007 fn=strip 
[CALL] line=8007 fn=str 
[CALL] line=8008 fn=get 
[CALL] line=8009 fn=get 
[CALL] line=8010 fn=get 
[IF] line=8014 cond=not has_name
[CALL] line=8017 fn=bool 
[CALL] line=8018 fn=strip 
[CALL] line=8018 fn=str 
[IF] line=8023 cond=current_turn_segment_resolved
[CALL] line=8026 fn=bool 
[CALL] line=8032 fn=strip 
[CALL] line=8032 fn=str 
[CALL] line=8033 fn=get 
[CALL] line=8034 fn=get 
[CALL] line=8037 fn=strip 
[CALL] line=8037 fn=str 
[CALL] line=8037 fn=get 
[CALL] line=8039 fn=strip 
[CALL] line=8039 fn=str 
[CALL] line=8039 fn=get 
[IF] line=8040 cond=payload_reply_source
[IF] line=8043 cond=free_mode and reply_text and (not spoken_text)
[IF] line=8046 cond=free_mode and (not reply_text)
[IF] line=8048 cond=not (str(raw or '').lstrip().startswith('{') or str(raw or '').lstrip().startswith('```'))
[CALL] line=8049 fn=startswith 
[CALL] line=8049 fn=lstrip 
[CALL] line=8049 fn=str 
[CALL] line=8050 fn=startswith 
[CALL] line=8050 fn=lstrip 
[CALL] line=8050 fn=str 
[CALL] line=8052 fn=_sanitize_user_facing_reply 
[CALL] line=8052 fn=str 
[CALL] line=8053 fn=strip 
[CALL] line=8053 fn=sub 
[IF] line=8055 cond=raw_text_candidate
[IF] line=8057 cond=not spoken_text
[IF] line=8059 cond=not str(reply_source or '').strip()
[CALL] line=8059 fn=strip 
[CALL] line=8059 fn=str 
[IF] line=8064 cond=topic not in TOPICS
[IF] line=8070 cond=platform_kb_mode and canonical_topic and (canonical_topic in TOPICS) and (canonical_topic != 'OTHER') and (topic == 'OTHER') and (not current_turn_topic_reset) and (not _front_topic_pivot_detected)
[IF] line=8081 cond=confidence not in ('high', 'medium')
[IF] line=8090 cond=current_turn_topic_reset
[IF] line=8098 cond=isinstance(kb_context, dict)
[CALL] line=8098 fn=isinstance 
[CALL] line=8114 fn=pop 
[IF] line=8116 cond=platform_kb_mode and (not current_turn_topic_reset)
[CALL] line=8117 fn=upper 
[CALL] line=8117 fn=strip 
[CALL] line=8117 fn=str 
[CALL] line=8117 fn=get 
[IF] line=8118 cond=forced_topic in TOPICS and forced_topic != 'OTHER' and (not current_turn_topic_reset) and (not _front_topic_pivot_detected)
[CALL] line=8129 fn=upper 
[CALL] line=8129 fn=strip 
[CALL] line=8129 fn=str 
[CALL] line=8129 fn=get 
[CALL] line=8129 fn=get 
[IF] line=8130 cond=next_step not in ('NONE', 'SEND_LINK')
[CALL] line=8133 fn=bool 
[CALL] line=8133 fn=get 
[CALL] line=8133 fn=bool 
[CALL] line=8133 fn=get 
[CALL] line=8137 fn=get 
[IF] line=8139 cond=not segment_for_prompt
[IF] line=8140 cond=topic == 'AGENDA' and 'PACK_A_AGENDA' in _packs
[IF] line=8142 cond=topic == 'PRICING' and 'PACK_B_SERVICOS' in _packs
[IF] line=8144 cond=topic == 'PROCESS' and 'PACK_D_STATUS' in _packs
[CALL] line=8156 fn=_infer_understanding_temperature 
[IF] line=8170 cond=discovery_resolved
[IF] line=8173 cond=should_ask_segment == 'yes'
[IF] line=8177 cond=platform_kb_mode and canonical_topic and (canonical_topic in TOPICS) and (canonical_topic != 'OTHER') and (topic == 'OTHER') and (not current_turn_topic_reset) and (not _front_topic_pivot_detected)
[IF] line=8188 cond=confidence not in ('high', 'medium')
[IF] line=8194 cond=platform_kb_mode and forced_topic in TOPICS and (forced_topic != 'OTHER') and (not _front_topic_pivot_detected)
[IF] line=8202 cond=confidence not in ('high', 'medium')
[CALL] line=8208 fn=_preferred_topic_from_kb 
[CALL] line=8209 fn=isinstance 
[IF] line=8212 cond=topic in ('OTHER', '') and preferred_topic in TOPICS and (preferred_topic not in ('OTHER', '')) and (not current_turn_topic_reset) and (not _front_topic_pivot_detected)
[IF] line=8220 cond=confidence not in ('high', 'medium')
[IF] line=8226 cond=platform_kb_mode
[CALL] line=8227 fn=_platform_pack_from_profile 
[CALL] line=8234 fn=_platform_pack_material 
[IF] line=8240 cond=platform_material
[CALL] line=8241 fn=strip 
[CALL] line=8241 fn=str 
[CALL] line=8241 fn=get 
[CALL] line=8242 fn=strip 
[CALL] line=8242 fn=str 
[CALL] line=8242 fn=get 
[CALL] line=8243 fn=strip 
[CALL] line=8243 fn=str 
[CALL] line=8243 fn=get 
[CALL] line=8244 fn=strip 
[CALL] line=8244 fn=str 
[CALL] line=8244 fn=get 
[CALL] line=8245 fn=strip 
[CALL] line=8245 fn=str 
[CALL] line=8245 fn=get 
[CALL] line=8246 fn=strip 
[CALL] line=8246 fn=str 
[CALL] line=8246 fn=get 
[CALL] line=8250 fn=_build_operational_contract TARGET
[CALL] line=8252 fn=isinstance 
[IF] line=8261 cond=platform_kb_mode and isinstance(operational_contract, dict)
[CALL] line=8261 fn=isinstance 
[IF] line=8262 cond=canonical_topic and canonical_topic in TOPICS and (canonical_topic != 'OTHER') and (not _front_topic_pivot_detected)
[CALL] line=8272 fn=bool 
[CALL] line=8273 fn=get 
[CALL] line=8274 fn=strip 
[CALL] line=8274 fn=str 
[CALL] line=8274 fn=get 
[CALL] line=8275 fn=strip 
[CALL] line=8275 fn=str 
[CALL] line=8275 fn=get 
[IF] line=8278 cond=platform_runtime
[IF] line=8279 cond=platform_runtime.get('pack_id')
[CALL] line=8279 fn=get 
[IF] line=8281 cond=platform_runtime.get('platform_segment_key')
[CALL] line=8281 fn=get 
[IF] line=8283 cond=_platform_runtime_operational_allowed and platform_runtime.get('direct_scene')
[CALL] line=8283 fn=get 
[IF] line=8285 cond=_platform_runtime_operational_allowed and platform_runtime.get('runtime_long_text')
[CALL] line=8285 fn=get 
[IF] line=8287 cond=_platform_runtime_operational_allowed and platform_runtime.get('runtime_short_reply')
[CALL] line=8287 fn=get 
[IF] line=8289 cond=not _platform_runtime_operational_allowed and platform_runtime.get('runtime_compact_reply')
[CALL] line=8289 fn=get 
[IF] line=8291 cond=_platform_runtime_operational_allowed and operational_reference
[IF] line=8293 cond=_platform_runtime_operational_allowed and reference_example
[IF] line=8296 cond=_platform_runtime_operational_allowed and micro_scene
[IF] line=8299 cond=platform_runtime.get('material_source')
[CALL] line=8299 fn=get 
[IF] line=8328 cond=isinstance(operational_contract, dict) and str(operational_contract.get('segment') or '').strip() and str(user_text or '').strip()
[CALL] line=8329 fn=isinstance 
[CALL] line=8330 fn=strip 
[CALL] line=8330 fn=str 
[CALL] line=8330 fn=get 
[CALL] line=8331 fn=strip 
[CALL] line=8331 fn=str 
[CALL] line=8333 fn=_doc_identity_is_compatible_with_current_text 
[CALL] line=8336 fn=str 
[CALL] line=8336 fn=get 
[IF] line=8340 cond=not _contract_segment_ok
[IF] line=8350 cond=isinstance(kb_context, dict)
[CALL] line=8350 fn=isinstance 
[IF] line=8380 cond=isinstance(real_kb_docs, dict)
[CALL] line=8380 fn=isinstance 
[CALL] line=8382 fn=get 
[CALL] line=8383 fn=get 
[IF] line=8387 cond=isinstance(_selected_doc, dict) and _selected_doc
[CALL] line=8387 fn=isinstance 
[CALL] line=8388 fn=strip 
[CALL] line=8388 fn=str 
[CALL] line=8389 fn=get 
[CALL] line=8390 fn=get 
[CALL] line=8391 fn=get 
[IF] line=8395 cond=str(user_text or '').strip()
[CALL] line=8395 fn=strip 
[CALL] line=8395 fn=str 
[CALL] line=8396 fn=_doc_identity_is_compatible_with_current_text 
[IF] line=8403 cond=not _docs_segment_ok
[IF] line=8421 cond=isinstance(kb_context, dict)
[CALL] line=8421 fn=isinstance 
[CALL] line=8445 fn=pop 
[CALL] line=8490 fn=bool 
[CALL] line=8491 fn=isinstance 
[CALL] line=8492 fn=bool 
[CALL] line=8492 fn=get 
[CALL] line=8494 fn=strip 
[CALL] line=8494 fn=str 
[CALL] line=8494 fn=get 
[CALL] line=8495 fn=strip 
[CALL] line=8495 fn=str 
[CALL] line=8495 fn=get 
[CALL] line=8497 fn=_doc_identity_is_compatible_with_current_text 
[CALL] line=8500 fn=str 
[CALL] line=8500 fn=get 
[IF] line=8508 cond=isinstance(operational_contract, dict)
[CALL] line=8508 fn=isinstance 
[CALL] line=8509 fn=bool 
[CALL] line=8512 fn=strip 
[CALL] line=8512 fn=str 
[CALL] line=8512 fn=get 
[CALL] line=8513 fn=strip 
[CALL] line=8513 fn=str 
[CALL] line=8513 fn=get 
[CALL] line=8514 fn=strip 
[CALL] line=8514 fn=str 
[CALL] line=8514 fn=get 
[CALL] line=8515 fn=strip 
[CALL] line=8515 fn=str 
[CALL] line=8515 fn=get 
[IF] line=8521 cond=not has_real_operational_context
[IF] line=8529 cond=selected_pack_id
[CALL] line=8530 fn=_platform_pack_material 
[CALL] line=8532 fn=isinstance 
[IF] line=8535 cond=has_real_operational_context
[CALL] line=8537 fn=strip 
[CALL] line=8537 fn=str 
[CALL] line=8537 fn=get 
[CALL] line=8538 fn=strip 
[CALL] line=8538 fn=str 
[CALL] line=8538 fn=get 
[CALL] line=8539 fn=strip 
[CALL] line=8539 fn=str 
[CALL] line=8539 fn=get 
[CALL] line=8540 fn=strip 
[CALL] line=8540 fn=str 
[CALL] line=8540 fn=get 
[IF] line=8543 cond=response_mode == 'DIRECT'
[CALL] line=8545 fn=strip 
[CALL] line=8545 fn=str 
[CALL] line=8545 fn=get 
[CALL] line=8546 fn=strip 
[CALL] line=8546 fn=str 
[CALL] line=8546 fn=get 
[CALL] line=8547 fn=strip 
[CALL] line=8547 fn=str 
[CALL] line=8547 fn=get 
[CALL] line=8548 fn=strip 
[CALL] line=8548 fn=str 
[CALL] line=8548 fn=get 
[CALL] line=8549 fn=strip 
[CALL] line=8549 fn=str 
[CALL] line=8549 fn=get 
[CALL] line=8553 fn=strip 
[CALL] line=8553 fn=str 
[CALL] line=8553 fn=get 
[CALL] line=8554 fn=strip 
[CALL] line=8554 fn=str 
[CALL] line=8554 fn=get 
[IF] line=8557 cond=_scene
[CALL] line=8559 fn=upper 
[CALL] line=8559 fn=strip 
[CALL] line=8559 fn=str 
[IF] line=8560 cond=has_real_operational_context and _runtime_material.get('runtime_long_text')
[CALL] line=8560 fn=get 
[IF] line=8562 cond=not has_real_operational_context
[CALL] line=8563 fn=pop 
[IF] line=8565 cond=has_real_operational_context and _runtime_material.get('runtime_short_reply')
[CALL] line=8565 fn=get 
[IF] line=8567 cond=not has_real_operational_context
[IF] line=8568 cond=response_mode == 'DIRECT' and hydrated_from_docs and (found_seg or found_sub or found_arch or operational_contract.get('has_practical_scene')) and _runtime_material.get('runtime_short_reply')
[CALL] line=8575 fn=get 
[CALL] line=8577 fn=get 
[IF] line=8580 cond=_runtime_material.get('runtime_compact_reply')
[CALL] line=8580 fn=get 
[CALL] line=8583 fn=bool 
[IF] line=8587 cond=current_turn_topic_reset
[IF] line=8590 cond=isinstance(operational_contract, dict)
[CALL] line=8590 fn=isinstance 
[CALL] line=8599 fn=bool 
[CALL] line=8604 fn=strip 
[CALL] line=8604 fn=str 
[CALL] line=8605 fn=strip 
[CALL] line=8605 fn=str 
[CALL] line=8606 fn=strip 
[CALL] line=8606 fn=str 
[CALL] line=8609 fn=upper 
[CALL] line=8609 fn=strip 
[CALL] line=8609 fn=str 
[CALL] line=8610 fn=lower 
[CALL] line=8610 fn=strip 
[CALL] line=8610 fn=str 
[CALL] line=8611 fn=upper 
[CALL] line=8611 fn=strip 
[CALL] line=8611 fn=str 
[IF] line=8613 cond=isinstance(operational_contract, dict)
[CALL] line=8613 fn=isinstance 
[IF] line=8618 cond=not response_mode
[CALL] line=8619 fn=_infer_response_mode_from_signals 
[IF] line=8633 cond=str(next_step or '').strip().upper() == 'SEND_LINK'
[CALL] line=8633 fn=upper 
[CALL] line=8633 fn=strip 
[CALL] line=8633 fn=str 
[IF] line=8635 cond=global_pack_scene_ready and str(question_type or '').strip().lower() not in ('punctual', 'continuity')
[CALL] line=8635 fn=lower 
[CALL] line=8635 fn=strip 
[CALL] line=8635 fn=str 
[IF] line=8639 cond=isinstance(operational_contract, dict)
[CALL] line=8639 fn=isinstance 
[IF] line=8641 cond=str(needs_clarify or '').strip().lower() == 'yes' or str(clarify_q or '').strip()
[CALL] line=8641 fn=lower 
[CALL] line=8641 fn=strip 
[CALL] line=8641 fn=str 
[CALL] line=8641 fn=strip 
[CALL] line=8641 fn=str 
[IF] line=8643 cond=str(question_type or '').strip().lower() in ('punctual', 'continuity')
[CALL] line=8643 fn=lower 
[CALL] line=8643 fn=strip 
[CALL] line=8643 fn=str 
[IF] line=8644 cond=response_mode == 'SCENE'
[IF] line=8646 cond=isinstance(operational_contract, dict)
[CALL] line=8646 fn=isinstance 
[IF] line=8648 cond=str(topic or '').strip().upper() in ('PRECO', 'TRIAL', 'ATIVAR', 'WHAT_IS', 'SOCIAL', 'VOZ')
[CALL] line=8648 fn=upper 
[CALL] line=8648 fn=strip 
[CALL] line=8648 fn=str 
[IF] line=8649 cond=response_mode == 'SCENE'
[CALL] line=8660 fn=isinstance 
[CALL] line=8661 fn=bool 
[CALL] line=8662 fn=get 
[CALL] line=8663 fn=get 
[CALL] line=8664 fn=strip 
[CALL] line=8664 fn=str 
[CALL] line=8664 fn=get 
[CALL] line=8665 fn=strip 
[CALL] line=8665 fn=str 
[CALL] line=8665 fn=get 
[CALL] line=8666 fn=list 
[CALL] line=8666 fn=get 
[CALL] line=8668 fn=bool 
[CALL] line=8669 fn=upper 
[CALL] line=8669 fn=strip 
[CALL] line=8669 fn=str 
[CALL] line=8670 fn=upper 
[CALL] line=8670 fn=strip 
[CALL] line=8670 fn=str 
[CALL] line=8671 fn=lower 
[CALL] line=8671 fn=strip 
[CALL] line=8671 fn=str 
[CALL] line=8672 fn=strip 
[CALL] line=8672 fn=str 
[IF] line=8676 cond=_contract_ready_for_scene
[CALL] line=8686 fn=_resolve_reply_size_policy 
[CALL] line=8692 fn=bool 
[CALL] line=8700 fn=_resolve_reply_size_policy 
[CALL] line=8721 fn=bool 
[CALL] line=8722 fn=strip 
[CALL] line=8722 fn=str 
[CALL] line=8722 fn=get 
[CALL] line=8723 fn=strip 
[CALL] line=8723 fn=str 
[CALL] line=8723 fn=get 
[CALL] line=8724 fn=list 
[CALL] line=8724 fn=get 
[CALL] line=8726 fn=bool 
[CALL] line=8727 fn=upper 
[CALL] line=8727 fn=strip 
[CALL] line=8727 fn=str 
[CALL] line=8727 fn=get 
[CALL] line=8728 fn=bool 
[CALL] line=8728 fn=get 
[IF] line=8732 cond=response_mode == 'SCENE' and (segment_for_prompt and kb_anchor_strong or global_pack_scene_ready or contract_hydrated_scene_ready) and contract_has_operational_base
[IF] line=8746 cond=response_mode in ('DIRECT', 'DISCOVERY', 'CLOSING')
[IF] line=8753 cond=isinstance(operational_contract, dict)
[CALL] line=8753 fn=isinstance 
[IF] line=8756 cond=isinstance(base_operational_contract, dict)
[CALL] line=8756 fn=isinstance 
[IF] line=8763 cond=isinstance(operational_contract, dict)
[CALL] line=8763 fn=isinstance 
[CALL] line=8764 fn=strip 
[CALL] line=8764 fn=str 
[CALL] line=8769 fn=get 
[CALL] line=8770 fn=get 
[CALL] line=8771 fn=get 
[CALL] line=8772 fn=get 
[CALL] line=8773 fn=get 
[CALL] line=8774 fn=get 
[CALL] line=8785 fn=lower 
[CALL] line=8785 fn=strip 
[CALL] line=8785 fn=str 
[CALL] line=8787 fn=bool 
[CALL] line=8793 fn=get 
[CALL] line=8798 fn=bool 
[CALL] line=8798 fn=get 
[CALL] line=8799 fn=bool 
[CALL] line=8800 fn=get 
[CALL] line=8801 fn=get 
[CALL] line=8808 fn=bool 
[IF] line=8814 cond=not isinstance(operational_contract, dict) or not operational_contract
[CALL] line=8814 fn=isinstance 
[CALL] line=8815 fn=locals 
[IF] line=8822 cond=platform_kb_mode and (not current_turn_topic_reset) and isinstance(operational_contract, dict) and selected_pack_id and (str(next_step or '').strip().upper() != 'SEND_LINK')
[CALL] line=8825 fn=isinstance 
[CALL] line=8827 fn=upper 
[CALL] line=8827 fn=strip 
[CALL] line=8827 fn=str 
[CALL] line=8829 fn=_platform_pack_material 
[CALL] line=8831 fn=isinstance 
[CALL] line=8835 fn=strip 
[CALL] line=8835 fn=str 
[CALL] line=8835 fn=get 
[CALL] line=8836 fn=strip 
[CALL] line=8836 fn=str 
[CALL] line=8836 fn=get 
[CALL] line=8837 fn=strip 
[CALL] line=8837 fn=str 
[CALL] line=8837 fn=get 
[CALL] line=8838 fn=strip 
[CALL] line=8838 fn=str 
[CALL] line=8838 fn=get 
[CALL] line=8839 fn=strip 
[CALL] line=8839 fn=str 
[CALL] line=8839 fn=get 
[CALL] line=8840 fn=strip 
[CALL] line=8840 fn=str 
[CALL] line=8840 fn=get 
[CALL] line=8842 fn=strip 
[CALL] line=8842 fn=str 
[CALL] line=8842 fn=get 
[IF] line=8844 cond=has_real_operational_context
[IF] line=8852 cond=response_mode == 'DIRECT'
[IF] line=8862 cond=_best_scene
[IF] line=8866 cond=has_real_operational_context
[CALL] line=8870 fn=pop 
[CALL] line=8871 fn=pop 
[CALL] line=8872 fn=pop 
[CALL] line=8873 fn=pop 
[CALL] line=8875 fn=pop 
[IF] line=8881 cond=operational_contract.get('runtime_short_reply')
[CALL] line=8881 fn=get 
[CALL] line=8883 fn=get 
[CALL] line=8884 fn=get 
[IF] line=8891 cond=_late_material_source
[CALL] line=8893 fn=bool 
[IF] line=8903 cond=platform_segment_key
[IF] line=8905 cond=has_real_operational_context and _late_runtime_long
[IF] line=8907 cond=has_real_operational_context and _late_runtime_short
[IF] line=8909 cond=has_real_operational_context and _late_reference
[IF] line=8913 cond=has_real_operational_context and str(question_type or '').strip().lower() not in ('punctual', 'continuity')
[CALL] line=8913 fn=lower 
[CALL] line=8913 fn=strip 
[CALL] line=8913 fn=str 
[IF] line=8919 cond=response_mode == 'SCENE'
[IF] line=8938 cond=bool(json_fail_safe_used) and free_mode and platform_kb_mode and (str(response_mode or '').strip().upper() == 'DIRECT') and (str(next_step or '').strip().upper() != 'SEND_LINK') and isinstance(operational_contract, dict)
[CALL] line=8939 fn=bool 
[CALL] line=8942 fn=upper 
[CALL] line=8942 fn=strip 
[CALL] line=8942 fn=str 
[CALL] line=8943 fn=upper 
[CALL] line=8943 fn=strip 
[CALL] line=8943 fn=str 
[CALL] line=8944 fn=isinstance 
[CALL] line=8947 fn=strip 
[CALL] line=8947 fn=str 
[CALL] line=8947 fn=get 
[CALL] line=8948 fn=strip 
[CALL] line=8948 fn=str 
[CALL] line=8948 fn=get 
[CALL] line=8949 fn=strip 
[CALL] line=8949 fn=str 
[CALL] line=8949 fn=get 
[CALL] line=8950 fn=strip 
[CALL] line=8950 fn=str 
[CALL] line=8950 fn=get 
[CALL] line=8951 fn=strip 
[CALL] line=8951 fn=str 
[CALL] line=8951 fn=get 
[IF] line=8954 cond=_safe_core
[CALL] line=8955 fn=_front_sanitize_lead_name_candidate 
[CALL] line=8956 fn=_front_sanitize_lead_name_candidate 
[CALL] line=8968 fn=get 
[CALL] line=8969 fn=get 
[CALL] line=8973 fn=strip 
[CALL] line=8973 fn=str 
[CALL] line=8977 fn=get 
[CALL] line=8978 fn=get 
[CALL] line=8982 fn=_humanize_reply_with_lead_context 
[CALL] line=8988 fn=_sanitize_user_facing_reply 
[CALL] line=8989 fn=strip 
[CALL] line=8989 fn=str 
[IF] line=8992 cond=_safe_reply
[CALL] line=9001 fn=bool 
[CALL] line=9002 fn=strip 
[CALL] line=9002 fn=str 
[CALL] line=9002 fn=get 
[CALL] line=9003 fn=list 
[CALL] line=9003 fn=get 
[IF] line=9006 cond=not _has_operational
[CALL] line=9007 fn=bool 
[IF] line=9008 cond=platform_kb_mode and isinstance(operational_contract, dict) and (not bool(operational_contract.get('hydrated_from_docs')))
[CALL] line=9010 fn=isinstance 
[CALL] line=9011 fn=bool 
[CALL] line=9011 fn=get 
[IF] line=9020 cond=isinstance(operational_contract, dict) and isinstance(base_operational_contract, dict) and (not str(operational_contract.get('operational_reference') or '').strip()) and (not list(operational_contract.get('operational_ritual') or []))
[CALL] line=9021 fn=isinstance 
[CALL] line=9022 fn=isinstance 
[CALL] line=9023 fn=strip 
[CALL] line=9023 fn=str 
[CALL] line=9023 fn=get 
[CALL] line=9024 fn=list 
[CALL] line=9024 fn=get 
[CALL] line=9027 fn=strip 
[CALL] line=9027 fn=str 
[CALL] line=9028 fn=get 
[CALL] line=9029 fn=strip 
[CALL] line=9029 fn=str 
[IF] line=9031 cond=base_ritual
[IF] line=9040 cond=not kb_anchor_strong and confidence == 'low' and _should_downgrade_premature_narrow_topic(topic=topic, confidence=confidence, ai_turns=ai_turns, effective_segment=segment_for_prompt, operational_family=operational_family, operational_reference='', reference_example=reference_example, reply_text=reply_text, next_step=next_step)
[CALL] line=9043 fn=_should_downgrade_premature_narrow_topic 
[IF] line=9058 cond=not clarify_q
[CALL] line=9059 fn=strip 
[CALL] line=9059 fn=str 
[IF] line=9065 cond=force_trial
[IF] line=9075 cond=bad in (reply_text or '').lower()
[CALL] line=9075 fn=lower 
[CALL] line=9077 fn=strip 
[CALL] line=9077 fn=sub 
[CALL] line=9078 fn=strip 
[CALL] line=9078 fn=sub 
[CALL] line=9084 fn=lower 
[CALL] line=9084 fn=strip 
[CALL] line=9084 fn=str 
[CALL] line=9084 fn=get 
[IF] line=9085 cond=name_use not in ('none', 'greet', 'empathy', 'clarify')
[CALL] line=9094 fn=any 
[CALL] line=9095 fn=upper 
[CALL] line=9095 fn=strip 
[CALL] line=9095 fn=str 
[CALL] line=9096 fn=upper 
[CALL] line=9096 fn=strip 
[CALL] line=9096 fn=str 
[CALL] line=9097 fn=upper 
[CALL] line=9097 fn=strip 
[CALL] line=9097 fn=str 
[CALL] line=9097 fn=get 
[IF] line=9099 cond=price_context_active
[CALL] line=9101 fn=strip 
[CALL] line=9101 fn=str 
[CALL] line=9102 fn=lower 
[CALL] line=9102 fn=str 
[IF] line=9104 cond=needs_price_repair
[CALL] line=9105 fn=_front_repair_price_reply 
[IF] line=9109 cond=str(repaired_price_reply or '').strip()
[CALL] line=9109 fn=strip 
[CALL] line=9109 fn=str 
[IF] line=9111 cond=not spoken_text
[IF] line=9123 cond=not free_mode and next_step != 'SEND_LINK'
[IF] line=9146 cond=str(reply_source or '').strip() == 'front_structured_python_assembly'
[CALL] line=9146 fn=strip 
[CALL] line=9146 fn=str 
[CALL] line=9147 fn=dict 
[CALL] line=9148 fn=bool 
[CALL] line=9148 fn=get 
[IF] line=9150 cond=_is_audio_policy
[CALL] line=9151 fn=min 
[CALL] line=9152 fn=int 
[CALL] line=9152 fn=get 
[CALL] line=9155 fn=min 
[CALL] line=9156 fn=int 
[CALL] line=9156 fn=get 
[CALL] line=9160 fn=min 
[CALL] line=9161 fn=int 
[CALL] line=9161 fn=get 
[CALL] line=9164 fn=min 
[CALL] line=9165 fn=int 
[CALL] line=9165 fn=get 
[CALL] line=9169 fn=_apply_reply_size_policy 
[CALL] line=9170 fn=_apply_reply_size_policy 
[CALL] line=9202 fn=len 
[IF] line=9209 cond=confidence not in ('high', 'medium', 'low')
[CALL] line=9212 fn=bool 
[CALL] line=9214 fn=strip 
[CALL] line=9214 fn=str 
[CALL] line=9216 fn=strip 
[CALL] line=9216 fn=str 
[CALL] line=9222 fn=bool 
[IF] line=9224 cond=discovery_resolved
[CALL] line=9238 fn=bool 
[IF] line=9240 cond=is_trial and next_step == 'SEND_LINK'
[IF] line=9251 cond=allow_send_link
[CALL] line=9253 fn=strip 
[CALL] line=9253 fn=str 
[CALL] line=9253 fn=get 
[IF] line=9254 cond=not base
[CALL] line=9255 fn=strip 
[CALL] line=9255 fn=getenv 
[CALL] line=9258 fn=strip 
[CALL] line=9258 fn=str 
[IF] line=9259 cond=base not in reply_text
[IF] line=9260 cond=reply_text
[CALL] line=9261 fn=find 
[IF] line=9262 cond=qpos != -1
[CALL] line=9263 fn=rstrip 
[IF] line=9264 cond=not reply_text.endswith(('.', '!', ':'))
[CALL] line=9264 fn=endswith 
[IF] line=9277 cond=next_step == 'SEND_LINK' and (not allow_send_link)
[IF] line=9280 cond=response_mode == 'CLOSING'
[CALL] line=9291 fn=bool 
[CALL] line=9296 fn=upper 
[CALL] line=9296 fn=strip 
[CALL] line=9296 fn=str 
[IF] line=9299 cond=identity_discovery_required
[IF] line=9303 cond=isinstance(kb_context, dict)
[CALL] line=9303 fn=isinstance 
[IF] line=9308 cond=use_direct_scene
[CALL] line=9309 fn=bool 
[CALL] line=9311 fn=get 
[CALL] line=9312 fn=get 
[CALL] line=9315 fn=_build_direct_scene_payload TARGET
[CALL] line=9319 fn=get 
[IF] line=9329 cond=direct_text
[CALL] line=9332 fn=_ensure_discovery_identity_request 
[IF] line=9340 cond=_identity_name_use == 'clarify'
[CALL] line=9351 fn=bool 
[CALL] line=9352 fn=upper 
[CALL] line=9352 fn=strip 
[CALL] line=9352 fn=str 
[CALL] line=9353 fn=isinstance 
[CALL] line=9354 fn=bool 
[CALL] line=9354 fn=get 
[IF] line=9359 cond=_continue_after_direct_scene
[RETURN] line=9364
[CALL] line=9385 fn=_front_sanitize_lead_name_candidate 
[CALL] line=9401 fn=len 
[CALL] line=9402 fn=isinstance 
[CALL] line=9403 fn=isinstance 
[IF] line=9411 cond=free_mode and next_step != 'SEND_LINK'
[IF] line=9412 cond=_needs_discovery_question(topic, confidence, operational_family, ai_turns, effective_segment=effective_segment, needs_clarify=needs_clarify, clarify_q=clarify_q, operational_reference='', reference_example=reference_example, reply_text=reply_text)
[CALL] line=9412 fn=_needs_discovery_question 
[CALL] line=9426 fn=strip 
[CALL] line=9426 fn=str 
[CALL] line=9426 fn=get 
[IF] line=9430 cond=not discovery_q
[CALL] line=9433 fn=bool 
[IF] line=9434 cond=not has_anchor
[CALL] line=9435 fn=strip 
[CALL] line=9435 fn=str 
[RETURN] line=9439
[CALL] line=9454 fn=len 
[CALL] line=9455 fn=isinstance 
[IF] line=9459 cond=response_mode == 'SCENE' and next_step != 'SEND_LINK' and bool((operational_contract if 'operational_contract' in locals() else {}).get('micro_scene_allowed'))
[CALL] line=9462 fn=bool 
[CALL] line=9462 fn=get 
[CALL] line=9462 fn=locals 
[CALL] line=9464 fn=strip 
[CALL] line=9464 fn=_generate_micro_scene_with_model 
[CALL] line=9466 fn=locals 
[IF] line=9469 cond=generated
[CALL] line=9470 fn=_is_live_operational_reply 
[CALL] line=9474 fn=locals 
[CALL] line=9477 fn=_is_show_micro_scene 
[CALL] line=9481 fn=locals 
[IF] line=9488 cond=generated
[CALL] line=9493 fn=bool 
[CALL] line=9494 fn=get 
[CALL] line=9494 fn=locals 
[CALL] line=9495 fn=strip 
[CALL] line=9495 fn=str 
[CALL] line=9496 fn=strip 
[CALL] line=9496 fn=str 
[CALL] line=9496 fn=get 
[CALL] line=9496 fn=locals 
[IF] line=9499 cond=upgraded and len(str(upgraded).strip()) > 40
[CALL] line=9499 fn=len 
[CALL] line=9499 fn=strip 
[CALL] line=9499 fn=str 
[IF] line=9500 cond=_upgrade_contract_strong
[CALL] line=9503 fn=bool 
[CALL] line=9509 fn=bool 
[IF] line=9514 cond=keep_upgraded
[IF] line=9524 cond=allow_scene_runtime and (not generated or len(str(generated).strip()) < 40)
[CALL] line=9524 fn=len 
[CALL] line=9524 fn=strip 
[CALL] line=9524 fn=str 
[CALL] line=9525 fn=_compose_grounded_scene_with_progression TARGET
[CALL] line=9527 fn=locals 
[IF] line=9531 cond=not structured
[CALL] line=9532 fn=_build_structural_last_resort_reply 
[CALL] line=9534 fn=locals 
[IF] line=9537 cond=structured
[CALL] line=9538 fn=_is_live_operational_reply 
[CALL] line=9542 fn=locals 
[CALL] line=9544 fn=_is_show_micro_scene 
[CALL] line=9548 fn=locals 
[CALL] line=9572 fn=bool 
[CALL] line=9575 fn=isinstance 
[CALL] line=9574 fn=get 
[CALL] line=9580 fn=isinstance 
[CALL] line=9579 fn=get 
[IF] line=9585 cond=generated_show and operational_upgrade_allowed
[IF] line=9589 cond=generated and operational_upgrade_allowed
[IF] line=9593 cond=allow_scene_runtime and structured_show
[IF] line=9597 cond=allow_scene_runtime and structured_live and (not _contract_strong)
[IF] line=9601 cond=allow_scene_runtime and structured_live and _contract_strong
[CALL] line=9603 fn=strip 
[CALL] line=9603 fn=_compose_grounded_scene_with_progression TARGET
[CALL] line=9605 fn=locals 
[CALL] line=9608 fn=strip 
[CALL] line=9608 fn=_build_structural_last_resort_reply 
[CALL] line=9610 fn=locals 
[IF] line=9613 cond=forced_scene
[IF] line=9622 cond=response_mode == 'DIRECT' and str(reply_text or '').strip() and (len(str(reply_text or '').strip()) >= 40)
[CALL] line=9624 fn=strip 
[CALL] line=9624 fn=str 
[CALL] line=9625 fn=len 
[CALL] line=9625 fn=strip 
[CALL] line=9625 fn=str 
[CALL] line=9630 fn=strip 
[CALL] line=9630 fn=str 
[IF] line=9632 cond=not str(reply_source or '').strip()
[CALL] line=9632 fn=strip 
[CALL] line=9632 fn=str 
[CALL] line=9636 fn=strip 
[CALL] line=9636 fn=str 
[CALL] line=9640 fn=bool 
[CALL] line=9644 fn=bool 
[CALL] line=9644 fn=get 
[CALL] line=9644 fn=locals 
[IF] line=9648 cond=allow_kb_runtime_fallback
[CALL] line=9649 fn=_build_kb_anchor_reply 
[CALL] line=9653 fn=locals 
[CALL] line=9653 fn=locals 
[IF] line=9656 cond=allow_kb_runtime_fallback and kb_reply
[CALL] line=9659 fn=strip 
[CALL] line=9659 fn=str 
[CALL] line=9660 fn=_looks_like_technical_output 
[IF] line=9662 cond=rescue_needed
[IF] line=9664 cond=_looks_like_technical_output(spoken_text) or not str(spoken_text or '').strip()
[CALL] line=9664 fn=_looks_like_technical_output 
[CALL] line=9664 fn=strip 
[CALL] line=9664 fn=str 
[IF] line=9666 cond=rescue_needed
[IF] line=9669 cond=next_step != 'SEND_LINK'
[IF] line=9673 cond=not reply_text
[IF] line=9675 cond=not reply_text and question and (not effective_segment)
[IF] line=9677 cond=not spoken_text
[CALL] line=9682 fn=bool 
[CALL] line=9683 fn=upper 
[CALL] line=9683 fn=str 
[CALL] line=9684 fn=lower 
[CALL] line=9684 fn=str 
[IF] line=9689 cond=operational_reply and next_step != 'SEND_LINK'
[CALL] line=9692 fn=_apply_reply_size_policy 
[CALL] line=9693 fn=_apply_reply_size_policy 
[CALL] line=9696 fn=strip 
[CALL] line=9696 fn=str 
[CALL] line=9697 fn=strip 
[CALL] line=9697 fn=str 
[CALL] line=9698 fn=_try_parse_kb_json 
[CALL] line=9699 fn=_sanitize_unverified_time_claims 
[CALL] line=9700 fn=_sanitize_unverified_time_claims 
[IF] line=9703 cond=_looks_like_bureaucratic_stub(reply_text)
[CALL] line=9703 fn=_looks_like_bureaucratic_stub 
[IF] line=9705 cond=allow_kb_runtime_fallback
[CALL] line=9706 fn=_build_kb_anchor_reply 
[CALL] line=9710 fn=locals 
[CALL] line=9710 fn=locals 
[IF] line=9718 cond=_looks_like_bureaucratic_stub(spoken_text)
[CALL] line=9718 fn=_looks_like_bureaucratic_stub 
[IF] line=9720 cond=allow_kb_runtime_fallback
[CALL] line=9721 fn=_build_kb_anchor_reply 
[CALL] line=9725 fn=locals 
[CALL] line=9725 fn=locals 
[CALL] line=9736 fn=_de_genericize_free_mode_text 
[CALL] line=9737 fn=_de_genericize_free_mode_text 
[CALL] line=9741 fn=strip 
[CALL] line=9741 fn=str 
[IF] line=9745 cond=str(reply_source or '').strip() == 'front_ia_soberana' and (ia_accepted or _is_show_micro_scene(text=reply_text, operational_reference='', reference_example=reference_example, contract=operational_contract if 'operational_contract' in locals() else {}))
[CALL] line=9746 fn=strip 
[CALL] line=9746 fn=str 
[CALL] line=9747 fn=_is_show_micro_scene 
[CALL] line=9751 fn=locals 
[IF] line=9758 cond=not ia_locked
[CALL] line=9760 fn=strip 
[CALL] line=9760 fn=str 
[CALL] line=9762 fn=strip 
[CALL] line=9762 fn=str 
[CALL] line=9763 fn=get 
[CALL] line=9763 fn=locals 
[CALL] line=9764 fn=strip 
[CALL] line=9764 fn=str 
[CALL] line=9768 fn=strip 
[CALL] line=9768 fn=str 
[CALL] line=9769 fn=strip 
[CALL] line=9769 fn=str 
[IF] line=9774 cond=reply_text and len(reply_text.strip()) >= 60 and _is_show_micro_scene(text=reply_text, operational_reference='', reference_example=reference_example, contract=operational_contract if 'operational_contract' in locals() else {})
[CALL] line=9776 fn=len 
[CALL] line=9776 fn=strip 
[CALL] line=9777 fn=_is_show_micro_scene 
[CALL] line=9781 fn=locals 
[CALL] line=9784 fn=strip 
[IF] line=9793 cond=not ia_locked and response_mode == 'SCENE'
[CALL] line=9795 fn=_compose_operational_reply 
[CALL] line=9800 fn=locals 
[IF] line=9802 cond=composed_reply
[IF] line=9804 cond=not spoken_text
[CALL] line=9810 fn=_is_live_operational_reply 
[CALL] line=9814 fn=locals 
[IF] line=9816 cond=final_live and reply_text
[CALL] line=9817 fn=strip 
[CALL] line=9817 fn=str 
[CALL] line=9822 fn=info 
[CALL] line=9824 fn=strip 
[CALL] line=9824 fn=str 
[CALL] line=9825 fn=bool 
[CALL] line=9826 fn=_is_live_operational_reply 
[CALL] line=9830 fn=locals 
[CALL] line=9833 fn=len 
[CALL] line=9833 fn=str 
[CALL] line=9839 fn=wrap_show_response 
[IF] line=9844 cond=allow_kb_runtime_fallback and kb_reply
[CALL] line=9846 fn=strip 
[CALL] line=9846 fn=str 
[CALL] line=9847 fn=_looks_like_technical_output 
[IF] line=9849 cond=rescue_needed
[IF] line=9851 cond=_looks_like_technical_output(spoken_text) or not str(spoken_text or '').strip()
[CALL] line=9851 fn=_looks_like_technical_output 
[CALL] line=9851 fn=strip 
[CALL] line=9851 fn=str 
[IF] line=9853 cond=rescue_needed
[IF] line=9856 cond=next_step != 'SEND_LINK'
[IF] line=9868 cond=reply_text and '?' in reply_text
[IF] line=9869 cond=not _should_allow_question(user_text=user_text, kb_context=kb_context if isinstance(kb_context, dict) else {}, reply_text=reply_text, understanding={'topic': topic, 'confidence': confidence}, decider=decider if isinstance(decider, dict) else {})
[CALL] line=9869 fn=_should_allow_question 
[CALL] line=9871 fn=isinstance 
[CALL] line=9874 fn=isinstance 
[CALL] line=9876 fn=_strip_trailing_question 
[IF] line=9877 cond=spoken_text and '?' in spoken_text
[IF] line=9878 cond=not _should_allow_question(user_text=user_text, kb_context=kb_context if isinstance(kb_context, dict) else {}, reply_text=spoken_text, understanding={'topic': topic, 'confidence': confidence}, decider=decider if isinstance(decider, dict) else {})
[CALL] line=9878 fn=_should_allow_question 
[CALL] line=9880 fn=isinstance 
[CALL] line=9883 fn=isinstance 
[CALL] line=9885 fn=_strip_trailing_question 
[CALL] line=9886 fn=strip 
[CALL] line=9886 fn=sub 
[CALL] line=9886 fn=str 
[CALL] line=9887 fn=strip 
[CALL] line=9887 fn=sub 
[CALL] line=9887 fn=str 
[CALL] line=9891 fn=_sanitize_user_facing_reply 
[CALL] line=9892 fn=_sanitize_user_facing_reply 
[CALL] line=9894 fn=_apply_reply_size_policy 
[CALL] line=9895 fn=_apply_reply_size_policy 
[IF] line=9897 cond=_looks_like_technical_output(reply_text)
[CALL] line=9897 fn=_looks_like_technical_output 
[IF] line=9899 cond=allow_scene_runtime
[CALL] line=9900 fn=_build_kb_anchor_reply 
[CALL] line=9904 fn=locals 
[CALL] line=9904 fn=locals 
[CALL] line=9906 fn=_build_contract_consequence 
[CALL] line=9907 fn=locals 
[CALL] line=9908 fn=locals 
[IF] line=9911 cond=_looks_like_technical_output(spoken_text)
[CALL] line=9911 fn=_looks_like_technical_output 
[IF] line=9914 cond=not spoken_text
[CALL] line=9920 fn=strip 
[CALL] line=9920 fn=str 
[IF] line=9922 cond=allow_scene_runtime and (not _rt or len(_rt) < 40)
[CALL] line=9922 fn=len 
[IF] line=9925 cond=operational_contract
[CALL] line=9926 fn=_build_kb_show_reply 
[CALL] line=9927 fn=isinstance 
[IF] line=9935 cond=(not forced or len(forced.strip()) < 40) and base_operational_contract
[CALL] line=9935 fn=len 
[CALL] line=9935 fn=strip 
[CALL] line=9936 fn=_build_kb_show_reply 
[CALL] line=9937 fn=isinstance 
[IF] line=9945 cond=not forced or len(forced.strip()) < 40
[CALL] line=9945 fn=len 
[CALL] line=9945 fn=strip 
[CALL] line=9946 fn=_build_kb_anchor_reply 
[IF] line=9953 cond=forced and len(forced.strip()) >= 40
[CALL] line=9953 fn=len 
[CALL] line=9953 fn=strip 
[IF] line=9955 cond=not spoken_text or len(str(spoken_text or '').strip()) < 40
[CALL] line=9955 fn=len 
[CALL] line=9955 fn=strip 
[CALL] line=9955 fn=str 
[IF] line=9962 cond=_final_candidate and (not reply_text or len(reply_text.strip()) < 40)
[CALL] line=9963 fn=len 
[CALL] line=9963 fn=strip 
[IF] line=9968 cond=allow_scene_runtime and (not str(reply_text or '').strip())
[CALL] line=9968 fn=strip 
[CALL] line=9968 fn=str 
[CALL] line=9969 fn=_split_scene_steps 
[IF] line=9971 cond=len(steps) >= 2
[CALL] line=9971 fn=len 
[CALL] line=9972 fn=_render_progressive_operational_flow 
[IF] line=9976 cond=rebuilt
[CALL] line=9982 fn=info 
[CALL] line=9985 fn=_is_live_operational_reply 
[CALL] line=9989 fn=locals 
[CALL] line=9991 fn=len 
[CALL] line=9996 fn=bool 
[CALL] line=9997 fn=_is_live_operational_reply 
[CALL] line=10001 fn=locals 
[CALL] line=10005 fn=_operational_density_score 
[CALL] line=10009 fn=strip 
[CALL] line=10009 fn=str 
[CALL] line=10009 fn=get 
[CALL] line=10009 fn=locals 
[CALL] line=10010 fn=strip 
[CALL] line=10010 fn=str 
[CALL] line=10010 fn=get 
[CALL] line=10010 fn=locals 
[CALL] line=10013 fn=strip 
[CALL] line=10013 fn=str 
[CALL] line=10015 fn=bool 
[CALL] line=10016 fn=_is_show_micro_scene 
[CALL] line=10020 fn=locals 
[CALL] line=10024 fn=bool 
[CALL] line=10025 fn=_is_live_operational_reply 
[CALL] line=10029 fn=locals 
[CALL] line=10033 fn=bool 
[CALL] line=10034 fn=get 
[CALL] line=10034 fn=locals 
[CALL] line=10036 fn=strip 
[CALL] line=10036 fn=str 
[CALL] line=10036 fn=get 
[CALL] line=10036 fn=locals 
[CALL] line=10039 fn=bool 
[CALL] line=10040 fn=isinstance 
[CALL] line=10040 fn=locals 
[CALL] line=10041 fn=get 
[CALL] line=10041 fn=locals 
[CALL] line=10042 fn=get 
[CALL] line=10042 fn=locals 
[CALL] line=10045 fn=_looks_explanatory_reply 
[CALL] line=10046 fn=str 
[CALL] line=10049 fn=locals 
[CALL] line=10052 fn=strip 
[CALL] line=10052 fn=str 
[IF] line=10054 cond=response_mode == 'DIRECT'
[CALL] line=10055 fn=bool 
[CALL] line=10063 fn=len 
[CALL] line=10063 fn=strip 
[CALL] line=10063 fn=str 
[CALL] line=10064 fn=_looks_like_technical_output 
[IF] line=10067 cond=_contract_strong or _contract_allows_operational_output
[CALL] line=10068 fn=bool 
[CALL] line=10070 fn=bool 
[CALL] line=10086 fn=lower 
[CALL] line=10086 fn=strip 
[CALL] line=10086 fn=str 
[IF] line=10092 cond=_should_force_continuity
[CALL] line=10093 fn=strip 
[CALL] line=10093 fn=str 
[CALL] line=10094 fn=_front_build_continuity_reply_from_platform_kb 
[CALL] line=10096 fn=isinstance 
[CALL] line=10103 fn=bool 
[CALL] line=10105 fn=bool 
[IF] line=10114 cond=_continuity_reply and len(_continuity_reply) >= 30 and (_continuity_reply != _continuity_current_reply)
[CALL] line=10116 fn=len 
[IF] line=10125 cond=accepted
[CALL] line=10126 fn=strip 
[CALL] line=10126 fn=str 
[CALL] line=10127 fn=strip 
[CALL] line=10127 fn=str 
[IF] line=10130 cond=reply_source != 'front_continuity_facts'
[IF] line=10133 cond=not accepted
[CALL] line=10134 fn=strip 
[CALL] line=10134 fn=str 
[CALL] line=10136 fn=bool 
[CALL] line=10137 fn=_is_show_micro_scene 
[CALL] line=10141 fn=locals 
[CALL] line=10145 fn=bool 
[CALL] line=10146 fn=_is_live_operational_reply 
[CALL] line=10150 fn=locals 
[CALL] line=10154 fn=_looks_explanatory_reply 
[CALL] line=10158 fn=locals 
[CALL] line=10161 fn=_looks_explanatory_reply 
[CALL] line=10165 fn=locals 
[IF] line=10168 cond=response_mode == 'DIRECT'
[CALL] line=10169 fn=bool 
[CALL] line=10170 fn=len 
[CALL] line=10170 fn=strip 
[CALL] line=10170 fn=str 
[CALL] line=10171 fn=_looks_like_technical_output 
[IF] line=10173 cond=_contract_strong or _contract_allows_operational_output
[CALL] line=10174 fn=bool 
[IF] line=10175 cond=int(ai_turns or 0) > 0
[CALL] line=10175 fn=int 
[CALL] line=10176 fn=bool 
[CALL] line=10177 fn=len 
[CALL] line=10177 fn=strip 
[CALL] line=10177 fn=str 
[CALL] line=10178 fn=_looks_like_technical_output 
[CALL] line=10181 fn=bool 
[CALL] line=10184 fn=strip 
[CALL] line=10184 fn=str 
[IF] line=10187 cond=_accept_current
[IF] line=10189 cond=(_contract_strong or _contract_allows_operational_output) and str(reply_source or '').strip() not in ('front_ia_soberana', 'front_operational_upgrade')
[CALL] line=10191 fn=strip 
[CALL] line=10191 fn=str 
[IF] line=10196 cond=not current_text or len(current_text) < 40 or _looks_like_technical_output(current_text) or (_contract_strong and current_is_mild)
[CALL] line=10198 fn=len 
[CALL] line=10199 fn=_looks_like_technical_output 
[CALL] line=10203 fn=strip 
[CALL] line=10203 fn=_compose_grounded_scene_with_progression TARGET
[CALL] line=10205 fn=locals 
[CALL] line=10208 fn=strip 
[CALL] line=10208 fn=_build_structural_last_resort_reply 
[CALL] line=10210 fn=locals 
[IF] line=10214 cond=fallback
[CALL] line=10229 fn=isinstance 
[CALL] line=10230 fn=upper 
[CALL] line=10230 fn=strip 
[CALL] line=10230 fn=str 
[CALL] line=10232 fn=get 
[CALL] line=10236 fn=_front_build_structured_assembly_reply TARGET
[CALL] line=10238 fn=locals 
[CALL] line=10239 fn=isinstance 
[CALL] line=10240 fn=isinstance 
[CALL] line=10246 fn=_front_sanitize_lead_name_candidate 
[IF] line=10260 cond=structured_assembly_result and structured_assembly_result.get('replyText')
[CALL] line=10260 fn=get 
[CALL] line=10261 fn=strip 
[CALL] line=10261 fn=str 
[CALL] line=10261 fn=get 
[CALL] line=10262 fn=strip 
[CALL] line=10262 fn=str 
[CALL] line=10262 fn=get 
[CALL] line=10269 fn=info 
[CALL] line=10271 fn=strip 
[CALL] line=10271 fn=str 
[CALL] line=10273 fn=len 
[CALL] line=10273 fn=str 
[CALL] line=10274 fn=locals 
[CALL] line=10275 fn=locals 
[IF] line=10279 cond=response_mode == 'DISCOVERY'
[CALL] line=10280 fn=strip 
[CALL] line=10280 fn=str 
[CALL] line=10282 fn=_strip_trailing_question 
[CALL] line=10284 fn=strip 
[CALL] line=10284 fn=str 
[IF] line=10287 cond=response_mode == 'DISCOVERY'
[CALL] line=10288 fn=bool 
[CALL] line=10289 fn=bool 
[IF] line=10291 cond=missing_name or missing_segment
[IF] line=10292 cond=not _has_question(reply_text)
[CALL] line=10292 fn=_has_question 
[IF] line=10300 cond='?' in reply_text
[CALL] line=10301 fn=split 
[IF] line=10302 cond=len(parts) > 2
[CALL] line=10302 fn=len 
[CALL] line=10303 fn=strip 
[CALL] line=10320 fn=strip 
[CALL] line=10320 fn=str 
[CALL] line=10326 fn=strip 
[CALL] line=10326 fn=str 
[IF] line=10333 cond=_context_segment_raw and (not str(segment_hint or '').strip())
[CALL] line=10333 fn=strip 
[CALL] line=10333 fn=str 
[IF] line=10336 cond=isinstance(operational_contract, dict) and _context_segment_raw and (not str(operational_contract.get('segment') or '').strip())
[CALL] line=10337 fn=isinstance 
[CALL] line=10339 fn=strip 
[CALL] line=10339 fn=str 
[CALL] line=10339 fn=get 
[CALL] line=10343 fn=_front_sanitize_lead_name_candidate 
[IF] line=10353 cond=reply_text and _context_lead_name
[CALL] line=10354 fn=_humanize_reply_with_lead_context 
[IF] line=10370 cond=str(reply_source or '').strip() == 'front_structured_python_assembly'
[CALL] line=10370 fn=strip 
[CALL] line=10370 fn=str 
[CALL] line=10371 fn=isinstance 
[CALL] line=10372 fn=bool 
[CALL] line=10372 fn=get 
[CALL] line=10373 fn=isinstance 
[CALL] line=10374 fn=upper 
[CALL] line=10374 fn=strip 
[CALL] line=10374 fn=str 
[CALL] line=10375 fn=upper 
[CALL] line=10375 fn=strip 
[CALL] line=10375 fn=str 
[CALL] line=10377 fn=bool 
[CALL] line=10389 fn=get 
[CALL] line=10390 fn=get 
[IF] line=10394 cond=_technical_direct_platform_kb
[CALL] line=10395 fn=_front_trim_to_complete_sentence 
[CALL] line=10399 fn=_front_trim_to_complete_sentence 
[CALL] line=10408 fn=strip 
[CALL] line=10408 fn=str 
[CALL] line=10411 fn=strip 
[CALL] line=10411 fn=str 
[CALL] line=10416 fn=info 
[CALL] line=10419 fn=len 
[CALL] line=10428 fn=_front_trim_to_complete_sentence 
[CALL] line=10432 fn=_front_trim_to_complete_sentence 
[CALL] line=10444 fn=strip 
[CALL] line=10444 fn=str 
[CALL] line=10447 fn=isinstance 
[CALL] line=10447 fn=get 
[IF] line=10451 cond=str(next_step or '').strip().upper() != 'SEND_LINK' and (not bool(has_name) or not bool(effective_segment or segment_for_prompt or segment_hint)) and _identity_question and ('?' not in str(reply_text or ''))
[CALL] line=10452 fn=upper 
[CALL] line=10452 fn=strip 
[CALL] line=10452 fn=str 
[CALL] line=10453 fn=bool 
[CALL] line=10453 fn=bool 
[CALL] line=10455 fn=str 
[CALL] line=10457 fn=strip 
[CALL] line=10457 fn=rstrip 
[CALL] line=10457 fn=str 
[CALL] line=10484 fn=len 
[CALL] line=10486 fn=isinstance 
[CALL] line=10487 fn=locals 
[CALL] line=10489 fn=_front_sanitize_lead_name_candidate 
[IF] line=10502 cond=decider_only and isinstance(decider, dict)
[CALL] line=10502 fn=isinstance 
[CALL] line=10506 fn=get 
[IF] line=10507 cond=not isinstance(am, dict)
[CALL] line=10507 fn=isinstance 
[CALL] line=10509 fn=isinstance 
[CALL] line=10510 fn=str 
[CALL] line=10510 fn=get 
[CALL] line=10511 fn=int 
[CALL] line=10511 fn=get 
[CALL] line=10512 fn=int 
[CALL] line=10512 fn=get 
[CALL] line=10513 fn=bool 
[CALL] line=10513 fn=get 
[CALL] line=10514 fn=bool 
[CALL] line=10514 fn=get 
[CALL] line=10515 fn=bool 
[CALL] line=10516 fn=isinstance 
[IF] line=10517 cond=sar
[CALL] line=10518 fn=str 
[CALL] line=10518 fn=get 
[CALL] line=10519 fn=str 
[CALL] line=10519 fn=get 
[CALL] line=10520 fn=str 
[CALL] line=10520 fn=get 
[CALL] line=10521 fn=str 
[CALL] line=10521 fn=get 
[CALL] line=10549 fn=isinstance 
[CALL] line=10552 fn=isinstance 
[CALL] line=10553 fn=bool 
[CALL] line=10553 fn=get 
[CALL] line=10554 fn=strip 
[CALL] line=10554 fn=str 
[CALL] line=10555 fn=upper 
[CALL] line=10555 fn=strip 
[CALL] line=10555 fn=str 
[CALL] line=10556 fn=upper 
[CALL] line=10556 fn=strip 
[CALL] line=10556 fn=str 
[CALL] line=10558 fn=bool 
[CALL] line=10571 fn=get 
[CALL] line=10572 fn=get 
[CALL] line=10574 fn=isinstance 
[CALL] line=10575 fn=len 
[CALL] line=10575 fn=strip 
[IF] line=10578 cond=_is_technical_direct_exit
[CALL] line=10579 fn=strip 
[CALL] line=10579 fn=str 
[CALL] line=10580 fn=get 
[CALL] line=10580 fn=locals 
[CALL] line=10583 fn=strip 
[CALL] line=10583 fn=str 
[CALL] line=10584 fn=get 
[CALL] line=10584 fn=locals 
[CALL] line=10590 fn=len 
[CALL] line=10591 fn=strip 
[CALL] line=10591 fn=str 
[CALL] line=10595 fn=len 
[CALL] line=10596 fn=strip 
[CALL] line=10596 fn=str 
[IF] line=10599 cond=len(_preserved_reply) >= 700
[CALL] line=10599 fn=len 
[IF] line=10612 cond=_safe_preserved_reply.startswith('{') or _safe_preserved_reply.startswith('```')
[CALL] line=10612 fn=startswith 
[CALL] line=10612 fn=startswith 
[CALL] line=10613 fn=strip 
[CALL] line=10614 fn=_unwrap_front_json_envelope 
[IF] line=10618 cond=len(_unwrapped_reply) >= max(700, int(len(_preserved_reply) * 0.9))
[CALL] line=10618 fn=len 
[CALL] line=10618 fn=max 
[CALL] line=10618 fn=int 
[CALL] line=10618 fn=len 
[CALL] line=10621 fn=search 
[IF] line=10626 cond=_m
[CALL] line=10627 fn=str 
[CALL] line=10627 fn=group 
[CALL] line=10628 fn=strip 
[CALL] line=10628 fn=sub 
[IF] line=10634 cond=_candidate
[IF] line=10637 cond=_safe_preserved_spoken.startswith('{') or _safe_preserved_spoken.startswith('```')
[CALL] line=10637 fn=startswith 
[CALL] line=10637 fn=startswith 
[CALL] line=10638 fn=strip 
[CALL] line=10639 fn=_unwrap_front_json_envelope 
[IF] line=10643 cond=len(_unwrapped_spoken) >= max(700, int(len(_preserved_spoken) * 0.9))
[CALL] line=10643 fn=len 
[CALL] line=10643 fn=max 
[CALL] line=10643 fn=int 
[CALL] line=10643 fn=len 
[CALL] line=10646 fn=search 
[IF] line=10651 cond=_m
[CALL] line=10652 fn=str 
[CALL] line=10652 fn=group 
[CALL] line=10653 fn=strip 
[CALL] line=10653 fn=sub 
[IF] line=10659 cond=_candidate
[CALL] line=10676 fn=_front_remove_unsafe_nominal_opening 
[CALL] line=10680 fn=_front_remove_unsafe_nominal_opening 
[CALL] line=10694 fn=strip 
[CALL] line=10694 fn=str 
[CALL] line=10699 fn=isinstance 
[CALL] line=10698 fn=get 
[CALL] line=10705 fn=bool 
[CALL] line=10706 fn=bool 
[CALL] line=10707 fn=bool 
[IF] line=10710 cond=str(next_step or '').strip().upper() != 'SEND_LINK' and _missing_identity and _identity_question and (_front_normalize_identity_text(_identity_question) not in _front_normalize_identity_text(_safe_preserved_reply))
[CALL] line=10711 fn=upper 
[CALL] line=10711 fn=strip 
[CALL] line=10711 fn=str 
[CALL] line=10714 fn=_front_normalize_identity_text 
[CALL] line=10715 fn=_front_normalize_identity_text 
[CALL] line=10719 fn=max 
[CALL] line=10721 fn=len 
[CALL] line=10721 fn=len 
[CALL] line=10723 fn=_front_trim_to_complete_sentence 
[CALL] line=10727 fn=strip 
[CALL] line=10735 fn=_front_remove_unsafe_nominal_opening 
[CALL] line=10739 fn=_front_remove_unsafe_nominal_opening 
[CALL] line=10747 fn=strip 
[CALL] line=10747 fn=str 
[CALL] line=10752 fn=isinstance 
[CALL] line=10751 fn=get 
[CALL] line=10758 fn=bool 
[CALL] line=10759 fn=bool 
[CALL] line=10760 fn=bool 
[IF] line=10763 cond=str(next_step or '').strip().upper() != 'SEND_LINK' and _missing_identity and _identity_question and (_front_normalize_identity_text(_identity_question) not in _front_normalize_identity_text(_safe_preserved_reply))
[CALL] line=10764 fn=upper 
[CALL] line=10764 fn=strip 
[CALL] line=10764 fn=str 
[CALL] line=10767 fn=_front_normalize_identity_text 
[CALL] line=10768 fn=_front_normalize_identity_text 
[CALL] line=10772 fn=max 
[CALL] line=10774 fn=len 
[CALL] line=10774 fn=len 
[CALL] line=10776 fn=_front_trim_to_complete_sentence 
[CALL] line=10780 fn=strip 
[CALL] line=10787 fn=_front_trim_to_complete_sentence 
[CALL] line=10791 fn=_front_trim_to_complete_sentence 
[IF] line=10797 cond=out['replyText'] and out['replyText'][-1] not in '.!?'
[CALL] line=10798 fn=rstrip 
[IF] line=10800 cond=out['spokenText'] and out['spokenText'][-1] not in '.!?'
[CALL] line=10801 fn=rstrip 
[IF] line=10803 cond=_reply_probe.startswith('{') or _reply_probe.startswith('```')
[CALL] line=10803 fn=startswith 
[CALL] line=10803 fn=startswith 
[CALL] line=10804 fn=_unwrap_front_json_envelope 
[IF] line=10806 cond=_spoken_probe.startswith('{') or _spoken_probe.startswith('```')
[CALL] line=10806 fn=startswith 
[CALL] line=10806 fn=startswith 
[CALL] line=10807 fn=_unwrap_front_json_envelope 
[CALL] line=10810 fn=_front_remove_unsafe_nominal_opening 
[CALL] line=10814 fn=_front_remove_unsafe_nominal_opening 
[CALL] line=10822 fn=_front_remove_unsafe_nominal_opening 
[CALL] line=10826 fn=_front_remove_unsafe_nominal_opening 
[CALL] line=10833 fn=_front_trim_to_complete_sentence 
[CALL] line=10837 fn=_front_trim_to_complete_sentence 
[CALL] line=10861 fn=lower 
[CALL] line=10861 fn=strip 
[CALL] line=10861 fn=str 
[CALL] line=10874 fn=len 
[CALL] line=10874 fn=strip 
[CALL] line=10874 fn=str 
[CALL] line=10874 fn=get 
[CALL] line=10876 fn=bool 
[CALL] line=10877 fn=isinstance 
[CALL] line=10878 fn=get 
[IF] line=10891 cond=_should_force_continuity
[CALL] line=10892 fn=strip 
[CALL] line=10892 fn=str 
[CALL] line=10892 fn=get 
[CALL] line=10893 fn=_front_build_continuity_reply_from_platform_kb 
[CALL] line=10895 fn=isinstance 
[CALL] line=10897 fn=locals 
[CALL] line=10902 fn=bool 
[CALL] line=10904 fn=bool 
[IF] line=10913 cond=_continuity_reply and len(_continuity_reply) >= 30 and (_continuity_reply != _continuity_current_reply)
[CALL] line=10915 fn=len 
[CALL] line=10921 fn=info 
[CALL] line=10923 fn=upper 
[CALL] line=10923 fn=strip 
[CALL] line=10923 fn=str 
[CALL] line=10925 fn=len 
[CALL] line=10931 fn=_sanitize_front_result_payload 
[CALL] line=10933 fn=info 
[CALL] line=10936 fn=len 
[CALL] line=10936 fn=str 
[CALL] line=10936 fn=get 
[CALL] line=10937 fn=len 
[CALL] line=10937 fn=str 
[CALL] line=10937 fn=get 
[CALL] line=10938 fn=len 
[RETURN] line=10943
[CALL] line=10947 fn=info 
[CALL] line=10951 fn=locals 
[CALL] line=10952 fn=locals 
[CALL] line=10953 fn=locals 
[CALL] line=10957 fn=len 
[CALL] line=10960 fn=locals 
[CALL] line=10961 fn=locals 
[CALL] line=10962 fn=locals 
[CALL] line=10962 fn=isinstance 
[CALL] line=10962 fn=bool 
[CALL] line=10962 fn=get 
[CALL] line=10984 fn=_sanitize_front_result_payload 
[CALL] line=10986 fn=strip 
[CALL] line=10986 fn=str 
[CALL] line=10986 fn=get 
[CALL] line=10987 fn=strip 
[CALL] line=10987 fn=str 
[CALL] line=10987 fn=get 
[IF] line=10989 cond=_free_reply.startswith('{') or _free_reply.startswith('```')
[CALL] line=10989 fn=startswith 
[CALL] line=10989 fn=startswith 
[CALL] line=10990 fn=_unwrap_front_json_envelope 
[IF] line=10992 cond=_free_spoken.startswith('{') or _free_spoken.startswith('```')
[CALL] line=10992 fn=startswith 
[CALL] line=10992 fn=startswith 
[CALL] line=10993 fn=_unwrap_front_json_envelope 
[CALL] line=10995 fn=lower 
[CALL] line=10995 fn=strip 
[CALL] line=10995 fn=str 
[CALL] line=10996 fn=bool 
[CALL] line=10997 fn=int 
[CALL] line=10997 fn=len 
[CALL] line=10997 fn=strip 
[CALL] line=10997 fn=str 
[CALL] line=11001 fn=_front_pick_rich_free_mode_base 
[CALL] line=11003 fn=isinstance 
[CALL] line=11004 fn=isinstance 
[CALL] line=11010 fn=_front_remove_unsafe_nominal_opening 
[CALL] line=11014 fn=_front_remove_unsafe_nominal_opening 
[CALL] line=11020 fn=upper 
[CALL] line=11020 fn=strip 
[CALL] line=11020 fn=str 
[CALL] line=11021 fn=locals 
[CALL] line=11026 fn=upper 
[CALL] line=11026 fn=strip 
[CALL] line=11026 fn=str 
[CALL] line=11027 fn=locals 
[IF] line=11029 cond=not _continuity_pack_id
[CALL] line=11030 fn=_pick_pack_for_intent 
[CALL] line=11045 fn=_front_sanitize_lead_name_candidate 
[CALL] line=11056 fn=bool 
[CALL] line=11058 fn=strip 
[CALL] line=11058 fn=str 
[CALL] line=11061 fn=bool 
[CALL] line=11069 fn=strip 
[CALL] line=11069 fn=str 
[CALL] line=11070 fn=_front_build_continuity_reply_from_platform_kb 
[CALL] line=11072 fn=isinstance 
[CALL] line=11076 fn=int 
[CALL] line=11083 fn=bool 
[CALL] line=11084 fn=strip 
[CALL] line=11084 fn=str 
[CALL] line=11085 fn=strip 
[CALL] line=11085 fn=str 
[CALL] line=11088 fn=_front_build_continuity_reply_from_platform_kb 
[CALL] line=11090 fn=isinstance 
[CALL] line=11094 fn=int 
[CALL] line=11101 fn=bool 
[CALL] line=11102 fn=bool 
[CALL] line=11103 fn=bool 
[CALL] line=11106 fn=bool 
[IF] line=11110 cond=not _has_segment_for_identity
[CALL] line=11111 fn=_front_extract_declared_segment_from_user_text 
[IF] line=11112 cond=_declared_segment
[CALL] line=11117 fn=bool 
[CALL] line=11117 fn=bool 
[CALL] line=11124 fn=strip 
[CALL] line=11124 fn=str 
[IF] line=11130 cond=_candidate_identity_question
[CALL] line=11131 fn=append 
[IF] line=11133 cond=_front_identity_request_is_valid(_candidate_identity_question)
[CALL] line=11133 fn=_front_identity_request_is_valid 
[IF] line=11136 cond=isinstance(kb_context, dict)
[CALL] line=11136 fn=isinstance 
[CALL] line=11143 fn=strip 
[CALL] line=11143 fn=str 
[CALL] line=11143 fn=get 
[IF] line=11144 cond=_v
[CALL] line=11145 fn=append 
[CALL] line=11147 fn=strip 
[CALL] line=11147 fn=str 
[CALL] line=11148 fn=get 
[IF] line=11151 cond=not _identity_question and _front_identity_request_is_valid(_kb_identity_question)
[CALL] line=11153 fn=_front_identity_request_is_valid 
[IF] line=11157 cond=_missing_identity and (not _identity_question)
[CALL] line=11158 fn=_front_build_identity_request 
[CALL] line=11165 fn=_front_remove_known_open_question_tail 
[CALL] line=11169 fn=_front_remove_known_open_question_tail 
[CALL] line=11174 fn=_front_clean_free_mode_tail 
[CALL] line=11175 fn=_front_clean_free_mode_tail 
[IF] line=11180 cond='?' in _free_reply
[CALL] line=11181 fn=_front_normalize_identity_text 
[CALL] line=11182 fn=_front_normalize_identity_text 
[IF] line=11183 cond=not (_norm_identity and _norm_identity in _norm_reply)
[CALL] line=11184 fn=_strip_trailing_question 
[CALL] line=11185 fn=_strip_trailing_question 
[CALL] line=11186 fn=_front_clean_free_mode_tail 
[CALL] line=11187 fn=_front_clean_free_mode_tail 
[CALL] line=11192 fn=int 
[IF] line=11193 cond=_allow_safe_greeting and _free_reply and (not re.match('(?i)^\\s*ol[áa]\\b', _free_reply))
[CALL] line=11193 fn=match 
[CALL] line=11194 fn=strip 
[IF] line=11195 cond=_allow_safe_greeting and _free_spoken and (not re.match('(?i)^\\s*ol[áa]\\b', _free_spoken))
[CALL] line=11195 fn=match 
[CALL] line=11196 fn=strip 
[IF] line=11200 cond=str(next_step or '').strip().upper() != 'SEND_LINK' and _missing_identity and _identity_question and (not _front_has_identity_request_tail(_free_reply, _identity_question))
[CALL] line=11201 fn=upper 
[CALL] line=11201 fn=strip 
[CALL] line=11201 fn=str 
[CALL] line=11204 fn=_front_has_identity_request_tail 
[CALL] line=11211 fn=max 
[CALL] line=11213 fn=len 
[CALL] line=11213 fn=len 
[CALL] line=11215 fn=_front_trim_free_mode_sentence 
[CALL] line=11219 fn=strip 
[CALL] line=11224 fn=_front_trim_free_mode_sentence 
[CALL] line=11255 fn=bool 
[CALL] line=11256 fn=int 
[CALL] line=11258 fn=bool 
[CALL] line=11260 fn=bool 
[CALL] line=11261 fn=len 
[CALL] line=11261 fn=strip 
[CALL] line=11261 fn=str 
[CALL] line=11261 fn=get 
[CALL] line=11263 fn=bool 
[CALL] line=11266 fn=isinstance 
[CALL] line=11267 fn=bool 
[CALL] line=11267 fn=get 
[IF] line=11272 cond=_preserve_continuity_reply
[CALL] line=11273 fn=strip 
[CALL] line=11273 fn=str 
[CALL] line=11274 fn=get 
[IF] line=11279 cond=isinstance(reply_size_policy, dict) and bool(reply_size_policy.get('is_audio'))
[CALL] line=11279 fn=isinstance 
[CALL] line=11279 fn=bool 
[CALL] line=11279 fn=get 
[CALL] line=11280 fn=int 
[CALL] line=11281 fn=get 
[CALL] line=11282 fn=get 
[CALL] line=11285 fn=max 
[CALL] line=11285 fn=min 
[IF] line=11291 cond=bool(_preserve_continuity_reply)
[CALL] line=11291 fn=bool 
[CALL] line=11292 fn=max 
[CALL] line=11292 fn=int 
[CALL] line=11293 fn=min 
[IF] line=11300 cond=isinstance(reply_size_policy, dict) and bool(reply_size_policy.get('is_audio')) and _missing_identity and _identity_question
[CALL] line=11301 fn=isinstance 
[CALL] line=11302 fn=bool 
[CALL] line=11302 fn=get 
[CALL] line=11307 fn=max 
[CALL] line=11309 fn=int 
[CALL] line=11309 fn=len 
[CALL] line=11309 fn=len 
[CALL] line=11311 fn=_front_remove_known_open_question_tail 
[CALL] line=11312 fn=str 
[CALL] line=11315 fn=_front_trim_free_mode_sentence 
[CALL] line=11319 fn=_front_trim_free_mode_sentence 
[CALL] line=11320 fn=strip 
[CALL] line=11324 fn=_front_trim_free_mode_sentence 
[CALL] line=11329 fn=_front_trim_free_mode_sentence 
[CALL] line=11338 fn=_front_sanitize_lead_name_candidate 
[IF] line=11347 cond=not bool(_safe_payload_name)
[CALL] line=11347 fn=bool 
[CALL] line=11351 fn=get 
[IF] line=11352 cond=isinstance(_u, dict)
[CALL] line=11352 fn=isinstance 
[CALL] line=11362 fn=get 
[IF] line=11363 cond=isinstance(_u, dict)
[CALL] line=11363 fn=isinstance 
[IF] line=11371 cond=not _missing_identity and (not _identity_question)
[CALL] line=11375 fn=get 
[IF] line=11376 cond=isinstance(_u, dict)
[CALL] line=11376 fn=isinstance 
[IF] line=11382 cond=not _missing_identity and int(ai_turns or 0) > 0 and (str(out.get('question_type') or '').strip().lower() == 'broad')
[CALL] line=11384 fn=int 
[CALL] line=11385 fn=lower 
[CALL] line=11385 fn=strip 
[CALL] line=11385 fn=str 
[CALL] line=11385 fn=get 
[CALL] line=11389 fn=get 
[IF] line=11390 cond=isinstance(_u, dict)
[CALL] line=11390 fn=isinstance 
[IF] line=11398 cond=_missing_identity and _identity_question
[CALL] line=11401 fn=get 
[IF] line=11402 cond=isinstance(_u, dict)
[CALL] line=11402 fn=isinstance 
[IF] line=11408 cond=out['replyText'] and out['replyText'][-1] not in '.!?'
[CALL] line=11409 fn=rstrip 
[IF] line=11411 cond=out['spokenText'] and out['spokenText'][-1] not in '.!?'
[CALL] line=11412 fn=rstrip 
[CALL] line=11414 fn=_sanitize_front_result_payload 
[CALL] line=11416 fn=info 
[CALL] line=11419 fn=len 
[CALL] line=11419 fn=str 
[CALL] line=11419 fn=get 
[CALL] line=11420 fn=len 
[CALL] line=11420 fn=str 
[CALL] line=11420 fn=get 
[CALL] line=11422 fn=bool 
[CALL] line=11425 fn=_sanitize_front_result_payload 
[RETURN] line=11427
[CALL] line=11434 fn=lower 
[CALL] line=11434 fn=strip 
[IF] line=11435 cond=intent == 'OTHER' and ('como funciona' in _ut or 'como que funciona' in _ut or 'funciona' in _ut or ('o que é' in _ut) or ('o que eh' in _ut))
[IF] line=11439 cond=not reply_text
[IF] line=11442 cond=kb_snapshot and str(kb_snapshot).strip().startswith('{')
[CALL] line=11442 fn=startswith 
[CALL] line=11442 fn=strip 
[CALL] line=11442 fn=str 
[CALL] line=11443 fn=loads 
[CALL] line=11443 fn=str 
[IF] line=11447 cond=isinstance(_kb, dict) and (_kb.get('value_packs_v1') or _kb.get('answer_playbook_v1') or _kb.get('kb_segments_v1') or _kb.get('kb_subsegments_v1') or _kb.get('kb_archetypes_v1'))
[CALL] line=11447 fn=isinstance 
[CALL] line=11448 fn=get 
[CALL] line=11449 fn=get 
[CALL] line=11450 fn=get 
[CALL] line=11451 fn=get 
[CALL] line=11452 fn=get 
[CALL] line=11456 fn=render_pack_reply 
[IF] line=11463 cond=rend.get('ok') and str(rend.get('replyText') or '').strip()
[CALL] line=11463 fn=get 
[CALL] line=11463 fn=strip 
[CALL] line=11463 fn=str 
[CALL] line=11463 fn=get 
[CALL] line=11464 fn=strip 
[CALL] line=11464 fn=str 
[CALL] line=11464 fn=get 
[IF] line=11465 cond=not spoken_text and str(rend.get('spokenText') or '').strip()
[CALL] line=11465 fn=strip 
[CALL] line=11465 fn=str 
[CALL] line=11465 fn=get 
[CALL] line=11466 fn=strip 
[CALL] line=11466 fn=str 
[CALL] line=11466 fn=get 
[CALL] line=11468 fn=strip 
[CALL] line=11468 fn=str 
[CALL] line=11468 fn=get 
[CALL] line=11469 fn=strip 
[CALL] line=11469 fn=str 
[CALL] line=11469 fn=get 
[CALL] line=11470 fn=lower 
[CALL] line=11470 fn=strip 
[CALL] line=11470 fn=str 
[CALL] line=11470 fn=get 
[IF] line=11475 cond=not reply_text and intent in ('WHAT_IS', 'OTHER')
[IF] line=11480 cond=question
[IF] line=11486 cond=next_step != 'SEND_LINK' and (not reply_text)
[CALL] line=11487 fn=strip 
[CALL] line=11487 fn=_infer_segment_from_text TARGET
[CALL] line=11488 fn=_pick_pack_for_intent 
[IF] line=11489 cond=_pack and intent in ('WHAT_IS', 'AGENDA', 'SERVICOS', 'PEDIDOS', 'ORCAMENTO', 'STATUS', 'PROCESSO')
[IF] line=11491 cond=_seg
[CALL] line=11492 fn=_compose_practical_scene 
[IF] line=11499 cond=practical_scene and intent in ('WHAT_IS', 'PROCESSO')
[CALL] line=11500 fn=_extract_value_line 
[CALL] line=11501 fn=_merge_value_and_scene 
[IF] line=11503 cond=not practical_scene
[CALL] line=11504 fn=_kb_get_micro_scene 
[IF] line=11505 cond=ms
[CALL] line=11506 fn=startswith 
[CALL] line=11506 fn=lower 
[IF] line=11508 cond=not practical_scene
[CALL] line=11511 fn=_extract_value_line 
[IF] line=11512 cond=not value_line
[IF] line=11516 cond=not _seg
[IF] line=11518 cond=not has_name and ai_turns >= 1
[IF] line=11521 cond=practical_scene
[CALL] line=11522 fn=_merge_value_and_scene 
[CALL] line=11524 fn=strip 
[IF] line=11525 cond=not spoken_text
[CALL] line=11528 fn=_extract_value_line 
[IF] line=11529 cond=practical_scene
[CALL] line=11530 fn=_merge_value_and_scene 
[CALL] line=11532 fn=strip 
[IF] line=11540 cond=not reply_text and needs_clarify == 'yes' and clarify_q
[IF] line=11541 cond=question and (not effective_segment)
[IF] line=11543 cond=not spoken_text
[IF] line=11547 cond=not spoken_text
[IF] line=11552 cond=not reply_text or len(str(reply_text).strip()) < 40
[CALL] line=11552 fn=len 
[CALL] line=11552 fn=strip 
[CALL] line=11552 fn=str 
[IF] line=11554 cond=operational_contract or base_operational_contract
[IF] line=11555 cond=not operational_reference
[CALL] line=11557 fn=_build_kb_show_reply 
[CALL] line=11558 fn=isinstance 
[IF] line=11565 cond=forced and len(forced.strip()) >= 40
[CALL] line=11565 fn=len 
[CALL] line=11565 fn=strip 
[CALL] line=11568 fn=ValueError 
[CALL] line=11570 fn=ValueError 
[IF] line=11575 cond=not reply_text or len(str(reply_text).strip()) < 40
[CALL] line=11575 fn=len 
[CALL] line=11575 fn=strip 
[CALL] line=11575 fn=str 
[IF] line=11585 cond=next_step == 'SEND_LINK'
[CALL] line=11587 fn=strip 
[CALL] line=11587 fn=getenv 
[CALL] line=11588 fn=strip 
[IF] line=11590 cond='http://' not in rt0 and 'https://' not in rt0
[IF] line=11591 cond=rt0
[CALL] line=11592 fn=find 
[IF] line=11593 cond=qpos != -1
[CALL] line=11594 fn=rstrip 
[IF] line=11595 cond=not rt0.endswith(('.', '!', ':'))
[CALL] line=11595 fn=endswith 
[CALL] line=11600 fn=strip 
[CALL] line=11611 fn=bool 
[CALL] line=11612 fn=get 
[CALL] line=11612 fn=locals 
[CALL] line=11613 fn=get 
[CALL] line=11613 fn=locals 
[CALL] line=11617 fn=_sanitize_user_facing_reply 
[CALL] line=11618 fn=_sanitize_user_facing_reply 
[CALL] line=11622 fn=locals 
[CALL] line=11622 fn=isinstance 
[CALL] line=11623 fn=locals 
[CALL] line=11623 fn=isinstance 
[CALL] line=11627 fn=bool 
[CALL] line=11628 fn=upper 
[CALL] line=11628 fn=strip 
[CALL] line=11628 fn=str 
[CALL] line=11629 fn=isinstance 
[CALL] line=11630 fn=bool 
[CALL] line=11630 fn=get 
[CALL] line=11631 fn=bool 
[CALL] line=11631 fn=get 
[CALL] line=11632 fn=bool 
[CALL] line=11632 fn=get 
[CALL] line=11635 fn=bool 
[CALL] line=11636 fn=isinstance 
[CALL] line=11637 fn=bool 
[CALL] line=11637 fn=get 
[CALL] line=11638 fn=bool 
[CALL] line=11638 fn=get 
[CALL] line=11639 fn=bool 
[CALL] line=11640 fn=get 
[CALL] line=11641 fn=get 
[CALL] line=11658 fn=bool 
[CALL] line=11659 fn=upper 
[CALL] line=11659 fn=strip 
[CALL] line=11659 fn=str 
[CALL] line=11660 fn=isinstance 
[CALL] line=11661 fn=bool 
[CALL] line=11661 fn=get 
[CALL] line=11662 fn=bool 
[CALL] line=11662 fn=get 
[CALL] line=11663 fn=bool 
[CALL] line=11663 fn=get 
[CALL] line=11664 fn=bool 
[CALL] line=11665 fn=get 
[CALL] line=11666 fn=get 
[IF] line=11670 cond=str(response_mode or '').strip().upper() == 'DIRECT' and bool(ia_accepted) and str(reply_text or '').strip() and (not _allow_direct_global_fallback_payload)
[CALL] line=11671 fn=upper 
[CALL] line=11671 fn=strip 
[CALL] line=11671 fn=str 
[CALL] line=11672 fn=bool 
[CALL] line=11673 fn=strip 
[CALL] line=11673 fn=str 
[IF] line=11678 cond=(_valid_real_scene or _valid_compact_fallback) and _should_run_late_payload
[CALL] line=11679 fn=bool 
[CALL] line=11680 fn=upper 
[CALL] line=11680 fn=strip 
[CALL] line=11680 fn=str 
[CALL] line=11681 fn=get 
[CALL] line=11682 fn=get 
[CALL] line=11685 fn=_build_direct_scene_payload TARGET
[CALL] line=11689 fn=get 
[IF] line=11698 cond=_direct_payload
[CALL] line=11703 fn=strip 
[CALL] line=11703 fn=str 
[CALL] line=11704 fn=bool 
[CALL] line=11706 fn=upper 
[CALL] line=11706 fn=strip 
[CALL] line=11706 fn=str 
[CALL] line=11707 fn=isinstance 
[CALL] line=11708 fn=bool 
[CALL] line=11708 fn=get 
[CALL] line=11709 fn=bool 
[CALL] line=11709 fn=get 
[CALL] line=11710 fn=strip 
[CALL] line=11710 fn=str 
[CALL] line=11713 fn=bool 
[CALL] line=11713 fn=search 
[CALL] line=11713 fn=str 
[CALL] line=11714 fn=_looks_like_structural_scene_payload 
[IF] line=11718 cond=_raw_scene_exit
[CALL] line=11719 fn=_upgrade_operational_reply_with_model 
[CALL] line=11720 fn=strip 
[CALL] line=11720 fn=str 
[CALL] line=11721 fn=strip 
[CALL] line=11721 fn=str 
[CALL] line=11722 fn=strip 
[CALL] line=11722 fn=str 
[CALL] line=11723 fn=isinstance 
[IF] line=11725 cond=_upgraded_exit and (not _looks_like_structural_scene_payload(_upgraded_exit))
[CALL] line=11725 fn=_looks_like_structural_scene_payload 
[CALL] line=11730 fn=_humanize_scene_flow 
[IF] line=11731 cond=_humanized_exit and _humanized_exit != str(reply_text or '').strip() and (not _looks_like_structural_scene_payload(_humanized_exit))
[CALL] line=11733 fn=strip 
[CALL] line=11733 fn=str 
[CALL] line=11734 fn=_looks_like_structural_scene_payload 
[IF] line=11742 cond=ai_turns == 0 and is_lead and (not has_name) and (str(next_step or '').strip().upper() != 'SEND_LINK')
[CALL] line=11742 fn=upper 
[CALL] line=11742 fn=strip 
[CALL] line=11742 fn=str 
[IF] line=11743 cond=isinstance(kb_context, dict)
[CALL] line=11743 fn=isinstance 
[IF] line=11746 cond=reply_text and '?' not in reply_text
[CALL] line=11747 fn=rstrip 
[IF] line=11753 cond=not hydrated_contract
[CALL] line=11755 fn=_preserve_technical_direct_reply_size 
[CALL] line=11766 fn=_preserve_technical_direct_reply_size 
[CALL] line=11776 fn=_apply_reply_size_policy 
[CALL] line=11780 fn=_apply_reply_size_policy 
[IF] line=11786 cond=reply_text and '?' in reply_text
[IF] line=11788 cond=not _should_allow_question(user_text=user_text, kb_context=kb_context if isinstance(kb_context, dict) else {}, reply_text=reply_text, understanding={**(understanding if isinstance(understanding, dict) else {}), 'response_mode': response_mode}, decider={**(decider if isinstance(decider, dict) else {}), 'response_mode': response_mode})
[CALL] line=11788 fn=_should_allow_question 
[CALL] line=11790 fn=isinstance 
[CALL] line=11793 fn=isinstance 
[CALL] line=11797 fn=isinstance 
[CALL] line=11801 fn=_strip_trailing_question 
[CALL] line=11803 fn=isinstance 
[IF] line=11810 cond=spoken_text and '?' in spoken_text
[IF] line=11812 cond=not _should_allow_question(user_text=user_text, kb_context=kb_context if isinstance(kb_context, dict) else {}, reply_text=spoken_text, understanding={**(understanding if isinstance(understanding, dict) else {}), 'response_mode': response_mode}, decider={**(decider if isinstance(decider, dict) else {}), 'response_mode': response_mode})
[CALL] line=11812 fn=_should_allow_question 
[CALL] line=11814 fn=isinstance 
[CALL] line=11817 fn=isinstance 
[CALL] line=11821 fn=isinstance 
[CALL] line=11825 fn=_strip_trailing_question 
[CALL] line=11837 fn=_try_parse_kb_json 
[CALL] line=11839 fn=_sanitize_unverified_time_claims 
[CALL] line=11840 fn=_sanitize_unverified_time_claims 
[IF] line=11852 cond=not free_mode and apply_sales_guardrails is not None
[CALL] line=11853 fn=apply_sales_guardrails 
[CALL] line=11859 fn=isinstance 
[IF] line=11863 cond=isinstance(gr, dict)
[CALL] line=11863 fn=isinstance 
[CALL] line=11864 fn=strip 
[CALL] line=11864 fn=str 
[CALL] line=11864 fn=get 
[CALL] line=11865 fn=strip 
[CALL] line=11865 fn=str 
[CALL] line=11865 fn=get 
[CALL] line=11872 fn=wrap_show_response 
[CALL] line=11876 fn=_sanitize_user_facing_reply 
[CALL] line=11877 fn=_sanitize_user_facing_reply 
[IF] line=11879 cond=_looks_like_technical_output(reply_text)
[CALL] line=11879 fn=_looks_like_technical_output 
[CALL] line=11880 fn=_build_contract_consequence 
[CALL] line=11881 fn=locals 
[CALL] line=11882 fn=locals 
[IF] line=11884 cond=_looks_like_technical_output(spoken_text)
[CALL] line=11884 fn=_looks_like_technical_output 
[IF] line=11887 cond=not spoken_text
[CALL] line=11893 fn=strip 
[CALL] line=11893 fn=str 
[CALL] line=11894 fn=bool 
[CALL] line=11895 fn=get 
[CALL] line=11895 fn=locals 
[CALL] line=11896 fn=get 
[CALL] line=11896 fn=locals 
[IF] line=11899 cond=not _rt or len(_rt) < 40
[CALL] line=11899 fn=len 
[IF] line=11900 cond=allow_final_kb_show and operational_contract
[IF] line=11901 cond=not operational_reference
[CALL] line=11903 fn=_build_kb_show_reply 
[CALL] line=11904 fn=isinstance 
[IF] line=11911 cond=forced and len(forced.strip()) >= 40
[CALL] line=11911 fn=len 
[CALL] line=11911 fn=strip 
[IF] line=11913 cond=allow_final_kb_show and base_operational_contract
[IF] line=11914 cond=not operational_reference
[CALL] line=11916 fn=_build_kb_show_reply 
[CALL] line=11917 fn=isinstance 
[IF] line=11924 cond=forced and len(forced.strip()) >= 40
[CALL] line=11924 fn=len 
[CALL] line=11924 fn=strip 
[IF] line=11931 cond=_final_candidate and (not reply_text or len(reply_text.strip()) < 40)
[CALL] line=11932 fn=len 
[CALL] line=11932 fn=strip 
[CALL] line=11941 fn=_normalize_response_mode 
[IF] line=11943 cond=response_mode == 'DIRECT'
[CALL] line=11944 fn=strip 
[CALL] line=11944 fn=str 
[CALL] line=11945 fn=strip 
[CALL] line=11945 fn=str 
[IF] line=11947 cond=response_mode == 'DISCOVERY'
[CALL] line=11948 fn=bool 
[CALL] line=11949 fn=bool 
[IF] line=11951 cond=missing_name or missing_segment
[IF] line=11952 cond=not _has_question(reply_text)
[CALL] line=11952 fn=_has_question 
[CALL] line=11957 fn=strip 
[CALL] line=11957 fn=str 
[IF] line=11959 cond=response_mode == 'SCENE'
[CALL] line=11960 fn=lstrip 
[CALL] line=11960 fn=str 
[CALL] line=11961 fn=lstrip 
[CALL] line=11961 fn=str 
[IF] line=11963 cond=response_mode == 'CLOSING'
[CALL] line=11964 fn=strip 
[CALL] line=11964 fn=str 
[CALL] line=11965 fn=strip 
[CALL] line=11965 fn=str 
[IF] line=11967 cond=response_mode == 'DISCOVERY'
[CALL] line=11968 fn=bool 
[CALL] line=11969 fn=bool 
[IF] line=11971 cond=missing_name or missing_segment
[IF] line=11972 cond=not _has_question(reply_text)
[CALL] line=11972 fn=_has_question 
[IF] line=11981 cond=not reply_text or len(reply_text.strip()) < 40
[CALL] line=11981 fn=len 
[CALL] line=11981 fn=strip 
[CALL] line=11982 fn=bool 
[CALL] line=11983 fn=get 
[CALL] line=11983 fn=locals 
[CALL] line=11984 fn=get 
[CALL] line=11984 fn=locals 
[IF] line=11988 cond=allow_final_kb_show
[CALL] line=11991 fn=_build_kb_show_reply 
[CALL] line=11992 fn=isinstance 
[CALL] line=11997 fn=locals 
[CALL] line=11997 fn=locals 
[IF] line=12001 cond=not forced and allow_scene_runtime
[CALL] line=12002 fn=_build_kb_anchor_reply 
[CALL] line=12006 fn=locals 
[CALL] line=12006 fn=locals 
[IF] line=12009 cond=forced and len(forced.strip()) >= 40
[CALL] line=12009 fn=len 
[CALL] line=12009 fn=strip 
[IF] line=12018 cond=response_mode == 'DISCOVERY'
[CALL] line=12019 fn=bool 
[CALL] line=12020 fn=bool 
[IF] line=12022 cond=missing_name or missing_segment
[IF] line=12023 cond=not _has_question(reply_text)
[CALL] line=12023 fn=_has_question 
[CALL] line=12028 fn=strip 
[CALL] line=12028 fn=str 
[IF] line=12032 cond='?' in reply_text
[CALL] line=12033 fn=split 
[IF] line=12034 cond=len(parts) > 2
[CALL] line=12034 fn=len 
[CALL] line=12035 fn=strip 
[CALL] line=12043 fn=_unwrap_front_json_envelope 
[CALL] line=12044 fn=_unwrap_front_json_envelope 
[IF] line=12049 cond=ai_turns == 0 and reply_text
[IF] line=12050 cond=not has_name
[IF] line=12053 cond=FRONT_TRACE_ENABLED
[CALL] line=12054 fn=info 
[CALL] line=12063 fn=_front_build_structured_assembly_reply TARGET
[CALL] line=12065 fn=locals 
[CALL] line=12066 fn=isinstance 
[CALL] line=12067 fn=isinstance 
[CALL] line=12068 fn=locals 
[CALL] line=12073 fn=_front_sanitize_lead_name_candidate 
[IF] line=12087 cond=structured_assembly_result and structured_assembly_result.get('replyText')
[CALL] line=12087 fn=get 
[CALL] line=12088 fn=strip 
[CALL] line=12088 fn=str 
[CALL] line=12088 fn=get 
[CALL] line=12089 fn=strip 
[CALL] line=12089 fn=str 
[CALL] line=12089 fn=get 
[CALL] line=12095 fn=_humanize_reply_with_lead_context 
[CALL] line=12098 fn=_front_sanitize_lead_name_candidate 
[CALL] line=12115 fn=_front_remove_unsafe_nominal_opening 
[CALL] line=12116 fn=_front_remove_unsafe_nominal_opening 
[CALL] line=12123 fn=_preserve_technical_direct_reply_size 
[CALL] line=12159 fn=isinstance 
[CALL] line=12163 fn=strip 
[CALL] line=12163 fn=str 
[CALL] line=12164 fn=upper 
[CALL] line=12164 fn=strip 
[CALL] line=12164 fn=str 
[CALL] line=12165 fn=upper 
[CALL] line=12165 fn=strip 
[CALL] line=12165 fn=str 
[CALL] line=12167 fn=bool 
[CALL] line=12168 fn=get 
[CALL] line=12169 fn=get 
[CALL] line=12172 fn=bool 
[IF] line=12186 cond=_is_technical_direct
[CALL] line=12187 fn=_front_trim_to_complete_sentence 
[CALL] line=12191 fn=_front_trim_to_complete_sentence 
[CALL] line=12197 fn=info 
[CALL] line=12202 fn=len 
[CALL] line=12203 fn=len 
[CALL] line=12212 fn=strip 
[CALL] line=12212 fn=str 
[IF] line=12218 cond=_declared_segment_for_payload
[CALL] line=12221 fn=get 
[IF] line=12222 cond=isinstance(_u, dict)
[CALL] line=12222 fn=isinstance 
[CALL] line=12246 fn=_front_sanitize_lead_name_candidate 
[CALL] line=12266 fn=len 
[CALL] line=12269 fn=isinstance 
[IF] line=12273 cond=decider_only and isinstance(decider, dict)
[CALL] line=12273 fn=isinstance 
[CALL] line=12277 fn=get 
[IF] line=12278 cond=not isinstance(am, dict)
[CALL] line=12278 fn=isinstance 
[CALL] line=12280 fn=isinstance 
[CALL] line=12281 fn=str 
[CALL] line=12281 fn=get 
[CALL] line=12282 fn=int 
[CALL] line=12282 fn=get 
[CALL] line=12283 fn=int 
[CALL] line=12283 fn=get 
[CALL] line=12284 fn=bool 
[CALL] line=12284 fn=get 
[CALL] line=12285 fn=bool 
[CALL] line=12285 fn=get 
[CALL] line=12293 fn=info 
[CALL] line=12300 fn=len 
[IF] line=12304 cond=not reply_text
[IF] line=12316 cond=not reply_text or not str(reply_text).strip() or _looks_like_technical_output(reply_text)
[CALL] line=12316 fn=strip 
[CALL] line=12316 fn=str 
[CALL] line=12316 fn=_looks_like_technical_output 
[CALL] line=12317 fn=warning 
[IF] line=12335 cond=ai_turns == 0
[CALL] line=12336 fn=strip 
[CALL] line=12336 fn=str 
[CALL] line=12336 fn=get 
[IF] line=12349 cond=txt and (not txt.lower().startswith(greetings))
[CALL] line=12349 fn=startswith 
[CALL] line=12349 fn=lower 
[CALL] line=12350 fn=upper 
[CALL] line=12362 fn=_unwrap_front_json_envelope 
[CALL] line=12362 fn=get 
[CALL] line=12363 fn=_unwrap_front_json_envelope 
[CALL] line=12363 fn=get 
[IF] line=12365 cond=final_reply
[IF] line=12370 cond=_looks_like_technical_output(out.get('replyText') or reply_text)
[CALL] line=12370 fn=_looks_like_technical_output 
[CALL] line=12370 fn=get 
[CALL] line=12379 fn=_sanitize_front_result_payload 
[IF] line=12387 cond=isinstance(result, dict)
[CALL] line=12387 fn=isinstance 
[CALL] line=12388 fn=_unwrap_front_json_envelope 
[CALL] line=12388 fn=get 
[CALL] line=12389 fn=_unwrap_front_json_envelope 
[CALL] line=12389 fn=get 
[IF] line=12391 cond=final_reply
[RETURN] line=12397
[CALL] line=12401 fn=exception 
[IF] line=12403 cond=free_mode
[CALL] line=12407 fn=_build_kb_show_reply 
[CALL] line=12408 fn=isinstance 
[CALL] line=12409 fn=locals 
[CALL] line=12410 fn=locals 
[CALL] line=12411 fn=locals 
[CALL] line=12412 fn=locals 
[CALL] line=12413 fn=locals 
[CALL] line=12413 fn=locals 
[CALL] line=12415 fn=_build_kb_anchor_reply 
[CALL] line=12416 fn=locals 
[CALL] line=12417 fn=locals 
[CALL] line=12418 fn=locals 
[CALL] line=12419 fn=locals 
[CALL] line=12419 fn=locals 
[IF] line=12425 cond=kb_fallback
[IF] line=12427 cond=question
[IF] line=12435 cond=_looks_like_technical_output(reply_text)
[CALL] line=12435 fn=_looks_like_technical_output 
[CALL] line=12459 fn=len 

## Observações

- TARGET marca hubs importantes do fluxo
- returns antecipados podem indicar short-circuit
- ifs ajudam a revelar gates/fallbacks
- relatório não representa execução dinâmica
- objetivo é reconstruir a ordem estrutural do handle

# Atualização — Terminal hierarchy

O runtime possui múltiplos terminais soberanos.

Nem todo early return encerra definitivamente o pipeline.

SCENE hidratado pode atravessar:
- DIRECT SCENE EARLY TERMINAL

via:
`_continue_after_direct_scene`

