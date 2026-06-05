import unittest

import app as app_module


class LocalAdminLoginTests(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()
        self.client.testing = True

    def test_global_admin_local_login_bypasses_otp_and_enters_as_admin(self):
        response = self.client.post(
            "/login",
            data={"username": "brahyammontoya@gammalab14.online"},
            follow_redirects=False
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/dashboard"))

        with self.client.session_transaction() as session:
            self.assertEqual(session.get("username"), "brahyammontoya@gammalab14.online")
            self.assertEqual(session.get("role"), "admin")

    def test_global_admin_fixed_otp_is_accepted_if_verify_screen_is_reached(self):
        with self.client.session_transaction() as session:
            session["otp_pending_username"] = "brahyammontoya@gammalab14.online"
            session["otp_pending_label"] = "brahyammontoya@gammalab14.online"
            session["otp_code"] = "000000"
            session["otp_expires_at"] = "2099-01-01T00:00:00Z"

        response = self.client.post(
            "/login/verify-otp",
            data={"otp_code": "51914977"},
            follow_redirects=False
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/dashboard"))

        with self.client.session_transaction() as session:
            self.assertEqual(session.get("username"), "brahyammontoya@gammalab14.online")
            self.assertEqual(session.get("role"), "admin")


if __name__ == "__main__":
    unittest.main()
