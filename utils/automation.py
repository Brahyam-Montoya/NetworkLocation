import json
import subprocess


def run_network_location_automation(run_id, stored_file_path, network_location_name):
    payload = {
        "id": run_id,
        "storedFilePath": stored_file_path,
        "networkLocationName": network_location_name
    }

    completed = subprocess.run(
        ["node", "automation_runner.mjs"],
        input=json.dumps(payload),
        text=True,
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
