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
CHANNEL_USERNAME = os.environ.get("CHANNEL_USERNAME", "").strip()
TRIGGER_WORDS_RAW = os.environ.get("TRIGGER_WORDS", "")
TRIGGER_WORDS = [w.strip().lower() for w in TRIGGER_WORDS_RAW.split(",") if w.strip()]

ADMINS_RAW = os.environ.get("ADMINS", MAIN_ADMIN_ID)
ADMINS = [a.strip() for a in ADMINS_RAW.split(",") if a.strip()]

AUTO_ACCEPT = os.environ.get("AUTO_ACCEPT", "false").strip().lower() == "true"

API = f"https://api.telegram.org/bot{BOT_TOKEN}"
TZ = timezone(timedelta(hours=3))

# ─── Vercel KV через REST API ───
KV_URL = os.environ.get("KV_REST_API_URL", "").strip()
KV_TOKEN = os.environ.get("KV_REST_API_TOKEN", "").strip()


def kv_get(key):
    if not KV_URL or not KV_TOKEN:
        return None
    try:
        r = requests.get(
            f"{KV_URL}/get/{key}",
            headers={"Authorization": f"Bearer {KV_TOKEN}"},
            timeout=5
        )
        if r.status_code == 200:
            data = r.json()
            return data.get("result")
        return None
    except Exception as e:
        print(f"KV GET error: {e}", file=sys.stderr)
        return None


def kv_set(key, value):
    if not KV_URL or not KV_TOKEN:
        return False
    try:
        r = requests.post(
            f"{KV_URL}/set/{key}/{value}",
            headers={"Authorization": f"Bearer {KV_TOKEN}"},
            timeout=5
        )
        return r.status_code == 200
    except Exception as e:
        print(f"KV SET error: {e}", file=sys.stderr)
        return False


# ═══════════════════════════════════════════════════
#  Чёрный список (ЧС)
# ═══════════════════════════════════════════════════
def get_banlist():
    data = kv_get("banlist")
    if not data:
        return []
    return [x.strip() for x in data.split(",") if x.strip()]


def is_banned(user_id):
    return str(user_id) in get_banlist()


def ban_user(user_id):
    bans = get_banlist()
    uid = str(user_id)
    if uid in bans:
        return False
    bans.append(uid)
    kv_set("banlist", ",".join(bans))
    return True


def unban_user(user_id):
    bans = get_banlist()
    uid = str(user_id)
    if uid not in bans:
        return False
    bans.remove(uid)
    kv_set("banlist", ",".join(bans))
    return True


# ═══════════════════════════════════════════════════
#  Белый список (БС)
# ═══════════════════════════════════════════════════
def get_whitelist():
    data = kv_get("whitelist")
    if not data:
        return []
    return [x.strip() for x in data.split(",") if x.strip()]


def is_whitelisted(user_id):
    return str(user_id) in get_whitelist()


def add_to_whitelist(user_id):
    wl = get_whitelist()
    uid = str(user_id)
    if uid in wl:
        return False
    wl.append(uid)
    kv_set("whitelist", ",".join(wl))
    return True


def remove_from_whitelist(user_id):
    wl = get_whitelist()
    uid = str(user_id)
    if uid not in wl:
        return False
    wl.remove(uid)
    kv_set("whitelist", ",".join(wl))
    return True


# ═══════════════════════════════════════════════════
#  Проверка подписки на канал
# ═══════════════════════════════════════════════════
def is_subscribed(user_id):
    if not CHANNEL_ID:
        return True
    try:
        r = requests.post(f"{API}/getChatMember", json={
            "chat_id": CHANNEL_ID,
            "user_id": int(user_id)
        }, timeout=5)
        if r.status_code == 200:
            data = r.json()
            if data.get("ok"):
                status = data["result"]["status"]
                return status in ["member", "administrator", "creator", "restricted"]
        return False
    except Exception as e:
        print(f"Subscription check error: {e}", file=sys.stderr)
        return True


# ═══════════════════════════════════════════════════
#  Утилиты
# ═══════════════════════════════════════════════════
def escape(text):
    return html.escape(str(text), quote=False)


def _send_msg(chat_id, text, reply_markup=None):
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        response = requests.post(f"{API}/sendMessage", json=payload, timeout=5)
        if response.status_code != 200:
            print(f"Send error {response.status_code}: {response.text}", file=sys.stderr)
        return response.status_code == 200
    except Exception as e:
        print(f"Send exception: {e}", file=sys.stderr)
        return False


def _notify_user(chat_id, text):
    """Безопасно отправляет уведомление пользователю (игнорирует ошибки)"""
    try:
        requests.post(f"{API}/sendMessage", json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML"
        }, timeout=5)
    except Exception:
        pass  # Если пользователь заблокировал бота — молча игнорируем


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

    # ── ПРОВЕРКА 1: ЧЁРНЫЙ СПИСОК ──
    if is_banned(user_id):
        print(f"🚫 Banned user {user_id} blocked", file=sys.stderr)
        return

    # ── БЛОК АДМИНА ──
    if is_admin(user_id):

        if text.startswith("/ban "):
            target = text.split("/ban ", 1)[1].strip()
            if not target.isdigit():
                _send_msg(chat_id, "❌ ID должен быть числом. Пример: <code>/ban 123456789</code>")
                return
            if target == str(MAIN_ADMIN_ID):
                _send_msg(chat_id, "❌ Нельзя забанить главного админа!")
                return
            if target in ADMINS:
                _send_msg(chat_id, "❌ Нельзя забанить админа!")
                return
            if ban_user(target):
                _send_msg(chat_id, f"🚫 <code>{target}</code> добавлен в ЧС.")
            else:
                _send_msg(chat_id, f"⚠️ <code>{target}</code> уже в ЧС.")
            return

        if text.startswith("/unban "):
            target = text.split("/unban ", 1)[1].strip()
            if not target.isdigit():
                _send_msg(chat_id, "❌ ID должен быть числом.")
                return
            if unban_user(target):
                _send_msg(chat_id, f"✅ <code>{target}</code> удалён из ЧС.")
            else:
                _send_msg(chat_id, f"⚠️ <code>{target}</code> не найден в ЧС.")
            return

        if text == "/banlist":
            bans = get_banlist()
            if not bans:
                _send_msg(chat_id, "✅ ЧС пуст.")
            else:
                ban_list = "\n".join([f"• <code>{b}</code>" for b in bans])
                _send_msg(chat_id, f"🚫 <b>Чёрный список ({len(bans)}):</b>\n\n{ban_list}")
            return

        if text.startswith("/add_wl "):
            target = text.split("/add_wl ", 1)[1].strip()
            if not target.isdigit():
                _send_msg(chat_id, "❌ ID должен быть числом.")
                return
            if add_to_whitelist(target):
                _send_msg(chat_id, f"⭐ <code>{target}</code> добавлен в БС.")
            else:
                _send_msg(chat_id, f"⚠️ <code>{target}</code> уже в БС.")
            return

        if text.startswith("/remove_wl "):
            target = text.split("/remove_wl ", 1)[1].strip()
            if not target.isdigit():
                _send_msg(chat_id, "❌ ID должен быть числом.")
                return
            if remove_from_whitelist(target):
                _send_msg(chat_id, f"✅ <code>{target}</code> удалён из БС.")
            else:
                _send_msg(chat_id, f"⚠️ <code>{target}</code> не найден в БС.")
            return

        if text == "/whitelist":
            wl = get_whitelist()
            if not wl:
                _send_msg(chat_id, "✅ БС пуст.")
            else:
                wl_list = "\n".join([f"• <code>{w}</code>" for w in wl])
                _send_msg(chat_id, f"⭐ <b>Белый список ({len(wl)}):</b>\n\n{wl_list}")
            return

        if text.startswith("/check "):
            target = text.split("/check ", 1)[1].strip()
            if not target.isdigit():
                _send_msg(chat_id, "❌ ID должен быть числом.")
                return
            banned = "🚫 В ЧС" if is_banned(target) else "✅ Не в ЧС"
            wl = "⭐ В БС" if is_whitelisted(target) else "— Не в БС"
            member = "✅ Подписан" if is_subscribed(target) else "❌ Не подписан"
            admin = "👑 Админ бота" if target in ADMINS else "— Обычный пользователь"
            _send_msg(
                chat_id,
                f"🔍 <b>Проверка <code>{target}</code>:</b>\n\n"
                f"• Статус: {admin}\n"
                f"• ЧС: {banned}\n"
                f"• БС: {wl}\n"
                f"• Подписка: {member}"
            )
            return

        if text == "/start" or text == "/help":
            status = "ВКЛ ✅" if AUTO_ACCEPT else "ВЫКЛ ❌"
            bans = get_banlist()
            wl = get_whitelist()
            _send_msg(
                chat_id,
                f"👋 <b>Привет, админ!</b>\n\n"
                f"🔄 Автоприём: <b>{status}</b>\n"
                f"🚫 В ЧС: <b>{len(bans)}</b>\n"
                f"⭐ В БС: <b>{len(wl)}</b>\n\n"
                f"<b>Команды:</b>\n"
                f"<code>/ban ID</code> — забанить\n"
                f"<code>/unban ID</code> — разбанить\n"
                f"<code>/banlist</code> — ЧС\n"
                f"<code>/add_wl ID</code> — в БС\n"
                f"<code>/remove_wl ID</code> — убрать из БС\n"
                f"<code>/whitelist</code> — БС\n"
                f"<code>/check ID</code> — проверить\n"
                f"<code>/list_admins</code> — админы"
            )
            return

        if text == "/list_admins":
            admin_list = "\n".join([
                f"• <code>{a}</code>" + (" 👑" if a == MAIN_ADMIN_ID else "")
                for a in ADMINS
            ])
            _send_msg(chat_id, f"👥 <b>Админы:</b>\n\n{admin_list}\n\n👑 — главный")
            return

        return

    # ── ПРОВЕРКА 2: ПОДПИСКА НА КАНАЛ ──
    if not is_subscribed(user_id):
        print(f"🔒 User {user_id} not subscribed", file=sys.stderr)
        channel_link = f"https://t.me/{CHANNEL_USERNAME.lstrip('@')}" if CHANNEL_USERNAME else "#"
        keyboard = {
            "inline_keyboard": [[
                {"text": "📢 Подписаться на канал", "url": channel_link}
            ], [
                {"text": "🔄 Проверить подписку", "callback_data": "check_sub"}
            ]]
        }
        _send_msg(
            chat_id,
            "🔒 <b>Доступ ограничен</b>\n\n"
            "Чтобы отправлять сообщения, нужно подписаться на наш канал.\n\n"
            f"Канал: {CHANNEL_USERNAME or CHANNEL_ID}\n\n"
            "После подписки нажмите <b>«Проверить подписку»</b> и отправьте сообщение снова.",
            reply_markup=keyboard
        )
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

    if not CHANNEL_ID:
        print("CHANNEL_ID is empty!", file=sys.stderr)
        return

    has_trigger = any(trigger in msg_text_lower for trigger in TRIGGER_WORDS)
    in_whitelist = is_whitelisted(user_id)

    safe_name = escape(full_name)
    safe_uname = escape(uname)
    safe_text = escape(msg_text)

    should_auto = (AUTO_ACCEPT or in_whitelist) and not has_trigger

    if should_auto:
        # ✅ АВТООДОБРЕНИЕ
        copy_resp = requests.post(f"{API}/copyMessage", json={
            "chat_id": CHANNEL_ID,
            "from_chat_id": chat_id,
            "message_id": msg["message_id"],
        })
        if copy_resp.status_code != 200:
            print(f"Copy error: {copy_resp.text}", file=sys.stderr)
            _notify_user(chat_id, "⚠️ <b>Ошибка:</b> не удалось опубликовать сообщение. Попробуйте позже.")
        else:
            # Уведомляем пользователя об успешной публикации
            _notify_user(
                chat_id,
                "✅ <b>Ваше сообщение опубликовано!</b>\n\n"
                f"Спасибо, что делитесь с нами! 🎉\n\n"
                f"👉 <a href=\"https://t.me/{CHANNEL_USERNAME.lstrip('@')}\">Перейти в канал</a>"
                if CHANNEL_USERNAME else
                "✅ <b>Ваше сообщение опубликовано!</b>\n\nСпасибо, что делитесь с нами! 🎉"
            )

        reason = "⭐ <b>Белый список:</b>" if in_whitelist else "✅ <b>Автоприём:</b>"
        admin_text = (
            f"{reason} Опубликовано в канале.\n\n"
            f"👤 {safe_name} (@{safe_uname})\n"
            f"💬 {safe_text}"
        )
        for admin_id in ADMINS:
            _send_msg(admin_id, admin_text)
    else:
        # ⏸ РУЧНОЕ ОДОБРЕНИЕ
        # Уведомляем пользователя, что сообщение на модерации
        _notify_user(
            chat_id,
            "📨 <b>Ваше сообщение отправлено на модерацию</b>\n\n"
            "Администраторы рассмотрят его в ближайшее время.\n"
            "Мы уведомим вас о решении. ⏳"
        )

        statuses = []
        if in_whitelist:
            statuses.append("⭐ БС")
        statuses.append("✅ Подписчик")
        status_line = f"🏷 <b>Статус:</b> {' | '.join(statuses)}\n" if statuses else ""

        reason = " ⚠️ <i>(подозрительные слова)</i>" if has_trigger else ""
        admin_text = (
            f"📨 <b>Новое сообщение!</b>{reason}\n\n"
            f"👤 <b>Автор:</b> {safe_name} (@{safe_uname})\n"
            f"🆔 <b>ID:</b> <code>{user_id}</code>\n"
            f"{status_line}"
            f"📅 <b>Дата:</b> {dt.strftime('%d.%m.%Y')}\n"
            f"🕐 <b>Время:</b> {dt.strftime('%H:%M:%S')}\n\n"
            f"💬 <b>Текст:</b>\n{safe_text}"
        )
        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "✅ Одобрить", "callback_data": f"approve:{chat_id}:{msg['message_id']}"},
                    {"text": "❌ Отклонить", "callback_data": f"reject:{chat_id}:{msg['message_id']}"},
                ],
                [
                    {"text": "🚫 Забанить", "callback_data": f"ban:{user_id}"},
                    {"text": "⭐ В БС", "callback_data": f"whitelist:{user_id}"},
                ]
            ]
        }
        for admin_id in ADMINS:
            _send_msg(admin_id, admin_text, reply_markup=keyboard)


# ═══════════════════════════════════════════════════
#  2) Админ нажал кнопку
# ═══════════════════════════════════════════════════
def _handle_callback(cb):
    data = cb["data"]
    cb_id = cb["id"]
    user_id = cb["from"]["id"]
    admin_msg = cb["message"]
    admin_chat = admin_msg["chat"]["id"]
    admin_mid = admin_msg["message_id"]

    # ── Проверка подписки ──
    if data == "check_sub":
        if is_subscribed(user_id):
            requests.post(f"{API}/answerCallbackQuery", json={
                "callback_query_id": cb_id,
                "text": "✅ Вы подписаны! Теперь можете отправлять сообщения.",
                "show_alert": True
            })
        else:
            requests.post(f"{API}/answerCallbackQuery", json={
                "callback_query_id": cb_id,
                "text": "❌ Вы не подписаны на канал!",
                "show_alert": True
            })
        return

    # ── Забанить из кнопки ──
    if data.startswith("ban:"):
        target_id = data.split(":")[1]
        if ban_user(target_id):
            status_text = f"\n\n🚫 <b>Автор <code>{target_id}</code> забанен!</b>"
            _send_msg(admin_chat, f"🚫 <code>{target_id}</code> добавлен в ЧС.")
            # Уведомляем забаненного (если он ещё не заблокировал бота)
            # Но обычно забаненным не пишем — они и так не смогут писать
        else:
            status_text = f"\n\n⚠️ <b>Автор <code>{target_id}</code> уже в ЧС.</b>"
        safe_original = escape(admin_msg.get("text", ""))
        requests.post(f"{API}/editMessageText", json={
            "chat_id": admin_chat,
            "message_id": admin_mid,
            "text": safe_original + status_text,
            "parse_mode": "HTML",
        })
        requests.post(f"{API}/answerCallbackQuery", json={"callback_query_id": cb_id})
        return

    # ── В белый список из кнопки ──
    if data.startswith("whitelist:"):
        target_id = data.split(":")[1]
        if add_to_whitelist(target_id):
            status_text = f"\n\n⭐ <b>Автор <code>{target_id}</code> добавлен в БС!</b>"
            _send_msg(admin_chat, f"⭐ <code>{target_id}</code> добавлен в БС.")
        else:
            status_text = f"\n\n⚠️ <b>Автор <code>{target_id}</code> уже в БС.</b>"
        safe_original = escape(admin_msg.get("text", ""))
        requests.post(f"{API}/editMessageText", json={
            "chat_id": admin_chat,
            "message_id": admin_mid,
            "text": safe_original + status_text,
            "parse_mode": "HTML",
        })
        requests.post(f"{API}/answerCallbackQuery", json={"callback_query_id": cb_id})
        return

    # ── Одобрение / Отклонение ──
    try:
        action, orig_chat, orig_mid = data.split(":")
    except Exception:
        requests.post(f"{API}/answerCallbackQuery", json={"callback_query_id": cb_id})
        return

    if action == "approve":
        copy_resp = requests.post(f"{API}/copyMessage", json={
            "chat_id": CHANNEL_ID,
            "from_chat_id": int(orig_chat),
            "message_id": int(orig_mid),
        })
        if copy_resp.status_code != 200:
            print(f"Copy error: {copy_resp.text}", file=sys.stderr)
            status_text = "\n\n⚠️ <b>Ошибка публикации</b>"
        else:
            status_text = "\n\n✅ <b>Опубликовано в канале</b>"
            # 🎉 УВЕДОМЛЯЕМ АВТОРА О ПУБЛИКАЦИИ
            _notify_user(
                int(orig_chat),
                "✅ <b>Ваше сообщение опубликовано!</b>\n\n"
                "Спасибо, что делитесь с нами! 🎉\n\n"
                + (f"👉 <a href=\"https://t.me/{CHANNEL_USERNAME.lstrip('@')}\">Перейти в канал</a>" if CHANNEL_USERNAME else "")
            )
    elif action == "reject":
        status_text = "\n\n❌ <b>Отклонено</b>"
        # 📢 УВЕДОМЛЯЕМ АВТОРА ОБ ОТКЛОНЕНИИ
        _notify_user(
            int(orig_chat),
            "❌ <b>Ваше сообщение отклонено</b>\n\n"
            "К сожалению, оно не подходит под формат нашего канала.\n"
            "Попробуйте отправить другое сообщение! ✨"
        )
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