import os
import sqlite3
import requests
import html
import threading
import time
import re
from flask import Flask

# Flask app initialization for Render Port Binding
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running perfectly!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# Environment Variables
TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0")) if os.environ.get("ADMIN_ID") else 0
SUPPORT_USERNAME = os.environ.get("SUPPORT_USERNAME", "telegram")
OTP_GROUP_ID = os.environ.get("OTP_GROUP_ID", "")

BASE_URL = f"https://api.telegram.org/bot{TOKEN}/"

# Payment & Exchange Rate Configuration
BDT_PER_USD = 120.0  # 120 BDT = 1 USD
BKASH_NUMBER = "01858582881 (Personal)"
NAGAD_NUMBER = "01858582881 (Personal)"
BINANCE_PAY_ID = "123456789"

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

def update_balance(user_id, amount_usd):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET balance = balance + ?, total_recharge = total_recharge + ? WHERE user_id = ?", (amount_usd, amount_usd, user_id))
    conn.commit()
    conn.close()

def deduct_balance(user_id, amount_usd):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (amount_usd, user_id))
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

def send_message(chat_id, text, reply_markup=None):
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        return requests.post(BASE_URL + "sendMessage", json=payload, timeout=10).json()
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
    try:
        requests.post(BASE_URL + "editMessageText", json=payload, timeout=10)
    except Exception as e:
        print(f"Error editing message: {e}")

def send_photo_to_admin(chat_id, photo_file_id, caption, reply_markup=None):
    payload = {
        "chat_id": chat_id,
        "photo": photo_file_id,
        "caption": caption,
        "parse_mode": "HTML"
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        requests.post(BASE_URL + "sendPhoto", json=payload, timeout=10)
    except Exception as e:
        print(f"Error sending photo: {e}")

# Background Automatic OTP Polling System (Strictly 2 Minutes / 60 Checks)
def background_otp_listener(user_id, phone, link):
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Cache-Control": "no-cache"
    })
    
    clean_phone = re.sub(r'\D', '', phone)
    max_checks = 60  # 60 times * 2 seconds = 120 seconds (Strictly 2 Minutes Auto Listening)

    for _ in range(max_checks):
        try:
            res = session.get(link, timeout=5)
            page_text = res.text

            # Filter 6-digit OTPs
            otp_matches = re.findall(r'\b\d{6}\b', page_text)
            filtered_otps = [code for code in otp_matches if code not in ['111111', '000000', '123456', '169582', '111110'] and code not in clean_phone]

            if filtered_otps:
                otp_code = filtered_otps[0]
                
                # Send OTP instantly to User
                markup = {
                    "inline_keyboard": [
                        [{"text": "🛒 Buy Another Number", "callback_data": "confirm_buy_usa", "style": "success"}]
                    ]
                }
                send_message(user_id, f"🎉 <b>OTP প্রাপ্ত হয়েছে!</b>\n\n📱 <b>নম্বর:</b> <code>{phone}</code>\n🔑 <b>OTP Code:</b> <code>{otp_code}</code>", reply_markup=markup)
                
                # Send OTP to Group if configured
                if OTP_GROUP_ID:
                    group_msg = (
                        f"🎉 <b>New OTP Received!</b>\n\n"
                        f"📱 <b>Number:</b> <code>{phone}</code>\n"
                        f"🔑 <b>OTP Code:</b> <code>{otp_code}</code>"
                    )
                    send_message(OTP_GROUP_ID, group_msg)
                
                return  # Stop polling once OTP is delivered

        except Exception as e:
            print(f"Polling Exception: {e}")

        time.sleep(2)  # Check every 2 seconds

    # If time exceeds 2 minutes without OTP
    send_message(user_id, f"⏳ <b>সময়সীমা শেষ (২ মিনিট)!</b>\nনম্বর <code>{phone}</code>-এর জন্য কোনো ওটিপি পাওয়া যায়নি। নতুন নম্বর কিনে আবার চেষ্টা করুন।")

# Keyboards
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

def get_back_keyboard():
    kb = [
        [{"text": "⬅️ Back", "style": "danger"}]
    ]
    return {"keyboard": kb, "resize_keyboard": True}

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
                        msg_text = f"💖 <b>bKash Send Money</b>\n\n💵 <b>পরিমাণ:</b> ৳{amount:.2f} BDT\n📱 <b>নম্বর:</b> <code>{BKASH_NUMBER}</code>\n\nটাকা পাঠানোর পর TrxID লিখুন:"
                    elif method == "NAGAD":
                        msg_text = f"🟠 <b>Nagad Send Money</b>\n\n💵 <b>পরিমাণ:</b> ৳{amount:.2f} BDT\n📱 <b>নম্বর:</b> <code>{NAGAD_NUMBER}</code>\n\nটাকা পাঠানোর পর TrxID লিখুন:"
                    elif method == "BINANCE":
                        msg_text = f"🟡 <b>Binance Pay</b>\n\n💵 <b>পরিমাণ:</b> {amount:.2f} USDT\n🆔 <b>Pay ID:</b> <code>{BINANCE_PAY_ID}</code>\n\nOrder ID / TrxID লিখুন:"

                    send_message(chat_id, msg_text, reply_markup=get_back_keyboard())
                    return
                except ValueError:
                    send_message(chat_id, "❌ <b>ভুল ইনপুট!</b> সংখ্যা লিখুন।")
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
                send_message(chat_id, "📸 <b>পেমেন্টের একটি স্ক্রিনশট পাঠান:</b>", reply_markup=get_back_keyboard())
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
                        amount_info = f"৳{amount:.2f} BDT (Estimated: ${converted_usd:.2f} USD)"

                    usd_str_clean = f"{converted_usd:.2f}"
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
                        msg_text = f"💖 <b>bKash Send Money</b>\n\n💵 <b>পরিমাণ:</b> ৳{amount:.2f} BDT\n📱 <b>নম্বর:</b> <code>{BKASH_NUMBER}</code>\n\nটাকা পাঠানোর পর TrxID লিখুন:"
                    elif method == "NAGAD":
                        msg_text = f"🟠 <b>Nagad Send Money</b>\n\n💵 <b>পরিমাণ:</b> ৳{amount:.2f} BDT\n📱 <b>নম্বর:</b> <code>{NAGAD_NUMBER}</code>\n\nটাকা পাঠানোর পর TrxID লিখুন:"
                    elif method == "BINANCE":
                        msg_text = f"🟡 <b>Binance Pay</b>\n\n💵 <b>পরিমাণ:</b> {amount:.2f} USDT\n🆔 <b>Pay ID:</b> <code>{BINANCE_PAY_ID}</code>\n\nOrder ID / TrxID লিখুন:"

                    send_message(chat_id, msg_text, reply_markup=get_back_keyboard())
                    return
                except ValueError:
                    send_message(chat_id, "❌ <b>ভুল ইনপুট!</b> সংখ্যা লিখুন।")
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
                send_message(chat_id, "📸 <b>পেমেন্টের একটি স্ক্রিনশট পাঠান:</b>", reply_markup=get_back_keyboard())
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
                        amount_info = f"৳{amount:.2f} BDT (Estimated: ${converted_usd:.2f} USD)"

                    usd_str_clean = f"{converted_usd:.2f}"
                    admin_markup = {
                        "inline_keyboard": [
                            [
                                {"text": f"✅ Auto Approve (${converted_usd:.2f})", "callback_data": f"appusd_{user_id}_{usd_str_clean}", "style": "success"},
                                {"text": "✏️ Custom Amount", "callback_data": f"dep_app_{user_id}", "style": "primary"}
                            ],
                            [
                                {"text": "❌ Reject", "callback_data": f"dep_rej_{user_id}", "style": "danger"}
                            ]
                        ]
                    }
                    admin_caption = (
                        f"📥 <b>New Deposit Request ({method})</b>\n\n"
                        f"👤 <b>User:</b> {html.escape(first_name)} (@{username})\n"
                        f"🆔 <b>User ID:</b> <code>{user_id}</code>\n"
                        f"💰 <b>Payment:</b> {amount_info}\n"
                        f"🧾 <b>TrxID:</b> <code>{html.escape(trx_id)}</code>"
                    )
                    
                    send_photo_to_admin(ADMIN_ID, photo_file_id, admin_caption, reply_markup=admin_markup)
                    send_message(chat_id, "✅ <b>রিকোয়েস্ট অ্যাডমিনের কাছে পাঠানো হয়েছে!</b>", reply_markup=get_main_keyboard(is_admin))
                    del user_states[user_id]
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

            elif isinstance(state_data, str) and state_data.startswith("ADMIN_APPROVE_AMOUNT_"):
                target_user = int(state_data.replace("ADMIN_APPROVE_AMOUNT_", ""))
                try:
                    usd_val = float(text)
                    update_balance(target_user, usd_val)
                    send_message(chat_id, f"✅ <b>User ID {target_user}-কে ${usd_val:.2f} USD যোগ করা হয়েছে।</b>")
                    send_message(target_user, f"🎉 <b>আপনার ডিপোজিট প্রসেস সফল হয়েছে! ${usd_val:.2f} USD যোগ করা হয়েছে।</b>")
                except Exception:
                    send_message(chat_id, "❌ <b>ভুল অ্যামাউন্ট!</b>")
                del user_states[user_id]
                return

            elif isinstance(state_data, str) and state_data == "ADMIN_SET_PRICE":
                try:
                    new_p = float(text)
                    set_number_price(new_p)
                    send_message(chat_id, f"✅ <b>নতুন মূল্য: ${new_p:.2f} USD</b>", reply_markup=get_main_keyboard(is_admin))
                except Exception:
                    send_message(chat_id, "❌ <b>ভুল ইনপুট!</b>")
                del user_states[user_id]
                return

            elif isinstance(state_data, str) and state_data == "ADMIN_BROADCAST":
                all_users = get_all_users()
                for u_id in all_users:
                    try:
                        send_message(u_id, text)
                    except Exception:
                        pass
                send_message(chat_id, "✅ <b>ব্রডকাস্ট সম্পন্ন হয়েছে!</b>", reply_markup=get_main_keyboard(is_admin))
                del user_states[user_id]
                return

        if text == "/start":
            send_message(chat_id, f"👋 <b>Welcome {html.escape(first_name)}!</b>", reply_markup=get_main_keyboard(is_admin))

        elif text in ["🛒 BUY NUMBER", "📱 GET NUMBER"]:
            markup = {
                "inline_keyboard": [
                    [{"text": f"🇺🇸 Buy USA WhatsApp Number (${current_price:.2f} USD)", "callback_data": "confirm_buy_usa", "style": "danger"}]
                ]
            }
            send_message(chat_id, f"<b>WhatsApp Service:</b>\nমূল্য: <b>${current_price:.2f} USD</b>", reply_markup=get_back_keyboard())
            send_message(chat_id, "সার্ভিস অপশন:", reply_markup=markup)

        elif text == "💳 DEPOSIT":
            markup = {
                "inline_keyboard": [
                    [{"text": "💖 bKash (BDT)", "callback_data": "dep_bkash", "style": "danger"}],
                    [{"text": "🟠 Nagad (BDT)", "callback_data": "dep_nagad", "style": "primary"}],
                    [{"text": "🟡 Binance (Crypto USDT)", "callback_data": "dep_binance", "style": "success"}]
                ]
            }
            send_message(chat_id, "<b>Deposit Options:</b>", reply_markup=get_back_keyboard())
            send_message(chat_id, "পেমেন্ট গেটওয়ে:", reply_markup=markup)

        elif text == "👤 PROFILE":
            u_info = get_user(user_id)
            bal = u_info[2] if u_info else 0.0
            tot = u_info[3] if u_info else 0.0
            send_message(chat_id, f"👤 <b>Profile Info</b>\n\n🆔 <b>ID:</b> <code>{user_id}</code>\n💰 <b>Balance:</b> ${bal:.2f} USD\n📊 <b>Total Deposit:</b> ${tot:.2f} USD", reply_markup=get_back_keyboard())

        elif text == "🎧 SUPPORT":
            send_message(chat_id, f"<b>সহায়তার জন্য যোগাযোগ করুন:</b>\n👉 @{SUPPORT_USERNAME}", reply_markup=get_back_keyboard())

        elif text == "⚙️ ADMIN PANEL" and is_admin:
            markup = {
                "inline_keyboard": [
                    [{"text": "🏷️ Change Price", "callback_data": "admin_set_rate", "style": "primary"}],
                    [{"text": "📢 Broadcast", "callback_data": "admin_broadcast", "style": "danger"}],
                    [{"text": "📁 Upload Stock", "callback_data": "admin_upload_file", "style": "success"}],
                    [{"text": "📊 View Stock", "callback_data": "admin_view_stock", "style": "primary"}],
                    [{"text": "🗑️ Delete Stock", "callback_data": "admin_delete_stock_confirm", "style": "danger"}]
                ]
            }
            send_message(chat_id, "<b>⚙️ ADMIN PANEL</b>", reply_markup=get_back_keyboard())
            send_message(chat_id, "একশন সিলেক্ট করুন:", reply_markup=markup)

    elif "callback_query" in update:
        cb = update["callback_query"]
        cb_id = cb["id"]
        chat_id = cb["message"]["chat"]["id"]
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
                send_message(chat_id, f"❌ <b>পর্যাপ্ত ব্যালেন্স নেই!</b>\nন্যূনতম ${current_price:.2f} USD লাগবে।")
                return

            phone, link = pop_stock_item()
            if not phone:
                send_message(chat_id, "⚠️ <b>স্টক ফাঁকা রয়েছে!</b> কিছু সময় পর চেষ্টা করুন।")
                return

            deduct_balance(user_id, current_price)
            save_active_order(user_id, phone, link)

            # Inform user
            res_text = (
                f"✅ <b>নম্বর বরাদ্দ করা হয়েছে!</b>\n\n"
                f"📱 <b>USA Number:</b> <code>{phone}</code>\n"
                f"💰 <b>ফি কাটা হয়েছে:</b> ${current_price:.2f} USD\n\n"
                f"⚡ <b>বট ব্যাকগ্রাউন্ডে ২ মিনিট ধরে ওটিপি খুঁজছে...</b>\n"
                f"নম্বরটি অ্যাপে বসিয়ে কোড পাঠান। ওটিপি আসামাত্র বট নিজে থেকেই আপনাকে মেসেজ পাঠিয়ে দেবে।"
            )
            send_message(chat_id, res_text, reply_markup=get_main_keyboard(is_admin))

            # START AUTOMATIC BACKGROUND OTP LISTENER THREAD (2 Minutes Limit)
            threading.Thread(target=background_otp_listener, args=(user_id, phone, link), daemon=True).start()

        elif data == "dep_bkash":
            user_states[user_id] = {"step": "WAITING_AMOUNT", "method": "BKASH"}
            send_message(chat_id, f"💖 <b>bKash Deposit</b>\nকত টাকা (BDT) ডিপোজিট করবেন লিখুন:", reply_markup=get_back_keyboard())

        elif data == "dep_nagad":
            user_states[user_id] = {"step": "WAITING_AMOUNT", "method": "NAGAD"}
            send_message(chat_id, f"🟠 <b>Nagad Deposit</b>\nকত টাকা (BDT) ডিপোজিট করবেন লিখুন:", reply_markup=get_back_keyboard())

        elif data == "dep_binance":
            user_states[user_id] = {"step": "WAITING_AMOUNT", "method": "BINANCE"}
            send_message(chat_id, "🟡 <b>Binance Deposit</b>\nকত USDT ডিপোজিট করবেন লিখুন:", reply_markup=get_back_keyboard())

        elif data == "admin_set_rate" and is_admin:
            user_states[user_id] = "ADMIN_SET_PRICE"
            send_message(chat_id, "🏷️ <b>নতুন মূল্য লিখুন ($):</b>", reply_markup=get_back_keyboard())

        elif data == "admin_broadcast" and is_admin:
            user_states[user_id] = "ADMIN_BROADCAST"
            send_message(chat_id, "📢 <b>ব্রডকাস্ট বার্তা লিখুন:</b>", reply_markup=get_back_keyboard())

        elif data == "admin_upload_file" and is_admin:
            user_states[user_id] = "ADMIN_UPLOAD_FILE"
            send_message(chat_id, "📁 <b>নম্বর ফাইল (.txt/.csv) পাঠান:</b>", reply_markup=get_back_keyboard())

        elif data == "admin_view_stock" and is_admin:
            stock_items = get_all_stock()
            send_message(chat_id, f"📊 <b>মোট স্টক: {len(stock_items)} টি</b>")

        elif data == "admin_delete_stock_confirm" and is_admin:
            clear_all_stock()
            send_message(chat_id, "🗑️ <b>সমস্ত স্টক মুছে ফেলা হয়েছে।</b>")

        elif data.startswith("appusd_") and is_admin:
            parts = data.split("_")
            target_user = int(parts[1])
            usd_val = float(parts[2])
            update_balance(target_user, usd_val)
            send_message(chat_id, f"✅ <b>${usd_val:.2f} USD অনুমোদিত হয়েছে।</b>")
            send_message(target_user, f"🎉 <b>আপনার ${usd_val:.2f} USD ডিপোজিট যুক্ত হয়েছে!</b>")

        elif data.startswith("dep_app_") and is_admin:
            target_user = int(data.replace("dep_app_", ""))
            user_states[user_id] = f"ADMIN_APPROVE_AMOUNT_{target_user}"
            send_message(chat_id, "<b>ডলার অ্যামাউন্ট লিখুন:</b>")

        elif data.startswith("dep_rej_") and is_admin:
            target_user = int(data.replace("dep_rej_", ""))
            send_message(target_user, f"❌ <b>ডিপোজিট বাতিল করা হয়েছে।</b>")
            send_message(chat_id, "❌ <b>বাতিল করা হয়েছে।</b>")

def safe_execution_wrapper(upd):
    try:
        handle_update(upd)
    except Exception as e:
        print(f"Exception Handled Safety: {e}")

if __name__ == "__main__":
    init_db()

    threading.Thread(target=run_flask, daemon=True).start()

    print("🚀 Auto Listener Bot Online (2 Min Limit)...")
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
