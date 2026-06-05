import os
import shutil
import zipfile
from datetime import UTC, datetime
from ipaddress import IPv4Address, ip_address
from pathlib import Path
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

import requests

from config import (
    POWER_AUT_LOCATION_CSV_PATH,
    POWER_AUT_LOCATION_HEADER_NAME,
    POWER_AUT_LOCATION_HEADER_VALUE,
    POWER_AUT_LOCATION_NAME,
    POWER_AUT_LOCATION_TIMEOUT_SECONDS,
    POWER_AUT_LOCATION_URL,
    UPLOAD_FOLDER
)
from utils.csv_processor import process_uploaded_csv
from utils.notifications import send_network_location_change_email
from utils.storage import ensure_app_dirs, utc_now_iso
from utils.automation import run_network_location_automation

BOGOTA_TZ = ZoneInfo("America/Bogota")


def build_network_location_change_message(network_location_name):
    change_timestamp = datetime.now(BOGOTA_TZ).strftime("%Y-%m-%d %H:%M:%S")
    return f"Se subio la Network Location {network_location_name} por medio de la automatizacion {change_timestamp}"


def build_ignored_values_message(ignored_values):
    if not ignored_values:
        return ""

    joined_values = ", ".join(ignored_values)
    label = "valor" if len(ignored_values) == 1 else "valores"
    return f" Se ignoraron {len(ignored_values)} {label} que no son IP validas: {joined_values}."


def _clean_response_lines(response_text):
    return [line.strip() for line in str(response_text or "").replace("\ufeff", "").splitlines()]


def parse_power_automate_ip_response(response_text):
    lines = [line for line in _clean_response_lines(response_text) if line]
    if not lines:
        raise ValueError("El API no devolvio contenido util para construir el CSV.")

    if lines[0].lower() == "ip":
        lines = lines[1:]

    unique_ips = []
    seen_ips = set()
    ignored_values = []

    for line in lines:
        try:
            parsed_ip = ip_address(line)
        except ValueError:
            ignored_values.append(line)
            continue

        if not isinstance(parsed_ip, IPv4Address):
            ignored_values.append(line)
            continue

        normalized_ip = str(parsed_ip)
        if normalized_ip in seen_ips:
            continue

        seen_ips.add(normalized_ip)
        unique_ips.append(normalized_ip)

    if not unique_ips:
        raise ValueError("El API no devolvio direcciones IPv4 validas para construir el CSV.")

    return {
        "ip_values": unique_ips,
        "ignored_values": ignored_values
    }


def normalize_power_automate_ip_response(response_text):
    return parse_power_automate_ip_response(response_text)["ip_values"]


def build_network_location_csv_content(network_location_name, ip_values):
    return ",".join([network_location_name, *ip_values]) + "\n"


def _xlsx_cell(cell_reference, shared_string_index):
    return f'<c r="{cell_reference}" t="s"><v>{shared_string_index}</v></c>'


def _create_simple_xlsx(file_path, rows):
    shared_strings = []
    shared_string_index = {}

    def get_shared_string_index(value):
        text = str(value)
        if text not in shared_string_index:
            shared_string_index[text] = len(shared_strings)
            shared_strings.append(text)
        return shared_string_index[text]

    sheet_rows = []
    for row_number, row in enumerate(rows, start=1):
        cells = []
        for column_number, value in enumerate(row, start=1):
            column_letter = chr(64 + column_number)
            cells.append(_xlsx_cell(f"{column_letter}{row_number}", get_shared_string_index(value)))
        sheet_rows.append(f'<row r="{row_number}">{"".join(cells)}</row>')

    shared_strings_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="{len(shared_strings)}" uniqueCount="{len(shared_strings)}">'
        + "".join(f"<si><t>{escape(value)}</t></si>" for value in shared_strings)
        + "</sst>"
    )
    sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(sheet_rows)}</sheetData>'
        "</worksheet>"
    )

    with zipfile.ZipFile(file_path, "w", compression=zipfile.ZIP_DEFLATED) as workbook:
        workbook.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>'
            '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
            '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
            "</Types>"
        )
        workbook.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
            '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>'
            "</Relationships>"
        )
        workbook.writestr(
            "docProps/core.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
            'xmlns:dcmitype="http://purl.org/dc/dcmitype/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            '<dc:creator>Codex</dc:creator><cp:lastModifiedBy>Codex</cp:lastModifiedBy>'
            f'<dcterms:created xsi:type="dcterms:W3CDTF">{datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")}</dcterms:created>'
            f'<dcterms:modified xsi:type="dcterms:W3CDTF">{datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")}</dcterms:modified>'
            "</cp:coreProperties>"
        )
        workbook.writestr(
            "docProps/app.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" '
            'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
            '<Application>Microsoft Excel</Application></Properties>'
        )
        workbook.writestr(
            "xl/workbook.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="IPs" sheetId="1" r:id="rId1"/></sheets></workbook>'
        )
        workbook.writestr(
            "xl/_rels/workbook.xml.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
            '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" Target="sharedStrings.xml"/>'
            "</Relationships>"
        )
        workbook.writestr(
            "xl/styles.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>'
            '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>'
            '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
            '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
            '<cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/></cellXfs>'
            '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
            "</styleSheet>"
        )
        workbook.writestr("xl/sharedStrings.xml", shared_strings_xml)
        workbook.writestr("xl/worksheets/sheet1.xml", sheet_xml)


def generate_network_location_excel_artifact(network_location_name, ip_values, output_dir):
    timestamp_compact = datetime.now(UTC).strftime("%Y%m%d_%H%M")
    excel_path = os.path.join(output_dir, f"{network_location_name}_Aut_{timestamp_compact}.xlsx")
    rows = [["Network Location", "IP"]] + [[network_location_name, ip_value] for ip_value in ip_values]
    _create_simple_xlsx(excel_path, rows)
    return str(Path(excel_path).resolve())


def fetch_power_automate_location_response(
    *,
    url=POWER_AUT_LOCATION_URL,
    header_name=POWER_AUT_LOCATION_HEADER_NAME,
    header_value=POWER_AUT_LOCATION_HEADER_VALUE,
    timeout_seconds=POWER_AUT_LOCATION_TIMEOUT_SECONDS,
    request_get=requests.get
):
    if not url:
        raise ValueError("Debes configurar POWER_AUT_LOCATION_URL para usar Network Location Aut.")

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        header_name: header_value
    }

    try:
        response = request_get(url, headers=headers, timeout=timeout_seconds)
    except requests.RequestException as error:
        raise ValueError(f"No fue posible consultar el API remoto: {error}") from error

    if not response.ok:
        body_preview = (response.text or "").strip().replace("\n", " ")[:200]
        raise ValueError(
            f"El API remoto respondio con estado {response.status_code}. "
            f"{body_preview or 'No devolvio cuerpo de respuesta.'}"
        )

    return {
        "url": url,
        "status_code": response.status_code,
        "headers": dict(response.headers),
        "text": response.text
    }


def generate_network_location_aut_csv(
    *,
    response_text,
    network_location_name=POWER_AUT_LOCATION_NAME,
    csv_path=POWER_AUT_LOCATION_CSV_PATH
):
    ensure_app_dirs()
    parsed_response = parse_power_automate_ip_response(response_text)
    ip_values = parsed_response["ip_values"]
    csv_content = build_network_location_csv_content(network_location_name, ip_values)
    timestamp_compact = datetime.now(UTC).strftime("%Y%m%d_%H%M")
    archive_path = os.path.join(Path(csv_path).parent, f"{network_location_name}_Aut_{timestamp_compact}.csv")
    excel_path = generate_network_location_excel_artifact(network_location_name, ip_values, str(Path(csv_path).parent))

    temporary_path = f"{csv_path}.tmp"
    Path(temporary_path).write_text(csv_content, encoding="utf-8")
    shutil.copyfile(temporary_path, archive_path)
    os.replace(temporary_path, csv_path)

    payload = process_uploaded_csv(csv_path, Path(csv_path).name)
    return {
        "network_location_name": network_location_name,
        "ip_count": len(ip_values),
        "ip_values": ip_values,
        "ignored_values": parsed_response["ignored_values"],
        "ignored_count": len(parsed_response["ignored_values"]),
        "csv_content": csv_content,
        "csv_path": str(Path(csv_path).resolve()),
        "archive_path": str(Path(archive_path).resolve()),
        "excel_path": excel_path,
        "payload": payload
    }


def _write_raw_response_artifact(response_text):
    ensure_app_dirs()
    timestamp = utc_now_iso().replace(":", "-")
    raw_response_path = os.path.join(UPLOAD_FOLDER, f"network-location-aut-raw-{timestamp}.txt")
    Path(raw_response_path).write_text(str(response_text or ""), encoding="utf-8")
    return str(Path(raw_response_path).resolve())


def execute_network_location_aut_run(
    *,
    run_id,
    triggered_by,
    approval_recipient=None,
    notification_recipient=None
):
    response_payload = fetch_power_automate_location_response()
    raw_response_path = _write_raw_response_artifact(response_payload.get("text", ""))
    csv_payload = generate_network_location_aut_csv(response_text=response_payload.get("text", ""))
    apply_change_message = build_network_location_change_message(csv_payload["network_location_name"])
    ignored_values_message = build_ignored_values_message(csv_payload["ignored_values"])

    automation_result = run_network_location_automation(
        run_id=run_id,
        stored_file_path=csv_payload["csv_path"],
        network_location_name=csv_payload["network_location_name"],
        apply_change_message=apply_change_message,
        approval_recipient=approval_recipient
    )

    notification_result = {"status": "skipped", "recipient": notification_recipient}
    if automation_result.get("status") == "success" and notification_recipient:
        email_body = (
            f"{automation_result.get('appliedChangeMessage', apply_change_message)}\n\n"
            f"IPs cargadas: {csv_payload['ip_count']}.\n"
            f"Archivo CSV generado: {csv_payload['csv_path']}\n"
            f"Archivo Excel adjunto: {csv_payload['excel_path']}\n"
        )
        if csv_payload["ignored_values"]:
            email_body += (
                f"\nSe detectaron y eliminaron {csv_payload['ignored_count']} valores que no corresponden a IPs: "
                f"{', '.join(csv_payload['ignored_values'])}\n"
            )

        notification_result = send_network_location_change_email(
            email_body,
            notification_recipient,
            attachment_paths=[csv_payload["excel_path"]]
        )

    if notification_result.get("status") not in {"ok", "skipped"}:
        automation_result["message"] = (
            f"{automation_result.get('message', 'Proceso finalizado.')} "
            f"No fue posible enviar el correo de notificacion: {notification_result.get('message', 'Sin detalle.')}."
        )

    if ignored_values_message:
        base_message = automation_result.get("message", "Proceso finalizado.")
        if ignored_values_message.strip() not in base_message:
            automation_result["message"] = f"{base_message}{ignored_values_message}"

    return {
        **automation_result,
        "triggered_by": triggered_by,
        "source_url": response_payload.get("url"),
        "source_status_code": response_payload.get("status_code"),
        "source_headers": response_payload.get("headers"),
        "raw_response_path": raw_response_path,
        "generated_csv_path": csv_payload["csv_path"],
        "archived_csv_path": csv_payload["archive_path"],
        "generated_excel_path": csv_payload["excel_path"],
        "network_location_name": csv_payload["network_location_name"],
        "ip_count": csv_payload["ip_count"],
        "ignored_count": csv_payload["ignored_count"],
        "ignored_values": csv_payload["ignored_values"],
        "original_file_name": Path(csv_payload["csv_path"]).name,
        "stored_file_name": Path(csv_payload["csv_path"]).name,
        "stored_file_path": csv_payload["csv_path"],
        "started_at": csv_payload["payload"]["started_at"],
        "finished_at": utc_now_iso(),
        "applied_change_message": automation_result.get("appliedChangeMessage", apply_change_message),
        "notification_email": notification_result.get("recipient"),
        "notification_status": notification_result.get("status")
    }
