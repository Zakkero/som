from http.server import BaseHTTPRequestHandler
import json
import os
import sys
import requests
from datetime import datetime, timezone, timedelta

# ─── Настройки ───
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
MAIN_ADMIN_ID = os.environ.get("ADMIN_ID", "").strip()
CHANNEL_ID = os.environ.get("CHANNEL_ID", "").strip()
TRIGGER_WORDS_RAW = os.environ.get("TRIGGER_WORDS", "")
TRIGGER_WORDS = [w.strip().lower() for w in TRIGGER_WORDS_RAW.split(",") if w.strip()]

API = f"https://api.telegram.org/bot{BOT_TOKEN}"
TZ = timezone(timedelta(hours=3))

ADMINS = [MAIN_ADMIN_ID]


def _send_msg(chat_id, text, reply_markup=None):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    response = requests.post(f"{API}/sendMessage", json=payload)
    print(f"📤 Sending message to {chat_id}: {response.status_code}", file=sys.stderr)


def is_admin(user_id):
    return str(user_id) in ADMINS


# ═══════════════════════════════════════════════════
#  Обработчик запросов
# ═══════════════════════════════════════════════════
class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        print("🔥 POST REQUEST RECEIVED", file=sys.stderr)
        
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        
        print(f"📦 Body length: {length}", file=sys.stderr)
        
        try:
            data = json.loads(body)
            print(f"✅ JSON parsed successfully", file=sys.stderr)
        except Exception as e:
            print(f"❌ JSON parse error: {e}", file=sys.stderr)
            self._respond(200)
            return

        if "callback_query" in data:
            print("🔘 Callback query detected", file=sys.stderr)
            _handle_callback(data["callback_query"])
        elif "message" in data:
            print("💬 Message detected", file=sys.stderr)
            _handle_message(data["message"])
        else:
            print("⚠️ Unknown request type", file=sys.stderr)
        
        self._respond(200)

    def do_GET(self):
        print("🌐 GET REQUEST RECEIVED", file=sys.stderr)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is alive!")

    def _respond(self, code):
        self.send_response(code)
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, format, *args):
        pass


# ═══════════════════════════════════════════════════
#  1) Пришло сообщение
# ═══════════════════════════════════════════════════
def _handle_message(msg):
    print(f"📨 Handling message from {msg['from']['id']}", file=sys.stderr)
    
    chat_id = msg["chat"]["id"]
    user_id = msg["from"]["id"]
    text = (msg.get("text") or "").strip()

    # ── БЛОК АДМИНА ──
    if is_admin(user_id):
        print(f"👑 User {user_id} is admin", file=sys.stderr)
        
        if text == "/start" or text == "/help":
            print(f"📝 Sending /start response", file=sys.stderr)
            _send_msg(chat_id, "👋 *Привет, админ!*\n\nДоступные команды:\n`/list_admins` — список админов\n`/help` — справка")
            return

        if text == "/list_admins":
            admin_list = "\n".join([f"• `{a}`" + (" 👑" if a == MAIN_ADMIN_ID else "") for a in ADMINS])
            _send_msg(chat_id, f"👥 *Список админов:*\n\n{admin_list}\n\n👑 — главный админ")
            return

        print(f"⏭ Ignoring admin message: {text}", file=sys.stderr)
        return

    # ── БЛОК ОБЫЧНОГО ПОЛЬЗОВАТЕЛЯ ──
    print(f"👤 User {user_id} is NOT admin", file=sys.stderr)
    
    user = msg.get("from", {})
    full_name = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip() or "Не указано"
    uname = user.get("username", "нет")
    dt = datetime.fromtimestamp(msg["date"], tz=TZ)

    msg_text = msg.get("text") or msg.get("caption") or "[Медиа без подписи]"
    msg_text_lower = msg_text.lower()

    has_trigger = any(trigger in msg_text_lower for trigger in TRIGGER_WORDS)

    reason = " ⚠️ *(подозрительные слова)*" if has_trigger else ""
    admin_text = (
        f"📨 *Новое сообщение!*{reason}\n\n"
        f"👤 *Автор:* {full_name} (@{uname})\n"
        f"📅 *Дата:* {dt.strftime('%d.%m.%Y')}\n"
        f"🕐 *Время:* {dt.strftime('%H:%M:%S')}\n\n"
        f"💬 *Текст:*\n{msg_text}"
    )
    keyboard = {
        "inline_keyboard": [[
            {"text": "✅ Одобрить", "callback_data": f"approve:{chat_id}:{msg['message_id']}"},
            {"text": "❌ Отклонить", "callback_data": f"reject:{chat_id}:{msg['message_id']}"},
        ]]
    }
    
    print(f"📤 Sending approval request to admins", file=sys.stderr)
    for admin_id in ADMINS:
        _send_msg(admin_id, admin_text, reply_markup=keyboard)


# ═══════════════════════════════════════════════════
#  2) Админ нажал кнопку
# ═══════════════════════════════════════════════════
def _handle_callback(cb):
    print(f"🔘 Handling callback: {cb['data']}", file=sys.stderr)
    
    data = cb["data"]
    cb_id = cb["id"]
    admin_msg = cb["message"]
    admin_chat = admin_msg["chat"]["id"]
    admin_mid = admin_msg["message_id"]

    try:
        action, orig_chat, orig_mid = data.split(":")
    except Exception as e:
        print(f"❌ Callback parse error: {e}", file=sys.stderr)
        requests.post(f"{API}/answerCallbackQuery", json={"callback_query_id": cb_id})
        return

    if action == "approve":
        print(f"✅ Approving message {orig_mid}", file=sys.stderr)
        requests.post(f"{API}/copyMessage", json={
            "chat_id": CHANNEL_ID,
            "from_chat_id": int(orig_chat),
            "message_id": int(orig_mid),
        })
        status_text = "\n\n✅ *Опубликовано в канале*"
    elif action == "reject":
        print(f"❌ Rejecting message {orig_mid}", file=sys.stderr)
        status_text = "\n\n❌ *Отклонено*"
    else:
        return

    requests.post(f"{API}/editMessageText", json={
        "chat_id": admin_chat,
        "message_id": admin_mid,
        "text": admin_msg["text"] + status_text,
        "parse_mode": "Markdown",
    })
    requests.post(f"{API}/answerCallbackQuery", json={"callback_query_id": cb_id})