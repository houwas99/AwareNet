import time
import unittest

import app as awarenet


class AdminPanelConnectivityTests(unittest.TestCase):
    def setUp(self):
        awarenet.campaigns.clear()
        awarenet.targets.clear()
        awarenet.events.clear()
        self.client = awarenet.app.test_client()

    def test_api_status_endpoint(self):
        res = self.client.get("/api/status")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "running")
        self.assertEqual(data["token"], awarenet.ATTACKER_URL_TOKEN)

    def test_socket_attacker_connect_emits_init_state(self):
        sio = awarenet.socketio.test_client(awarenet.app, flask_test_client=self.client)
        self.assertTrue(sio.is_connected())
        sio.emit("attacker_connect")
        packets = sio.get_received()
        names = [p["name"] for p in packets]
        self.assertIn("init_state", names)
        init = next(p for p in packets if p["name"] == "init_state")["args"][0]
        self.assertIn("token", init)
        self.assertEqual(init["token"], awarenet.ATTACKER_URL_TOKEN)
        sio.disconnect()

    def test_panel_markup_has_connecting_indicator_and_state_manager(self):
        login = self.client.post(
            f"/panel/{awarenet.ATTACKER_URL_TOKEN}",
            data={"password": awarenet.ATTACKER_PASSWORD},
            follow_redirects=True,
        )
        self.assertEqual(login.status_code, 200)
        html = login.get_data(as_text=True)
        self.assertIn('id="cdot"', html)
        self.assertIn('id="clabel">Connecting<', html)
        self.assertIn("window.__awarenetConnectionState", html)
        self.assertIn("function setConnState(state", html)

    def test_button_handlers_use_api_wrapper_and_socket_dispatch(self):
        login = self.client.post(
            f"/panel/{awarenet.ATTACKER_URL_TOKEN}",
            data={"password": awarenet.ATTACKER_PASSWORD},
            follow_redirects=True,
        )
        html = login.get_data(as_text=True)
        self.assertIn("apiRequest('/api/campaigns'", html)
        self.assertIn("apiRequest('/api/delete/all'", html)
        self.assertIn("emitCmd('cmd_capture_photo'", html)
        self.assertIn("ensureSocketConnected('photo capture')", html)
        self.assertIn("let card=document.getElementById('tc-'+sid);", html)
        self.assertNotIn("const card=document.getElementById('tc-'+sid);", html)
        self.assertIn('id="script-health-banner"', html)
        self.assertIn('id="script-health-text"', html)
        self.assertIn('id="nav-health-btn"', html)
        self.assertIn("window.__awarenetMainReady = false;", html)
        self.assertIn("function downloadHealthReport()", html)
        self.assertIn("function auditAction(kind, detail)", html)
        self.assertIn(".lk.audit", html)

    def test_campaign_api_responds_under_500ms(self):
        start = time.perf_counter()
        res = self.client.post(
            "/api/campaigns",
            json={"slug": "load-test", "name": "Load Test", "template": "zoom"},
            headers={"X-Attacker-Token": awarenet.ATTACKER_URL_TOKEN},
        )
        elapsed_ms = (time.perf_counter() - start) * 1000
        self.assertEqual(res.status_code, 201)
        self.assertLess(elapsed_ms, 500)


if __name__ == "__main__":
    unittest.main()
