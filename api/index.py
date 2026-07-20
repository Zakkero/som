from http.server import BaseHTTPRequestHandler
import json
import os
import requests
from datetime import datetime, timezone, timedelta

# ─── Настройки из переменных окружения Vercel ───
BOT_TOKEN  = os.environ.get("8988219440:AAFl0ZC2jZvUcfY71gwqFG1mePke0CpSf60")
ADMIN_ID   = os.environ.get("1935742032")    # твой Telegram user_id (число)
CHANNEL_ID = os.environ.get("-1003907328618")  # @имя_канала или -100xxxx

API = f"https://api.telegram.org/bot{BOT_TOKEN}"

# Московское время (UTC+3). Поменяй если нужно
TZ = timezone(timedelta(hours=3))


# ═══════════════════════════════════════════════════
#  Обработчик запросов от Vercel
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
        pass  # глушим логи, чтобы не засорять


# ═══════════════════════════════════════════════════
#  1) Пришло новое сообщение от пользователя
# ═══════════════════════════════════════════════════
def _handle_message(msg):
    chat_id    = msg["chat"]["id"]
    message_id = msg["message_id"]

    # Не пересылаем собственные сообщения админа
    if str(chat_id) == str(ADMIN_ID):
        return

    # ── Информация об авторе ──
    user = msg.get("from", {})
    first = user.get("first_name", "")
    last  = user.get("last_name", "")
    uname = user.get("username", "—")
    full_name = f"{first} {last}".strip() or "не указано"

    # ── Дата / время ──
    dt = datetime.fromtimestamp(msg["date"], tz=TZ)
    date_str = dt.strftime("%d.%m.%Y")
    time_str = dt.strftime("%H:%M:%S")

    # ── Текст ──
    text = msg.get("text") or msg.get("caption") or "[медиа без подписи]"

    # ── Собираем сообщение для админа ──
    admin_text = (
        f"📨 *Новое сообщение!*\n\n"
        f"👤 *Автор:* {full_name} (@{uname})\n"
        f"📅 *Дата:* {date_str}\n"
        f"🕐 *Время:* {time_str}\n\n"
        f"💬 *Текст:*\n{text}"
    )

    # ── Инлайн-кнопки ──
    # В callback_data кодируем chat_id и message_id оригинала
    cb_approve = f"approve:{chat_id}:{message_id}"
    cb_reject  = f"reject:{chat_id}:{message_id}"

    keyboard = {
        "inline_keyboard": [[
            {"text": "✅ Одобрить", "callback_data": cb_approve},
            {"text": "❌ Отклонить", "callback_data": cb_reject},
        ]]
    }

    requests.post(f"{API}/sendMessage", json={
        "chat_id": ADMIN_ID,
        "text": admin_text,
        "parse_mode": "Markdown",
        "reply_markup": keyboard,
    })


# ═══════════════════════════════════════════════════
#  2) Админ нажал кнопку
# ═══════════════════════════════════════════════════
def _handle_callback(cb):
    data      = cb["data"]
    cb_id     = cb["id"]
    admin_msg = cb["message"]          # сообщение у админа
    admin_chat = admin_msg["chat"]["id"]
    admin_mid  = admin_msg["message_id"]

    action, orig_chat, orig_mid = data.split(":")

    if action == "approve":
        # Копируем оригинальное сообщение в канал БЕЗ метаданных
        requests.post(f"{API}/copyMessage", json={
            "chat_id": CHANNEL_ID,
            "from_chat_id": int(orig_chat),
            "message_id": int(orig_mid),
        })
        status = "\n\n✅ *Опубликовано в канале*"

    elif action == "reject":
        status = "\n\n❌ *Отклонено*"

    else:
        return

    # Обновляем сообщение у админа (убираем кнопки, добавляем статус)
    requests.post(f"{API}/editMessageText", json={
        "chat_id": admin_chat,
        "message_id": admin_mid,
        "text": admin_msg["text"] + status,
        "parse_mode": "Markdown",
    })

    # Убираем «часики» на кнопке
    requests.post(f"{API}/answerCallbackQuery", json={
        "callback_query_id": cb_id,
    })