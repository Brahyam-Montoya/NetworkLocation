from pathlib import Path

from utils.storage import utc_now_iso


def extract_network_location_name(csv_content):
    first_line = csv_content.replace("\ufeff", "").splitlines()[0].strip() if csv_content.strip() else ""

    if not first_line:
        raise ValueError("El CSV esta vacio o no tiene contenido legible.")

    first_value = first_line.split(",")[0].strip()
    if not first_value:
        raise ValueError("No fue posible detectar el nombre de la Network Location en la primera columna.")

    return first_value


def process_uploaded_csv(file_path, original_file_name):
    content = Path(file_path).read_text(encoding="utf-8")
    return {
        "original_file_name": original_file_name,
        "stored_file_name": Path(file_path).name,
        "stored_file_path": str(Path(file_path).resolve()),
        "network_location_name": extract_network_location_name(content),
        "started_at": utc_now_iso(),
        "finished_at": utc_now_iso()
    }
