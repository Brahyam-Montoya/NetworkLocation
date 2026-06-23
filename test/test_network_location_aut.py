import os
import shutil
import unittest
import zipfile
from pathlib import Path

import app as app_module
import utils.audit as audit_module
import utils.network_location_aut as aut_module

TEST_TMP_DIR = Path("test") / "_tmp_network_location_aut"
SAMPLE_API_RESPONSE = """ip
10.8.132.208
10.8.37.8
10.8.48.30
"""


def reset_test_tmp_dir():
    shutil.rmtree(TEST_TMP_DIR, ignore_errors=True)
    TEST_TMP_DIR.mkdir(parents=True, exist_ok=True)


class NetworkLocationAutParsingTests(unittest.TestCase):
    def setUp(self):
        reset_test_tmp_dir()

    def tearDown(self):
        shutil.rmtree(TEST_TMP_DIR, ignore_errors=True)

    def test_normalizes_plain_text_response_with_lowercase_header(self):
        ips = aut_module.normalize_power_automate_ip_response(SAMPLE_API_RESPONSE)
        self.assertEqual(ips, ["10.8.132.208", "10.8.37.8", "10.8.48.30"])

    def test_normalizes_plain_text_response_with_uppercase_header_and_duplicates(self):
        ips = aut_module.normalize_power_automate_ip_response("IP\n10.8.132.208\n10.8.132.208\n10.8.37.8\n")
        self.assertEqual(ips, ["10.8.132.208", "10.8.37.8"])

    def test_ignores_blank_lines(self):
        ips = aut_module.normalize_power_automate_ip_response("ip\n\n10.8.132.208\n  \n10.8.37.8\n")
        self.assertEqual(ips, ["10.8.132.208", "10.8.37.8"])

    def test_ignores_non_ip_lines_when_valid_ips_exist(self):
        parsed = aut_module.parse_power_automate_ip_response("ip\n10.8.132.208\nSBMDEBGD05V\n10.8.37.8\n")
        self.assertEqual(parsed["ip_values"], ["10.8.132.208", "10.8.37.8"])
        self.assertEqual(parsed["ignored_values"], ["SBMDEBGD05V"])

    def test_rejects_response_without_valid_ips(self):
        with self.assertRaisesRegex(ValueError, "IPv4 validas"):
            aut_module.normalize_power_automate_ip_response("ip\nSERVIDOR01\n")

    def test_generates_compatible_csv_file(self):
        csv_path = TEST_TMP_DIR / "CO_AzureArc_Server.csv"
        payload = aut_module.generate_network_location_aut_csv(
            response_text=SAMPLE_API_RESPONSE,
            network_location_name="CO_AzureArc_Server",
            csv_path=str(csv_path)
        )

        self.assertEqual(payload["network_location_name"], "CO_AzureArc_Server")
        self.assertEqual(payload["ip_count"], 3)
        self.assertTrue(Path(payload["csv_path"]).exists())
        self.assertTrue(Path(payload["archive_path"]).exists())
        self.assertTrue(Path(payload["excel_path"]).exists())
        self.assertEqual(Path(payload["csv_path"]).read_text(encoding="utf-8"), "CO_AzureArc_Server,10.8.132.208,10.8.37.8,10.8.48.30\n")
        with zipfile.ZipFile(payload["excel_path"], "r") as workbook:
            self.assertIn("xl/worksheets/sheet1.xml", workbook.namelist())

    def test_fetch_reports_http_error(self):
        class FakeResponse:
            ok = False
            status_code = 500
            text = "boom"
            headers = {"Content-Type": "text/plain"}

        def fake_get(_url, headers=None, timeout=None):
            return FakeResponse()

        with self.assertRaisesRegex(ValueError, "estado 500"):
            aut_module.fetch_power_automate_location_response(
                url="https://example.test",
                request_get=fake_get
            )

    def test_fetch_uses_linux_header_configuration(self):
        observed = {}

        class FakeResponse:
            ok = True
            status_code = 200
            text = SAMPLE_API_RESPONSE
            headers = {"Content-Type": "text/plain"}

        def fake_get(_url, headers=None, timeout=None):
            observed["headers"] = headers
            return FakeResponse()

        payload = aut_module.fetch_power_automate_location_response(
            url="https://example.test",
            source_platform="linux",
            request_get=fake_get
        )

        self.assertEqual(payload["source_platform"], "linux")
        self.assertEqual(observed["headers"]["x-sistema-operativo"], "linux")


class NetworkLocationAutRouteTests(unittest.TestCase):
    def setUp(self):
        reset_test_tmp_dir()
        self.client = app_module.app.test_client()
        self.client.testing = True
        self.original_execute = app_module.execute_network_location_aut_run
        self.original_windows_csv_path = app_module.POWER_AUT_LOCATION_WINDOWS_CSV_PATH
        self.original_linux_csv_path = app_module.POWER_AUT_LOCATION_LINUX_CSV_PATH
        self.original_windows_name = app_module.POWER_AUT_LOCATION_WINDOWS_NAME
        self.original_linux_name = app_module.POWER_AUT_LOCATION_LINUX_NAME
        self.original_url = app_module.POWER_AUT_LOCATION_URL
        self.original_logs_file = audit_module.EXECUTION_LOGS_FILE
        app_module.POWER_AUT_LOCATION_WINDOWS_CSV_PATH = str((TEST_TMP_DIR / "CO_AzureArc_Server_Windows.csv").resolve())
        app_module.POWER_AUT_LOCATION_LINUX_CSV_PATH = str((TEST_TMP_DIR / "CO_AzureArc_Server_Linux.csv").resolve())
        app_module.POWER_AUT_LOCATION_WINDOWS_NAME = "CO_AzureArc_Server_Windows"
        app_module.POWER_AUT_LOCATION_LINUX_NAME = "CO_AzureArc_Server_Linux"
        app_module.POWER_AUT_LOCATION_URL = "https://example.test/power-automate"
        audit_module.EXECUTION_LOGS_FILE = str((TEST_TMP_DIR / "execution_logs.json").resolve())

    def tearDown(self):
        app_module.execute_network_location_aut_run = self.original_execute
        app_module.POWER_AUT_LOCATION_WINDOWS_CSV_PATH = self.original_windows_csv_path
        app_module.POWER_AUT_LOCATION_LINUX_CSV_PATH = self.original_linux_csv_path
        app_module.POWER_AUT_LOCATION_WINDOWS_NAME = self.original_windows_name
        app_module.POWER_AUT_LOCATION_LINUX_NAME = self.original_linux_name
        app_module.POWER_AUT_LOCATION_URL = self.original_url
        audit_module.EXECUTION_LOGS_FILE = self.original_logs_file
        shutil.rmtree(TEST_TMP_DIR, ignore_errors=True)

    def test_network_location_aut_page_and_menu_entry(self):
        with self.client.session_transaction() as session:
            session["username"] = "admin"
            session["role"] = "admin"

        response = self.client.get("/network-location-aut")
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("Network Location Aut", html)
        self.assertIn("Windows", html)
        self.assertIn("Linux", html)
        self.assertIn("CO_AzureArc_Server_Windows", html)
        self.assertIn("CO_AzureArc_Server_Linux", html)

    def test_network_location_aut_refresh_success(self):
        observed = {}
        generated_csv_path = str((TEST_TMP_DIR / "CO_AzureArc_Server_Linux.csv").resolve())
        archived_csv_path = str((TEST_TMP_DIR / "CO_AzureArc_Server_Linux_linux_Aut_20260604_1600.csv").resolve())
        raw_response_path = str((TEST_TMP_DIR / "response.txt").resolve())
        generated_excel_path = str((TEST_TMP_DIR / "CO_AzureArc_Server_Linux_linux_Aut_20260604_1600.xlsx").resolve())
        Path(generated_csv_path).write_text("CO_AzureArc_Server_Linux,10.8.132.208\n", encoding="utf-8")
        Path(archived_csv_path).write_text("CO_AzureArc_Server_Linux,10.8.132.208\n", encoding="utf-8")
        Path(raw_response_path).write_text(SAMPLE_API_RESPONSE, encoding="utf-8")
        Path(generated_excel_path).write_bytes(b"fake-xlsx")

        def fake_execute(**kwargs):
            observed.update(kwargs)
            return {
                "status": "success",
                "message": "ok Se ignoraron 2 valores que no son IP validas: SBMDEBGD05V, SBMDEBQVYN01V.",
                "screenshots": [str((TEST_TMP_DIR / "shot.png").resolve())],
                "logsPath": str((TEST_TMP_DIR / "automation-log.json").resolve()),
                "raw_response_path": raw_response_path,
                "generated_csv_path": generated_csv_path,
                "archived_csv_path": archived_csv_path,
                "generated_excel_path": generated_excel_path,
                "network_location_name": "CO_AzureArc_Server_Linux",
                "source_platform": "linux",
                "source_platform_label": "Linux",
                "ip_count": 1,
                "ignored_count": 2,
                "ignored_values": ["SBMDEBGD05V", "SBMDEBQVYN01V"],
                "applied_change_message": "apply message",
                "notification_email": "ops@example.com",
                "notification_status": "ok",
                "source_url": "https://example.test/power-automate",
                "source_status_code": 200,
                "source_headers": {"Content-Type": "text/plain"},
                "original_file_name": "CO_AzureArc_Server_Linux.csv",
                "stored_file_name": "CO_AzureArc_Server_Linux.csv",
                "stored_file_path": generated_csv_path
            }

        app_module.execute_network_location_aut_run = fake_execute

        with self.client.session_transaction() as session:
            session["username"] = "admin"
            session["role"] = "admin"

        response = self.client.post(
            "/network-location-aut/refresh",
            data={"platform": "linux"},
            follow_redirects=True
        )
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(observed["source_platform"], "linux")
        self.assertIn("Network Location Aut Linux actualizada con 1 IPs y aplicada en Netskope.", html)
        self.assertIn("Historial Network Location Aut", html)
        self.assertIn("SBMDEBGD05V, SBMDEBQVYN01V", html)
        self.assertIn("Ver Excel", html)
        self.assertIn("Linux", html)

    def test_network_location_aut_refresh_failure_keeps_page_usable(self):
        def fake_execute(**kwargs):
            raise ValueError("El API remoto no respondio.")

        app_module.execute_network_location_aut_run = fake_execute

        with self.client.session_transaction() as session:
            session["username"] = "admin"
            session["role"] = "admin"

        response = self.client.post(
            "/network-location-aut/refresh",
            headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"}
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["redirect_url"], "/network-location-aut")
        self.assertIn("El API remoto no respondio.", payload["message"])


if __name__ == "__main__":
    unittest.main()
