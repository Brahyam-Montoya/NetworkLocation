import os
import shutil
from datetime import datetime, UTC
from pathlib import Path

from config import ALLOWED_USERS_FILE, EVIDENCE_DIR, EXECUTION_LOGS_FILE, LOGS_DIR, ROLES_FILE, UPLOAD_FOLDER


def ensure_app_dirs():
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    os.makedirs(LOGS_DIR, exist_ok=True)
    os.makedirs(EVIDENCE_DIR, exist_ok=True)

    roles_path = Path(ROLES_FILE)
    if not roles_path.exists():
        roles_path.write_text("{}", encoding="utf-8")

    allowed_users_path = Path(ALLOWED_USERS_FILE)
    if not allowed_users_path.exists():
        allowed_users_path.write_text("[]", encoding="utf-8")

    execution_logs_path = Path(EXECUTION_LOGS_FILE)
    if not execution_logs_path.exists():
        execution_logs_path.write_text("[]", encoding="utf-8")


def utc_now_iso():
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def save_upload_file(file_storage):
    ensure_app_dirs()
    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%SZ")
    safe_name = Path(file_storage.filename).name.replace(" ", "_")
    final_name = f"{timestamp}-{safe_name}"
    destination = os.path.join(UPLOAD_FOLDER, final_name)
    file_storage.save(destination)
    return destination


def clear_directory_contents(directory):
    if not os.path.isdir(directory):
        return

    for item in os.listdir(directory):
        full_path = os.path.join(directory, item)
        if os.path.isdir(full_path):
            shutil.rmtree(full_path, ignore_errors=True)
        else:
            try:
                os.remove(full_path)
            except FileNotFoundError:
                pass
