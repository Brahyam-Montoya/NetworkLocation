import json
import os
import shutil
import uuid

from config import EVIDENCE_DIR, EXECUTION_LOGS_FILE, LOGS_DIR, UPLOAD_FOLDER
from utils.storage import ensure_app_dirs, utc_now_iso


def _read_logs():
    ensure_app_dirs()
    try:
        with open(EXECUTION_LOGS_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
            return data if isinstance(data, list) else []
    except Exception:
        return []


def _write_logs(logs):
    with open(EXECUTION_LOGS_FILE, "w", encoding="utf-8") as file:
        json.dump(logs, file, indent=2, ensure_ascii=False)


def get_logs():
    logs = _read_logs()
    return sorted(logs, key=lambda item: item.get("started_at", ""), reverse=True)


def get_log(log_id):
    for log in _read_logs():
        if log.get("id") == log_id:
            return log
    return None


def save_log(entry):
    logs = _read_logs()
    payload = {
        "id": str(uuid.uuid4()),
        "created_at": utc_now_iso(),
        **entry
    }
    logs.append(payload)
    _write_logs(logs)
    return payload


def update_log(log_id, patch):
    logs = _read_logs()
    updated = None

    for index, log in enumerate(logs):
        if log.get("id") == log_id:
            logs[index] = {**log, **patch}
            updated = logs[index]
            break

    if updated:
      _write_logs(logs)

    return updated


def clear_execution_data():
    _write_logs([])

    if os.path.isdir(EVIDENCE_DIR):
        shutil.rmtree(EVIDENCE_DIR, ignore_errors=True)
    os.makedirs(EVIDENCE_DIR, exist_ok=True)

    if os.path.isdir(UPLOAD_FOLDER):
        for item in os.listdir(UPLOAD_FOLDER):
            full_path = os.path.join(UPLOAD_FOLDER, item)
            if os.path.isfile(full_path):
                os.remove(full_path)

    history_file = os.path.join(LOGS_DIR, "history.json")
    if os.path.exists(history_file):
        os.remove(history_file)
