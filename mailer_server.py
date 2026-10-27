import os
import json
import smtplib
from http.server import BaseHTTPRequestHandler, HTTPServer
from email.message import EmailMessage
from dotenv import load_dotenv

load_dotenv()

SMTP_EMAIL = os.getenv("SMTP_EMAIL", "abhinavjha542@gmail.com")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
RESUME_PATH = os.getenv("RESUME_PATH", "AbhinavJhaIIITManipurResume.pdf")

class MailHandler(BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_GET(self):
        if self.path == "/status":
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "ok": True,
                "smtp_email": SMTP_EMAIL,
                "resume_found": os.path.exists(RESUME_PATH),
                "resume_path": RESUME_PATH
            }).encode())

    def do_POST(self):
        if self.path == "/send":
            length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(length).decode("utf-8"))
            to_email = data.get("to", "").strip()
            subject = data.get("subject", "").strip()
            body = data.get("body", "")

            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.end_headers()

            if not os.path.exists(RESUME_PATH):
                self.wfile.write(json.dumps({"ok": False, "error": f"Resume not found at {RESUME_PATH}"}).encode())
                return

            try:
                msg = EmailMessage()
                msg["From"] = f"Abhinav Kumar Jha <{SMTP_EMAIL}>"
                msg["To"] = to_email
                msg["Subject"] = subject
                msg.set_content(body)

                with open(RESUME_PATH, "rb") as f:
                    msg.add_attachment(
                        f.read(),
                        maintype="application",
                        subtype="pdf",
                        filename=os.path.basename(RESUME_PATH)
                    )

                with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as server:
                    server.login(SMTP_EMAIL, SMTP_PASSWORD)
                    server.send_message(msg)

                print(f"[SENT] -> {to_email} | {subject}")
                self.wfile.write(json.dumps({"ok": True}).encode())
            except Exception as e:
                print(f"[ERROR] -> {e}")
                self.wfile.write(json.dumps({"ok": False, "error": str(e)}).encode())

if __name__ == "__main__":
    print(f"[*] 1-Click Mailer Bridge running on http://127.0.0.1:8765")
    print(f"[*] Using Gmail: {SMTP_EMAIL} | Resume: {RESUME_PATH} (Exists: {os.path.exists(RESUME_PATH)})")
    HTTPServer(("127.0.0.1", 8765), MailHandler).serve_forever()