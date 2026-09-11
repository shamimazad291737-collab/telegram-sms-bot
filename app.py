import os
import requests
import html
import threading
import time
import re
from datetime import datetime, timedelta
from flask import Flask
from pymongo import MongoClient

# Language Detector Function with custom shortcodes
def detect_language(text):
    if not text:
        return "EN"
    # Chinese Character Range
    if re.search(r'[\u4e00-\u9fff]', text):
        return "ZH"
    # Arabic Character Range
    elif re.search(r'[\u0600-\u06FF]', text):
        return "AR"
    # Cyrillic / Russian Range
    elif re.search(r'[\u0400-\u04FF]', text):
        return "RU"
    # Hindi Range
    elif re.search(r'[\u0900-\u097F]', text):
        return "HI"
    # Latin / English Range
    elif re.search(r'[a-zA-Z]', text):
        return "EN"
    return "EN"

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

# Custom Premium Emoji HTML Tags
WA_EMOJI = '<tg-emoji emoji-id="5427009714745507009">🟢</tg-emoji>'
USDT_EMOJI = '<tg-emoji emoji-id="5427009714745507009">💵</tg-emoji>'
FIRE_EMOJI = '<tg-emoji emoji-id="5427009714745507009">🔥</tg-emoji>'

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

def get_buyers_list():
    buyer_ids = orders_col.distinct("user_id")
    buyers = list(users_col.find({"user_id": {"$in": buyer_ids}}))
    return [(u["user_id"], u.get("username", "NoUsername"), u.get("balance", 0.0)) for u in buyers]

def get_user_by_username(username):
    clean_username = username.replace("@", "").strip()
    u = users_col.find_one({"username": {"$regex": f"^{clean_username}$", "$options": "i"}})
    if u:
        return (u["user_id"], u.get("username", "NoUsername"), u.get("balance", 0.0), u.get("total_recharge", 0.0))
    return None

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
        "app_type": None,
        "lang": None,
        "purchase_date": now_str,
        "created_at": datetime.now()
    })

def update_order_otp(phone, otp_code, app_type="WA", lang="EN"):
    orders_col.update_one(
        {"phone_number": phone}, 
        {"$set": {"otp_code": otp_code, "app_type": app_type, "lang": lang}}
    )

def get_user_orders_count(user_id):
    return orders_col.count_documents({"user_id": user_id})

def get_user_orders_all(user_id):
    rows = list(orders_col.find({"user_id": user_id}).sort("_id", -1))
    all_orders = []
    for row in rows:
        all_orders.append((
            row["phone_number"], 
            row.get("otp_code"), 
            row["purchase_date"], 
            row["otp_link"], 
            row.get("app_type", "WA"), 
            row.get("lang", "EN")
        ))
    return all_orders

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
            path = ch.split("t.me/")[-1].replace("/", "")
            if path.startswith("+") or path.startswith("joinchat"):
                ch = path 
            else:
                ch = "@" + path
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

# Admin Panel Inline Keyboard Builder (Single Popup Container)
def get_admin_inline_keyboard(panel_type="main", extra_data=None):
    bot_active = (get_bot_status() == "ON")
    toggle_btn = {"text": "🔴 Turn OFF Bot", "callback_data": "admin_toggle_bot_off"} if bot_active else {"text": "🟢 Turn ON Bot", "callback_data": "admin_toggle_bot_on"}
    
    if panel_type == "main":
        return {
            "inline_keyboard": [
                [toggle_btn],
                [{"text": "👥 USER MANAGEMENT", "callback_data": "admin_user_mgmt_menu"}],
                [{"text": "🏷️ Change WhatsApp Price", "callback_data": "admin_set_rate"}],
                [{"text": "💱 Change Exchange Rate", "callback_data": "admin_set_exchange"}],
                [{"text": "📢 Dynamic Force Join (2 Channels)", "callback_data": "admin_set_channels"}],
                [{"text": "📢 Broadcast Message", "callback_data": "admin_broadcast"}],
                [{"text": "📁 Upload Stock File", "callback_data": "admin_upload_file"}],
                [{"text": "📊 View Current Stock", "callback_data": "admin_view_stock"}],
                [{"text": "🗑️ Delete All Stock", "callback_data": "admin_delete_stock_confirm"}]
            ]
        }
    elif panel_type == "user_mgmt":
        return {
            "inline_keyboard": [
                [{"text": "👥 All User View", "callback_data": "admin_view_users"}],
                [{"text": "🛒 Active Buyers List", "callback_data": "admin_view_buyers"}],
                [{"text": "🔎 Search User & Refund", "callback_data": "admin_search_user_btn"}],
                [{"text": "⬅️ Back to Admin Main", "callback_data": "admin_main_menu"}]
            ]
        }
    return {"inline_keyboard": []}

# Helper to automatically update OTP from link even without explicit button press
def sync_otp_status(phone, link):
    order = get_order_by_phone(phone)
    if not order:
        return None
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "*/*",
            "Cache-Control": "no-cache"
        }
        api_link = link.replace("/sms/", "/api/sms/") if "/sms/" in link else link
        response = requests.get(api_link, headers=headers, timeout=5)
        api_text = response.text.strip()
        raw_response_text = api_text
        otp_code = None

        if re.match(r'^\d{3,10}$', api_text):
            otp_code = api_text
        else:
            main_res = requests.get(link, headers=headers, timeout=5)
            raw_response_text = main_res.text
            matches = re.findall(r'\b\d{6}\b', main_res.text)
            clean_phone = re.sub(r'\D', '', phone)
            for code in matches:
                if code not in ['111111', '000000', '123456'] and code not in clean_phone:
                    otp_code = code
                    break

        if otp_code:
            app_type = "WB" if ("business" in raw_response_text.lower() or "smb" in raw_response_text.lower()) else "WA"
            detected_lang = detect_language(raw_response_text)
            update_order_otp(phone, otp_code, app_type=app_type, lang=detected_lang)
            return otp_code, detected_lang, app_type
    except Exception:
        pass
    return None

# Core Update Handler
def handle_update(update):
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

        if text in ["⬅️ Back", "🔙 Back"]:
            if user_id in user_states:
                del user_states[user_id]
            send_message(chat_id, "<b>মূল মেনুতে ফিরে আসা হয়েছে:</b>", reply_markup=get_main_keyboard(is_admin))
            return

        if not is_admin and not bot_active:
            send_message(chat_id, "⚠️ <b>সাময়িক সময়ের জন্য বট আপডেট করা হচ্ছে!</b>\nআপনারা একটু ধৈর্য ধরুন, এরপর জানিয়ে দেওয়া হবে। আপাতত কেউ ডিপোজিট বা নম্বর ক্রয় করবেন না। 🛑")
            return

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

        if user_id in user_states:
            state_data = user_states[user_id]
            
            if isinstance(state_data, str) and state_data == "BUY_MULTI_QTY":
                try:
                    qty = int(text)
                    if qty <= 0:
                        send_message(chat_id, "❌ <b>সঠিক সংখ্যা লিখুন (কমপক্ষে ১ টি)।</b>")
                        return
                    
                    u_info = get_user(user_id)
                    bal = u_info[2] if u_info else 0.0
                    total_cost = current_price * qty

                    if bal < total_cost:
                        send_message(chat_id, f"❌ <b>পর্যাপ্ত ব্যালেন্স নেই!</b>\n{qty} টি নম্বর কিনতে ${total_cost:.2f} USD লাগবে। আপনার ব্যালেন্স: ${bal:.2f} USD।")
                        del user_states[user_id]
                        return

                    stock_items = get_all_stock()
                    if len(stock_items) < qty:
                        send_message(chat_id, f"⚠️ <b>দুঃখিত! স্টকে পর্যাপ্ত নম্বর নেই।</b>\nবর্তমানে স্টকে {len(stock_items)} টি নম্বর খালি রয়েছে।")
                        del user_states[user_id]
                        return

                    purchased_list = []
                    for _ in range(qty):
                        phone, link = pop_stock_item()
                        if phone:
                            deduct_balance(user_id, current_price)
                            save_active_order(user_id, phone, link)
                            purchased_list.append((phone, link))

                    del user_states[user_id]
                    
                    res_msg = f"✅ <b>সফলভাবে {len(purchased_list)} টি নম্বর কেনা হয়েছে!</b>\n\n"
                    for idx, (p, l) in enumerate(purchased_list, 1):
                        res_msg += f"<b>{idx}.</b> {WA_EMOJI} <code>{p}</code> | 🔗 {l}\n"
                    
                    res_msg += f"\n{USDT_EMOJI} <b>মোট ফি কাটা হয়েছে:</b> ${current_price * len(purchased_list):.2f} USD\n👉 যেকোনো একটির ওটিপি পেতে <b>Check OTP</b> বাটনে চাপ দিন।"
                    
                    multi_btns = []
                    for p, l in purchased_list[:10]:
                        multi_btns.append([{"text": f"🔄 Check OTP ({p})", "callback_data": f"chk_otp_{p}"}])
                    
                    send_message(chat_id, res_msg, reply_markup={"inline_keyboard": multi_btns})
                    send_message(chat_id, "<b>মূল মেনু:</b>", reply_markup=get_main_keyboard(is_admin))
                    return

                except ValueError:
                    send_message(chat_id, "❌ <b>ভুল ইনপুট!</b> কেবল পূর্ণসংখ্যা লিখুন (যেমন: 2, 5, 10)।")
                    return

            if is_admin and isinstance(state_data, str) and state_data == "ADMIN_SEARCH_USER":
                u_info = get_user_by_username(text)
                if not u_info:
                    send_message(chat_id, f"❌ <b>'{text}' ইউজারনেমে কোনো ইউজার খুঁজে পাওয়া যায়নি!</b>", reply_markup=get_main_keyboard(is_admin))
                    del user_states[user_id]
                    return

                target_u_id = u_info[0]
                orders = get_user_orders_all(target_u_id)
                
                search_res = (
                    f"🔎 <b>USER SEARCH RESULT</b>\n\n"
                    f"👤 <b>Username:</b> @{u_info[1]}\n"
                    f"🆔 <b>User ID:</b> <code>{target_u_id}</code>\n"
                    f"💰 <b>Current Balance:</b> ${u_info[2]:.2f} USD\n"
                    f"📊 <b>Total Recharge:</b> ${u_info[3]:.2f} USD\n"
                    f"🛒 <b>Total Purchased Numbers:</b> {len(orders)} টি\n"
                )

                markup = {
                    "inline_keyboard": [
                        [{"text": f"➕ Add / Refund Balance to @{u_info[1]}", "callback_data": f"admin_ref_input_{target_u_id}"}]
                    ]
                }
                send_message(chat_id, search_res, reply_markup=markup)
                del user_states[user_id]
                return

            if is_admin and state_data == "ADMIN_SET_EXCHANGE":
                try:
                    new_rate = float(text)
                    set_bdt_per_usd(new_rate)
                    send_message(chat_id, f"✅ <b>ডলার এক্সচেঞ্জ রেট সফলভাবে পরিবর্তন করা হয়েছে!</b>\nবর্তমান রেট: 1 USD = ৳{new_rate:.2f} BDT", reply_markup=get_main_keyboard(is_admin))
                except ValueError:
                    send_message(chat_id, "❌ <b>ভুল ইনপুট!</b> সঠিক সংখ্যা লিখুন (যেমন: 120.0)।")
                del user_states[user_id]
                return

            if is_admin and state_data == "ADMIN_SET_PRICE":
                try:
                    new_pr = float(text)
                    set_number_price(new_pr)
                    send_message(chat_id, f"✅ <b>হোয়াটসঅ্যাপ নম্বরের নতুন মূল্য সেট করা হয়েছে: ${new_pr:.2f} USD</b>", reply_markup=get_main_keyboard(is_admin))
                except ValueError:
                    send_message(chat_id, "❌ <b>ভুল ইনপুট!</b> সঠিক সংখ্যা লিখুন (যেমন: 0.10)।")
                del user_states[user_id]
                return

            if is_admin and state_data == "ADMIN_SET_CHANNELS":
                ch_list = [c.strip() for c in text.split(",") if c.strip()]
                if len(ch_list) > 2:
                    send_message(chat_id, "❌ <b>সর্বোচ্চ ২টি চ্যানেল লিঙ্ক বা ইউজারনেম দিতে পারবেন!</b>\nকমা (,) দিয়ে ২টি লিঙ্ক বা ইউজারনেম দিন।")
                    return
                set_force_channels(ch_list)
                send_message(chat_id, f"✅ <b>ফোর্স জয়েন চ্যানেল ২ টি সেট করা হয়েছে!</b>\nচ্যানেলসমূহ: {', '.join(ch_list)}", reply_markup=get_main_keyboard(is_admin))
                del user_states[user_id]
                return

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

            elif isinstance(state_data, dict) and state_data.get("step") == "WAITING_TRX":
                user_states[user_id] = {
                    "step": "WAITING_SCREENSHOT",
                    "method": state_data["method"],
                    "amount": state_data["amount"],
                    "trx_id": text
                }
                send_message(chat_id, "📸 <b>ধন্যবাদ! এবার পেমেন্টের একটি স্পষ্ট স্ক্রিনশট (Photo) পাঠান:</b>", reply_markup=get_back_keyboard())
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
                        converted_usd = round(amount / bdt_rate, 2)
                        amount_info = f"৳{amount:.2f} BDT (Estimated: ${converted_usd:.2f} USD @ {int(bdt_rate)} BDT/$)"

                    usd_str_clean = f"{converted_usd:.2f}"
                    admin_markup = {
                        "inline_keyboard": [
                            [
                                {"text": f"✅ Auto Approve (${converted_usd:.2f})", "callback_data": f"appusd_{user_id}_{usd_str_clean}"},
                                {"text": "✏️ Custom Amount", "callback_data": f"dep_app_{user_id}"}
                            ],
                            [{"text": "❌ Reject Request", "callback_data": f"dep_rej_{user_id}"}]
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

        if text == "/start":
            welcome_text = f"👋 <b>Welcome {html.escape(first_name)}!</b>\n\nনিচের মেনু থেকে সার্ভিস সিলেক্ট করুন:"
            send_message(chat_id, welcome_text, reply_markup=get_main_keyboard(is_admin))

        elif text in ["🛒 BUY NUMBER", "📱 GET NUMBER"]:
            markup = {
                "inline_keyboard": [
                    [{"text": f"👤 Buy Single Number (${current_price:.2f})", "callback_data": "confirm_buy_usa"}],
                    [{"text": "🔢 Buy Multiple Numbers", "callback_data": "buy_multi_num"}]
                ]
            }
            send_message(chat_id, f"<b>{WA_EMOJI} WhatsApp Service Selected:</b>\n\nমূল্য: <b>${current_price:.2f} USD / Number</b>", reply_markup=get_back_keyboard())
            send_message(chat_id, "সার্ভিস অপশন বেছে নিন:", reply_markup=markup)

        elif text == "💳 DEPOSIT":
            dep_text = f"💳 <b>Deposit Options</b>\n\n<i>নোট: ৳{int(bdt_rate)} BDT = $1.00 USD ডাইনামিক কনভার্ট হবে।</i>\n\nআপনার সুবিধাজনক পেমেন্ট মেথডটি বেছে নিন:"
            markup = {
                "inline_keyboard": [
                    [{"text": "💖 bKash (BDT)", "callback_data": "dep_bkash"}],
                    [{"text": "🟠 Nagad (BDT)", "callback_data": "dep_nagad"}],
                    [{"text": f"{USDT_EMOJI} Binance (Crypto USDT)", "callback_data": "dep_binance"}]
                ]
            }
            send_message(chat_id, dep_text, reply_markup=get_back_keyboard())
            send_message(chat_id, "পেমেন্ট গেটওয়ে:", reply_markup=markup)

        elif text == "👤 PROFILE":
            u_info = get_user(user_id)
            bal = u_info[2] if u_info else 0.0
            tot = u_info[3] if u_info else 0.0
            total_purchased = get_user_orders_count(user_id)
            
            prof_text = (
                f"👤 <b>Your Profile Information</b>\n\n"
                f"🆔 <b>User ID:</b> <code>{user_id}</code>\n"
                f"{USDT_EMOJI} <b>Current Balance:</b> ${bal:.2f} USD\n"
                f"📊 <b>Total Deposit:</b> ${tot:.2f} USD\n"
                f"🛒 <b>Total Purchased Numbers:</b> {total_purchased} টি"
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
            
            send_message(chat_id, "এডমিন প্যানেলে স্বাগতম:", reply_markup=get_back_keyboard())
            send_message(chat_id, msg, reply_markup=get_admin_inline_keyboard("main"))

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

        if not is_admin and not bot_active and data != "verify_join":
            send_message(chat_id, "⚠️ <b>সাময়িক সময়ের জন্য বট বন্ধ রয়েছে!</b>\nএডমিন বট চালু করলে সেবা গ্রহণ করতে পারবেন।")
            return

        current_price = get_number_price()
        bdt_rate = get_bdt_per_usd()

        # Navigation Callbacks inside Same Window Popup
        if data == "admin_main_menu" and is_admin:
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
            edit_message(chat_id, message_id, msg, reply_markup=get_admin_inline_keyboard("main"))

        elif data == "admin_toggle_bot_off" and is_admin:
            set_bot_status("OFF")
            edit_message(chat_id, message_id, "🔴 <b>বট সফলভাবে বন্ধ করা হয়েছে!</b>", reply_markup=get_admin_inline_keyboard("main"))

        elif data == "admin_toggle_bot_on" and is_admin:
            set_bot_status("ON")
            edit_message(chat_id, message_id, "🟢 <b>বট সফলভাবে চালু করা হয়েছে!</b>", reply_markup=get_admin_inline_keyboard("main"))

        elif data == "verify_join":
            is_joined, _ = verify_force_join(user_id)
            if is_joined:
                send_message(chat_id, "✅ <b>ধন্যবাদ! ভেরিফিকেশন সফল হয়েছে।</b>\nএখন বট ব্যবহার করতে পারবেন।", reply_markup=get_main_keyboard(is_admin))
            else:
                send_message(chat_id, "❌ <b>আপনি এখনও সবগুলো চ্যানেলে জয়েন করেননি!</b>\nদয়া করে ২টি চ্যানেলেই জয়েন করে আবার ট্রাই করুন।")

        elif data == "buy_multi_num":
            user_states[user_id] = "BUY_MULTI_QTY"
            send_message(chat_id, "🔢 <b>আপনি কতগুলো নম্বর কিনতে চান লিখে পাঠান:</b>\n(যেমন: 2, 5, 10 ইত্যাদি)", reply_markup=get_back_keyboard())

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
                    [{"text": "🔄 Check OTP", "callback_data": f"chk_otp_{phone}"}],
                    [{"text": "🛒 Buy Another Number", "callback_data": "confirm_buy_usa"}]
                ]
            }
            res_text = (
                f"✅ <b>নম্বর বরাদ্দ করা হয়েছে!</b>\n\n"
                f"{WA_EMOJI} <b>USA Number:</b> <code>{phone}</code>\n"
                f"🔗 <b>OTP Link:</b> {link}\n"
                f"{USDT_EMOJI} <b>ফি কাটা হয়েছে:</b> ${current_price:.2f} USD\n\n"
                f"👉 নম্বরটি অ্যাপে ব্যবহার করার পর <b>Check OTP</b> বাটনে চাপ দিন।"
            )
            
            send_message(chat_id, res_text, reply_markup=markup)
            send_message(chat_id, "<b>মূল মেনু:</b>", reply_markup=get_main_keyboard(is_admin))

        elif data.startswith("chk_otp_"):
            phone = data.replace("chk_otp_", "")
            order = get_order_by_phone(phone)
            
            if order:
                link = order[2]
                res = sync_otp_status(phone, link)

                if res:
                    otp_code, detected_lang, app_type = res
                    markup = {
                        "inline_keyboard": [
                            [{"text": "🛒 Buy Another Number", "callback_data": "confirm_buy_usa"}]
                        ]
                    }
                    
                    otp_msg = (
                        f"<b>Your WhatsApp Code ({app_type})</b>\n\n"
                        f"🔑 <b>OTP:</b> <code>{otp_code}</code>\n"
                        f"🌐 <b>Language:</b> <code>[{detected_lang}]</code>"
                    )
                    send_message(chat_id, otp_msg, reply_markup=markup)
                    
                    if OTP_GROUP_ID:
                        masked_num = mask_phone_number(phone)
                        group_msg = (
                            f"{FIRE_EMOJI} <b>New OTP Received! ({app_type})</b>\n\n"
                            f"{WA_EMOJI} <b>Number:</b> <code>{masked_num}</code>\n"
                            f"🔑 <b>OTP Code:</b> <code>{otp_code}</code>\n"
                            f"🌐 <b>Language:</b> <code>[{detected_lang}]</code>"
                        )
                        send_message(OTP_GROUP_ID, group_msg)
                else:
                    send_message(chat_id, "⌛ <b>OTP এখনও আসেনি!</b> অনুগ্রহ করে কিছুক্ষণ পর আবার Check OTP চাপুন।")

        elif data == "admin_user_mgmt_menu" and is_admin:
            edit_message(chat_id, message_id, "<b>👥 USER MANAGEMENT OPTIONS:</b>\nএকটি অপশন বেছে নিন:", reply_markup=get_admin_inline_keyboard("user_mgmt"))

        elif data == "admin_view_users" and is_admin:
            users_list = get_all_users_info()
            if not users_list:
                send_message(chat_id, "❌ <b>বটে এখনও কোনো ইউজার রেজিস্টার করেনি।</b>")
                return

            buttons = []
            for u in users_list:
                u_id, u_name, u_bal = u[0], u[1], u[2]
                display_title = f"👤 @{u_name} (${u_bal:.2f})" if u_name != "NoUsername" else f"👤 ID: {u_id} (${u_bal:.2f})"
                buttons.append([{"text": display_title, "callback_data": f"inspect_u_{u_id}"}])
            
            buttons.append([{"text": "⬅️ Back", "callback_data": "admin_user_mgmt_menu"}])
            markup = {"inline_keyboard": buttons}
            edit_message(chat_id, message_id, f"👥 <b>বটের সমস্ত ইউজারের তালিকা (মোট: {len(users_list)} জন):</b>\nইউজারের ডিটেইলস দেখতে তার নামের ওপর ক্লিক করুন:", reply_markup=markup)

        elif data == "admin_view_buyers" and is_admin:
            buyers_list = get_buyers_list()
            if not buyers_list:
                send_message(chat_id, "❌ <b>এখনও কোনো ইউজার নম্বর কেনেনি।</b>")
                return

            buttons = []
            for u in buyers_list:
                u_id, u_name, u_bal = u[0], u[1], u[2]
                display_title = f"🛒 @{u_name} (${u_bal:.2f})" if u_name != "NoUsername" else f"🛒 ID: {u_id} (${u_bal:.2f})"
                buttons.append([{"text": display_title, "callback_data": f"inspect_buyer_{u_id}"}])

            buttons.append([{"text": "⬅️ Back", "callback_data": "admin_user_mgmt_menu"}])
            markup = {"inline_keyboard": buttons}
            edit_message(chat_id, message_id, f"🛒 <b>নম্বর ক্রয়কারী ইউজারদের তালিকা (মোট: {len(buyers_list)} জন):</b>\nকার কোন নম্বরে ওটিপি এসেছে তা দেখতে ক্লিক করুন:", reply_markup=markup)

        elif data == "admin_search_user_btn" and is_admin:
            user_states[user_id] = "ADMIN_SEARCH_USER"
            send_message(chat_id, "🔎 <b>ইউজারের Username টি লিখে পাঠান:</b>\n(যেমন: `@username` বা `username`)", reply_markup=get_back_keyboard())

        elif data.startswith("inspect_buyer_") and is_admin:
            target_u_id = int(data.replace("inspect_buyer_", ""))
            u_info = get_user(target_u_id)
            
            if not u_info:
                send_message(chat_id, "❌ <b>ইউজার পাওয়া যায়নি!</b>")
                return

            orders = get_user_orders_all(target_u_id)
            buyer_msg = (
                f"🛒 <b>BUYER DETAILED HISTORY</b>\n\n"
                f"🆔 <b>User ID:</b> <code>{u_info[0]}</code>\n"
                f"👤 <b>Username:</b> @{u_info[1]}\n"
                f"{USDT_EMOJI} <b>Current Balance:</b> ${u_info[2]:.2f} USD\n"
                f"📊 <b>Total Recharge:</b> ${u_info[3]:.2f} USD\n"
                f"🛒 <b>Total Purchased Numbers:</b> {len(orders)} টি\n\n"
                f"<b>📋 ক্রয়ের হিস্ট্রি ও OTP স্ট্যাটাস:</b>\n"
            )

            for idx, ord_item in enumerate(orders, 1):
                p_num, otp_c, p_date, otp_l, app_t, lang_t = ord_item[0], ord_item[1], ord_item[2], ord_item[3], ord_item[4], ord_item[5]
                
                # Auto Sync Check if OTP was received directly from link without clicking Check OTP
                if not otp_c:
                    sync_res = sync_otp_status(p_num, otp_l)
                    if sync_res:
                        otp_c, lang_t, app_t = sync_res

                status = f"✅ OTP Received ({otp_c}) [{app_t}]" if otp_c else "❌ OTP Pending / Not Received"
                buyer_msg += f"<b>{idx}.</b> {WA_EMOJI} <code>{p_num}</code>\n   📅 Date: {p_date}\n   📌 Status: {status}\n   🌐 Lang: [{lang_t}]\n\n"

            markup = {
                "inline_keyboard": [
                    [{"text": f"➕ Add / Refund Balance to @{u_info[1]}", "callback_data": f"admin_ref_input_{target_u_id}"}],
                    [{"text": "⬅️ Back to Buyers List", "callback_data": "admin_view_buyers"}]
                ]
            }
            edit_message(chat_id, message_id, buyer_msg, reply_markup=markup)

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
                f"{USDT_EMOJI} <b>Current Balance:</b> ${u_info[2]:.2f} USD\n"
                f"📊 <b>Total Recharge:</b> ${u_info[3]:.2f} USD\n"
                f"🛒 <b>Purchased Numbers (Last 24h):</b> {len(orders)} টি\n\n"
                f"<b>📋 গত ২৪ ঘণ্টার ক্রয়ের হিস্ট্রি, লিংক ও OTP স্ট্যাটাস:</b>\n"
            )

            if not orders:
                user_msg += "<i>এই ইউজার গত ২৪ ঘণ্টায় কোনো নম্বর কেনেনি।</i>\n"
            else:
                for idx, ord_item in enumerate(orders, 1):
                    p_num, otp_c, p_date, otp_l = ord_item[0], ord_item[1], ord_item[2], ord_item[3]
                    
                    if not otp_c:
                        sync_res = sync_otp_status(p_num, otp_l)
                        if sync_res:
                            otp_c = sync_res[0]

                    status = f"✅ OTP Received ({otp_c})" if otp_c else "❌ OTP Pending / Not Received"
                    user_msg += f"<b>{idx}.</b> {WA_EMOJI} <code>{p_num}</code>\n   📅 Date: {p_date}\n   🔗 Link: {otp_l}\n   📌 Status: {status}\n\n"

            markup = {
                "inline_keyboard": [
                    [{"text": f"➕ Add / Refund Balance to @{u_info[1]}", "callback_data": f"admin_ref_input_{target_u_id}"}],
                    [{"text": "⬅️ Back to User List", "callback_data": "admin_view_users"}]
                ]
            }
            edit_message(chat_id, message_id, user_msg, reply_markup=markup)

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
            send_message(chat_id, f"{USDT_EMOJI} <b>Binance Deposit Selected</b>\n\nকত <b>USDT</b> (USD) ডিপোজিট করতে চান লিখে পাঠান:", reply_markup=get_back_keyboard())

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
                edit_message(chat_id, message_id, "📊 <b>বর্তমানে স্টকে কোনো নম্বর খালি নেই!</b>", reply_markup=get_admin_inline_keyboard("main"))
            else:
                stock_text = f"📊 <b>বর্তমান স্টকে থাকা নম্বরসমূহ (মোট: {len(stock_items)} টি):</b>\n\n"
                for item in stock_items[:30]:
                    stock_text += f"{WA_EMOJI} <code>{item[1]}</code>\n🔗 {item[2]}\n\n"
                if len(stock_items) > 30:
                    stock_text += f"<i>...এবং আরও {len(stock_items) - 30} টি নম্বর রয়েছে।</i>"
                edit_message(chat_id, message_id, stock_text, reply_markup=get_admin_inline_keyboard("main"))

        elif data == "admin_delete_stock_confirm" and is_admin:
            markup = {"inline_keyboard": [
                [{"text": "✅ Yes, Delete All", "callback_data": "admin_delete_stock_execute"}],
                [{"text": "⬅️ Cancel", "callback_data": "admin_main_menu"}]
            ]}
            edit_message(chat_id, message_id, "⚠️ <b>আপনি কি নিশ্চিতভাবে সমস্ত স্টক ফাইল/নম্বর মুছে ফেলতে চান?</b>", reply_markup=markup)

        elif data == "admin_delete_stock_execute" and is_admin:
            clear_all_stock()
            edit_message(chat_id, message_id, "🗑️ <b>সফলভাবে সমস্ত স্টকে থাকা নম্বর ও লিংক ডিলিট করা হয়েছে!</b>", reply_markup=get_admin_inline_keyboard("main"))

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
