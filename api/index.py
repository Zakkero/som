from http.server import BaseHTTPRequestHandler
import json
import os
import requests

# .strip() автоматически удалит случайные пробелы в начале и конце
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
ADMIN_ID = os.environ.get("ADMIN_ID", "").strip()

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            data = json.loads(body)

            if "message" in data:
                msg = data["message"]
                chat_id = msg["chat"]["id"]
                user_id = str(msg["from"]["id"])
                text = msg.get("text", "[нет текста]")

                is_admin = "✅ ДА" if user_id == ADMIN_ID else "❌ НЕТ"
                token_ok = "✅ ЕСТЬ" if BOT_TOKEN else "❌ НЕТ"

                debug_text = (
                    f"🔍 *ДИАГНОСТИКА*\n\n"
                    f"🆔 Твой ID: `{user_id}`\n"
                    f"⚙️ ADMIN_ID в настройках: `{ADMIN_ID}`\n"
                    f"👑 Ты админ: {is_admin}\n"
                    f"🔑 Токен: {token_ok}\n\n"
                    f"💬 Твой текст: `{text}`"
                )

                url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
                requests.post(url, json={
                    "chat_id": chat_id, 
                    "text": debug_text, 
                    "parse_mode": "Markdown"
                })

            self._respond(200)
            
        except Exception as e:
            # Если что-то пошло не так, мы запишем это в логи Vercel, а не упадём с 500
            print(f"PYTHON ERROR: {str(e)}")
            self._respond(500)

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is alive! Send me a message in Telegram.")

    def _respond(self, code):
        self.send_response(code)
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, format, *args):
        pass