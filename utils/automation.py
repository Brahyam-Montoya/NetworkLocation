import json
import subprocess


def _run_automation_runner(script_name, payload):
    completed = subprocess.run(
        ["node", script_name],
        input=json.dumps(payload),
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False
    )

    stdout = (completed.stdout or "").strip()
    stderr = (completed.stderr or "").strip()

    if not stdout:
        return {
            "status": "failed",
            "message": stderr or "El runner de automatizacion no devolvio respuesta.",
            "screenshots": [],
            "logsPath": None
        }

    try:
        result = json.loads(stdout)
    except json.JSONDecodeError:
        return {
            "status": "failed",
            "message": f"Respuesta invalida del runner: {stdout[:300]}",
            "screenshots": [],
            "logsPath": None
        }

    if completed.returncode != 0 and result.get("status") != "failed":
        result["status"] = "failed"
        result["message"] = stderr or result.get("message", "La automatizacion termino con error.")

    return result


def run_network_location_automation(run_id, stored_file_path, network_location_name, apply_change_message, approval_recipient=None):
    payload = {
        "id": run_id,
        "storedFilePath": stored_file_path,
        "networkLocationName": network_location_name,
        "applyChangeMessage": apply_change_message,
        "approvalRecipient": approval_recipient
    }

    return _run_automation_runner("automation_runner.mjs", payload)


def run_ip_inventory_automation(run_id):
    payload = {"id": run_id}
    return _run_automation_runner("inventory_automation_runner.mjs", payload)
