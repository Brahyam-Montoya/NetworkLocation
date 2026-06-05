import json
import os
from datetime import datetime, timezone

from config import (
    ALLOWED_USERS_FILE,
    DEFAULT_ADMIN_USERS,
    DEFAULT_OTP_EMAIL,
    DEFAULT_READ_ONLY_USERS,
    GLOBAL_ADMIN_USER,
    LOCAL_LOGIN_ALIASES,
    LOCAL_LOGIN_OTP_TARGETS,
    ROLES_FILE
)

ADMIN_ROLE = "admin"
READ_ONLY_ROLE = "read_only"
DEFAULT_ALLOWED_USERS = DEFAULT_ADMIN_USERS | DEFAULT_READ_ONLY_USERS


def _normalize_username(username):
    return (username or "").strip().lower()


def canonicalize_username(username):
    normalized_username = _normalize_username(username)
    return LOCAL_LOGIN_ALIASES.get(normalized_username, normalized_username)


def resolve_otp_recipient(username):
    normalized_username = _normalize_username(username)
    canonical_username = canonicalize_username(username)

    if normalized_username in LOCAL_LOGIN_OTP_TARGETS:
        return LOCAL_LOGIN_OTP_TARGETS[normalized_username]

    if canonical_username in LOCAL_LOGIN_OTP_TARGETS:
        return LOCAL_LOGIN_OTP_TARGETS[canonical_username]

    if "@" in canonical_username:
        return canonical_username

    return DEFAULT_OTP_EMAIL or canonical_username


def _utc_now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def get_roles():
    if os.path.exists(ROLES_FILE):
        try:
            with open(ROLES_FILE, "r", encoding="utf-8") as file:
                return json.load(file)
        except Exception:
            return {}

    return {}


def _default_allowed_records():
    return {
        _normalize_username(user): {
            "username": _normalize_username(user),
            "enabled": True,
            "deleted": False,
            "source": "default"
        }
        for user in DEFAULT_ALLOWED_USERS
        if _normalize_username(user)
    }


def get_allowed_user_records():
    records = _default_allowed_records()
    if os.path.exists(ALLOWED_USERS_FILE):
        try:
            with open(ALLOWED_USERS_FILE, "r", encoding="utf-8") as file:
                data = json.load(file)
                if isinstance(data, list):
                    for item in data:
                        normalized = _normalize_username(item)
                        if normalized:
                            records[normalized] = {
                                "username": normalized,
                                "enabled": True,
                                "deleted": False,
                                "source": "file"
                            }
                elif isinstance(data, dict):
                    for username, metadata in data.items():
                        normalized = _normalize_username(username)
                        if not normalized:
                            continue

                        if isinstance(metadata, dict):
                            records[normalized] = {
                                "username": normalized,
                                "enabled": bool(metadata.get("enabled", True)),
                                "deleted": bool(metadata.get("deleted", False)),
                                "source": metadata.get("source", "file"),
                                "updated_at": metadata.get("updated_at")
                            }
                        else:
                            records[normalized] = {
                                "username": normalized,
                                "enabled": bool(metadata),
                                "deleted": False,
                                "source": "file"
                            }
        except Exception:
            pass

    return records


def get_allowed_users(include_disabled=False):
    users = set()
    for username, record in get_allowed_user_records().items():
        if not username or record.get("deleted"):
            continue
        if include_disabled or record.get("enabled", True):
            users.add(username)
    return users


def save_allowed_user_records(records):
    os.makedirs(os.path.dirname(ALLOWED_USERS_FILE), exist_ok=True)
    normalized = {}
    for username, metadata in sorted(records.items()):
        normalized_username = _normalize_username(username)
        if not normalized_username:
            continue

        normalized[normalized_username] = {
            "enabled": bool(metadata.get("enabled", True)),
            "deleted": bool(metadata.get("deleted", False)),
            "source": metadata.get("source", "file"),
            "updated_at": metadata.get("updated_at") or _utc_now_iso()
        }

    with open(ALLOWED_USERS_FILE, "w", encoding="utf-8") as file:
        json.dump(normalized, file, indent=2, ensure_ascii=False)


def allow_user(username):
    normalized_username = _normalize_username(username)
    if not normalized_username:
        return

    records = get_allowed_user_records()
    records[normalized_username] = {
        "username": normalized_username,
        "enabled": True,
        "deleted": False,
        "source": "file",
        "updated_at": _utc_now_iso()
    }
    save_allowed_user_records(records)


def set_user_enabled(username, enabled):
    normalized_username = _normalize_username(username)
    if not normalized_username or normalized_username == GLOBAL_ADMIN_USER:
        return

    records = get_allowed_user_records()
    existing = records.get(normalized_username, {"username": normalized_username, "source": "file"})
    existing["enabled"] = bool(enabled)
    existing["deleted"] = False
    existing["updated_at"] = _utc_now_iso()
    records[normalized_username] = existing
    save_allowed_user_records(records)


def remove_user(username):
    normalized_username = _normalize_username(username)
    if not normalized_username or normalized_username == GLOBAL_ADMIN_USER:
        return

    records = get_allowed_user_records()
    existing = records.get(normalized_username, {"username": normalized_username, "source": "file"})
    existing["enabled"] = False
    existing["deleted"] = True
    existing["updated_at"] = _utc_now_iso()
    records[normalized_username] = existing
    save_allowed_user_records(records)

    roles = get_roles()
    roles.pop(normalized_username, None)
    save_roles(roles)


def save_roles(roles):
    os.makedirs(os.path.dirname(ROLES_FILE), exist_ok=True)
    with open(ROLES_FILE, "w", encoding="utf-8") as file:
        json.dump(roles, file, indent=2, ensure_ascii=False)


def get_user_role(username):
    normalized_username = _normalize_username(username)
    canonical_username = canonicalize_username(username)

    if normalized_username == GLOBAL_ADMIN_USER or canonical_username == GLOBAL_ADMIN_USER:
        return ADMIN_ROLE

    roles = get_roles()
    if normalized_username in roles:
        return roles[normalized_username]
    if canonical_username in roles:
        return roles[canonical_username]
    if normalized_username in DEFAULT_ADMIN_USERS or canonical_username in DEFAULT_ADMIN_USERS:
        return ADMIN_ROLE
    if normalized_username in DEFAULT_READ_ONLY_USERS or canonical_username in DEFAULT_READ_ONLY_USERS:
        return READ_ONLY_ROLE
    return READ_ONLY_ROLE


def set_user_role(username, role):
    normalized_username = _normalize_username(username)
    if not normalized_username:
        return

    roles = get_roles()
    roles[normalized_username] = role if role in {ADMIN_ROLE, READ_ONLY_ROLE} else READ_ONLY_ROLE
    save_roles(roles)


def is_admin(username):
    return get_user_role(username) == ADMIN_ROLE


def visible_users(logs):
    users = {_normalize_username(log.get("user")) for log in logs if log.get("user")}
    users.update(get_roles().keys())
    users.update(get_allowed_user_records().keys())
    return sorted(user for user in users if user)


def allowed_users():
    return sorted(get_allowed_users())


def is_allowed_user(username):
    normalized_username = _normalize_username(username)
    canonical_username = canonicalize_username(username)
    if normalized_username == GLOBAL_ADMIN_USER or canonical_username == GLOBAL_ADMIN_USER:
        return True

    allowed = get_allowed_users()
    return (
        normalized_username in allowed
        or canonical_username in allowed
    )


def get_user_access_state(username):
    normalized_username = _normalize_username(username)
    record = get_allowed_user_records().get(normalized_username)
    if not record or record.get("deleted"):
        return "deleted"
    return "enabled" if record.get("enabled", True) else "disabled"
