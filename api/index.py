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
RATING_AUTO_THRESHOLD = int(os.environ.get("RATING_AUTO_THRESHOLD", "8"))

API = f"https://api.telegram.org/bot{BOT_TOKEN}"
TZ = timezone(timedelta(hours=3))

# ─── Vercel KV ───
KV_URL = os.environ.get("KV_REST_API_URL", "").strip()
KV_TOKEN = os.environ.get("KV_REST_API_TOKEN", "").strip()


def kv_get(key):
    if not KV_URL or not KV_TOKEN: return None
    try:
        r = requests.get(f"{KV_URL}/get/{key}", headers={"Authorization": f"Bearer {KV_TOKEN}"}, timeout=5)
        if r.status_code == 200: return r.json().get("result")
        return None
    except Exception as e:
        print(f"KV GET error: {e}", file=sys.stderr)
        return None


def kv_set(key, value):
    if not KV_URL or not KV_TOKEN: return False
    try:
        r = requests.post(f"{KV_URL}/set/{key}/{value}", headers={"Authorization": f"Bearer {KV_TOKEN}"}, timeout=5)
        return r.status_code == 200
    except Exception as e:
        print(f"KV SET error: {e}", file=sys.stderr)
        return False


# ═══════════════════════════════════════════════════
#  ЧЁРНЫЙ СПИСОК
# ═══════════════════════════════════════════════════
def get_banlist():
    data = kv_get("banlist")
    return [x.strip() for x in data.split(",") if x.strip()] if data else []

def is_banned(user_id):
    return str(user_id) in get_banlist()

def ban_user(user_id):
    bans = get_banlist()
    uid = str(user_id)
    if uid in bans: return False
    bans.append(uid)
    kv_set("banlist", ",".join(bans))
    return True

def unban_user(user_id):
    bans = get_banlist()
    uid = str(user_id)
    if uid not in bans: return False
    bans.remove(uid)
    kv_set("banlist", ",".join(bans))
    return True


# ═══════════════════════════════════════════════════
#  БЕЛЫЙ СПИСОК
# ═══════════════════════════════════════════════════
def get_whitelist():
    data = kv_get("whitelist")
    return [x.strip() for x in data.split(",") if x.strip()] if data else []

def is_whitelisted(user_id):
    return str(user_id) in get_whitelist()

def add_to_whitelist(user_id):
    wl = get_whitelist()
    uid = str(user_id)
    if uid in wl: return False
    wl.append(uid)
    kv_set("whitelist", ",".join(wl))
    return True

def remove_from_whitelist(user_id):
    wl = get_whitelist()
    uid = str(user_id)
    if uid not in wl: return False
    wl.remove(uid)
    kv_set("whitelist", ",".join(wl))
    return True


# ═══════════════════════════════════════════════════
#  РЕЙТИНГ
# ═══════════════════════════════════════════════════
def get_rating(user_id):
    data = kv_get(f"rating_{user_id}")
    return int(data) if data else 5

def change_rating(user_id, delta):
    current = get_rating(user_id)
    new_rating = max(0, min(10, current + delta))
    kv_set(f"rating_{user_id}", str(new_rating))
    return new_rating


# ═══════════════════════════════════════════════════
#  СТАТИСТИКА
# ═══════════════════════════════════════════════════
def inc_stat(key):
    current = kv_get(key)
    value = int(current) + 1 if current else 1
    kv_set(key, str(value))

def get_stats():
    return {
        "total": int(kv_get("stats_total") or 0),
        "approved": int(kv_get("stats_approved") or 0),
        "rejected": int(kv_get("stats_rejected") or 0),
        "banned": int(kv_get("stats_banned") or 0),
    }


# ═══════════════════════════════════════════════════
#  ЛОГИ
# ═══════════════════════════════════════════════════
def add_log(action, admin_id, details=""):
    logs = kv_get("admin_logs") or ""
    timestamp = datetime.now(TZ).strftime("%d.%m %H:%M")
    new_log = f"[{timestamp}] {admin_id}: {action} {details}\n"
    logs = new_log + logs
    log_lines = logs.strip().split("\n")[:50]
    kv_set("admin_logs", "\n".join(log_lines))

def get_logs():
    return kv_get("admin_logs") or "Логи пусты."


# ═══════════════════════════════════════════════════
#  ПОДПИСКА
# ═══════════════════════════════════════════════════
def is_subscribed(user_id):
    if not CHANNEL_ID: return True
    try:
        r = requests.post(f"{API}/getChatMember", json={"chat_id": CHANNEL_ID, "user_id": int(user_id)}, timeout=5)
        if r.status_code == 200 and r.json().get("ok"):
            return r.json()["result"]["status"] in ["member", "administrator", "creator", "restricted"]
        return False
    except Exception:
        return True


# ═══════════════════════════════════════════════════
#  УТИЛИТЫ
# ═══════════════════════════════════════════════════
def escape(text):
    return html.escape(str(text), quote=False)

def _send_msg(chat_id, text, reply_markup=None):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup: payload["reply_markup"] = reply_markup
    try:
        response = requests.post(f"{API}/sendMessage", json=payload, timeout=5)
        return response.status_code == 200
    except Exception:
        return False

def _notify_user(chat_id, text):
    try:
        requests.post(f"{API}/sendMessage", json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"}, timeout=5)
    except Exception:
        pass

def is_admin(user_id):
    return str(user_id) in ADMINS

def get_media_type(msg):
    if msg.get("photo"): return "photo"
    if msg.get("video"): return "video"
    if msg.get("voice"): return "voice"
    if msg.get("video_note"): return "video_note"
    if msg.get("document"): return "document"
    if msg.get("sticker"): return "sticker"
    if msg.get("audio"): return "audio"
    if msg.get("animation"): return "animation"
    return None

def get_media_emoji(media_type):
    emojis = {"photo": "📷 Фото", "video": "🎥 Видео", "voice": "🎤 Голосовое", "video_note": "📹 Кружок", "document": "📄 Документ", "sticker": "🎭 Стикер", "audio": "🎵 Аудио", "animation": "🎞 GIF"}
    return emojis.get(media_type, "")

def send_media_to_admin(admin_id, msg, caption, keyboard):
    media_type = get_media_type(msg)
    if not media_type: return None
    try:
        if media_type == "photo":
            file_id = msg["photo"][-1]["file_id"]
            return requests.post(f"{API}/sendPhoto", json={"chat_id": admin_id, "photo": file_id, "caption": caption, "parse_mode": "HTML", "reply_markup": keyboard}, timeout=10)
        elif media_type == "video":
            file_id = msg["video"]["file_id"]
            return requests.post(f"{API}/sendVideo", json={"chat_id": admin_id, "video": file_id, "caption": caption, "parse_mode": "HTML", "reply_markup": keyboard}, timeout=10)
        elif media_type == "voice":
            file_id = msg["voice"]["file_id"]
            return requests.post(f"{API}/sendVoice", json={"chat_id": admin_id, "voice": file_id, "caption": caption, "parse_mode": "HTML", "reply_markup": keyboard}, timeout=10)
        elif media_type == "document":
            file_id = msg["document"]["file_id"]
            return requests.post(f"{API}/sendDocument", json={"chat_id": admin_id, "document": file_id, "caption": caption, "parse_mode": "HTML", "reply_markup": keyboard}, timeout=10)
        elif media_type == "animation":
            file_id = msg["animation"]["file_id"]
            return requests.post(f"{API}/sendAnimation", json={"chat_id": admin_id, "animation": file_id, "caption": caption, "parse_mode": "HTML", "reply_markup": keyboard}, timeout=10)
    except Exception as e:
        print(f"Send media error: {e}", file=sys.stderr)
    return None


# ═══════════════════════════════════════════════════
#  HTTP ОБРАБОТЧИК
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
#  ОБРАБОТКА СООБЩЕНИЙ
# ═══════════════════════════════════════════════════
def _handle_message(msg):
    chat_id = msg["chat"]["id"]
    user_id = msg["from"]["id"]
    text = (msg.get("text") or "").strip()

    if is_banned(user_id):
        return

    if is_admin(user_id):
        _handle_admin_command(chat_id, user_id, text)
        return

    # Пользовательские команды
    if text == "/myrating":
        rating = get_rating(user_id)
        stars = "⭐" * rating + "☆" * (10 - rating)
        _send_msg(chat_id, f"👤 <b>Ваш рейтинг:</b>\n\n{stars} ({rating}/10)\n\nЧем выше рейтинг, тем быстрее ваши сообщения публикуются!")
        return

    if text == "/info":
        rating = get_rating(user_id)
        stars = "⭐" * rating
        subscribed = "✅ Да" if is_subscribed(user_id) else "❌ Нет"
        in_wl = "✅ Да" if is_whitelisted(user_id) else "❌ Нет"
        _send_msg(chat_id,
            f"📊 <b>Ваша информация</b>\n\n"
            f"⭐ Рейтинг: {stars} ({rating}/10)\n"
            f"📢 Подписан на канал: {subscribed}\n"
            f"⭐ В белом списке: {in_wl}\n\n"
            f"💡 Совет: чем выше рейтинг, тем быстрее публикуются ваши сообщения!"
        )
        return

    if not is_subscribed(user_id):
        channel_link = f"https://t.me/{CHANNEL_USERNAME.lstrip('@')}" if CHANNEL_USERNAME else "#"
        keyboard = {"inline_keyboard": [[{"text": "📢 Подписаться", "url": channel_link}], [{"text": "🔄 Проверить", "callback_data": "check_sub"}]]}
        _send_msg(chat_id, "🔒 <b>Доступ ограничен</b>\n\nПодпишитесь на канал:\n" + (CHANNEL_USERNAME or CHANNEL_ID), reply_markup=keyboard)
        return

    _handle_user_message(msg)


def _handle_admin_command(chat_id, user_id, text):
    if text == "/start" or text == "/help":
        stats = get_stats()
        bans = len(get_banlist())
        wl = len(get_whitelist())
        _send_msg(chat_id,
            f"👋 <b>Привет, админ!</b>\n\n"
            f"📊 Всего: {stats['total']} | ✅ Одобрено: {stats['approved']} | ❌ Отклонено: {stats['rejected']}\n"
            f"🚫 В ЧС: {bans} | ⭐ В БС: {wl}\n\n"
            f"<b>📊 СТАТИСТИКА</b>\n<code>/stats</code> — статистика\n\n"
            f"<b>👥 ПОЛЬЗОВАТЕЛИ</b>\n<code>/rating ID</code> — рейтинг\n<code>/rate ID ±N</code> — изменить\n<code>/check ID</code> — проверка\n\n"
            f"<b>🚫 МОДЕРАЦИЯ</b>\n<code>/ban ID</code> — бан\n<code>/unban ID</code> — разбан\n<code>/banlist</code> — ЧС\n<code>/add_wl ID</code> — в БС\n<code>/remove_wl ID</code> — из БС\n<code>/whitelist</code> — БС\n\n"
            f"<b>📨 РАССЫЛКИ</b>\n<code>/broadcast текст</code> — рассылка в БС\n\n"
            f"<b>📜 ЛОГИ</b>\n<code>/log</code> — действия\n\n"
            f"<b>🔧 АДМИНЫ</b>\n<code>/list_admins</code> — список"
        )
        return

    if text == "/stats":
        stats = get_stats()
        bans = len(get_banlist())
        wl = len(get_whitelist())
        _send_msg(chat_id, f"📊 <b>Статистика</b>\n\n📨 Всего: <b>{stats['total']}</b>\n✅ Одобрено: <b>{stats['approved']}</b>\n❌ Отклонено: <b>{stats['rejected']}</b>\n🚫 Забанено: <b>{stats['banned']}</b>\n\n⭐ В БС: <b>{wl}</b>")
        return

    if text.startswith("/rating "):
        target = text.split("/rating ", 1)[1].strip()
        if not target.isdigit():
            _send_msg(chat_id, "❌ ID должен быть числом.")
            return
        rating = get_rating(target)
        stars = "⭐" * rating + "☆" * (10 - rating)
        _send_msg(chat_id, f"👤 Рейтинг <code>{target}</code>:\n\n{stars} ({rating}/10)")
        return

    if text.startswith("/rate "):
        parts = text.split()
        if len(parts) != 3:
            _send_msg(chat_id, "❌ Формат: <code>/rate ID ±N</code>")
            return
        target, delta_str = parts[1], parts[2]
        if not target.isdigit() or not delta_str.startswith(("+", "-")) or not delta_str[1:].isdigit():
            _send_msg(chat_id, "❌ Формат: <code>/rate ID ±N</code>")
            return
        delta = int(delta_str)
        new_rating = change_rating(target, delta)
        stars = "⭐" * new_rating + "☆" * (10 - new_rating)
        add_log("RATE", user_id, f"{target} {delta_str} → {new_rating}")
        _send_msg(chat_id, f"✅ Рейтинг <code>{target}</code>:\n\n{stars} ({new_rating}/10)")
        return

    if text.startswith("/check "):
        target = text.split("/check ", 1)[1].strip()
        if not target.isdigit():
            _send_msg(chat_id, "❌ ID должен быть числом.")
            return
        banned = "🚫 В ЧС" if is_banned(target) else "✅ Не в ЧС"
        wl = "⭐ В БС" if is_whitelisted(target) else "— Не в БС"
        member = "✅ Подписан" if is_subscribed(target) else "❌ Не подписан"
        rating = get_rating(target)
        stars = "⭐" * rating
        admin = "👑 Админ" if target in ADMINS else "— Пользователь"
        _send_msg(chat_id, f"🔍 <b>Проверка <code>{target}</code>:</b>\n\n• Статус: {admin}\n• ЧС: {banned}\n• БС: {wl}\n• Подписка: {member}\n• Рейтинг: {stars} ({rating}/10)")
        return

    if text.startswith("/ban "):
        target = text.split("/ban ", 1)[1].strip()
        if not target.isdigit():
            _send_msg(chat_id, "❌ ID должен быть числом.")
            return
        if target == MAIN_ADMIN_ID or target in ADMINS:
            _send_msg(chat_id, "❌ Нельзя забанить админа!")
            return
        if ban_user(target):
            inc_stat("stats_banned")
            add_log("BAN", user_id, target)
            _send_msg(chat_id, f"🚫 <code>{target}</code> забанен.")
        else:
            _send_msg(chat_id, f"⚠️ Уже в ЧС.")
        return

    if text.startswith("/unban "):
        target = text.split("/unban ", 1)[1].strip()
        if not target.isdigit():
            _send_msg(chat_id, "❌ ID должен быть числом.")
            return
        if unban_user(target):
            add_log("UNBAN", user_id, target)
            _send_msg(chat_id, f"✅ <code>{target}</code> разбанен.")
        else:
            _send_msg(chat_id, f"⚠️ Не найден в ЧС.")
        return

    if text == "/banlist":
        bans = get_banlist()
        if not bans:
            _send_msg(chat_id, "✅ ЧС пуст.")
        else:
            ban_list = "\n".join([f"• <code>{b}</code>" for b in bans[:20]])
            _send_msg(chat_id, f"🚫 <b>ЧС ({len(bans)}):</b>\n\n{ban_list}")
        return

    if text.startswith("/add_wl "):
        target = text.split("/add_wl ", 1)[1].strip()
        if not target.isdigit():
            _send_msg(chat_id, "❌ ID должен быть числом.")
            return
        if add_to_whitelist(target):
            add_log("ADD_WL", user_id, target)
            _send_msg(chat_id, f"⭐ <code>{target}</code> в БС.")
        else:
            _send_msg(chat_id, f"⚠️ Уже в БС.")
        return

    if text.startswith("/remove_wl "):
        target = text.split("/remove_wl ", 1)[1].strip()
        if not target.isdigit():
            _send_msg(chat_id, "❌ ID должен быть числом.")
            return
        if remove_from_whitelist(target):
            add_log("REMOVE_WL", user_id, target)
            _send_msg(chat_id, f"✅ <code>{target}</code> убран из БС.")
        else:
            _send_msg(chat_id, f"⚠️ Не найден в БС.")
        return

    if text == "/whitelist":
        wl = get_whitelist()
        if not wl:
            _send_msg(chat_id, "✅ БС пуст.")
        else:
            wl_list = "\n".join([f"• <code>{w}</code>" for w in wl[:20]])
            _send_msg(chat_id, f"⭐ <b>БС ({len(wl)}):</b>\n\n{wl_list}")
        return

    if text.startswith("/broadcast "):
        broadcast_text = text.split("/broadcast ", 1)[1].strip()
        wl = get_whitelist()
        if not wl:
            _send_msg(chat_id, "⚠️ БС пуст.")
            return
        sent = 0
        for member_id in wl:
            if _send_msg(member_id, f"📢 <b>Рассылка:</b>\n\n{broadcast_text}"):
                sent += 1
        add_log("BROADCAST", user_id, f"{sent}/{len(wl)}")
        _send_msg(chat_id, f"✅ Рассылка: {sent}/{len(wl)}")
        return

    if text == "/log":
        logs = get_logs()
        _send_msg(chat_id, f"📜 <b>Последние действия:</b>\n\n{logs}")
        return

    if text == "/list_admins":
        admin_list = "\n".join([f"• <code>{a}</code>" + (" 👑" if a == MAIN_ADMIN_ID else "") for a in ADMINS])
        _send_msg(chat_id, f"👥 <b>Админы:</b>\n\n{admin_list}")
        return


def _handle_user_message(msg):
    chat_id = msg["chat"]["id"]
    user_id = msg["from"]["id"]
    inc_stat("stats_total")
    
    user = msg.get("from", {})
    full_name = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip() or "Не указано"
    uname = user.get("username", "нет")
    dt = datetime.fromtimestamp(msg["date"], tz=TZ)
    
    msg_text = msg.get("text") or msg.get("caption") or ""
    msg_text_lower = msg_text.lower()
    media_type = get_media_type(msg)
    
    if not CHANNEL_ID: return
    
    has_trigger = any(trigger in msg_text_lower for trigger in TRIGGER_WORDS)
    in_whitelist = is_whitelisted(user_id)
    rating = get_rating(user_id)
    
    safe_name = escape(full_name)
    safe_uname = escape(uname)
    safe_text = escape(msg_text) if msg_text else ""
    
    should_auto = (in_whitelist or rating >= RATING_AUTO_THRESHOLD or AUTO_ACCEPT) and not has_trigger
    
    media_info = f"\n{get_media_emoji(media_type)}" if media_type else ""
    status_line = f"🏷 <b>Статус:</b> Подписчик | ⭐ Рейтинг: {rating}/10\n"
    
    if should_auto:
        copy_resp = requests.post(f"{API}/copyMessage", json={"chat_id": CHANNEL_ID, "from_chat_id": chat_id, "message_id": msg["message_id"]}, timeout=10)
        if copy_resp.status_code == 200:
            inc_stat("stats_approved")
            _notify_user(chat_id, "✅ <b>Ваше сообщение опубликовано!</b>\n\nСпасибо! 🎉\n\n" + (f"👉 <a href=\"https://t.me/{CHANNEL_USERNAME.lstrip('@')}\">Перейти в канал</a>" if CHANNEL_USERNAME else ""))
            reason = "⭐ БС" if in_whitelist else ("🔥 Рейтинг" if rating >= RATING_AUTO_THRESHOLD else "✅ Авто")
            admin_text = f"{reason}: Опубликовано.\n\n👤 {safe_name} (@{safe_uname}){media_info}\n💬 {safe_text}"
            for admin_id in ADMINS:
                _send_msg(admin_id, admin_text)
        else:
            _notify_user(chat_id, "⚠️ Ошибка публикации.")
    else:
        _notify_user(chat_id, "📨 <b>Ваше сообщение на модерации</b>\n\nМы уведомим вас о решении. ⏳")
        reason = " ⚠️ <i>(подозрительные слова)</i>" if has_trigger else ""
        admin_text = f"📨 <b>Новое сообщение!</b>{reason}{media_info}\n\n👤 <b>Автор:</b> {safe_name} (@{safe_uname})\n🆔 <b>ID:</b> <code>{user_id}</code>\n{status_line}📅 {dt.strftime('%d.%m.%Y %H:%M')}\n\n💬 {safe_text}"
        keyboard = {"inline_keyboard": [[{"text": "✅ Одобрить", "callback_data": f"approve:{chat_id}:{msg['message_id']}"}, {"text": "❌ Отклонить", "callback_data": f"reject:{chat_id}:{msg['message_id']}"}], [{"text": "🚫 Бан", "callback_data": f"ban:{user_id}"}, {"text": "⭐ БС", "callback_data": f"whitelist:{user_id}"}], [{"text": "👍 +1", "callback_data": f"rate_up:{user_id}"}, {"text": "👎 -1", "callback_data": f"rate_down:{user_id}"}]]}
        for admin_id in ADMINS:
            if media_type:
                send_media_to_admin(admin_id, msg, admin_text, keyboard)
            else:
                _send_msg(admin_id, admin_text, reply_markup=keyboard)


# ═══════════════════════════════════════════════════
#  КНОПКИ
# ═══════════════════════════════════════════════════
def _handle_callback(cb):
    data = cb["data"]
    cb_id = cb["id"]
    user_id = cb["from"]["id"]
    admin_msg = cb["message"]
    admin_chat = admin_msg["chat"]["id"]
    admin_mid = admin_msg["message_id"]

    if data == "check_sub":
        if is_subscribed(user_id):
            requests.post(f"{API}/answerCallbackQuery", json={"callback_query_id": cb_id, "text": "✅ Вы подписаны!", "show_alert": True})
        else:
            requests.post(f"{API}/answerCallbackQuery", json={"callback_query_id": cb_id, "text": "❌ Не подписаны!", "show_alert": True})
        return

    if data.startswith("ban:"):
        target_id = data.split(":")[1]
        if ban_user(target_id):
            inc_stat("stats_banned")
            add_log("BAN", user_id, target_id)
            status_text = f"\n\n🚫 <b>Автор забанен!</b>"
        else:
            status_text = f"\n\n⚠️ <b>Уже в ЧС.</b>"
        safe_original = escape(admin_msg.get("text") or admin_msg.get("caption") or "")
        requests.post(f"{API}/editMessageCaption" if get_media_type(admin_msg) else f"{API}/editMessageText", json={"chat_id": admin_chat, "message_id": admin_mid, "text" if not get_media_type(admin_msg) else "caption": safe_original + status_text, "parse_mode": "HTML"})
        requests.post(f"{API}/answerCallbackQuery", json={"callback_query_id": cb_id})
        return

    if data.startswith("whitelist:"):
        target_id = data.split(":")[1]
        if add_to_whitelist(target_id):
            add_log("ADD_WL", user_id, target_id)
            status_text = f"\n\n⭐ <b>Автор в БС!</b>"
        else:
            status_text = f"\n\n⚠️ <b>Уже в БС.</b>"
        safe_original = escape(admin_msg.get("text") or admin_msg.get("caption") or "")
        requests.post(f"{API}/editMessageCaption" if get_media_type(admin_msg) else f"{API}/editMessageText", json={"chat_id": admin_chat, "message_id": admin_mid, "text" if not get_media_type(admin_msg) else "caption": safe_original + status_text, "parse_mode": "HTML"})
        requests.post(f"{API}/answerCallbackQuery", json={"callback_query_id": cb_id})
        return

    if data.startswith("rate_up:") or data.startswith("rate_down:"):
        target_id = data.split(":")[1]
        delta = 1 if data.startswith("rate_up:") else -1
        new_rating = change_rating(target_id, delta)
        add_log("RATE", user_id, f"{target_id} {'+' if delta > 0 else ''}{delta} → {new_rating}")
        status_text = f"\n\n⭐ <b>Рейтинг: {new_rating}/10</b>"
        safe_original = escape(admin_msg.get("text") or admin_msg.get("caption") or "")
        requests.post(f"{API}/editMessageCaption" if get_media_type(admin_msg) else f"{API}/editMessageText", json={"chat_id": admin_chat, "message_id": admin_mid, "text" if not get_media_type(admin_msg) else "caption": safe_original + status_text, "parse_mode": "HTML"})
        requests.post(f"{API}/answerCallbackQuery", json={"callback_query_id": cb_id, "text": f"⭐ Рейтинг: {new_rating}/10"})
        return

    try:
        action, orig_chat, orig_mid = data.split(":")
    except Exception:
        requests.post(f"{API}/answerCallbackQuery", json={"callback_query_id": cb_id})
        return

    if action == "approve":
        copy_resp = requests.post(f"{API}/copyMessage", json={"chat_id": CHANNEL_ID, "from_chat_id": int(orig_chat), "message_id": int(orig_mid)}, timeout=10)
        if copy_resp.status_code == 200:
            inc_stat("stats_approved")
            change_rating(int(orig_chat), 1)
            status_text = "\n\n✅ <b>Опубликовано</b>"
            _notify_user(int(orig_chat), "✅ <b>Ваше сообщение опубликовано!</b>\n\nСпасибо! 🎉\n\n" + (f"👉 <a href=\"https://t.me/{CHANNEL_USERNAME.lstrip('@')}\">Перейти в канал</a>" if CHANNEL_USERNAME else ""))
            add_log("APPROVE", user_id, f"{orig_chat}:{orig_mid}")
        else:
            status_text = "\n\n⚠️ <b>Ошибка</b>"
    elif action == "reject":
        inc_stat("stats_rejected")
        change_rating(int(orig_chat), -1)
        status_text = "\n\n❌ <b>Отклонено</b>"
        _notify_user(int(orig_chat), "❌ <b>Ваше сообщение отклонено</b>\n\nПопробуйте другое! ✨")
        add_log("REJECT", user_id, f"{orig_chat}:{orig_mid}")
    else:
        return

    safe_original = escape(admin_msg.get("text") or admin_msg.get("caption") or "")
    requests.post(f"{API}/editMessageCaption" if get_media_type(admin_msg) else f"{API}/editMessageText", json={"chat_id": admin_chat, "message_id": admin_mid, "text" if not get_media_type(admin_msg) else "caption": safe_original + status_text, "parse_mode": "HTML"})
    requests.post(f"{API}/answerCallbackQuery", json={"callback_query_id": cb_id})