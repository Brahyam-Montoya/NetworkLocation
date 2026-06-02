import json
import os

from config import (
    ALLOWED_USERS_FILE,
    DEFAULT_ADMIN_USERS,
    DEFAULT_OTP_EMAIL,
    DEFAULT_READ_ONLY_USERS,
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


def get_roles():
    if os.path.exists(ROLES_FILE):
        try:
            with open(ROLES_FILE, "r", encoding="utf-8") as file:
                return json.load(file)
        except Exception:
            return {}

    return {}


def get_allowed_users():
    users = set(DEFAULT_ALLOWED_USERS)

    if os.path.exists(ALLOWED_USERS_FILE):
        try:
            with open(ALLOWED_USERS_FILE, "r", encoding="utf-8") as file:
                data = json.load(file)
                if isinstance(data, list):
                    users.update(_normalize_username(item) for item in data if item)
        except Exception:
            pass

    return {user for user in users if user}


def save_allowed_users(users):
    os.makedirs(os.path.dirname(ALLOWED_USERS_FILE), exist_ok=True)
    normalized = sorted({_normalize_username(user) for user in users if _normalize_username(user)})
    with open(ALLOWED_USERS_FILE, "w", encoding="utf-8") as file:
        json.dump(normalized, file, indent=2, ensure_ascii=False)


def allow_user(username):
    normalized_username = _normalize_username(username)
    if not normalized_username:
        return

    users = get_allowed_users()
    users.add(normalized_username)
    save_allowed_users(users)


def save_roles(roles):
    os.makedirs(os.path.dirname(ROLES_FILE), exist_ok=True)
    with open(ROLES_FILE, "w", encoding="utf-8") as file:
        json.dump(roles, file, indent=2, ensure_ascii=False)


def get_user_role(username):
    normalized_username = _normalize_username(username)
    canonical_username = canonicalize_username(username)

    if normalized_username in DEFAULT_ADMIN_USERS or canonical_username in DEFAULT_ADMIN_USERS:
        return ADMIN_ROLE

    if normalized_username in DEFAULT_READ_ONLY_USERS or canonical_username in DEFAULT_READ_ONLY_USERS:
        return READ_ONLY_ROLE

    roles = get_roles()
    return roles.get(normalized_username, roles.get(canonical_username, READ_ONLY_ROLE))


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
    users.update(get_allowed_users())
    return sorted(user for user in users if user)


def allowed_users():
    return sorted(get_allowed_users())


def is_allowed_user(username):
    normalized_username = _normalize_username(username)
    canonical_username = canonicalize_username(username)
    allowed = get_allowed_users()
    roles = get_roles()
    return (
        normalized_username in allowed
        or canonical_username in allowed
        or normalized_username in roles
        or canonical_username in roles
    )
