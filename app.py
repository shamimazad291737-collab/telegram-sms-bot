import os
import requests
import html
import threading
import time
import re
from datetime import datetime, timedelta
from flask import Flask
from pymongo import MongoClient

# Language Detector Function with expanded shortcodes mapping & fix
def detect_language(text):
    if not text:
        return "OTHERS"
    
    clean_text = text.lower().strip()
    
    # Direct shortcode matching
    if clean_text in ['en', 'eng', 'english', 'us', 'gb']:
        return "EN"
    elif clean_text in ['bn', 'ben', 'bengali']:
        return "BN"
    elif clean_text in ['hi', 'hin', 'hindi']:
        return "HI"
    elif clean_text in ['ar', 'arabic']:
        return "AR"
    elif clean_text in ['ru', 'russian']:
        return "RU"
    elif clean_text in ['zh', 'chinese', 'cn']:
        return "ZH"
    elif clean_text in ['es', 'spanish']:
        return "ES"
    elif clean_text in ['fr', 'french']:
        return "FR"

    # Regex character range checks
    if re.search(r'[\u4e00-\u9fff]', text):
        return "ZH"
    elif re.search(r'[\u0600-\u06FF]', text):
        return "AR"
    elif re.search(r'[\u0400-\u04FF]', text):
        return "RU"
    elif re.search(r'[\u0900-\u097F]', text):
        return "HI"
    elif re.search(r'[a-zA-Z]', text):
        return "EN"
    return "OTHERS"

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
vpn_stock_col = db["vpn_stock"]
vpn_orders_col = db["vpn_orders"]
orders_col = db["active_orders"]
settings_col = db["settings"]
user_states_col = db["user_states"] # Database state collection to fix state loss issue
refund_logs_col = db["refund_logs"] # Collection for Refund History

# Helper functions for MongoDB User States
def get_user_state(user_id):
    doc = user_states_col.find_one({"user_id": user_id})
    return doc.get("state") if doc else None

def set_user_state(user_id, state):
    user_states_col.update_one({"user_id": user_id}, {"$set": {"state": state}}, upsert=True)

def delete_user_state(user_id):
    user_states_col.delete_one({"user_id": user_id})

# Default Settings Setup
def init_settings():
    if not settings_col.find_one({"key": "number_price"}):
        settings_col.insert_one({"key": "number_price", "value": "0.10"})
    if not settings_col.find_one({"key": "nord_price"}):
        settings_col.insert_one({"key": "nord_price", "value": "1.00"})
    if not settings_col.find_one({"key": "proton_price"}):
        settings_col.insert_one({"key": "proton_price", "value": "1.00"})
    if not settings_col.find_one({"key": "bdt_per_usd"}):
        settings_col.insert_one({"key": "bdt_per_usd", "value": "120.0"})
    if not settings_col.find_one({"key": "force_channels"}):
        settings_col.insert_one({"key": "force_channels", "channels": []})
    if not settings_col.find_one({"key": "bot_status"}):
        settings_col.insert_one({"key": "bot_status", "value": "ON"})
    if not settings_col.find_one({"key": "rex_checker_link"}):
        settings_col.insert_one({"key": "rex_checker_link", "value": "https://t.me/rex_checker_bot"})
    if not settings_col.find_one({"key": "google_sheet_url"}):
        settings_col.insert_one({"key": "google_sheet_url", "value": ""})

init_settings()

BKASH_NUMBER = "01858582881 (Personal)"
NAGAD_NUMBER = "01858582881 (Personal)"
BINANCE_PAY_ID = "907194603"

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

def get_rex_checker_link():
    doc = settings_col.find_one({"key": "rex_checker_link"})
    return doc["value"] if doc else "https://t.me/rex_checker_bot"

def set_rex_checker_link(link):
    settings_col.update_one({"key": "rex_checker_link"}, {"$set": {"value": link}}, upsert=True)

def get_google_sheet_url():
    doc = settings_col.find_one({"key": "google_sheet_url"})
    return doc["value"] if doc else ""

def set_google_sheet_url(url):
    settings_col.update_one({"key": "google_sheet_url"}, {"$set": {"value": url}}, upsert=True)

def log_purchase_to_google_sheet(user_id, username, phone, otp_link, purchase_date, otp_code=None, order_id=None):
    """Send a purchase to the configured Google Apps Script webhook."""
    sheet_url = get_google_sheet_url()
    if not sheet_url:
        return False
    try:
        payload = {
            "action": "purchase",
            "user_id": str(user_id),
            "username": str(username),
            "phone": str(phone),
            "otp": str(otp_code) if otp_code else "",
            "otp_link": str(otp_link),
            "date": str(purchase_date)
        }
        response = requests.post(sheet_url, json=payload, timeout=10)
        if response.ok:
            if order_id:
                try:
                    orders_col.update_one({"_id": order_id}, {"$set": {"google_sheet_synced": True}})
                except Exception as e:
                    print(f"Google Sheet Sync Flag Error: {e}")
            try:
                result = response.json()
                gid = result.get("gid")
                if gid:
                    users_col.update_one(
                        {"user_id": user_id},
                        {"$set": {"google_sheet_gid": str(gid)}},
                        upsert=False
                    )
            except Exception:
                pass
            return True
        print(f"Google Sheet HTTP Error: {response.status_code}")
    except Exception as e:
        print(f"Google Sheet Logging Error: {e}")
    return False

def get_user_google_sheet_url(user_id):
    sheet_url = get_google_sheet_url()
    if not sheet_url:
        return ""
    u = users_col.find_one({"user_id": user_id}, {"google_sheet_gid": 1})
    gid = u.get("google_sheet_gid") if u else None
    return f"{sheet_url}#gid={gid}" if gid else sheet_url

def update_purchase_otp_in_google_sheet(user_id, phone, otp_code):
    """Update the OTP for the matching purchased number in the user's sheet."""
    sheet_url = get_google_sheet_url()
    if not sheet_url or not otp_code:
        return
    try:
        payload = {
            "action": "otp_update",
            "user_id": str(user_id),
            "phone": str(phone),
            "otp": str(otp_code)
        }
        response = requests.post(sheet_url, json=payload, timeout=10)
        if not response.ok:
            print(f"Google Sheet OTP Update HTTP Error: {response.status_code}")
    except Exception as e:
        print(f"Google Sheet OTP Update Error: {e}")

def sync_all_existing_orders_to_google_sheet():
    """Backfill MongoDB purchase history that has not yet been synced."""
    sheet_url = get_google_sheet_url()
    if not sheet_url:
        return 0, 0
    success = 0
    failed = 0
    try:
        rows = orders_col.find({"google_sheet_synced": {"$ne": True}}).sort("_id", 1)
        for row in rows:
            u = users_col.find_one({"user_id": row.get("user_id")})
            username = u.get("username", "NoUsername") if u else "NoUsername"
            if log_purchase_to_google_sheet(
                row.get("user_id"),
                username,
                row.get("phone_number", ""),
                row.get("otp_link", ""),
                row.get("purchase_date", ""),
                row.get("otp_code"),
                row.get("_id")
            ):
                success += 1
            else:
                failed += 1
        return success, failed
    except Exception as e:
        print(f"Google Sheet History Sync Error: {e}")
        return success, failed

def get_number_price():
    doc = settings_col.find_one({"key": "number_price"})
    return float(doc["value"]) if doc else 0.10

def set_number_price(new_price):
    settings_col.update_one({"key": "number_price"}, {"$set": {"value": str(new_price)}}, upsert=True)

def get_vpn_price(service):
    key = "nord_price" if service == "nord" else "proton_price"
    doc = settings_col.find_one({"key": key})
    return float(doc["value"]) if doc else 1.00

def set_vpn_price(service, new_price):
    key = "nord_price" if service == "nord" else "proton_price"
    settings_col.update_one({"key": key}, {"$set": {"value": str(new_price)}}, upsert=True)

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
    users = list(users_col.find({}, {"user_id": 1}))
    return [u["user_id"] for u in users if "user_id" in u]

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

def add_vpn_stock_item(service, account_data):
    vpn_stock_col.insert_one({"service": service, "account": account_data})

def get_vpn_stock_count(service):
    return vpn_stock_col.count_documents({"service": service})

def pop_vpn_stock_item(service):
    item = vpn_stock_col.find_one_and_delete({"service": service})
    if item:
        return item["account"]
    return None

def save_vpn_order(user_id, service, amount):
    now_str = datetime.now().strftime("%d-%b-%Y %I:%M %p")
    res = vpn_orders_col.insert_one({
        "user_id": user_id,
        "service": service,
        "amount": amount,
        "status": "PENDING",
        "date": now_str
    })
    return str(res.inserted_id)

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

def add_refund_balance(user_id, amount_usd, num_count=0):
    users_col.update_one(
        {"user_id": user_id},
        {"$inc": {"balance": amount_usd}}
    )
    u = get_user(user_id)
    username = u[1] if u else "NoUsername"
    now_str = datetime.now().strftime("%d-%b-%Y %I:%M %p")
    refund_logs_col.insert_one({
        "user_id": user_id,
        "username": username,
        "amount": amount_usd,
        "num_count": num_count,
        "date": now_str,
        "timestamp": datetime.now()
    })

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
    if otp_code:
        latest_order = orders_col.find_one({"phone_number": phone}, sort=[("_id", -1)])
        if latest_order:
            update_purchase_otp_in_google_sheet(
                latest_order.get("user_id"),
                phone,
                otp_code
            )

def get_user_orders_all(user_id):
    rows = list(orders_col.find({"user_id": user_id}).sort("_id", -1))
    all_orders = []
    for row in rows:
        all_orders.append((
            row["phone_number"], 
            row.get("otp_code"), 
            row.get("purchase_date", "N/A"), 
            row.get("otp_link", ""), 
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
            p_date = datetime.strptime(row.get("purchase_date", ""), "%d-%b-%Y %I:%M %p")
            if now - p_date <= timedelta(hours=24):
                recent_orders.append((
                    row["phone_number"], 
                    row.get("otp_code"), 
                    row.get("purchase_date", "N/A"), 
                    row.get("otp_link", ""),
                    row.get("app_type", "WA"),
                    row.get("lang", "EN")
                ))
        except Exception:
            recent_orders.append((
                row["phone_number"], 
                row.get("otp_code"), 
                row.get("purchase_date", "N/A"), 
                row.get("otp_link", ""),
                row.get("app_type", "WA"),
                row.get("lang", "EN")
            ))
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
        return requests.post(BASE_URL + "editMessageText", json=payload, timeout=10).json()
    except Exception as e:
        print(f"Error editing message: {e}")
        return {}

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
    rex_link = get_rex_checker_link()
    kb = [
        [
            {"text": "🛒 BUY NUMBER", "style": "success"},
            {"text": "🛡️ BUY VPN", "style": "primary"}
        ],
        [
            {"text": "💳 DEPOSIT", "style": "primary"},
            {"text": "👤 PROFILE", "style": "primary"}
        ],
        [
            {"text": "🔍 Rex Checker", "style": "primary"},
            {"text": "🎧 SUPPORT", "style": "primary"}
        ]
    ]
    if is_admin:
        kb.append([{"text": "⚙️ ADMIN PANEL", "style": "danger"}])
    return {"keyboard": kb, "resize_keyboard": True}

def get_back_keyboard():
    kb = [[{"text": "⬅️ Back", "style": "danger"}]]
    return {"keyboard": kb, "resize_keyboard": True}

# Helper for Admin Panel Main Text & Markup
def get_admin_panel_data():
    bot_active = (get_bot_status() == "ON")
    current_price = get_number_price()
    nord_pr = get_vpn_price("nord")
    proton_pr = get_vpn_price("proton")
    bdt_rate = get_bdt_per_usd()
    chans = get_force_channels()
    chan_str = ", ".join(chans) if chans else "None"
    rex_link = get_rex_checker_link()
    sheet_url = get_google_sheet_url() or "Not Set"
    status_str = "🟢 ONLINE" if bot_active else "🔴 OFF / MAINTENANCE"
    
    msg = (
        "<b>⚙️ ADMIN PANEL</b>\n\n"
        f"🤖 <b>Bot Status:</b> {status_str}\n"
        f"💰 <b>WhatsApp Price:</b> ${current_price:.2f} USD\n"
        f"🛡️ <b>NordVPN Price:</b> ${nord_pr:.2f} USD | <b>ProtonVPN Price:</b> ${proton_pr:.2f} USD\n"
        f"💱 <b>Exchange Rate:</b> 1 USD = ৳{int(bdt_rate)} BDT\n"
        f"🔍 <b>Rex Checker Link:</b> {rex_link}\n"
        f"📊 <b>Google Sheet Webhook URL:</b> {sheet_url}\n"
        f"📢 <b>Force Channels (Max 2):</b> {chan_str}"
    )
    
    toggle_btn = {"text": "🔴 Turn OFF Bot", "callback_data": "admin_toggle_bot_off", "style": "danger"} if bot_active else {"text": "🟢 Turn ON Bot", "callback_data": "admin_toggle_bot_on", "style": "success"}

    markup = {
        "inline_keyboard": [
            [toggle_btn],
            [{"text": "👥 USER MANAGEMENT", "callback_data": "admin_user_mgmt_menu", "style": "success"}],
            [{"text": "🏷️ Change WhatsApp Price", "callback_data": "admin_set_rate", "style": "primary"}],
            [{"text": "🛡️ Set NordVPN Price", "callback_data": "admin_set_nord_price", "style": "primary"}, {"text": "🛡️ Set ProtonVPN Price", "callback_data": "admin_set_proton_price", "style": "primary"}],
            [{"text": "🔍 Set Rex Checker Link", "callback_data": "admin_set_rex_link", "style": "primary"}],
            [{"text": "📊 Set Google Sheet URL", "callback_data": "admin_set_sheet_url", "style": "success"}],
            [{"text": "📁 Upload VPN Stock File", "callback_data": "admin_upload_vpn_file", "style": "success"}],
            [{"text": "💱 Change Exchange Rate", "callback_data": "admin_set_exchange", "style": "primary"}],
            [{"text": "📢 Dynamic Force Join (2 Channels)", "callback_data": "admin_set_channels", "style": "success"}],
            [{"text": "📢 Broadcast Message", "callback_data": "admin_broadcast", "style": "primary"}],
            [{"text": "📁 Upload Stock File", "callback_data": "admin_upload_file", "style": "success"}],
            [{"text": "📊 View Current Stock", "callback_data": "admin_view_stock", "style": "primary"}],
            [{"text": "🗑️ Delete All Stock", "callback_data": "admin_delete_stock_confirm", "style": "danger"}]
        ]
    }
    return msg, markup

# Helper Generator for Buyer Details with Pagination System
def render_buyer_page(target_u_id, page=1, items_per_page=10):
    u_info = get_user(target_u_id)
    if not u_info:
        return "❌ <b>ইউজার পাওয়া যায়নি!</b>", {"inline_keyboard": []}

    orders = get_user_orders_all(target_u_id)
    total_purchased = len(orders)
    otp_sent_count = sum(1 for o in orders if o[1])
    failed_count = total_purchased - otp_sent_count
    success_rate = (otp_sent_count / total_purchased * 100) if total_purchased > 0 else 0.0

    total_pages = (total_purchased + items_per_page - 1) // items_per_page
    if total_pages == 0:
        total_pages = 1
    if page < 1:
        page = 1
    if page > total_pages:
        page = total_pages

    buyer_msg = (
        f"🛒 <b>BUYER DETAILED HISTORY</b>\n\n"
        f"🆔 <b>User ID:</b> <code>{u_info[0]}</code>\n"
        f"👤 <b>Username:</b> @{u_info[1]}\n"
        f"💰 <b>Current Balance:</b> ${u_info[2]:.2f} USD\n"
        f"📊 <b>Total Recharge:</b> ${u_info[3]:.2f} USD\n\n"
        f"📈 <b>BUYER STATS:</b>\n"
        f"🔹 Total Bought: <b>{total_purchased}</b>\n"
        f"✅ OTP Sent (Success): <b>{otp_sent_count}</b>\n"
        f"❌ OTP Failed: <b>{failed_count}</b>\n"
        f"🎯 Success Rate: <b>{success_rate:.1f}%</b>\n\n"
        f"<b>📋 ক্রয়ের হিস্ট্রি ও OTP স্ট্যাটাস (Page {page}/{total_pages}):</b>\n\n"
    )

    if not orders:
        buyer_msg += "<i>কোনো নম্বরের তথ্য পাওয়া যায়নি।</i>\n"
    else:
        start_idx = (page - 1) * items_per_page
        end_idx = start_idx + items_per_page
        page_orders = orders[start_idx:end_idx]

        for idx, ord_item in enumerate(page_orders, start=start_idx + 1):
            p_num, otp_c, p_date, otp_l, app_t, lang_t = ord_item[0], ord_item[1], ord_item[2], ord_item[3], ord_item[4], ord_item[5]
            status = f"✅ Received ({otp_c}) [{app_t}]" if otp_c else "❌ OTP Pending / Not Received"
            buyer_msg += f"<b>{idx}.</b> 📱 <code>{p_num}</code>\n   📅 Date: {p_date}\n   🔗 Link: {otp_l}\n   📌 Status: {status}\n   🌐 Lang: [{lang_t}]\n\n"

    # Pagination Nav Buttons
    nav_buttons = []
    if total_pages > 1:
        row = []
        if page > 1:
            row.append({"text": f"◀️ Page {page-1}", "callback_data": f"pb_{target_u_id}_{page-1}", "style": "primary"})
        row.append({"text": f"📄 {page}/{total_pages}", "callback_data": "noop"})
        if page < total_pages:
            row.append({"text": f"Page {page+1} ▶️", "callback_data": f"pb_{target_u_id}_{page+1}", "style": "primary"})
        nav_buttons.append(row)

    nav_buttons.append([{"text": f"➕ Add / Refund Balance to @{u_info[1]}", "callback_data": f"admin_ref_input_{target_u_id}", "style": "success"}])
    nav_buttons.append([{"text": "⬅️ Back to Buyers List", "callback_data": "admin_view_buyers", "style": "primary"}])

    return buyer_msg, {"inline_keyboard": nav_buttons}


# Helper Generator for User Details Page Pagination
def render_user_page(target_u_id, page=1, items_per_page=10):
    u_info = get_user(target_u_id)
    if not u_info:
        return "❌ <b>ইউজার পাওয়া যায়নি!</b>", {"inline_keyboard": []}

    # Full purchase history for this specific user
    orders = get_user_orders_all(target_u_id)
    total_purchased = len(orders)

    total_pages = (total_purchased + items_per_page - 1) // items_per_page
    if total_pages == 0:
        total_pages = 1
    if page < 1:
        page = 1
    if page > total_pages:
        page = total_pages

    user_msg = (
        f"👤 <b>USER HISTORY</b>\n\n"
        f"👤 <b>Username:</b> @{u_info[1]}\n\n"
        f"<b>📋 Number / OTP / Link (Page {page}/{total_pages}):</b>\n\n"
    )

    if not orders:
        user_msg += "<i>এই ইউজারের কোনো ক্রয় হিস্ট্রি নেই।</i>\n"
    else:
        start_idx = (page - 1) * items_per_page
        end_idx = start_idx + items_per_page
        page_orders = orders[start_idx:end_idx]

        for idx, ord_item in enumerate(page_orders, start=start_idx + 1):
            p_num, otp_c, p_date, otp_l, app_t, lang_t = ord_item[0], ord_item[1], ord_item[2], ord_item[3], ord_item[4], ord_item[5]
            otp_display = otp_c if otp_c else "Pending / Not Received"
            user_msg += (
                f"<b>{idx}.</b> 📱 <b>Number:</b> <code>{p_num}</code>\n"
                f"   🔐 <b>OTP:</b> <code>{otp_display}</code>\n"
                f"   🔗 <b>Link:</b> {otp_l}\n\n"
            )

    # Pagination Nav Buttons
    nav_buttons = []
    if total_pages > 1:
        row = []
        if page > 1:
            row.append({"text": f"◀️ Page {page-1}", "callback_data": f"pu_{target_u_id}_{page-1}", "style": "primary"})
        row.append({"text": f"📄 {page}/{total_pages}", "callback_data": "noop"})
        if page < total_pages:
            row.append({"text": f"Page {page+1} ▶️", "callback_data": f"pu_{target_u_id}_{page+1}", "style": "primary"})
        nav_buttons.append(row)

    nav_buttons.append([{"text": f"➕ Add / Refund Balance to @{u_info[1]}", "callback_data": f"admin_ref_input_{target_u_id}", "style": "success"}])
    user_sheet_url = get_user_google_sheet_url(target_u_id)
    if user_sheet_url:
        nav_buttons.append([{"text": "📊 Open User Google Sheet", "url": user_sheet_url, "style": "primary"}])
    nav_buttons.append([{"text": "⬅️ Back to User List", "callback_data": "admin_view_users", "style": "primary"}])

    return user_msg, {"inline_keyboard": nav_buttons}


# Core Update Handler
def handle_update(update):
    try:
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

            # Admin Reply Handler for VPN Orders
            if is_admin and "reply_to_message" in msg:
                reply_msg = msg["reply_to_message"]
                reply_text = reply_msg.get("text", "")
                if "VPN ORDER #" in reply_text:
                    match = re.search(r'VPN ORDER #([a-f0-9]+)', reply_text)
                    user_match = re.search(r'User ID: (\d+)', reply_text)
                    if user_match:
                        target_u_id = int(user_match.group(1))
                        vpn_account_info = text.strip()
                        
                        send_message(
                            target_u_id, 
                            f"🎉 <b>Your order is completed!</b>\n\n<b>VPN Details:</b>\n<code>{vpn_account_info}</code>"
                        )
                        send_message(chat_id, f"✅ <b>Order notification & VPN details successfully sent to User {target_u_id}!</b>")
                        return

            # Handle Back Button Globally
            if text in ["⬅️ Back", "🔙 Back"]:
                delete_user_state(user_id)
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

            # Input State Handling from Database
            state_data = get_user_state(user_id)
            if state_data:
                # Set Rex Checker Link
                if is_admin and state_data == "ADMIN_SET_REX_LINK":
                    set_rex_checker_link(text.strip())
                    send_message(chat_id, f"✅ <b>Rex Checker Link updated successfully:</b>\n{text.strip()}", reply_markup=get_main_keyboard(is_admin))
                    delete_user_state(user_id)
                    return

                # Set Google Sheet URL
                if is_admin and state_data == "ADMIN_SET_SHEET_URL":
                    sheet_url = text.strip()
                    if not (sheet_url.startswith("https://") or sheet_url.startswith("http://")):
                        send_message(chat_id, "❌ <b>সঠিক Google Apps Script Web App URL দিন।</b>\nউদাহরণ: https://script.google.com/macros/s/.../exec")
                        return
                    set_google_sheet_url(sheet_url)
                    send_message(chat_id, "⏳ <b>Google Sheet সংযোগ করা হয়েছে। পুরোনো MongoDB purchase history sync করা হচ্ছে...</b>")
                    synced, failed = sync_all_existing_orders_to_google_sheet()
                    send_message(
                        chat_id,
                        f"✅ <b>Google Sheet URL saved.</b>\n\n📥 পুরোনো history sync: <b>{synced}</b>\n❌ ব্যর্থ: <b>{failed}</b>\n\nএখন থেকে নতুন purchase ও OTP-ও sheet-এ save হবে।",
                        reply_markup=get_main_keyboard(is_admin)
                    )
                    delete_user_state(user_id)
                    return

                # Set VPN Prices
                if is_admin and state_data in ["ADMIN_SET_NORD_PRICE", "ADMIN_SET_PROTON_PRICE"]:
                    service = "nord" if state_data == "ADMIN_SET_NORD_PRICE" else "proton"
                    try:
                        new_p = float(text)
                        set_vpn_price(service, new_p)
                        send_message(chat_id, f"✅ <b>{service.capitalize()}VPN Price updated to: ${new_p:.2f} USD</b>", reply_markup=get_main_keyboard(is_admin))
                    except ValueError:
                        send_message(chat_id, "❌ <b>ভুল ইনপুট!</b> সঠিক সংখ্যা লিখুন (যেমন: 1.50)।")
                    delete_user_state(user_id)
                    return

                # Admin Upload VPN Stock File Step 2
                if is_admin and isinstance(state_data, dict) and state_data.get("step") == "ADMIN_UPLOAD_VPN_FILE":
                    service = state_data.get("service")
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
                                if line and ":" in line:
                                    add_vpn_stock_item(service, line)
                                    count += 1
                            
                            send_message(chat_id, f"✅ <b>সফলভাবে {count} টি {service.capitalize()}VPN অ্যাকাউন্ট স্টকে আপলোড করা হয়েছে!</b>", reply_markup=get_main_keyboard(is_admin))
                            delete_user_state(user_id)
                            return
                    else:
                        send_message(chat_id, "❌ <b>অনুগ্রহ করে একটি সঠিক টেক্সট (.txt / .csv) ফাইল আপলোড করুন।</b>", reply_markup=get_back_keyboard())
                        return

                # Multiple Number Quantity Input
                if isinstance(state_data, str) and state_data == "BUY_MULTI_QTY":
                    try:
                        qty = int(text)
                        if qty <= 0:
                            send_message(chat_id, "❌ <b>সঠিক সংখ্যা লিখুন (কমপক্ষে ১ টি)।</b>")
                            return
                        
                        u_info = get_user(user_id)
                        bal = u_info[2] if u_info else 0.0
                        total_cost = current_price * qty

                        # Fixed Floating-Point Balance Check Issue
                        if round(bal, 2) < round(total_cost, 2):
                            send_message(chat_id, f"❌ <b>পর্যাপ্ত ব্যালেন্স নেই!</b>\n{qty} টি নম্বর কিনতে ${total_cost:.2f} USD লাগবে। আপনার ব্যালেন্স: ${bal:.2f} USD।")
                            delete_user_state(user_id)
                            return

                        stock_items = get_all_stock()
                        if len(stock_items) < qty:
                            send_message(chat_id, f"⚠️ <b>দুঃখিত! স্টকে পর্যাপ্ত নম্বর নেই।</b>\nবর্তমানে স্টকে {len(stock_items)} টি নম্বর খালি রয়েছে।")
                            delete_user_state(user_id)
                            return

                        purchased_list = []
                        for _ in range(qty):
                            phone, link = pop_stock_item()
                            if phone:
                                deduct_balance(user_id, current_price)
                                save_active_order(user_id, phone, link)
                                # Log to Google Sheet with link & date
                                latest_order = orders_col.find_one({"phone_number": phone}, sort=[("_id", -1)])
                                p_date = latest_order.get("purchase_date", "") if latest_order else datetime.now().strftime("%d-%b-%Y %I:%M %p")
                                log_purchase_to_google_sheet(user_id, username, phone, link, p_date, order_id=latest_order.get("_id") if latest_order else None)
                                purchased_list.append((phone, link))

                        delete_user_state(user_id)
                        
                        res_msg = f"✅ <b>সফলভাবে {len(purchased_list)} টি নম্বর কেনা হয়েছে!</b>\n\n"
                        for idx, (p, l) in enumerate(purchased_list, 1):
                            res_msg += f"<b>{idx}.</b> 📱 <code>{p}</code> | 🔗 {l}\n"
                        
                        res_msg += f"\n💰 <b>মোট ফি কাটা হয়েছে:</b> ${current_price * len(purchased_list):.2f} USD\n👉 যেকোনো একটির ওটিপি পেতে <b>Check OTP</b> বাটনে চাপ দিন।"
                        
                        multi_btns = []
                        for p, l in purchased_list[:10]:
                            multi_btns.append([{"text": f"🔄 Check OTP ({p})", "callback_data": f"chk_otp_{p}", "style": "primary"}])
                        
                        send_message(chat_id, res_msg, reply_markup={"inline_keyboard": multi_btns})
                        send_message(chat_id, "<b>মূল মেনু:</b>", reply_markup=get_main_keyboard(is_admin))
                        return

                    except ValueError:
                        send_message(chat_id, "❌ <b>ভুল ইনপুট!</b> কেবল পূর্ণসংখ্যা লিখুন (যেমন: 2, 5, 10)।")
                        return

               # Search User by Username
                if is_admin and isinstance(state_data, str) and state_data == "ADMIN_SEARCH_USER":
                    u_info = get_user_by_username(text)
                    if not u_info:
                        send_message(chat_id, f"❌ <b>'{text}' ইউজারনেমে কোনো ইউজার খুঁজে পাওয়া যায়নি!</b>", reply_markup=get_main_keyboard(is_admin))
                        delete_user_state(user_id)
                        return

                    target_u_id = u_info[0]
                    buyer_msg, buyer_markup = render_buyer_page(target_u_id, page=1)
                    send_message(chat_id, buyer_msg, reply_markup=buyer_markup)
                    delete_user_state(user_id)
                    return

                # Change Number Price
                if is_admin and state_data == "ADMIN_SET_PRICE":
                    try:
                        new_pr = float(text)
                        set_number_price(new_pr)
                        send_message(chat_id, f"✅ <b>হোয়াটসঅ্যাপ নম্বরের নতুন মূল্য সেট করা হয়েছে: ${new_pr:.2f} USD</b>", reply_markup=get_main_keyboard(is_admin))
                    except ValueError:
                        send_message(chat_id, "❌ <b>ভুল ইনপুট!</b> সঠিক সংখ্যা লিখুন (যেমন: 0.10)।")
                    delete_user_state(user_id)
                    return

                # Dynamic Force Join Set
                if is_admin and state_data == "ADMIN_SET_CHANNELS":
                    ch_list = [c.strip() for c in text.split(",") if c.strip()]
                    if len(ch_list) > 2:
                        send_message(chat_id, "❌ <b>সর্বোচ্চ ২টি চ্যানেল লিঙ্ক বা ইউজারনেম দিতে পারবেন!</b>\nকমা (,) দিয়ে ২টি লিঙ্ক বা ইউজারনেম দিন।")
                        return
                    set_force_channels(ch_list)
                    send_message(chat_id, f"✅ <b>ফোর্স জয়েন চ্যানেল ২ টি সেট করা হয়েছে!</b>\nচ্যানেলসমূহ: {', '.join(ch_list)}", reply_markup=get_main_keyboard(is_admin))
                    delete_user_state(user_id)
                    return

                # Deposit Step 1: Amount
                if isinstance(state_data, dict) and state_data.get("step") == "WAITING_AMOUNT":
                    method = state_data["method"]
                    try:
                        amount = float(text)
                        if amount <= 0:
                            send_message(chat_id, "❌ <b>সঠিক পরিমাণ উল্লেখ করুন!</b>")
                            return
                        
                        set_user_state(user_id, {"step": "WAITING_TRX", "method": method, "amount": amount})

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
                    set_user_state(user_id, {
                        "step": "WAITING_SCREENSHOT",
                        "method": state_data["method"],
                        "amount": state_data["amount"],
                        "trx_id": text
                    })
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
                        delete_user_state(user_id)
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
                            delete_user_state(user_id)
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
                    delete_user_state(user_id)
                    return

                # Admin Refund Input
                elif isinstance(state_data, str) and state_data.startswith("ADMIN_REFUND_USER_"):
                    target_user = int(state_data.replace("ADMIN_REFUND_USER_", ""))
                    try:
                        parts = text.split()
                        usd_val = float(parts[0])
                        num_cnt = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
                        
                        target_info = get_user(target_user)
                        target_name = target_info[1] if target_info else "NoUsername"
                        
                        add_refund_balance(target_user, usd_val, num_count=num_cnt)
                        
                        send_message(chat_id, f"✅ <b>User @{target_name} (ID: {target_user})-কে ${usd_val:.2f} USD সফলভাবে রিফান্ড করা হয়েছে!</b>\n(রিফান্ড হিস্ট্রিতে রেকর্ডটি সেভ হয়েছে)", reply_markup=get_main_keyboard(is_admin))
                        send_message(target_user, f"🎉 <b>এডমিন আপনার অ্যাকাউন্টে ${usd_val:.2f} USD রিফান্ড যোগ করেছেন!</b>")
                    except Exception:
                        send_message(chat_id, "❌ <b>ভুল ইনপুট!</b> অ্যামাউন্ট লিখুন অথবা অ্যামাউন্ট ও নম্বরের সংখ্যা লিখুন। (যেমন: 0.10 বা 0.50 5)")
                    delete_user_state(user_id)
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
                    delete_user_state(user_id)
                    return

         
            # Main Keyboards Handling
            if text == "/start":
                welcome_text = f"👋 <b>Welcome {html.escape(first_name)}!</b>\n\nনিচের মেনু থেকে সার্ভিস সিলেক্ট করুন:"
                send_message(chat_id, welcome_text, reply_markup=get_main_keyboard(is_admin))

            elif text in ["🛒 BUY NUMBER", "📱 GET NUMBER"]:
                markup = {
                    "inline_keyboard": [
                        [{"text": f"👤 Buy Single Number (${current_price:.2f})", "callback_data": "confirm_buy_usa", "style": "success"}],
                        [{"text": "🔢 Buy Multiple Numbers", "callback_data": "buy_multi_num", "style": "primary"}]
                    ]
                }
                send_message(chat_id, f"<b>WhatsApp Service Selected:</b>\n\nমূল্য: <b>${current_price:.2f} USD / Number</b>", reply_markup=get_back_keyboard())
                send_message(chat_id, "সার্ভিস অপশন বেছে নিন:", reply_markup=markup)

            elif text == "🛡️ BUY VPN":
                nord_pr = get_vpn_price("nord")
                proton_pr = get_vpn_price("proton")
                markup = {
                    "inline_keyboard": [
                        [{"text": f"🛡️ NordVPN (${nord_pr:.2f})", "callback_data": "buy_vpn_nord", "style": "primary"}],
                        [{"text": f"🛡️ ProtonVPN (${proton_pr:.2f})", "callback_data": "buy_vpn_proton", "style": "primary"}]
                    ]
                }
                send_message(chat_id, "🛡️ <b>Select VPN Service:</b>\n\nপছন্দের VPN সার্ভিস বেছে নিন:", reply_markup=get_back_keyboard())
                send_message(chat_id, "উপলব্ধ ভিপিএন সার্ভিসসমূহ:", reply_markup=markup)

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
                all_purchased = len(get_user_orders_all(user_id))
                prof_text = (
                    f"👤 <b>Your Profile Information</b>\n\n"
                    f"🆔 <b>User ID:</b> <code>{user_id}</code>\n"
                    f"💰 <b>Current Balance:</b> ${bal:.2f} USD\n"
                    f"📊 <b>Total Recharge:</b> ${tot:.2f} USD\n"
                    f"🛒 <b>Total Purchased Numbers:</b> {all_purchased} টি"
                )
                send_message(chat_id, prof_text, reply_markup=get_back_keyboard())

            elif text == "🔍 Rex Checker":
                rex_link = get_rex_checker_link()
                rex_markup = {
                    "inline_keyboard": [
                        [{"text": "🔍 Open Rex Checker", "url": rex_link}]
                    ]
                }
                send_message(
                    chat_id,
                    "🔍 <b>Rex Checker</b>\n\nনিচের বাটনে চাপ দিয়ে Rex Checker ওপেন করুন:",
                    reply_markup=rex_markup
                )

            elif text == "🎧 SUPPORT":
                send_message(chat_id, f"<b>যেকোনো সাহায্যে যোগাযোগ করুন:</b>\n👉 @{SUPPORT_USERNAME}", reply_markup=get_back_keyboard())

            elif text == "⚙️ ADMIN PANEL" and is_admin:
                admin_msg, admin_markup = get_admin_panel_data()
                send_message(chat_id, admin_msg, reply_markup=get_back_keyboard())
                send_message(chat_id, "এডমিন একশন সিলেক্ট করুন:", reply_markup=admin_markup)

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
                requests.post(BASE_URL + "answerCallbackQuery", json={"callback_query_id": cb_id}, timeout=5)
            except Exception:
                pass

            if not is_admin and not bot_active and data != "verify_join":
                send_message(chat_id, "⚠️ <b>সাময়িক সময়ের জন্য বট বন্ধ রয়েছে!</b>\nএডমিন বট চালু করলে সেবা গ্রহণ করতে পারবেন।")
                return

            current_price = get_number_price()
            bdt_rate = get_bdt_per_usd()

            if data == "noop":
                return

            # VPN Buy Callbacks with Confirm & Cancel Support
            if data.startswith("buy_vpn_"):
                service = "nord" if "nord" in data else "proton"
                pr = get_vpn_price(service)
                u_info = get_user(user_id)
                bal = u_info[2] if u_info else 0.0

                if round(bal, 2) < round(pr, 2):
                    edit_message(chat_id, message_id, f"❌ <b>পর্যাপ্ত ব্যালেন্স নেই!</b>\n{service.capitalize()}VPN কিনতে ${pr:.2f} USD লাগবে। আপনার ব্যালেন্স: ${bal:.2f} USD।")
                    return

                conf_markup = {
                    "inline_keyboard": [
                        [
                            {"text": "✅ Confirm Order", "callback_data": f"conf_vpn_{service}", "style": "success"},
                            {"text": "❌ Cancel", "callback_data": "cancel_vpn", "style": "danger"}
                        ]
                    ]
                }
                edit_message(chat_id, message_id, f"🛡️ <b>{service.capitalize()}VPN Order Confirmation</b>\n\n💰 Price: <b>${pr:.2f} USD</b>\n💵 Your Balance: <b>${bal:.2f} USD</b>\n\nআপনি কি এই ভিপিএনটি কিনতে চান?", reply_markup=conf_markup)
                return

            elif data.startswith("conf_vpn_"):
                service = "nord" if "nord" in data else "proton"
                pr = get_vpn_price(service)
                u_info = get_user(user_id)
                bal = u_info[2] if u_info else 0.0

                if round(bal, 2) < round(pr, 2):
                    edit_message(chat_id, message_id, f"❌ <b>পর্যাপ্ত ব্যালেন্স নেই!</b>\n{service.capitalize()}VPN কিনতে ${pr:.2f} USD লাগবে। আপনার ব্যালেন্স: ${bal:.2f} USD।")
                    return

                deduct_balance(user_id, pr)
                order_id = save_vpn_order(user_id, service, pr)

                # Admin Notification
                admin_notif = (
                    f"🚨 <b>NEW VPN ORDER #{order_id}</b>\n\n"
                    f"👤 <b>User ID:</b> <code>{user_id}</code>\n"
                    f"🛡️ <b>Service:</b> {service.upper()}VPN\n"
                    f"💰 <b>Price:</b> ${pr:.2f} USD\n\n"
                    f"👉 <i>এই মেসেজটিতে Reply দিয়ে ইমেইল ও পাসওয়ার্ড লিখে দিন (যেমন: email:password)。</i>"
                )
                send_message(ADMIN_ID, admin_notif)

                edit_message(chat_id, message_id, f"✅ <b>আপনার {service.capitalize()}VPN অর্ডারটি সফলভাবে কনফার্ম হয়েছে!</b>\n\n💰 ফি কাটা হয়েছে: ${pr:.2f} USD\n⏳ অল্প কিছুক্ষণের মধ্যে এডমিন আপনার ভিপিএন এর ইমেইল এবং পাসওয়ার্ড পাঠিয়ে দেবে।")
                return

            elif data == "cancel_vpn":
                edit_message(chat_id, message_id, "❌ <b>ভিপিএন অর্ডারটি বাতিল করা হয়েছে।</b>")
                return

            # Bot Status Toggle Callback
            if data == "admin_toggle_bot_off" and is_admin:
                set_bot_status("OFF")
                admin_msg, admin_markup = get_admin_panel_data()
                edit_message(chat_id, message_id, admin_msg, reply_markup=admin_markup)

            elif data == "admin_toggle_bot_on" and is_admin:
                set_bot_status("ON")
                admin_msg, admin_markup = get_admin_panel_data()
                edit_message(chat_id, message_id, admin_msg, reply_markup=admin_markup)

            elif data == "verify_join":
                is_joined, _ = verify_force_join(user_id)
                if is_joined:
                    send_message(chat_id, "✅ <b>ধন্যবাদ! ভেরিফিকেশন সফল হয়েছে।</b>\nএখন বট ব্যবহার করতে পারবেন।", reply_markup=get_main_keyboard(is_admin))
                else:
                    send_message(chat_id, "❌ <b>আপনি এখনও সবগুলো চ্যানেলে জয়েন করেননি!</b>\nদয়া করে ২টি চ্যানেলেই জয়েন করে আবার ট্রাই করুন।")

            elif data == "buy_multi_num":
                set_user_state(user_id, "BUY_MULTI_QTY")
                send_message(chat_id, "🔢 <b>আপনি কতগুলো নম্বর কিনতে চান লিখে পাঠান:</b>\n(যেমন: 2, 5, 10 ইত্যাদি)", reply_markup=get_back_keyboard())

            elif data == "confirm_buy_usa":
                u_info = get_user(user_id)
                bal = u_info[2] if u_info else 0.0

                # Fixed Floating-Point Balance Check Issue
                if round(bal, 2) < round(current_price, 2):
                    edit_message(chat_id, message_id, f"❌ <b>পর্যাপ্ত ব্যালেন্স নেই!</b>\nনম্বর কিনতে অন্তত ${current_price:.2f} USD ব্যালেন্স লাগবে। Deposit সেকশন থেকে রিচার্জ করুন।")
                    return

                phone, link = pop_stock_item()
                if not phone:
                    edit_message(chat_id, message_id, "⚠️ <b>দুঃখিত! বর্তমানে স্টক ফাঁকা রয়েছে।</b> কিছু সময় পর আবার চেষ্টা করুন।")
                    return

                deduct_balance(user_id, current_price)
                save_active_order(user_id, phone, link)
                
                # Log to Google Sheet with link & date
                latest_order = orders_col.find_one({"phone_number": phone}, sort=[("_id", -1)])
                p_date = latest_order.get("purchase_date", "") if latest_order else datetime.now().strftime("%d-%b-%Y %I:%M %p")
                log_purchase_to_google_sheet(user_id, username, phone, link, p_date, order_id=latest_order.get("_id") if latest_order else None)

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

            elif data.startswith("chk_otp_"):
                phone = data.replace("chk_otp_", "")
                order = get_order_by_phone(phone)
                
                if order:
                    link = order[2]
                    otp_code = None
                    raw_response_text = ""
                    
                    try:
                        headers = {
                            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                            "Accept": "*/*",
                            "Cache-Control": "no-cache"
                        }

                        api_link = link.replace("/sms/", "/api/sms/") if "/sms/" in link else link
                        response = requests.get(api_link, headers=headers, timeout=8)
                        api_text = response.text.strip()
                        raw_response_text = api_text

                        if re.match(r'^\d{3,10}$', api_text):
                            otp_code = api_text
                        else:
                            main_res = requests.get(link, headers=headers, timeout=8)
                            raw_response_text = main_res.text
                            matches = re.findall(r'\b\d{6}\b', main_res.text)
                            clean_phone = re.sub(r'\D', '', phone)
                            
                            for code in matches:
                                if code not in ['111111', '000000', '123456'] and code not in clean_phone:
                                    otp_code = code
                                    break

                    except Exception as e:
                        print(f"OTP Scraping Error: {e}")

                    if otp_code:
                        app_type = "WB" if ("business" in raw_response_text.lower() or "smb" in raw_response_text.lower()) else "WA"
                        detected_lang = detect_language(raw_response_text)
                        update_order_otp(phone, otp_code, app_type=app_type, lang=detected_lang)
                        
                        markup = {
                            "inline_keyboard": [
                                [{"text": "🛒 Buy Another Number", "callback_data": "confirm_buy_usa", "style": "success"}]
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
                                f"🎉 <b>New OTP Received! ({app_type})</b>\n\n"
                                f"📱 <b>Number:</b> <code>{masked_num}</code>\n"
                                f"🔑 <b>OTP Code:</b> <code>{otp_code}</code>\n"
                                f"🌐 <b>Language:</b> <code>[{detected_lang}]</code>"
                            )
                            send_message(OTP_GROUP_ID, group_msg)
                    else:
                        send_message(chat_id, "⌛ <b>OTP এখনও আসেনি!</b> অনুগ্রহ করে কিছুক্ষণ পর আবার Check OTP চাপুন।")

            elif data == "admin_panel_back" and is_admin:
                admin_msg, admin_markup = get_admin_panel_data()
                edit_message(chat_id, message_id, admin_msg, reply_markup=admin_markup)

            elif data == "admin_user_mgmt_menu" and is_admin:
                markup = {
                    "inline_keyboard": [
                        [{"text": "👥 All User View", "callback_data": "admin_view_users", "style": "primary"}],
                        [{"text": "🛒 Active Buyers List", "callback_data": "admin_view_buyers", "style": "success"}],
                        [{"text": "📜 Refund History Log", "callback_data": "admin_refund_history", "style": "primary"}],
                        [{"text": "🔎 Search User & Refund", "callback_data": "admin_search_user_btn", "style": "primary"}],
                        [{"text": "⬅️ Back to Admin Panel", "callback_data": "admin_panel_back", "style": "danger"}]
                    ]
                }
                edit_message(chat_id, message_id, "<b>👥 USER MANAGEMENT OPTIONS:</b>\nএকটি অপশন বেছে নিন:", reply_markup=markup)

            elif data == "admin_view_users" and is_admin:
                users_list = get_all_users_info()
                if not users_list:
                    edit_message(chat_id, message_id, "❌ <b>বটে এখনও কোনো ইউজার রেজিস্টার করেনি।</b>", reply_markup={"inline_keyboard": [[{"text": "⬅️ Back", "callback_data": "admin_user_mgmt_menu"}]]})
                    return

                buttons = []
                for u in users_list:
                    u_id, u_name, u_bal = u[0], u[1], u[2]
                    display_title = f"👤 @{u_name} (${u_bal:.2f})" if u_name != "NoUsername" else f"👤 ID: {u_id} (${u_bal:.2f})"
                    buttons.append([{"text": display_title, "callback_data": f"pu_{u_id}_1", "style": "primary"}])

                buttons.append([{"text": "⬅️ Back to User Management", "callback_data": "admin_user_mgmt_menu", "style": "danger"}])
                markup = {"inline_keyboard": buttons}
                edit_message(chat_id, message_id, f"👥 <b>বটের সমস্ত ইউজারের তালিকা (মোট: {len(users_list)} জন):</b>\nইউজারের ডিটেইলস দেখতে তার নামের ওপর ক্লিক করুন:", reply_markup=markup)

            elif data == "admin_view_buyers" and is_admin:
                buyers_list = get_buyers_list()
                if not buyers_list:
                    edit_message(chat_id, message_id, "❌ <b>এখনও কোনো ইউজার নম্বর কেনেনি।</b>", reply_markup={"inline_keyboard": [[{"text": "⬅️ Back", "callback_data": "admin_user_mgmt_menu"}]]})
                    return

                buttons = []
                for u in buyers_list:
                    u_id, u_name, u_bal = u[0], u[1], u[2]
                    display_title = f"🛒 @{u_name} (${u_bal:.2f})" if u_name != "NoUsername" else f"🛒 ID: {u_id} (${u_bal:.2f})"
                    buttons.append([{"text": display_title, "callback_data": f"pb_{u_id}_1", "style": "success"}])

                buttons.append([{"text": "⬅️ Back to User Management", "callback_data": "admin_user_mgmt_menu", "style": "danger"}])
                markup = {"inline_keyboard": buttons}
                edit_message(chat_id, message_id, f"🛒 <b>নম্বর ক্রয়কারী ইউজারদের তালিকা (মোট: {len(buyers_list)} জন):</b>\nকার কোন নম্বরে ওটিপি এসেছে তা দেখতে ক্লিক করুন:", reply_markup=markup)

            elif data == "admin_refund_history" and is_admin:
                logs = list(refund_logs_col.find().sort("_id", -1).limit(30))
                if not logs:
                    edit_message(chat_id, message_id, "📜 <b>এখনও কাউকে রিফান্ড করা হয়নি।</b>", reply_markup={"inline_keyboard": [[{"text": "⬅️ Back", "callback_data": "admin_user_mgmt_menu"}]]})
                    return

                history_msg = f"📜 <b>REFUND HISTORY LOG (LAST {len(logs)} RECORDS)</b>\n\n"
                for idx, log in enumerate(logs, 1):
                    u_name = log.get("username", "NoUsername")
                    u_id = log.get("user_id")
                    amt = log.get("amount", 0.0)
                    n_cnt = log.get("num_count", 0)
                    dt = log.get("date", "N/A")
                    
                    num_str = f" ({n_cnt} Numbers)" if n_cnt > 0 else ""
                    history_msg += f"<b>{idx}.</b> 👤 <b>User:</b> @{u_name} (<code>{u_id}</code>)\n   💵 <b>Refund:</b> ${amt:.2f} USD{num_str}\n   📅 <b>Date:</b> {dt}\n\n"

                markup = {"inline_keyboard": [[{"text": "⬅️ Back to User Management", "callback_data": "admin_user_mgmt_menu", "style": "danger"}]]}
                edit_message(chat_id, message_id, history_msg, reply_markup=markup)

            elif data == "admin_search_user_btn" and is_admin:
                set_user_state(user_id, "ADMIN_SEARCH_USER")
                send_message(chat_id, "🔎 <b>ইউজারের Username টি লিখে পাঠান:</b>\n(যেমন: `@username` বা `username`)", reply_markup=get_back_keyboard())

            # PAGINATION CALLBACK FOR ACTIVE BUYERS PAGE NAVIGATION
            elif (data.startswith("pb_") or data.startswith("insp_b_") or data.startswith("inspect_buyer_")) and is_admin:
                clean_data = data.replace("insp_b_", "").replace("inspect_buyer_", "")
                if clean_data.startswith("pb_"):
                    parts = clean_data.split("_")
                    target_u_id = int(parts[1])
                    page_num = int(parts[2])
                else:
                    target_u_id = int(clean_data)
                    page_num = 1

                buyer_msg, buyer_markup = render_buyer_page(target_u_id, page=page_num)
                edit_message(chat_id, message_id, buyer_msg, reply_markup=buyer_markup)

            # PAGINATION CALLBACK FOR USER DETAILS PAGE NAVIGATION
            elif (data.startswith("pu_") or data.startswith("insp_u_") or data.startswith("inspect_u_")) and is_admin:
                clean_data = data.replace("insp_u_", "").replace("inspect_u_", "")
                if clean_data.startswith("pu_"):
                    parts = clean_data.split("_")
                    target_u_id = int(parts[1])
                    page_num = int(parts[2])
                else:
                    target_u_id = int(clean_data)
                    page_num = 1

                user_msg, user_markup = render_user_page(target_u_id, page=page_num)
                edit_message(chat_id, message_id, user_msg, reply_markup=user_markup)

            elif data == "admin_set_rex_link" and is_admin:
                set_user_state(user_id, "ADMIN_SET_REX_LINK")
                send_message(chat_id, "🔍 <b>Rex Checker-এর নতুন লিংকটি (URL / Bot Link) লিখে পাঠান:</b>", reply_markup=get_back_keyboard())

            elif data == "admin_set_sheet_url" and is_admin:
                set_user_state(user_id, "ADMIN_SET_SHEET_URL")
                send_message(chat_id, "📊 <b>Google Sheet Webhook / Apps Script URL টি লিখে পাঠান:</b>", reply_markup=get_back_keyboard())

            elif data == "admin_set_nord_price" and is_admin:
                set_user_state(user_id, "ADMIN_SET_NORD_PRICE")
                send_message(chat_id, "🛡️ <b>NordVPN-এর নতুন মূল্য ($ USD) লিখে পাঠান:</b>", reply_markup=get_back_keyboard())

            elif data == "admin_set_proton_price" and is_admin:
                set_user_state(user_id, "ADMIN_SET_PROTON_PRICE")
                send_message(chat_id, "🛡️ <b>ProtonVPN-এর নতুন মূল্য ($ USD) লিখে পাঠান:</b>", reply_markup=get_back_keyboard())

            elif data == "admin_upload_vpn_file" and is_admin:
                markup = {
                    "inline_keyboard": [
                        [{"text": "🛡️ Upload NordVPN", "callback_data": "up_vpn_nord", "style": "primary"}],
                        [{"text": "🛡️ Upload ProtonVPN", "callback_data": "up_vpn_proton", "style": "primary"}]
                    ]
                }
                send_message(chat_id, "কোন ভিপিএন-এর স্টক ফাইল আপলোড করবেন সিলেক্ট করুন:", reply_markup=markup)

            elif data.startswith("up_vpn_") and is_admin:
                service = "nord" if "nord" in data else "proton"
                set_user_state(user_id, {"step": "ADMIN_UPLOAD_VPN_FILE", "service": service})
                send_message(chat_id, f"📁 <b>{service.capitalize()}VPN সম্বলিত ফাইলটি (.txt / .csv) পাঠান:</b>\nফরম্যাট:\n<code>email:password</code>", reply_markup=get_back_keyboard())

            elif data == "admin_set_exchange" and is_admin:
                set_user_state(user_id, "ADMIN_SET_EXCHANGE")
                send_message(chat_id, f"💱 <b>নতুন BDT to USD রেট লিখে পাঠান:</b>\n(যেমন: 120, 122, 125 ইত্যাদি। বর্তমান রেট: ৳{int(bdt_rate)})", reply_markup=get_back_keyboard())

            elif data == "admin_set_channels" and is_admin:
                set_user_state(user_id, "ADMIN_SET_CHANNELS")
                send_message(chat_id, "📢 <b>ফোর্স জয়েন চ্যানেল ২ টি লিঙ্ক বা ইউজারনেম দিন:</b>\n(সর্বোচ্চ ২টি, কমা দিয়ে দিন। যেমন: `@channel1, @channel2` অথবা `https://t.me/link1, https://t.me/link2`)", reply_markup=get_back_keyboard())

            elif data.startswith("admin_ref_input_") and is_admin:
                target_u_id = int(data.replace("admin_ref_input_", ""))
                u = get_user(target_u_id)
                target_uname = u[1] if u else "User"
                set_user_state(user_id, f"ADMIN_REFUND_USER_{target_u_id}")
                send_message(chat_id, f"➕ <b>User @{target_uname} (ID: {target_u_id})-এর অ্যাকাউন্টে কত $ (USD) রিফান্ড করতে চান লিখে পাঠান:</b>\n\n<i>নোট: আপনি চাইলে রিফান্ড অ্যামাউন্টের সাথে স্পেস দিয়ে নম্বরের সংখ্যাও লিখতে পারেন (যেমন: <code>0.30 3</code> বা শুধু <code>0.30</code>)</i>", reply_markup=get_back_keyboard())

            elif data == "dep_bkash":
                set_user_state(user_id, {"step": "WAITING_AMOUNT", "method": "BKASH"})
                send_message(chat_id, f"💖 <b>bKash Deposit Selected</b>\n\nকত টাকা (BDT) ডিপোজিট করতে চান লিখে পাঠান:\n<i>(রেট: ৳{int(bdt_rate)} BDT = $1.00 USD)</i>", reply_markup=get_back_keyboard())

            elif data == "dep_nagad":
                set_user_state(user_id, {"step": "WAITING_AMOUNT", "method": "NAGAD"})
                send_message(chat_id, f"🟠 <b>Nagad Deposit Selected</b>\n\nকত টাকা (BDT) ডিপোজিট করতে চান লিখে পাঠান:\n<i>(রেট: ৳{int(bdt_rate)} BDT = $1.00 USD)</i>", reply_markup=get_back_keyboard())

            elif data == "dep_binance":
                set_user_state(user_id, {"step": "WAITING_AMOUNT", "method": "BINANCE"})
                send_message(chat_id, "🟡 <b>Binance Deposit Selected</b>\n\nকত <b>USDT</b> (USD) ডিপোজিট করতে চান লিখে পাঠান:", reply_markup=get_back_keyboard())

            elif data == "admin_set_rate" and is_admin:
                set_user_state(user_id, "ADMIN_SET_PRICE")
                send_message(chat_id, f"🏷️ <b>WhatsApp নম্বরের নতুন মূল্য ($ USD) লিখে পাঠান:</b>\n(বর্তমান রেট: ${current_price:.2f} USD)", reply_markup=get_back_keyboard())

            elif data == "admin_broadcast" and is_admin:
                set_user_state(user_id, "ADMIN_BROADCAST")
                send_message(chat_id, "📢 <b>সব ইউজারদের উদ্দেশ্যে পাঠানোর বার্তাটি লিখে পাঠান:</b>", reply_markup=get_back_keyboard())

            elif data == "admin_upload_file" and is_admin:
                set_user_state(user_id, "ADMIN_UPLOAD_FILE")
                send_message(chat_id, "📁 <b>নম্বর সম্বলিত ফাইলটি (.txt / .csv) এখানে পাঠাও:</b>\nফরম্যাট:\n<code>+1234567890, https://otp-link.com/check</code>", reply_markup=get_back_keyboard())

            elif data == "admin_view_stock" and is_admin:
                stock_items = get_all_stock()
                nord_count = get_vpn_stock_count("nord")
                proton_count = get_vpn_stock_count("proton")
                
                stock_text = (
                    f"📊 <b>বর্তমান স্টক ওভারভিউ:</b>\n\n"
                    f"📱 <b>WhatsApp Number Stock:</b> {len(stock_items)} টি\n"
                    f"🛡️ <b>NordVPN Stock:</b> {nord_count} টি\n"
                    f"🛡️ <b>ProtonVPN Stock:</b> {proton_count} টি\n\n"
                )
                
                if stock_items:
                    stock_text += "<b>WhatsApp নম্বরসমূহ:</b>\n"
                    for item in stock_items[:20]:
                        stock_text += f"📱 <code>{item[1]}</code>\n🔗 {item[2]}\n\n"
                    if len(stock_items) > 20:
                        stock_text += f"<i>...এবং আরও {len(stock_items) - 20} টি নম্বর রয়েছে।</i>"
                
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
                set_user_state(user_id, f"ADMIN_APPROVE_AMOUNT_{target_user}")
                send_message(chat_id, f"<b>User ID {target_user}-এর অ্যাকাউন্টে কত $ (USD) যোগ করতে চান লিখে পাঠান:</b>")

            elif data.startswith("dep_rej_") and is_admin:
                target_user = int(data.replace("dep_rej_", ""))
                send_message(target_user, f"❌ <b>আপনার জমা দেওয়া ডিপোজিট প্রুফটি সঠিক নয়!</b>\nদয়া করে সঠিক তথ্য দিন বা সাপোর্ট অ্যাডমিনের সাথে কথা বলুন: @{SUPPORT_USERNAME}")
                send_message(chat_id, f"❌ <b>User ID {target_user}-এর ডিপোজিট বাতিল করা হয়েছে।</b>")

    except Exception as general_error:
        print(f"General Exception Prevented Crash: {general_error}")

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
