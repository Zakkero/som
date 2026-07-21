from http.server import BaseHTTPRequestHandler
import json
import os
import sys
import html
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


def escape(text):
    """Экранируем спецсимволы HTML"""
    return html.escape(str(text), quote=False)


def _send_msg(chat_id, text, reply_markup=None):
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    
    response = requests.post(f"{API}/sendMessage", json=payload)
    print(f"📤 Sending to {chat_id}: status={response.status_code}", file=sys.stderr)
    if response.status_code != 200:
        print(f"❌ Telegram error: {response.text}", file=sys.stderr)


def is_admin(user_id):
    return str(user_id) in ADMINS


# ═══════════════════════════════════════════════════
#  Обработчик запросов
# ═══════════════════════════════════════════════════
class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            data = json.loads(body)
        except Exception:
            self._respond(200)
            return

        if "callback_query" in data:
            _handle_callback(data["callback_query"])
        elif "message" in data:
            _handle_message(data["message"])
        self._respond(200)

    def do_GET(self):
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
    chat_id = msg["chat"]["id"]
    user_id = msg["from"]["id"]
    text = (msg.get("text") or "").strip()

    # ── БЛОК АДМИНА ──
    if is_admin(user_id):
        if text == "/start" or text == "/help":
            _send_msg(
                chat_id,
                "👋 <b>Привет, админ!</b>\n\n"
                "Доступные команды:\n"
                "<code>/list_admins</code> — список админов\n"
                "<code>/help</code> — справка"
            )
            return

        if text == "/list_admins":
            admin_list = "\n".join([
                f"• <code>{a}</code>" + (" 👑" if a == MAIN_ADMIN_ID else "")
                for a in ADMINS
            ])
            _send_msg(
                chat_id,
                f"👥 <b>Список админов:</b>\n\n{admin_list}\n\n👑 — главный админ"
            )
            return

        return

    # ── БЛОК ОБЫЧНОГО ПОЛЬЗОВАТЕЛЯ ──
    user = msg.get("from", {})
    first = user.get("first_name", "")
    last = user.get("last_name", "")
    full_name = f"{first} {last}".strip() or "Не указано"
    uname = user.get("username", "нет")
    dt = datetime.fromtimestamp(msg["date"], tz=TZ)

    msg_text = msg.get("text") or msg.get("caption") or "[Медиа без подписи]"
    msg_text_lower = msg_text.lower()

    has_trigger = any(trigger in msg_text_lower for trigger in TRIGGER_WORDS)

    # Экранируем текст пользователя, чтобы HTML не ломался
    safe_name = escape(full_name)
    safe_uname = escape(uname)
    safe_text = escape(msg_text)

    reason = " ⚠️ <i>(подозрительные слова)</i>" if has_trigger else ""
    admin_text = (
        f"📨 <b>Новое сообщение!</b>{reason}\n\n"
        f"👤 <b>Автор:</b> {safe_name} (@{safe_uname})\n"
        f"📅 <b>Дата:</b> {dt.strftime('%d.%m.%Y')}\n"
        f"🕐 <b>Время:</b> {dt.strftime('%H:%M:%S')}\n\n"
        f"💬 <b>Текст:</b>\n{safe_text}"
    )
    keyboard = {
        "inline_keyboard": [[
            {"text": "✅ Одобрить", "callback_data": f"approve:{chat_id}:{msg['message_id']}"},
            {"text": "❌ Отклонить", "callback_data": f"reject:{chat_id}:{msg['message_id']}"},
        ]]
    }

    for admin_id in ADMINS:
        _send_msg(admin_id, admin_text, reply_markup=keyboard)


# ═══════════════════════════════════════════════════
#  2) Админ нажал кнопку
# ═══════════════════════════════════════════════════
def _handle_callback(cb):
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
        copy_resp = requests.post(f"{API}/copyMessage", json={
            "chat_id": CHANNEL_ID,
            "from_chat_id": int(orig_chat),
            "message_id": int(orig_mid),
        })
        print(f"📤 Copy to channel: {copy_resp.status_code}", file=sys.stderr)
        if copy_resp.status_code != 200:
            print(f"❌ Copy error: {copy_resp.text}", file=sys.stderr)
        status_text = "\n\n✅ <b>Опубликовано в канале</b>"
    elif action == "reject":
        status_text = "\n\n❌ <b>Отклонено</b>"
    else:
        return

    # Экранируем оригинальный текст, чтобы HTML не сломался
    safe_original = escape(admin_msg.get("text", ""))
    requests.post(f"{API}/editMessageText", json={
        "chat_id": admin_chat,
        "message_id": admin_mid,
        "text": safe_original + status_text,
        "parse_mode": "HTML",
    })
    requests.post(f"{API}/answerCallbackQuery", json={"callback_query_id": cb_id})