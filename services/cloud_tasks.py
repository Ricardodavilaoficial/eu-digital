# services/cloud_tasks.py
from __future__ import annotations

import os
import json
import time
import hashlib
import logging
import datetime
from typing import Any, Dict, Optional

from google.cloud import tasks_v2  # type: ignore
from google.protobuf import timestamp_pb2  # type: ignore

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


def enqueue_ycloud_buffer_flush(wa_key: str, delay_seconds: int = 4) -> Dict[str, Any]:
    """
    Agenda o flush do buffer inbound do WhatsApp.
    Task deduplicada por wa_key + janela temporal curta.
    """
    project = (os.environ.get("CLOUD_TASKS_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT") or "").strip()
    location = (os.environ.get("CLOUD_TASKS_LOCATION") or "").strip()
    queue = (os.environ.get("CLOUD_TASKS_QUEUE") or "").strip()
    target_url = (os.environ.get("CLOUD_TASKS_TARGET_URL") or "").strip().rstrip("/")
    secret = (os.environ.get("CLOUD_TASKS_SECRET") or "").strip()

    if not (project and location and queue and target_url and secret):
        raise RuntimeError("Cloud Tasks ENVs ausentes: CLOUD_TASKS_PROJECT/LOCATION/QUEUE/TARGET_URL/SECRET")

    wa_key = "".join(ch for ch in str(wa_key or "") if ch.isdigit()) or str(wa_key or "").strip()
    if not wa_key:
        raise RuntimeError("wa_key ausente para flush do buffer")

    try:
        delay_seconds = max(1, int(delay_seconds or 4))
    except Exception:
        delay_seconds = 4

    parent = _client().queue_path(project, location, queue)

    now_ts = time.time()
    window = int(now_ts / float(delay_seconds))
    task_id = _sha1(f"ycloud-flush:{wa_key}:{window}")[:32]
    task_name = _client().task_path(project, location, queue, task_id)

    body = json.dumps(
        {
            "waKey": wa_key,
            "enqueuedAt": now_ts,
            "delaySeconds": delay_seconds,
        },
        ensure_ascii=False,
    ).encode("utf-8")

    schedule_time = datetime.datetime.utcnow() + datetime.timedelta(seconds=delay_seconds)
    ts = timestamp_pb2.Timestamp()
    ts.FromDatetime(schedule_time)

    task = {
        "name": task_name,
        "http_request": {
            "http_method": tasks_v2.HttpMethod.POST,
            "url": f"{target_url}/tasks/ycloud-flush",
            "headers": {
                "Content-Type": "application/json",
                "X-MR-Tasks-Secret": secret,
            },
            "body": body,
        },
        "schedule_time": ts,
    }

    try:
        created = _client().create_task(request={"parent": parent, "task": task})
        return {"ok": True, "taskName": getattr(created, "name", ""), "deduped": False}
    except Exception as e:
        msg = str(e)
        if "ALREADY_EXISTS" in msg or "AlreadyExists" in msg:
            return {"ok": True, "taskName": task_name, "deduped": True}
        raise


def enqueue_acervo_index(uid: str, acervo_id: str) -> Dict[str, Any]:
    """
    Enfileira indexação do acervo (gera magrinho + resumo + tags + embedding).
    """
    project = (os.environ.get("CLOUD_TASKS_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT") or "").strip()
    location = (os.environ.get("CLOUD_TASKS_LOCATION") or "").strip()
    queue = (os.environ.get("CLOUD_TASKS_QUEUE") or "").strip()
    target_url = (os.environ.get("CLOUD_TASKS_TARGET_URL") or "").strip().rstrip("/")
    secret = (os.environ.get("CLOUD_TASKS_SECRET") or "").strip()

    if not (project and location and queue and target_url and secret):
        raise RuntimeError("Cloud Tasks ENVs ausentes: CLOUD_TASKS_PROJECT/LOCATION/QUEUE/TARGET_URL/SECRET")

    parent = _client().queue_path(project, location, queue)

    key = f"acervo:{uid}:{acervo_id}"
    task_id = _sha1(key)[:32]
    task_name = _client().task_path(project, location, queue, task_id)

    body = json.dumps({"uid": uid, "acervoId": acervo_id}).encode("utf-8")

    task = {
        "name": task_name,
        "http_request": {
            "http_method": tasks_v2.HttpMethod.POST,
            "url": f"{target_url}/tasks/acervo-index",
            "headers": {
                "Content-Type": "application/json",
                "X-MR-Tasks-Secret": secret,
            },
            "body": body,
        },
    }

    try:
        _client().create_task(request={"parent": parent, "task": task})
        return {"ok": True, "task": task_name, "mode": "cloudtasks", "dup": False}
    except Exception as e:
        msg = str(e)
        if "ALREADY_EXISTS" in msg or "AlreadyExists" in msg:
            return {"ok": True, "task": task_name, "mode": "cloudtasks", "dup": True}
        raise
