import smtplib, logging, threading
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from string import Template

logger = logging.getLogger(__name__)

class EmailSender:
    def __init__(self):
        self.host = ""
        self.port = 587
        self.username = ""
        self.password = ""
        self.use_tls = True
        self.sender_name = "AwareNet"
        self.sender_email = ""

    def configure(self, host, port=587, username="", password="", use_tls=True,
                  sender_name="AwareNet", sender_email=""):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.use_tls = use_tls
        self.sender_name = sender_name
        self.sender_email = sender_email

    def is_configured(self):
        return bool(self.host and self.sender_email)

    def send(self, to_email, subject, body_html, cc=None, bcc=None):
        if not self.is_configured():
            return False, "SMTP not configured"
        try:
            msg = MIMEMultipart("alternative")
            msg["From"] = f"{self.sender_name} <{self.sender_email}>"
            msg["To"] = to_email
            msg["Subject"] = subject
            if cc:
                msg["Cc"] = ", ".join(cc) if isinstance(cc, list) else cc
            msg.attach(MIMEText(body_html, "html"))
            recipients = [to_email]
            if cc:
                recipients += (cc if isinstance(cc, list) else [cc])
            if bcc:
                recipients += (bcc if isinstance(bcc, list) else [bcc])
            server = smtplib.SMTP(self.host, self.port, timeout=15)
            server.ehlo()
            if self.use_tls:
                server.starttls()
                server.ehlo()
            if self.username and self.password:
                server.login(self.username, self.password)
            server.sendmail(self.sender_email, recipients, msg.as_string())
            server.quit()
            return True, "Sent"
        except Exception as e:
            logger.error(f"Email send failed: {e}")
            return False, str(e)

    def send_async(self, to_email, subject, body_html, callback=None):
        def _send():
            success, msg = self.send(to_email, subject, body_html)
            if callback:
                callback(success, msg)
        threading.Thread(target=_send, daemon=True).start()

    def render_template(self, template_body, variables):
        try:
            return Template(template_body).safe_substitute(**variables)
        except Exception as e:
            logger.error(f"Template render error: {e}")
            return template_body

    def get_presets(self):
        return [
            {
                "name": "Zoom Meeting Invitation",
                "subject": "You are invited to join a Zoom meeting",
                "body": self._zoom_invite_template(),
            },
            {
                "name": "Account Security Alert",
                "subject": "Unusual sign-in attempt detected",
                "body": self._security_alert_template(),
            },
            {
                "name": "Password Reset Request",
                "subject": "Reset your password",
                "body": self._password_reset_template(),
            },
        ]

    def _zoom_invite_template(self):
        return """<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
<div style="background: #2D8CFF; padding: 24px; text-align: center;">
<img src="https://st1.zoom.us/zoom.ico" style="width: 48px;" />
<h1 style="color: white; font-size: 22px; margin: 10px 0 0;">You are invited to a Zoom Meeting</h1>
</div>
<div style="padding: 28px; background: #f9f9f9;">
<p style="font-size: 15px; color: #333;">Hi <strong>${name}</strong>,</p>
<p style="font-size: 15px; color: #555; line-height: 1.7;">
You are invited to join a Zoom meeting scheduled by your organization.</p>
<p style="font-size: 15px; color: #555;"><strong>Topic:</strong> ${topic}</p>
<p style="font-size: 15px; color: #555;"><strong>Time:</strong> ${time}</p>
<div style="text-align: center; margin: 28px 0;">
<a href="${link}" style="background: #2D8CFF; color: white; padding: 14px 36px;
border-radius: 6px; text-decoration: none; font-size: 16px; font-weight: bold;
display: inline-block;">Join Zoom Meeting</a>
</div>
<p style="font-size: 13px; color: #888;">If the button doesn't work, copy this link:<br>
<span style="color: #2D8CFF;">${link}</span></p>
</div>
<div style="padding: 16px; text-align: center; font-size: 12px; color: #aaa;">
Zoom Video Communications Inc.<br>
This is a simulated phishing test.
</div>
</div>"""

    def _security_alert_template(self):
        return """<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
<div style="background: #e8294c; padding: 20px; text-align: center; color: white;">
<h1 style="font-size: 20px; margin: 0;">⚠ Security Alert</h1>
</div>
<div style="padding: 28px; background: #f9f9f9;">
<p style="font-size: 15px; color: #333;">Dear <strong>${name}</strong>,</p>
<p style="font-size: 15px; color: #555; line-height: 1.7;">
We noticed an unusual sign-in attempt to your account from a new device.</p>
<div style="background: #fff3f3; border-left: 4px solid #e8294c; padding: 14px; margin: 18px 0;">
<p style="margin: 2px 0; font-size: 13px; color: #666;"><strong>Time:</strong> ${time}</p>
<p style="margin: 2px 0; font-size: 13px; color: #666;"><strong>Location:</strong> Unknown</p>
</div>
<div style="text-align: center; margin: 24px 0;">
<a href="${link}" style="background: #e8294c; color: white; padding: 14px 36px;
border-radius: 6px; text-decoration: none; font-size: 16px; font-weight: bold;
display: inline-block;">Secure Your Account</a>
</div>
<p style="font-size: 13px; color: #888;">If this wasn't you, please secure your account immediately.</p>
</div>
<div style="padding: 16px; text-align: center; font-size: 12px; color: #aaa;">
Security Team<br>
This is a simulated phishing test.
</div>
</div>"""

    def _password_reset_template(self):
        return """<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
<div style="background: #1a1a2e; padding: 20px; text-align: center;">
<h1 style="color: white; font-size: 20px; margin: 0;">Password Reset Request</h1>
</div>
<div style="padding: 28px; background: #f9f9f9;">
<p style="font-size: 15px; color: #333;">Hi <strong>${name}</strong>,</p>
<p style="font-size: 15px; color: #555; line-height: 1.7;">
We received a request to reset the password associated with your account.</p>
<div style="text-align: center; margin: 28px 0;">
<a href="${link}" style="background: #1a1a2e; color: white; padding: 14px 36px;
border-radius: 6px; text-decoration: none; font-size: 16px; font-weight: bold;
display: inline-block;">Reset Password</a>
</div>
<p style="font-size: 13px; color: #888;">
This link will expire in <strong>24 hours</strong>.<br>
If you didn't request this, please ignore this email.</p>
</div>
<div style="padding: 16px; text-align: center; font-size: 12px; color: #aaa;">
Your Company<br>
This is a simulated phishing test.
</div>
</div>"""

email_sender = EmailSender()
