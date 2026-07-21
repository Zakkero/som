import json
import os

def handler(req, res):
    # 1. Обработка GET-запросов (просто проверка, что бот жив)
    if req.method == 'GET':
        res.status(200).send('Bot is alive! Send me a message in Telegram.')
        return

    # 2. Обработка POST-запросов от Telegram
    if req.method == 'POST':
        try:
            # Telegram присылает данные в req.body
            body = req.body
            if isinstance(body, str):
                data = json.loads(body)
            else:
                data = body

            # Если пришло сообщение
            if 'message' in data:
                chat_id = data['message']['chat']['id']
                user_id = data['message']['from']['id']
                
                # Записываем успешный приём в логи Vercel
                print(f"✅ SUCCESS: Received message from user {user_id} in chat {chat_id}")
                
                # Проверяем переменные окружения
                token = os.environ.get("BOT_TOKEN", "MISSING")
                admin = os.environ.get("ADMIN_ID", "MISSING")
                
                # Показываем в логах начало токена (для безопасности) и ID
                token_preview = token[:15] + "..." if token != "MISSING" else "NONE"
                print(f"🔍 DEBUG VARS: Token={token_preview}, Admin={admin}")

            # Всегда возвращаем 200 OK, чтобы Telegram не думал, что произошла ошибка
            res.status(200).send('OK')
            
        except Exception as e:
            # Если всё-таки произошла ошибка, мы запишем её в логи, но всё равно вернём 200
            print(f"❌ PYTHON EXCEPTION: {str(e)}")
            res.status(200).send('OK')