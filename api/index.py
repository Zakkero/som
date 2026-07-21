from http.server import BaseHTTPRequestHandler
import json
import os
import requests
from datetime import datetime, timezone, timedelta

# ─── Настройки из переменных окружения ───
BOT_TOKEN = os.environ.get("BOT_TOKEN")
MAIN_ADMIN_ID = os.environ.get("ADMIN_ID")
CHANNEL_ID = os.environ.get("CHANNEL_ID")
TRIGGER_WORDS_RAW = os.environ.get("TRIGGER_WORDS", "")
TRIGGER_WORDS = [w.strip().lower() for w in TRIGGER_WORDS_RAW.split(",") if w.strip()]

API = f"https://api.telegram.org/bot{BOT_TOKEN}"
TZ = timezone(timedelta(hours=3))

# ─── Подключение к Vercel KV ───
try:
    from upstash_redis import Redis
    redis = Redis(
        url=os.environ.get("KV_REST_API_URL"),
        token=os.environ.get("KV_REST_API_TOKEN")
    )
except Exception as e:
    print(f"KV connection error: {e}")
    redis = None


# ═══════════════════════════════════════════════════
#  Работа с базой данных (админы и настройки)
# ═══════════════════════════════════════════════════
def get_admins():
    if not redis:
        return [str(MAIN_ADMIN_ID)]
    try:
        admins_str = redis.get("bot_admins")
        if not admins_str:
            redis.set("bot_admins", str(MAIN_ADMIN_ID))
            return [str(MAIN_ADMIN_ID)]
        return admins_str.split(",")
    except Exception:
        return [str(MAIN_ADMIN_ID)]

def is_admin(user_id):
    return str(user_id) in get_admins()

def _send_msg(chat_id, text, reply_markup=None):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    requests.post(f"{API}/sendMessage", json=payload)


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
        if text.startswith("/add_admin "):
            new_admin = text.split("/add_admin ", 1)[1].strip()
            if not new_admin.isdigit():
                _send_msg(chat_id, "❌ ID должен быть числом. Пример: `/add_admin 123456789`")
                return
            admins = get_admins()
            if new_admin not in admins:
                admins.append(new_admin)
                if redis:
                    try: redis.set("bot_admins", ",".join(admins))
                    except Exception: pass
                _send_msg(chat_id, f"✅ Админ `{new_admin}` успешно добавлен!")
            else:
                _send_msg(chat_id, "⚠️ Этот пользователь уже в списке админов.")
            return

        if text.startswith("/remove_admin "):
            rem_admin = text.split("/remove_admin ", 1)[1].strip()
            if rem_admin == str(MAIN_ADMIN_ID):
                _send_msg(chat_id, "❌ Нельзя удалить главного админа!")
                return
            admins = get_admins()
            if rem_admin in admins:
                admins.remove(rem_admin)
                if redis:
                    try: redis.set("bot_admins", ",".join(admins))
                    except Exception: pass
                _send_msg(chat_id, f"🗑 Админ `{rem_admin}` удален.")
            else:
                _send_msg(chat_id, "⚠️ Пользователь не найден в списке админов.")
            return

        if text == "/settings":
            auto_accept = False
            if redis:
                try: auto_accept = redis.get("auto_accept") == "true"
                except Exception: auto_accept = False
            status = "ВКЛ ✅" if auto_accept else "ВЫКЛ ❌"
            kb = {"inline_keyboard": [[{"text": f"🔄 Автоприём: {status}", "callback_data": "toggle_auto"}]]}
            _send_msg(chat_id, f"⚙️ *Настройки бота*\n\nАвтоприём: *{status}*\n\nКоманды:\n`/add_admin ID`\n`/remove_admin ID`\n`/list_admins`", reply_markup=kb)
            return

        if text == "/list_admins":
            admins = get_admins()
            admin_list = "\n".join([f"• `{a}`" + (" 👑" if a == str(MAIN_ADMIN_ID) else "") for a in admins])
            _send_msg(chat_id, f"👥 *Список админов:*\n\n{admin_list}\n\n👑 — главный админ")
            return

        # 🆕 КОМАНДА ДЛЯ ТЕСТИРОВАНИЯ КНОПОК
        if text == "/test":
            _send_msg(
                chat_id,
                "📨 *Тестовое сообщение!*\n\n"
                "👤 *Автор:* Тестовый Пользователь (@test)\n"
                "💬 *Текст:*\nПроверка работы кнопок одобрения.\n\n"
                "*(При нажатии 'Одобрить' бот просто подтвердит действие, не отправляя ничего в канал)*",
                reply_markup={
                    "inline_keyboard": [[
                        {"text": "✅ Одобрить (тест)", "callback_data": "test_approve"},
                        {"text": "❌ Отклонить (тест)", "callback_data": "test_reject"},
                    ]]
                }
            )
            return

        if text == "/start" or text == "/help":
            _send_msg(chat_id, "👋 *Привет, админ!*\n\nДоступные команды:\n`/settings` — настройки\n`/add_admin ID`\n`/remove_admin ID`\n`/list_admins`\n`/test` — проверка кнопок\n`/help` — справка")
            return

        # Если админ написал что-то другое, просто игнорируем (защита от случайных постов)
        return

    # ── БЛОК ОБЫЧНОГО ПОЛЬЗОВАТЕЛЯ ──
    user = msg.get("from", {})
    full_name = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip() or "Не указано"
    uname = user.get("username", "нет")
    dt = datetime.fromtimestamp(msg["date"], tz=TZ)

    msg_text = msg.get("text") or msg.get("caption") or "[Медиа без подписи]"
    msg_text_lower = msg_text.lower()

    auto_accept = False
    if redis:
        try: auto_accept = redis.get("auto_accept") == "true"
        except Exception: auto_accept = False

    has_trigger = any(trigger in msg_text_lower for trigger in TRIGGER_WORDS)

    if auto_accept and not has_trigger:
        # ✅ АВТООДОБРЕНИЕ
        requests.post(f"{API}/copyMessage", json={
            "chat_id": CHANNEL_ID,
            "from_chat_id": chat_id,
            "message_id": msg["message_id"],
        })
        admin_text = f"✅ *Автоприём:* Сообщение опубликовано в канале.\n\n👤 {full_name} (@{uname})\n💬 {msg_text}"
        for admin_id in get_admins():
            _send_msg(admin_id, admin_text)
    else:
        # ⏸ РУЧНОЕ ОДОБРЕНИЕ
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
        for admin_id in get_admins():
            _send_msg(admin_id, admin_text, reply_markup=keyboard)


# ═══════════════════════════════════════════════════
#  2) Админ нажал инлайн-кнопку
# ═══════════════════════════════════════════════════
def _handle_callback(cb):
    data = cb["data"]
    cb_id = cb["id"]
    admin_msg = cb["message"]
    admin_chat = admin_msg["chat"]["id"]
    admin_mid = admin_msg["message_id"]

    # 🆕 Обработка тестовых кнопок
    if data == "test_approve":
        requests.post(f"{API}/editMessageText", json={
            "chat_id": admin_chat,
            "message_id": admin_mid,
            "text": admin_msg["text"] + "\n\n✅ *Тест пройден! Кнопки работают корректно.*",
            "parse_mode": "Markdown",
        })
        requests.post(f"{API}/answerCallbackQuery", json={"callback_query_id": cb_id})
        return

    if data == "test_reject":
        requests.post(f"{API}/editMessageText", json={
            "chat_id": admin_chat,
            "message_id": admin_mid,
            "text": admin_msg["text"] + "\n\n❌ *Тест отклонён.*",
            "parse_mode": "Markdown",
        })
        requests.post(f"{API}/answerCallbackQuery", json={"callback_query_id": cb_id})
        return

    # Переключение автоприёма
    if data == "toggle_auto":
        current = False
        if redis:
            try: current = redis.get("auto_accept") == "true"
            except Exception: current = False

        new_state = "false" if current else "true"
        if redis:
            try: redis.set("auto_accept", new_state)
            except Exception: pass

        status = "ВКЛ ✅" if new_state == "true" else "ВЫКЛ ❌"
        kb = {"inline_keyboard": [[{"text": f"🔄 Автоприём: {status}", "callback_data": "toggle_auto"}]]}

        requests.post(f"{API}/editMessageText", json={
            "chat_id": admin_chat,
            "message_id": admin_mid,
            "text": f"⚙️ *Настройки бота*\n\nАвтоприём: *{status}*\n\nКоманды:\n`/add_admin ID`\n`/remove_admin ID`\n`/list_admins`",
            "parse_mode": "Markdown",
            "reply_markup": kb
        })
        requests.post(f"{API}/answerCallbackQuery", json={"callback_query_id": cb_id, "text": f"Автоприём {status}"})
        return

    # Одобрение / Отклонение реального сообщения
    try:
        action, orig_chat, orig_mid = data.split(":")
    except Exception:
        requests.post(f"{API}/answerCallbackQuery", json={"callback_query_id": cb_id})
        return

    if action == "approve":
        requests.post(f"{API}/copyMessage", json={
            "chat_id": CHANNEL_ID,
            "from_chat_id": int(orig_chat),
            "message_id": int(orig_mid),
        })
        status_text = "\n\n✅ *Опубликовано в канале*"
    elif action == "reject":
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