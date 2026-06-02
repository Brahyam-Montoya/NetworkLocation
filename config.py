import os
from urllib.parse import urljoin


def _load_env_file(filepath=".env"):
    if not os.path.exists(filepath):
        return

    with open(filepath, "r", encoding="utf-8") as file:
      for line in file:
        line = line.strip()

        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env_file()


def _csv_env(name, default):
    value = os.getenv(name, default)
    return [item.strip().lower() for item in value.split(",") if item.strip()]


def _mapping_env(name, default):
    raw_value = os.getenv(name, default)
    mapping = {}

    for item in raw_value.split(","):
        if ":" not in item:
            continue

        key, value = item.split(":", 1)
        normalized_key = key.strip().lower()
        normalized_value = value.strip().lower()

        if normalized_key and normalized_value:
            mapping[normalized_key] = normalized_value

    return mapping


def _normalize_env_value(name, default=""):
    return os.getenv(name, default).strip().lower()


PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
SECRET_KEY = os.getenv("SECRET_KEY", "networklocation_secret_key")
PORT = int(os.getenv("PORT", "5000"))
APP_BASE_URL = os.getenv("APP_BASE_URL", f"http://localhost:{PORT}").rstrip("/")
UPLOAD_FOLDER = os.path.join(PROJECT_ROOT, "uploads")
LOGS_DIR = os.path.join(PROJECT_ROOT, "logs")
EVIDENCE_DIR = os.path.join(LOGS_DIR, "evidence")
EXECUTION_LOGS_FILE = os.path.join(LOGS_DIR, "execution_logs.json")
ROLES_FILE = os.path.join(LOGS_DIR, "user_roles.json")
ALLOWED_USERS_FILE = os.path.join(LOGS_DIR, "allowed_users.json")
IP_INVENTORY_INDEX_FILE = os.path.join(LOGS_DIR, "ip_inventory_index.json")

DEFAULT_ADMIN_USERS = set(
    _csv_env(
        "DEFAULT_ADMIN_USERS",
        "admin,brahyam,brahyammontoya@gammalab14.online,aurrego,aurrego@gammalab14.online"
    )
)
DEFAULT_READ_ONLY_USERS = set(
    _csv_env(
        "DEFAULT_READ_ONLY_USERS",
        "bsmontoy@bancolombia.com.co"
    )
)
LOCAL_LOGIN_ALIASES = _mapping_env(
    "LOCAL_LOGIN_ALIASES",
    "admin:brahyammontoya@gammalab14.online,brahyam:brahyammontoya@gammalab14.online,aurrego:aurrego@gammalab14.online"
)
LOCAL_LOGIN_OTP_TARGETS = _mapping_env(
    "LOCAL_LOGIN_OTP_TARGETS",
    "admin:brahyam.montoya@gammaingenieros.com,brahyam:brahyam.montoya@gammaingenieros.com"
)
DEFAULT_OTP_EMAIL = _normalize_env_value("DEFAULT_OTP_EMAIL")
GLOBAL_ADMIN_USER = "brahyammontoya@gammalab14.online"
LOCAL_LOGIN_ENABLED = os.getenv("LOCAL_LOGIN_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
LOCAL_OTP_TTL_MINUTES = int(os.getenv("LOCAL_OTP_TTL_MINUTES", "10"))

AZURE_TENANT_ID = os.getenv("AZURE_TENANT_ID", "")
AZURE_CLIENT_ID = os.getenv("AZURE_CLIENT_ID", "")
AZURE_CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET", "")
AZURE_REDIRECT_URI = os.getenv("AZURE_REDIRECT_URI", f"{APP_BASE_URL}/auth/callback")
AZURE_AUTHORITY = f"https://login.microsoftonline.com/{AZURE_TENANT_ID}" if AZURE_TENANT_ID else ""
AZURE_AUTHORIZE_URL = f"{AZURE_AUTHORITY}/oauth2/v2.0/authorize" if AZURE_AUTHORITY else ""
AZURE_TOKEN_URL = f"{AZURE_AUTHORITY}/oauth2/v2.0/token" if AZURE_AUTHORITY else ""
AZURE_LOGOUT_URL = f"{AZURE_AUTHORITY}/oauth2/v2.0/logout" if AZURE_AUTHORITY else ""
POST_LOGOUT_REDIRECT_URI = urljoin(f"{APP_BASE_URL}/", "")
AZURE_ENABLED = bool(AZURE_TENANT_ID and AZURE_CLIENT_ID and AZURE_CLIENT_SECRET and AZURE_AUTHORIZE_URL and AZURE_TOKEN_URL)

NETSKOPE_BASE_URL = os.getenv("NETSKOPE_BASE_URL", "https://gammaingenieros-co.goskope.com")
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", SMTP_USER or "")
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").strip().lower() in {"1", "true", "yes", "on"}
