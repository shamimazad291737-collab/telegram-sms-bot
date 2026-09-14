import os
import logging
import asyncio
import requests
from aiogram import Bot, Dispatcher, executor, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from motor.motor_asyncio import AsyncIOMotorClient
from keep_alive import keep_alive

# Logging setup
logging.basicConfig(level=logging.INFO)

# Configuration from Environment Variables
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
MONGO_URI = os.getenv("MONGO_URI", "mongodb+srv://shamimazad291736_db_user:CwJ0XbyRhDrRfgRJ@cluster0.mswnw5q.mongodb.net/?appName=Cluster0")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "123456789").split(",") if x.strip().isdigit()]
OTP_FORWARD_GROUP_ID = os.getenv("OTP_FORWARD_GROUP_ID", "-1001234567890") # ওটিপি যে গ্রুপে ফরওয়ার্ড হবে তার আইডি বা ইউজারনেম

bot = Bot(token=BOT_TOKEN, parse_mode=types.ParseMode.HTML)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

# MongoDB Connection
client = AsyncIOMotorClient(MONGO_URI)
db = client.get_database("whatsapp_bot_db")
users_col = db.users
stock_col = db.stock
settings_col = db.settings
deposits_col = db.deposits
history_col = db.purchase_history

# FSM States
class AdminStates(StatesGroup):
    upload_stock = State()
    set_price = State()
    add_group = State()
    broadcast_msg = State()

class DepositStates(StatesGroup):
    amount = State()
    trx_id = State()
    screenshot = State()

class OtpStates(StatesGroup):
    waiting_for_link = State()

# --- Keyboards ---
def main_menu(user_id):
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    keyboard.add("📱 Buy Number", "👤 My Profile")
    keyboard.add("💳 Deposit", "🛠️ Check OTP")
    keyboard.add("📞 Support", "ℹ️ Help")
    if user_id in ADMIN_IDS:
        keyboard.add("⚙️ Admin Panel")
    return keyboard

def buy_number_menu():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    keyboard.add("🔹 Single Number", "🔸 Multiple Numbers")
    keyboard.add("🔙 Back to Menu")
    return keyboard

def admin_menu_kb():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    keyboard.add("📤 Upload Stock (.txt)", "💰 Set Price")
    keyboard.add("📢 Add Force Join Group", "📢 Broadcast")
    keyboard.add("👥 User Management", "🔙 Back to Menu")
    return keyboard

# --- Start & Force Join Check ---
async def check_force_join(user_id):
    settings = await settings_col.find_one({"type": "force_join"})
    if not settings or not settings.get("groups"):
        return True
    
    for group in settings["groups"]:
        try:
            member = await bot.get_chat_member(chat_id=group, user_id=user_id)
            if member.status in ['left', 'kicked']:
                return False
        except:
            pass
    return True

@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    user_name = message.from_user.full_name
    
    user = await users_col.find_one({"user_id": user_id})
    if not user:
        await users_col.insert_one({
            "user_id": user_id,
            "name": user_name,
            "balance": 0.0,
            "total_purchased": 0,
            "total_deposited": 0.0,
            "banned": False
        })
    else:
        if user.get("banned", False):
            await message.answer("⚠️ You are banned from using this bot.")
            return

    is_joined = await check_force_join(user_id)
    if not is_joined:
        settings = await settings_col.find_one({"type": "force_join"})
        kb = types.InlineKeyboardMarkup()
        for i, grp in enumerate(settings["groups"]):
            kb.add(types.InlineKeyboardButton(f"Join Group {i+1}", url=settings["links"][i]))
        kb.add(types.InlineKeyboardButton("✅ I Have Joined", callback_data="check_join"))
        await message.answer("⚠️ Please join our required channels/groups first to use this bot!", reply_markup=kb)
        return

    await message.answer(f"Welcome to WhatsApp Number Store Bot! 🤖\nChoose an option below:", reply_markup=main_menu(user_id))

@dp.callback_query_handler(text="check_join")
async def verify_join(call: types.CallbackQuery):
    user_id = call.from_user.id
    if await check_force_join(user_id):
        await call.message.answer("✅ Verification Successful!", reply_markup=main_menu(user_id))
        await call.message.delete()
    else:
        await call.answer("❌ You haven't joined all groups yet!", show_alert=True)

# --- Navigation Handlers ---
@dp.message_handler(text="📱 Buy Number")
async def buy_number_handler(message: types.Message):
    await message.answer("Select your buying option:", reply_markup=buy_number_menu())

@dp.message_handler(text="🔙 Back to Menu")
async def back_to_menu(message: types.Message):
    await message.answer("Main Menu:", reply_markup=main_menu(message.from_user.id))

@dp.message_handler(text="👤 My Profile")
async def my_profile(message: types.Message):
    user = await users_col.find_one({"user_id": message.from_user.id})
    if not user:
        await message.answer("Profile not found. Send /start")
        return
    
    text = (
        f"👤 <b>Your Profile</b>\n\n"
        f"🆔 User ID: <code>{user['user_id']}</code>\n"
        f"👤 Name: {user['name']}\n"
        f"💰 Balance: ${user.get('balance', 0.0):.2f}\n"
        f"📦 Total Purchased: {user.get('total_purchased', 0)} Numbers\n"
        f"💵 Total Deposited: ${user.get('total_deposited', 0.0):.2f}"
    )
    await message.answer(text)

@dp.message_handler(text="📞 Support")
async def support_handler(message: types.Message):
    await message.answer("📞 <b>Admin Support Contact:</b>\nFor any help, message our admin: @AdminUsername")

# --- Buy Number Logic ---
@dp.message_handler(text="🔹 Single Number")
async def buy_single_number(message: types.Message):
    user_id = message.from_user.id
    settings = await settings_col.find_one({"type": "pricing"})
    price = settings.get("single_price", 0.5) if settings else 0.5
    
    user = await users_col.find_one({"user_id": user_id})
    if user["balance"] < price:
        await message.answer(f"❌ Insufficient balance! You need ${price} to buy a single number.")
        return
    
    stock_item = await stock_col.find_one({"status": "available"})
    if not stock_item:
        await message.answer("❌ Sorry, stock is currently empty. Try again later.")
        return
    
    await users_col.update_one({"user_id": user_id}, {"$inc": {"balance": -price, "total_purchased": 1}})
    await stock_col.update_one({"_id": stock_item["_id"]}, {"$set": {"status": "sold", "buyer_id": user_id}})
    
    await history_col.insert_one({
        "user_id": user_id,
        "number_data": stock_item["data"],
        "price": price
    })
    
    await message.answer(f"✅ <b>Number & OTP Link Purchased Successfully!</b>\n\n<code>{stock_item['data']}</code>")

@dp.message_handler(text="🔸 Multiple Numbers")
async def buy_multiple_prompt(message: types.Message):
    await message.answer("How many numbers do you want to buy? (Send a number, e.g., 5)")

@dp.message_handler(lambda msg: msg.text.isdigit() and msg.from_user.id not in ADMIN_IDS)
async def process_multiple_buy(message: types.Message):
    qty = int(message.text)
    user_id = message.from_user.id
    
    settings = await settings_col.find_one({"type": "pricing"})
    unit_price = settings.get("single_price", 0.5) if settings else 0.5
    total_price = qty * unit_price
    
    user = await users_col.find_one({"user_id": user_id})
    if user["balance"] < total_price:
        await message.answer(f"❌ Insufficient balance! Total cost for {qty} numbers is ${total_price:.2f}.")
        return
    
    available_cursor = stock_col.find({"status": "available"}).limit(qty)
    available_items = await available_cursor.to_list(length=qty)
    
    if len(available_items) < qty:
        await message.answer(f"❌ Sorry! Only {len(available_items)} numbers available in stock right now.")
        return
    
    file_content = ""
    item_ids = []
    for item in available_items:
        file_content += f"{item['data']}\n"
        item_ids.append(item["_id"])
        
    await users_col.update_one({"user_id": user_id}, {"$inc": {"balance": -total_price, "total_purchased": qty}})
    await stock_col.update_many({"_id": {"$in": item_ids}}, {"$set": {"status": "sold", "buyer_id": user_id}})
    
    await history_col.insert_one({
        "user_id": user_id,
        "number_data": f"Bulk Purchase: {qty} numbers",
        "price": total_price
    })
    
    file_path = f"numbers_{user_id}.txt"
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(file_content)
        
    await message.answer(f"✅ Successfully purchased {qty} numbers for ${total_price:.2f}!")
    await message.answer_document(open(file_path, "rb"), caption="📱 Your purchased numbers & OTP links:")
    if os.path.exists(file_path):
        os.remove(file_path)

# --- Deposit System ---
@dp.message_handler(text="💳 Deposit")
async def deposit_start(message: types.Message):
    kb = types.InlineKeyboardMarkup(row_width=3)
    kb.add(
        types.InlineKeyboardButton("Bkash", callback_data="dep_bkash"),
        types.InlineKeyboardButton("Nagad", callback_data="dep_nagad"),
        types.InlineKeyboardButton("Binance", callback_data="dep_binance")
    )
    await message.answer("Select payment method for deposit:\n(Exchange Rate: 1 USD = 128 BDT)", reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith("dep_"))
async def select_payment_method(call: types.CallbackQuery, state: FSMContext):
    method = call.data.split("_")[1].upper()
    acc_num = "01700000000 (Personal/Merchant)" if method in ["BKASH", "NAGAD"] else "Binance Pay ID: 12345678"
    
    async with state.proxy() as data:
        data['method'] = method
        
    await call.message.answer(f"💳 Send money to {method}:\n<b>{acc_num}</b>\n\nNow, enter how much USD you want to deposit (e.g., 5):")
    await DepositStates.amount.set()
    await call.message.delete()

@dp.message_handler(state=DepositStates.amount)
async def process_deposit_amount(message: types.Message, state: FSMContext):
    try:
        usd_amount = float(message.text)
        bdt_amount = usd_amount * 128
        async with state.proxy() as data:
            data['usd'] = usd_amount
            data['bdt'] = bdt_amount
            
        await message.answer(f"You requested to deposit ${usd_amount} (৳{bdt_amount}).\nNow, enter your Transaction ID (TrxID):")
        await DepositStates.trx_id.set()
    except ValueError:
        await message.answer("❌ Please enter a valid number (e.g., 5 or 10).")

@dp.message_handler(state=DepositStates.trx_id)
async def process_deposit_trx(message: types.Message, state: FSMContext):
    trx_id = message.text
    async with state.proxy() as data:
        data['trx_id'] = trx_id
        
    await message.answer("Please send the screenshot of your payment:")
    await DepositStates.screenshot.set()

@dp.message_handler(content_types=['photo'], state=DepositStates.screenshot)
async def process_deposit_screenshot(message: types.Message, state: FSMContext):
    photo_id = message.photo[-1].file_id
    async with state.proxy() as data:
        method = data['method']
        usd = data['usd']
        bdt = data['bdt']
        trx_id = data['trx_id']
        
    user_id = message.from_user.id
    kb = types.InlineKeyboardMarkup()
    kb.add(
        types.InlineKeyboardButton("✅ Approve", callback_data=f"app_dep_{user_id}_{usd}"),
        types.InlineKeyboardButton("❌ Reject", callback_data=f"rej_dep_{user_id}")
    )
    
    caption = (
        f"🔔 <b>New Deposit Request!</b>\n\n"
        f"👤 User: {message.from_user.full_name} (<code>{user_id}</code>)\n"
        f"💳 Method: {method}\n"
        f"💵 Amount: ${usd} (৳{bdt})\n"
        f"📌 TrxID: <code>{trx_id}</code>"
    )
    
    for admin in ADMIN_IDS:
        try:
            await bot.send_photo(admin, photo_id, caption=caption, reply_markup=kb)
        except:
            pass
            
    await message.answer("✅ Deposit request submitted successfully! Admin will review it soon.", reply_markup=main_menu(user_id))
    await state.finish()

@dp.callback_query_handler(lambda c: c.data.startswith("app_dep_") or c.data.startswith("rej_dep_"))
async def admin_deposit_action(call: types.CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        return
    
    parts = call.data.split("_")
    action = parts[0]
    user_id = int(parts[2])
    
    if action == "app":
        usd = float(parts[3])
        await users_col.update_one({"user_id": user_id}, {"$inc": {"balance": usd, "total_deposited": usd}})
        await bot.send_message(user_id, f"✅ Your deposit of ${usd} has been approved by admin!")
        await call.message.edit_caption(caption=call.message.caption + "\n\n<b>[APPROVED]</b>")
    else:
        await bot.send_message(user_id, "❌ Your deposit request was rejected by admin.")
        await call.message.edit_caption(caption=call.message.caption + "\n\n<b>[REJECTED]</b>")

# --- Real OTP Checking & Group Forwarding Logic ---
@dp.message_handler(text="🛠️ Check OTP")
async def check_otp_start(message: types.Message):
    await message.answer("Send the full OTP link or API URL (e.g., containing `/api/sms/...`):")
    await OtpStates.waiting_for_link.set()

@dp.message_handler(state=OtpStates.waiting_for_link)
async def fetch_otp_result(message: types.Message, state: FSMContext):
    target_url = message.text.strip()
    
    # যদি ইউজার শুধু লিংকের শেষের অংশ বা পুরো URL দেয় সেটিকে ফরম্যাট করে নেওয়া
    if not target_url.startswith("http"):
        # যদি ডোমেইন ছাড়া শুধু পাথ দেয়, তবে বেস ডোমেইন এখানে সেট করতে পারো
        target_url = f"https://yourdomain.com{target_url}"
        
    await message.answer("⏳ Checking for OTP, please wait...")
    
    try:
        # এপিআই রিকোয়েস্ট পাঠানো (যেমনটি তোমার সোর্স কোডে ছিল)
        response = requests.get(target_url, headers={"Cache-Control": "no-store"}, timeout=10)
        otp_text = response.text.strip()
        
        # রেসপন্সটি ৩ থেকে ১০ ডিজিটের কোড কিনা চেক করা
        if otp_text.isdigit() and 3 <= len(otp_text) <= 10:
            result_msg = (
                f"✅ <b>OTP Received Successfully!</b>\n\n"
                f"🔗 Link: <code>{target_url}</code>\n"
                f"🔑 OTP Code: <b>{otp_text}</b>"
            )
            await message.answer(result_msg)
            
            # নির্দিষ্ট টেলিগ্রাম গ্রুপে ফরওয়ার্ড করা
            try:
                await bot.send_message(OTP_FORWARD_GROUP_ID, f"🔔 <b>New OTP Fetched via Bot!</b>\n\nUser: {message.from_user.full_name}\nCode: <b>{otp_text}</b>")
            except Exception as e:
                logging.error(f"Group forward error: {e}")
                
        else:
            await message.answer(f"⏳ No code yet or waiting... Response: <code>{otp_text[:50]}</code>\nTry again in a few seconds.")
            
    except Exception as e:
        await message.answer(f"❌ Error connecting to OTP API: {str(e)}")
        
    await state.finish()

# --- Admin Panel ---
@dp.message_handler(text="⚙️ Admin Panel")
async def admin_panel(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    await message.answer("Welcome to Admin Panel:", reply_markup=admin_menu_kb())

@dp.message_handler(text="📤 Upload Stock (.txt)")
async def admin_upload_prompt(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    await message.answer("Please send the `.txt` file containing numbers and OTP links (Format: Number|OTP_Link per line).")
    await AdminStates.upload_stock.set()

@dp.message_handler(content_types=['document'], state=AdminStates.upload_stock)
async def process_stock_file(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    document = message.document
    if not document.file_name.endswith('.txt'):
        await message.answer("❌ Please send a valid .txt file.")
        return
    
    file_info = await bot.get_file(document.file_id)
    downloaded_file = await bot.download_file(file_info.file_path)
    
    content = downloaded_file.read().decode('utf-8')
    lines = content.splitlines()
    
    count = 0
    for line in lines:
        if line.strip():
            await stock_col.insert_one({"data": line.strip(), "status": "available", "buyer_id": None})
            count += 1
            
    await message.answer(f"✅ Successfully uploaded {count} numbers to stock!", reply_markup=admin_menu_kb())
    await state.finish()

@dp.message_handler(text="💰 Set Price")
async def set_price_prompt(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    await message.answer("Send the new price for single number in USD (e.g., 0.25):")
    await AdminStates.set_price.set()

@dp.message_handler(state=AdminStates.set_price)
async def save_new_price(message: types.Message, state: FSMContext):
    try:
        price = float(message.text)
        await settings_col.update_one({"type": "pricing"}, {"$set": {"single_price": price}}, upsert=True)
        await message.answer(f"✅ Price updated successfully to ${price}", reply_markup=admin_menu_kb())
        await state.finish()
    except ValueError:
        await message.answer("❌ Invalid amount. Enter a valid number:")

@dp.message_handler(text="👥 User Management")
async def user_management(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    users = await users_col.find({}).to_list(length=20)
    kb = types.InlineKeyboardMarkup()
    for u in users:
        kb.add(types.InlineKeyboardButton(f"{u['name']} (${u.get('balance',0)})", callback_data=f"manage_user_{u['user_id']}"))
        
    await message.answer("Select a user to view history & manage:", reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith("manage_user_"))
async def view_user_detail(call: types.CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        return
    user_id = int(call.data.split("_")[2])
    user = await users_col.find_one({"user_id": user_id})
    
    history = await history_col.find({"user_id": user_id}).to_list(length=10)
    hist_text = "\n".join([f"- {h['number_data']} (${h['price']})" for h in history]) or "No purchases yet."
    
    text = (
        f"👤 <b>User Management Details</b>\n\n"
        f"ID: <code>{user['user_id']}</code>\n"
        f"Name: {user['name']}\n"
        f"Balance: ${user.get('balance', 0.0)}\n"
        f"Total Purchased: {user.get('total_purchased', 0)}\n\n"
        f"<b>Recent History:</b>\n{hist_text}"
    )
    
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🚫 Ban/Unban User", callback_data=f"toggle_ban_{user_id}"))
    await call.message.answer(text, reply_markup=kb)

# --- Main Entry ---
if __name__ == '__main__':
    keep_alive()
    executor.start_polling(dp, skip_updates=True)
