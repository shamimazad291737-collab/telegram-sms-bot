import os
import psycopg2
import requests
import html
import threading
import time
import re
import trace
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler

# Environment Variables
TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0")) if os.environ.get("ADMIN_ID") else 0
SUPPORT_USERNAME = os.environ.get("SUPPORT_USERNAME", "telegram")

BASE_URL = f"https://api.telegram.org/bot{TOKEN}/"

# Payment & Exchange Rate Configuration
BDT_PER_USD = 120.0  # 120 BDT = 1 USD
BKASH_NUMBER = "01858582881 (Personal)"
NAGAD_NUMBER = "01858582881 (Personal)"
BINANCE_PAY_ID = "123456789"

user_states = {}

# Database Helper Function
def get_db():
    return psycopg2.connect(os.environ.get("DATABASE_URL"))

# Database Initialization
def init_db():
    conn = get_db()
    cursor = conn.cursor()
    
    # Users table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            username TEXT,
            balance REAL DEFAULT 0.0,
            total_recharge REAL DEFAULT 0.0
        )
    ''')
    
    # Stock table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS stock (
            id SERIAL PRIMARY KEY,
            phone_number TEXT,
            otp_link TEXT
        )
    ''')
    
    # Active Orders table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS active_orders (
            order_id SERIAL PRIMARY KEY,
            user_id BIGINT,
            phone_number TEXT,
            otp_link TEXT
        )
    ''')
    
    # Settings table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    
    cursor.execute("INSERT INTO settings (key, value) VALUES ('number_price', '0.10') ON CONFLICT (key) DO NOTHING")
    conn.commit()
    conn.close()

def get_number_price():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = 'number_price'")
    row = cursor.fetchone()
    conn.close()
    return float(row[0]) if row else 0.10

def set_number_price(new_price):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE settings SET value = %s WHERE key = 'number_price'", (str(new_price),))
    conn.commit()
    conn.close()

def get_all_users():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users")
    rows = cursor.fetchall()
    conn.close()
    return [r[0] for r in rows]

def get_all_stock():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, phone_number, otp_link FROM stock")
    rows = cursor.fetchall()
    conn.close()
    return rows

def clear_all_stock():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM stock")
    conn.commit()
    conn.close()

def save_active_order(user_id, phone_number, otp_link):
    conn = get_db()
    cursor = conn.cursor()
    clean_phone = phone_number.replace("+", "").strip()
    cursor.execute(
        "INSERT INTO active_orders (user_id, phone_number, otp_link) VALUES (%s, %s, %s)",
        (user_id, clean_phone, otp_link)
    )
    conn.commit()
    conn.close()

def get_order_by_phone(phone):
    conn = get_db()
    cursor = conn.cursor()
    clean_phone = phone.replace("+", "").strip()
    cursor.execute("""
        SELECT order_id, user_id, otp_link, phone_number 
        FROM active_orders 
        WHERE REPLACE(phone_number, '+', '') = %s 
        ORDER BY order_id DESC LIMIT 1
    """, (clean_phone,))
    row = cursor.fetchone()
    conn.close()
    return row

def get_user(user_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, username, balance, total_recharge FROM users WHERE user_id = %s", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row

def add_user(user_id, username):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO users (user_id, username) VALUES (%s, %s) ON CONFLICT (user_id) DO NOTHING", (user_id, username))
    conn.commit()
    conn.close()

def update_balance(user_id, amount_usd):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET balance = balance + %s, total_recharge = total_recharge + %s WHERE user_id = %s", (amount_usd, amount_usd, user_id))
    conn.commit()
    conn.close()

def deduct_balance(user_id, amount_usd):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET balance = balance - %s WHERE user_id = %s", (amount_usd, user_id))
    conn.commit()
    conn.close()

def add_stock_item(phone, link):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO stock (phone_number, otp_link) VALUES (%s, %s)", (phone, link))
    conn.commit()
    conn.close()

def pop_stock_item():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, phone_number, otp_link FROM stock LIMIT 1")
    row = cursor.fetchone()
    if row:
        cursor.execute("DELETE FROM stock WHERE id = %s", (row[0],))
        conn.commit()
        conn.close()
        return row[1], row[2]
    conn.close()
    return None, None
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

        # Handle Back Button Globally
        if text in ["⬅️ Back", "🔙 Back"]:
            if user_id in user_states:
                del user_states[user_id]
            send_message(chat_id, "<b>মূল মেনুতে ফিরে আসা হয়েছে:</b>", reply_markup=get_main_keyboard(is_admin))
            return

        # Input State Handling
        if user_id in user_states:
            state_data = user_states[user_id]
            
            # Step 1: Receiving Deposit Amount from User
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
                        msg_text = (
                            f"💖 <b>bKash Send Money</b>\n\n"
                            f"💵 <b>ডিপোজিট পরিমাণ:</b> ৳{amount:.2f} BDT\n"
                            f"📱 <b>bKash Number:</b> <code>{BKASH_NUMBER}</code>\n\n"
                            f"উপরের নম্বরে টাকা পাঠানোর পর আপনার <b>TrxID</b> এখানে লিখে পাঠান:"
                        )
                    elif method == "NAGAD":
                        msg_text = (
                            f"🟠 <b>Nagad Send Money</b>\n\n"
                            f"💵 <b>ডিপোজিট পরিমাণ:</b> ৳{amount:.2f} BDT\n"
                            f"📱 <b>Nagad Number:</b> <code>{NAGAD_NUMBER}</code>\n\n"
                            f"উপরের নম্বরে টাকা পাঠানোর পর আপনার <b>TrxID</b> এখানে লিখে পাঠান:"
                        )
                    elif method == "BINANCE":
                        msg_text = (
                            f"🟡 <b>Binance Pay (Crypto)</b>\n\n"
                            f"💵 <b>ডিপোজিট পরিমাণ:</b> {amount:.2f} USDT\n"
                            f"🆔 <b>Binance Pay ID:</b> <code>{BINANCE_PAY_ID}</code>\n\n"
                            f"উপরের আইডি তে USDT পাঠানোর পর আপনার <b>Binance Order ID / TrxID</b> মেসেজ লিখে পাঠান:"
                        )

                    send_message(chat_id, msg_text, reply_markup=get_back_keyboard())
                    return
                except ValueError:
                    send_message(chat_id, "❌ <b>ভুল ইনপুট!</b> কেবল সংখ্যা লিখুন। (যেমন: 120 বা 5)")
                    return

            # Step 2: Receiving TrxID / Order ID
            elif isinstance(state_data, dict) and state_data.get("step") == "WAITING_TRX":
                method = state_data["method"]
                amount = state_data["amount"]
                
                user_states[user_id] = {
                    "step": "WAITING_SCREENSHOT",
                    "method": method,
                    "amount": amount,
                    "trx_id": text
                }
                send_message(chat_id, "📸 <b>ধন্যবাদ! এবার পেমেন্টের একটি স্পষ্ট স্ক্রিনশট (Photo) পাঠান:</b>", reply_markup=get_back_keyboard())
                return

            # Step 3: Receiving Screenshot & Sending Request to Admin
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
                        amount_info = f"৳{amount:.2f} BDT (Estimated: ${converted_usd:.2f} USD @ 120 BDT/$)"

                    usd_str_clean = f"{converted_usd:.2f}"
                    admin_markup = {
                        "inline_keyboard": [
                            [
                                {"text": f"✅ Auto Approve (${converted_usd:.2f})", "callback_data": f"appusd_{user_id}_{usd_str_clean}", "style": "success"},
                                {"text": "✏️ Custom Amount", "callback_data": f"dep_app_{user_id}", "style": "primary"}
                            ],
                            [
                                {"text": "❌ Reject Request", "callback_data": f"dep_rej_{user_id}", "style": "danger"}
                            ]
                        ]
                    }
                    admin_caption = (
                        f"📥 <b>New Deposit Request ({method})</b>\n\n"
                        f"👤 <b>User:</b> {html.escape(first_name)} (@{username})\n"
                        f"🆔 <b>User ID:</b> <code>{user_id}</code>\n"
                        f"💰 <b>Payment:</b> {amount_info}\n"
                        f"🧾 <b>TrxID / Order ID:</b> <code>{html.escape(trx_id)}</code>\n\n"
                        f"যাচাই করে ডলারে যোগ করতে নিচের বাটন প্রেস করুন:"
                    )
                    
                    send_photo_to_admin(ADMIN_ID, photo_file_id, admin_caption, reply_markup=admin_markup)
                    send_message(chat_id, "✅ <b>আপনার তথ্য ও স্ক্রিনশট অ্যাডমিনের কাছে পাঠানো হয়েছে!</b>\nযাচাই করার পর অ্যাকাউন্টে ডলার ব্যালেন্স যোগ করা হবে।", reply_markup=get_main_keyboard(is_admin))
                    del user_states[user_id]
                    return
                else:
                    send_message(chat_id, "❌ <b>অনুগ্রহ করে পেমেন্টের একটি ছবি/স্ক্রিনশট পাঠান।</b>", reply_markup=get_back_keyboard())
                    return

            # Admin Uploading File via Menu Button
            elif is_admin and state_data == "ADMIN_UPLOAD_FILE":
                if "document" in msg:
                    doc = msg["document"]
                    file_name = doc.get("file_name", "").lower()
                    if not (file_name.endswith(".txt") or file_name.endswith(".csv")):
                        send_message(chat_id, "❌ <b>দয়া করে শুধুমাত্র .txt অথবা .csv ফাইল আপলোড করুন!</b>", reply_markup=get_back_keyboard())
                        return

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
                        
                        send_message(chat_id, f"✅ <b>সফলভাবে {count} টি নম্বর স্টকে আপলোড করা হয়েছে!</b>", reply_markup=get_main_keyboard(is_admin))
                        del user_states[user_id]
                        return
                else:
                    send_message(chat_id, "❌ <b>অনুগ্রহ করে একটি সঠিক টেক্সট (.txt / .csv) ফাইল আপলোড করুন।</b>", reply_markup=get_back_keyboard())
                    return

            # Admin Custom Inputting Balance Amount (USD) to Add
            elif isinstance(state_data, str) and state_data.startswith("ADMIN_APPROVE_AMOUNT_"):
                target_user = int(state_data.replace("ADMIN_APPROVE_AMOUNT_", ""))
                try:
                    usd_val = float(text)
                    update_balance(target_user, usd_val)
                    send_message(chat_id, f"✅ <b>User ID {target_user}-কে ${usd_val:.2f} USD ব্যালেন্স যোগ করা হয়েছে।</b>")
                    send_message(target_user, f"🎉 <b>আপনার ডিপোজিট প্রসেস সফল হয়েছে! ${usd_val:.2f} USD অ্যাকাউন্টে যোগ করা হয়েছে।</b>")
                except Exception:
                    send_message(chat_id, "❌ <b>ভুল অ্যামাউন্ট!</b> কেবল ডলারে সংখ্যা লিখুন। (যেমন: 0.21 বা 5.00)")
                del user_states[user_id]
                return

            # Admin Setting Rate State
            elif isinstance(state_data, str) and state_data == "ADMIN_SET_PRICE":
                try:
                    new_p = float(text)
                    set_number_price(new_p)
                    send_message(chat_id, f"✅ <b>WhatsApp নম্বর মূল্য কাস্টমাইজ সফল হয়েছে!</b>\nবর্তমান রেট: <b>${new_p:.2f} USD</b>", reply_markup=get_main_keyboard(is_admin))
                except Exception:
                    send_message(chat_id, "❌ <b>ভুল ইনপুট!</b> কেবল রেটের সংখ্যা লিখুন। (যেমন: 0.12)")
                del user_states[user_id]
                return

            # Admin Broadcast Message State
            elif isinstance(state_data, str) and state_data == "ADMIN_BROADCAST":
                all_users = get_all_users()
                success, failed = 0, 0
                send_message(chat_id, f"⏳ <b>{len(all_users)} জন ইউজারের কাছে মেসেজ পাঠানো শুরু হচ্ছে...</b>")
                for u_id in all_users:
                    try:
                        res = send_message(u_id, text)
                        if res.get("ok"):
                            success += 1
                        else:
                            failed += 1
                    except Exception:
                        failed += 1
                send_message(chat_id, f"✅ <b>ব্রডকাস্ট সম্পন্ন হয়েছে!</b>\n\n🎯 সফল: {success}\n❌ ব্যর্থ: {failed}", reply_markup=get_main_keyboard(is_admin))
                del user_states[user_id]
                return

        # Main Reply Keyboards
        if text == "/start":
            welcome_text = f"👋 <b>Welcome {html.escape(first_name)}!</b>\n\nনিচের মেনু থেকে সার্ভিস সিলেক্ট করুন:"
            send_message(chat_id, welcome_text, reply_markup=get_main_keyboard(is_admin))

        elif text in ["🛒 BUY NUMBER", "📱 GET NUMBER"]:
            markup = {
                "inline_keyboard": [
                    [{"text": f"🇺🇸 Buy USA WhatsApp Number (${current_price:.2f} USD)", "callback_data": "confirm_buy_usa", "style": "danger"}]
                ]
            }
            send_message(chat_id, f"<b>WhatsApp Service Selected:</b>\n\nমূল্য: <b>${current_price:.2f} USD / Number</b>", reply_markup=get_back_keyboard())
            send_message(chat_id, "সার্ভিস অপশন:", reply_markup=markup)

        elif text == "💳 DEPOSIT":
            dep_text = f"💳 <b>Deposit Options</b>\n\n<i>নোট: ৳{int(BDT_PER_USD)} BDT = $1.00 USD ডাইনামিক কনভার্ট হবে।</i>\n\nআপনার সুবিধাজনক পেমেন্ট মেথডটি বেছে নিন:"
            markup = {
                "inline_keyboard": [
                    [{"text": "💖 bKash (BDT)", "callback_data": "dep_bkash", "style": "danger"}],
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
                f"👤 <b>Your Profile Information</b>\n\n"
                f"🆔 <b>User ID:</b> <code>{user_id}</code>\n"
                f"💰 <b>Current Balance:</b> ${bal:.2f} USD\n"
                f"📊 <b>Total Recharge:</b> ${tot:.2f} USD"
            )
            send_message(chat_id, prof_text, reply_markup=get_back_keyboard())

        elif text == "🎧 SUPPORT":
            send_message(chat_id, f"<b>যেকোনো সাহায্যে যোগাযোগ করুন:</b>\n👉 @{SUPPORT_USERNAME}", reply_markup=get_back_keyboard())

        elif text == "⚙️ ADMIN PANEL" and is_admin:
            msg = (
                "<b>⚙️ ADMIN PANEL</b>\n\n"
                f"💰 <b>WhatsApp Number Price:</b> ${current_price:.2f} USD\n"
                f"💱 <b>Exchange Rate:</b> 1 USD = ৳{int(BDT_PER_USD)} BDT"
            )
            markup = {
                "inline_keyboard": [
                    [{"text": "🏷️ Change WhatsApp Price", "callback_data": "admin_set_rate", "style": "primary"}],
                    [{"text": "📢 Broadcast Message", "callback_data": "admin_broadcast", "style": "danger"}],
                    [{"text": "📁 Upload Stock File", "callback_data": "admin_upload_file", "style": "success"}],
                    [{"text": "📊 View Current Stock", "callback_data": "admin_view_stock", "style": "primary"}],
                    [{"text": "🗑️ Delete All Stock", "callback_data": "admin_delete_stock_confirm", "style": "danger"}]
                ]
            }
            send_message(chat_id, msg, reply_markup=get_back_keyboard())
            send_message(chat_id, "এডমিন একশন সিলেক্ট করুন:", reply_markup=markup)

    elif "callback_query" in update:
        cb = update["callback_query"]
        cb_id = cb["id"]
        chat_id = cb["message"]["chat"]["id"]
        message_id = cb["message"]["message_id"]
        user_id = cb["from"]["id"]
        data = cb.get("data", "")

        try:
            requests.post(BASE_URL + "answerCallbackQuery", data={"callback_query_id": cb_id}, timeout=5)
        except Exception:
            pass

        current_price = get_number_price()

        if data == "confirm_buy_usa":
            u_info = get_user(user_id)
            bal = u_info[2] if u_info else 0.0

            if bal < current_price:
                edit_message(chat_id, message_id, f"❌ <b>পর্যাপ্ত ব্যালেন্স নেই!</b>\nনম্বর কিনতে অন্তত ${current_price:.2f} USD ব্যালেন্স লাগবে। Deposit সেকশন থেকে রিচার্জ করুন।")
                return

            phone, link = pop_stock_item()
            if not phone:
                edit_message(chat_id, message_id, "⚠️ <b>দুঃখিত! বর্তমানে স্টক ফাঁকা রয়েছে।</b> কিছু সময় পর আবার চেষ্টা করুন।")
                return
            deduct_balance(user_id, current_price)
            save_active_order(user_id, phone, link)
            clean_phone = phone.replace("+", "")
            markup = {
                "inline_keyboard": [
                    [{"text": "🔄 Check OTP", "callback_data": f"chk_otp_{clean_phone}", "style": "success"}],
                    [{"text": "🛒 Buy Another Number", "callback_data": "confirm_buy_usa", "style": "primary"}]
                ]
            }
            res_text = (
                f"✅ <b>নম্বর বরাদ্দ করা হয়েছে!</b>\n\n"
                f"📱 <b>USA Number:</b> <code>{phone}</code>\n"
                f"🔗 <b>OTP Link:</b> {link}\n"
                f"💰 <b>ফি কাটা হয়েছে:</b> ${current_price:.2f} USD\n\n"
                f"👉 নম্বরটি অ্যাপে ব্যবহার করার পর <b>Check OTP</b> বাটনে চাপ দিন অথবা সরাসরি উপরের লিংকে ঢুকেও কোড দেখতে পারেন।"
            )
            edit_message(chat_id, message_id, res_text, reply_markup=markup)

        # REGEX OTP EXTRACTION
        elif data.startswith("chk_otp_"):
            phone = data.replace("chk_otp_", "").replace("+", "").strip()
            order = get_order_by_phone(phone)

            if order:
                link = order[2]
                try:
                    headers = {
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                    }
                    res = requests.get(link, headers=headers, timeout=12)
                    raw_text = res.text

                    # HTML Tag সরিয়ে স্পেস দেওয়া
                    clean_text = re.sub(r'<[^>]+>', ' ', raw_text)

                    # ৬ ডিজিটের OTP খোঁজা
                    otp_match = re.search(r'\b(\d{6})\b', clean_text)
                    if not otp_match:
                        otp_match_dash = re.search(r'\b(\d{3})[- ](\d{3})\b', clean_text)
                        if otp_match_dash:
                            otp_code = f"{otp_match_dash.group(1)}{otp_match_dash.group(2)}"
                        else:
                            otp_code = None
                    else:
                        otp_code = otp_match.group(1)

                    if otp_code:
                        markup = {
                            "inline_keyboard": [
                                [{"text": "🛒 Buy Another Number", "callback_data": "confirm_buy_usa", "style": "primary"}]
                            ]
                        }
                        send_message(chat_id, f"📥 <b>আপনার OTP:</b> <code>{otp_code}</code>", reply_markup=markup)
                    else:
                        send_message(chat_id, "⌛ <b>OTP এখনও আসেনি!</b> নম্বরটি অ্যাপে বসিয়ে কিছুক্ষণ পর আবার Check OTP চাপুন।")
                except Exception as e:
                    send_message(chat_id, f"⚠️ <b>OTP চেক করতে সমস্যা হয়েছে!</b>\nএরর: {e}")
            else:
                send_message(chat_id, "❌ <b>অর্ডার সম্পর্কিত তথ্য খুঁজে পাওয়া যায়নি!</b>")
        # Deposit Selection Events
        elif data == "dep_bkash":
            user_states[user_id] = {"step": "WAITING_AMOUNT", "method": "BKASH"}
            send_message(chat_id, f"💖 <b>bKash Deposit Selected</b>\n\nকত টাকা (BDT) ডিপোজিট করতে চান লিখে পাঠান:\n<i>(রেট: ৳{int(BDT_PER_USD)} BDT = $1.00 USD)</i>", reply_markup=get_back_keyboard())

        elif data == "dep_nagad":
            user_states[user_id] = {"step": "WAITING_AMOUNT", "method": "NAGAD"}
            send_message(chat_id, f"🟠 <b>Nagad Deposit Selected</b>\n\nকত টাকা (BDT) ডিপোজিট করতে চান লিখে পাঠান:\n<i>(রেট: ৳{int(BDT_PER_USD)} BDT = $1.00 USD)</i>", reply_markup=get_back_keyboard())

        elif data == "dep_binance":
            user_states[user_id] = {"step": "WAITING_AMOUNT", "method": "BINANCE"}
            send_message(chat_id, "🟡 <b>Binance Deposit Selected</b>\n\nকত <b>USDT</b> (USD) ডিপোজিট করতে চান লিখে পাঠান:", reply_markup=get_back_keyboard())

        # Admin Control Callbacks
        elif data == "admin_set_rate" and user_id == ADMIN_ID:
            user_states[user_id] = "ADMIN_SET_PRICE"
            send_message(chat_id, f"🏷️ <b>WhatsApp নম্বরের নতুন মূল্য ($ USD) লিখে পাঠান:</b>\n(বর্তমান রেট: ${current_price:.2f} USD)", reply_markup=get_back_keyboard())

        elif data == "admin_broadcast" and user_id == ADMIN_ID:
            user_states[user_id] = "ADMIN_BROADCAST"
            send_message(chat_id, "📢 <b>সব ইউজারদের উদ্দেশ্যে পাঠানোর বার্তাটি লিখে পাঠান:</b>", reply_markup=get_back_keyboard())

        elif data == "admin_upload_file" and user_id == ADMIN_ID:
            user_states[user_id] = "ADMIN_UPLOAD_FILE"
            send_message(chat_id, "📁 <b>নম্বর সম্বলিত ফাইলটি (.txt / .csv) এখানে পাঠাও:</b>\nফরম্যাট:\n<code>+1234567890, https://otp-link.com/check</code>", reply_markup=get_back_keyboard())

        elif data == "admin_view_stock" and user_id == ADMIN_ID:
            stock_items = get_all_stock()
            if not stock_items:
                send_message(chat_id, "📊 <b>বর্তমানে স্টকে কোনো নম্বর খালি নেই!</b>")
            else:
                stock_text = f"📊 <b>বর্তমান স্টকে থাকা নম্বরসমূহ (মোট: {len(stock_items)} টি):</b>\n\n"
                for item in stock_items[:30]:
                    stock_text += f"📱 <code>{item[1]}</code>\n🔗 {item[2]}\n\n"
                if len(stock_items) > 30:
                    stock_text += f"<i>...এবং আরও {len(stock_items) - 30} টি নম্বর রয়েছে।</i>"
                send_message(chat_id, stock_text)

        elif data == "admin_delete_stock_confirm" and user_id == ADMIN_ID:
            markup = {
                "inline_keyboard": [
                    [{"text": "✅ Yes, Delete All", "callback_data": "admin_delete_stock_execute", "style": "danger"}]
                ]
            }
            edit_message(chat_id, message_id, "⚠️ <b>আপনি কি নিশ্চিতভাবে সমস্ত স্টক ফাইল/নম্বর মুছে ফেলতে চান?</b>", reply_markup=markup)

        elif data == "admin_delete_stock_execute" and user_id == ADMIN_ID:
            clear_all_stock()
            edit_message(chat_id, message_id, "🗑️ <b>সফলভাবে সমস্ত স্টকে থাকা নম্বর ও লিংক ডিলিট করা হয়েছে!</b>")

        # Dynamic Auto Approve with Converted USD Rate
        elif data.startswith("appusd_") and user_id == ADMIN_ID:
            parts = data.split("_")
            target_user = int(parts[1])
            usd_val = float(parts[2])
            
            update_balance(target_user, usd_val)
            send_message(chat_id, f"✅ <b>User ID {target_user}-এর অ্যাকাউন্টে সফলভাবে ${usd_val:.2f} USD যোগ করা হয়েছে!</b>")
            send_message(target_user, f"🎉 <b>আপনার ডিপোজিট প্রসেস সফল হয়েছে! ${usd_val:.2f} USD অ্যাকাউন্টে যোগ করা হয়েছে।</b>")

        # Admin Custom Approval Option
        elif data.startswith("dep_app_") and user_id == ADMIN_ID:
            target_user = int(data.replace("dep_app_", ""))
            user_states[user_id] = f"ADMIN_APPROVE_AMOUNT_{target_user}"
            send_message(chat_id, f"<b>User ID {target_user}-এর অ্যাকাউন্টে কত $ (USD) যোগ করতে চান লিখে পাঠান:</b>")

        elif data.startswith("dep_rej_") and user_id == ADMIN_ID:
            target_user = int(data.replace("dep_rej_", ""))
            send_message(target_user, f"❌ <b>আপনার জমা দেওয়া ডিপোজিট প্রুফটি সঠিক নয়!</b>\nদয়া করে সঠিক তথ্য দিন বা সাপোর্ট অ্যাডমিনের সাথে কথা বলুন: @{SUPPORT_USERNAME}")
            send_message(chat_id, f"❌ <b>User ID {target_user}-এর ডিপোজিট বাতিল করা হয়েছে।</b>")

# Keep-Alive Web Server for UptimeRobot
class DummyServer(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(b"Bot Engine Live and Healthy.")

    def do_HEAD(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        
def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), DummyServer)
    server.serve_forever()

def safe_execution_wrapper(upd):
    try:
        handle_update(upd)
    except Exception as e:
        print(f"Exception Handled Safety: {e}")

if __name__ == "__main__":
    init_db()
    threading.Thread(target=run_web_server, daemon=True).start()

    print("🚀 Bot Engine Online with Crash Shield & UptimeRobot Support...")
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
