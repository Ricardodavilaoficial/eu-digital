def build_audit_record(event, draft=None):
    classification = event.get("classification") or {}
    policy = event.get("permission_policy") or {}

    return {
        "timestamp": event.get("received_at"),
        "source_platform": event.get("source_platform"),
        "source_channel": event.get("source_channel"),
        "dedupe_key": event.get("dedupe_key"),
        "event_id": event.get("event_id"),
        "classification.fit_score": classification.get("fit_score"),
        "classification.fit_level": classification.get("fit_level"),
        "recommended_action": classification.get("recommended_action"),
        "risk_flags": event.get("risk_flags", []),
        "status": event.get("processing_status"),
        "blocked_actions": [
            key for key, value in sorted(policy.items())
            if key.startswith("can_") and value is False
        ],
        "draft_created": bool(draft),
        "dry_run": bool(policy.get("dry_run", True)),
        "requires_human_approval": bool(policy.get("requires_human_approval", True)),
    }
