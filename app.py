import os
import sqlite3
import requests
import html
import threading
import time
import re
from flask import Flask

# Render Port Binding for Health Checks
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running on Render!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# Environment Variables
TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0")) if os.environ.get("ADMIN_ID") else 0
SUPPORT_USERNAME = os.environ.get("SUPPORT_USERNAME", "telegram")
OTP_GROUP_ID = os.environ.get("OTP_GROUP_ID", "")

BASE_URL = f"https://api.telegram.org/bot{TOKEN}/"

BDT_PER_USD = 120.0 
BKASH_NUMBER = "01858582881 (Personal)"
NAGAD_NUMBER = "01858582881 (Personal)"
BINANCE_PAY_ID = "123456789"

user_states = {}

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
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('number_price', '0.10')")
    conn.commit()
    conn.close()

def get_number_price():
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = 'number_price'")
    row = cursor.fetchone()
    conn.close()
    return float(row[0]) if row else 0.10

def set_number_price(new_price):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute("UPDATE settings SET value = ? WHERE key = 'number_price'", (str(new_price),))
    conn.commit()
    conn.close()

def get_user(user_id):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, username, balance, total_recharge FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row

def update_balance(user_id, amount):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO users (user_id, balance, total_recharge) VALUES (?, 0.0, 0.0)", (user_id,))
    cursor.execute("UPDATE users SET balance = balance + ?, total_recharge = total_recharge + ? WHERE user_id = ?", (amount, amount, user_id))
    conn.commit()
    conn.close()

def deduct_balance(user_id, amount):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (amount, user_id))
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

def add_stock_item(phone, link):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute("INSERT INTO stock (phone_number, otp_link) VALUES (?, ?)", (phone, link))
    conn.commit()
    conn.close()

def get_all_users():
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users")
    rows = cursor.fetchall()
    conn.close()
    return [r[0] for r in rows]

def get_all_stock():
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute("SELECT id, phone_number, otp_link FROM stock")
    rows = cursor.fetchall()
    conn.close()
    return rows

def clear_all_stock():
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute("DELETE FROM stock")
    conn.commit()
    conn.close()

# Telegram Standard Sender for Render
def send_message(chat_id, text, reply_markup=None):
    payload = {
        "chat_id": chat_id, 
        "text": text, 
        "parse_mode": "HTML"
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
        
    headers = {"Content-Type": "application/json"}
    try:
        res = requests.post(BASE_URL + "sendMessage", json=payload, headers=headers, timeout=10)
        return res.json()
    except Exception as e:
        print(f"Error sending message: {e}")
        return {}

def edit_message(chat_id, message_id, text, reply_markup=None):
    payload = {
        "chat_id": chat_id, 
        "message_id": message_id, 
        "text": text, 
        "parse_mode": "HTML"
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
        
    headers = {"Content-Type": "application/json"}
    try:
        res = requests.post(BASE_URL + "editMessageText", json=payload, headers=headers, timeout=10)
        return res.json()
    except Exception as e:
        print(f"Error editing message: {e}")
        return {}

def send_photo_to_admin(admin_id, photo_file_id, caption, reply_markup=None):
    payload = {
        "chat_id": admin_id, 
        "photo": photo_file_id, 
        "caption": caption, 
        "parse_mode": "HTML"
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
        
    headers = {"Content-Type": "application/json"}
    try:
        requests.post(BASE_URL + "sendPhoto", json=payload, headers=headers, timeout=10)
    except Exception as e:
        print(f"Error sending photo to admin: {e}")

def get_main_keyboard(is_admin=False):
    kb = [
        ["🛒 BUY NUMBER", "💳 DEPOSIT"],
        ["👤 PROFILE", "🎧 SUPPORT"]
    ]
    if is_admin:
        kb.append(["⚙️ ADMIN PANEL"])
    return {"keyboard": [[{"text": b} for b in row] for row in kb], "resize_keyboard": True}

def get_back_keyboard():
    return {"keyboard": [[{"text": "⬅️ Back"}]], "resize_keyboard": True}

# Main Handler
def handle_update(update):
    if "message" in update:
        msg = update["message"]
        chat_id = msg["chat"]["id"]
        user_id = msg["from"]["id"]
        text = msg.get("text", "")
        first_name = msg["from"].get("first_name", "User")
        username = msg["from"].get("username", "NoUsername")
        is_admin = (user_id == ADMIN_ID)

        conn = sqlite3.connect('bot_database.db')
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO users (user_id, username, balance, total_recharge) VALUES (?, ?, 0.0, 0.0)", (user_id, username))
        cursor.execute("UPDATE users SET username = ? WHERE user_id = ?", (username, user_id))
        conn.commit()
        conn.close()

        current_price = get_number_price()

        if text in ["⬅️ Back", "🔙 Back"]:
            if user_id in user_states:
                del user_states[user_id]
            send_message(chat_id, "<b>মূল মেনুতে ফিরে আসা হয়েছে:</b>", reply_markup=get_main_keyboard(is_admin))
            return

        if user_id in user_states:
            state_data = user_states[user_id]
            
            if isinstance(state_data, dict) and state_data.get("step") == "WAITING_AMOUNT":
                method = state_data["method"]
                try:
                    amount = float(text)
                    if amount <= 0:
                        send_message(chat_id, "❌ <b>সঠিক পরিমাণ উল্লেখ করুন!</b>")
                        return
                    
                    user_states[user_id] = {
                        "step": "WAITING_TRX",
                        "method": method,
                        "amount": amount
                    }

                    if method == "BKASH":
                        msg_text = f"💖 <b>bKash Send Money</b>\n\n💵 <b>পরিমাণ:</b> ৳{amount:.2f} BDT\n📱 <b>নম্বর:</b> <code>{BKASH_NUMBER}</code>\n\nটাকা পাঠিয়ে <b>TrxID</b> দিন:"
                    elif method == "NAGAD":
                        msg_text = f"🟠 <b>Nagad Send Money</b>\n\n💵 <b>পরিমাণ:</b> ৳{amount:.2f} BDT\n📱 <b>নম্বর:</b> <code>{NAGAD_NUMBER}</code>\n\nটাকা পাঠিয়ে <b>TrxID</b> দিন:"
                    elif method == "BINANCE":
                        msg_text = f"🟡 <b>Binance Pay</b>\n\n💵 <b>পরিমাণ:</b> {amount:.2f} USDT\n🆔 <b>Pay ID:</b> <code>{BINANCE_PAY_ID}</code>\n\nUSDT পাঠিয়ে <b>Order ID / TrxID</b> দিন:"

                    send_message(chat_id, msg_text, reply_markup=get_back_keyboard())
                    return
                except ValueError:
                    send_message(chat_id, "❌ <b>ভুল ইনপুট!</b> কেবল সংখ্যা লিখুন।")
                    return

            elif isinstance(state_data, dict) and state_data.get("step") == "WAITING_TRX":
                method = state_data["method"]
                amount = state_data["amount"]
                
                user_states[user_id] = {
                    "step": "WAITING_SCREENSHOT",
                    "method": method,
                    "amount": amount,
                    "trx_id": text
                }
                send_message(chat_id, "📸 <b>পেমেন্টের একটি স্পষ্ট স্ক্রিনশট পাঠান:</b>", reply_markup=get_back_keyboard())
                return

            elif isinstance(state_data, dict) and state_data.get("step") == "WAITING_SCREENSHOT":
                if "photo" in msg:
                    photo_file_id = msg["photo"][-1]["file_id"]
                    method = state_data["method"]
                    amount = state_data["amount"]
                    trx_id = state_data["trx_id"]

                    if method == "BINANCE":
                        converted_usd = amount
                        amount_info = f"{amount:.2f} USDT"
                    else:
                        converted_usd = round(amount / BDT_PER_USD, 2)
                        amount_info = f"৳{amount:.2f} BDT (${converted_usd:.2f} USD)"

                    usd_str_clean = f"{converted_usd:.2f}"
                    
                    admin_markup = {
                        "inline_keyboard": [
                            [
                                {"text": f"✅ Auto Approve (${converted_usd:.2f})", "callback_data": f"appusd_{user_id}_{usd_str_clean}", "style": "success"},
                                {"text": "✏️ Custom", "callback_data": f"dep_app_{user_id}", "style": "primary"}
                            ],
                            [
                                {"text": "❌ Reject", "callback_data": f"dep_rej_{user_id}", "style": "danger"}
                            ]
                        ]
                    }
                    admin_caption = (
                        f"📥 <b>New Deposit ({method})</b>\n\n"
                        f"👤 <b>User:</b> {html.escape(first_name)} (@{username})\n"
                        f"🆔 <b>ID:</b> <code>{user_id}</code>\n"
                        f"💰 <b>Amount:</b> {amount_info}\n"
                        f"🧾 <b>TrxID:</b> <code>{html.escape(trx_id)}</code>"
                    )
                    
                    send_photo_to_admin(ADMIN_ID, photo_file_id, admin_caption, reply_markup=admin_markup)
                    send_message(chat_id, "✅ <b>আপনার জমা দেওয়া তথ্য অ্যাডমিনের কাছে গেছে।</b>", reply_markup=get_main_keyboard(is_admin))
                    del user_states[user_id]
                    return
                else:
                    send_message(chat_id, "❌ <b>অনুরোধ করে ছবি/স্ক্রিনশট দিন।</b>", reply_markup=get_back_keyboard())
                    return

            elif is_admin and state_data == "ADMIN_UPLOAD_FILE":
                if "document" in msg:
                    doc = msg["document"]
                    file_id = doc["file_id"]
                    file_info = requests.get(BASE_URL + f"getFile?file_id={file_id}").json()
                    if file_info.get("ok"):
                        file_path = file_info["result"]["file_path"]
                        content = requests.get(f"https://api.telegram.org/file/bot{TOKEN}/{file_path}").text
                        
                        count = 0
                        for line in content.splitlines():
                            line = line.strip()
                            if line.startswith("+") and ("http://" in line or "https://" in line):
                                parts = line.replace(",", " ").split()
                                if len(parts) >= 2:
                                    add_stock_item(parts[0].strip(), parts[1].strip())
                                    count += 1
                        
                        send_message(chat_id, f"✅ <b>{count} টি নম্বর স্টকে আপলোড করা হয়েছে!</b>", reply_markup=get_main_keyboard(is_admin))
                        del user_states[user_id]
                        return
                else:
# Main Handler
def handle_update(update):
    if "message" in update:
        msg = update["message"]
        chat_id = msg["chat"]["id"]
        user_id = msg["from"]["id"]
        text = msg.get("text", "")
        first_name = msg["from"].get("first_name", "User")
        username = msg["from"].get("username", "NoUsername")
        is_admin = (user_id == ADMIN_ID)

        conn = sqlite3.connect('bot_database.db')
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO users (user_id, username, balance, total_recharge) VALUES (?, ?, 0.0, 0.0)", (user_id, username))
        cursor.execute("UPDATE users SET username = ? WHERE user_id = ?", (username, user_id))
        conn.commit()
        conn.close()

        current_price = get_number_price()

        if text in ["⬅️ Back", "🔙 Back"]:
            if user_id in user_states:
                del user_states[user_id]
            send_message(chat_id, "<b>মূল মেনুতে ফিরে আসা হয়েছে:</b>", reply_markup=get_main_keyboard(is_admin))
            return

        if user_id in user_states:
            state_data = user_states[user_id]
            
            if isinstance(state_data, dict) and state_data.get("step") == "WAITING_AMOUNT":
                method = state_data["method"]
                try:
                    amount = float(text)
                    if amount <= 0:
                        send_message(chat_id, "❌ <b>সঠিক পরিমাণ উল্লেখ করুন!</b>")
                        return
                    
                    user_states[user_id] = {
                        "step": "WAITING_TRX",
                        "method": method,
                        "amount": amount
                    }

                    if method == "BKASH":
                        msg_text = f"💖 <b>bKash Send Money</b>\n\n💵 <b>পরিমাণ:</b> ৳{amount:.2f} BDT\n📱 <b>নম্বর:</b> <code>{BKASH_NUMBER}</code>\n\nটাকা পাঠিয়ে <b>TrxID</b> দিন:"
                    elif method == "NAGAD":
                        msg_text = f"🟠 <b>Nagad Send Money</b>\n\n💵 <b>পরিমাণ:</b> ৳{amount:.2f} BDT\n📱 <b>নম্বর:</b> <code>{NAGAD_NUMBER}</code>\n\nটাকা পাঠিয়ে <b>TrxID</b> দিন:"
                    elif method == "BINANCE":
                        msg_text = f"🟡 <b>Binance Pay</b>\n\n💵 <b>পরিমাণ:</b> {amount:.2f} USDT\n🆔 <b>Pay ID:</b> <code>{BINANCE_PAY_ID}</code>\n\nUSDT পাঠিয়ে <b>Order ID / TrxID</b> দিন:"

                    send_message(chat_id, msg_text, reply_markup=get_back_keyboard())
                    return
                except ValueError:
                    send_message(chat_id, "❌ <b>ভুল ইনপুট!</b> কেবল সংখ্যা লিখুন।")
                    return

            elif isinstance(state_data, dict) and state_data.get("step") == "WAITING_TRX":
                method = state_data["method"]
                amount = state_data["amount"]
                
                user_states[user_id] = {
                    "step": "WAITING_SCREENSHOT",
                    "method": method,
                    "amount": amount,
                    "trx_id": text
                }
                send_message(chat_id, "📸 <b>পেমেন্টের একটি স্পষ্ট স্ক্রিনশট পাঠান:</b>", reply_markup=get_back_keyboard())
                return

            elif isinstance(state_data, dict) and state_data.get("step") == "WAITING_SCREENSHOT":
                if "photo" in msg:
                    photo_file_id = msg["photo"][-1]["file_id"]
                    method = state_data["method"]
                    amount = state_data["amount"]
                    trx_id = state_data["trx_id"]

                    if method == "BINANCE":
                        converted_usd = amount
                        amount_info = f"{amount:.2f} USDT"
                    else:
                        converted_usd = round(amount / BDT_PER_USD, 2)
                        amount_info = f"৳{amount:.2f} BDT (${converted_usd:.2f} USD)"

                    usd_str_clean = f"{converted_usd:.2f}"
                    
                    admin_markup = {
                        "inline_keyboard": [
                            [
                                {"text": f"✅ Auto Approve (${converted_usd:.2f})", "callback_data": f"appusd_{user_id}_{usd_str_clean}", "style": "success"},
                                {"text": "✏️ Custom", "callback_data": f"dep_app_{user_id}", "style": "primary"}
                            ],
                            [
                                {"text": "❌ Reject", "callback_data": f"dep_rej_{user_id}", "style": "danger"}
                            ]
                        ]
                    }
                    admin_caption = (
                        f"📥 <b>New Deposit ({method})</b>\n\n"
                        f"👤 <b>User:</b> {html.escape(first_name)} (@{username})\n"
                        f"🆔 <b>ID:</b> <code>{user_id}</code>\n"
                        f"💰 <b>Amount:</b> {amount_info}\n"
                        f"🧾 <b>TrxID:</b> <code>{html.escape(trx_id)}</code>"
                    )
                    
                    send_photo_to_admin(ADMIN_ID, photo_file_id, admin_caption, reply_markup=admin_markup)
                    send_message(chat_id, "✅ <b>আপনার জমা দেওয়া তথ্য অ্যাডমিনের কাছে গেছে।</b>", reply_markup=get_main_keyboard(is_admin))
                    del user_states[user_id]
                    return
                else:
                    send_message(chat_id, "❌ <b>অনুরোধ করে ছবি/স্ক্রিনশট দিন।</b>", reply_markup=get_back_keyboard())
                    return

            elif is_admin and state_data == "ADMIN_UPLOAD_FILE":
                if "document" in msg:
                    doc = msg["document"]
                    file_id = doc["file_id"]
                    file_info = requests.get(BASE_URL + f"getFile?file_id={file_id}").json()
                    if file_info.get("ok"):
                        file_path = file_info["result"]["file_path"]
                        content = requests.get(f"https://api.telegram.org/file/bot{TOKEN}/{file_path}").text
                        
                        count = 0
                        for line in content.splitlines():
                            line = line.strip()
                            if line.startswith("+") and ("http://" in line or "https://" in line):
                                parts = line.replace(",", " ").split()
                                if len(parts) >= 2:
                                    add_stock_item(parts[0].strip(), parts[1].strip())
                                    count += 1
                        
                        send_message(chat_id, f"✅ <b>{count} টি নম্বর স্টকে আপলোড করা হয়েছে!</b>", reply_markup=get_main_keyboard(is_admin))
                        del user_states[user_id]
                        return
                else:
                    send_message(chat_id, "❌ <b>একটি সঠিক ফাইল দিন।</b>", reply_markup=get_back_keyboard())
                    return

            elif isinstance(state_data, str) and state_data.startswith("ADMIN_APPROVE_AMOUNT_"):
                target_user = int(state_data.replace("ADMIN_APPROVE_AMOUNT_", ""))
                try:
                    usd_val = float(text)
                    update_balance(target_user, usd_val)
                    send_message(chat_id, f"✅ <b>User ID {target_user}-কে ${usd_val:.2f} USD যোগ করা হয়েছে।</b>")
                    send_message(target_user, f"🎉 <b>আপনার অ্যাকাউন্টে ${usd_val:.2f} USD যোগ করা হয়েছে।</b>")
                except Exception:
                    send_message(chat_id, "❌ <b>ভুল ইনপুট!</b>")
                del user_states[user_id]
                return

            elif isinstance(state_data, str) and state_data == "ADMIN_SET_PRICE":
                try:
                    new_p = float(text)
                    set_number_price(new_p)
                    send_message(chat_id, f"✅ <b>নতুন রেট: ${new_p:.2f} USD</b>", reply_markup=get_main_keyboard(is_admin))
                except Exception:
                    send_message(chat_id, "❌ <b>ভুল ইনপুট!</b>")
                del user_states[user_id]
                return

            elif isinstance(state_data, str) and state_data == "ADMIN_BROADCAST":
                all_users = get_all_users()
                success, failed = 0, 0
                send_message(chat_id, f"⏳ <b>মেসেজ পাঠানো হচ্ছে...</b>")
                for u_id in all_users:
                    try:
                        res = send_message(u_id, text)
                        if res.get("ok"):
                            success += 1
                        else:
                            failed += 1
                    except Exception:
                        failed += 1
                send_message(chat_id, f"✅ <b>ব্রডকাস্ট সম্পন্ন!</b>\n\n🎯 সফল: {success}\n❌ ব্যর্থ: {failed}", reply_markup=get_main_keyboard(is_admin))
                del user_states[user_id]
                return

        if text == "/start":
            welcome_text = f"👋 <b>Welcome {html.escape(first_name)}!</b>\n\nনিচের মেনু থেকে সার্ভিস সিলেক্ট করুন:"
            send_message(chat_id, welcome_text, reply_markup=get_main_keyboard(is_admin))

        elif text in ["🛒 BUY NUMBER", "📱 GET NUMBER"]:
            markup = {
                "inline_keyboard": [
                    [{"text": f"🇺🇸 Buy USA WhatsApp Number (${current_price:.2f})", "callback_data": "confirm_buy_usa", "style": "success"}]
                ]
            }
            send_message(chat_id, f"<b>WhatsApp Service Selected:</b>\nমূল্য: <b>${current_price:.2f} USD</b>", reply_markup=get_back_keyboard())
            send_message(chat_id, "সার্ভিস অপশন:", reply_markup=markup)

        elif text == "💳 DEPOSIT":
            dep_text = f"💳 <b>Deposit Options</b>\n\n<i>রেট: ৳{int(BDT_PER_USD)} BDT = $1.00 USD</i>"
            markup = {
                "inline_keyboard": [
                    [{"text": "💖 bKash (BDT)", "callback_data": "dep_bkash", "style": "primary"}],
                    [{"text": "🟠 Nagad (BDT)", "callback_data": "dep_nagad", "style": "primary"}],
                    [{"text": "🟡 Binance (Crypto USDT)", "callback_data": "dep_binance", "style": "success"}]
                ]
            }
            send_message(chat_id, dep_text, reply_markup=get_back_keyboard())
            send_message(chat_id, "পেমেন্ট গেটওয়ে:", reply_markup=markup)

        elif text == "👤 PROFILE":
            u_info = get_user(user_id)
            bal = u_info[2] if u_info else 0.0
            tot = u_info[3] if u_info else 0.0
            prof_text = (
                f"👤 <b>Profile Info</b>\n\n"
                f"🆔 <b>ID:</b> <code>{user_id}</code>\n"
                f"💰 <b>Balance:</b> ${bal:.2f} USD\n"
                f"📊 <b>Total Recharge:</b> ${tot:.2f} USD"
            )
            send_message(chat_id, prof_text, reply_markup=get_back_keyboard())

        elif text == "🎧 SUPPORT":
            send_message(chat_id, f"<b>যোগাযোগ করুন:</b> @{SUPPORT_USERNAME}", reply_markup=get_back_keyboard())

        elif text == "⚙️ ADMIN PANEL" and is_admin:
            msg = f"<b>⚙️ ADMIN PANEL</b>\n\n💰 <b>Price:</b> ${current_price:.2f} USD"
            markup = {
                "inline_keyboard": [
                    [{"text": "🏷️ Change Price", "callback_data": "admin_set_rate", "style": "primary"}],
                    [{"text": "📢 Broadcast", "callback_data": "admin_broadcast", "style": "primary"}],
                    [{"text": "📁 Upload Stock", "callback_data": "admin_upload_file", "style": "primary"}],
                    [{"text": "📊 View Stock", "callback_data": "admin_view_stock", "style": "primary"}],
                    [{"text": "🗑️ Delete Stock", "callback_data": "admin_delete_stock_confirm", "style": "danger"}]
                ]
            }
            send_message(chat_id, msg, reply_markup=get_back_keyboard())
            send_message(chat_id, "এডমিন অপশন:", reply_markup=markup)

    elif "callback_query" in update:
        cb = update["callback_query"]
        cb_id = cb["id"]
        chat_id = cb["message"]["chat"]["id"]
        message_id = cb["message"]["message_id"]
        user_id = cb["from"]["id"]
        data = cb.get("data", "")
        is_admin = (user_id == ADMIN_ID)

        try:
            requests.post(BASE_URL + "answerCallbackQuery", data={"callback_query_id": cb_id}, timeout=5)
        except Exception:
            pass

        current_price = get_number_price()

        if data == "confirm_buy_usa":
            u_info = get_user(user_id)
            bal = u_info[2] if u_info else 0.0

            if bal < current_price:
                edit_message(chat_id, message_id, f"❌ <b>পর্যাপ্ত ব্যালেন্স নেই! (${current_price:.2f} USD প্রয়োজন)</b>")
                return

            phone, link = pop_stock_item()
            if not phone:
                edit_message(chat_id, message_id, "⚠️ <b>স্টক খালি রয়েছে!</b>")
                return

            deduct_balance(user_id, current_price)
            save_active_order(user_id, phone, link)

            markup = {
                "inline_keyboard": [
                    [{"text": "🔄 Check OTP", "callback_data": f"chk_otp_{phone}", "style": "success"}],
                    [{"text": "🛒 Buy Another", "callback_data": "confirm_buy_usa", "style": "primary"}]
                ]
            }
            res_text = (
                f"✅ <b>নম্বর বরাদ্দ করা হয়েছে!</b>\n\n"
                f"📱 <b>Number:</b> <code>{phone}</code>\n"
                f"🔗 <b>OTP Link:</b> {link}\n"
                f"💰 <b>ফি:</b> ${current_price:.2f} USD\n\n"
                f"অ্যাপে নম্বর বসিয়ে Check OTP চাপুন।"
            )
            
            send_message(chat_id, res_text, reply_markup=markup)
            send_message(chat_id, "<b>মেনু:</b>", reply_markup=get_main_keyboard(is_admin))

        elif data.startswith("chk_otp_"):
            phone = data.replace("chk_otp_", "")
            order = get_order_by_phone(phone)
            
            if order:
                link = order[2]
                otp_code = None
                
                try:
                    headers = {
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                        "Accept": "*/*"
                    }

                    api_link = link.replace("/sms/", "/api/sms/") if "/sms/" in link else link

                    response = requests.get(api_link, headers=headers, timeout=8)
                    api_text = response.text.strip()

                    if re.match(r'^\d{3,10}$', api_text):
                        otp_code = api_text
                    else:
                        main_res = requests.get(link, headers=headers, timeout=8)
                        matches = re.findall(r'\b\d{6}\b', main_res.text)
                        clean_phone = re.sub(r'\D', '', phone)
                        
                        for code in matches:
                            if code not in ['111111', '000000', '123456'] and code not in clean_phone:
                                otp_code = code
                                break

                except Exception as e:
                    print(f"OTP Scraping Error: {e}")

                if otp_code:
                    markup = {
                        "inline_keyboard": [
                            [{"text": "🛒 Buy Another Number", "callback_data": "confirm_buy_usa", "style": "primary"}]
                        ]
                    }
                    send_message(chat_id, f"🇺🇸 <b>USA Number OTP</b>\n\n📥 <b>আপনার OTP:</b> <code>{otp_code}</code>", reply_markup=markup)
                    
                    if OTP_GROUP_ID:
                        group_msg = f"🇺🇸 🎉 <b>New USA OTP!</b>\n\n📱 <b>Number:</b> <code>{phone}</code>\n🔑 <b>OTP Code:</b> <code>{otp_code}</code>"
                        send_message(OTP_GROUP_ID, group_msg)
                else:
                    send_message(chat_id, "⌛ <b>OTP এখনও আসেনি!</b> আবার Check OTP চাপুন।")

        elif data == "dep_bkash":
            user_states[user_id] = {"step": "WAITING_AMOUNT", "method": "BKASH"}
            send_message(chat_id, f"💖 <b>bKash Deposit</b>\n\nকত টাকা (BDT) ডিপোজিট করবেন লিখুন:", reply_markup=get_back_keyboard())

        elif data == "dep_nagad":
            user_states[user_id] = {"step": "WAITING_AMOUNT", "method": "NAGAD"}
            send_message(chat_id, f"🟠 <b>Nagad Deposit</b>\n\nকত টাকা (BDT) ডিপোজিট করবেন লিখুন:", reply_markup=get_back_keyboard())

        elif data == "dep_binance":
            user_states[user_id] = {"step": "WAITING_AMOUNT", "method": "BINANCE"}
            send_message(chat_id, "🟡 <b>Binance Deposit</b>\n\nকত USDT (USD) ডিপোজিট করবেন লিখুন:", reply_markup=get_back_keyboard())

        elif data == "admin_set_rate" and is_admin:
            user_states[user_id] = "ADMIN_SET_PRICE"
            send_message(chat_id, "🏷️ <b>নতুন মূল্য ($ USD) লিখুন:</b>", reply_markup=get_back_keyboard())

        elif data == "admin_broadcast" and is_admin:
            user_states[user_id] = "ADMIN_BROADCAST"
            send_message(chat_id, "📢 <b>ব্রডকাস্ট বার্তা লিখুন:</b>", reply_markup=get_back_keyboard())

        elif data == "admin_upload_file" and is_admin:
            user_states[user_id] = "ADMIN_UPLOAD_FILE"
            send_message(chat_id, "📁 <b>নম্বর ফাইল (.txt / .csv) দিন:</b>", reply_markup=get_back_keyboard())

        elif data == "admin_view_stock" and is_admin:
            stock_items = get_all_stock()
            if not stock_items:
                send_message(chat_id, "📊 <b>স্টকে কোনো নম্বর নেই!</b>")
            else:
                stock_text = f"📊 <b>স্টক (মোট: {len(stock_items)} টি):</b>\n\n"
                for item in stock_items[:30]:
                    stock_text += f"📱 <code>{item[1]}</code>\n🔗 {item[2]}\n\n"
                send_message(chat_id, stock_text)

        elif data == "admin_delete_stock_confirm" and is_admin:
            markup = {
                "inline_keyboard": [
                    [{"text": "✅ Yes, Delete All", "callback_data": "admin_delete_stock_execute", "style": "danger"}]
                ]
            }
            edit_message(chat_id, message_id, "⚠️ <b>আপনি কি নিশ্চিতভাবে সমস্ত স্টক মুছতে চান?</b>", reply_markup=markup)

        elif data == "admin_delete_stock_execute" and is_admin:
            clear_all_stock()
            edit_message(chat_id, message_id, "🗑️ <b>সমস্ত স্টক ডিলিট করা হয়েছে!</b>")

        elif data.startswith("appusd_") and is_admin:
            parts = data.split("_")
            target_user = int(parts[1])
            usd_val = float(parts[2])
            
            update_balance(target_user, usd_val)
            send_message(chat_id, f"✅ <b>User ID {target_user}-কে ${usd_val:.2f} USD যোগ করা হয়েছে!</b>")
            send_message(target_user, f"🎉 <b>আপনার অ্যাকাউন্টে ${usd_val:.2f} USD যোগ করা হয়েছে।</b>")

        elif data.startswith("dep_app_") and is_admin:
            target_user = int(data.replace("dep_app_", ""))
            user_states[user_id] = f"ADMIN_APPROVE_AMOUNT_{target_user}"
            send_message(chat_id, f"<b>User ID {target_user}-এর জন্য $ (USD) পরিমাণ লিখুন:</b>")

        elif data.startswith("dep_rej_") and is_admin:
            target_user = int(data.replace("dep_rej_", ""))
            send_message(target_user, f"❌ <b>আপনার ডিপোজিট প্রুফটি সঠিক নয়!</b>")
            send_message(chat_id, f"❌ <b>User ID {target_user}-এর ডিপোজিট বাতিল করা হয়েছে।</b>")

def safe_execution_wrapper(upd):
    try:
        handle_update(upd)
    except Exception as e:
        print(f"Exception Handled: {e}")

if __name__ == "__main__":
    init_db()

    threading.Thread(target=run_flask, daemon=True).start()

    print("🚀 Bot Engine Online on Render...")
    offset = 0
    while True:
        try:
            res = requests.get(BASE_URL + "getUpdates", params={"offset": offset, "timeout": 20}, timeout=25).json()
            if res.get("ok"):
                for update in res.get("result", []):
                    offset = update["update_id"] + 1
                    threading.Thread(target=safe_execution_wrapper, args=(update,), daemon=True).start()
        except Exception as e:
            print(f"Polling Network Recovering... {e}")
            time.sleep(3)
