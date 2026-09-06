import os
import sys
import time
import json
import sqlite3
import requests
import threading
import html
from http.server import HTTPServer, BaseHTTPRequestHandler

# ==========================================
# Global Configuration & Settings
# ==========================================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "123456789"))
SUPPORT_USERNAME = os.environ.get("SUPPORT_USERNAME", "YourSupportUsername")

BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/"

user_states = {}

# ==========================================
# Database Handlers (SQLite)
# ==========================================
def init_db():
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            first_name TEXT,
            balance REAL DEFAULT 0.0
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('payment_details', 'Bkash/Nagad: 017XXXXXXXX\nBinance Pay ID: 12345678')")
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('rate_whatsapp', '0.50')")
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('rate_telegram', '0.60')")
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('rate_facebook', '0.30')")
    conn.commit()
    conn.close()

def get_setting(key):
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else ""

def set_setting(key, value):
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()

def add_user(user_id, first_name):
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO users (user_id, first_name, balance) VALUES (?, ?, 0.0)", (user_id, first_name))
    conn.commit()
    conn.close()

def get_user(user_id):
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, first_name, balance FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {"user_id": row[0], "first_name": row[1], "balance": row[2]}
    return None

def update_user_balance(user_id, amount):
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
    conn.commit()
    conn.close()

# ==========================================
# Telegram API Wrappers
# ==========================================
def send_message(chat_id, text, reply_markup=None, parse_mode="HTML"):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    try:
        return requests.post(BASE_URL + "sendMessage", data=payload).json()
    except Exception:
        return None

# ==========================================
# Keyboards & Menus
# ==========================================
def get_main_keyboard(is_admin=False):
    kb = [
        [{"text": "📱 GET NUMBER"}, {"text": "💳 DEPOSIT"}],
        [{"text": "👤 PROFILE"}, {"text": "🎧 SUPPORT"}]
    ]
    if is_admin:
        kb.append([{"text": "⚙️ ADMIN PANEL"}])
    return {"keyboard": kb, "resize_keyboard": True}

def get_admin_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "💳 Change Payment Details", "callback_data": "admin_set_payment"}],
            [{"text": "🏷️ Change Rates/Prices", "callback_data": "admin_set_rates"}],
            [{"text": "➕ Add User Balance", "callback_data": "admin_add_bal"}]
        ]
    }

# ==========================================
# Main Update Handler
# ==========================================
def handle_update(update):
    global user_states

    if "message" in update:
        msg = update["message"]
        chat_id = msg["chat"]["id"]
        user_id = msg["from"]["id"]
        first_name = msg["from"].get("first_name", "User")
        text = msg.get("text", "").strip()

        add_user(user_id, first_name)
        is_admin = (user_id == ADMIN_ID)

        if user_id in user_states:
            state = user_states[user_id]
            if state == "WAITING_PAYMENT_TEXT":
                set_setting("payment_details", text)
                del user_states[user_id]
                send_message(chat_id, "✅ <b>Payment Methods successfully updated!</b>")
                return
            elif state == "WAITING_WA_RATE":
                set_setting("rate_whatsapp", text)
                del user_states[user_id]
                send_message(chat_id, f"✅ <b>WhatsApp rate updated to: ${text}</b>")
                return
            elif state == "WAITING_TG_RATE":
                set_setting("rate_telegram", text)
                del user_states[user_id]
                send_message(chat_id, f"✅ <b>Telegram rate updated to: ${text}</b>")
                return
            elif state == "WAITING_FB_RATE":
                set_setting("rate_facebook", text)
                del user_states[user_id]
                send_message(chat_id, f"✅ <b>Facebook rate updated to: ${text}</b>")
                return
            elif state == "WAITING_ADD_BAL":
                try:
                    parts = text.split()
                    target_id = int(parts[0])
                    amt = float(parts[1])
                    update_user_balance(target_id, amt)
                    del user_states[user_id]
                    send_message(chat_id, f"✅ <b>User <code>{target_id}</code>-এর অ্যাকাউন্টে ${amt} যোগ করা হয়েছে।</b>")
                    send_message(target_id, f"🎉 <b>আপনার অ্যাকাউন্টে ${amt} জমা হয়েছে!</b>")
                except Exception:
                    send_message(chat_id, "❌ **ফরম্যাট ভুল!** উদাহরণ: `USER_ID AMOUNT`", parse_mode="Markdown")
                return

        if text.startswith("/start"):
            welcome_text = f"👋 <b>Welcome {html.escape(first_name)}!</b>\n\nনিচের মেনু থেকে আপনার সার্ভিস নির্বাচন করুন:"
            send_message(chat_id, welcome_text, reply_markup=get_main_keyboard(is_admin))

        elif text == "📱 GET NUMBER":
            u_data = get_user(user_id)
            wa_rate = get_setting("rate_whatsapp")
            tg_rate = get_setting("rate_telegram")
            fb_rate = get_setting("rate_facebook")

            if u_data and u_data["balance"] <= 0:
                send_message(chat_id, "⚠️ <b>পর্যাপ্ত ব্যালেন্স নেই!</b>\nনম্বর নেওয়ার জন্য প্রথমে ডিপোজিট করুন।")
            else:
                markup = {"inline_keyboard": [
                    [{"text": f"WhatsApp (${wa_rate})", "callback_data": "get_num_wa"}],
                    [{"text": f"Telegram (${tg_rate})", "callback_data": "get_num_tg"}],
                    [{"text": f"Facebook (${fb_rate})", "callback_data": "get_num_fb"}]
                ]}
                send_message(chat_id, "📲 <b>আপনার প্রয়োজনীয় সার্ভিস সিলেক্ট করুন:</b>", reply_markup=markup)

        elif text == "💳 DEPOSIT":
            pay_info = get_setting("payment_details")
            dep_text = f"💳 <b>DEPOSIT BALANCE</b>\n\n<b>পেমেন্ট ইনফরমেশন:</b>\n<code>{pay_info}</code>\n\nটাকা পাঠানোর পর Admin/Support-এ Transaction ID এবং স্ক্রিনশট পাঠান।"
            send_message(chat_id, dep_text)

        elif text == "👤 PROFILE":
            u_data = get_user(user_id)
            bal = u_data["balance"] if u_data else 0.0
            prof_text = f"👤 <b>USER PROFILE</b>\n━━━━━━━━━━━━━━━━━━━\n🆔 <b>ID:</b> <code>{user_id}</code>\n👤 <b>Name:</b> {html.escape(first_name)}\n💰 <b>Balance:</b> ${bal:.2f}\n━━━━━━━━━━━━━━━━━━━"
            send_message(chat_id, prof_text)

        elif text == "🎧 SUPPORT":
            markup = {"inline_keyboard": [[{"text": "💬 Contact Admin", "url": f"https://t.me/{SUPPORT_USERNAME}"}]]}
            send_message(chat_id, "🎧 <b>যেকোনো সাহায্য বা ডিপোজিটের জন্য অ্যাডমিনের সাথে যোগাযোগ করুন:</b>", reply_markup=markup)

        elif text == "⚙️ ADMIN PANEL" and is_admin:
            send_message(chat_id, "⚙️ <b>WELCOME TO ADMIN PANEL</b>\nনিচের অপশনগুলো থেকে পরিবর্তন করুন:", reply_markup=get_admin_keyboard())

    elif "callback_query" in update:
        cb = update["callback_query"]
        cb_id = cb["id"]
        chat_id = cb["message"]["chat"]["id"]
        user_id = cb["from"]["id"]
        data = cb.get("data", "")

        requests.post(BASE_URL + "answerCallbackQuery", data={"callback_query_id": cb_id})

        if data.startswith("get_num_"):
            service = data.replace("get_num_", "").upper()
            send_message(chat_id, f"📱 <b>{service} Number Allocated:</b>\n<code>+8801700000000</code>\n\n⌛ OTP-র জন্য অপেক্ষা করা হচ্ছে...")

        elif user_id == ADMIN_ID:
            if data == "admin_set_payment":
                user_states[user_id] = "WAITING_PAYMENT_TEXT"
                send_message(chat_id, "📝 <b>নতুন Payment Methods লেখে মেসেজ দিন:</b>")
            elif data == "admin_set_rates":
                markup = {"inline_keyboard": [
                    [{"text": "WhatsApp Rate", "callback_data": "rate_set_wa"}],
                    [{"text": "Telegram Rate", "callback_data": "rate_set_tg"}],
                    [{"text": "Facebook Rate", "callback_data": "rate_set_fb"}]
                ]}
                send_message(chat_id, "🏷️ <b>কোন সার্ভিসের রেট পরিবর্তন করতে চান?</b>", reply_markup=markup)
            elif data == "rate_set_wa":
                user_states[user_id] = "WAITING_WA_RATE"
                send_message(chat_id, "✏️ <b>WhatsApp এর নতুন দাম লিখুন:</b>")
            elif data == "rate_set_tg":
                user_states[user_id] = "WAITING_TG_RATE"
                send_message(chat_id, "✏️ <b>Telegram এর নতুন দাম লিখুন:</b>")
            elif data == "rate_set_fb":
                user_states[user_id] = "WAITING_FB_RATE"
                send_message(chat_id, "✏️ <b>Facebook এর নতুন দাম লিখুন:</b>")
            elif data == "admin_add_bal":
                user_states[user_id] = "WAITING_ADD_BAL"
                send_message(chat_id, "➕ <b>ইউজার আইডি ও পরিমাণ পাঠান:</b>\n<code>USER_ID AMOUNT</code>")

# ==========================================
# Web Server for Render Web Service Port Binding
# ==========================================
class DummyServer(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is active and running on Web Service!")

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), DummyServer)
    server.serve_forever()

if __name__ == "__main__":
    init_db()
    
    # Render Web Service-এর পোর্ট ওপেন রাখার জন্য থ্রেড চালু করা
    threading.Thread(target=run_web_server, daemon=True).start()
    
    print("🚀 Bot is running with Environment Variables...")
    offset = 0
    while True:
        try:
            res = requests.get(BASE_URL + "getUpdates", params={"offset": offset, "timeout": 20}, timeout=25).json()
            if res.get("ok"):
                for update in res.get("result", []):
                    offset = update["update_id"] + 1
                    threading.Thread(target=handle_update, args=(update,), daemon=True).start()
        except Exception:
            time.sleep(2)
