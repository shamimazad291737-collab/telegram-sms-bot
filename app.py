import os
import sqlite3
import requests
import html
import threading
import time
import re
from flask import Flask, request, render_template_string

app = Flask(__name__)

TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0")) if os.environ.get("ADMIN_ID") else 0
SUPPORT_USERNAME = os.environ.get("SUPPORT_USERNAME", "telegram")
OTP_GROUP_ID = os.environ.get("OTP_GROUP_ID", "")
BASE_URL = f"https://api.telegram.org/bot{TOKEN}/"

BDT_PER_USD = 120.0
BKASH_NUMBER = "01858582881 (Personal)"
NAGAD_NUMBER = "01858582881 (Personal)"
BINANCE_PAY_ID = "123456789"

user_states = {}

# HTML Template for Telegram Mini App (Admin Web Panel)
WEB_PANEL_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Admin Stock Panel</title>
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
    <style>
        body { font-family: Arial, sans-serif; background: #121212; color: #fff; padding: 20px; text-align: center; }
        .card { background: #1e1e1e; padding: 20px; border-radius: 12px; box-shadow: 0 4px 10px rgba(0,0,0,0.5); }
        input[type="file"] { display: none; }
        label { background: #0088cc; padding: 12px 20px; border-radius: 8px; color: #fff; cursor: pointer; display: inline-block; margin-top: 15px; }
        button { background: #28a745; border: none; padding: 12px 20px; color: #fff; border-radius: 8px; font-weight: bold; cursor: pointer; margin-top: 15px; width: 100%; }
        #status { margin-top: 15px; font-weight: bold; }
    </style>
</head>
<body>
    <div class="card">
        <h2>📱 Stock File Upload</h2>
        <p>Upload .txt file containing line by line:<br><code>+1234567890 http://otp-link.com</code></p>
        <form id="uploadForm">
            <label for="fileInput">📁 Choose .txt File</label>
            <input type="file" id="fileInput" accept=".txt" required onchange="showFileName()">
            <p id="fileName" style="color: #aaa;"></p>
            <button type="submit">🚀 Save To Bot Stock</button>
        </form>
        <div id="status"></div>
    </div>

    <script>
        const tg = window.Telegram.WebApp;
        tg.expand();

        function showFileName() {
            const input = document.getElementById('fileInput');
            if (input.files.length > 0) {
                document.getElementById('fileName').innerText = input.files[0].name;
            }
        }

        document.getElementById('uploadForm').addEventListener('submit', async function(e) {
            e.preventDefault();
            const fileInput = document.getElementById('fileInput');
            const statusDiv = document.getElementById('status');
            
            if (!fileInput.files.length) return;

            const formData = new FormData();
            formData.append('file', fileInput.files[0]);

            statusDiv.innerText = "⏳ Uploading...";
            statusDiv.style.color = "#ffc107";

            try {
                const response = await fetch('/api/upload_stock', {
                    method: 'POST',
                    body: formData
                });
                const result = await response.json();
                if (result.success) {
                    statusDiv.innerText = "✅ " + result.message;
                    statusDiv.style.color = "#28a745";
                } else {
                    statusDiv.innerText = "❌ " + result.message;
                    statusDiv.style.color = "#dc3545";
                }
            } catch (err) {
                statusDiv.innerText = "❌ Error uploading file!";
                statusDiv.style.color = "#dc3545";
            }
        });
    </script>
</body>
</html>
"""

# Flask Web Server
@app.route('/')
def home():
    return "Bot and Web Panel running perfectly!"

@app.route('/admin_panel')
def admin_panel():
    return render_template_string(WEB_PANEL_HTML)

@app.route('/api/upload_stock', methods=['POST'])
def api_upload_stock():
    if 'file' not in request.files:
        return {"success": False, "message": "No file uploaded!"}
    file = request.files['file']
    content = file.read().decode('utf-8', errors='ignore')
    
    count = 0
    for line in content.splitlines():
        line = line.strip()
        if line.startswith("+") and ("http://" in line or "https://" in line):
            parts = line.replace(",", " ").split()
            if len(parts) >= 2:
                add_stock_item(parts[0].strip(), parts[1].strip())
                count += 1
    
    return {"success": True, "message": f"{count} Numbers added to stock successfully!"}

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# Database Operations
def init_db():
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT, balance REAL DEFAULT 0.0, total_recharge REAL DEFAULT 0.0)')
    cursor.execute('CREATE TABLE IF NOT EXISTS stock (id INTEGER PRIMARY KEY AUTOINCREMENT, phone_number TEXT, otp_link TEXT)')
    cursor.execute('CREATE TABLE IF NOT EXISTS active_orders (order_id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, phone_number TEXT, otp_link TEXT)')
    cursor.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)')
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

def get_active_order_link(phone):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute("SELECT otp_link FROM active_orders WHERE phone_number = ? ORDER BY order_id DESC LIMIT 1", (phone,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None

def save_active_order(user_id, phone, link):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute("INSERT INTO active_orders (user_id, phone_number, otp_link) VALUES (?, ?, ?)", (user_id, phone, link))
    conn.commit()
    conn.close()

def send_message(chat_id, text, reply_markup=None):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        return requests.post(BASE_URL + "sendMessage", json=payload, timeout=10).json()
    except Exception as e:
        print(f"Error sending message: {e}")
        return {}

def send_photo_to_admin(chat_id, photo_file_id, caption, reply_markup=None):
    payload = {"chat_id": chat_id, "photo": photo_file_id, "caption": caption, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        requests.post(BASE_URL + "sendPhoto", json=payload, timeout=10)
    except Exception as e:
        print(f"Error sending photo: {e}")

# OTP Checker Engine
def fetch_otp_from_url(phone, link):
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Cache-Control": "no-cache"
    })
    clean_phone = re.sub(r'\D', '', phone)
    try:
        res = session.get(link, timeout=5)
        page_text = res.text
        otp_matches = re.findall(r'\b\d{6}\b', page_text)
        filtered_otps = [code for code in otp_matches if code not in ['111111', '000000', '123456', '169582', '111110'] and code not in clean_phone]
        if filtered_otps:
            return filtered_otps[0]
    except Exception as e:
        print(f"OTP Fetch Error: {e}")
    return None

def background_otp_listener(user_id, phone, link):
    for _ in range(60): # 2 Minutes Polling
        otp_code = fetch_otp_from_url(phone, link)
        if otp_code:
            markup = {"inline_keyboard": [[{"text": "🛒 Buy Another Number", "callback_data": "confirm_buy_usa"}]]}
            send_message(user_id, f"🎉 <b>OTP প্রাপ্ত হয়েছে!</b>\n\n📱 <b>নম্বর:</b> <code>{phone}</code>\n🔑 <b>OTP Code:</b> <code>{otp_code}</code>", reply_markup=markup)
            if OTP_GROUP_ID:
                send_message(OTP_GROUP_ID, f"🎉 <b>New OTP Received!</b>\n\n📱 <b>Number:</b> <code>{phone}</code>\n🔑 <b>OTP Code:</b> <code>{otp_code}</code>")
            return
        time.sleep(2)

# Keyboard Layouts
def get_main_keyboard(is_admin=False):
    kb = [[{"text": "🛒 BUY NUMBER"}, {"text": "💳 DEPOSIT"}], [{"text": "👤 PROFILE"}, {"text": "🎧 SUPPORT"}]]
    if is_admin:
        kb.append([{"text": "⚙️ ADMIN PANEL"}])
    return {"keyboard": kb, "resize_keyboard": True}

def get_back_keyboard():
    return {"keyboard": [[{"text": "⬅️ Back"}]], "resize_keyboard": True}

# Core Bot Handler
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
                    user_states[user_id] = {"step": "WAITING_TRX", "method": method, "amount": amount}
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
                user_states[user_id] = {"step": "WAITING_SCREENSHOT", "method": state_data["method"], "amount": state_data["amount"], "trx_id": text}
                send_message(chat_id, "📸 <b>পেমেন্টের একটি স্ক্রিনশট পাঠান:</b>", reply_markup=get_back_keyboard())
                return

            elif isinstance(state_data, dict) and state_data.get("step") == "WAITING_SCREENSHOT":
                if "photo" in msg:
                    photo_file_id = msg["photo"][-1]["file_id"]
                    method = state_data["method"]
                    amount = state_data["amount"]
                    trx_id = state_data["trx_id"]
                    converted_usd = amount if method == "BINANCE" else round(amount / BDT_PER_USD, 2)
                    amount_info = f"{amount:.2f} USDT" if method == "BINANCE" else f"৳{amount:.2f} BDT (Estimated: ${converted_usd:.2f} USD)"
                    
                    admin_markup = {
                        "inline_keyboard": [
                            [{"text": f"✅ Auto Approve (${converted_usd:.2f})", "callback_data": f"appusd_{user_id}_{converted_usd:.2f}"}, {"text": "✏️ Custom Amount", "callback_data": f"dep_app_{user_id}"}],
                            [{"text": "❌ Reject", "callback_data": f"dep_rej_{user_id}"}]
                        ]
                    }
                    admin_caption = f"📥 <b>New Deposit Request ({method})</b>\n\n👤 <b>User:</b> {html.escape(first_name)} (@{username})\n🆔 <b>User ID:</b> <code>{user_id}</code>\n💰 <b>Payment:</b> {amount_info}\n🧾 <b>TrxID:</b> <code>{html.escape(trx_id)}</code>"
                    send_photo_to_admin(ADMIN_ID, photo_file_id, admin_caption, reply_markup=admin_markup)
                    send_message(chat_id, "✅ <b>রিকোয়েস্ট অ্যাডমিনের কাছে পাঠানো হয়েছে!</b>", reply_markup=get_main_keyboard(is_admin))
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
                    set_number_price(float(text))
                    send_message(chat_id, f"✅ <b>নতুন মূল্য: ${float(text):.2f} USD</b>", reply_markup=get_main_keyboard(is_admin))
                except Exception:
                    send_message(chat_id, "❌ <b>ভুল ইনপুট!</b>")
                del user_states[user_id]
                return

            elif isinstance(state_data, str) and state_data == "ADMIN_BROADCAST":
                for u_id in get_all_users():
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
            markup = {"inline_keyboard": [[{"text": f"🇺🇸 Buy USA WhatsApp Number (${current_price:.2f} USD)", "callback_data": "confirm_buy_usa"}]]}
            send_message(chat_id, f"<b>WhatsApp Service:</b>\nমূল্য: <b>${current_price:.2f} USD</b>", reply_markup=get_back_keyboard())
            send_message(chat_id, "পেমেন্ট গেটওয়ে / সার্ভিস অপশন:", reply_markup=markup)
        elif text == "💳 DEPOSIT":
            markup = {"inline_keyboard": [[{"text": "💖 bKash (BDT)", "callback_data": "dep_bkash"}], [{"text": "🟠 Nagad (BDT)", "callback_data": "dep_nagad"}], [{"text": "🟡 Binance (Crypto USDT)", "callback_data": "dep_binance"}]]}
            send_message(chat_id, "<b>Deposit Options:</b>", reply_markup=get_back_keyboard())
            send_message(chat_id, "পেমেন্ট গেটওয়ে সিলেক্ট করুন:", reply_markup=markup)
        elif text == "👤 PROFILE":
            u_info = get_user(user_id)
            send_message(chat_id, f"👤 <b>Profile Info</b>\n\n🆔 <b>ID:</b> <code>{user_id}</code>\n💰 <b>Balance:</b> ${u_info[2]:.2f} USD\n📊 <b>Total Deposit:</b> ${u_info[3]:.2f} USD", reply_markup=get_back_keyboard())
        elif text == "🎧 SUPPORT":
            send_message(chat_id, f"<b>সহায়তার জন্য যোগাযোগ করুন:</b>\n👉 @{SUPPORT_USERNAME}", reply_markup=get_back_keyboard())
        elif text == "⚙️ ADMIN PANEL" and is_admin:
            web_panel_url = os.environ.get("RENDER_EXTERNAL_URL", "http://localhost:10000") + "/admin_panel"
            markup = {
                "inline_keyboard": [
                    [{"text": "🌐 Open Admin Web Panel", "web_app": {"url": web_panel_url}}],
                    [{"text": "🏷️ Change Price", "callback_data": "admin_set_rate"}, {"text": "📢 Broadcast", "callback_data": "admin_broadcast"}],
                    [{"text": "📊 View Stock", "callback_data": "admin_view_stock"}, {"text": "🗑️ Delete Stock", "callback_data": "admin_delete_stock_confirm"}]
                ]
            }
            send_message(chat_id, "<b>⚙️ ADMIN PANEL</b>\n\nওয়েব প্যানেল থেকে ফাইল আপলোড করতে নিচের বাটনে চাপ দিন:", reply_markup=markup)

    elif "callback_query" in update:
        cb = update["callback_query"]
        chat_id = cb["message"]["chat"]["id"]
        user_id = cb["from"]["id"]
        data = cb.get("data", "")
        is_admin = (user_id == ADMIN_ID)
        try:
            requests.post(BASE_URL + "answerCallbackQuery", data={"callback_query_id": cb["id"]}, timeout=5)
        except Exception:
            pass

        current_price = get_number_price()
        if data == "confirm_buy_usa":
            u_info = get_user(user_id)
            if (u_info[2] if u_info else 0.0) < current_price:
                send_message(chat_id, f"❌ <b>পর্যাপ্ত ব্যালেন্স নেই!</b>\nন্যূনতম ${current_price:.2f} USD লাগবে।")
                return
            phone, link = pop_stock_item()
            if not phone:
                send_message(chat_id, "⚠️ <b>স্টক ফাঁকা রয়েছে!</b> কিছু সময় পর চেষ্টা করুন।")
                return
            
            deduct_balance(user_id, current_price)
            save_active_order(user_id, phone, link)
            
            markup = {
                "inline_keyboard": [
                    [{"text": "🔄 Check OTP", "callback_data": f"checkotp_{phone}"}]
                ]
            }
            
            msg_text = f"✅ <b>নম্বর বরাদ্দ করা হয়েছে!</b>\n\n📱 <b>Number:</b> <code>{phone}</code>\n🔗 <b>OTP Link:</b> <code>{link}</code>\n\n💰 <b>ফি কাটা হয়েছে:</b> ${current_price:.2f} USD\n\n⚡ <b>ওটিপি চেক করতে 'Check OTP' বাটনে ক্লিক করুন।</b>"
            send_message(chat_id, msg_text, reply_markup=markup)
            
            # Auto Polling Background Thread
            threading.Thread(target=background_otp_listener, args=(user_id, phone, link), daemon=True).start()

        elif data.startswith("checkotp_"):
            phone = data.replace("checkotp_", "")
            link = get_active_order_link(phone)
            if link:
                otp_code = fetch_otp_from_url(phone, link)
                if otp_code:
                    markup = {"inline_keyboard": [[{"text": "🛒 Buy Another Number", "callback_data": "confirm_buy_usa"}]]}
                    send_message(chat_id, f"🎉 <b>OTP প্রাপ্ত হয়েছে!</b>\n\n📱 <b>নম্বর:</b> <code>{phone}</code>\n🔑 <b>OTP Code:</b> <code>{otp_code}</code>", reply_markup=markup)
                    if OTP_GROUP_ID:
                        send_message(OTP_GROUP_ID, f"🎉 <b>New OTP Received!</b>\n\n📱 <b>Number:</b> <code>{phone}</code>\n🔑 <b>OTP Code:</b> <code>{otp_code}</code>")
                else:
                    send_message(chat_id, f"⏳ <code>{phone}</code> নম্বরের লিংকে এখনও ওটিপি আসেনি, আবার চেষ্টা করুন।")
            else:
                send_message(chat_id, "❌ নম্বরটির তথ্য পাওয়া যায়নি!")

        elif data == "dep_bkash":
            user_states[user_id] = {"step": "WAITING_AMOUNT", "method": "BKASH"}
            send_message(chat_id, "💖 <b>bKash Deposit</b>\nকত টাকা (BDT) ডিপোজিট করবেন লিখুন:", reply_markup=get_back_keyboard())
        elif data == "dep_nagad":
            user_states[user_id] = {"step": "WAITING_AMOUNT", "method": "NAGAD"}
            send_message(chat_id, "🟠 <b>Nagad Deposit</b>\nকত টাকা (BDT) ডিপোজিট করবেন লিখুন:", reply_markup=get_back_keyboard())
        elif data == "dep_binance":
            user_states[user_id] = {"step": "WAITING_AMOUNT", "method": "BINANCE"}
            send_message(chat_id, "🟡 <b>Binance Deposit</b>\nকত USDT ডিপোজিট করবেন লিখুন:", reply_markup=get_back_keyboard())
        elif data == "admin_set_rate" and is_admin:
            user_states[user_id] = "ADMIN_SET_PRICE"
            send_message(chat_id, "🏷️ <b>নতুন মূল্য লিখুন ($):</b>", reply_markup=get_back_keyboard())
        elif data == "admin_broadcast" and is_admin:
            user_states[user_id] = "ADMIN_BROADCAST"
            send_message(chat_id, "📢 <b>ব্রডকাস্ট বার্তা লিখুন:</b>", reply_markup=get_back_keyboard())
        elif data == "admin_view_stock" and is_admin:
            send_message(chat_id, f"📊 <b>মোট স্টক: {len(get_all_stock())} টি</b>")
        elif data == "admin_delete_stock_confirm" and is_admin:
            clear_all_stock()
            send_message(chat_id, "🗑️ <b>সমস্ত স্টক মুছে ফেলা হয়েছে।</b>")
        elif data.startswith("appusd_") and is_admin:
            parts = data.split("_")
            update_balance(int(parts[1]), float(parts[2]))
            send_message(chat_id, f"✅ <b>${float(parts[2]):.2f} USD অনুমোদিত হয়েছে।</b>")
            send_message(int(parts[1]), f"🎉 <b>আপনার ${float(parts[2]):.2f} USD ডিপোজিট যুক্ত হয়েছে!</b>")
        elif data.startswith("dep_app_") and is_admin:
            user_states[user_id] = f"ADMIN_APPROVE_AMOUNT_{data.replace('dep_app_', '')}"
            send_message(chat_id, "<b>ডলার অ্যামাউন্ট লিখুন:</b>")
        elif data.startswith("dep_rej_") and is_admin:
            target_user = int(data.replace("dep_rej_", ""))
            send_message(target_user, "❌ <b>ডিপোজিট বাতিল করা হয়েছে।</b>")
            send_message(chat_id, "❌ <b>বাতিল করা হয়েছে।</b>")

if __name__ == "__main__":
    init_db()
    threading.Thread(target=run_flask, daemon=True).start()
    print("🚀 Bot and Web Panel Online...")
    offset = 0
    while True:
        try:
            res = requests.get(BASE_URL + "getUpdates", params={"offset": offset, "timeout": 20}, timeout=25).json()
            if res.get("ok"):
                for update in res.get("result", []):
                    offset = update["update_id"] + 1
                    threading.Thread(target=lambda u: handle_update(u), args=(update,), daemon=True).start()
        except Exception as e:
            print(f"Polling Network Recovering... {e}")
            time.sleep(3)
