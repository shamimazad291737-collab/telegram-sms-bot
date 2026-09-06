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
BINANCE_PAY_ID = "123456789"
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
    return requests.post(BASE_URL + "sendMessage", json=payload).json()

def edit_message(chat_id, message_id, text, reply_markup=None):
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "HTML"
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    requests.post(BASE_URL + "editMessageText", json=payload)

def send_photo_to_admin(chat_id, photo_file_id, caption, reply_markup=None):
    payload = {
        "chat_id": chat_id,
        "photo": photo_file_id,
        "caption": caption,
        "parse_mode": "HTML"
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    requests.post(BASE_URL + "sendPhoto", json=payload)

# Keyboard Builder
def get_main_keyboard(is_admin=False):
    kb = [
        [
            {"text": "🛒 BUY NUMBER", "style": "primary"},
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

# Cancel Button Generator
def get_cancel_inline_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "❌ Cancel", "callback_data": "action_cancel", "style": "danger"}]
        ]
    }

# Core Update Logic
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

        # Admin File Uploading for Stock
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

        # Input State Handling
        if user_id in user_states:
            state_data = user_states[user_id]
            
            # Step 1: Receiving TrxID / Order ID
            if isinstance(state_data, str) and state_data.startswith("WAITING_TRX_"):
                method = state_data.replace("WAITING_TRX_", "")
                user_states[user_id] = {
                    "step": "WAITING_SCREENSHOT",
                    "method": method,
                    "trx_id": text
                }
                send_message(chat_id, "📸 <b>ধন্যবাদ! এবার পেমেন্টের একটি স্পষ্ট স্ক্রিনশট (Photo) পাঠান:</b>", reply_markup=get_cancel_inline_keyboard())
                return

            # Step 2: Receiving Screenshot
            elif isinstance(state_data, dict) and state_data.get("step") == "WAITING_SCREENSHOT":
                if "photo" in msg:
                    photo_file_id = msg["photo"][-1]["file_id"]
                    method = state_data["method"]
                    trx_id = state_data["trx_id"]

                    admin_markup = {
                        "inline_keyboard": [
                            [
                                {"text": "✅ Approve", "callback_data": f"dep_app_{user_id}", "style": "success"},
                                {"text": "❌ Reject", "callback_data": f"dep_rej_{user_id}", "style": "danger"}
                            ]
                        ]
                    }
                    admin_caption = (
                        f"📥 <b>New Deposit Request ({method})</b>\n\n"
                        f"👤 <b>User:</b> {html.escape(first_name)} (@{username})\n"
                        f"🆔 <b>User ID:</b> <code>{user_id}</code>\n"
                        f"🧾 <b>TrxID / Order ID:</b> <code>{html.escape(trx_id)}</code>\n\n"
                        f"যাচাই করে Approve বা Reject করুন:"
                    )
                    
                    send_photo_to_admin(ADMIN_ID, photo_file_id, admin_caption, reply_markup=admin_markup)
                    send_message(chat_id, "✅ <b>আপনার তথ্য ও স্ক্রিনশট অ্যাডমিনের কাছে পাঠানো হয়েছে!</b>\nযাচাই করার পর অ্যাকাউন্টে ব্যালেন্স যোগ করা হবে।", reply_markup=get_main_keyboard(is_admin))
                    del user_states[user_id]
                    return
                else:
                    send_message(chat_id, "❌ <b>অনুগ্রহ করে পেমেন্টের একটি ছবি/স্ক্রিনশট পাঠান।</b>", reply_markup=get_cancel_inline_keyboard())
                    return

            # Admin Inputting Amount
            elif isinstance(state_data, str) and state_data.startswith("ADMIN_APPROVE_AMOUNT_"):
                target_user = int(state_data.replace("ADMIN_APPROVE_AMOUNT_", ""))
                try:
                    amount = float(text)
                    update_balance(target_user, amount)
                    send_message(chat_id, f"✅ <b>User ID {target_user}-কে ${amount} ব্যালেন্স যোগ করা হয়েছে।</b>")
                    send_message(target_user, f"🎉 <b>আপনার ডিপোজিট প্রসেস সফল হয়েছে! ${amount} অ্যাকাউন্টে যোগ করা হয়েছে।</b>")
                except Exception:
                    send_message(chat_id, "❌ <b>ভুল অ্যামাউন্ট!</b> কেবল সংখ্যা লিখুন। (যেমন: 10 বা 5.5)")
                del user_states[user_id]
                return

        # Main Reply Keyboards
        if text == "/start":
            welcome_text = f"👋 <b>Welcome {html.escape(first_name)}!</b>\n\nনিচের মেনু থেকে সার্ভিস সিলেক্ট করুন:"
            send_message(chat_id, welcome_text, reply_markup=get_main_keyboard(is_admin))

        elif text in ["🛒 BUY NUMBER", "📱 GET NUMBER"]:
            markup = {
                "inline_keyboard": [
                    [{"text": "🟢 WhatsApp Number", "callback_data": "menu_wa", "style": "success"}],
                    [{"text": "❌ Cancel", "callback_data": "action_cancel", "style": "danger"}]
                ]
            }
            send_message(chat_id, "<b>কোন প্ল্যাটফর্মের জন্য নম্বর নিতে চান?</b>", reply_markup=markup)

        elif text == "💳 DEPOSIT":
            dep_text = "💳 <b>Deposit Options</b>\n\nআপনার সুবিধাজনক পেমেন্ট মেথডটি বেছে নিন:"
            markup = {
                "inline_keyboard": [
                    [{"text": "💖 bKash", "callback_data": "dep_bkash", "style": "danger"}],
                    [{"text": "🟠 Nagad", "callback_data": "dep_nagad", "style": "primary"}],
                    [{"text": "🟡 Binance (Crypto)", "callback_data": "dep_binance", "style": "success"}],
                    [{"text": "❌ Cancel", "callback_data": "action_cancel", "style": "danger"}]
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
                "সরাসরি ফাইল পাঠোন।\n"
                "ফরম্যাট:\n<code>+1234567890, https://otp-link.com/check</code>"
            )
            send_message(chat_id, msg)

    elif "callback_query" in update:
        cb = update["callback_query"]
        cb_id = cb["id"]
        chat_id = cb["message"]["chat"]["id"]
        message_id = cb["message"]["message_id"]
        user_id = cb["from"]["id"]
        data = cb.get("data", "")

        requests.post(BASE_URL + "answerCallbackQuery", data={"callback_query_id": cb_id})

        # Global Action Cancel Event Handler
        if data == "action_cancel":
            if user_id in user_states:
                del user_states[user_id]
            edit_message(chat_id, message_id, "❌ <b>প্রক্রিয়াটি বাতিল করা হয়েছে!</b>\nনিচের মেনু থেকে নতুন সার্ভিস বেছে নিন।")
            return

        # Dynamic Single Popup Message Flow
        if data == "menu_wa":
            markup = {
                "inline_keyboard": [
                    [{"text": f"🇺🇸 Buy USA WhatsApp Number (${NUMBER_PRICE})", "callback_data": "confirm_buy_usa", "style": "danger"}],
                    [{"text": "❌ Cancel", "callback_data": "action_cancel", "style": "danger"}]
                ]
            }
            edit_message(chat_id, message_id, f"<b>WhatsApp Service Selected:</b>\n\nমূল্য: <b>${NUMBER_PRICE} / Number</b>", reply_markup=markup)

        elif data == "confirm_buy_usa":
            u_info = get_user(user_id)
            bal = u_info[2] if u_info else 0.0

            if bal < NUMBER_PRICE:
                markup = {
                    "inline_keyboard": [
                        [{"text": "💳 Recharge Balance", "callback_data": "dep_options_direct", "style": "success"}],
                        [{"text": "❌ Cancel", "callback_data": "action_cancel", "style": "danger"}]
                    ]
                }
                edit_message(chat_id, message_id, f"❌ <b>পর্যাপ্ত ব্যালেন্স নেই!</b>\nনম্বর কিনতে অন্তত ${NUMBER_PRICE} ব্যালেন্স লাগবে। Deposit সেকশন থেকে রিচার্জ করুন।", reply_markup=markup)
                return

            phone, link = pop_stock_item()
            if not phone:
                markup = {
                    "inline_keyboard": [
                        [{"text": "❌ Cancel", "callback_data": "action_cancel", "style": "danger"}]
                    ]
                }
                edit_message(chat_id, message_id, "⚠️ <b>দুঃখিত! বর্তমানে স্টক ফাঁকা রয়েছে।</b> কিছু সময় পর আবার চেষ্টা করুন।", reply_markup=markup)
                return

            deduct_balance(user_id, NUMBER_PRICE)
            save_active_order(user_id, phone, link)

            markup = {
                "inline_keyboard": [
                    [{"text": "🔄 Check OTP", "callback_data": f"chk_otp_{phone}", "style": "success"}],
                    [{"text": "🛒 Buy Another Number", "callback_data": "confirm_buy_usa", "style": "primary"}],
                    [{"text": "❌ Cancel", "callback_data": "action_cancel", "style": "danger"}]
                ]
            }
            res_text = (
                f"✅ <b>নম্বর বরাদ্দ করা হয়েছে!</b>\n\n"
                f"📱 <b>USA Number:</b> <code>{phone}</code>\n"
                f"💰 <b>ফি কাটা হয়েছে:</b> ${NUMBER_PRICE}\n\n"
                f"👉 নম্বরটি অ্যাপে ব্যবহার করার পর <b>Check OTP</b> বাটনে চাপ দিন।"
            )
            edit_message(chat_id, message_id, res_text, reply_markup=markup)

        elif data.startswith("chk_otp_"):
            phone = data.replace("chk_otp_", "")
            order = get_order_by_phone(phone)
            
            if order:
                link = order[2]
                try:
                    res = requests.get(link, timeout=10)
                    otp_text = res.text.strip()
                    if otp_text and "wait" not in otp_text.lower():
                        markup = {
                            "inline_keyboard": [
                                [{"text": "🛒 Buy Another Number", "callback_data": "confirm_buy_usa", "style": "success"}],
                                [{"text": "❌ Cancel", "callback_data": "action_cancel", "style": "danger"}]
                            ]
                        }
                        send_message(chat_id, f"📥 <b>আপনার OTP:</b> <code>{otp_text}</code>", reply_markup=markup)
                    else:
                        send_message(chat_id, "⌛ <b>OTP এখনও আসেনি!</b> অনুগ্রহ করে কিছুক্ষণ পর আবার Check OTP চাপুন।")
                except Exception:
                    send_message(chat_id, "⚠️ <b>OTP চেক করতে সমস্যা হয়েছে!</b> সার্ভার রিচ করা যাচ্ছে না।")

        # Deposit Selection Events
        elif data in ["dep_options_direct", "back_to_deposit"]:
            dep_text = "💳 <b>Deposit Options</b>\n\nআপনার সুবিধাজনক পেমেন্ট মেথডটি বেছে নিন:"
            markup = {
                "inline_keyboard": [
                    [{"text": "💖 bKash", "callback_data": "dep_bkash", "style": "danger"}],
                    [{"text": "🟠 Nagad", "callback_data": "dep_nagad", "style": "primary"}],
                    [{"text": "🟡 Binance (Crypto)", "callback_data": "dep_binance", "style": "success"}],
                    [{"text": "❌ Cancel", "callback_data": "action_cancel", "style": "danger"}]
                ]
            }
            edit_message(chat_id, message_id, dep_text, reply_markup=markup)

        elif data == "dep_bkash":
            user_states[user_id] = "WAITING_TRX_BKASH"
            edit_message(chat_id, message_id, f"💖 <b>bKash Send Money:</b> <code>{BKASH_NUMBER}</code>\n\nটাকা পাঠানোর পর প্রথমে আপনার <b>TrxID</b> এখানে লিখে পাঠান:", reply_markup=get_cancel_inline_keyboard())

        elif data == "dep_nagad":
            user_states[user_id] = "WAITING_TRX_NAGAD"
            edit_message(chat_id, message_id, f"🟠 <b>Nagad Send Money:</b> <code>{NAGAD_NUMBER}</code>\n\nটাকা পাঠানোর পর প্রথমে আপনার <b>TrxID</b> এখানে লিখে পাঠান:", reply_markup=get_cancel_inline_keyboard())

        elif data == "dep_binance":
            user_states[user_id] = "WAITING_TRX_BINANCE"
            edit_message(chat_id, message_id, f"🟡 <b>Binance Pay ID:</b> <code>{BINANCE_PAY_ID}</code>\n\nUSDT পাঠানোর পর আপনার <b>Binance Order ID</b> মেসেজ লিখে পাঠান:", reply_markup=get_cancel_inline_keyboard())

        # Admin Approval Handlers
        elif data.startswith("dep_app_"):
            target_user = int(data.replace("dep_app_", ""))
            user_states[user_id] = f"ADMIN_APPROVE_AMOUNT_{target_user}"
            send_message(chat_id, f"<b>User ID {target_user}-এর জন্য কত $ যোগ করতে চান লিখে পাঠান:</b>")

        elif data.startswith("dep_rej_"):
            target_user = int(data.replace("dep_rej_", ""))
            send_message(target_user, f"❌ <b>আপনার জমা দেওয়া ডিপোজিট প্রুফটি সঠিক নয়!</b>\nদয়া করে সঠিক তথ্য দিন বা সাপোর্ট অ্যাডমিনের সাথে কথা বলুন: @{SUPPORT_USERNAME}")
            send_message(chat_id, f"❌ <b>User ID {target_user}-এর ডিপোজিট বাতিল করা হয়েছে।</b>")

# Dummy Server Header
class DummyServer(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot Engine Live.")

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), DummyServer)
    server.serve_forever()

if __name__ == "__main__":
    init_db()
    threading.Thread(target=run_web_server, daemon=True).start()

    print("🚀 Bot Engine Online with Inline Cancel Buttons...")
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
