import os
import requests
import html
import threading
import time
import re
from datetime import datetime, timedelta
from flask import Flask
from pymongo import MongoClient

# Flask app initialization for Render Port Binding
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running perfectly with Cloud Storage!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# Flask সার্ভার চালু করার জন্য থ্রেড কল

# Environment Variables
TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0")) if os.environ.get("ADMIN_ID") else 0
SUPPORT_USERNAME = os.environ.get("SUPPORT_USERNAME", "telegram")
OTP_GROUP_ID = os.environ.get("OTP_GROUP_ID", "")
MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017/my_telegram_bot") # Replace or set via Environment

BASE_URL = f"https://api.telegram.org/bot{TOKEN}/"

# MongoDB Initialization (Persistent Cloud Storage)
client = MongoClient(MONGO_URI)
db = client['telegram_otp_bot']

users_col = db['users']
stock_col = db['stock']
orders_col = db['active_orders']
settings_col = db['settings']

# Required Join Channels Config (Must be set by Admin or manually in DB)
REQUIRED_CHANNELS = [
    {"title": "Channel 1", "username": "@channel1_username"}, # আপনার প্রথম চ্যানেল ইউজারনেম দিন
    {"title": "Channel 2", "username": "@channel2_username"}, # আপনার দ্বিতীয় চ্যানেল ইউজারনেম দিন
    {"title": "Channel 3", "username": "@channel3_username"}  # আপনার তৃতীয় চ্যানেল ইউজারনেম দিন
]

user_states = {}

# Settings Helpers
def get_setting(key, default_value):
    doc = settings_col.find_one({"key": key})
    if doc:
        return doc["value"]
    else:
        settings_col.insert_one({"key": key, "value": str(default_value)})
        return str(default_value)

def set_setting(key, value):
    settings_col.update_one({"key": key}, {"$set": {"value": str(value)}}, upsert=True)

def get_number_price():
    return float(get_setting("number_price", "0.10"))

def set_number_price(price):
    set_setting("number_price", str(price))

def get_bdt_rate():
    return float(get_setting("bdt_per_usd", "128.0"))

def set_bdt_rate(rate):
    set_setting("bdt_per_usd", str(rate))

def is_bot_active():
    return get_setting("bot_status", "ON") == "ON"

def toggle_bot_status(status):
    set_setting("bot_status", status)

# Payment Configs
BKASH_NUMBER = "01858582881 (Personal)"
NAGAD_NUMBER = "01858582881 (Personal)"
BINANCE_PAY_ID = "907194603"

# Helper Function: OTP গ্রুপের জন্য নম্বর মাস্কিং
def mask_phone_number(phone):
    clean_phone = phone.strip()
    if len(clean_phone) > 6:
        mid = len(clean_phone) // 2
        return clean_phone[:mid-1] + "RX" + clean_phone[mid+1:]
    return clean_phone

# Database Helpers (MongoDB Migration)
def get_user(user_id):
    return users_col.find_one({"user_id": user_id})

def add_user(user_id, username):
    users_col.update_one(
        {"user_id": user_id},
        {"$set": {"username": username}, "$setOnInsert": {"balance": 0.0, "total_recharge": 0.0}},
        upsert=True
    )

def update_balance(user_id, amount_usd):
    users_col.update_one(
        {"user_id": user_id},
        {"$inc": {"balance": amount_usd, "total_recharge": amount_usd}}
    )

def add_refund_balance(user_id, amount_usd):
    users_col.update_one(
        {"user_id": user_id},
        {"$inc": {"balance": amount_usd}}
    )

def deduct_balance(user_id, amount_usd):
    users_col.update_one(
        {"user_id": user_id},
        {"$inc": {"balance": -amount_usd}}
    )

def add_stock_item(phone, link):
    stock_col.insert_one({"phone_number": phone, "otp_link": link})

def pop_stock_item():
    item = stock_col.find_one_and_delete({})
    if item:
        return item["phone_number"], item["otp_link"]
    return None, None

def get_all_stock():
    return list(stock_col.find())

def clear_all_stock():
    stock_col.delete_many({})

def save_active_order(user_id, phone, link):
    now_str = datetime.now().strftime("%d-%b-%Y %I:%M %p")
    orders_col.insert_one({
        "user_id": user_id,
        "phone_number": phone,
        "otp_link": link,
        "otp_code": None,
        "purchase_date": now_str,
        "timestamp": datetime.now()
    })

def update_order_otp(phone, otp_code):
    orders_col.update_one({"phone_number": phone}, {"$set": {"otp_code": otp_code}})

def get_user_orders_24h(user_id):
    time_24h_ago = datetime.now() - timedelta(hours=24)
    orders = list(orders_col.find({"user_id": user_id, "timestamp": {"$gte": time_24h_ago}}).sort("_id", -1))
    return orders

def get_order_by_phone(phone):
    return orders_col.find_one({"phone_number": phone}, sort=[("_id", -1)])

def get_all_users_info():
    return list(users_col.find())

def get_all_users():
    return [u["user_id"] for u in users_col.find({}, {"user_id": 1})]

# Force Join Verification Helper
def check_force_join(user_id):
    for ch in REQUIRED_CHANNELS:
        ch_username = ch["username"]
        try:
            res = requests.post(BASE_URL + "getChatMember", json={"chat_id": ch_username, "user_id": user_id}, timeout=5).json()
            if res.get("ok"):
                status = res["result"]["status"]
                if status not in ["creator", "administrator", "member"]:
                    return False
            else:
                return False
        except Exception:
            return False
    return True

def send_force_join_msg(chat_id):
    buttons = []
    for ch in REQUIRED_CHANNELS:
        buttons.append([{"text": f"📢 {ch['title']}", "url": f"https://t.me/{ch['username'].replace('@', '')}"}])
    buttons.append([{"text": "✅ Verify Membership", "callback_data": "verify_force_join", "style": "success"}])
    
    markup = {"inline_keyboard": buttons}
    msg_text = "<b>⚠️ বটে কাজ করার জন্য নিচের চ্যানেলগুলোতে জয়েন করা বাধ্যতামূলক:</b>\n\nসবগুলো চ্যানেলে জয়েন করে <b>Verify</b> বাটনে চাপ দিন।"
    send_message(chat_id, msg_text, reply_markup=markup)

# Telegram Requests
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
            {"text": "🛒 BUY NUMBER", "style": "success"},
            {"text": "💳 DEPOSIT", "style": "primary"}
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
    kb = [[{"text": "⬅️ Back", "style": "danger"}]]
    return {"keyboard": kb, "resize_keyboard": True}

# Core Update Handler
def handle_update(update):
    if "message" in update:
        msg = update["message"]
        chat_id = msg["chat"]["id"]
        chat_type = msg["chat"].get("type", "private")
        user_id = msg["from"]["id"]
        username = msg["from"].get("username", "NoUsername")
        first_name = msg["from"].get("first_name", "User")
        text = msg.get("text", "")

        # 🚫১. গ্রুপে বট কমান্ড বন্ধ (গ্রুপ মেসেজ বা ওটিপি গ্রুপ ইগনোর করা)
        if chat_type in ["group", "supergroup"]:
            return

        is_admin = (user_id == ADMIN_ID)
        add_user(user_id, username)

        # 🚫২. বট অফ থাকলে ইউজারের কাজ বন্ধ রাখা (এডমিন এক্সেস পাবে)
        if not is_bot_active() and not is_admin:
            send_message(chat_id, "⚠️ <b>এডমিন বর্তমানে বট সার্ভিস অফ রেখেছেন।</b>\nপরবর্তী নির্দেশনার জন্য অপেক্ষা করুন।")
            return

        # 🛑৩. ফোর্স জয়েন চেক
        if not is_admin and not check_force_join(user_id):
            send_force_join_msg(chat_id)
            return

        bdt_per_usd = get_bdt_rate()
        current_price = get_number_price()

        # Handle Back Button
        if text in ["⬅️ Back", "🔙 Back"]:
            if user_id in user_states:
                del user_states[user_id]
            send_message(chat_id, "<b>মূল মেনুতে ফিরে আসা হয়েছে:</b>", reply_markup=get_main_keyboard(is_admin))
            return

        # State Handler
        if user_id in user_states:
            state_data = user_states[user_id]

            if isinstance(state_data, dict) and state_data.get("step") == "WAITING_AMOUNT":
                method = state_data["method"]
                try:
                    amount = float(text)
                    if amount <= 0:
                        send_message(chat_id, "❌ <b>সঠিক পরিমাণ উল্লেখ করুন!</b>")
                        return
                    
                    user_states[user_id] = {"step": "WAITING_TRX", "method": method, "amount": amount}

                    if method == "BKASH":
                        msg_text = f"💖 <b>bKash Send Money</b>\n\n💵 <b>ডিপোজিট:</b> ৳{amount:.2f} BDT\n📱 <b>bKash:</b> <code>{BKASH_NUMBER}</code>\n\nটাকা পাঠানোর পর আপনার <b>TrxID</b> লিখে পাঠান:"
                    elif method == "NAGAD":
                        msg_text = f"🟠 <b>Nagad Send Money</b>\n\n💵 <b>ডিপোজিট:</b> ৳{amount:.2f} BDT\n📱 <b>Nagad:</b> <code>{NAGAD_NUMBER}</code>\n\nটাকা পাঠানোর পর আপনার <b>TrxID</b> লিখে পাঠান:"
                    elif method == "BINANCE":
                        msg_text = f"🟡 <b>Binance Pay</b>\n\n💵 <b>ডিপোজিট:</b> {amount:.2f} USDT\n🆔 <b>Pay ID:</b> <code>{BINANCE_PAY_ID}</code>\n\nUSDT পাঠানোর পর আপনার <b>Order ID / TrxID</b> লিখে পাঠান:"

                    send_message(chat_id, msg_text, reply_markup=get_back_keyboard())
                    return
                except ValueError:
                    send_message(chat_id, "❌ <b>ভুল ইনপুট!</b> কেবল সংখ্যা লিখুন।")
                    return

            elif isinstance(state_data, dict) and state_data.get("step") == "WAITING_TRX":
                method = state_data["method"]
                amount = state_data["amount"]
                user_states[user_id] = {"step": "WAITING_SCREENSHOT", "method": method, "amount": amount, "trx_id": text}
                send_message(chat_id, "📸 <b>পেমেন্টের একটি স্পষ্ট স্ক্রিনশট (Photo) পাঠান:</b>", reply_markup=get_back_keyboard())
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
                        converted_usd = round(amount / bdt_per_usd, 2)
                        amount_info = f"৳{amount:.2f} BDT (Estimated: ${converted_usd:.2f} USD @ {bdt_per_usd} BDT/$)"

                    usd_str_clean = f"{converted_usd:.2f}"
                    admin_markup = {
                        "inline_keyboard": [
                            [
                                {"text": f"✅ Auto Approve (${converted_usd:.2f})", "callback_data": f"appusd_{user_id}_{usd_str_clean}", "style": "success"},
                                {"text": "✏️ Custom Amount", "callback_data": f"dep_app_{user_id}", "style": "primary"}
                            ],
                            [{"text": "❌ Reject Request", "callback_data": f"dep_rej_{user_id}", "style": "danger"}]
                        ]
                    }
                    admin_caption = (
                        f"📥 <b>New Deposit Request ({method})</b>\n\n"
                        f"👤 <b>User:</b> {html.escape(first_name)} (@{username})\n"
                        f"🆔 <b>User ID:</b> <code>{user_id}</code>\n"
                        f"💰 <b>Payment:</b> {amount_info}\n"
                        f"🧾 <b>TrxID / Order ID:</b> <code>{html.escape(trx_id)}</code>\n\n"
                        f"যাচাই করে ডলার যোগ করতে বাটন চাপুন:"
                    )
                    
                    send_photo_to_admin(ADMIN_ID, photo_file_id, admin_caption, reply_markup=admin_markup)
                    send_message(chat_id, "✅ <b>আপনার তথ্য ও স্ক্রিনশট এডমিনের কাছে পাঠানো হয়েছে!</b>", reply_markup=get_main_keyboard(is_admin))
                    del user_states[user_id]
                    return
                else:
                    send_message(chat_id, "❌ <b>অনুগ্রহ করে পেমেন্টের একটি ফটো/স্ক্রিনশট পাঠান।</b>", reply_markup=get_back_keyboard())
                    return

            # Admin: Bulk Add Users
            elif is_admin and state_data == "ADMIN_BULK_ADD_USERS":
                raw_inputs = text.strip().split()
                added_count = 0
                for item in raw_inputs:
                    item_clean = item.replace("@", "").strip()
                    if item_clean.isdigit():
                        add_user(int(item_clean), "NoUsername")
                        added_count += 1
                    elif len(item_clean) > 0:
                        add_user(hash(item_clean) % 100000000, item_clean)
                        added_count += 1
                
                send_message(chat_id, f"✅ <b>সফলভাবে {added_count} জন ইউজার সিস্টেমে এড/আপডেট করা হয়েছে!</b>", reply_markup=get_main_keyboard(is_admin))
                del user_states[user_id]
                return

            # Admin: Change BDT Rate
            elif is_admin and state_data == "ADMIN_SET_BDT_RATE":
                try:
                    new_rate = float(text)
                    set_bdt_rate(new_rate)
                    send_message(chat_id, f"✅ <b>নতুন ডলার রেট ৳{new_rate} BDT সেট করা হয়েছে!</b>", reply_markup=get_main_keyboard(is_admin))
                except ValueError:
                    send_message(chat_id, "❌ <b>সঠিক সংখ্যা লিখুন (যেমন: 128 বা 130)।</b>")
                del user_states[user_id]
                return

            # Admin: Change Number Price
            elif is_admin and state_data == "ADMIN_SET_PRICE":
                try:
                    new_p = float(text)
                    set_number_price(new_p)
                    send_message(chat_id, f"✅ <b>নম্বরের নতুন দাম ${new_p:.2f} USD সেট করা হয়েছে!</b>", reply_markup=get_main_keyboard(is_admin))
                except ValueError:
                    send_message(chat_id, "❌ <b>সঠিক ডলার অ্যামাউন্ট লিখুন (যেমন: 0.10 или 0.15)।</b>")
                del user_states[user_id]
                return

            # Admin Stock File Upload
            elif is_admin and state_data == "ADMIN_UPLOAD_FILE":
                if "document" in msg:
                    doc = msg["document"]
                    file_name = doc.get("file_name", "").lower()
                    if not (file_name.endswith(".txt") or file_name.endswith(".csv")):
                        send_message(chat_id, "❌ <b>শুধুমাত্র .txt বা .csv ফাইল পাঠান।</b>")
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
                        
                        send_message(chat_id, f"✅ <b>{count} টি নম্বর স্টকে যোগ করা হয়েছে!</b>", reply_markup=get_main_keyboard(is_admin))
                        del user_states[user_id]
                        return
                else:
                    send_message(chat_id, "❌ <b>টেক্সট ফাইল পাঠাতে হবে।</b>")
                    return

            # Admin Custom Balance / Refund Handlers
            elif isinstance(state_data, str) and state_data.startswith("ADMIN_APPROVE_AMOUNT_"):
                target_user = int(state_data.replace("ADMIN_APPROVE_AMOUNT_", ""))
                try:
                    usd_val = float(text)
                    update_balance(target_user, usd_val)
                    send_message(chat_id, f"✅ <b>User ID {target_user}-কে ${usd_val:.2f} USD যোগ করা হয়েছে।</b>")
                    send_message(target_user, f"🎉 <b>আপনার অ্যাকাউন্টে ${usd_val:.2f} USD ডিপোজিট যোগ হয়েছে।</b>")
                except Exception:
                    send_message(chat_id, "❌ <b>ভুল ইনপুট!</b>")
                del user_states[user_id]
                return

            elif isinstance(state_data, str) and state_data.startswith("ADMIN_REFUND_USER_"):
                target_user = int(state_data.replace("ADMIN_REFUND_USER_", ""))
                try:
                    usd_val = float(text)
                    add_refund_balance(target_user, usd_val)
                    send_message(chat_id, f"✅ <b>User ID {target_user}-কে ${usd_val:.2f} USD রিফান্ড করা হয়েছে।</b>")
                    send_message(target_user, f"🎉 <b>এডমিন আপনার অ্যাকাউন্টে ${usd_val:.2f} USD রিফান্ড করেছেন!</b>")
                except Exception:
                    send_message(chat_id, "❌ <b>ভুল ইনপুট!</b>")
                del user_states[user_id]
                return

            elif isinstance(state_data, str) and state_data == "ADMIN_BROADCAST":
                all_users = get_all_users()
                success, failed = 0, 0
                for u_id in all_users:
                    try:
                        res = send_message(u_id, text)
                        if res.get("ok"): success += 1
                        else: failed += 1
                    except Exception: failed += 1
                send_message(chat_id, f"✅ <b>ব্রডকাস্ট সম্পন্ন!</b>\n🎯 সফল: {success}\n❌ ব্যর্থ: {failed}", reply_markup=get_main_keyboard(is_admin))
                del user_states[user_id]
                return

         # Main Command Handlers
        if text == "/start":
            welcome_text = f"👋 <b>Welcome {html.escape(first_name)}!</b>\n\nনিচের মেনু থেকে সার্ভিস বেছে নিন:"
            send_message(chat_id, welcome_text, reply_markup=get_main_keyboard(is_admin))

        elif text in ["🛒 BUY NUMBER", "📱 GET NUMBER"]:
            markup = {
                "inline_keyboard": [
                    [{"text": f"🇺🇸 Buy USA WhatsApp Number (${current_price:.2f} USD)", "callback_data": "confirm_buy_usa", "style": "success"}]
                ]
            }
            send_message(chat_id, f"<b>WhatsApp Service Selected:</b>\n\nমূল্য: <b>${current_price:.2f} USD / Number</b>", reply_markup=get_back_keyboard())
            send_message(chat_id, "সার্ভিস অপশন:", reply_markup=markup)

        elif text == "💳 DEPOSIT":
            dep_text = f"💳 <b>Deposit Options</b>\n\n<i>নোট: ৳{int(bdt_per_usd)} BDT = $1.00 USD কনভার্ট হবে।</i>\n\nআপনার সুবিধাজনক মেথড বেছে নিন:"
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
            bal = u_info["balance"] if u_info else 0.0
            tot = u_info["total_recharge"] if u_info else 0.0
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
            status_str = "🟢 ON" if is_bot_active() else "🔴 OFF"
            msg = (
                "<b>⚙️ ADMIN PANEL</b>\n\n"
                f"🤖 <b>Bot Status:</b> {status_str}\n"
                f"💰 <b>WhatsApp Number Price:</b> ${current_price:.2f} USD\n"
                f"💱 <b>Exchange Rate:</b> 1 USD = ৳{int(bdt_per_usd)} BDT"
            )
            markup = {
                "inline_keyboard": [
                    [{"text": f"🔘 Toggle Bot Status ({status_str})", "callback_data": "admin_toggle_bot", "style": "danger"}],
                    [{"text": "👥 USER MANAGEMENT", "callback_data": "admin_view_users", "style": "success"}],
                    [{"text": "➕ Bulk Add Users (ID/Username)", "callback_data": "admin_bulk_users", "style": "primary"}],
                    [{"text": "💱 Change BDT Exchange Rate", "callback_data": "admin_set_bdt_rate", "style": "primary"}],
                    [{"text": "🏷️ Change WhatsApp Price", "callback_data": "admin_set_rate", "style": "primary"}],
                    [{"text": "📢 Broadcast Message", "callback_data": "admin_broadcast", "style": "primary"}],
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
        is_admin = (user_id == ADMIN_ID)

        try:
            requests.post(BASE_URL + "answerCallbackQuery", data={"callback_query_id": cb_id}, timeout=5)
        except Exception: pass

        if data == "verify_force_join":
            if check_force_join(user_id):
                edit_message(chat_id, message_id, "✅ <b>ভেরিফিকেশন সফল হয়েছে!</b>\nএখন আপনি বটটি ব্যবহার করতে পারেন।")
                send_message(chat_id, "মূল মেনু:", reply_markup=get_main_keyboard(is_admin))
            else:
                send_message(chat_id, "❌ <b>আপনি এখনও সবগুলো চ্যানেলে জয়েন করেননি!</b>\nঅনুগ্রহ করে সব চ্যানেলে জয়েন করে আবার ভেরিফাই করুন।")
            return

        current_price = get_number_price()

        if data == "confirm_buy_usa":
            if not is_bot_active() and not is_admin:
                edit_message(chat_id, message_id, "⚠️ <b>এডমিন বর্তমানে বট বন্ধ রেখেছেন।</b>")
                return

            u_info = get_user(user_id)
            bal = u_info["balance"] if u_info else 0.0

            if bal < current_price:
                edit_message(chat_id, message_id, f"❌ <b>পর্যাপ্ত ব্যালেন্স নেই!</b>\nকমপক্ষে ${current_price:.2f} USD প্রয়োজন।")
                return

            phone, link = pop_stock_item()
            if not phone:
                edit_message(chat_id, message_id, "⚠️ <b>দুঃখিত! বর্তমানে স্টক ফাঁকা রয়েছে।</b>")
                return

            deduct_balance(user_id, current_price)
            save_active_order(user_id, phone, link)

            markup = {
                "inline_keyboard": [
                    [{"text": "🔄 Check OTP", "callback_data": f"chk_otp_{phone}", "style": "primary"}],
                    [{"text": "🛒 Buy Another Number", "callback_data": "confirm_buy_usa", "style": "success"}]
                ]
            }
            res_text = (
                f"✅ <b>নম্বর বরাদ্দ করা হয়েছে!</b>\n\n"
                f"📱 <b>USA Number:</b> <code>{phone}</code>\n"
                f"🔗 <b>OTP Link:</b> {link}\n"
                f"💰 <b>ফি কাটা হয়েছে:</b> ${current_price:.2f} USD\n\n"
                f"👉 <b>Check OTP</b> বাটনে চাপ দিন।"
            )
            send_message(chat_id, res_text, reply_markup=markup)
            send_message(chat_id, "<b>মূল মেনু:</b>", reply_markup=get_main_keyboard(is_admin))

        elif data.startswith("chk_otp_"):
            phone = data.replace("chk_otp_", "")
            order = get_order_by_phone(phone)
            
            if order:
                link = order["otp_link"]
                otp_code = None
                
                try:
                    headers = {
                        "User-Agent": "Mozilla/5.0",
                        "Accept": "*/*",
                        "Cache-Control": "no-cache"
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
                    print(f"OTP Error: {e}")

                if otp_code:
                    update_order_otp(phone, otp_code)
                    markup = {"inline_keyboard": [[{"text": "🛒 Buy Another Number", "callback_data": "confirm_buy_usa", "style": "success"}]]}
                    send_message(chat_id, f"📥 <b>আপনার OTP:</b> <code>{otp_code}</code>", reply_markup=markup)
                    
                    # 📢 ওটিপি গ্রুপে নোটিফিকেশন পাঠানো (গ্রুপ প্রাইভেসির জন্য মাস্কিং)
                    if OTP_GROUP_ID:
                        masked_num = mask_phone_number(phone)
                        group_msg = f"🎉 <b>New OTP Received!</b>\n\n📱 <b>Number:</b> <code>{masked_num}</code>\n🔑 <b>OTP Code:</b> <code>{otp_code}</code>"
                        send_message(OTP_GROUP_ID, group_msg)
                else:
                    send_message(chat_id, "⌛ <b>OTP এখনও আসেনি!</b> কিছুক্ষণ পর আবার চেক করুন।")

        # Admin Actions
        elif data == "admin_toggle_bot" and is_admin:
            new_st = "OFF" if is_bot_active() else "ON"
            toggle_bot_status(new_st)
            edit_message(chat_id, message_id, f"⚙️ <b>বটের স্ট্যাটাস পরিবর্তন করা হয়েছে:</b> {new_st}")

        elif data == "admin_bulk_users" and is_admin:
            user_states[user_id] = "ADMIN_BULK_ADD_USERS"
            send_message(chat_id, "➕ <b>ইউজারদের ID অথবা Username দিন:</b>\n(একসাথে একাধিক দিতে স্পেস বা নতুন লাইন ব্যবহার করুন। উদাহরণ: <code>12345678 @username2 87654321</code>)", reply_markup=get_back_keyboard())

        elif data == "admin_set_bdt_rate" and is_admin:
            user_states[user_id] = "ADMIN_SET_BDT_RATE"
            send_message(chat_id, f"💱 <b>নতুন ১ ডলারের BDT রেট লিখে পাঠান:</b>\n(বর্তমান রেট: ৳{get_bdt_rate()} BDT)", reply_markup=get_back_keyboard())

        elif data == "admin_view_users" and is_admin:
            users_list = get_all_users_info()
            if not users_list:
                send_message(chat_id, "❌ <b>কোনো ইউজার নেই।</b>")
                return

            buttons = []
            for u in users_list:
                u_id, u_name, u_bal = u["user_id"], u.get("username", "NoUsername"), u.get("balance", 0.0)
                display_title = f"👤 @{u_name} (${u_bal:.2f})" if u_name != "NoUsername" else f"👤 ID: {u_id} (${u_bal:.2f})"
                buttons.append([{"text": display_title, "callback_data": f"inspect_u_{u_id}", "style": "primary"}])

            markup = {"inline_keyboard": buttons}
            send_message(chat_id, f"👥 <b>বটের ইউজারের তালিকা (মোট: {len(users_list)} জন):</b>", reply_markup=markup)

        elif data.startswith("inspect_u_") and is_admin:
            target_u_id = int(data.replace("inspect_u_", ""))
            u_info = get_user(target_u_id)
            orders = get_user_orders_24h(target_u_id)
            
            user_msg = (
                f"👤 <b>USER DETAILS & HISTORY (LAST 24 HOURS)</b>\n\n"
                f"🆔 <b>User ID:</b> <code>{u_info['user_id']}</code>\n"
                f"👤 <b>Username:</b> @{u_info.get('username', 'N/A')}\n"
                f"💰 <b>Current Balance:</b> ${u_info.get('balance', 0.0):.2f} USD\n"
                f"📊 <b>Total Recharge:</b> ${u_info.get('total_recharge', 0.0):.2f} USD\n"
                f"🛒 <b>Purchased Numbers (Last 24h):</b> {len(orders)} টি\n\n"
            )
            for idx, ord_item in enumerate(orders, 1):
                otp_c = ord_item.get("otp_code")
                status = f"✅ OTP Received ({otp_c})" if otp_c else "❌ OTP Pending"
                user_msg += f"<b>{idx}.</b> 📱 <code>{ord_item['phone_number']}</code>\n   📅 Date: {ord_item['purchase_date']}\n   🔗 Link: {ord_item['otp_link']}\n   📌 Status: {status}\n\n"

            markup = {
                "inline_keyboard": [
                    [{"text": f"➕ Add / Refund Balance", "callback_data": f"admin_ref_input_{target_u_id}", "style": "success"}],
                    [{"text": "⬅️ Back", "callback_data": "admin_view_users", "style": "primary"}]
                ]
            }
            send_message(chat_id, user_msg, reply_markup=markup)

        elif data.startswith("admin_ref_input_") and is_admin:
            target_u_id = int(data.replace("admin_ref_input_", ""))
            user_states[user_id] = f"ADMIN_REFUND_USER_{target_u_id}"
            send_message(chat_id, f"➕ <b>User ID {target_u_id}-এর অ্যাকাউন্টে ডলার ($) অ্যামাউন্ট লিখুন:</b>", reply_markup=get_back_keyboard())

        elif data == "dep_bkash":
            user_states[user_id] = {"step": "WAITING_AMOUNT", "method": "BKASH"}
            send_message(chat_id, f"💖 <b>bKash Deposit</b>\n\nকত টাকা (BDT) ডিপোজিট করবেন লিখে পাঠান:\n<i>(রেট: ৳{int(get_bdt_rate())} BDT = $1.00 USD)</i>", reply_markup=get_back_keyboard())

        elif data == "dep_nagad":
            user_states[user_id] = {"step": "WAITING_AMOUNT", "method": "NAGAD"}
            send_message(chat_id, f"🟠 <b>Nagad Deposit</b>\n\nকত টাকা (BDT) ডিপোজিট করবেন লিখে পাঠান:\n<i>(রেট: ৳{int(get_bdt_rate())} BDT = $1.00 USD)</i>", reply_markup=get_back_keyboard())

        elif data == "dep_binance":
            user_states[user_id] = {"step": "WAITING_AMOUNT", "method": "BINANCE"}
            send_message(chat_id, "🟡 <b>Binance Deposit</b>\n\nকত <b>USDT</b> (USD) ডিপোজিট করবেন লিখে পাঠান:", reply_markup=get_back_keyboard())

        elif data == "admin_set_rate" and is_admin:
            user_states[user_id] = "ADMIN_SET_PRICE"
            send_message(chat_id, f"🏷️ <b>WhatsApp নম্বরের নতুন মূল্য ($ USD) লিখে পাঠান:</b>", reply_markup=get_back_keyboard())

        elif data == "admin_broadcast" and is_admin:
            user_states[user_id] = "ADMIN_BROADCAST"
            send_message(chat_id, "📢 <b>বার্তাটি লিখে পাঠান:</b>", reply_markup=get_back_keyboard())

        elif data == "admin_upload_file" and is_admin:
            user_states[user_id] = "ADMIN_UPLOAD_FILE"
            send_message(chat_id, "📁 <b>ফাইলটি (.txt / .csv) পাঠান:</b>", reply_markup=get_back_keyboard())

        elif data == "admin_view_stock" and is_admin:
            stock_items = get_all_stock()
            if not stock_items:
                send_message(chat_id, "📊 <b>বর্তমানে স্টক ফাঁকা!</b>")
            else:
                stock_text = f"📊 <b>বর্তমান স্টক (মোট: {len(stock_items)} টি):</b>\n\n"
                for item in stock_items[:30]:
                    stock_text += f"📱 <code>{item['phone_number']}</code>\n🔗 {item['otp_link']}\n\n"
                send_message(chat_id, stock_text)

        elif data == "admin_delete_stock_confirm" and is_admin:
            markup = {"inline_keyboard": [[{"text": "✅ Yes, Delete All", "callback_data": "admin_delete_stock_execute", "style": "danger"}]]}
            edit_message(chat_id, message_id, "⚠️ <b>সমস্ত স্টক মুছে ফেলতে চান?</b>", reply_markup=markup)

        elif data == "admin_delete_stock_execute" and is_admin:
            clear_all_stock()
            edit_message(chat_id, message_id, "🗑️ <b>সমস্ত স্টক ডিলিট করা হয়েছে!</b>")

        elif data.startswith("appusd_") and is_admin:
            parts = data.split("_")
            target_user = int(parts[1])
            usd_val = float(parts[2])
            update_balance(target_user, usd_val)
            send_message(chat_id, f"✅ <b>User ID {target_user}-কে ${usd_val:.2f} USD যোগ করা হয়েছে!</b>")
            send_message(target_user, f"🎉 <b>আপনার ডিপোজিট সফল হয়েছে! ${usd_val:.2f} USD যোগ করা হয়েছে।</b>")

        elif data.startswith("dep_app_") and is_admin:
            target_user = int(data.replace("dep_app_", ""))
            user_states[user_id] = f"ADMIN_APPROVE_AMOUNT_{target_user}"
            send_message(chat_id, f"<b>User ID {target_user}-এর জন্য ডলার অ্যামাউন্ট লিখুন:</b>")

        elif data.startswith("dep_rej_") and is_admin:
            target_user = int(data.replace("dep_rej_", ""))
            send_message(target_user, f"❌ <b>ডিপোজিট প্রুফটি সঠিক নয়!</b>")
            send_message(chat_id, f"❌ <b>User ID {target_user}-এর ডিপোজিট বাতিল করা হয়েছে।</b>")

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, use_reloader=False)

# ব্যাকগ্রাউন্ড থ্রেডে Flask সার্ভার চালু করা
threading.Thread(target=run_flask, daemon=True).start()

# টেলিগ্রাম Webhook ক্লিয়ার করা (W বড় হাতের হতে হবে)
try:
    requests.get(BASE_URL + "deleteWebhook?drop_pending_updates=True")
    print("Cleaned existing webhooks.")
except Exception as e:
    print(f"Error clearing webhook: {e}")

print("🚀 Bot Engine Online with MongoDB Cloud Storage...")

# টেলিগ্রাম থেকে মেসেজ রিসিভ করার লুপ
offset = 0
while True:
    try:
        res = requests.get(
            BASE_URL + "getUpdates", params={"offset": offset, "timeout": 20}
        ).json()
        if res.get("ok"):
            for update in res.get("result", []):
                offset = update["update_id"] + 1
                threading.Thread(
                    target=safe_execution_wrapper, args=(update,)
                ).start()
    except Exception as e:
        print(f"Polling Network Recovering... {e}")
        time.sleep(3)
        
