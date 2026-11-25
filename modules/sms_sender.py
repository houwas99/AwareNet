import logging, threading, urllib.request, urllib.parse, json, base64
from string import Template

logger = logging.getLogger(__name__)

class SMSSender:
    def __init__(self):
        self.provider = "twilio"  # twilio, generic
        self.account_sid = ""
        self.auth_token = ""
        self.from_number = ""
        self.api_key = ""
        self.sender_id = ""

    def configure(self, provider="twilio", account_sid="", auth_token="", from_number="", api_key="", sender_id=""):
        self.provider = provider or "twilio"
        self.account_sid = account_sid or ""
        self.auth_token = auth_token or ""
        self.from_number = from_number or ""
        self.api_key = api_key or ""
        self.sender_id = sender_id or ""

    def is_configured(self):
        if self.provider == "twilio":
            return bool(self.account_sid and self.auth_token and self.from_number)
        # generic provider
        return bool(self.api_key or self.auth_token)

    def send(self, to_number, body):
        if not self.is_configured():
            return False, "SMS not configured"
        try:
            if self.provider == "twilio":
                return self._send_twilio(to_number, body)
            else:
                return self._send_generic(to_number, body)
        except Exception as e:
            logger.error(f"SMS send failed: {e}")
            return False, str(e)

    def _send_twilio(self, to_number, body):
        # Twilio REST API: POST https://api.twilio.com/2010-04-01/Accounts/{SID}/Messages.json
        url = f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}/Messages.json"
        data = urllib.parse.urlencode({
            "From": self.from_number,
            "To": to_number,
            "Body": body
        }).encode()
        auth_str = f"{self.account_sid}:{self.auth_token}"
        auth_b64 = base64.b64encode(auth_str.encode()).decode()
        headers = {
            "Authorization": f"Basic {auth_b64}",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "AwareNet"
        }
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp_data = resp.read().decode()
            j = json.loads(resp_data) if resp_data else {}
            if resp.status in (200, 201):
                return True, "Sent"
            return False, j.get("message", f"HTTP {resp.status}")

    def _send_generic(self, to_number, body):
        # Generic HTTP API example - can be extended
        # Use api_key as URL if provided as full URL
        if self.api_key and self.api_key.startswith("http"):
            url = self.api_key
            payload = json.dumps({"to": to_number, "message": body, "from": self.sender_id}).encode()
            headers = {"Content-Type": "application/json", "User-Agent": "AwareNet"}
            req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=15) as resp:
                return True, "Sent"
        return False, "No generic SMS provider configured"

    def send_async(self, to_number, body, callback=None):
        def _send():
            success, msg = self.send(to_number, body)
            if callback:
                callback(success, msg)
        threading.Thread(target=_send, daemon=True).start()

    def render_template(self, template_body, variables):
        try:
            return Template(template_body).safe_substitute(**variables)
        except Exception as e:
            logger.error(f"SMS template render error: {e}")
            return template_body

sms_sender = SMSSender()
