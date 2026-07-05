DEFAULT_READONLY_POLICY = {
    "can_read_local_fixture": True,
    "can_extract_data": True,
    "can_classify": True,
    "can_generate_summary": True,
    "can_generate_draft": True,
    "can_save_local_report": True,

    "can_read_gmail_real": False,
    "can_open_platform_url": False,
    "can_login_platform": False,
    "can_click": False,
    "can_type": False,
    "can_send_message": False,
    "can_submit_proposal": False,
    "can_send_email": False,
    "can_write_firestore": False,
    "can_deploy": False,

    "requires_human_approval": True,
    "dry_run": True,
}

EXTERNAL_ACTIONS = {
    "read_gmail_real": "can_read_gmail_real",
    "open_platform_url": "can_open_platform_url",
    "login_platform": "can_login_platform",
    "click": "can_click",
    "type": "can_type",
    "send_message": "can_send_message",
    "submit_proposal": "can_submit_proposal",
    "send_email": "can_send_email",
    "write_firestore": "can_write_firestore",
    "deploy": "can_deploy",
}


def get_default_policy():
    return dict(DEFAULT_READONLY_POLICY)


def is_action_allowed(action_name, policy=None):
    policy = policy or DEFAULT_READONLY_POLICY
    key = EXTERNAL_ACTIONS.get(action_name)
    if not key:
        return False
    return bool(policy.get(key, False))


def blocked_external_actions(policy=None):
    policy = policy or DEFAULT_READONLY_POLICY
    blocked = []
    for action_name, key in sorted(EXTERNAL_ACTIONS.items()):
        if not policy.get(key, False):
            blocked.append(action_name)
    return blocked
