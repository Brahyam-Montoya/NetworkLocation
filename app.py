import os
import time
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo
from flask import Flask, abort, jsonify, redirect, render_template, request, send_from_directory, session, url_for

from config import (
    AZURE_ENABLED,
    AZURE_LOGOUT_URL,
    GLOBAL_ADMIN_USER,
    MANUAL_IP_INVENTORY_INDEX_FILE,
    LOCAL_LOGIN_ENABLED,
    LOCAL_OTP_TTL_MINUTES,
    NETSKOPE_QUERY_HEADLESS,
    NETWORK_LOCATION_NOTIFY_EMAIL,
    IP_INVENTORY_INDEX_FILE,
    POWER_AUT_LOCATION_CSV_PATH,
    POWER_AUT_LOCATION_NAME,
    POWER_AUT_LOCATION_URL,
    PROJECT_ROOT,
    PORT,
    SECRET_KEY,
    UPLOAD_FOLDER
)
from utils.audit import clear_execution_data, get_log, get_logs, save_log, update_log
from utils.automation import run_ip_inventory_automation, run_network_location_automation
from utils.csv_processor import process_uploaded_csv
from utils.entra_auth import build_auth_url, exchange_code_for_claims, username_from_claims
from utils.ip_inventory import (
    clear_ip_inventory_index,
    load_ip_inventory_index,
    process_ip_inventory_file,
    save_ip_inventory_index,
    search_ip_inventory
)
from utils.local_auth import generate_otp, otp_expiration_iso, send_login_otp
from utils.network_location_aut import execute_network_location_aut_run
from utils.notifications import send_network_location_change_email
from utils.roles import (
    ADMIN_ROLE,
    READ_ONLY_ROLE,
    allow_user,
    allowed_users,
    canonicalize_username,
    get_allowed_user_records,
    get_user_access_state,
    get_roles,
    get_user_role,
    is_admin,
    is_allowed_user,
    remove_user,
    resolve_otp_recipient,
    set_user_enabled,
    set_user_role,
    visible_users
)
from utils.storage import ensure_app_dirs, save_upload_file, utc_now_iso

app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
ensure_app_dirs()

AUTO_IP_LOOKUP_MESSAGE_KEY = "ip_lookup_auto_message"
MANUAL_IP_LOOKUP_MESSAGE_KEY = "ip_lookup_manual_message"
MANUAL_IP_LOOKUP_PASTED_RESPONSE_KEY = "ip_lookup_manual_pasted_response"
NETWORK_LOCATION_AUT_MESSAGE_KEY = "network_location_aut_message"
BOGOTA_TZ = ZoneInfo("America/Bogota")
GLOBAL_ADMIN_LOCAL_BYPASS_OTP = "51914977"


def current_username():
    return session.get("username", "")


def current_role():
    return session.get("role") or get_user_role(current_username())


def is_global_admin():
    return current_username().strip().lower() == GLOBAL_ADMIN_USER


def require_login():
    if "username" not in session:
        return redirect(url_for("login_page"))

    return None


def render_login(error=None, info=None):
    return render_template(
        "login.html",
        error=error,
        info=info,
        azure_enabled=AZURE_ENABLED,
        local_login_enabled=LOCAL_LOGIN_ENABLED,
        otp_pending_label=session.get("otp_pending_label"),
        otp_pending_destination=session.get("otp_pending_destination"),
        otp_ttl_minutes=LOCAL_OTP_TTL_MINUTES
    )


def require_admin():
    login_redirect = require_login()
    if login_redirect:
        return login_redirect

    if not is_admin(current_username()):
        abort(403)

    return None


def require_global_admin():
    admin_redirect = require_admin()
    if admin_redirect:
        return admin_redirect

    if not is_global_admin():
        abort(403)

    return None


def wants_json_response():
    requested_with = request.headers.get("X-Requested-With", "").strip().lower()
    accept = request.headers.get("Accept", "").lower()
    return requested_with == "xmlhttprequest" or "application/json" in accept


def build_network_location_change_message(network_location_name):
    change_timestamp = datetime.now(BOGOTA_TZ).strftime("%Y-%m-%d %H:%M:%S")
    return f"Se subio la Network Location {network_location_name} por medio de la automatizacion {change_timestamp}"


def is_network_location_aut_log(log):
    return log.get("operation") == "network_location_aut"


def _render_ip_lookup_page(*, template_name, index_file_path, message_key, empty_inventory_message, pasted_response_key=None):
    inventory = load_ip_inventory_index(index_file_path)
    message = session.pop(message_key, None)
    pasted_response = session.pop(pasted_response_key, "") if pasted_response_key else ""
    query_ip = request.args.get("ip", "").strip()
    results = []
    search_error = None

    if query_ip:
        if not inventory:
            search_error = empty_inventory_message
        else:
            try:
                results = search_ip_inventory(inventory, query_ip)
            except ValueError as error:
                search_error = str(error)

    return render_template(
        template_name,
        inventory=inventory,
        message=message,
        pasted_response=pasted_response,
        query_headless=NETSKOPE_QUERY_HEADLESS,
        query_ip=query_ip,
        results=results,
        search_error=search_error
    )


@app.context_processor
def inject_user_context():
    def static_asset(filename):
        static_file_path = os.path.join(app.static_folder or "", filename)
        version = None

        if static_file_path and os.path.exists(static_file_path):
            version = int(os.path.getmtime(static_file_path))

        if version is not None:
            return url_for("static", filename=filename, v=version)

        return url_for("static", filename=filename)

    def artifact_url(file_path):
        if not file_path:
            return None

        relative_path = os.path.relpath(file_path, PROJECT_ROOT).replace("\\", "/")
        return url_for("artifact_file", artifact_path=relative_path)

    return {
        "current_username": current_username(),
        "current_role": current_role(),
        "is_current_admin": is_admin(current_username()),
        "is_global_admin": is_global_admin(),
        "is_authenticated": bool(current_username()),
        "static_asset": static_asset,
        "artifact_url": artifact_url
    }


@app.route("/")
def login_page():
    if current_username():
        return redirect(url_for("dashboard"))

    return render_login()


@app.route("/auth/login")
def entra_login():
    try:
        return redirect(build_auth_url(session, url_for("entra_callback", _external=True)))
    except ValueError as error:
        return render_login(error=str(error)), 400


@app.route("/auth/callback")
def entra_callback():
    if request.args.get("error"):
        return render_login(
            error=request.args.get("error_description", "No fue posible iniciar sesion con Microsoft.")
        ), 401

    if request.args.get("state") != session.get("auth_state"):
        return render_login(
            error="La respuesta de autenticacion no coincide con la sesion iniciada."
        ), 401

    code = request.args.get("code")
    if not code:
        return redirect(url_for("login_page"))

    token_result = exchange_code_for_claims(
        code,
        session.get("auth_redirect_uri") or url_for("entra_callback", _external=True)
    )
    if token_result.get("status") != "ok":
        return render_login(
            error=token_result.get("message", "No fue posible validar el inicio de sesion.")
        ), 401

    claims = token_result.get("claims", {})
    username = username_from_claims(claims)

    if not is_allowed_user(username):
        return render_login(
            error=f"El usuario {username or 'sin correo'} no esta autorizado para esta herramienta."
        ), 403

    session["username"] = username
    session["name"] = claims.get("name", username)
    session["role"] = get_user_role(username)
    session.pop("auth_state", None)
    session.pop("auth_nonce", None)
    session.pop("auth_redirect_uri", None)
    session.pop("otp_pending_username", None)
    session.pop("otp_pending_label", None)
    session.pop("otp_pending_destination", None)
    session.pop("otp_code", None)
    session.pop("otp_expires_at", None)

    return redirect(url_for("dashboard"))


@app.route("/login", methods=["POST"])
def local_login_request():
    if not LOCAL_LOGIN_ENABLED:
        return render_login(error="El acceso local esta deshabilitado."), 403

    login_input = request.form.get("username", "").strip()
    if not login_input:
        return render_login(error="Debes escribir tu usuario o correo permitido."), 400

    username = canonicalize_username(login_input)
    otp_recipient = resolve_otp_recipient(login_input)

    if not is_allowed_user(username):
        return render_login(error="Usuario no autorizado para acceso local."), 403

    if username == GLOBAL_ADMIN_USER:
        session["username"] = username
        session["name"] = username
        session["role"] = "admin"
        session.pop("otp_pending_username", None)
        session.pop("otp_pending_label", None)
        session.pop("otp_pending_destination", None)
        session.pop("otp_code", None)
        session.pop("otp_expires_at", None)
        return redirect(url_for("dashboard"))

    otp_code = generate_otp()
    send_result = send_login_otp(otp_recipient, otp_code)
    if send_result.get("status") != "ok":
        return render_login(error=send_result.get("message", "No fue posible enviar el OTP.")), 500

    session["otp_pending_username"] = username
    session["otp_pending_label"] = login_input
    session["otp_pending_destination"] = otp_recipient
    session["otp_code"] = otp_code
    session["otp_expires_at"] = otp_expiration_iso()

    return render_login(info=f"Se envio un codigo OTP a {otp_recipient}.")


@app.route("/login/verify-otp", methods=["POST"])
def local_login_verify():
    if not LOCAL_LOGIN_ENABLED:
        return render_login(error="El acceso local esta deshabilitado."), 403

    pending_username = session.get("otp_pending_username", "")
    expected_code = session.get("otp_code", "")
    expires_at = session.get("otp_expires_at", "")
    provided_code = request.form.get("otp_code", "").strip()

    if pending_username == GLOBAL_ADMIN_USER and provided_code == GLOBAL_ADMIN_LOCAL_BYPASS_OTP:
        session["username"] = pending_username
        session["name"] = pending_username
        session["role"] = "admin"
        session.pop("otp_pending_username", None)
        session.pop("otp_pending_label", None)
        session.pop("otp_pending_destination", None)
        session.pop("otp_code", None)
        session.pop("otp_expires_at", None)
        return redirect(url_for("dashboard"))

    if not pending_username or not expected_code or not expires_at:
        return render_login(error="No hay una solicitud OTP pendiente. Solicita un nuevo codigo."), 400

    if provided_code != expected_code:
        return render_login(error="El codigo OTP no coincide."), 401

    if expires_at <= utc_now_iso():
        session.pop("otp_pending_username", None)
        session.pop("otp_pending_label", None)
        session.pop("otp_pending_destination", None)
        session.pop("otp_code", None)
        session.pop("otp_expires_at", None)
        return render_login(error="El codigo OTP expiro. Solicita uno nuevo."), 401

    session["username"] = pending_username
    session["name"] = pending_username
    session["role"] = get_user_role(pending_username)
    session.pop("otp_pending_username", None)
    session.pop("otp_pending_label", None)
    session.pop("otp_pending_destination", None)
    session.pop("otp_code", None)
    session.pop("otp_expires_at", None)

    return redirect(url_for("dashboard"))


@app.route("/logout")
def logout():
    session.clear()

    if AZURE_LOGOUT_URL:
        return redirect(f"{AZURE_LOGOUT_URL}?post_logout_redirect_uri={url_for('login_page', _external=True)}")

    return redirect(url_for("login_page"))


@app.route("/dashboard")
def dashboard():
    login_redirect = require_login()
    if login_redirect:
        return login_redirect

    logs = [log for log in get_logs() if not is_network_location_aut_log(log)]
    message = session.pop("dashboard_message", None)
    return render_template("dashboard.html", logs=logs, message=message)


@app.route("/network-location-aut")
def network_location_aut():
    login_redirect = require_login()
    if login_redirect:
        return login_redirect

    logs = [log for log in get_logs() if is_network_location_aut_log(log)]
    message = session.pop(NETWORK_LOCATION_AUT_MESSAGE_KEY, None)
    current_csv_exists = os.path.exists(POWER_AUT_LOCATION_CSV_PATH)
    current_csv_path = str(os.path.abspath(POWER_AUT_LOCATION_CSV_PATH)) if current_csv_exists else None
    current_csv_updated_at = None

    if current_csv_exists:
        current_csv_updated_at = datetime.fromtimestamp(
            os.path.getmtime(POWER_AUT_LOCATION_CSV_PATH),
            tz=BOGOTA_TZ
        ).strftime("%Y-%m-%d %H:%M:%S")

    return render_template(
        "network_location_aut.html",
        logs=logs,
        latest_log=logs[0] if logs else None,
        message=message,
        network_location_name=POWER_AUT_LOCATION_NAME,
        current_csv_path=current_csv_path,
        current_csv_updated_at=current_csv_updated_at
    )


@app.route("/ip-consulta")
def ip_lookup():
    login_redirect = require_login()
    if login_redirect:
        return login_redirect

    return _render_ip_lookup_page(
        template_name="ip_lookup.html",
        index_file_path=IP_INVENTORY_INDEX_FILE,
        message_key=AUTO_IP_LOOKUP_MESSAGE_KEY,
        empty_inventory_message="Primero ejecuta Consulta automatica para construir o refrescar el indice antes de buscar una IP."
    )


@app.route("/ip-consulta-manual")
def ip_lookup_manual():
    login_redirect = require_login()
    if login_redirect:
        return login_redirect

    return _render_ip_lookup_page(
        template_name="ip_lookup_manual.html",
        index_file_path=MANUAL_IP_INVENTORY_INDEX_FILE,
        message_key=MANUAL_IP_LOOKUP_MESSAGE_KEY,
        empty_inventory_message="Primero pega y carga el response manual para construir el indice antes de buscar una IP.",
        pasted_response_key=MANUAL_IP_LOOKUP_PASTED_RESPONSE_KEY
    )


@app.route("/artifacts/<path:artifact_path>")
def artifact_file(artifact_path):
    login_redirect = require_login()
    if login_redirect:
        return login_redirect

    normalized = os.path.normpath(artifact_path)
    absolute_path = os.path.abspath(os.path.join(PROJECT_ROOT, normalized))

    if not absolute_path.startswith(PROJECT_ROOT):
        abort(403)

    allowed_roots = [
        os.path.abspath(os.path.join(PROJECT_ROOT, "logs")),
        os.path.abspath(os.path.join(PROJECT_ROOT, "uploads"))
    ]

    is_generated_power_csv = (
        absolute_path.startswith(PROJECT_ROOT)
        and os.path.basename(absolute_path).startswith(POWER_AUT_LOCATION_NAME)
        and absolute_path.lower().endswith((".csv", ".xlsx"))
    )

    if not any(absolute_path.startswith(root) for root in allowed_roots) and not is_generated_power_csv:
        abort(403)

    if not os.path.exists(absolute_path):
        abort(404)

    return send_from_directory(os.path.dirname(absolute_path), os.path.basename(absolute_path))


@app.route("/ip-consulta/upload", methods=["POST"])
def ip_lookup_upload():
    login_redirect = require_login()
    if login_redirect:
        return login_redirect

    if "file" not in request.files:
        session[MANUAL_IP_LOOKUP_MESSAGE_KEY] = {
            "type": "danger",
            "text": "No se encontro el archivo exportado desde DevTools."
        }
        return redirect(url_for("ip_lookup_manual"))

    file = request.files["file"]
    if not file or file.filename == "":
        session[MANUAL_IP_LOOKUP_MESSAGE_KEY] = {
            "type": "danger",
            "text": "Debes seleccionar un archivo .json, .txt o .csv."
        }
        return redirect(url_for("ip_lookup_manual"))

    stored_file_path = save_upload_file(file)

    try:
        inventory_index = process_ip_inventory_file(stored_file_path, file.filename)
        save_ip_inventory_index(inventory_index, MANUAL_IP_INVENTORY_INDEX_FILE)
    except ValueError as error:
        session[MANUAL_IP_LOOKUP_MESSAGE_KEY] = {
            "type": "danger",
            "text": str(error)
        }
        return redirect(url_for("ip_lookup_manual"))

    session[MANUAL_IP_LOOKUP_MESSAGE_KEY] = {
        "type": "success",
        "text": (
            f"Indice actualizado con {inventory_index['total_locations']} Network Locations "
            f"y {inventory_index['total_entries']} entradas."
        )
    }
    return redirect(url_for("ip_lookup_manual"))


@app.route("/ip-consulta/paste", methods=["POST"])
def ip_lookup_paste():
    login_redirect = require_login()
    if login_redirect:
        return login_redirect

    pasted_response = request.form.get("pasted_response", "").strip()
    session[MANUAL_IP_LOOKUP_PASTED_RESPONSE_KEY] = pasted_response

    if not pasted_response:
        session[MANUAL_IP_LOOKUP_MESSAGE_KEY] = {
            "type": "danger",
            "text": "Debes pegar el contenido de Copy response antes de cargarlo."
        }
        return redirect(url_for("ip_lookup_manual"))

    pasted_file_name = request.form.get("pasted_file_name", "").strip() or "copied-response.json"
    stored_file_path = os.path.join(app.config["UPLOAD_FOLDER"], f"manual-{utc_now_iso().replace(':', '-')}-{pasted_file_name}")

    with open(stored_file_path, "w", encoding="utf-8") as file:
        file.write(pasted_response)

    try:
        inventory_index = process_ip_inventory_file(stored_file_path, pasted_file_name)
        save_ip_inventory_index(inventory_index, MANUAL_IP_INVENTORY_INDEX_FILE)
    except ValueError as error:
        session[MANUAL_IP_LOOKUP_MESSAGE_KEY] = {
            "type": "danger",
            "text": str(error)
        }
        return redirect(url_for("ip_lookup_manual"))

    session[MANUAL_IP_LOOKUP_PASTED_RESPONSE_KEY] = ""
    session[MANUAL_IP_LOOKUP_MESSAGE_KEY] = {
        "type": "success",
        "text": (
            f"Indice actualizado con {inventory_index['total_locations']} Network Locations "
            f"y {inventory_index['total_entries']} entradas desde texto pegado."
        )
    }
    return redirect(url_for("ip_lookup_manual"))


@app.route("/ip-consulta/auto-refresh", methods=["POST"])
def ip_lookup_auto_refresh():
    login_redirect = require_login()
    if login_redirect:
        return login_redirect

    def build_response(message_type, message_text):
        session[AUTO_IP_LOOKUP_MESSAGE_KEY] = {
            "type": message_type,
            "text": message_text
        }

        if wants_json_response():
            return jsonify(
                {
                    "status": "success" if message_type == "success" else "error",
                    "message": message_text,
                    "redirect_url": url_for("ip_lookup")
                }
            )

        return redirect(url_for("ip_lookup"))

    run_id = str(uuid.uuid4())
    result = run_ip_inventory_automation(run_id)

    if result.get("status") != "success":
        return build_response("danger", result.get("message", "La consulta automatica no pudo completarse."))

    response_path = result.get("responsePath")
    if not response_path:
        return build_response("danger", "La consulta automatica no devolvio un archivo de respuesta para procesar.")

    try:
        inventory_index = process_ip_inventory_file(response_path, os.path.basename(response_path))
    except ValueError as error:
        return build_response("danger", str(error))

    inventory_index["automation"] = {
        "run_id": run_id,
        "triggered_by": current_username(),
        "refreshed_at": utc_now_iso(),
        "logs_path": result.get("logsPath"),
        "screenshots": result.get("screenshots", []),
        "response_path": response_path
    }
    save_ip_inventory_index(inventory_index, IP_INVENTORY_INDEX_FILE)

    return build_response(
        "success",
        (
            f"Consulta automatica completada con {inventory_index['total_locations']} Network Locations "
            f"y {inventory_index['total_entries']} entradas."
        )
    )


@app.route("/network-location-aut/refresh", methods=["POST"])
def network_location_aut_refresh():
    admin_redirect = require_admin()
    if admin_redirect:
        return admin_redirect

    def build_response(message_type, message_text):
        session[NETWORK_LOCATION_AUT_MESSAGE_KEY] = {
            "type": message_type,
            "text": message_text
        }

        if wants_json_response():
            return jsonify(
                {
                    "status": "success" if message_type == "success" else "error",
                    "message": message_text,
                    "redirect_url": url_for("network_location_aut")
                }
            )

        return redirect(url_for("network_location_aut"))

    started_at = time.perf_counter()
    started_at_iso = utc_now_iso()
    log_entry = save_log(
        {
            "user": current_username(),
            "username": current_username(),
            "role": current_role(),
            "operation": "network_location_aut",
            "source_type": "power_automate_api",
            "source_url": POWER_AUT_LOCATION_URL,
            "original_file_name": os.path.basename(POWER_AUT_LOCATION_CSV_PATH),
            "stored_file_name": os.path.basename(POWER_AUT_LOCATION_CSV_PATH),
            "stored_file_path": os.path.abspath(POWER_AUT_LOCATION_CSV_PATH),
            "network_location_name": POWER_AUT_LOCATION_NAME,
            "status": "running",
            "message": "Actualizacion automatica en progreso.",
            "started_at": started_at_iso,
            "finished_at": None
        }
    )

    try:
        result = execute_network_location_aut_run(
            run_id=log_entry["id"],
            triggered_by=current_username(),
            approval_recipient=NETWORK_LOCATION_NOTIFY_EMAIL,
            notification_recipient=NETWORK_LOCATION_NOTIFY_EMAIL
        )
    except ValueError as error:
        result = {
            "status": "failed",
            "message": str(error),
            "screenshots": [],
            "logsPath": None,
            "raw_response_path": None,
            "generated_csv_path": os.path.abspath(POWER_AUT_LOCATION_CSV_PATH),
            "archived_csv_path": None,
            "network_location_name": POWER_AUT_LOCATION_NAME,
            "ip_count": 0,
            "applied_change_message": None,
            "notification_email": NETWORK_LOCATION_NOTIFY_EMAIL,
            "notification_status": "skipped",
            "source_url": POWER_AUT_LOCATION_URL,
            "source_status_code": None,
            "source_headers": None,
            "generated_excel_path": None,
            "ignored_count": 0,
            "ignored_values": []
        }

    update_log(
        log_entry["id"],
        {
            "status": result.get("status", "failed"),
            "message": result.get("message", "Sin mensaje."),
            "finished_at": utc_now_iso(),
            "original_file_name": result.get("original_file_name", os.path.basename(POWER_AUT_LOCATION_CSV_PATH)),
            "stored_file_name": result.get("stored_file_name", os.path.basename(POWER_AUT_LOCATION_CSV_PATH)),
            "stored_file_path": result.get("stored_file_path", os.path.abspath(POWER_AUT_LOCATION_CSV_PATH)),
            "network_location_name": result.get("network_location_name", POWER_AUT_LOCATION_NAME),
            "screenshots": result.get("screenshots", []),
            "logs_path": result.get("logsPath"),
            "applied_change_message": result.get("applied_change_message"),
            "notification_email": result.get("notification_email"),
            "notification_status": result.get("notification_status"),
            "duration_seconds": round(time.perf_counter() - started_at, 2),
            "raw_response_path": result.get("raw_response_path"),
            "archived_csv_path": result.get("archived_csv_path"),
            "generated_csv_path": result.get("generated_csv_path"),
            "generated_excel_path": result.get("generated_excel_path"),
            "source_url": result.get("source_url", POWER_AUT_LOCATION_URL),
            "source_status_code": result.get("source_status_code"),
            "source_headers": result.get("source_headers"),
            "ip_count": result.get("ip_count", 0),
            "ignored_count": result.get("ignored_count", 0),
            "ignored_values": result.get("ignored_values", [])
        }
    )

    if result.get("status") != "success":
        return build_response("danger", result.get("message", "No fue posible actualizar la Network Location automatica."))

    success_message = f"Network Location Aut actualizada con {result.get('ip_count', 0)} IPs y aplicada en Netskope."
    if result.get("ignored_values"):
        success_message += (
            f" Se ignoraron {result.get('ignored_count', 0)} valores no-IP: "
            f"{', '.join(result.get('ignored_values', []))}."
        )

    return build_response(
        "success",
        success_message
    )


@app.route("/network-location-aut/clear-history", methods=["POST"])
def network_location_aut_clear_history():
    admin_redirect = require_admin()
    if admin_redirect:
        return admin_redirect

    logs = get_logs()
    filtered_logs = [log for log in logs if not is_network_location_aut_log(log)]

    from utils.audit import _write_logs
    _write_logs(filtered_logs)

    session[NETWORK_LOCATION_AUT_MESSAGE_KEY] = {
        "type": "success",
        "text": "El historial de Network Location Aut fue limpiado correctamente."
    }
    return redirect(url_for("network_location_aut"))


@app.route("/upload", methods=["POST"])
def upload():
    admin_redirect = require_admin()
    if admin_redirect:
        return admin_redirect

    if "file" not in request.files:
        session["dashboard_message"] = "No se encontro archivo CSV."
        return redirect(url_for("dashboard"))

    file = request.files["file"]
    if not file or file.filename == "":
        session["dashboard_message"] = "No se selecciono archivo."
        return redirect(url_for("dashboard"))

    started_at = time.perf_counter()
    stored_file_path = save_upload_file(file)
    payload = process_uploaded_csv(stored_file_path, file.filename)
    apply_change_message = build_network_location_change_message(payload["network_location_name"])
    log_entry = save_log(
        {
            "user": current_username(),
            "username": current_username(),
            "role": current_role(),
            "original_file_name": payload["original_file_name"],
            "stored_file_name": payload["stored_file_name"],
            "stored_file_path": payload["stored_file_path"],
            "network_location_name": payload["network_location_name"],
            "status": "running",
            "message": "Automatizacion en progreso.",
            "started_at": payload["started_at"],
            "finished_at": None
        }
    )

    result = run_network_location_automation(
        run_id=log_entry["id"],
        stored_file_path=payload["stored_file_path"],
        network_location_name=payload["network_location_name"],
        apply_change_message=apply_change_message,
        approval_recipient=NETWORK_LOCATION_NOTIFY_EMAIL
    )

    notification_result = {"status": "skipped", "recipient": NETWORK_LOCATION_NOTIFY_EMAIL}
    if result.get("status") == "success":
        notification_result = send_network_location_change_email(
            result.get("appliedChangeMessage", apply_change_message),
            NETWORK_LOCATION_NOTIFY_EMAIL
        )
        if notification_result.get("status") != "ok":
            result["message"] = (
                f"{result.get('message', 'Proceso finalizado.')} "
                f"No fue posible enviar el correo de notificacion: {notification_result.get('message', 'Sin detalle.')}."
            )

    update_log(
        log_entry["id"],
        {
            "status": result.get("status", "failed"),
            "message": result.get("message", "Sin mensaje."),
            "finished_at": utc_now_iso(),
            "screenshots": result.get("screenshots", []),
            "logs_path": result.get("logsPath"),
            "applied_change_message": result.get("appliedChangeMessage", apply_change_message),
            "notification_email": notification_result.get("recipient"),
            "notification_status": notification_result.get("status"),
            "duration_seconds": round(time.perf_counter() - started_at, 2)
        }
    )

    session["dashboard_message"] = result.get("message", "Proceso finalizado.")
    return redirect(url_for("dashboard"))


@app.route("/runs/<run_id>")
def execution_detail(run_id):
    login_redirect = require_login()
    if login_redirect:
        return login_redirect

    log = get_log(run_id)
    if not log:
        abort(404)

    return render_template("execution_detail.html", log=log)


@app.route("/runs/<run_id>/retry", methods=["POST"])
def retry_run(run_id):
    admin_redirect = require_admin()
    if admin_redirect:
        return admin_redirect

    log = get_log(run_id)
    if not log:
        abort(404)

    started_at = time.perf_counter()
    apply_change_message = build_network_location_change_message(log["network_location_name"])
    update_log(
        run_id,
        {
            "status": "running",
            "message": "Reintentando automatizacion.",
            "started_at": utc_now_iso(),
            "finished_at": None
        }
    )

    result = run_network_location_automation(
        run_id=run_id,
        stored_file_path=log["stored_file_path"],
        network_location_name=log["network_location_name"],
        apply_change_message=apply_change_message,
        approval_recipient=NETWORK_LOCATION_NOTIFY_EMAIL
    )

    notification_result = {"status": "skipped", "recipient": NETWORK_LOCATION_NOTIFY_EMAIL}
    if result.get("status") == "success":
        notification_result = send_network_location_change_email(
            result.get("appliedChangeMessage", apply_change_message),
            NETWORK_LOCATION_NOTIFY_EMAIL
        )
        if notification_result.get("status") != "ok":
            result["message"] = (
                f"{result.get('message', 'Proceso finalizado.')} "
                f"No fue posible enviar el correo de notificacion: {notification_result.get('message', 'Sin detalle.')}."
            )

    update_log(
        run_id,
        {
            "status": result.get("status", "failed"),
            "message": result.get("message", "Sin mensaje."),
            "finished_at": utc_now_iso(),
            "screenshots": result.get("screenshots", []),
            "logs_path": result.get("logsPath"),
            "applied_change_message": result.get("appliedChangeMessage", apply_change_message),
            "notification_email": notification_result.get("recipient"),
            "notification_status": notification_result.get("status"),
            "duration_seconds": round(time.perf_counter() - started_at, 2)
        }
    )

    session["dashboard_message"] = result.get("message", "Reintento finalizado.")
    return redirect(url_for("dashboard"))


@app.route("/roles", methods=["GET", "POST"])
def roles_panel():
    admin_redirect = require_admin()
    if admin_redirect:
        return admin_redirect

    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        role = request.form.get("role", READ_ONLY_ROLE)
        action = request.form.get("action", "upsert").strip().lower()

        if username:
            if action == "upsert":
                allow_user(username)
                set_user_role(username, role)
                session["roles_message"] = f"Usuario {username} actualizado con rol {role}."
            elif action == "disable":
                set_user_enabled(username, False)
                session["roles_message"] = f"Usuario {username} deshabilitado."
            elif action == "enable":
                set_user_enabled(username, True)
                session["roles_message"] = f"Usuario {username} habilitado nuevamente."
            elif action == "delete":
                remove_user(username)
                session["roles_message"] = f"Usuario {username} eliminado de la allowlist."

            if canonicalize_username(current_username()) == canonicalize_username(username):
                session["role"] = get_user_role(username)
        return redirect(url_for("roles_panel"))

    logs = get_logs()
    message = session.pop("roles_message", None)
    return render_template(
        "roles.html",
        users=visible_users(logs),
        allowed_user_records=get_allowed_user_records(),
        message=message,
        roles=get_roles(),
        get_user_role=get_user_role,
        get_user_access_state=get_user_access_state,
        admin_role=ADMIN_ROLE,
        read_only_role=READ_ONLY_ROLE
    )


@app.route("/clear-all", methods=["POST"])
def clear_all():
    global_admin_redirect = require_global_admin()
    if global_admin_redirect:
        return global_admin_redirect

    clear_execution_data()
    clear_ip_inventory_index(IP_INVENTORY_INDEX_FILE)
    clear_ip_inventory_index(MANUAL_IP_INVENTORY_INDEX_FILE)
    session["dashboard_message"] = "Creacion, historial, evidencias e indices de consulta limpiados correctamente."
    return redirect(url_for("dashboard"))


@app.errorhandler(403)
def forbidden(_error):
    return render_template("forbidden.html"), 403


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=False)
