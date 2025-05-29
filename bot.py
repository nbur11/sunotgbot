import asyncio
import aiohttp
import aiofiles
import os
import logging
import json
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime, timedelta
from pydub import AudioSegment
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, PreCheckoutQuery, LabeledPrice, FSInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
import qrcode
from io import BytesIO
import uuid

# Конфигурация
MAIN_BOT_TOKEN = "7947448978:AAF9tgOuTd2YVaZcCrhxpPHYPBZs0h2x3SE"
AGENT_BOT_TOKEN = "8189844333:AAHHmGaubop2ewMzkCRMunyb8ZmswcjU5v4"
YUKASSA_TOKEN = "390540012:LIVE:70884"
SUNO_API_KEY = "e0aa832859da8ad919a7dc627cd8c3e5"
SUNO_BASE_URL = "https://apibox.erweima.ai"
FULL_VERSION_PRICE = 50000  # 500 рублей в копейках
AGENT_COMMISSION_PERCENT = 30  # Комиссия агента в процентах

# ID администраторов
OWNER_ID = 8638330
ADMIN_ID = 7519737387

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Инициализация ботов
main_bot = Bot(token=MAIN_BOT_TOKEN)
agent_bot = Bot(token=AGENT_BOT_TOKEN)

# Диспетчеры для каждого бота
main_dp = Dispatcher(storage=MemoryStorage())
agent_dp = Dispatcher(storage=MemoryStorage())

# Файлы для хранения данных
DATA_DIR = "bot_data"
USERS_FILE = f"{DATA_DIR}/users.json"
ORDERS_FILE = f"{DATA_DIR}/orders.json"
FEEDBACK_FILE = f"{DATA_DIR}/feedback.json"
PROMOCODES_FILE = f"{DATA_DIR}/promocodes.json"
BLOCKED_USERS_FILE = f"{DATA_DIR}/blocked_users.json"
PROMO_USAGE_FILE = f"{DATA_DIR}/promo_usage.json"
AGENTS_FILE = f"{DATA_DIR}/agents.json"
REFERRAL_STATS_FILE = f"{DATA_DIR}/referral_stats.json"
AGENT_PAYMENTS_FILE = f"{DATA_DIR}/agent_payments.json"

# Состояния FSM для основного бота
class MusicGeneration(StatesGroup):
    waiting_for_mode = State()
    waiting_for_voice = State()
    waiting_for_custom_prompt = State()
    waiting_for_custom_style = State()
    waiting_for_auto_prompt = State()
    waiting_for_feedback = State()
    waiting_for_rating = State()
    waiting_for_promocode = State()

class AdminPanel(StatesGroup):
    waiting_for_user_id_block = State()
    waiting_for_user_id_unblock = State()
    waiting_for_promocode_discount = State()
    waiting_for_promocode_name = State()
    waiting_for_promocode_uses = State()
    waiting_for_support_response = State()
    waiting_for_broadcast_text = State()
    waiting_for_broadcast_selection = State()

class Support(StatesGroup):
    waiting_for_support_message = State()

# Состояния FSM для агентского бота
class AgentRegistration(StatesGroup):
    waiting_for_type = State()
    waiting_for_name = State()
    waiting_for_phone = State()
    waiting_for_card = State()
    waiting_for_documents = State()
    waiting_for_withdrawal_amount = State()

# Инициализация файлов данных
def init_data_files():
    os.makedirs(DATA_DIR, exist_ok=True)
    
    files_to_init = [
        (USERS_FILE, {}),
        (ORDERS_FILE, {}),
        (FEEDBACK_FILE, []),
        (PROMOCODES_FILE, {"WELCOME": {"discount": 10, "uses": 0, "max_uses": 100}}),
        (BLOCKED_USERS_FILE, []),
        (PROMO_USAGE_FILE, []),
        (AGENTS_FILE, {}),
        (REFERRAL_STATS_FILE, {}),
        (AGENT_PAYMENTS_FILE, {})
    ]
    
    for file_path, default_data in files_to_init:
        if not os.path.exists(file_path):
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(default_data, f, ensure_ascii=False, indent=2)

# Функции для работы с данными
def load_json(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return {} if file_path in [USERS_FILE, ORDERS_FILE, AGENTS_FILE, REFERRAL_STATS_FILE, AGENT_PAYMENTS_FILE] else []

def save_json(file_path, data):
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def is_admin(user_id):
    return user_id in [OWNER_ID, ADMIN_ID]

def is_blocked(user_id):
    blocked_users = load_json(BLOCKED_USERS_FILE)
    return user_id in blocked_users

# Функции для работы с агентами
def register_agent(user_id, username, first_name, agent_type):
    agents = load_json(AGENTS_FILE)
    ref_code = str(uuid.uuid4())[:8]
    
    agents[str(user_id)] = {
        "username": username,
        "first_name": first_name,
        "type": agent_type,
        "ref_code": ref_code,
        "registration_date": datetime.now().isoformat(),
        "total_referrals": 0,
        "paid_referrals": 0,
        "total_earned": 0,
        "total_withdrawn": 0,
        "balance": 0,
        "card_number": None,
        "phone": None,
        "status": "active"
    }
    save_json(AGENTS_FILE, agents)
    
    # Инициализируем статистику рефералов
    ref_stats = load_json(REFERRAL_STATS_FILE)
    ref_stats[ref_code] = {
        "agent_id": user_id,
        "clicks": 0,
        "registrations": 0,
        "orders": 0,
        "paid_orders": 0,
        "total_revenue": 0
    }
    save_json(REFERRAL_STATS_FILE, ref_stats)
    
    return ref_code

def get_agent_by_ref_code(ref_code):
    agents = load_json(AGENTS_FILE)
    for agent_id, agent_data in agents.items():
        if agent_data.get("ref_code") == ref_code:
            return agent_id, agent_data
    return None, None

def update_agent_balance(agent_id, amount):
    agents = load_json(AGENTS_FILE)
    if str(agent_id) in agents:
        agents[str(agent_id)]["balance"] += amount
        agents[str(agent_id)]["total_earned"] += amount
        save_json(AGENTS_FILE, agents)

def generate_referral_link(ref_code):
    return f"https://t.me/tvoyaistoriyainsong_bot?start=ref_{ref_code}"

def generate_qr_code(data):
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    bio = BytesIO()
    img.save(bio, 'PNG')
    bio.seek(0)
    return bio

def add_user(user_id, username, first_name, referrer_code=None):
    users = load_json(USERS_FILE)
    if str(user_id) not in users:
        users[str(user_id)] = {
            "username": username,
            "first_name": first_name,
            "join_date": datetime.now().isoformat(),
            "orders_count": 0,
            "paid_count": 0,
            "total_spent": 0,
            "received_broadcast": False,
            "referrer_code": referrer_code  # Добавляем код реферера
        }
        save_json(USERS_FILE, users)
        
        # Обновляем статистику реферала
        if referrer_code:
            ref_stats = load_json(REFERRAL_STATS_FILE)
            if referrer_code in ref_stats:
                ref_stats[referrer_code]["registrations"] += 1
                save_json(REFERRAL_STATS_FILE, ref_stats)
                
                # Обновляем статистику агента
                agent_id, agent_data = get_agent_by_ref_code(referrer_code)
                if agent_id:
                    agents = load_json(AGENTS_FILE)
                    agents[agent_id]["total_referrals"] += 1
                    save_json(AGENTS_FILE, agents)

def add_order(user_id, task_id, prompt, mode, title, status="preview"):
    orders = load_json(ORDERS_FILE)
    order_data = {
        "user_id": user_id,
        "task_id": task_id,
        "prompt": prompt,
        "mode": mode,
        "title": title,
        "status": status,
        "created_date": datetime.now().isoformat(),
        "audio_url": None,
        "full_filename": None,
        "generation_in_progress": True
    }
    orders[task_id] = order_data
    save_json(ORDERS_FILE, orders)
    
    # Обновляем счетчики пользователя
    users = load_json(USERS_FILE)
    if str(user_id) in users:
        users[str(user_id)]["orders_count"] += 1
        save_json(USERS_FILE, users)

def update_order_paid(task_id, user_id, price_paid):
    orders = load_json(ORDERS_FILE)
    if task_id in orders:
        orders[task_id]["status"] = "paid"
        orders[task_id]["paid_date"] = datetime.now().isoformat()
        orders[task_id]["price_paid"] = price_paid / 100  # в рублях
        orders[task_id]["generation_in_progress"] = False
        save_json(ORDERS_FILE, orders)
        
        # Обновляем счетчики пользователя
        users = load_json(USERS_FILE)
        if str(user_id) in users:
            users[str(user_id)]["paid_count"] += 1
            users[str(user_id)]["total_spent"] += price_paid / 100
            
            # Проверяем реферера и начисляем комиссию
            referrer_code = users[str(user_id)].get("referrer_code")
            if referrer_code:
                # Обновляем статистику реферала
                ref_stats = load_json(REFERRAL_STATS_FILE)
                if referrer_code in ref_stats:
                    ref_stats[referrer_code]["paid_orders"] += 1
                    ref_stats[referrer_code]["total_revenue"] += price_paid / 100
                    save_json(REFERRAL_STATS_FILE, ref_stats)
                
                # Начисляем комиссию агенту
                agent_id, agent_data = get_agent_by_ref_code(referrer_code)
                if agent_id:
                    commission = (price_paid / 100) * AGENT_COMMISSION_PERCENT / 100
                    update_agent_balance(agent_id, commission)
                    
                    agents = load_json(AGENTS_FILE)
                    agents[agent_id]["paid_referrals"] += 1
                    save_json(AGENTS_FILE, agents)
                    
                    # Отправляем уведомление агенту
                    try:
                        asyncio.create_task(agent_bot.send_message(
                            int(agent_id),
                            f"💰 **Новое начисление!**\n\n"
                            f"Ваш реферал оплатил заказ.\n"
                            f"Сумма заказа: {price_paid / 100}₽\n"
                            f"Ваша комиссия: {commission:.2f}₽\n"
                            f"Текущий баланс: {agents[agent_id]['balance']:.2f}₽",
                            parse_mode="Markdown"
                        ))
                    except:
                        pass
            
            save_json(USERS_FILE, users)

def update_order_data(task_id, audio_url, title=None):
    orders = load_json(ORDERS_FILE)
    if task_id in orders:
        orders[task_id]["audio_url"] = audio_url
        if title:
            orders[task_id]["title"] = title
        orders[task_id]["generation_in_progress"] = False
        save_json(ORDERS_FILE, orders)

def can_user_use_promocode(user_id, code, task_id):
    users = load_json(USERS_FILE)
    if str(user_id) not in users or not users[str(user_id)].get("received_broadcast", False):
        return False, "Промокоды доступны только пользователям, получившим рассылку"
    
    promo_usage = load_json(PROMO_USAGE_FILE)
    for usage in promo_usage:
        if (usage["user_id"] == user_id and 
            usage["code"] == code and 
            usage["task_id"] == task_id):
            return False, "Вы уже использовали этот промокод для данной песни"
    
    return True, ""

def record_promocode_usage(user_id, code, task_id):
    promo_usage = load_json(PROMO_USAGE_FILE)
    promo_usage.append({
        "user_id": user_id,
        "code": code,
        "task_id": task_id,
        "used_date": datetime.now().isoformat()
    })
    save_json(PROMO_USAGE_FILE, promo_usage)

def delete_expired_promocode(code):
    promocodes = load_json(PROMOCODES_FILE)
    if code in promocodes:
        promo = promocodes[code]
        if promo["uses"] >= promo["max_uses"]:
            del promocodes[code]
            save_json(PROMOCODES_FILE, promocodes)
            logging.info(f"Промокод {code} удален - достигнут лимит использований")

def apply_promocode(code, price, user_id, task_id):
    promocodes = load_json(PROMOCODES_FILE)
    if code in promocodes:
        promo = promocodes[code]
        if promo["uses"] < promo["max_uses"]:
            can_use, error_msg = can_user_use_promocode(user_id, code, task_id)
            if not can_use:
                return price, 0, error_msg
            
            discount = promo["discount"]
            new_price = int(price * (100 - discount) / 100)
            
            if new_price < 10000:
                new_price = 10000
            
            promocodes[code]["uses"] += 1
            save_json(PROMOCODES_FILE, promocodes)
            
            record_promocode_usage(user_id, code, task_id)
            delete_expired_promocode(code)
            
            return new_price, discount, ""
    
    return price, 0, "Промокод недействителен или закончился"

def create_promocode(code, discount, max_uses):
    promocodes = load_json(PROMOCODES_FILE)
    promocodes[code] = {
        "discount": discount,
        "uses": 0,
        "max_uses": max_uses
    }
    save_json(PROMOCODES_FILE, promocodes)

def can_user_generate(user_id):
    orders = load_json(ORDERS_FILE)
    yesterday = datetime.now() - timedelta(hours=24)
    
    for order in orders.values():
        if (order["user_id"] == user_id and 
            datetime.fromisoformat(order["created_date"]) > yesterday):
            
            if (order["status"] == "preview" or 
                order.get("generation_in_progress", False)):
                return False, order
    
    return True, None

def get_user_active_orders(user_id):
    orders = load_json(ORDERS_FILE)
    yesterday = datetime.now() - timedelta(hours=24)
    
    active_orders = []
    for order in orders.values():
        if (order["user_id"] == user_id and 
            datetime.fromisoformat(order["created_date"]) > yesterday):
            
            if (order["status"] == "preview" or 
                order.get("generation_in_progress", False)):
                active_orders.append(order)
    
    return active_orders

def mark_user_received_broadcast(user_id):
    users = load_json(USERS_FILE)
    if str(user_id) in users:
        users[str(user_id)]["received_broadcast"] = True
        save_json(USERS_FILE, users)

# Проверка блокировки пользователя
async def check_user_blocked(message: types.Message):
    if is_blocked(message.from_user.id):
        await message.answer("❌ Вы заблокированы администратором.")
        return True
    return False

# Безопасная обработка callback
async def safe_callback_answer(callback):
    try:
        await callback.answer()
    except Exception as e:
        logging.warning(f"Callback answer failed: {e}")

# Создание клавиатур для основного бота
def get_main_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎵 Создать песню", callback_data="create_music")],
        [InlineKeyboardButton(text="📚 Мои заказы", callback_data="my_orders")],
        [InlineKeyboardButton(text="💡 Рекомендации", callback_data="recommendations")],
        [InlineKeyboardButton(text="💬 Поддержка", callback_data="support")],
        [InlineKeyboardButton(text="ℹ️ Помощь", callback_data="help")]
    ])
    return keyboard

def get_admin_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎵 Создать песню", callback_data="create_music")],
        [InlineKeyboardButton(text="📚 Мои заказы", callback_data="my_orders")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="👥 Пользователи", callback_data="admin_users")],
        [InlineKeyboardButton(text="🚫 Заблокировать", callback_data="admin_block")],
        [InlineKeyboardButton(text="✅ Разблокировать", callback_data="admin_unblock")],
        [InlineKeyboardButton(text="🎫 Промокоды", callback_data="admin_promo")],
        [InlineKeyboardButton(text="📢 Рассылка всем", callback_data="admin_broadcast_all")],
        [InlineKeyboardButton(text="📤 Рассылка выборочно", callback_data="admin_broadcast_select")],
        [InlineKeyboardButton(text="💬 Админ поддержка", callback_data="admin_support")],
        [InlineKeyboardButton(text="💡 Рекомендации", callback_data="recommendations")],
        [InlineKeyboardButton(text="ℹ️ Помощь", callback_data="help")]
    ])
    return keyboard

# Создание клавиатур для агентского бота
def get_agent_main_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 Личный кабинет", callback_data="agent_cabinet")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="agent_stats")],
        [InlineKeyboardButton(text="💸 Вывод средств", callback_data="agent_withdraw")],
        [InlineKeyboardButton(text="📄 Договор", callback_data="agent_contract")],
        [InlineKeyboardButton(text="❓ Помощь", callback_data="agent_help")]
    ])
    return keyboard

def get_agent_type_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 Физическое лицо", callback_data="agent_type_individual")],
        [InlineKeyboardButton(text="🏢 ИП", callback_data="agent_type_ip")],
        [InlineKeyboardButton(text="💼 Самозанятый", callback_data="agent_type_selfemployed")]
    ])
    return keyboard

def get_mode_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎨 Пользовательская", callback_data="mode_custom")],
        [InlineKeyboardButton(text="🤖 Автоматический", callback_data="mode_auto")]
    ])
    return keyboard

def get_voice_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👨 Мужской голос", callback_data="voice_male")],
        [InlineKeyboardButton(text="👩 Женский голос", callback_data="voice_female")]
    ])
    return keyboard

def get_share_keyboard(task_id):
    share_url = f"https://t.me/tvoyaistoriyainsong_bot?start=share_{task_id}"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Оплатить полную версию (500₽)", callback_data=f"pay_{task_id}")],
        [InlineKeyboardButton(text="🎫 Использовать промокод", callback_data=f"promo_{task_id}")],
        [InlineKeyboardButton(text="📤 Поделиться песней", url=f"https://t.me/share/url?url={share_url}&text=Послушайте мою новую песню!")],
        [InlineKeyboardButton(text="⭐ Оценить песню", callback_data=f"rate_{task_id}")]
    ])
    return keyboard

def get_rating_keyboard(task_id):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐", callback_data=f"rating_{task_id}_1"),
         InlineKeyboardButton(text="⭐⭐", callback_data=f"rating_{task_id}_2"),
         InlineKeyboardButton(text="⭐⭐⭐", callback_data=f"rating_{task_id}_3")],
        [InlineKeyboardButton(text="⭐⭐⭐⭐", callback_data=f"rating_{task_id}_4"),
         InlineKeyboardButton(text="⭐⭐⭐⭐⭐", callback_data=f"rating_{task_id}_5")]
    ])
    return keyboard

def get_payment_keyboard(task_id):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Оплатить (500₽)", callback_data=f"pay_{task_id}")],
        [InlineKeyboardButton(text="🎫 Использовать промокод", callback_data=f"promo_{task_id}")]
    ])
    return keyboard

def get_active_orders_keyboard(active_orders):
    keyboard_buttons = []
    for order in active_orders:
        if order.get("generation_in_progress", False):
            text = f"⏳ Генерация: {order['title'][:25]}..."
            callback_data = "generation_in_progress"
        else:
            text = f"💰 Оплатить: {order['title'][:25]}..."
            callback_data = f"pay_{order['task_id']}"
        
        keyboard_buttons.append([InlineKeyboardButton(text=text, callback_data=callback_data)])
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

def get_user_selection_keyboard(users_list, page=0, per_page=10):
    keyboard_buttons = []
    
    start_idx = page * per_page
    end_idx = start_idx + per_page
    current_users = users_list[start_idx:end_idx]
    
    for user_id, user_data in current_users:
        name = user_data.get("first_name") or user_data.get("username") or f"User {user_id}"
        keyboard_buttons.append([
            InlineKeyboardButton(
                text=f"📤 {name}",
                callback_data=f"select_user_{user_id}"
            )
        ])
    
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"user_page_{page-1}"))
    if end_idx < len(users_list):
        nav_buttons.append(InlineKeyboardButton(text="➡️ Далее", callback_data=f"user_page_{page+1}"))
    
    if nav_buttons:
        keyboard_buttons.append(nav_buttons)
    
    keyboard_buttons.append([InlineKeyboardButton(text="✅ Завершить выбор", callback_data="finish_user_selection")])
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

# API функции
async def generate_music(prompt: str, custom_mode: bool = False, callback_url: str = "https://example.com/callback"):
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {SUNO_API_KEY}"
    }
    
    payload = {
        "prompt": prompt,
        "customMode": custom_mode,
        "instrumental": False,
        "model": "V4_5",
        "callBackUrl": callback_url
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{SUNO_BASE_URL}/api/v1/generate", 
                                   headers=headers, json=payload, timeout=30) as response:
                if response.status == 200:
                    result = await response.json()
                    if result.get("code") == 200:
                        return result.get("data")
                return None
    except Exception as e:
        logging.error(f"Request Error: {e}")
        return None

async def get_task_info(task_id: str):
    headers = {"Authorization": f"Bearer {SUNO_API_KEY}"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{SUNO_BASE_URL}/api/v1/generate/record-info?taskId={task_id}", 
                                  headers=headers, timeout=30) as response:
                if response.status == 200:
                    result = await response.json()
                    if result.get("code") == 200:
                        return result.get("data")
                return None
    except Exception as e:
        logging.error(f"Task info error: {e}")
        return None

async def download_audio(url: str, filename: str):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=120) as response:
                if response.status == 200:
                    os.makedirs(os.path.dirname(filename), exist_ok=True)
                    async with aiofiles.open(filename, 'wb') as f:
                        async for chunk in response.content.iter_chunked(8192):
                            await f.write(chunk)
                    return True
        return False
    except Exception as e:
        logging.error(f"Download error: {e}")
        return False

def trim_audio(input_file: str, output_file: str, duration: int = 30):
    try:
        if not os.path.exists(input_file):
            return False
        audio = AudioSegment.from_file(input_file)
        trimmed = audio[:duration * 1000]
        trimmed.export(output_file, format="mp3")
        return os.path.exists(output_file)
    except Exception as e:
        logging.error(f"Trim error: {e}")
        return False

# Генерация статистики
def generate_stats_chart():
    users = load_json(USERS_FILE)
    orders = load_json(ORDERS_FILE)
    
    fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(15, 10))
    
    # 1. Топ пользователей по заказам
    user_orders = [(data["first_name"] or data["username"] or f"User {uid}", data["orders_count"]) 
                   for uid, data in users.items() if data["orders_count"] > 0]
    user_orders.sort(key=lambda x: x[1], reverse=True)
    
    if user_orders:
        names, counts = zip(*user_orders[:10])
        ax1.bar(range(len(names)), counts)
        ax1.set_title('Топ пользователей по заказам')
        ax1.set_xticks(range(len(names)))
        ax1.set_xticklabels(names, rotation=45, ha='right')
    else:
        ax1.text(0.5, 0.5, 'Нет данных', ha='center', va='center')
        ax1.set_title('Топ пользователей по заказам')
    
    # 2. Топ пользователей по оплатам
    user_paid = [(data["first_name"] or data["username"] or f"User {uid}", data["paid_count"]) 
                 for uid, data in users.items() if data["paid_count"] > 0]
    user_paid.sort(key=lambda x: x[1], reverse=True)
    
    if user_paid:
        names, counts = zip(*user_paid[:10])
        ax2.bar(range(len(names)), counts, color='green')
        ax2.set_title('Топ пользователей по оплатам')
        ax2.set_xticks(range(len(names)))
        ax2.set_xticklabels(names, rotation=45, ha='right')
    else:
        ax2.text(0.5, 0.5, 'Нет данных', ha='center', va='center')
        ax2.set_title('Топ пользователей по оплатам')
    
    # 3. Доходы по дням
    daily_revenue = {}
    for order in orders.values():
        if order["status"] == "paid" and "paid_date" in order:
            date = order["paid_date"][:10]
            price = order.get("price_paid", FULL_VERSION_PRICE / 100)
            daily_revenue[date] = daily_revenue.get(date, 0) + price
    
    if daily_revenue:
        dates = sorted(daily_revenue.keys())
        revenues = [daily_revenue[date] for date in dates]
        ax3.plot(dates, revenues, marker='o')
        ax3.set_title('Доходы по дням')
        ax3.tick_params(axis='x', rotation=45)
    else:
        ax3.text(0.5, 0.5, 'Нет данных', ha='center', va='center')
        ax3.set_title('Доходы по дням')
    
    # 4. Общая статистика
    total_users = len(users)
    total_orders = sum(data["orders_count"] for data in users.values())
    total_paid = sum(data["paid_count"] for data in users.values())
    total_revenue = sum(data["total_spent"] for data in users.values())
    
    stats_text = f"""Общая статистика:
Пользователей: {total_users}
Заказов: {total_orders}
Оплачено: {total_paid}
Доход: {total_revenue}₽
Конверсия: {(total_paid/total_orders*100) if total_orders > 0 else 0:.1f}%"""
    
    ax4.text(0.1, 0.5, stats_text, fontsize=12, verticalalignment='center')
    ax4.set_xlim(0, 1)
    ax4.set_ylim(0, 1)
    ax4.axis('off')
    ax4.set_title('Общая статистика')
    
    plt.tight_layout()
    chart_path = f"{DATA_DIR}/stats_chart.png"
    plt.savefig(chart_path, dpi=300, bbox_inches='tight')
    plt.close()
    
    return chart_path

# Вспомогательные функции для отправки сообщений
async def safe_send_message(bot, chat_id, text, **kwargs):
    try:
        return await bot.send_message(chat_id, text, **kwargs)
    except Exception as e:
        logging.error(f"Error sending message: {e}")
        return None

async def safe_edit_message(message, text, **kwargs):
    try:
        return await message.edit_text(text, **kwargs)
    except Exception as e:
        logging.error(f"Error editing message: {e}")
        return await safe_send_message(message.bot, message.chat.id, text, **kwargs)

# === ОБРАБОТЧИКИ ДЛЯ ОСНОВНОГО БОТА ===

# Основные команды
@main_dp.message(Command("start"))
async def cmd_start(message: types.Message):
    if await check_user_blocked(message):
        return
    
    logging.info(f"USER_ID: {message.from_user.id}, USERNAME: {message.from_user.username}, NAME: {message.from_user.first_name}")
    
    # Проверяем реферальный код
    referrer_code = None
    if message.text and len(message.text.split()) > 1:
        param = message.text.split()[1]
        if param.startswith("ref_"):
            referrer_code = param.replace("ref_", "")
            
            # Обновляем статистику кликов
            ref_stats = load_json(REFERRAL_STATS_FILE)
            if referrer_code in ref_stats:
                ref_stats[referrer_code]["clicks"] += 1
                save_json(REFERRAL_STATS_FILE, ref_stats)
            
            # Получаем информацию об агенте
            agent_id, agent_data = get_agent_by_ref_code(referrer_code)
            if agent_data:
                await message.answer(
                    f"🎉 Добро пожаловать!\n\n"
                    f"Вы приглашены агентом: {agent_data['first_name']}\n"
                    f"Создавайте уникальные песни с помощью ИИ!"
                )
        elif param.startswith("share_"):
            task_id = param.replace("share_", "")
            orders = load_json(ORDERS_FILE)
            if task_id in orders:
                order = orders[task_id]
                keyboard = get_admin_keyboard() if is_admin(message.from_user.id) else get_main_keyboard()
                await message.answer(
                    f"🎵 *{order['title']}*\n\n"
                    f"📝 Создано: {order['created_date'][:10]}\n"
                    f"🎨 Режим: {order['mode']}\n\n"
                    f"Создайте свою песню с помощью нашего бота!",
                    parse_mode="Markdown",
                    reply_markup=keyboard
                )
                return
    
    add_user(message.from_user.id, message.from_user.username, message.from_user.first_name, referrer_code)
    
    keyboard = get_admin_keyboard() if is_admin(message.from_user.id) else get_main_keyboard()
    
    welcome_text = "🎵 Добро пожаловать в Music Generator Bot!\n\n"
    welcome_text += "Создавайте уникальные песни с помощью ИИ\n\n"
    welcome_text += "🎁 Используйте промокод **WELCOME** для скидки 10%!"
    
    await message.answer(welcome_text, parse_mode="Markdown", reply_markup=keyboard)

# Команда для создания промокодов
@main_dp.message(Command("createpromo"))
async def cmd_create_promo(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет доступа к этой команде.")
        return
    
    await message.answer(
        "🎫 **Создание промокода**\n\n"
        "Введите процент скидки (от 0 до 100):",
        parse_mode="Markdown"
    )
    await state.set_state(AdminPanel.waiting_for_promocode_discount)

@main_dp.message(AdminPanel.waiting_for_promocode_discount)
async def process_promo_discount(message: types.Message, state: FSMContext):
    try:
        discount = int(message.text.strip())
        if discount < 0 or discount > 100:
            await message.answer("❌ Процент скидки должен быть от 0 до 100. Попробуйте еще раз:")
            return
        
        await state.update_data(discount=discount)
        await message.answer(
            f"✅ Скидка: {discount}%\n\n"
            f"Теперь введите название промокода (например, HELLO):",
            parse_mode="Markdown"
        )
        await state.set_state(AdminPanel.waiting_for_promocode_name)
        
    except ValueError:
        await message.answer("❌ Введите число от 0 до 100:")

@main_dp.message(AdminPanel.waiting_for_promocode_name)
async def process_promo_name(message: types.Message, state: FSMContext):
    promo_name = message.text.strip().upper()
    
    if len(promo_name) < 2 or len(promo_name) > 20:
        await message.answer("❌ Название промокода должно быть от 2 до 20 символов. Попробуйте еще раз:")
        return
    
    promocodes = load_json(PROMOCODES_FILE)
    if promo_name in promocodes:
        await message.answer(f"❌ Промокод {promo_name} уже существует. Введите другое название:")
        return
    
    await state.update_data(promo_name=promo_name)
    await message.answer(
        f"✅ Название: {promo_name}\n\n"
        f"Теперь введите количество использований (максимум 100000):",
        parse_mode="Markdown"
    )
    await state.set_state(AdminPanel.waiting_for_promocode_uses)

@main_dp.message(AdminPanel.waiting_for_promocode_uses)
async def process_promo_uses(message: types.Message, state: FSMContext):
    try:
        max_uses = int(message.text.strip())
        if max_uses < 1 or max_uses > 100000:
            await message.answer("❌ Количество использований должно быть от 1 до 100000. Попробуйте еще раз:")
            return
        
        data = await state.get_data()
        discount = data["discount"]
        promo_name = data["promo_name"]
        
        create_promocode(promo_name, discount, max_uses)
        
        await message.answer(
            f"✅ **Промокод создан!**\n\n"
            f"📝 Название: `{promo_name}`\n"
            f"💰 Скидка: {discount}%\n"
            f"📊 Использований: 0/{max_uses}\n\n"
            f"Промокод готов к использованию пользователями.",
            parse_mode="Markdown",
            reply_markup=get_admin_keyboard()
        )
        await state.clear()
        
    except ValueError:
        await message.answer("❌ Введите число от 1 до 100000:")

# РАССЫЛКА ВСЕМ ПОЛЬЗОВАТЕЛЯМ
@main_dp.callback_query(F.data == "admin_broadcast_all")
async def admin_broadcast_all(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await safe_callback_answer(callback)
        await callback.message.answer("❌ Нет доступа")
        return
    
    users = load_json(USERS_FILE)
    total_users = len(users)
    
    await safe_edit_message(
        callback.message,
        f"📢 **Создание рассылки для всех пользователей**\n\n"
        f"📊 Всего пользователей в боте: {total_users}\n\n"
        f"Напишите текст сообщения для рассылки всем пользователям:\n\n"
        f"💡 *Поддерживается Markdown разметка*",
        parse_mode="Markdown"
    )
    await state.update_data(broadcast_type="all")
    await state.set_state(AdminPanel.waiting_for_broadcast_text)
    await safe_callback_answer(callback)

# ВЫБОРОЧНАЯ РАССЫЛКА
@main_dp.callback_query(F.data == "admin_broadcast_select")
async def admin_broadcast_select(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await safe_callback_answer(callback)
        await callback.message.answer("❌ Нет доступа")
        return
    
    users = load_json(USERS_FILE)
    users_list = list(users.items())
    
    await safe_edit_message(
        callback.message,
        f"📤 **Выборочная рассылка**\n\n"
        f"📊 Всего пользователей: {len(users_list)}\n\n"
        f"Выберите пользователей для отправки сообщения:",
        parse_mode="Markdown",
        reply_markup=get_user_selection_keyboard(users_list, 0)
    )
    
    await state.update_data(
        broadcast_type="select",
        users_list=users_list,
        selected_users=[],
        current_page=0
    )
    await state.set_state(AdminPanel.waiting_for_broadcast_selection)
    await safe_callback_answer(callback)

# Обработка выбора пользователей
@main_dp.callback_query(F.data.startswith("select_user_"))
async def select_user_for_broadcast(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await safe_callback_answer(callback)
        return
    
    user_id = int(callback.data.split("_", 2)[2])
    data = await state.get_data()
    selected_users = data.get("selected_users", [])
    
    if user_id not in selected_users:
        selected_users.append(user_id)
        await state.update_data(selected_users=selected_users)
        
        users = load_json(USERS_FILE)
        user_name = users[str(user_id)].get("first_name") or users[str(user_id)].get("username") or f"User {user_id}"
        
        await safe_send_message(
            main_bot,
            callback.message.chat.id,
            f"✅ Пользователь *{user_name}* добавлен в список рассылки\n"
            f"📊 Выбрано пользователей: {len(selected_users)}",
            parse_mode="Markdown"
        )
    
    await safe_callback_answer(callback)

@main_dp.callback_query(F.data.startswith("user_page_"))
async def change_user_page(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await safe_callback_answer(callback)
        return
    
    page = int(callback.data.split("_", 2)[2])
    data = await state.get_data()
    users_list = data.get("users_list", [])
    selected_count = len(data.get("selected_users", []))
    
    await safe_edit_message(
        callback.message,
        f"📤 **Выборочная рассылка**\n\n"
        f"📊 Всего пользователей: {len(users_list)}\n"
        f"✅ Выбрано: {selected_count}\n\n"
        f"Выберите пользователей для отправки сообщения:",
        parse_mode="Markdown",
        reply_markup=get_user_selection_keyboard(users_list, page)
    )
    
    await state.update_data(current_page=page)
    await safe_callback_answer(callback)

@main_dp.callback_query(F.data == "finish_user_selection")
async def finish_user_selection(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await safe_callback_answer(callback)
        return
    
    data = await state.get_data()
    selected_users = data.get("selected_users", [])
    
    if not selected_users:
        await safe_edit_message(
            callback.message,
            "❌ Не выбран ни один пользователь для рассылки.",
            reply_markup=get_admin_keyboard()
        )
        await state.clear()
        await safe_callback_answer(callback)
        return
    
    await safe_edit_message(
        callback.message,
        f"📤 **Выборочная рассылка**\n\n"
        f"✅ Выбрано пользователей: {len(selected_users)}\n\n"
        f"Напишите текст сообщения для выбранных пользователей:\n\n"
        f"💡 *Поддерживается Markdown разметка*",
        parse_mode="Markdown"
    )
    
    await state.set_state(AdminPanel.waiting_for_broadcast_text)
    await safe_callback_answer(callback)

# ОБРАБОТКА ТЕКСТА РАССЫЛКИ
@main_dp.message(AdminPanel.waiting_for_broadcast_text)
async def process_broadcast_text(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет доступа")
        await state.clear()
        return
    
    broadcast_text = message.text
    data = await state.get_data()
    broadcast_type = data.get("broadcast_type", "all")
    
    if broadcast_type == "all":
        users = load_json(USERS_FILE)
        target_users = list(users.keys())
    else:
        target_users = [str(uid) for uid in data.get("selected_users", [])]
    
    if not target_users:
        await message.answer("❌ Нет пользователей для рассылки", reply_markup=get_admin_keyboard())
        await state.clear()
        return
    
    status_message = await message.answer(
        f"📢 **Начинаю рассылку...**\n\n"
        f"📊 Пользователей для рассылки: {len(target_users)}\n"
        f"📤 Отправлено: 0\n"
        f"❌ Ошибок: 0",
        parse_mode="Markdown"
    )
    
    sent_count = 0
    error_count = 0
    
    for i, user_id in enumerate(target_users):
        try:
            if int(user_id) == message.from_user.id:
                continue
            
            await main_bot.send_message(int(user_id), broadcast_text, parse_mode="Markdown")
            sent_count += 1
            
            mark_user_received_broadcast(int(user_id))
            
            if (i + 1) % 10 == 0:
                await status_message.edit_text(
                    f"📢 **Рассылка в процессе...**\n\n"
                    f"📊 Пользователей для рассылки: {len(target_users)}\n"
                    f"📤 Отправлено: {sent_count}\n"
                    f"❌ Ошибок: {error_count}\n"
                    f"📈 Прогресс: {((i + 1) / len(target_users) * 100):.1f}%",
                    parse_mode="Markdown"
                )
            
            await asyncio.sleep(0.05)
            
        except Exception as e:
            error_count += 1
            logging.error(f"Ошибка при рассылке пользователю {user_id}: {e}")
    
    await status_message.edit_text(
        f"✅ **Рассылка завершена!**\n\n"
        f"📊 Всего пользователей: {len(target_users)}\n"
        f"📤 Успешно отправлено: {sent_count}\n"
        f"❌ Ошибок: {error_count}\n"
        f"📈 Успешность: {(sent_count / len(target_users) * 100):.1f}%\n\n"
        f"🎫 Пользователи получили доступ к промокодам",
        parse_mode="Markdown"
    )
    
    await message.answer(
        "📢 Рассылка завершена. Возвращайтесь к админ-панели:",
        reply_markup=get_admin_keyboard()
    )
    
    await state.clear()

# Callback обработчики
@main_dp.callback_query(F.data == "create_music")
async def create_music_callback(callback: types.CallbackQuery, state: FSMContext):
    if is_blocked(callback.from_user.id):
        await safe_callback_answer(callback)
        await callback.message.answer("❌ Вы заблокированы")
        return
    
    can_generate, active_order = can_user_generate(callback.from_user.id)
    
    if not can_generate:
        active_orders = get_user_active_orders(callback.from_user.id)
        
        text = "⏳ **Ограничение генерации**\n\n"
        
        generating_orders = [o for o in active_orders if o.get("generation_in_progress", False)]
        unpaid_orders = [o for o in active_orders if o["status"] == "preview" and not o.get("generation_in_progress", False)]
        
        if generating_orders:
            text += "🔄 У вас уже генерируется песня. Дождитесь завершения:\n\n"
            for order in generating_orders:
                date = order["created_date"][:16].replace("T", " ")
                text += f"⏳ *{order['title']}*\n"
                text += f"📅 Начато: {date}\n\n"
            text += "После завершения генерации вы сможете её оплатить или создать новую."
        
        if unpaid_orders:
            text += "💰 У вас есть неоплаченные песни. Оплатите одну из них, чтобы создать новую:\n\n"
            for order in unpaid_orders:
                date = order["created_date"][:16].replace("T", " ")
                text += f"🎵 *{order['title']}*\n"
                text += f"📅 Создано: {date}\n\n"
            text += "После оплаты вы сможете создать следующую песню!"
        
        await safe_edit_message(
            callback.message,
            text,
            parse_mode="Markdown",
            reply_markup=get_active_orders_keyboard(active_orders)
        )
        await safe_callback_answer(callback)
        return
    
    await safe_edit_message(
        callback.message,
        "🎼 Выберите режим создания песни:\n\n"
        "🎨 **Пользовательская** - Вы сами пишете текст песни (до 1000 символов)\n"
        "🤖 **Автоматический** - ИИ создаст текст по вашей идее (до 191 символа)",
        parse_mode="Markdown",
        reply_markup=get_mode_keyboard()
    )
    await state.set_state(MusicGeneration.waiting_for_mode)
    await safe_callback_answer(callback)

@main_dp.callback_query(F.data == "generation_in_progress")
async def generation_in_progress_callback(callback: types.CallbackQuery):
    await callback.answer("⏳ Генерация уже в процессе. Пожалуйста, подождите.", show_alert=True)

@main_dp.callback_query(F.data == "my_orders")
async def my_orders_callback(callback: types.CallbackQuery):
    orders = load_json(ORDERS_FILE)
    user_orders = [order for order in orders.values() if order["user_id"] == callback.from_user.id]
    
    if not user_orders:
        keyboard = get_admin_keyboard() if is_admin(callback.from_user.id) else get_main_keyboard()
        await safe_edit_message(
            callback.message,
            "📚 У вас пока нет заказов.\n\nСоздайте свою первую песню!",
            reply_markup=keyboard
        )
        await safe_callback_answer(callback)
        return
    
    user_orders.sort(key=lambda x: x["created_date"], reverse=True)
    
    text = "📚 **Ваши заказы:**\n\n"
    for i, order in enumerate(user_orders[:10], 1):
        if order.get("generation_in_progress", False):
            status_emoji = "⏳"
            status_text = "Генерируется"
        elif order["status"] == "paid":
            status_emoji = "✅"
            status_text = "Оплачено"
        else:
            status_emoji = "⏳"
            status_text = "Ожидает оплаты"
        
        date = order["created_date"][:10]
        text += f"{i}. {status_emoji} *{order['title']}*\n"
        text += f"   📅 {date} | 🎨 {order['mode']}\n"
        text += f"   📊 Статус: {status_text}\n\n"
    
    if len(user_orders) > 10:
        text += f"... и еще {len(user_orders) - 10} заказов"
    
    keyboard = get_admin_keyboard() if is_admin(callback.from_user.id) else get_main_keyboard()
    await safe_edit_message(callback.message, text, parse_mode="Markdown", reply_markup=keyboard)
    await safe_callback_answer(callback)

@main_dp.callback_query(F.data == "recommendations")
async def recommendations_callback(callback: types.CallbackQuery):
    recommendations = [
        "🎵 **Популярные стили:**\nJazz, Rock, Electronic, Classical, Pop, Hip-Hop",
        "📝 **Примеры идей для песен:**\nО любви и расставании, мотивационные треки, релаксирующая музыка, праздничные мелодии",
        "💡 **Советы по описанию:**\n• Описывайте настроение песни\n• Указывайте желаемые инструменты\n• Добавляйте темп (быстро/медленно)",
        "🎤 **Выбор голоса:**\n• Мужской голос подходит для рока, рэпа\n• Женский голос - для баллад, попа"
    ]
    
    text = "💡 **Рекомендации по созданию песен:**\n\n" + "\n\n".join(recommendations)
    keyboard = get_admin_keyboard() if is_admin(callback.from_user.id) else get_main_keyboard()
    await safe_edit_message(callback.message, text, parse_mode="Markdown", reply_markup=keyboard)
    await safe_callback_answer(callback)

@main_dp.callback_query(F.data == "support")
async def support_callback(callback: types.CallbackQuery, state: FSMContext):
    await safe_edit_message(
        callback.message,
        "💬 **Поддержка**\n\n"
        "Опишите вашу проблему или вопрос, и мы ответим в ближайшее время:",
        parse_mode="Markdown"
    )
    await state.set_state(Support.waiting_for_support_message)
    await safe_callback_answer(callback)

@main_dp.callback_query(F.data == "help")
async def help_callback(callback: types.CallbackQuery):
    text = """ℹ️ **Помощь по использованию бота**

🎵 **Создание песен:**
1. Нажмите "Создать песню"
2. Выберите режим (пользовательский/автоматический)
3. Выберите голос (мужской/женский)
4. Введите текст песни или идею
5. Получите превью (30 сек)
6. Оплатите полную версию

📝 **Режимы:**
🎨 **Пользовательский** - вы пишете текст (до 1000 символов) + стиль
🤖 **Автоматический** - опишите идею песни (до 191 символа для мужского голоса, 188 для женского)

💰 **Система оплаты:**
• Стоимость: 500₽
• Можно создать только 1 неоплаченную песню
• Нельзя генерировать во время активной генерации
• После оплаты - доступ к созданию новой
• Доступны промокоды со скидками

🎫 **Промокоды:**
• Доступны только получившим рассылку
• Каждый промокод - 1 раз на песню
• Нажмите "Использовать промокод" при оплате

🤖 **Технология:** ИИ генерация"""

    keyboard = get_admin_keyboard() if is_admin(callback.from_user.id) else get_main_keyboard()
    await safe_edit_message(callback.message, text, parse_mode="Markdown", reply_markup=keyboard)
    await safe_callback_answer(callback)

# Обработка режимов создания музыки
@main_dp.callback_query(F.data.startswith("mode_"))
async def process_mode_selection(callback: types.CallbackQuery, state: FSMContext):
    mode = callback.data.split("_", 1)[1]
    await state.update_data(mode=mode)
    
    await safe_edit_message(
        callback.message,
        "🎤 **Выберите голос для песни:**\n\n"
        "👨 **Мужской голос** - подходит для рока, рэпа, драйвовых песен\n"
        "👩 **Женский голос** - подходит для баллад, попа, лирических песен",
        parse_mode="Markdown",
        reply_markup=get_voice_keyboard()
    )
    await state.set_state(MusicGeneration.waiting_for_voice)
    await safe_callback_answer(callback)

@main_dp.callback_query(F.data.startswith("voice_"))
async def process_voice_selection(callback: types.CallbackQuery, state: FSMContext):
    voice = callback.data.split("_", 1)[1]
    data = await state.get_data()
    mode = data.get("mode")
    
    await state.update_data(voice=voice)
    
    if mode == "custom":
        await safe_edit_message(
            callback.message,
            "🎨 **Пользовательский режим**\n\n"
            "Напишите текст для вашей песни (максимум 1000 символов):\n\n"
            "Пример:\n"
            "*[Verse 1]\n"
            "В тишине ночной\n"
            "Звезды танцуют в свете\n"
            "[Chorus]\n"
            "Мы поднимемся выше всех*",
            parse_mode="Markdown"
        )
        await state.set_state(MusicGeneration.waiting_for_custom_prompt)
        
    elif mode == "auto":
        max_chars = 191 if voice == "male" else 188
        await safe_edit_message(
            callback.message,
            f"🤖 **Автоматический режим**\n\n"
            f"Опишите идею вашей песни (максимум {max_chars} символов):\n\n"
            f"Примеры:\n"
            f"• *Песня о первой любви в школе*\n"
            f"• *Мотивационный трек о достижении целей*\n"
            f"• *Грустная баллада о расставании*\n"
            f"• *Веселая песня о дружбе*",
            parse_mode="Markdown"
        )
        await state.set_state(MusicGeneration.waiting_for_auto_prompt)
    
    await safe_callback_answer(callback)

# Обработка промптов
@main_dp.message(MusicGeneration.waiting_for_custom_prompt)
async def process_custom_prompt(message: types.Message, state: FSMContext):
    if await check_user_blocked(message):
        await state.clear()
        return
        
    prompt = message.text.strip()
    
    if len(prompt) > 1000:
        await message.answer("❌ Текст слишком длинный! Максимум 1000 символов.")
        return
    
    if len(prompt) < 10:
        await message.answer("❌ Текст слишком короткий! Напишите хотя бы 10 символов.")
        return
    
    await state.update_data(prompt=prompt)
    await message.answer(
        "🎨 **Укажите стиль песни** (максимум 1000 символов):\n\n"
        "Примеры:\n"
        "• *Rock, energetic, electric guitar*\n"
        "• *Pop ballad, emotional, piano*\n"
        "• *Jazz, smooth, saxophone*\n"
        "• *Electronic, upbeat, synthesizer*",
        parse_mode="Markdown"
    )
    await state.set_state(MusicGeneration.waiting_for_custom_style)

@main_dp.message(MusicGeneration.waiting_for_custom_style)
async def process_custom_style(message: types.Message, state: FSMContext):
    if await check_user_blocked(message):
        await state.clear()
        return
        
    style = message.text.strip()
    
    if len(style) > 1000:
        await message.answer("❌ Описание стиля слишком длинное! Максимум 1000 символов.")
        return
    
    if len(style) < 3:
        await message.answer("❌ Описание стиля слишком короткое! Напишите хотя бы 3 символа.")
        return
    
    data = await state.get_data()
    prompt = data["prompt"]
    voice = data["voice"]
    
    voice_prefix = "Man Vocal, " if voice == "male" else "Female Vocal, "
    final_prompt = voice_prefix + style + "\n\n" + prompt
    
    await generate_music_task(message, state, final_prompt, custom_mode=True)

@main_dp.message(MusicGeneration.waiting_for_auto_prompt)
async def process_auto_prompt(message: types.Message, state: FSMContext):
    if await check_user_blocked(message):
        await state.clear()
        return
        
    data = await state.get_data()
    voice = data["voice"]
    max_chars = 191 if voice == "male" else 188
    
    prompt = message.text.strip()
    
    if len(prompt) > max_chars:
        await message.answer(f"❌ Описание слишком длинное! Максимум {max_chars} символов.")
        return
    
    if len(prompt) < 5:
        await message.answer("❌ Описание слишком короткое! Напишите хотя бы 5 символов.")
        return
    
    voice_prefix = "Man Vocal, " if voice == "male" else "Female Vocal, "
    final_prompt = voice_prefix + prompt
    
    await generate_music_task(message, state, final_prompt, custom_mode=False)

# Основная функция генерации музыки
async def generate_music_task(message: types.Message, state: FSMContext, prompt: str, custom_mode: bool):
    data = await state.get_data()
    voice = data.get("voice")
    mode_text = "пользовательском" if custom_mode else "автоматическом"
    voice_text = "мужским" if voice == "male" else "женским"
    
    status_message = await message.answer(f"🎵 Создаю песню в {mode_text} режиме с {voice_text} голосом... Это может занять несколько минут.")
    
    try:
        task_data = await generate_music(prompt, custom_mode)
        
        if not task_data or not task_data.get("taskId"):
            await status_message.edit_text("❌ Ошибка при создании песни. Попробуйте еще раз.")
            await state.clear()
            return
        
        task_id = task_data["taskId"]
        
        add_order(message.from_user.id, task_id, prompt, 
                 "Пользовательский" if custom_mode else "Автоматический", 
                 "Генерируется...")
        
        await status_message.edit_text("⏳ Песня генерируется... Ожидайте результат.")
        
        max_attempts = 40
        attempt = 0
        
        while attempt < max_attempts:
            await asyncio.sleep(15)
            
            task_info = await get_task_info(task_id)
            
            if task_info is None:
                attempt += 1
                continue
            
            status = task_info.get("status")
            
            if status in ["SUCCESS", "FIRST_SUCCESS"]:
                response_data = task_info.get("response", {})
                data_list = response_data.get("sunoData", [])
                
                if data_list:
                    for track in data_list:
                        audio_url = track.get("audioUrl")
                        if audio_url:
                            title = track.get("title", "Generated Music")
                            duration = track.get("duration", 0)
                            
                            temp_full_filename = f"temp/temp_full_{task_id}.mp3"
                            preview_filename = f"temp/preview_{task_id}.mp3"
                            
                            if await download_audio(audio_url, temp_full_filename):
                                update_order_data(task_id, audio_url, title)
                                
                                if trim_audio(temp_full_filename, preview_filename, 30):
                                    try:
                                        audio_file = FSInputFile(preview_filename)
                                        
                                        caption = f"🎵 *{title}*\n\n📝 Режим: {'Пользовательский' if custom_mode else 'Автоматический'}\n🎤 Голос: {'Мужской' if voice == 'male' else 'Женский'}\n🤖 ИИ генерация\n⏱ Превью (30 сек)\n🎼 Полная длительность: {duration:.1f} сек"
                                        
                                        await main_bot.send_audio(
                                            chat_id=message.chat.id,
                                            audio=audio_file,
                                            title=f"{title} (Preview)",
                                            caption=caption,
                                            parse_mode="Markdown",
                                            reply_markup=get_share_keyboard(task_id)
                                        )
                                        
                                        await status_message.delete()
                                        
                                        try:
                                            os.remove(preview_filename)
                                            os.remove(temp_full_filename)
                                            logging.info(f"Временные файлы для {task_id} удалены")
                                        except Exception as e:
                                            logging.error(f"Ошибка при удалении временных файлов: {e}")
                                        
                                        await state.clear()
                                        return
                                        
                                    except Exception as e:
                                        logging.error(f"Ошибка отправки аудио: {e}")
                                        await status_message.edit_text("❌ Ошибка при отправке аудио.")
                                        
                                        try:
                                            os.remove(preview_filename)
                                            os.remove(temp_full_filename)
                                        except:
                                            pass
                            break
                
            elif status in ["CREATE_TASK_FAILED", "GENERATE_AUDIO_FAILED", "SENSITIVE_WORD_ERROR"]:
                orders = load_json(ORDERS_FILE)
                if task_id in orders:
                    orders[task_id]["generation_in_progress"] = False
                    save_json(ORDERS_FILE, orders)
                
                await status_message.edit_text(f"❌ Ошибка генерации: {status}. Попробуйте изменить текст.")
                await state.clear()
                return
            
            attempt += 1
            
            if attempt % 2 == 0:
                await status_message.edit_text(f"⏳ Генерация песни... {attempt * 15} сек")
        
        orders = load_json(ORDERS_FILE)
        if task_id in orders:
            orders[task_id]["generation_in_progress"] = False
            save_json(ORDERS_FILE, orders)
        
        await status_message.edit_text("⏰ Превышено время ожидания. Попробуйте еще раз позже.")
        
    except Exception as e:
        logging.error(f"Критическая ошибка: {e}")
        orders = load_json(ORDERS_FILE)
        if task_id in orders:
            orders[task_id]["generation_in_progress"] = False
            save_json(ORDERS_FILE, orders)
        
        await status_message.edit_text("❌ Произошла ошибка. Попробуйте позже.")
    
    await state.clear()

# Обработка поддержки
@main_dp.message(Support.waiting_for_support_message)
async def process_support_message(message: types.Message, state: FSMContext):
    support_text = f"💬 **Новое обращение в поддержку**\n\n"
    support_text += f"👤 Пользователь: {message.from_user.first_name or 'Неизвестно'} (@{message.from_user.username or 'нет'})\n"
    support_text += f"🆔 ID: `{message.from_user.id}`\n\n"
    support_text += f"📝 Сообщение:\n{message.text}"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Ответить", callback_data=f"support_reply_{message.from_user.id}")]
    ])
    
    for admin_id in [OWNER_ID, ADMIN_ID]:
        try:
            await main_bot.send_message(admin_id, support_text, parse_mode="Markdown", reply_markup=keyboard)
        except:
            pass
    
    keyboard = get_admin_keyboard() if is_admin(message.from_user.id) else get_main_keyboard()
    await message.answer(
        "✅ Ваше обращение отправлено в поддержку!\n\n"
        "Мы ответим в ближайшее время.",
        reply_markup=keyboard
    )
    await state.clear()

# Обработка оценок
@main_dp.callback_query(F.data.startswith("rate_"))
async def rate_callback(callback: types.CallbackQuery):
    task_id = callback.data.split("_", 1)[1]
    
    await safe_edit_message(
        callback.message,
        "⭐ **Оцените песню**\n\n"
        "Как вам понравилась созданная песня?",
        parse_mode="Markdown",
        reply_markup=get_rating_keyboard(task_id)
    )
    await safe_callback_answer(callback)

@main_dp.callback_query(F.data.startswith("rating_"))
async def rating_callback(callback: types.CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    task_id = parts[1]
    rating = int(parts[2])
    
    feedback = load_json(FEEDBACK_FILE)
    feedback.append({
        "user_id": callback.from_user.id,
        "task_id": task_id,
        "rating": rating,
        "date": datetime.now().isoformat()
    })
    save_json(FEEDBACK_FILE, feedback)
    
    await safe_edit_message(
        callback.message,
        f"⭐ Спасибо за оценку: {rating}/5!\n\n"
        f"Хотите оставить комментарий к песне?",
        parse_mode="Markdown"
    )
    
    await state.update_data(task_id=task_id, rating=rating)
    await state.set_state(MusicGeneration.waiting_for_feedback)
    await safe_callback_answer(callback)

@main_dp.message(MusicGeneration.waiting_for_feedback)
async def process_feedback(message: types.Message, state: FSMContext):
    data = await state.get_data()
    task_id = data.get("task_id")
    rating = data.get("rating")
    
    feedback = load_json(FEEDBACK_FILE)
    for item in feedback:
        if item["task_id"] == task_id and item["user_id"] == message.from_user.id:
            item["comment"] = message.text
            break
    save_json(FEEDBACK_FILE, feedback)
    
    keyboard = get_admin_keyboard() if is_admin(message.from_user.id) else get_main_keyboard()
    await message.answer(
        "✅ Спасибо за отзыв! Ваше мнение поможет нам улучшить сервис.",
        reply_markup=keyboard
    )
    await state.clear()

# Обработка промокодов
@main_dp.callback_query(F.data.startswith("promo_"))
async def promo_callback(callback: types.CallbackQuery, state: FSMContext):
    task_id = callback.data.split("_", 1)[1]
    
    await safe_edit_message(
        callback.message,
        "🎫 **Введите промокод**\n\n"
        "Введите промокод для получения скидки:\n"
        "Например: WELCOME\n\n"
        "💡 *Промокоды доступны только пользователям, получившим рассылку*",
        parse_mode="Markdown"
    )
    
    await state.update_data(task_id=task_id)
    await state.set_state(MusicGeneration.waiting_for_promocode)
    await safe_callback_answer(callback)

@main_dp.message(MusicGeneration.waiting_for_promocode)
async def process_promocode(message: types.Message, state: FSMContext):
    data = await state.get_data()
    task_id = data.get("task_id")
    code = message.text.strip().upper()
    
    new_price, discount, error_msg = apply_promocode(code, FULL_VERSION_PRICE, message.from_user.id, task_id)
    
    if discount > 0:
        if discount == 100:
            orders = load_json(ORDERS_FILE)
            if task_id in orders:
                order = orders[task_id]
                audio_url = order.get("audio_url")
                title = order.get("title", "Generated Music")
                
                update_order_paid(task_id, message.from_user.id, 0)
                
                full_filename = f"temp/full_{task_id}.mp3"
                if await download_audio(audio_url, full_filename):
                    audio_file = FSInputFile(full_filename)
                    
                    await main_bot.send_audio(
                        chat_id=message.chat.id,
                        audio=audio_file,
                        title=title,
                        caption=f"🎵 *{title}* (Полная версия)\n\n🤖 ИИ генерация\n🎁 Получено по промокоду {code} (100% скидка)\n\n✅ Спасибо за использование бота!",
                        parse_mode="Markdown"
                    )
                    
                    keyboard = get_admin_keyboard() if is_admin(message.from_user.id) else get_main_keyboard()
                    await message.answer("🎁 Промокод применен! Полная версия получена бесплатно!", reply_markup=keyboard)
                    
                    try:
                        os.remove(full_filename)
                        logging.info(f"Файл {full_filename} удален после отправки")
                    except Exception as e:
                        logging.error(f"Ошибка при удалении файла: {e}")
                else:
                    await message.answer("❌ Ошибка при получении файла. Обратитесь в поддержку.")
            else:
                await message.answer("❌ Заказ не найден.")
        else:
            original_price = FULL_VERSION_PRICE / 100
            discounted_price = new_price / 100
            savings = original_price - discounted_price
            
            await main_bot.send_invoice(
                chat_id=message.chat.id,
                title=f"Полная версия песни (скидка {discount}%)",
                description=f"Получите полную версию сгенерированной песни со скидкой {discount}%! Экономия: {savings}₽",
                payload=f"full_music_{task_id}",
                provider_token=YUKASSA_TOKEN,
                currency="RUB",
                prices=[LabeledPrice(label=f"Полная версия (-{discount}%)", amount=new_price)],
                start_parameter="music_payment"
            )
            await message.answer(f"✅ Промокод применен! Скидка {discount}% = экономия {savings}₽")
    else:
        await message.answer(f"❌ {error_msg}")
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💰 Оплатить (500₽)", callback_data=f"pay_{task_id}")],
            [InlineKeyboardButton(text="🎫 Попробовать другой промокод", callback_data=f"promo_{task_id}")]
        ])
        await message.answer("Выберите способ оплаты:", reply_markup=keyboard)
    
    await state.clear()

# Обработка платежей
@main_dp.callback_query(F.data.startswith("pay_"))
async def process_payment_button(callback: types.CallbackQuery):
    task_id = callback.data.split("_", 1)[1]
    
    await main_bot.send_invoice(
        chat_id=callback.message.chat.id,
        title="Полная версия песни",
        description="Получите полную версию сгенерированной песни без ограничений по времени",
        payload=f"full_music_{task_id}",
        provider_token=YUKASSA_TOKEN,
        currency="RUB",
        prices=[LabeledPrice(label="Полная версия", amount=FULL_VERSION_PRICE)],
        start_parameter="music_payment"
    )
    
    await safe_callback_answer(callback)

@main_dp.pre_checkout_query()
async def process_pre_checkout_query(pre_checkout_query: PreCheckoutQuery):
    await main_bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@main_dp.message(F.successful_payment)
async def process_successful_payment(message: types.Message):
    payload = message.successful_payment.invoice_payload
    amount_paid = message.successful_payment.total_amount
    
    if payload.startswith("full_music_"):
        task_id = payload.replace("full_music_", "")
        
        update_order_paid(task_id, message.from_user.id, amount_paid)
        
        orders = load_json(ORDERS_FILE)
        if task_id in orders:
            order = orders[task_id]
            audio_url = order.get("audio_url")
            title = order.get("title", "Generated Music")
            
            full_filename = f"temp/full_{task_id}.mp3"
            if await download_audio(audio_url, full_filename):
                audio_file = FSInputFile(full_filename)
                
                await main_bot.send_audio(
                    chat_id=message.chat.id,
                    audio=audio_file,
                    title=title,
                    caption=f"🎵 *{title}* (Полная версия)\n\n🤖 ИИ генерация\n💰 Оплачено: {amount_paid/100}₽\n\n✅ Спасибо за покупку!",
                    parse_mode="Markdown"
                )
                
                keyboard = get_admin_keyboard() if is_admin(message.from_user.id) else get_main_keyboard()
                await message.answer("✅ Спасибо за покупку! Полная версия песни отправлена.", reply_markup=keyboard)
                
                try:
                    os.remove(full_filename)
                    logging.info(f"Файл {full_filename} удален после отправки")
                except Exception as e:
                    logging.error(f"Ошибка при удалении файла: {e}")
                
                return
            else:
                await message.answer("❌ Ошибка при скачивании полной версии. Обратитесь в поддержку.")
                return
        
        await message.answer("❌ Ошибка при получении полной версии. Обратитесь в поддержку.")

# АДМИН ФУНКЦИИ
@main_dp.callback_query(F.data == "admin_stats")
async def admin_stats_callback(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_callback_answer(callback)
        await callback.message.answer("❌ Нет доступа")
        return
    
    status_msg = await safe_send_message(main_bot, callback.message.chat.id, "📊 Генерирую статистику...")
    
    try:
        chart_path = generate_stats_chart()
        chart_file = FSInputFile(chart_path)
        
        await main_bot.send_photo(
            chat_id=callback.message.chat.id,
            photo=chart_file,
            caption="📊 **Статистика бота**",
            parse_mode="Markdown",
            reply_markup=get_admin_keyboard()
        )
        
        if status_msg:
            await status_msg.delete()
            
    except Exception as e:
        if status_msg:
            await status_msg.edit_text(f"❌ Ошибка генерации статистики: {e}")
        logging.error(f"Ошибка генерации статистики: {e}")

    await safe_callback_answer(callback)

@main_dp.callback_query(F.data == "admin_users")
async def admin_users_callback(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_callback_answer(callback)
        await callback.message.answer("❌ Нет доступа")
        return

    users = load_json(USERS_FILE)

    text = "👥 **Пользователи бота:**\n\n"

    sorted_users = sorted(users.items(), key=lambda x: x[1]["orders_count"], reverse=True)

    for i, (user_id, data) in enumerate(sorted_users[:20], 1):
        name = data["first_name"] or data["username"] or f"User {user_id}"
        text += f"{i}. *{name}*\n"
        text += f"   🆔 `{user_id}`\n"
        text += f"   📊 Заказов: {data['orders_count']} | Оплачено: {data['paid_count']}\n"
        text += f"   💰 Потрачено: {data['total_spent']}₽\n"
        text += f"   📅 Присоединился: {data['join_date'][:10]}\n"
        text += f"   📢 Рассылка: {'✅' if data.get('received_broadcast', False) else '❌'}\n"
        
        # Показываем реферера, если есть
        if data.get("referrer_code"):
            agent_id, agent_data = get_agent_by_ref_code(data["referrer_code"])
            if agent_data:
                text += f"   👤 Реферер: {agent_data['first_name']}\n"
        
        text += "\n"

    if len(users) > 20:
        text += f"... и еще {len(users) - 20} пользователей"

    await safe_send_message(main_bot, callback.message.chat.id, text, parse_mode="Markdown", reply_markup=get_admin_keyboard())
    await safe_callback_answer(callback)

@main_dp.callback_query(F.data == "admin_block")
async def admin_block_callback(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await safe_callback_answer(callback)
        await callback.message.answer("❌ Нет доступа")
        return

    await safe_send_message(main_bot, callback.message.chat.id, "🚫 Введите ID пользователя для блокировки:")
    await state.set_state(AdminPanel.waiting_for_user_id_block)
    await safe_callback_answer(callback)

@main_dp.message(AdminPanel.waiting_for_user_id_block)
async def process_user_block(message: types.Message, state: FSMContext):
    try:
        user_id = int(message.text.strip())

        blocked_users = load_json(BLOCKED_USERS_FILE)
        if user_id not in blocked_users:
            blocked_users.append(user_id)
            save_json(BLOCKED_USERS_FILE, blocked_users)
            await message.answer(f"✅ Пользователь {user_id} заблокирован", reply_markup=get_admin_keyboard())
        else:
            await message.answer(f"❌ Пользователь {user_id} уже заблокирован", reply_markup=get_admin_keyboard())
    except ValueError:
        await message.answer("❌ Неверный формат ID", reply_markup=get_admin_keyboard())

    await state.clear()

@main_dp.callback_query(F.data == "admin_unblock")
async def admin_unblock_callback(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await safe_callback_answer(callback)
        await callback.message.answer("❌ Нет доступа")
        return

    await safe_send_message(main_bot, callback.message.chat.id, "✅ Введите ID пользователя для разблокировки:")
    await state.set_state(AdminPanel.waiting_for_user_id_unblock)
    await safe_callback_answer(callback)

@main_dp.message(AdminPanel.waiting_for_user_id_unblock)
async def process_user_unblock(message: types.Message, state: FSMContext):
    try:
        user_id = int(message.text.strip())

        blocked_users = load_json(BLOCKED_USERS_FILE)
        if user_id in blocked_users:
            blocked_users.remove(user_id)
            save_json(BLOCKED_USERS_FILE, blocked_users)
            await message.answer(f"✅ Пользователь {user_id} разблокирован", reply_markup=get_admin_keyboard())
        else:
            await message.answer(f"❌ Пользователь {user_id} не был заблокирован", reply_markup=get_admin_keyboard())
    except ValueError:
        await message.answer("❌ Неверный формат ID", reply_markup=get_admin_keyboard())

    await state.clear()

@main_dp.callback_query(F.data == "admin_promo")
async def admin_promo_callback(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_callback_answer(callback)
        await callback.message.answer("❌ Нет доступа")
        return

    promocodes = load_json(PROMOCODES_FILE)

    text = "🎫 **Промокоды:**\n\n"
    if promocodes:
        for code, data in promocodes.items():
            remaining = data['max_uses'] - data['uses']
            text += f"📝 `{code}`\n"
            text += f"   💰 Скидка: {data['discount']}%\n"
            text += f"   📊 Использований: {data['uses']}/{data['max_uses']} (осталось: {remaining})\n\n"
    else:
        text += "Промокодов нет\n\n"

    text += "💡 Создать новый промокод: /createpromo"

    await safe_send_message(main_bot, callback.message.chat.id, text, parse_mode="Markdown", reply_markup=get_admin_keyboard())
    await safe_callback_answer(callback)

@main_dp.callback_query(F.data == "admin_support")
async def admin_support_callback(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_callback_answer(callback)
        await callback.message.answer("❌ Нет доступа")
        return

    await safe_send_message(
        main_bot,
        callback.message.chat.id,
        "💬 **Панель поддержки**\n\n"
        "Здесь будут отображаться обращения пользователей.\n"
        "Когда придет обращение, вы получите уведомление.",
        parse_mode="Markdown",
        reply_markup=get_admin_keyboard()
    )
    await safe_callback_answer(callback)

# Обработка неизвестных сообщений для основного бота
@main_dp.message()
async def unknown_message_main(message: types.Message):
    if await check_user_blocked(message):
        return

    keyboard = get_admin_keyboard() if is_admin(message.from_user.id) else get_main_keyboard()
    await message.answer(
        "🤔 Не понимаю эту команду.\n"
        "Используйте кнопки ниже для навигации:",
        reply_markup=keyboard
    )

# === ОБРАБОТЧИКИ ДЛЯ АГЕНТСКОГО БОТА ===

@agent_dp.message(Command("start"))
async def agent_start(message: types.Message):
    agent_id = str(message.from_user.id)
    agents = load_json(AGENTS_FILE)
    
    if agent_id in agents:
        # Уже зарегистрированный агент
        agent_data = agents[agent_id]
        ref_link = generate_referral_link(agent_data["ref_code"])
        
        await message.answer(
            f"👋 **С возвращением, {agent_data['first_name']}!**\n\n"
            f"📊 Ваша статистика:\n"
            f"• Баланс: {agent_data['balance']:.2f}₽\n"
            f"• Всего рефералов: {agent_data['total_referrals']}\n"
            f"• Оплаченных заказов: {agent_data['paid_referrals']}\n"
            f"• Заработано всего: {agent_data['total_earned']:.2f}₽\n\n"
            f"🔗 Ваша реферальная ссылка:\n`{ref_link}`",
            parse_mode="Markdown",
            reply_markup=get_agent_main_keyboard()
        )
    else:
        # Новый агент
        await message.answer(
            "🎉 **Добро пожаловать в агентскую программу!**\n\n"
            "💰 Зарабатывайте 30% с каждой оплаченной песни!\n\n"
            "Для начала выберите ваш статус:",
            parse_mode="Markdown",
            reply_markup=get_agent_type_keyboard()
        )

@agent_dp.callback_query(F.data.startswith("agent_type_"))
async def process_agent_type(callback: types.CallbackQuery, state: FSMContext):
    agent_type = callback.data.replace("agent_type_", "")
    
    await state.update_data(agent_type=agent_type)
    
    type_names = {
        "individual": "Физическое лицо",
        "ip": "ИП",
        "selfemployed": "Самозанятый"
    }
    
    await safe_edit_message(
        callback.message,
        f"✅ Вы выбрали: **{type_names[agent_type]}**\n\n"
        f"Введите ваше полное имя:",
        parse_mode="Markdown"
    )
    
    await state.set_state(AgentRegistration.waiting_for_name)
    await safe_callback_answer(callback)

@agent_dp.message(AgentRegistration.waiting_for_name)
async def process_agent_name(message: types.Message, state: FSMContext):
    name = message.text.strip()
    
    if len(name) < 3:
        await message.answer("❌ Имя слишком короткое. Введите полное имя:")
        return
    
    await state.update_data(name=name)
    await message.answer(
        "📱 Введите ваш номер телефона для связи:\n"
        "Формат: +79001234567",
        parse_mode="Markdown"
    )
    await state.set_state(AgentRegistration.waiting_for_phone)

@agent_dp.message(AgentRegistration.waiting_for_phone)
async def process_agent_phone(message: types.Message, state: FSMContext):
    phone = message.text.strip()
    
    if not phone.startswith('+') or len(phone) < 10:
        await message.answer("❌ Неверный формат номера. Введите в формате +79001234567:")
        return
    
    await state.update_data(phone=phone)
    await message.answer(
        "💳 Введите номер карты для вывода средств:\n"
        "(16 цифр без пробелов)",
        parse_mode="Markdown"
    )
    await state.set_state(AgentRegistration.waiting_for_card)

@agent_dp.message(AgentRegistration.waiting_for_card)
async def process_agent_card(message: types.Message, state: FSMContext):
    card = message.text.strip().replace(" ", "")
    
    if not card.isdigit() or len(card) != 16:
        await message.answer("❌ Неверный номер карты. Введите 16 цифр:")
        return
    
    data = await state.get_data()
    agent_type = data["agent_type"]
    
    # Регистрируем агента
    ref_code = register_agent(
        message.from_user.id,
        message.from_user.username,
        data["name"],
        agent_type
    )
    
    # Сохраняем дополнительные данные
    agents = load_json(AGENTS_FILE)
    agents[str(message.from_user.id)]["phone"] = data["phone"]
    agents[str(message.from_user.id)]["card_number"] = card
    save_json(AGENTS_FILE, agents)
    
    # Генерируем ссылку и QR-код
    ref_link = generate_referral_link(ref_code)
    qr_code = generate_qr_code(ref_link)
    
    # Отправляем приветственное сообщение
    await agent_bot.send_photo(
        chat_id=message.chat.id,
        photo=types.BufferedInputFile(qr_code.getvalue(), filename="qr_code.png"),
        caption=f"✅ **Регистрация завершена!**\n\n"
                f"🎉 Добро пожаловать в команду агентов!\n\n"
                f"📄 Договор-оферта отправлен следующим сообщением.\n\n"
                f"🔗 Ваша уникальная реферальная ссылка:\n`{ref_link}`\n\n"
                f"📲 QR-код для быстрого доступа выше\n\n"
                f"💰 Вы будете получать 30% с каждой оплаченной песни!",
        parse_mode="Markdown",
        reply_markup=get_agent_main_keyboard()
    )
    
    # Отправляем договор
    agent_type_names = {
        'individual': 'Физическое лицо',
        'ip': 'ИП',
        'selfemployed': 'Самозанятый'
    }
    
    contract_text = f"""📄 **ДОГОВОР-ОФЕРТА**

**Агент:** {data['name']}
**Тип:** {agent_type_names[agent_type]}
**Дата:** {datetime.now().strftime('%d.%m.%Y')}

**УСЛОВИЯ:**
1. Агент получает вознаграждение 30% от стоимости оплаченных заказов
2. Выплаты производятся на указанную карту
3. Агент самостоятельно декларирует доход и платит налоги
4. Минимальная сумма для вывода: 100₽

**ОБЯЗАННОСТИ АГЕНТА:**
- Привлекать новых пользователей
- Не использовать спам и недобросовестную рекламу
- Соблюдать законодательство РФ

Используя бота, вы соглашаетесь с условиями договора."""
    
    await message.answer(contract_text, parse_mode="Markdown")
    await state.clear()

@agent_dp.callback_query(F.data == "agent_cabinet")
async def agent_cabinet(callback: types.CallbackQuery):
    agent_id = str(callback.from_user.id)
    agents = load_json(AGENTS_FILE)
    
    if agent_id not in agents:
        await callback.answer("❌ Вы не зарегистрированы как агент", show_alert=True)
        return
    
    agent_data = agents[agent_id]
    ref_link = generate_referral_link(agent_data["ref_code"])
    
    # Маскируем номер карты
    card_masked = agent_data["card_number"][:4] + " **** **** " + agent_data["card_number"][-4:]
    
    agent_type_names = {
        'individual': 'Физическое лицо',
        'ip': 'ИП',
        'selfemployed': 'Самозанятый'
    }
    
    text = f"""👤 **Личный кабинет**

**Информация:**
• Имя: {agent_data['name']}
• Тип: {agent_type_names[agent_data['type']]}
• Телефон: {agent_data['phone']}
• Карта: {card_masked}

**Финансы:**
• Текущий баланс: {agent_data['balance']:.2f}₽
• Заработано всего: {agent_data['total_earned']:.2f}₽
• Выведено: {agent_data['total_withdrawn']:.2f}₽

**Статистика:**
• Всего рефералов: {agent_data['total_referrals']}
• Оплаченных заказов: {agent_data['paid_referrals']}

**Ваша ссылка:**
`{ref_link}`"""
    
    await safe_edit_message(callback.message, text, parse_mode="Markdown", reply_markup=get_agent_main_keyboard())
    await safe_callback_answer(callback)

@agent_dp.callback_query(F.data == "agent_stats")
async def agent_stats(callback: types.CallbackQuery):
    agent_id = str(callback.from_user.id)
    agents = load_json(AGENTS_FILE)
    
    if agent_id not in agents:
        await callback.answer("❌ Вы не зарегистрированы как агент", show_alert=True)
        return
    
    agent_data = agents[agent_id]
    ref_stats = load_json(REFERRAL_STATS_FILE)
    stats = ref_stats.get(agent_data["ref_code"], {})
    
    # Считаем конверсию
    conversion_rate = 0
    if stats.get("registrations", 0) > 0:
        conversion_rate = (stats.get("paid_orders", 0) / stats.get("registrations", 0)) * 100
    
    text = f"""📊 **Детальная статистика**

**Трафик:**
• Переходов по ссылке: {stats.get('clicks', 0)}
• Регистраций: {stats.get('registrations', 0)}
• Конверсия в регистрации: {(stats.get('registrations', 0) / stats.get('clicks', 1) * 100) if stats.get('clicks', 0) > 0 else 0:.1f}%

**Заказы:**
• Всего заказов: {stats.get('orders', 0)}
• Оплаченных заказов: {stats.get('paid_orders', 0)}
• Конверсия в оплаты: {conversion_rate:.1f}%

**Финансы:**
• Общий оборот: {stats.get('total_revenue', 0):.2f}₽
• Ваша комиссия (30%): {stats.get('total_revenue', 0) * 0.3:.2f}₽
• Средний чек: {(stats.get('total_revenue', 0) / stats.get('paid_orders', 1)) if stats.get('paid_orders', 0) > 0 else 0:.2f}₽

**Эффективность:**
• Доход на клик: {(agent_data['total_earned'] / stats.get('clicks', 1)) if stats.get('clicks', 0) > 0 else 0:.2f}₽
• Доход на регистрацию: {(agent_data['total_earned'] / stats.get('registrations', 1)) if stats.get('registrations', 0) > 0 else 0:.2f}₽"""
    
    await safe_edit_message(callback.message, text, parse_mode="Markdown", reply_markup=get_agent_main_keyboard())
    await safe_callback_answer(callback)

@agent_dp.callback_query(F.data == "agent_withdraw")
async def agent_withdraw(callback: types.CallbackQuery, state: FSMContext):
    agent_id = str(callback.from_user.id)
    agents = load_json(AGENTS_FILE)
    
    if agent_id not in agents:
        await callback.answer("❌ Вы не зарегистрированы как агент", show_alert=True)
        return
    
    agent_data = agents[agent_id]
    balance = agent_data["balance"]
    
    if balance < 100:
        await callback.answer(f"❌ Минимальная сумма для вывода 100₽. Ваш баланс: {balance:.2f}₽", show_alert=True)
        return
    
    await safe_edit_message(
        callback.message,
        f"💸 **Вывод средств**\n\n"
        f"Доступно для вывода: {balance:.2f}₽\n\n"
        f"Введите сумму для вывода (минимум 100₽):",
        parse_mode="Markdown"
    )
    
    await state.set_state(AgentRegistration.waiting_for_withdrawal_amount)
    await safe_callback_answer(callback)

@agent_dp.message(AgentRegistration.waiting_for_withdrawal_amount)
async def process_withdrawal_amount(message: types.Message, state: FSMContext):
    try:
        amount = float(message.text.strip())
        
        if amount < 100:
            await message.answer("❌ Минимальная сумма для вывода 100₽")
            return
        
        agent_id = str(message.from_user.id)
        agents = load_json(AGENTS_FILE)
        agent_data = agents[agent_id]
        
        if amount > agent_data["balance"]:
            await message.answer(f"❌ Недостаточно средств. Доступно: {agent_data['balance']:.2f}₽")
            return
        
        # Создаем заявку на вывод
        payments = load_json(AGENT_PAYMENTS_FILE)
        payment_id = str(uuid.uuid4())[:8]
        
        payments[payment_id] = {
            "agent_id": agent_id,
            "amount": amount,
            "card": agent_data["card_number"],
            "status": "pending",
            "created_date": datetime.now().isoformat()
        }
        save_json(AGENT_PAYMENTS_FILE, payments)
        
        # Уведомляем админов
        admin_text = f"""💸 **Новая заявка на вывод**

Агент: {agent_data['name']}
ID: `{agent_id}`
Сумма: {amount:.2f}₽
Карта: {agent_data['card_number']}

ID заявки: `{payment_id}`"""
        
        admin_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"approve_payment_{payment_id}")],
            [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_payment_{payment_id}")]
        ])
        
        for admin_id in [OWNER_ID, ADMIN_ID]:
            try:
                await main_bot.send_message(admin_id, admin_text, parse_mode="Markdown", reply_markup=admin_keyboard)
            except:
                pass
        
        await message.answer(
            f"✅ Заявка на вывод {amount:.2f}₽ создана!\n\n"
            f"Ожидайте подтверждения администратора.\n"
            f"Обычно это занимает до 24 часов.",
            parse_mode="Markdown",
            reply_markup=get_agent_main_keyboard()
        )
        
        await state.clear()
        
    except ValueError:
        await message.answer("❌ Введите корректную сумму")

@agent_dp.callback_query(F.data == "agent_contract")
async def agent_contract(callback: types.CallbackQuery):
    agent_id = str(callback.from_user.id)
    agents = load_json(AGENTS_FILE)
    
    if agent_id not in agents:
        await callback.answer("❌ Вы не зарегистрированы как агент", show_alert=True)
        return
    
    agent_data = agents[agent_id]
    
    agent_type_names = {
        'individual': 'Физическое лицо',
        'ip': 'ИП',
        'selfemployed': 'Самозанятый'
    }
    
    contract_text = f"""📄 **ДОГОВОР-ОФЕРТА**

**Агент:** {agent_data['name']}
**Тип:** {agent_type_names[agent_data['type']]}
**Дата регистрации:** {agent_data['registration_date'][:10]}

**УСЛОВИЯ:**
1. Агент получает вознаграждение 30% от стоимости оплаченных заказов
2. Выплаты производятся на карту: {agent_data['card_number'][:4]} **** **** {agent_data['card_number'][-4:]}
3. Агент самостоятельно декларирует доход и платит налоги
4. Минимальная сумма для вывода: 100₽

**ОБЯЗАННОСТИ АГЕНТА:**
- Привлекать новых пользователей честными методами
- Не использовать спам и недобросовестную рекламу
- Соблюдать законодательство РФ
- Предоставлять достоверную информацию о сервисе

**ОТВЕТСТВЕННОСТЬ:**
За нарушение условий договора агент может быть заблокирован с потерей накоплений."""
    
    await safe_send_message(agent_bot, callback.message.chat.id, contract_text, parse_mode="Markdown")
    await safe_callback_answer(callback)

@agent_dp.callback_query(F.data == "agent_help")
async def agent_help(callback: types.CallbackQuery):
    help_text = """❓ **Помощь по агентской программе**

**Как это работает:**
1. Делитесь вашей уникальной ссылкой
2. Люди регистрируются по вашей ссылке
3. Когда они оплачивают песни, вы получаете 30%

**Где взять ссылку:**
Нажмите "Личный кабинет" - там есть ваша ссылка и QR-код

**Как вывести деньги:**
1. Накопите минимум 100₽
2. Нажмите "Вывод средств"
3. Введите сумму
4. Дождитесь подтверждения (до 24ч)

**Советы по продвижению:**
• Расскажите друзьям о возможности создавать песни
• Поделитесь в соцсетях
• Покажите примеры созданных песен
• Объясните, как это просто

**Важно:**
• Не используйте спам
• Не обманывайте людей
• Платите налоги с дохода

По всем вопросам пишите в поддержку основного бота."""
    
    await safe_edit_message(callback.message, help_text, parse_mode="Markdown", reply_markup=get_agent_main_keyboard())
    await safe_callback_answer(callback)

# Обработка платежей агентов в основном боте
@main_dp.callback_query(F.data.startswith("approve_payment_"))
async def approve_payment(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    
    payment_id = callback.data.replace("approve_payment_", "")
    payments = load_json(AGENT_PAYMENTS_FILE)
    
    if payment_id not in payments:
        await callback.answer("❌ Платеж не найден", show_alert=True)
        return
    
    payment = payments[payment_id]
    agent_id = payment["agent_id"]
    amount = payment["amount"]
    
    # Обновляем статус платежа
    payments[payment_id]["status"] = "approved"
    payments[payment_id]["approved_date"] = datetime.now().isoformat()
    payments[payment_id]["approved_by"] = callback.from_user.id
    save_json(AGENT_PAYMENTS_FILE, payments)
    
    # Обновляем баланс агента
    agents = load_json(AGENTS_FILE)
    agents[agent_id]["balance"] -= amount
    agents[agent_id]["total_withdrawn"] += amount
    save_json(AGENTS_FILE, agents)
    
    # Уведомляем агента
    try:
        await agent_bot.send_message(
            int(agent_id),
            f"✅ **Вывод подтвержден!**\n\n"
            f"Сумма: {amount:.2f}₽\n"
            f"Средства будут переведены на вашу карту в течение 1-3 рабочих дней.",
            parse_mode="Markdown"
        )
    except:
        pass
    
    await safe_edit_message(
        callback.message,
        callback.message.text + f"\n\n✅ **Одобрено администратором {callback.from_user.first_name}**",
        parse_mode="Markdown"
    )
    await callback.answer("✅ Платеж одобрен")

@main_dp.callback_query(F.data.startswith("reject_payment_"))
async def reject_payment(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    
    payment_id = callback.data.replace("reject_payment_", "")
    payments = load_json(AGENT_PAYMENTS_FILE)
    
    if payment_id not in payments:
        await callback.answer("❌ Платеж не найден", show_alert=True)
        return
    
    payment = payments[payment_id]
    agent_id = payment["agent_id"]
    amount = payment["amount"]
    
    # Обновляем статус платежа
    payments[payment_id]["status"] = "rejected"
    payments[payment_id]["rejected_date"] = datetime.now().isoformat()
    payments[payment_id]["rejected_by"] = callback.from_user.id
    save_json(AGENT_PAYMENTS_FILE, payments)
    
    # Уведомляем агента
    try:
        await agent_bot.send_message(
            int(agent_id),
            f"❌ **Вывод отклонен**\n\n"
            f"Сумма: {amount:.2f}₽\n"
            f"Свяжитесь с поддержкой для выяснения причин.",
            parse_mode="Markdown"
        )
    except:
        pass
    
    await safe_edit_message(
        callback.message,
        callback.message.text + f"\n\n❌ **Отклонено администратором {callback.from_user.first_name}**",
        parse_mode="Markdown"
    )
    await callback.answer("❌ Платеж отклонен")

# Обработка неизвестных сообщений для агентского бота
@agent_dp.message()
async def unknown_message_agent(message: types.Message):
    agents = load_json(AGENTS_FILE)
    
    if str(message.from_user.id) in agents:
        keyboard = get_agent_main_keyboard()
    else:
        keyboard = get_agent_type_keyboard()
    
    await message.answer(
        "🤔 Не понимаю эту команду.\n"
        "Используйте кнопки ниже для навигации:",
        reply_markup=keyboard
    )

# Основная функция
async def main():
    # Инициализация
    init_data_files()
    os.makedirs("temp", exist_ok=True)

    try:
        logging.info("Запуск ботов...")
        
        # Запускаем оба бота параллельно
        await asyncio.gather(
            main_dp.start_polling(main_bot),
            agent_dp.start_polling(agent_bot)
        )
    except Exception as e:
        logging.error(f"Ошибка запуска ботов: {e}")
    finally:
        await main_bot.session.close()
        await agent_bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
