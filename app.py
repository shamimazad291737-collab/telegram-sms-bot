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
    return "Bot is running perfectly with MongoDB!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# Environment Variables
TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0")) if os.environ.get("ADMIN_ID") else 0
SUPPORT_USERNAME = os.environ.get("SUPPORT_USERNAME", "telegram")
OTP_GROUP_ID = os.environ.get("OTP_GROUP_ID", "")
MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")

BASE_URL = f"https://api.telegram.org/bot{TOKEN}/"

# MongoDB Database Connection
mongo_client = MongoClient(MONGO_URI)
db = mongo_client["telegram_otp_bot"]

users_col = db["users"]
stock_col = db["stock"]
orders_col = db["active_orders"]
settings_col = db["settings"]

# Default Settings Setup
def init_settings():
    if not settings_col.find_one({"key": "number_price"}):
        settings_col.insert_one({"key": "number_price", "value": "0.10"})
    if not settings_col.find_one({"key": "bdt_per_usd"}):
        settings_col.insert_one({"key": "bdt_per_usd", "value": "120.0"})
    if not settings_col.find_one({"key": "force_channels"}):
        settings_col.insert_one({"key": "force_channels", "channels": []})
    if not settings_col.find_one({"key": "bot_status"}):
        settings_col.insert_one({"key": "bot_status", "value": "ON"})

init_settings()

BKASH_NUMBER = "01858582881 (Personal)"
NAGAD_NUMBER = "01858582881 (Personal)"
BINANCE_PAY_ID = "907194603"

user_states = {}

# Helper Functions
def mask_phone_number(phone):
    clean_phone = phone.strip()
    if len(clean_phone) > 6:
        mid = len(clean_phone) // 2
        return clean_phone[:mid-1] + "RX" + clean_phone[mid+1:]
    return clean_phone

def get_bot_status():
    doc = settings_col.find_one({"key": "bot_status"})
    return doc["value"] if doc else "ON"

def set_bot_status(status):
    settings_col.update_one({"key": "bot_status"}, {"$set": {"value": status}}, upsert=True)

def get_number_price():
    doc = settings_col.find_one({"key": "number_price"})
    return float(doc["value"]) if doc else 0.10

def set_number_price(new_price):
    settings_col.update_one({"key": "number_price"}, {"$set": {"value": str(new_price)}}, upsert=True)

def get_bdt_per_usd():
    doc = settings_col.find_one({"key": "bdt_per_usd"})
    return float(doc["value"]) if doc else 120.0

def set_bdt_per_usd(new_rate):
    settings_col.update_one({"key": "bdt_per_usd"}, {"$set": {"value": str(new_rate)}}, upsert=True)

def get_force_channels():
    doc = settings_col.find_one({"key": "force_channels"})
    return doc.get("channels", []) if doc else []

def set_force_channels(channels_list):
    settings_col.update_one({"key": "force_channels"}, {"$set": {"channels": channels_list}}, upsert=True)

def get_all_users_info():
    users = list(users_col.find())
    return [(u["user_id"], u.get("username", "NoUsername"), u.get("balance", 0.0)) for u in users]

def get_all_users():
    return [u["user_id"] for u in users_col.find({}, {"user_id": 1})]

def get_all_stock():
    stocks = list(stock_col.find())
    return [(str(s["_id"]), s["phone_number"], s["otp_link"]) for s in stocks]

def clear_all_stock():
    stock_col.delete_many({})

def get_user(user_id):
    u = users_col.find_one({"user_id": user_id})
    if u:
        return (u["user_id"], u.get("username", "NoUsername"), u.get("balance", 0.0), u.get("total_recharge", 0.0))
    return None

def add_user(user_id, username):
    users_col.update_one(
        {"user_id": user_id},
        {"$setOnInsert": {"balance": 0.0, "total_recharge": 0.0}, "$set": {"username": username}},
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

def save_active_order(user_id, phone, link):
    now_str = datetime.now().strftime("%d-%b-%Y %I:%M %p")
    orders_col.insert_one({
        "user_id": user_id,
        "phone_number": phone,
        "otp_link": link,
        "otp_code": None,
        "purchase_date": now_str,
        "created_at": datetime.now()
    })

def update_order_otp(phone, otp_code):
    orders_col.update_one({"phone_number": phone}, {"$set": {"otp_code": otp_code}})

def get_user_orders_24h(user_id):
    rows = list(orders_col.find({"user_id": user_id}).sort("_id", -1))
    recent_orders = []
    now = datetime.now()
    for row in rows:
        try:
            p_date = datetime.strptime(row["purchase_date"], "%d-%b-%Y %I:%M %p")
            if now - p_date <= timedelta(hours=24):
                recent_orders.append((row["phone_number"], row.get("otp_code"), row["purchase_date"], row["otp_link"]))
        except Exception:
            recent_orders.append((row["phone_number"], row.get("otp_code"), row["purchase_date"], row["otp_link"]))
    return recent_orders

def get_order_by_phone(phone):
    row = orders_col.find_one({"phone_number": phone}, sort=[("_id", -1)])
    if row:
        return (str(row["_id"]), row["user_id"], row["otp_link"])
    return None

# Telegram API Requests
def send_message(chat_id, text, reply_markup=None):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        return requests.post(BASE_URL + "sendMessage", json=payload, timeout=10).json()
    except Exception as e:
        print(f"Error sending message: {e}")
        return {}

def edit_message(chat_id, message_id, text, reply_markup=None):
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        requests.post(BASE_URL + "editMessageText", json=payload, timeout=10)
    except Exception as e:
        print(f"Error editing message: {e}")

def send_photo_to_admin(chat_id, photo_file_id, caption, reply_markup=None):
    payload = {"chat_id": chat_id, "photo": photo_file_id, "caption": caption, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        requests.post(BASE_URL + "sendPhoto", json=payload, timeout=10)
    except Exception as e:
        print(f"Error sending photo: {e}")

def check_channel_member(user_id, channel_input):
    try:
        ch = channel_input.strip()
        if "t.me/" in ch:
            ch = "@" + ch.split("t.me/")[-1].replace("/", "")
        elif not ch.startswith("@") and not ch.startswith("-100"):
            ch = "@" + ch
        res = requests.post(BASE_URL + "getChatMember", json={"chat_id": ch, "user_id": user_id}, timeout=5).json()
        if res.get("ok"):
            status = res["result"]["status"]
            return status in ["creator", "administrator", "member"]
    except Exception as e:
        print(f"Check channel error: {e}")
    return False

def verify_force_join(user_id):
    channels = get_force_channels()
    if not channels:
        return True, []
    not_joined = []
    for ch in channels:
        if not check_channel_member(user_id, ch):
            not_joined.append(ch)
    return len(not_joined) == 0, not_joined

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
    # Block Group Execution (Only Private Chat Allowed)
    msg_data = update.get("message") or update.get("callback_query", {}).get("message")
    if msg_data:
        chat_type = msg_data.get("chat", {}).get("type", "")
        if chat_type in ["group", "supergroup"]:
            return

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
        bdt_rate = get_bdt_per_usd()
        bot_active = (get_bot_status() == "ON")

        # Handle Back Button Globally
        if text in ["⬅️ Back", "🔙 Back"]:
            if user_id in user_states:
                del user_states[user_id]
            send_message(chat_id, "<b>মূল মেনুতে ফিরে আসা হয়েছে:</b>", reply_markup=get_main_keyboard(is_admin))
            return

        # Check Bot OFF Status for Normal Users
        if not is_admin and not bot_active:
            send_message(chat_id, "⚠️ <b>সাময়িক সময়ের জন্য বট আপডেট করা হচ্ছে!</b>\nআপনারা একটু ধৈর্য ধরুন, এরপর জানিয়ে দেওয়া হবে। আপাতত কেউ ডিপোজিট বা নম্বর ক্রয় করবেন না। 🛑")
            return

        # Force Join Verification Guard for Normal Users
        if not is_admin:
            is_joined, missing = verify_force_join(user_id)
            if not is_joined:
                buttons = []
                for idx, ch in enumerate(missing, 1):
                    clean_ch = ch.strip()
                    if clean_ch.startswith("http://") or clean_ch.startswith("https://"):
                        link = clean_ch
                    elif "t.me/" in clean_ch:
                        link = clean_ch if clean_ch.startswith("http") else f"https://{clean_ch}"
                    else:
                        link = f"https://t.me/{clean_ch.replace('@', '')}"
                    
                    buttons.append([{"text": f"📢 Join Channel {idx}", "url": link}])
                
                buttons.append([{"text": "🔄 Verify Join", "callback_data": "verify_join"}])
                
                send_message(
                    chat_id, 
                    "⚠️ <b>বটটি ব্যবহার করতে নিচের ২টি চ্যানেলে জয়েন করুন:</b>\nসবগুলো চ্যানেলে জয়েন করার পর Verify Join বোতামে চাপ দিন।", 
                    reply_markup={"inline_keyboard": buttons}
                )
                return

        # Input State Handling
        if user_id in user_states:
            state_data = user_states[user_id]
            
            # Change Exchange Rate
            if is_admin and state_data == "ADMIN_SET_EXCHANGE":
                try:
                    new_rate = float(text)
                    set_bdt_per_usd(new_rate)
                    send_message(chat_id, f"✅ <b>ডলার এক্সচেঞ্জ রেট সফলভাবে পরিবর্তন করা হয়েছে!</b>\nবর্তমান রেট: 1 USD = ৳{new_rate:.2f} BDT", reply_markup=get_main_keyboard(is_admin))
                except ValueError:
                    send_message(chat_id, "❌ <b>ভুল ইনপুট!</b> সঠিক সংখ্যা লিখুন (যেমন: 120.0)।")
                del user_states[user_id]
                return

            # Change Number Price
            if is_admin and state_data == "ADMIN_SET_PRICE":
                try:
                    new_pr = float(text)
                    set_number_price(new_pr)
                    send_message(chat_id, f"✅ <b>হোয়াটসঅ্যাপ নম্বরের নতুন মূল্য সেট করা হয়েছে: ${new_pr:.2f} USD</b>", reply_markup=get_main_keyboard(is_admin))
                except ValueError:
                    send_message(chat_id, "❌ <b>ভুল ইনপুট!</b> সঠিক সংখ্যা লিখুন (যেমন: 0.10)।")
                del user_states[user_id]
                return

            # Dynamic Force Join Set (Strict 2 Channels Option)
            if is_admin and state_data == "ADMIN_SET_CHANNELS":
                ch_list = [c.strip() for c in text.split(",") if c.strip()]
                if len(ch_list) > 2:
                    send_message(chat_id, "❌ <b>সর্বোচ্চ ২টি চ্যানেল লিঙ্ক বা ইউজারনেম দিতে পারবেন!</b>\nকমা (,) দিয়ে ২টি লিঙ্ক বা ইউজারনেম দিন।")
                    return
                set_force_channels(ch_list)
                send_message(chat_id, f"✅ <b>ফোর্স জয়েন চ্যানেল ২ টি সেট করা হয়েছে!</b>\nচ্যানেলসমূহ: {', '.join(ch_list)}", reply_markup=get_main_keyboard(is_admin))
                del user_states[user_id]
                return

            # Deposit Step 1: Amount
            if isinstance(state_data, dict) and state_data.get("step") == "WAITING_AMOUNT":
                method = state_data["method"]
                try:
                    amount = float(text)
                    if amount <= 0:
                        send_message(chat_id, "❌ <b>সঠিক পরিমাণ উল্লেখ করুন!</b>")
                        return
                    
                    user_states[user_id] = {"step": "WAITING_TRX", "method": method, "amount": amount}

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

            # Deposit Step 2: TrxID
            elif isinstance(state_data, dict) and state_data.get("step") == "WAITING_TRX":
                user_states[user_id] = {
                    "step": "WAITING_SCREENSHOT",
                    "method": state_data["method"],
                    "amount": state_data["amount"],
                    "trx_id": text
                }
                send_message(chat_id, "📸 <b>ধন্যবাদ! এবার পেমেন্টের একটি স্পষ্ট স্ক্রিনশট (Photo) পাঠান:</b>", reply_markup=get_back_keyboard())
                return

            # Deposit Step 3: Screenshot
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
                        converted_usd = round(amount / bdt_rate, 2)
                        amount_info = f"৳{amount:.2f} BDT (Estimated: ${converted_usd:.2f} USD @ {int(bdt_rate)} BDT/$)"

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
                        f"যাচাই করে ডলারে যোগ করতে নিচের বাটন প্রেস করুন:"
                    )
                    
                    send_photo_to_admin(ADMIN_ID, photo_file_id, admin_caption, reply_markup=admin_markup)
                    send_message(chat_id, "✅ <b>আপনার তথ্য ও স্ক্রিনশট অ্যাডমিনের কাছে পাঠানো হয়েছে!</b>\nযাচাই করার পর অ্যাকাউন্টে ডলার ব্যালেন্স যোগ করা হবে।", reply_markup=get_main_keyboard(is_admin))
                    del user_states[user_id]
                    return
                else:
                    send_message(chat_id, "❌ <b>অনুগ্রহ করে পেমেন্টের একটি ছবি/স্ক্রিনশট পাঠান।</b>", reply_markup=get_back_keyboard())
                    return

            # Admin File Upload
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

            # Admin Custom Deposit Input
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

            # Admin Refund Input
            elif isinstance(state_data, str) and state_data.startswith("ADMIN_REFUND_USER_"):
                target_user = int(state_data.replace("ADMIN_REFUND_USER_", ""))
                try:
                    usd_val = float(text)
                    add_refund_balance(target_user, usd_val)
                    send_message(chat_id, f"✅ <b>User ID {target_user}-কে ${usd_val:.2f} USD রিফান্ড/ব্যালেন্স যোগ করে দেওয়া হয়েছে।</b>", reply_markup=get_main_keyboard(is_admin))
                    send_message(target_user, f"🎉 <b>এডমিন আপনার অ্যাকাউন্টে ${usd_val:.2f} USD রিফান্ড/ব্যালেন্স যোগ করেছেন!</b>")
                except Exception:
                    send_message(chat_id, "❌ <b>ভুল অ্যামাউন্ট!</b> কেবল ডলারে সংখ্যা লিখুন। (যেমন: 0.10 বা 1.50)")
                del user_states[user_id]
                return

            # Admin Broadcast
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

        # Main Keyboards Handling
        if text == "/start":
            welcome_text = f"👋 <b>Welcome {html.escape(first_name)}!</b>\n\nনিচের মেনু থেকে সার্ভিস সিলেক্ট করুন:"
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
            dep_text = f"💳 <b>Deposit Options</b>\n\n<i>নোট: ৳{int(bdt_rate)} BDT = $1.00 USD ডাইনামিক কনভার্ট হবে।</i>\n\nআপনার সুবিধাজনক পেমেন্ট মেথডটি বেছে নিন:"
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
                f"👤 <b>Your Profile Information</b>\n\n"
                f"🆔 <b>User ID:</b> <code>{user_id}</code>\n"
                f"💰 <b>Current Balance:</b> ${bal:.2f} USD\n"
                f"📊 <b>Total Recharge:</b> ${tot:.2f} USD"
            )
            send_message(chat_id, prof_text, reply_markup=get_back_keyboard())

        elif text == "🎧 SUPPORT":
            send_message(chat_id, f"<b>যেকোনো সাহায্যে যোগাযোগ করুন:</b>\n👉 @{SUPPORT_USERNAME}", reply_markup=get_back_keyboard())

        elif text == "⚙️ ADMIN PANEL" and is_admin:
            chans = get_force_channels()
            chan_str = ", ".join(chans) if chans else "None"
            status_str = "🟢 ONLINE" if bot_active else "🔴 OFF / MAINTENANCE"
            msg = (
                "<b>⚙️ ADMIN PANEL</b>\n\n"
                f"🤖 <b>Bot Status:</b> {status_str}\n"
                f"💰 <b>WhatsApp Price:</b> ${current_price:.2f} USD\n"
                f"💱 <b>Exchange Rate:</b> 1 USD = ৳{int(bdt_rate)} BDT\n"
                f"📢 <b>Force Channels (Max 2):</b> {chan_str}"
            )
            
            toggle_btn = {"text": "🔴 Turn OFF Bot", "callback_data": "admin_toggle_bot_off", "style": "danger"} if bot_active else {"text": "🟢 Turn ON Bot", "callback_data": "admin_toggle_bot_on", "style": "success"}

            markup = {
                "inline_keyboard": [
                    [toggle_btn],
                    [{"text": "👥 USER MANAGEMENT", "callback_data": "admin_view_users", "style": "success"}],
                    [{"text": "🏷️ Change WhatsApp Price", "callback_data": "admin_set_rate", "style": "primary"}],
                    [{"text": "💱 Change Exchange Rate", "callback_data": "admin_set_exchange", "style": "primary"}],
                    [{"text": "📢 Dynamic Force Join (2 Channels)", "callback_data": "admin_set_channels", "style": "success"}],
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
        bot_active = (get_bot_status() == "ON")

        try:
            requests.post(BASE_URL + "answerCallbackQuery", data={"callback_query_id": cb_id}, timeout=5)
        except Exception:
            pass

        # Check Bot OFF Status for Callbacks (Non-Admin)
        if not is_admin and not bot_active and data != "verify_join":
            send_message(chat_id, "⚠️ <b>সাময়িক সময়ের জন্য বট বন্ধ রয়েছে!</b>\nএডমিন বট চালু করলে সেবা গ্রহণ করতে পারবেন।")
            return

        current_price = get_number_price()
        bdt_rate = get_bdt_per_usd()

        # Bot Status Toggle Callback
        if data == "admin_toggle_bot_off" and is_admin:
            set_bot_status("OFF")
            send_message(chat_id, "🔴 <b>বট সফলভাবে বন্ধ করা হয়েছে!</b>\nইউজাররা এখন আর নম্বর কেনা বা ডিপোজিট রিকোয়েস্ট দিতে পারবে না।")

        elif data == "admin_toggle_bot_on" and is_admin:
            set_bot_status("ON")
            send_message(chat_id, "🟢 <b>বট সফলভাবে চালু করা হয়েছে!</b>\nইউজাররা স্বাভাবিকভাবে বট ব্যবহার করতে পারবে।")

        elif data == "verify_join":
            is_joined, _ = verify_force_join(user_id)
            if is_joined:
                send_message(chat_id, "✅ <b>ধন্যবাদ! ভেরিফিকেশন সফল হয়েছে।</b>\nএখন বট ব্যবহার করতে পারবেন।", reply_markup=get_main_keyboard(is_admin))
            else:
                send_message(chat_id, "❌ <b>আপনি এখনও সবগুলো চ্যানেলে জয়েন করেননি!</b>\nদয়া করে ২টি চ্যানেলেই জয়েন করে আবার ট্রাই করুন।")

        elif data == "confirm_buy_usa":
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
                f"👉 নম্বরটি অ্যাপে ব্যবহার করার পর <b>Check OTP</b> বাটনে চাপ দিন।"
            )
            
            send_message(chat_id, res_text, reply_markup=markup)
            send_message(chat_id, "<b>মূল মেনু:</b>", reply_markup=get_main_keyboard(is_admin))

         # OTP Dynamic Scraping
        elif data.startswith("chk_otp_"):
            phone = data.replace("chk_otp_", "")
            order = get_order_by_phone(phone)
            
            if order:
                link = order[2]
                otp_code = None
                
                try:
                    headers = {
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
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
                    print(f"OTP Scraping Error: {e}")

                if otp_code:
                    update_order_otp(phone, otp_code)
                    markup = {
                        "inline_keyboard": [
                            [{"text": "🛒 Buy Another Number", "callback_data": "confirm_buy_usa", "style": "success"}]
                        ]
                    }
                    send_message(chat_id, f"📥 <b>আপনার OTP:</b> <code>{otp_code}</code>", reply_markup=markup)
                    
                    if OTP_GROUP_ID:
                        masked_num = mask_phone_number(phone)
                        group_msg = (
                            f"🎉 <b>New OTP Received!</b>\n\n"
                            f"📱 <b>Number:</b> <code>{masked_num}</code>\n"
                            f"🔑 <b>OTP Code:</b> <code>{otp_code}</code>"
                        )
                        send_message(OTP_GROUP_ID, group_msg)
                else:
                    send_message(chat_id, "⌛ <b>OTP এখনও আসেনি!</b> অনুগ্রহ করে কিছুক্ষণ পর আবার Check OTP চাপুন।")

        # Admin View All Users
        elif data == "admin_view_users" and is_admin:
            users_list = get_all_users_info()
            if not users_list:
                send_message(chat_id, "❌ <b>বটে এখনও কোনো ইউজার রেজিস্টার করেনি।</b>")
                return

            buttons = []
            for u in users_list:
                u_id, u_name, u_bal = u[0], u[1], u[2]
                display_title = f"👤 @{u_name} (${u_bal:.2f})" if u_name != "NoUsername" else f"👤 ID: {u_id} (${u_bal:.2f})"
                buttons.append([{"text": display_title, "callback_data": f"inspect_u_{u_id}", "style": "primary"}])

            markup = {"inline_keyboard": buttons}
            send_message(chat_id, f"👥 <b>বটের সমস্ত ইউজারের তালিকা (মোট: {len(users_list)} জন):</b>\nইউজারের ডিটেইলস ও নম্বর হিস্ট্রি দেখতে তার নামের ওপর ক্লিক করুন:", reply_markup=markup)

        # Admin Inspect Specific User History
        elif data.startswith("inspect_u_") and is_admin:
            target_u_id = int(data.replace("inspect_u_", ""))
            u_info = get_user(target_u_id)
            
            if not u_info:
                send_message(chat_id, "❌ <b>ইউজার পাওয়া যায়নি!</b>")
                return

            orders = get_user_orders_24h(target_u_id)
            user_msg = (
                f"👤 <b>USER DETAILS & HISTORY (LAST 24 HOURS)</b>\n\n"
                f"🆔 <b>User ID:</b> <code>{u_info[0]}</code>\n"
                f"👤 <b>Username:</b> @{u_info[1]}\n"
                f"💰 <b>Current Balance:</b> ${u_info[2]:.2f} USD\n"
                f"📊 <b>Total Recharge:</b> ${u_info[3]:.2f} USD\n"
                f"🛒 <b>Purchased Numbers (Last 24h):</b> {len(orders)} টি\n\n"
                f"<b>📋 গত ২৪ ঘণ্টার ক্রয়ের হিস্ট্রি, লিংক ও OTP স্ট্যাটাস:</b>\n"
            )

            if not orders:
                user_msg += "<i>এই ইউজার গত ২৪ ঘণ্টায় কোনো নম্বর কেনেনি।</i>\n"
            else:
                for idx, ord_item in enumerate(orders, 1):
                    p_num, otp_c, p_date, otp_l = ord_item[0], ord_item[1], ord_item[2], ord_item[3]
                    status = f"✅ OTP Received ({otp_c})" if otp_c else "❌ OTP Pending / Not Received"
                    user_msg += f"<b>{idx}.</b> 📱 <code>{p_num}</code>\n   📅 Date: {p_date}\n   🔗 Link: {otp_l}\n   📌 Status: {status}\n\n"

            markup = {
                "inline_keyboard": [
                    [{"text": f"➕ Add / Refund Balance to @{u_info[1]}", "callback_data": f"admin_ref_input_{target_u_id}", "style": "success"}],
                    [{"text": "⬅️ Back to User List", "callback_data": "admin_view_users", "style": "primary"}]
                ]
            }
            send_message(chat_id, user_msg, reply_markup=markup)

        # Admin Controls Callback Setup
        elif data == "admin_set_exchange" and is_admin:
            user_states[user_id] = "ADMIN_SET_EXCHANGE"
            send_message(chat_id, f"💱 <b>নতুন BDT to USD রেট লিখে পাঠান:</b>\n(যেমন: 120, 122, 125 ইত্যাদি। বর্তমান রেট: ৳{int(bdt_rate)})", reply_markup=get_back_keyboard())

        elif data == "admin_set_channels" and is_admin:
            user_states[user_id] = "ADMIN_SET_CHANNELS"
            send_message(chat_id, "📢 <b>ফোর্স জয়েন চ্যানেল ২ টি লিঙ্ক বা ইউজারনেম দিন:</b>\n(সর্বোচ্চ ২টি, কমা দিয়ে দিন। যেমন: `@channel1, @channel2` অথবা `https://t.me/link1, https://t.me/link2`)", reply_markup=get_back_keyboard())

        elif data.startswith("admin_ref_input_") and is_admin:
            target_u_id = int(data.replace("admin_ref_input_", ""))
            user_states[user_id] = f"ADMIN_REFUND_USER_{target_u_id}"
            send_message(chat_id, f"➕ <b>User ID {target_u_id}-এর অ্যাকাউন্টে কত $ (USD) রিফান্ড/যোগ করতে চান লিখে পাঠান:</b>\n(যেমন: 0.10, 0.20 বা 1.00)", reply_markup=get_back_keyboard())

        elif data == "dep_bkash":
            user_states[user_id] = {"step": "WAITING_AMOUNT", "method": "BKASH"}
            send_message(chat_id, f"💖 <b>bKash Deposit Selected</b>\n\nকত টাকা (BDT) ডিপোজিট করতে চান লিখে পাঠান:\n<i>(রেট: ৳{int(bdt_rate)} BDT = $1.00 USD)</i>", reply_markup=get_back_keyboard())

        elif data == "dep_nagad":
            user_states[user_id] = {"step": "WAITING_AMOUNT", "method": "NAGAD"}
            send_message(chat_id, f"🟠 <b>Nagad Deposit Selected</b>\n\nকত টাকা (BDT) ডিপোজিট করতে চান লিখে পাঠান:\n<i>(রেট: ৳{int(bdt_rate)} BDT = $1.00 USD)</i>", reply_markup=get_back_keyboard())

        elif data == "dep_binance":
            user_states[user_id] = {"step": "WAITING_AMOUNT", "method": "BINANCE"}
            send_message(chat_id, "🟡 <b>Binance Deposit Selected</b>\n\nকত <b>USDT</b> (USD) ডিপোজিট করতে চান লিখে পাঠান:", reply_markup=get_back_keyboard())

        elif data == "admin_set_rate" and is_admin:
            user_states[user_id] = "ADMIN_SET_PRICE"
            send_message(chat_id, f"🏷️ <b>WhatsApp নম্বরের নতুন মূল্য ($ USD) লিখে পাঠান:</b>\n(বর্তমান রেট: ${current_price:.2f} USD)", reply_markup=get_back_keyboard())

        elif data == "admin_broadcast" and is_admin:
            user_states[user_id] = "ADMIN_BROADCAST"
            send_message(chat_id, "📢 <b>সব ইউজারদের উদ্দেশ্যে পাঠানোর বার্তাটি লিখে পাঠান:</b>", reply_markup=get_back_keyboard())

        elif data == "admin_upload_file" and is_admin:
            user_states[user_id] = "ADMIN_UPLOAD_FILE"
            send_message(chat_id, "📁 <b>নম্বর সম্বলিত ফাইলটি (.txt / .csv) এখানে পাঠাও:</b>\nফরম্যাট:\n<code>+1234567890, https://otp-link.com/check</code>", reply_markup=get_back_keyboard())

        elif data == "admin_view_stock" and is_admin:
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

        elif data == "admin_delete_stock_confirm" and is_admin:
            markup = {"inline_keyboard": [[{"text": "✅ Yes, Delete All", "callback_data": "admin_delete_stock_execute", "style": "danger"}]]}
            edit_message(chat_id, message_id, "⚠️ <b>আপনি কি নিশ্চিতভাবে সমস্ত স্টক ফাইল/নম্বর মুছে ফেলতে চান?</b>", reply_markup=markup)

        elif data == "admin_delete_stock_execute" and is_admin:
            clear_all_stock()
            edit_message(chat_id, message_id, "🗑️ <b>সফলভাবে সমস্ত স্টকে থাকা নম্বর ও লিংক ডিলিট করা হয়েছে!</b>")

        elif data.startswith("appusd_") and is_admin:
            parts = data.split("_")
            target_user = int(parts[1])
            usd_val = float(parts[2])
            update_balance(target_user, usd_val)
            send_message(chat_id, f"✅ <b>User ID {target_user}-এর অ্যাকাউন্টে সফলভাবে ${usd_val:.2f} USD যোগ করা হয়েছে!</b>")
            send_message(target_user, f"🎉 <b>আপনার ডিপোজিট প্রসেস সফল হয়েছে! ${usd_val:.2f} USD অ্যাকাউন্টে যোগ করা হয়েছে।</b>")

        elif data.startswith("dep_app_") and is_admin:
            target_user = int(data.replace("dep_app_", ""))
            user_states[user_id] = f"ADMIN_APPROVE_AMOUNT_{target_user}"
            send_message(chat_id, f"<b>User ID {target_user}-এর অ্যাকাউন্টে কত $ (USD) যোগ করতে চান লিখে পাঠান:</b>")

        elif data.startswith("dep_rej_") and is_admin:
            target_user = int(data.replace("dep_rej_", ""))
            send_message(target_user, f"❌ <b>আপনার জমা দেওয়া ডিপোজিট প্রুফটি সঠিক নয়!</b>\nদয়া করে সঠিক তথ্য দিন বা সাপোর্ট অ্যাডমিনের সাথে কথা বলুন: @{SUPPORT_USERNAME}")
            send_message(chat_id, f"❌ <b>User ID {target_user}-এর ডিপোজিট বাতিল করা হয়েছে।</b>")

def safe_execution_wrapper(upd):
    try:
        handle_update(upd)
    except Exception as e:
        print(f"Exception Handled Safety: {e}")

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()

    print("🚀 Bot Engine Online with Dynamic On/Off Switch & MongoDB...")
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
