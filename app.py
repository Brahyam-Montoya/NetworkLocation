import os
import time
from flask import Flask, abort, redirect, render_template, request, send_from_directory, session, url_for

from config import (
    AZURE_ENABLED,
    AZURE_LOGOUT_URL,
    GLOBAL_ADMIN_USER,
    LOCAL_LOGIN_ENABLED,
    LOCAL_OTP_TTL_MINUTES,
    PROJECT_ROOT,
    PORT,
    SECRET_KEY,
    UPLOAD_FOLDER
)
from utils.audit import clear_execution_data, get_log, get_logs, save_log, update_log
from utils.automation import run_network_location_automation
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
from utils.roles import (
    ADMIN_ROLE,
    READ_ONLY_ROLE,
    allow_user,
    allowed_users,
    canonicalize_username,
    get_roles,
    get_user_role,
    is_admin,
    is_allowed_user,
    resolve_otp_recipient,
    set_user_role,
    visible_users
)
from utils.storage import ensure_app_dirs, save_upload_file, utc_now_iso

app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
ensure_app_dirs()


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


@app.context_processor
def inject_user_context():
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

    logs = get_logs()
    message = session.pop("dashboard_message", None)
    return render_template("dashboard.html", logs=logs, message=message)


@app.route("/ip-consulta")
def ip_lookup():
    login_redirect = require_login()
    if login_redirect:
        return login_redirect

    inventory = load_ip_inventory_index()
    message = session.pop("ip_lookup_message", None)
    pasted_response = session.pop("ip_lookup_pasted_response", "")
    query_ip = request.args.get("ip", "").strip()
    results = []
    search_error = None

    if query_ip:
        if not inventory:
            search_error = "Primero debes cargar un archivo con la respuesta copiada desde DevTools."
        else:
            try:
                results = search_ip_inventory(inventory, query_ip)
            except ValueError as error:
                search_error = str(error)

    return render_template(
        "ip_lookup.html",
        inventory=inventory,
        message=message,
        pasted_response=pasted_response,
        query_ip=query_ip,
        results=results,
        search_error=search_error
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

    if not any(absolute_path.startswith(root) for root in allowed_roots):
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
        session["ip_lookup_message"] = {
            "type": "danger",
            "text": "No se encontro el archivo exportado desde DevTools."
        }
        return redirect(url_for("ip_lookup"))

    file = request.files["file"]
    if not file or file.filename == "":
        session["ip_lookup_message"] = {
            "type": "danger",
            "text": "Debes seleccionar un archivo .json, .txt o .csv."
        }
        return redirect(url_for("ip_lookup"))

    stored_file_path = save_upload_file(file)

    try:
        inventory_index = process_ip_inventory_file(stored_file_path, file.filename)
        save_ip_inventory_index(inventory_index)
    except ValueError as error:
        session["ip_lookup_message"] = {
            "type": "danger",
            "text": str(error)
        }
        return redirect(url_for("ip_lookup"))

    session["ip_lookup_message"] = {
        "type": "success",
        "text": (
            f"Indice actualizado con {inventory_index['total_locations']} Network Locations "
            f"y {inventory_index['total_entries']} entradas."
        )
    }
    return redirect(url_for("ip_lookup"))


@app.route("/ip-consulta/paste", methods=["POST"])
def ip_lookup_paste():
    login_redirect = require_login()
    if login_redirect:
        return login_redirect

    pasted_response = request.form.get("pasted_response", "").strip()
    session["ip_lookup_pasted_response"] = pasted_response

    if not pasted_response:
        session["ip_lookup_message"] = {
            "type": "danger",
            "text": "Debes pegar el contenido de Copy response antes de cargarlo."
        }
        return redirect(url_for("ip_lookup"))

    pasted_file_name = request.form.get("pasted_file_name", "").strip() or "copied-response.json"
    stored_file_path = os.path.join(app.config["UPLOAD_FOLDER"], f"manual-{utc_now_iso().replace(':', '-')}-{pasted_file_name}")

    with open(stored_file_path, "w", encoding="utf-8") as file:
        file.write(pasted_response)

    try:
        inventory_index = process_ip_inventory_file(stored_file_path, pasted_file_name)
        save_ip_inventory_index(inventory_index)
    except ValueError as error:
        session["ip_lookup_message"] = {
            "type": "danger",
            "text": str(error)
        }
        return redirect(url_for("ip_lookup"))

    session["ip_lookup_pasted_response"] = ""
    session["ip_lookup_message"] = {
        "type": "success",
        "text": (
            f"Indice actualizado con {inventory_index['total_locations']} Network Locations "
            f"y {inventory_index['total_entries']} entradas desde texto pegado."
        )
    }
    return redirect(url_for("ip_lookup"))


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
        network_location_name=payload["network_location_name"]
    )

    update_log(
        log_entry["id"],
        {
            "status": result.get("status", "failed"),
            "message": result.get("message", "Sin mensaje."),
            "finished_at": utc_now_iso(),
            "screenshots": result.get("screenshots", []),
            "logs_path": result.get("logsPath"),
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
        network_location_name=log["network_location_name"]
    )

    update_log(
        run_id,
        {
            "status": result.get("status", "failed"),
            "message": result.get("message", "Sin mensaje."),
            "finished_at": utc_now_iso(),
            "screenshots": result.get("screenshots", []),
            "logs_path": result.get("logsPath"),
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
        if username:
            allow_user(username)
            set_user_role(username, role)
        return redirect(url_for("roles_panel"))

    logs = get_logs()
    return render_template(
        "roles.html",
        users=visible_users(logs),
        roles=get_roles(),
        get_user_role=get_user_role,
        admin_role=ADMIN_ROLE,
        read_only_role=READ_ONLY_ROLE
    )


@app.route("/clear-all", methods=["POST"])
def clear_all():
    global_admin_redirect = require_global_admin()
    if global_admin_redirect:
        return global_admin_redirect

    clear_execution_data()
    clear_ip_inventory_index()
    session["dashboard_message"] = "Dashboard, historial y evidencias limpiados correctamente."
    return redirect(url_for("dashboard"))


@app.errorhandler(403)
def forbidden(_error):
    return render_template("forbidden.html"), 403


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=False)
