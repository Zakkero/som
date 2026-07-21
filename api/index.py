from http.server import BaseHTTPRequestHandler
import json
import os
import sys

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'Bot is alive! Send me a message in Telegram.')

    def do_POST(self):
        try:
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length)
            
            if not body:
                self._respond(200)
                return

            data = json.loads(body)
            
            if 'message' in data:
                chat_id = data['message']['chat']['id']
                user_id = data['message']['from']['id']
                
                print(f"✅ SUCCESS: Received message from user {user_id} in chat {chat_id}", file=sys.stderr)
                
                token = os.environ.get("BOT_TOKEN", "MISSING")
                admin = os.environ.get("ADMIN_ID", "MISSING")
                
                token_preview = token[:15] + "..." if token != "MISSING" else "NONE"
                print(f"🔍 DEBUG VARS: Token={token_preview}, Admin={admin}", file=sys.stderr)

            self._respond(200)
            
        except Exception as e:
            print(f"❌ PYTHON EXCEPTION: {str(e)}", file=sys.stderr)
            self._respond(200)

    def _respond(self, code):
        self.send_response(code)
        self.end_headers()
        self.wfile.write(b'OK')

    def log_message(self, format, *args):
        pass