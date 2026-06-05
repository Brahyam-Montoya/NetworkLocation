import io
import os
import shutil
import unittest
from pathlib import Path

import app as app_module
import utils.ip_inventory as ip_inventory_module

SAMPLE_RESPONSE = """{"status":"success","msg":"","data":[{"obj_id":"12","obj_name":"IPs_Servidores_CO","obj_data":"[\\"10.1.10.201\\\\/32\\",\\"10.1.10.0\\\\/24\\"]","modify_type":"Created"},{"obj_id":"22","obj_name":"VPN","obj_data":"[\\"10.2.2.10-10.2.2.20\\"]","modify_type":"Created"}]}"""
SAMPLE_CSV = """IPs_Servidores_CO,10.1.10.201,10.1.10.0/24
VPN,10.2.2.10-10.2.2.20
"""
TEST_TMP_DIR = Path("test") / "_tmp_ip_inventory"


def reset_test_tmp_dir():
    shutil.rmtree(TEST_TMP_DIR, ignore_errors=True)
    TEST_TMP_DIR.mkdir(parents=True, exist_ok=True)


class IpInventoryParsingTests(unittest.TestCase):
    def setUp(self):
        reset_test_tmp_dir()

    def tearDown(self):
        shutil.rmtree(TEST_TMP_DIR, ignore_errors=True)

    def test_processes_netskope_response_format(self):
        response_file = TEST_TMP_DIR / "response.json"
        response_file.write_text(SAMPLE_RESPONSE, encoding="utf-8")

        inventory = ip_inventory_module.process_ip_inventory_file(str(response_file), "response.json")
        self.assertEqual(inventory["total_locations"], 2)
        self.assertEqual(inventory["total_entries"], 3)
        self.assertEqual(inventory["locations"][0]["name"], "IPs_Servidores_CO")
        self.assertEqual(inventory["locations"][0]["entries"][0]["type"], "exact")

        results = ip_inventory_module.search_ip_inventory(inventory, "10.1.10.201")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["network_location_name"], "IPs_Servidores_CO")
        self.assertEqual(len(results[0]["matches"]), 2)

    def test_processes_pasted_txt_response_and_ignores_ipv6_entries(self):
        pasted_response = """Network payload:
{"status":"success","msg":"","data":[{"obj_id":"12","obj_name":"10.1.10.201","obj_data":"[\\"10.1.10.201\\\\/32\\"]"},{"obj_id":"20","obj_name":"a","obj_data":"[\\"2001:db8:3333:4444:5555:6666:7777:8888\\"]"},{"obj_id":"21","obj_name":"IPs_Servidores_CO","obj_data":"[\\"10.8.8.8\\",\\"10.8.8.0\\\\/24\\"]"}]}
"""
        response_file = TEST_TMP_DIR / "response.txt"
        response_file.write_text(pasted_response, encoding="utf-8")

        inventory = ip_inventory_module.process_ip_inventory_file(str(response_file), "response.txt")

        self.assertEqual(inventory["total_locations"], 3)
        self.assertEqual(inventory["total_entries"], 3)
        ipv6_only_location = next(item for item in inventory["locations"] if item["name"] == "a")
        self.assertEqual(ipv6_only_location["entries_count"], 0)

    def test_processes_csv_fallback_format(self):
        csv_file = TEST_TMP_DIR / "inventory.csv"
        csv_file.write_text(SAMPLE_CSV, encoding="utf-8")

        inventory = ip_inventory_module.process_ip_inventory_file(str(csv_file), "inventory.csv")
        self.assertEqual(inventory["total_locations"], 2)
        self.assertEqual(inventory["locations"][1]["name"], "VPN")

        results = ip_inventory_module.search_ip_inventory(inventory, "10.2.2.15")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["network_location_name"], "VPN")
        self.assertEqual(results[0]["matches"][0]["type"], "range")

    def test_processes_json_payload_even_when_extension_is_csv(self):
        csv_named_json_file = TEST_TMP_DIR / "Data.csv"
        csv_named_json_file.write_text(SAMPLE_RESPONSE, encoding="utf-8")

        inventory = ip_inventory_module.process_ip_inventory_file(str(csv_named_json_file), "Data.csv")

        self.assertEqual(inventory["total_locations"], 2)
        self.assertEqual(inventory["total_entries"], 3)

    def test_rejects_invalid_query_ip(self):
        response_file = TEST_TMP_DIR / "response.json"
        response_file.write_text(SAMPLE_RESPONSE, encoding="utf-8")
        inventory = ip_inventory_module.process_ip_inventory_file(str(response_file), "response.json")

        with self.assertRaisesRegex(ValueError, "IPv4"):
            ip_inventory_module.search_ip_inventory(inventory, "abc")


class IpLookupRouteTests(unittest.TestCase):
    def setUp(self):
        reset_test_tmp_dir()
        self.client = app_module.app.test_client()
        self.client.testing = True
        self.original_save_upload_file = app_module.save_upload_file
        self.original_run_ip_inventory_automation = app_module.run_ip_inventory_automation
        self.original_auto_index_file = app_module.IP_INVENTORY_INDEX_FILE
        self.original_manual_index_file = app_module.MANUAL_IP_INVENTORY_INDEX_FILE
        self.original_ip_inventory_index_file = ip_inventory_module.IP_INVENTORY_INDEX_FILE
        app_module.IP_INVENTORY_INDEX_FILE = str(TEST_TMP_DIR / "ip_inventory_auto_index.json")
        app_module.MANUAL_IP_INVENTORY_INDEX_FILE = str(TEST_TMP_DIR / "ip_inventory_manual_index.json")
        ip_inventory_module.IP_INVENTORY_INDEX_FILE = app_module.IP_INVENTORY_INDEX_FILE

        def fake_save_upload_file(file_storage):
            destination = str(TEST_TMP_DIR / file_storage.filename)
            file_storage.save(destination)
            return destination

        app_module.save_upload_file = fake_save_upload_file

    def tearDown(self):
        app_module.save_upload_file = self.original_save_upload_file
        app_module.run_ip_inventory_automation = self.original_run_ip_inventory_automation
        app_module.IP_INVENTORY_INDEX_FILE = self.original_auto_index_file
        app_module.MANUAL_IP_INVENTORY_INDEX_FILE = self.original_manual_index_file
        ip_inventory_module.IP_INVENTORY_INDEX_FILE = self.original_ip_inventory_index_file
        shutil.rmtree(TEST_TMP_DIR, ignore_errors=True)

    def test_upload_and_manual_search_flow(self):
        with self.client.session_transaction() as session:
            session["username"] = "bsmontoy@bancolombia.com.co"
            session["role"] = "read_only"

        upload_response = self.client.post(
            "/ip-consulta/upload",
            data={"file": (io.BytesIO(SAMPLE_RESPONSE.encode("utf-8")), "response.json")},
            content_type="multipart/form-data",
            follow_redirects=True
        )

        upload_html = upload_response.get_data(as_text=True)
        self.assertEqual(upload_response.status_code, 200)
        self.assertIn("Indice actualizado con 2 Network Locations y 3 entradas.", upload_html)
        self.assertIn("Consultar documento", upload_html)

        search_response = self.client.get("/ip-consulta-manual?ip=10.1.10.201")
        search_html = search_response.get_data(as_text=True)
        self.assertEqual(search_response.status_code, 200)
        self.assertIn("IPs_Servidores_CO", search_html)
        self.assertIn("10.1.10.201/32", search_html)

    def test_paste_and_manual_search_flow(self):
        with self.client.session_transaction() as session:
            session["username"] = "bsmontoy@bancolombia.com.co"
            session["role"] = "read_only"

        paste_response = self.client.post(
            "/ip-consulta/paste",
            data={
                "pasted_file_name": "copied-response.json",
                "pasted_response": SAMPLE_RESPONSE
            },
            follow_redirects=True
        )

        paste_html = paste_response.get_data(as_text=True)
        self.assertEqual(paste_response.status_code, 200)
        self.assertIn("Indice actualizado con 2 Network Locations y 3 entradas desde texto pegado.", paste_html)
        self.assertIn("Consultar documento", paste_html)

        search_response = self.client.get("/ip-consulta-manual?ip=10.1.10.201")
        search_html = search_response.get_data(as_text=True)
        self.assertEqual(search_response.status_code, 200)
        self.assertIn("IPs_Servidores_CO", search_html)

    def test_search_without_inventory_shows_automatic_refresh_message(self):
        with self.client.session_transaction() as session:
            session["username"] = "bsmontoy@bancolombia.com.co"
            session["role"] = "read_only"

        search_response = self.client.get("/ip-consulta?ip=10.1.10.201")
        search_html = search_response.get_data(as_text=True)

        self.assertEqual(search_response.status_code, 200)
        self.assertIn("Primero ejecuta Consulta automatica para construir o refrescar el indice antes de buscar una IP.", search_html)

    def test_manual_search_without_inventory_shows_manual_message(self):
        with self.client.session_transaction() as session:
            session["username"] = "bsmontoy@bancolombia.com.co"
            session["role"] = "read_only"

        search_response = self.client.get("/ip-consulta-manual?ip=10.1.10.201")
        search_html = search_response.get_data(as_text=True)

        self.assertEqual(search_response.status_code, 200)
        self.assertIn("Primero pega y carga el response manual para construir el indice antes de buscar una IP.", search_html)

    def test_auto_refresh_and_search_flow(self):
        automated_response_file = TEST_TMP_DIR / "auto-response.json"
        automated_response_file.write_text(SAMPLE_RESPONSE, encoding="utf-8")

        def fake_run_ip_inventory_automation(run_id):
            return {
                "status": "success",
                "message": "ok",
                "logsPath": str(TEST_TMP_DIR / f"{run_id}-log.json"),
                "screenshots": [str(TEST_TMP_DIR / f"{run_id}-01.png")],
                "responsePath": str(automated_response_file)
            }

        app_module.run_ip_inventory_automation = fake_run_ip_inventory_automation

        with self.client.session_transaction() as session:
            session["username"] = "bsmontoy@bancolombia.com.co"
            session["role"] = "read_only"

        refresh_response = self.client.post("/ip-consulta/auto-refresh", follow_redirects=True)
        refresh_html = refresh_response.get_data(as_text=True)
        self.assertEqual(refresh_response.status_code, 200)
        self.assertIn("Consulta automatica completada con 2 Network Locations y 3 entradas.", refresh_html)
        self.assertIn("Ver response capturado", refresh_html)

        search_response = self.client.get("/ip-consulta?ip=10.1.10.201")
        self.assertEqual(search_response.status_code, 200)
        self.assertIn("IPs_Servidores_CO", search_response.get_data(as_text=True))

    def test_auto_refresh_returns_json_for_ajax_requests(self):
        automated_response_file = TEST_TMP_DIR / "auto-response.json"
        automated_response_file.write_text(SAMPLE_RESPONSE, encoding="utf-8")

        def fake_run_ip_inventory_automation(run_id):
            return {
                "status": "success",
                "message": "ok",
                "logsPath": str(TEST_TMP_DIR / f"{run_id}-log.json"),
                "screenshots": [str(TEST_TMP_DIR / f"{run_id}-01.png")],
                "responsePath": str(automated_response_file)
            }

        app_module.run_ip_inventory_automation = fake_run_ip_inventory_automation

        with self.client.session_transaction() as session:
            session["username"] = "bsmontoy@bancolombia.com.co"
            session["role"] = "read_only"

        refresh_response = self.client.post(
            "/ip-consulta/auto-refresh",
            headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"}
        )

        self.assertEqual(refresh_response.status_code, 200)
        payload = refresh_response.get_json()
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["redirect_url"], "/ip-consulta")
        self.assertIn("Consulta automatica completada", payload["message"])

    def test_navigation_labels_and_manual_menu_entry(self):
        with self.client.session_transaction() as session:
            session["username"] = "bsmontoy@bancolombia.com.co"
            session["role"] = "read_only"

        dashboard_response = self.client.get("/dashboard")
        dashboard_html = dashboard_response.get_data(as_text=True)
        self.assertEqual(dashboard_response.status_code, 200)
        self.assertIn("Crear Network Location", dashboard_html)
        self.assertIn("Consulta IP", dashboard_html)
        self.assertIn("Consultar documento", dashboard_html)

        manual_response = self.client.get("/ip-consulta-manual")
        manual_html = manual_response.get_data(as_text=True)
        self.assertEqual(manual_response.status_code, 200)
        self.assertIn("Consultar documento", manual_html)
        self.assertIn("Copy response", manual_html)


if __name__ == "__main__":
    unittest.main()
