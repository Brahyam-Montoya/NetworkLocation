import json
import time

from config import NETWORK_LOCATION_NOTIFY_EMAIL, POWER_AUT_LOCATION_URL
from utils.audit import save_log, update_log
from utils.network_location_aut import execute_network_location_aut_run, resolve_network_location_target
from utils.storage import utc_now_iso


def main():
    target_config = resolve_network_location_target("windows")
    started_at = time.perf_counter()
    started_at_iso = utc_now_iso()
    log_entry = save_log(
        {
            "user": "codex-automation",
            "username": "codex-automation",
            "role": "system",
            "operation": "network_location_aut",
            "source_type": "power_automate_api",
            "source_platform": "windows",
            "source_platform_label": "Windows",
            "source_url": POWER_AUT_LOCATION_URL,
            "original_file_name": target_config["network_location_name"] + ".csv",
            "stored_file_name": target_config["network_location_name"] + ".csv",
            "stored_file_path": target_config["csv_path"],
            "network_location_name": target_config["network_location_name"],
            "status": "running",
            "message": "Actualizacion automatica programada en progreso.",
            "started_at": started_at_iso,
            "finished_at": None
        }
    )

    try:
        result = execute_network_location_aut_run(
            run_id=log_entry["id"],
            triggered_by="codex-automation",
            source_platform="windows",
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
            "generated_csv_path": target_config["csv_path"],
            "archived_csv_path": None,
            "network_location_name": target_config["network_location_name"],
            "ip_count": 0,
            "applied_change_message": None,
            "notification_email": NETWORK_LOCATION_NOTIFY_EMAIL,
            "notification_status": "skipped",
            "source_platform": "windows",
            "source_platform_label": "Windows",
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
            "original_file_name": result.get("original_file_name", target_config["network_location_name"] + ".csv"),
            "stored_file_name": result.get("stored_file_name", target_config["network_location_name"] + ".csv"),
            "stored_file_path": result.get("stored_file_path", target_config["csv_path"]),
            "network_location_name": result.get("network_location_name", target_config["network_location_name"]),
            "screenshots": result.get("screenshots", []),
            "logs_path": result.get("logsPath"),
            "applied_change_message": result.get("applied_change_message"),
            "notification_email": result.get("notification_email"),
            "notification_status": result.get("notification_status"),
            "duration_seconds": round(time.perf_counter() - started_at, 2),
            "source_platform": result.get("source_platform", "windows"),
            "source_platform_label": result.get("source_platform_label", "Windows"),
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

    print(json.dumps({"run_id": log_entry["id"], **result}, ensure_ascii=False))
    return 0 if result.get("status") == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
