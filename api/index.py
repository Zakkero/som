import json
import os
import sys

class handler:
    def __init__(self, req, res):
        self.req = req
        self.res = res

    def GET(self):
        self.res.status(200)
        self.res.send("Bot is alive! Send me a message in Telegram.")

    def POST(self):
        try:
            # Читаем тело запроса от Telegram
            body = self.req.body
            if isinstance(body, bytes):
                body = body.decode('utf-8')
            
            if not body:
                self.res.status(200)
                self.res.send("OK")
                return

            data = json.loads(body)
            
            # Если пришло сообщение, логируем его и переменные
            if "message" in data:
                chat_id = data["message"]["chat"]["id"]
                user_id = data["message"]["from"]["id"]
                
                # Записываем успешный приём в логи Vercel
                print(f"✅ SUCCESS: Received message from user {user_id} in chat {chat_id}", file=sys.stderr)
                
                # Проверяем, видит ли Vercel наши переменные
                token = os.environ.get("BOT_TOKEN", "MISSING")
                admin = os.environ.get("ADMIN_ID", "MISSING")
                
                # Показываем в логах начало токена (для безопасности не показываем весь) и ID
                token_preview = token[:15] + "..." if token != "MISSING" else "NONE"
                print(f"🔍 DEBUG VARS: Token={token_preview}, Admin={admin}", file=sys.stderr)

            # Всегда возвращаем 200 OK, чтобы Telegram не думал, что произошла ошибка
            self.res.status(200)
            self.res.send("OK")
            
        except Exception as e:
            # Если всё-таки произошла ошибка, мы запишем её в логи, но всё равно вернём 200
            print(f"❌ PYTHON EXCEPTION: {str(e)}", file=sys.stderr)
            self.res.status(200)
            self.res.send("OK")