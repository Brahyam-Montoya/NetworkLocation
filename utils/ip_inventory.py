import csv
import json
import os
from ipaddress import IPv4Address, IPv6Address, ip_address, ip_network
from pathlib import Path

from config import IP_INVENTORY_INDEX_FILE
from utils.storage import utc_now_iso

NETWORK_LOCATION_NAME_KEYS = (
    "network_location",
    "network_location_name",
    "set_location",
    "setLocation",
    "location_name",
    "location",
    "obj_name",
    "name",
    "title"
)
ENTRY_COLLECTION_KEYS = ("obj_data", "entries", "values", "addresses", "items", "data")


def _read_file_text(file_path):
    return Path(file_path).read_text(encoding="utf-8").replace("\ufeff", "")


def _clean_text(value):
    return str(value or "").strip().replace("\\/", "/")


def _try_parse_json_payload(content):
    normalized_content = content.strip()
    if not normalized_content:
        raise ValueError("El archivo cargado esta vacio.")

    try:
        return json.loads(normalized_content)
    except json.JSONDecodeError:
        pass

    start_index = normalized_content.find("{")
    while start_index != -1:
        try:
            decoder = json.JSONDecoder()
            payload, _end_index = decoder.raw_decode(normalized_content[start_index:])
            return payload
        except json.JSONDecodeError:
            start_index = normalized_content.find("{", start_index + 1)

    raise ValueError("El archivo no contiene un JSON valido para la respuesta copiada desde DevTools.")


def _extract_network_location_name(item):
    for key in NETWORK_LOCATION_NAME_KEYS:
        value = _clean_text(item.get(key))
        if value:
            return value

    return ""


def _coerce_entries(value):
    if value is None:
        return []

    if isinstance(value, list):
        return [_clean_text(item) for item in value if _clean_text(item)]

    if isinstance(value, dict):
        for key in ENTRY_COLLECTION_KEYS:
            if key in value:
                return _coerce_entries(value.get(key))

        return []

    text = _clean_text(value)
    if not text:
        return []

    if text.startswith("[") or text.startswith("{"):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return [text]

        return _coerce_entries(parsed)

    return [text]


def _dedupe_entries(entries):
    seen = set()
    unique_entries = []

    for entry in entries:
        if entry in seen:
            continue

        seen.add(entry)
        unique_entries.append(entry)

    return unique_entries


def _normalize_entry(raw_entry):
    value = _clean_text(raw_entry)
    if not value:
        return None

    if "-" in value and "/" not in value:
        start_text, end_text = [part.strip() for part in value.split("-", 1)]
        start_ip = ip_address(start_text)
        end_ip = ip_address(end_text)
        if isinstance(start_ip, IPv6Address) or isinstance(end_ip, IPv6Address):
            return None
        if not isinstance(start_ip, IPv4Address) or not isinstance(end_ip, IPv4Address):
            raise ValueError(f"La entrada {value} no es una direccion IPv4 valida.")
        if int(start_ip) > int(end_ip):
            raise ValueError(f"El rango {value} no es valido.")

        return {
            "raw": value,
            "type": "range",
            "start": int(start_ip),
            "end": int(end_ip)
        }

    if "/" in value:
        network = ip_network(value, strict=False)
        if network.version != 4:
            return None

        entry_type = "exact" if network.prefixlen == 32 else "cidr"
        return {
            "raw": value,
            "type": entry_type,
            "start": int(network.network_address),
            "end": int(network.broadcast_address)
        }

    address = ip_address(value)
    if isinstance(address, IPv6Address):
        return None
    if not isinstance(address, IPv4Address):
        raise ValueError(f"La entrada {value} no es una direccion IPv4 valida.")

    numeric_value = int(address)
    return {
        "raw": value,
        "type": "exact",
        "start": numeric_value,
        "end": numeric_value
    }


def _normalize_location_entries(location_name, raw_entries):
    normalized_entries = []

    for raw_entry in _dedupe_entries(raw_entries):
        try:
            normalized_entry = _normalize_entry(raw_entry)
        except ValueError as error:
            raise ValueError(f"La Network Location {location_name} tiene una entrada invalida: {error}") from error

        if normalized_entry:
            normalized_entries.append(normalized_entry)

    return normalized_entries


def _build_locations_from_netskope_response(payload):
    if not isinstance(payload, dict):
        raise ValueError("El archivo JSON debe contener un objeto raiz.")

    data = payload.get("data")
    if not isinstance(data, list):
        raise ValueError("La respuesta de Netskope no contiene un arreglo valido en data.")

    locations = []
    for item in data:
        if not isinstance(item, dict):
            continue

        location_name = _extract_network_location_name(item)
        if not location_name:
            continue

        raw_entries = []
        for key in ENTRY_COLLECTION_KEYS:
            if key in item:
                raw_entries = _coerce_entries(item.get(key))
                if raw_entries:
                    break

        locations.append(
            {
                "name": location_name,
                "raw_entries": raw_entries
            }
        )

    if not locations:
        raise ValueError("No se encontraron Network Locations dentro de la respuesta cargada.")

    return locations


def _build_locations_from_csv(content):
    locations = []

    reader = csv.reader(content.splitlines())
    for row in reader:
        cleaned_row = [_clean_text(value) for value in row]
        if not any(cleaned_row):
            continue

        location_name = cleaned_row[0]
        if not location_name:
            raise ValueError("No fue posible detectar el nombre de la Network Location en la primera columna.")

        locations.append(
            {
                "name": location_name,
                "raw_entries": [value for value in cleaned_row[1:] if value]
            }
        )

    if not locations:
        raise ValueError("El archivo CSV esta vacio o no contiene filas validas.")

    return locations


def _parse_locations_from_text(content, original_file_name):
    lowered_name = (original_file_name or "").lower()

    try:
        payload = _try_parse_json_payload(content)
    except ValueError:
        if lowered_name.endswith(".json") or lowered_name.endswith(".txt"):
            raise ValueError("El archivo no contiene un JSON valido para la respuesta copiada desde DevTools.")
    else:
        return _build_locations_from_netskope_response(payload)

    return _build_locations_from_csv(content)


def process_ip_inventory_file(file_path, original_file_name):
    content = _read_file_text(file_path)
    locations = _parse_locations_from_text(content, original_file_name)

    normalized_locations = []
    total_entries = 0

    for location in locations:
        entries = _normalize_location_entries(location["name"], location.get("raw_entries", []))
        total_entries += len(entries)
        normalized_locations.append(
            {
                "name": location["name"],
                "entries": entries,
                "entries_count": len(entries)
            }
        )

    if not normalized_locations:
        raise ValueError("No fue posible construir un indice de Network Locations con el archivo cargado.")

    return {
        "loaded_at": utc_now_iso(),
        "source_file_name": original_file_name,
        "source_file_path": str(Path(file_path).resolve()),
        "total_locations": len(normalized_locations),
        "total_entries": total_entries,
        "locations": normalized_locations
    }


def save_ip_inventory_index(index_payload):
    os.makedirs(os.path.dirname(IP_INVENTORY_INDEX_FILE), exist_ok=True)
    with open(IP_INVENTORY_INDEX_FILE, "w", encoding="utf-8") as file:
        json.dump(index_payload, file, indent=2, ensure_ascii=False)


def load_ip_inventory_index():
    if not os.path.exists(IP_INVENTORY_INDEX_FILE):
        return None

    try:
        with open(IP_INVENTORY_INDEX_FILE, "r", encoding="utf-8") as file:
            payload = json.load(file)
    except Exception:
        return None

    return payload if isinstance(payload, dict) else None


def clear_ip_inventory_index():
    try:
        os.remove(IP_INVENTORY_INDEX_FILE)
    except FileNotFoundError:
        return


def search_ip_inventory(index_payload, query_ip):
    query_text = _clean_text(query_ip)
    if not query_text:
        raise ValueError("Ingresa una direccion IP para realizar la busqueda.")

    try:
        ip_value = ip_address(query_text)
    except ValueError as error:
        raise ValueError("La IP consultada no tiene un formato IPv4 valido.") from error

    if not isinstance(ip_value, IPv4Address):
        raise ValueError("Solo se permiten direcciones IPv4 en esta consulta.")

    numeric_ip = int(ip_value)
    results = []

    for location in index_payload.get("locations", []):
        matched_entries = []
        seen_matches = set()

        for entry in location.get("entries", []):
            if entry["start"] <= numeric_ip <= entry["end"]:
                signature = (entry["raw"], entry["type"])
                if signature in seen_matches:
                    continue

                seen_matches.add(signature)
                matched_entries.append(
                    {
                        "raw": entry["raw"],
                        "type": entry["type"]
                    }
                )

        if matched_entries:
            results.append(
                {
                    "network_location_name": location.get("name", ""),
                    "entries_count": location.get("entries_count", 0),
                    "matches": matched_entries
                }
            )

    return results
