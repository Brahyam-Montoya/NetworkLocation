import base64
import json
import secrets
from urllib.parse import urlencode

import requests

from config import (
    AZURE_ENABLED,
    AZURE_AUTHORIZE_URL,
    AZURE_CLIENT_ID,
    AZURE_CLIENT_SECRET,
    AZURE_REDIRECT_URI,
    AZURE_TOKEN_URL
)


def build_auth_url(session, redirect_uri=None):
    if not AZURE_ENABLED:
        raise ValueError("Microsoft Entra no esta configurado completamente en el archivo .env.")

    state = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(24)
    session["auth_state"] = state
    session["auth_nonce"] = nonce

    redirect_uri = redirect_uri or session.get("auth_redirect_uri") or AZURE_REDIRECT_URI
    session["auth_redirect_uri"] = redirect_uri

    params = {
        "client_id": AZURE_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "response_mode": "query",
        "scope": "openid profile email User.Read",
        "state": state,
        "nonce": nonce
    }

    return f"{AZURE_AUTHORIZE_URL}?{urlencode(params)}"


def exchange_code_for_claims(code, redirect_uri=None):
    if not AZURE_CLIENT_SECRET:
        return {"status": "error", "message": "AZURE_CLIENT_SECRET no esta configurado."}

    redirect_uri = redirect_uri or AZURE_REDIRECT_URI

    try:
        response = _request_without_proxy().post(
            AZURE_TOKEN_URL,
            data={
                "client_id": AZURE_CLIENT_ID,
                "client_secret": AZURE_CLIENT_SECRET,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "scope": "openid profile email User.Read"
            },
            timeout=30
        )
    except Exception as error:
        return {"status": "error", "message": f"No fue posible conectar con Microsoft Entra ID: {error}"}

    if response.status_code >= 300:
        return {"status": "error", "message": response.text}

    token_data = response.json()
    claims = decode_id_token(token_data.get("id_token", ""))
    return {"status": "ok", "claims": claims, "token_data": token_data}


def decode_id_token(id_token):
    try:
        payload = id_token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        decoded = base64.urlsafe_b64decode(payload.encode("utf-8"))
        return json.loads(decoded)
    except Exception:
        return {}


def username_from_claims(claims):
    for key in ("preferred_username", "email", "upn", "unique_name"):
        value = claims.get(key)
        if value:
            return value.strip().lower()
    return ""


def _request_without_proxy():
    session = requests.Session()
    session.trust_env = False
    return session
