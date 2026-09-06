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

# Payment Configuration
BKASH_NUMBER = "01858582881 (Personal)"
NAGAD_NUMBER = "01858582881 (Personal)"
BINANCE_PAY_ID = "907194603"
NUMBER_PRICE = 0.10  # Price per USA Number in USD/BDT Equivalent

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
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS stock (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone_number TEXT,
            otp_link TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS active_orders (
            order_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            phone_number TEXT,
            otp_link TEXT
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

def deduct_balance(user_id, amount):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (amount, user_id))
    conn.commit()
    conn.close()

def add_stock_item(phone, link):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute("INSERT INTO stock (phone_number, otp_link) VALUES (?, ?)", (phone, link))
    conn.commit()
    conn.close()

def pop_stock_item():
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute("SELECT id, phone_number, otp_link FROM stock LIMIT 1")
    row = cursor.fetchone()
    if row:
        cursor.execute("DELETE FROM stock WHERE id = ?", (row[0],))
        conn.commit()
        conn.close()
        return row[1], row[2]
    conn.close()
    return None, None

def save_active_order(user_id, phone, link):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute("INSERT INTO active_orders (user_id, phone_number, otp_link) VALUES (?, ?, ?)", (user_id, phone, link))
    conn.commit()
    conn.close()

def get_order_by_phone(phone):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute("SELECT order_id, user_id, otp_link FROM active_orders WHERE phone_number = ? ORDER BY order_id DESC LIMIT 1", (phone,))
    row = cursor.fetchone()
    conn.close()
    return row

def send_message(chat_id, text, reply_markup=None):
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    requests.post(BASE_URL + "sendMessage", json=payload)

# Keyboard Builder
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

# Core Logic
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

        # Admin File / Stock Handler
        if is_admin and "document" in msg:
            doc = msg["document"]
            file_id = doc["file_id"]
            file_info = requests.get(BASE_URL + f"getFile?file_id={file_id}").json()
            if file_info.get("ok"):
                file_path = file_info["result"]["file_path"]
                content = requests.get(f"https://api.telegram.org/file/bot{TOKEN}/{file_path}").text
                
                count = 0
                for line in content.splitlines():
                    if "," in line or " " in line:
                        parts = line.replace(",", " ").split()
                        if len(parts) >= 2:
                            add_stock_item(parts[0].strip(), parts[1].strip())
                            count += 1
                send_message(chat_id, f"✅ <b>সফলভাবে {count} টি নম্বর স্টকে আপলোড করা হয়েছে!</b>")
                return

        # Input States
        if user_id in user_states:
            state = user_states[user_id]
            
            # User Sending Deposit Trx/Proof
            if state.startswith("WAITING_TRX_"):
                method = state.replace("WAITING_TRX_", "")
                
                # Notification for Admin with Approve/Reject Buttons
                admin_markup = {
                    "inline_keyboard": [
                        [
                            {"text": "✅ Approve", "callback_data": f"dep_app_{user_id}", "style": "success"},
                            {"text": "❌ Reject", "callback_data": f"dep_rej_{user_id}", "style": "danger"}
                        ]
                    ]
                }
                admin_msg = (
                    f"📥 <b>New Deposit Request ({method})</b>\n\n"
                    f"👤 <b>User:</b> {html.escape(first_name)} (@{username})\n"
                    f"🆔 <b>User ID:</b> <code>{user_id}</code>\n"
                    f"📝 <b>Sent Details:</b>\n{html.escape(text)}\n\n"
                    f"স্বীকৃতি বা বাতিলের জন্য নিচের বাটনে চাপ দিন:"
                )
                send_message(ADMIN_ID, admin_msg, reply_markup=admin_markup)
                send_message(chat_id, "✅ <b>আপনার তথ্য অ্যাডমিনের কাছে পাঠানো হয়েছে!</b>\nযাচাই করার পর আপনার রিকোয়েস্ট প্রসেস করা হবে।")
                del user_states[user_id]
                return

            elif state.startswith("ADMIN_APPROVE_AMOUNT_"):
                target_user = int(state.replace("ADMIN_APPROVE_AMOUNT_", ""))
                try:
                    amount = float(text)
                    update_balance(target_user, amount)
                    send_message(chat_id, f"✅ <b>User ID {target_user}-কে {amount} BDT ব্যালেন্স দেওয়া হয়েছে।</b>")
                    send_message(target_user, f"🎉 <b>আপনার ডিপোজিট সফল হয়েছে! {amount} BDT অ্যাকাউন্টে যোগ করা হয়েছে।</b>")
                except Exception:
                    send_message(chat_id, "❌ <b>ভুল ইনপুট!</b> কেবল সংখ্যা লিখুন।")
                del user_states[user_id]
                return

        # Regular Menu Inputs
        if text == "/start":
            welcome_text = f"👋 <b>Welcome {html.escape(first_name)}!</b>\nনিচের মেনু থেকে আপনার সার্ভিস নির্বাচন করুন:"
            send_message(chat_id, welcome_text, reply_markup=get_main_keyboard(is_admin))

        elif text == "📱 GET NUMBER":
            markup = {
                "inline_keyboard": [
                    [{"text": "🛒 BUY NUMBER", "callback_data": "menu_buy_number", "style": "primary"}]
                ]
            }
            send_message(chat_id, "<b>নিচের বাটন চেপে নম্বর সেকশনে যান:</b>", reply_markup=markup)

        elif text == "💳 DEPOSIT":
            dep_text = "💳 <b>Deposit Options</b>\n\nআপনার পেমেন্ট মেথডটি বেছে নিন:"
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
                f"💰 <b>Current Balance:</b> ${bal:.2f}\n"
                f"📊 <b>Total Recharge:</b> ${tot:.2f}"
            )
            send_message(chat_id, prof_text)

        elif text == "🎧 SUPPORT":
            send_message(chat_id, f"<b>যেকোনো সাহায্যে যোগাযোগ করুন:</b>\n👉 @{SUPPORT_USERNAME}")

        elif text == "⚙️ ADMIN PANEL" and is_admin:
            msg = (
                "<b>⚙️ ADMIN PANEL</b>\n\n"
                "📂 <b>নম্বর ও লিংক আপলোড করতে:</b>\n"
                "সরাসরি একটি `.txt` বা `.csv` ফাইল পাঠান।\n"
                "ফাইল ফরম্যাট:\n<code>+1234567890, https://otp-link.com/check</code>"
            )
            send_message(chat_id, msg)

    elif "callback_query" in update:
        cb = update["callback_query"]
        cb_id = cb["id"]
        chat_id = cb["message"]["chat"]["id"]
        user_id = cb["from"]["id"]
        data = cb.get("data", "")

        requests.post(BASE_URL + "answerCallbackQuery", data={"callback_query_id": cb_id})

        if data == "menu_buy_number":
            markup = {
                "inline_keyboard": [
                    [{"text": "🟢 WhatsApp Number", "callback_data": "buy_wa_num", "style": "success"}]
                ]
            }
            send_message(chat_id, "<b>কোন সোশ্যাল মিডিয়ার জন্য নম্বর নিতে চান?</b>", reply_markup=markup)

        elif data == "buy_wa_num":
            markup = {
                "inline_keyboard": [
                    [{"text": f"🇺🇸 Buy USA Number (${NUMBER_PRICE})", "callback_data": "confirm_buy_usa", "style": "danger"}]
                ]
            }
            send_message(chat_id, f"<b>WhatsApp Service Select করা হয়েছে:</b>\nমূল্য: <b>${NUMBER_PRICE} / Number</b>", reply_markup=markup)

        elif data == "confirm_buy_usa":
            u_info = get_user(user_id)
            bal = u_info[2] if u_info else 0.0

            if bal < NUMBER_PRICE:
                send_message(chat_id, f"❌ <b>পর্যাপ্ত ব্যালেন্স নেই!</b>\nনম্বর কিনতে অন্তত ${NUMBER_PRICE} ব্যালেন্স লাগবে। Deposit সেকশন থেকে রিচার্জ করুন।")
                return

            phone, link = pop_stock_item()
            if not phone:
                send_message(chat_id, "⚠️ <b>দুঃখিত! বর্তমানে পর্যাপ্ত স্টক নেই।</b> কিছুক্ষণ পর আবার চেষ্টা করুন।")
                return

            deduct_balance(user_id, NUMBER_PRICE)
            save_active_order(user_id, phone, link)

            # Buy Output Response with Check OTP Button
            markup = {
                "inline_keyboard": [
                    [{"text": "🔄 Check OTP", "callback_data": f"chk_otp_{phone}", "style": "success"}]
                ]
            }
            res_text = (
                f"✅ <b>নম্বর বরাদ্দ করা হয়েছে!</b>\n\n"
                f"📱 <b>USA Number:</b> <code>{phone}</code>\n"
                f"💰 <b>কানেক্ট করা ফি:</b> ${NUMBER_PRICE}\n\n"
                f"👉 অ্যাপে নম্বরটি বসিয়ে OTP পাঠান, এরপর নিচের <b>Check OTP</b> বাটনে চাপ দিন।"
            )
            send_message(chat_id, res_text, reply_markup=markup)

        elif data.startswith("chk_otp_"):
            phone = data.replace("chk_otp_", "")
            order = get_order_by_phone(phone)
            
            if order:
                link = order[2]
                try:
                    res = requests.get(link, timeout=10)
                    otp_text = res.text.strip()
                    if otp_text and "wait" not in otp_text.lower():
                        send_message(chat_id, f"📥 <b>আপনার OTP:</b> <code>{otp_text}</code>")
                    else:
                        send_message(chat_id, "⌛ <b>OTP এখনও আসেনি!</b> অনুগ্রহ করে কিছুক্ষণ পর আবার Check OTP চাপুন।")
                except Exception:
                    send_message(chat_id, "⚠️ <b>OTP চেক করতে সমস্যা হয়েছে!</b> লিংক সংযোগ করা সম্ভব হচ্ছে না।")

        # Deposit Trx Admin Action (Approve / Reject)
        elif data.startswith("dep_app_"):
            target_user = int(data.replace("dep_app_", ""))
            user_states[user_id] = f"ADMIN_APPROVE_AMOUNT_{target_user}"
            send_message(chat_id, f"<b>User ID {target_user}-এর জন্য কত টাকা যোগ করবেন তা লিখে পাঠান:</b>")

        elif data.startswith("dep_rej_"):
            target_user = int(data.replace("dep_rej_", ""))
            send_message(target_user, f"❌ <b>আপনার জমা দেওয়া ডিপোজিট তথ্য ভুল ছিল!</b>\nসঠিক তথ্য প্রদান করুন অথবা সাপোর্ট অ্যাডমিনের সাথে যোগাযোগ করুন: @{SUPPORT_USERNAME}")
            send_message(chat_id, f"❌ <b>User ID {target_user}-এর ডিপোজিট রিকোয়েস্ট বাতিল করা হয়েছে।</b>")

        # Deposit Channel Selections
        elif data == "dep_bkash":
            user_states[user_id] = "WAITING_TRX_BKASH"
            send_message(chat_id, f"💖 <b>bKash Send Money:</b> <code>{BKASH_NUMBER}</code>\n\nটাকা পাঠিয়ে TrxID এবং স্কিনশটের টেক্সট মেসেজ পাঠোন।")

        elif data == "dep_nagad":
            user_states[user_id] = "WAITING_TRX_NAGAD"
            send_message(chat_id, f"🟠 <b>Nagad Send Money:</b> <code>{NAGAD_NUMBER}</code>\n\nটাকা পাঠিয়ে TrxID এবং বিস্তারিত মেসেজ পাঠোন।")

        elif data == "dep_binance":
            user_states[user_id] = "WAITING_TRX_BINANCE"
            send_message(chat_id, f"🟡 <b>Binance Pay ID:</b> <code>{BINANCE_PAY_ID}</code>\n\nUSDT পাঠোনোর পর Pay ID ও ট্রানজাকশন মেসেজ পাঠোন।")

# Server Listener
class DummyServer(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot Service Running Correctly.")

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), DummyServer)
    server.serve_forever()

if __name__ == "__main__":
    init_db()
    threading.Thread(target=run_web_server, daemon=True).start()

    print("🚀 Bot Engine Online...")
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
                
