# Front Lookup Cluster Audit

## _best_doc_match

### Calls
- _score_query_against_doc
- isinstance
- str

### Called By
- _infer_segment_from_docs
- _infer_segment_from_text
- _kb_lookup_operational_docs

---

## _best_lookup_key_match

### Calls
- _lookup_token_overlap_score
- str

### Called By
- _infer_segment_from_docs
- _kb_lookup_operational_docs

---

## _collect_doc_texts

### Calls
- _iter_doc_text_fragments
- isinstance
- set
- str

### Called By
- _score_query_against_doc

---

## _iter_doc_text_fragments

### Calls
- _iter_doc_text_fragments
- isinstance
- str

### Called By
- _collect_doc_texts
- _iter_doc_text_fragments

---

## _lookup_token_overlap_score

### Calls
- _base
- _normalize_lookup_key
- _tokenize_lookup_text
- len
- max
- set
- str

### Called By
- _best_lookup_key_match
- _score_query_against_doc

---

## _normalize_lookup_key

### Calls
- str

### Called By
- _front_build_continuity_reply_from_platform_kb
- _infer_segment_from_text
- _keyword_doc_match
- _lookup_token_overlap_score
- _platform_kb_resolve_runtime
- _platform_segment_profile_from_kb
- _platform_topic_from_kb_rules
- _tokenize_lookup_text
- handle

---

## _score_query_against_doc

### Calls
- _collect_doc_texts
- _lookup_token_overlap_score
- isinstance
- max
- str

### Called By
- _best_doc_match
- _doc_identity_is_compatible_with_current_text

---

## _tokenize_lookup_text

### Calls
- _normalize_lookup_key
- len

### Called By
- _infer_segment_from_text
- _lookup_token_overlap_score

---
