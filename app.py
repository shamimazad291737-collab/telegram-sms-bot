import os
import sqlite3
import requests
import html
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler

# Environment Variables
TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0")) if os.environ.get("ADMIN_ID") else 0
SUPPORT_USERNAME = os.environ.get("SUPPORT_USERNAME", "telegram")

BASE_URL = f"https://api.telegram.org/bot{TOKEN}/"

# Payment Details Configuration
BKASH_NUMBER = "01700000000 (Personal)"
NAGAD_NUMBER = "01700000000 (Personal)"
BINANCE_PAY_ID = "123456789"

# User states dictionary
user_states = {}

# Database Initialization
def init_db():
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            balance REAL DEFAULT 0.0,
            total_recharge REAL DEFAULT 0.0
        )
    ''')
    conn.commit()
    conn.close()

def get_user(user_id):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, username, balance, total_recharge FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row

def add_user(user_id, username):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (user_id, username))
    conn.commit()
    conn.close()

def update_balance(user_id, amount):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET balance = balance + ?, total_recharge = total_recharge + ? WHERE user_id = ?", (amount, amount, user_id))
    conn.commit()
    conn.close()

def send_message(chat_id, text, reply_markup=None):
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    requests.post(BASE_URL + "sendMessage", json=payload)

# Bot API 8.4 Styled Main Keyboard
def get_main_keyboard(is_admin=False):
    kb = [
        [
            {"text": "📱 GET NUMBER", "style": "primary"},
            {"text": "💳 DEPOSIT", "style": "success"}
        ],
        [
            {"text": "👤 PROFILE", "style": "primary"},
            {"text": "🎧 SUPPORT", "style": "primary"}
        ]
    ]
    if is_admin:
        kb.append([{"text": "⚙️ ADMIN PANEL", "style": "danger"}])
        
    return {"keyboard": kb, "resize_keyboard": True}

# Message Handling Logic
def handle_update(update):
    if "message" in update:
        msg = update["message"]
        chat_id = msg["chat"]["id"]
        user_id = msg["from"]["id"]
        username = msg["from"].get("username", "NoUsername")
        first_name = msg["from"].get("first_name", "User")
        text = msg.get("text", "")

        add_user(user_id, username)
        is_admin = (user_id == ADMIN_ID)

        # State Handlers for Input
        if user_id in user_states:
            state = user_states[user_id]
            
            # User Submitting Transaction Proof
            if state.startswith("WAITING_TRX_"):
                method = state.replace("WAITING_TRX_", "")
                admin_msg = (
                    f"📥 <b>New Deposit Request ({method})</b>\n\n"
                    f"👤 <b>User:</b> {html.escape(first_name)} (@{username})\n"
                    f"🆔 <b>User ID:</b> <code>{user_id}</code>\n"
                    f"📝 <b>Details Sent:</b>\n{html.escape(text)}\n\n"
                    f"💡 <i>যাচাই করে ব্যালেন্স দিতে ডায়ালগ ব্যবহার করুন:</i>\n"
                    f"<code>{user_id} AMOUNT</code>"
                )
                send_message(ADMIN_ID, admin_msg)
                send_message(chat_id, "✅ <b>আপনার ডিপোজিট রিকোয়েস্ট অ্যাডমিনের কাছে পাঠানো হয়েছে!</b>\nযাচাই করার পর খুব শীঘ্রই ব্যালেন্স যোগ করা হবে।")
                del user_states[user_id]
                return

            # Admin Balance Credit Handler
            elif state == "WAITING_ADD_BAL" and is_admin:
                try:
                    parts = text.split()
                    target_id = int(parts[0])
                    amount = float(parts[1])
                    update_balance(target_id, amount)
                    send_message(chat_id, f"✅ <b>সফলভাবে User ID {target_id}-এ {amount} টাকা যোগ করা হয়েছে।</b>")
                    send_message(target_id, f"🎉 <b>আপনার অ্যাকাউন্টে {amount} BDT যোগ করা হয়েছে!</b>")
                except Exception:
                    send_message(chat_id, "❌ <b>ভুল ফরম্যাট!</b> দয়া করে আবার লিখুন:\n<code>USER_ID AMOUNT</code>")
                del user_states[user_id]
                return

        # Commands & Keyboard Inputs
        if text == "/start":
            welcome_text = (
                f"👋 <tg-emoji emoji-id=\"528543839720966085\">🔥</tg-emoji> "
                f"<b>Welcome {html.escape(first_name)} !</b>\n\n"
                f"নিচের মেনু থেকে আপনার সার্ভিস নির্বাচন করুন:"
            )
            send_message(chat_id, welcome_text, reply_markup=get_main_keyboard(is_admin))

        elif text == "📱 GET NUMBER":
            markup = {
                "inline_keyboard": [
                    [{"text": "WhatsApp Rate", "callback_data": "get_num_wa", "style": "success"}],
                    [{"text": "Telegram Rate", "callback_data": "get_num_tg", "style": "primary"}],
                    [{"text": "Facebook Rate", "callback_data": "get_num_fb", "style": "danger"}]
                ]
            }
            send_message(chat_id, "<b>কোন সার্ভিসের জন্য নম্বর নিতে চান?</b>", reply_markup=markup)

        elif text == "💳 DEPOSIT":
            dep_text = "💳 <b>Deposit Options</b>\n\nআপনার সুবিধাজনক পেমেন্ট মেথডটি নির্বাচন করুন:"
            markup = {
                "inline_keyboard": [
                    [{"text": "💖 bKash", "callback_data": "dep_bkash", "style": "danger"}],
                    [{"text": "🟠 Nagad", "callback_data": "dep_nagad", "style": "primary"}],
                    [{"text": "🟡 Binance (Crypto)", "callback_data": "dep_binance", "style": "success"}]
                ]
            }
            send_message(chat_id, dep_text, reply_markup=markup)

        elif text == "👤 PROFILE":
            u_info = get_user(user_id)
            bal = u_info[2] if u_info else 0.0
            tot = u_info[3] if u_info else 0.0
            prof_text = (
                f"👤 <b>Your Profile Information</b>\n\n"
                f"🆔 <b>User ID:</b> <code>{user_id}</code>\n"
                f"👤 <b>Name:</b> {html.escape(first_name)}\n"
                f"💰 <b>Current Balance:</b> {bal} BDT\n"
                f"📊 <b>Total Recharge:</b> {tot} BDT"
            )
            send_message(chat_id, prof_text)

        elif text == "🎧 SUPPORT":
            sup_text = f"<b>যেকোনো সমস্যা বা সাহায্যের জন্য সাপোর্ট অ্যাডমিনকে মেসেজ দিন:</b>\n\n👉 @{SUPPORT_USERNAME}"
            send_message(chat_id, sup_text)

        elif text == "⚙️ ADMIN PANEL" and is_admin:
            markup = {
                "inline_keyboard": [
                    [{"text": "➕ Add Balance", "callback_data": "admin_add_bal", "style": "success"}],
                    [{"text": "⚙️ Change Rates", "callback_data": "admin_set_rates", "style": "primary"}]
                ]
            }
            send_message(chat_id, "<b>WELCOME TO ADMIN PANEL</b>\nনিচের অপশন নির্বাচন করুন:", reply_markup=markup)

    elif "callback_query" in update:
        cb = update["callback_query"]
        cb_id = cb["id"]
        chat_id = cb["message"]["chat"]["id"]
        user_id = cb["from"]["id"]
        data = cb.get("data", "")

        requests.post(BASE_URL + "answerCallbackQuery", data={"callback_query_id": cb_id})

        if data == "dep_bkash":
            user_states[user_id] = "WAITING_TRX_BKASH"
            msg = (
                f"💖 <b>bKash Personal Deposit</b>\n\n"
                f"নম্বর: <code>{BKASH_NUMBER}</code>\n\n"
                f"📌 <b>নিয়মাবলী:</b>\n"
                f"১. উপরের নম্বরে টাকা Send Money করুন।\n"
                f"২. টাকা পাঠানোর পর আপনার bKash নম্বর এবং <b>TrxID</b> এখানে মেসেজ পাঠোন।"
            )
            send_message(chat_id, msg)

        elif data == "dep_nagad":
            user_states[user_id] = "WAITING_TRX_NAGAD"
            msg = (
                f"🟠 <b>Nagad Personal Deposit</b>\n\n"
                f"নম্বর: <code>{NAGAD_NUMBER}</code>\n\n"
                f"📌 <b>নিয়মাবলী:</b>\n"
                f"১. উপরের নম্বরে টাকা Send Money করুন।\n"
                f"২. টাকা পাঠানোর পর আপনার Nagad নম্বর এবং <b>TrxID</b> এখানে মেসেজ পাঠোন।"
            )
            send_message(chat_id, msg)

        elif data == "dep_binance":
            user_states[user_id] = "WAITING_TRX_BINANCE"
            msg = (
                f"🟡 <b>Binance Pay Deposit</b>\n\n"
                f"Binance Pay ID: <code>{BINANCE_PAY_ID}</code>\n\n"
                f"📌 <b>নিয়মাবলী:</b>\n"
                f"১. উপরের Pay ID-তে USDT পাঠান।\n"
                f"২. পাঠানোর পর আপনার <b>Pay ID/Order ID</b> এবং কত USDT পাঠিয়েছেন তা মেসেজ লিখে পাঠান।"
            )
            send_message(chat_id, msg)

        elif data.startswith("get_num_"):
            service = data.replace("get_num_", "").upper()
            send_message(chat_id, f"📱 <b>{service} Number Allocated:</b>\n<code>+8801700000000</code>\n\n<i>Waiting for OTP...</i>")

        elif user_id == ADMIN_ID:
            if data == "admin_set_rates":
                markup = {
                    "inline_keyboard": [
                        [{"text": "WhatsApp Rate", "callback_data": "rate_set_wa", "style": "primary"}],
                        [{"text": "Telegram Rate", "callback_data": "rate_set_tg", "style": "primary"}],
                        [{"text": "Facebook Rate", "callback_data": "rate_set_fb", "style": "primary"}]
                    ]
                }
                send_message(chat_id, "⚙️ <b>কোন সার্ভিসের রেট পরিবর্তন করতে চান?</b>", reply_markup=markup)
            elif data == "admin_add_bal":
                user_states[user_id] = "WAITING_ADD_BAL"
                send_message(chat_id, "➕ <b>ইউজার আইডি ও পরিমাণ পাঠান:</b>\n\n<code>USER_ID AMOUNT</code>")

# Web Server for Render Web Service Port Binding
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

    # Thread for Render Port Binding
    threading.Thread(target=run_web_server, daemon=True).start()

    print("🚀 Bot is running with Bot API 8.4 & Multi-payment Support...")
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
            
