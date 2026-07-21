from http.server import BaseHTTPRequestHandler
import json
import os
import requests

# Читаем переменные
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = os.environ.get("ADMIN_ID")

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        
        try:
            data = json.loads(body)
        except Exception:
            self._respond(200)
            return

        # Если это сообщение
        if "message" in data:
            msg = data["message"]
            chat_id = msg["chat"]["id"]
            user_id = msg["from"]["id"]
            user_name = msg["from"].get("first_name", "Неизвестно")
            text = msg.get("text", "[нет текста]")

            # Формируем диагностическое сообщение
            token_status = "✅ ЕСТЬ" if BOT_TOKEN else "❌ ОТСУТСТВУЕТ"
            is_admin = "✅ ДА" if str(user_id) == str(ADMIN_ID) else "❌ НЕТ"

            debug_text = (
                f"🔍 *ДИАГНОСТИКА БОТА*\n\n"
                f"👤 Твоё имя: {user_name}\n"
                f"🆔 Твой ID: `{user_id}`\n"
                f"💬 Твой текст: `{text}`\n\n"
                f"⚙️ *Статус настроек:*\n"
                f"• BOT_TOKEN: {token_status}\n"
                f"• ADMIN_ID в настройках: `{ADMIN_ID}`\n"
                f"• Ты являешься админом для бота: {is_admin}"
            )

            # Пытаемся отправить ответ
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
            response = requests.post(url, json={
                "chat_id": chat_id,
                "text": debug_text,
                "parse_mode": "Markdown"
            })
            
            # Если отправка не удалась, запишем это в логи Vercel
            if response.status_code != 200:
                print(f"TELEGRAM API ERROR: {response.text}")

        self._respond(200)

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