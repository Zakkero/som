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

# ─── Подключение к Vercel KV ───
try:
    from upstash_redis import Redis
    redis = Redis(
        url=os.environ.get("KV_REST_API_URL"),
        token=os.environ.get("KV_REST_API_TOKEN")
    )
except Exception as e:
    print(f"KV connection error: {e}", file=sys.stderr)
    redis = None


# ═══════════════════════════════════════════════════
#  Работа с базой данных
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
    except Exception as e:
        print(f"Error getting admins: {e}", file=sys.stderr)
        return [str(MAIN_ADMIN_ID)]


def is_admin(user_id):
    return str(user_id) in get_admins()


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
        if text.startswith("/add_admin "):
            new_admin = text.split("/add_admin ", 1)[1].strip()
            if not new_admin.isdigit():
                _send_msg(chat_id, "❌ ID должен быть числом. Пример: <code>/add_admin 123456789</code>")
                return
            admins = get_admins()
            if new_admin not in admins:
                admins.append(new_admin)
                if redis:
                    try: redis.set("bot_admins", ",".join(admins))
                    except Exception: pass
                _send_msg(chat_id, f"✅ Админ <code>{new_admin}</code> успешно добавлен!")
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
                _send_msg(chat_id, f"🗑 Админ <code>{rem_admin}</code> удален.")
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
            _send_msg(
                chat_id,
                f"⚙️ <b>Настройки бота</b>\n\n"
                f"Автоприём: <b>{status}</b>\n\n"
                f"Команды:\n"
                f"<code>/add_admin ID</code> — добавить админа\n"
                f"<code>/remove_admin ID</code> — удалить админа\n"
                f"<code>/list_admins</code> — список админов",
                reply_markup=kb
            )
            return

        if text == "/list_admins":
            admins = get_admins()
            admin_list = "\n".join([
                f"• <code>{a}</code>" + (" 👑" if a == str(MAIN_ADMIN_ID) else "")
                for a in admins
            ])
            _send_msg(chat_id, f"👥 <b>Список админов:</b>\n\n{admin_list}\n\n👑 — главный админ")
            return

        if text == "/start" or text == "/help":
            _send_msg(
                chat_id,
                "👋 <b>Привет, админ!</b>\n\n"
                "Доступные команды:\n"
                "<code>/settings</code> — настройки (автоприём)\n"
                "<code>/add_admin ID</code> — добавить админа\n"
                "<code>/remove_admin ID</code> — удалить админа\n"
                "<code>/list_admins</code> — список админов\n"
                "<code>/help</code> — справка"
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

    # Проверяем CHANNEL_ID
    if not CHANNEL_ID:
        print("❌ CHANNEL_ID is empty!", file=sys.stderr)
        _send_msg(chat_id, "⚠️ Ошибка: CHANNEL_ID не установлен. Обратитесь к администратору.")
        return

    auto_accept = False
    if redis:
        try: auto_accept = redis.get("auto_accept") == "true"
        except Exception: auto_accept = False

    has_trigger = any(trigger in msg_text_lower for trigger in TRIGGER_WORDS)

    # Экранируем текст
    safe_name = escape(full_name)
    safe_uname = escape(uname)
    safe_text = escape(msg_text)

    if auto_accept and not has_trigger:
        # ✅ АВТООДОБРЕНИЕ
        copy_resp = requests.post(f"{API}/copyMessage", json={
            "chat_id": CHANNEL_ID,
            "from_chat_id": chat_id,
            "message_id": msg["message_id"],
        })
        print(f"📤 Auto-approve copy: {copy_resp.status_code}", file=sys.stderr)
        if copy_resp.status_code != 200:
            print(f"❌ Copy error: {copy_resp.text}", file=sys.stderr)
        
        admin_text = f"✅ <b>Автоприём:</b> Сообщение опубликовано в канале.\n\n👤 {safe_name} (@{safe_uname})\n💬 {safe_text}"
        for admin_id in get_admins():
            _send_msg(admin_id, admin_text)
    else:
        # ⏸ РУЧНОЕ ОДОБРЕНИЕ
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
        for admin_id in get_admins():
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
            "text": (
                f"⚙️ <b>Настройки бота</b>\n\n"
                f"Автоприём: <b>{status}</b>\n\n"
                f"Команды:\n"
                f"<code>/add_admin ID</code> — добавить админа\n"
                f"<code>/remove_admin ID</code> — удалить админа\n"
                f"<code>/list_admins</code> — список админов"
            ),
            "parse_mode": "HTML",
            "reply_markup": kb
        })
        requests.post(f"{API}/answerCallbackQuery", json={"callback_query_id": cb_id, "text": f"Автоприём {status}"})
        return

    # Одобрение / Отклонение
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
        print(f"📤 Manual approve copy: {copy_resp.status_code}", file=sys.stderr)
        if copy_resp.status_code != 200:
            print(f"❌ Copy error: {copy_resp.text}", file=sys.stderr)
        status_text = "\n\n✅ <b>Опубликовано в канале</b>"
    elif action == "reject":
        status_text = "\n\n❌ <b>Отклонено</b>"
    else:
        return

    safe_original = escape(admin_msg.get("text", ""))
    requests.post(f"{API}/editMessageText", json={
        "chat_id": admin_chat,
        "message_id": admin_mid,
        "text": safe_original + status_text,
        "parse_mode": "HTML",
    })
    requests.post(f"{API}/answerCallbackQuery", json={"callback_query_id": cb_id})