# services/cloud_tasks.py
from __future__ import annotations

import os
import json
import time
import hashlib
import logging
from typing import Any, Dict, Optional

from google.cloud import tasks_v2  # type: ignore

logger = logging.getLogger("mei_robo.cloud_tasks")

_CLIENT: Optional[tasks_v2.CloudTasksClient] = None


def _client() -> tasks_v2.CloudTasksClient:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = tasks_v2.CloudTasksClient()
    return _CLIENT


def _sha1(s: str) -> str:
    return hashlib.sha1((s or "").encode("utf-8")).hexdigest()


def enqueue_ycloud_inbound(payload: Dict[str, Any], event_key: str) -> Dict[str, Any]:
    """
    Enfileira processamento do inbound do YCloud.
    - Usa task name determinística por event_key -> ALREADY_EXISTS evita duplicação.
    - Autenticação por header X-MR-Tasks-Secret (validada no worker).
    """
    project = (os.environ.get("CLOUD_TASKS_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT") or "").strip()
    location = (os.environ.get("CLOUD_TASKS_LOCATION") or "").strip()
    queue = (os.environ.get("CLOUD_TASKS_QUEUE") or "").strip()
    target_url = (os.environ.get("CLOUD_TASKS_TARGET_URL") or "").strip().rstrip("/")
    secret = (os.environ.get("CLOUD_TASKS_SECRET") or "").strip()

    if not (project and location and queue and target_url and secret):
        raise RuntimeError("Cloud Tasks ENVs ausentes: CLOUD_TASKS_PROJECT/LOCATION/QUEUE/TARGET_URL/SECRET")

    parent = _client().queue_path(project, location, queue)

    # task id determinística: evita duplicar em retries do provider/webhook
    task_id = _sha1(event_key)[:32]
    task_name = _client().task_path(project, location, queue, task_id)

    body = json.dumps({
        "eventKey": event_key,
        "payload": payload,
        "enqueuedAt": time.time(),
    }, ensure_ascii=False).encode("utf-8")

    task = {
        "http_request": {
            "http_method": tasks_v2.HttpMethod.POST,
            "url": f"{target_url}/tasks/ycloud-inbound",
            "headers": {
                "Content-Type": "application/json",
                "X-MR-Tasks-Secret": secret,
            },
            "body": body,
        }
    }

    try:
        created = _client().create_task(request={"parent": parent, "task": task})
        return {"ok": True, "taskName": getattr(created, "name", ""), "deduped": False}
    except Exception as e:
        # Se já existe, é dedupe OK. Não explode.
        msg = str(e)
        if "ALREADY_EXISTS" in msg or "AlreadyExists" in msg:
            return {"ok": True, "taskName": task_name, "deduped": True}
        raise

