import asyncio
import aiohttp
import logging
import math
import time
import re
import aiosqlite
from typing import Callable, Dict, Any, Awaitable
from aiogram import Bot, Dispatcher, F, BaseMiddleware
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, TelegramObject
from aiogram.filters import Command, StateFilter
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# === Настройка логирования ===
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s"
)
logger = logging.getLogger(__name__)

# === Конфигурация и Токены ===
BOT_TOKEN = "Ваш_Токен"
LZT_MARKET_TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzUxMiJ9.eyJzdWIiOjkzODcwOTIsImlzcyI6Imx6dCIsImlhdCI6MTc4MTg5MzMyNiwianRpIjoiOTg3NjA4Iiwic2NvcGUiOiJiYXNpYyByZWFkIHBvc3QgY29udmVyc2F0ZSBwYXltZW50IGludm9pY2UgY2hhdGJveCBtYXJrZXQiLCJleHAiOjE5Mzk1NzMzMjZ9.n6ipv8-t-c_5yzjX43NrL95fWCgGAn6blng2cGlkVDArYEP_iiEZshV_tmgfsnlNapv5fQoXVI5PbzyOn4TcEr--MDRQCIWQOVzOs4ieJTxXZoU51WT6TJn0AnsqWsFMCtUSVq_3AM6pC17TUtaMBEWcvBuyjt76LXU--Y8KF9o"

CRYPTOBOT_TOKEN = "598369:AAc0qeNLq4RnWNShSQ3WimDpmLfRiDkXptu"
SUPPORT_USERNAME = "@Юзернейм_Поддержки"

#  НАСТРОЙКИ ОБЯЗАТЕЛЬНОЙ ПОДПИСКИ
REQUIRED_CHANNEL = "@kzfdblog" # ЗАМЕНИ НА ЮЗЕРНЕЙМ СВОЕГО КАНАЛА
CHANNEL_URL = "https://t.me/kzfdblog" # ЗАМЕНИ НА ССЫЛКУ НА КАНАЛ

#  УКАЖИ СВОЙ ТЕЛЕГРАМ ID ДЛЯ ДОСТУПА К АДМИНКЕ
ADMIN_ID = 6306380030 

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

#      API 
API_BASE = "https://api.lzt.market"
PROD_API_BASE = "https://prod-api.lzt.market"
CRYPTO_API_BASE = "https://pay.crypt.bot/api"

LZT_HEADERS = {
    "Authorization": f"Bearer {LZT_MARKET_TOKEN}",
    "Accept": "application/json"
}

CRYPTO_HEADERS = {
    "Crypto-Pay-API-Token": CRYPTOBOT_TOKEN
}

DB_NAME = "onyx_store.db"

#  Словари
ORIGIN_MAP = {
    "autoreg": "Авторег",
    "phishing": "Фишинг",
    "brute": "Брут",
    "resale": "Перепродажа",
    "personal": "Личный аккаунт",
    "stealer": "Стилер",
    "self_registration": "Саморег",
    "retrieve_via_support": "Вернутый поддержкой"
}

COUNTRY_MAP = {
    "US": "🇺🇸 США", "RU": "🇷🇺 Россия", "KZ": "🇰🇿 Казахстан",
    "ID": "🇮🇩 Индонезия", "IN": "🇮🇳 Индия", "NG": "🇳🇬 Нигерия",
    "VN": "🇻🇳 Вьетнам", "BR": "🇧🇷 Бразилия", "PH": "🇵🇭 Филиппины",
    "EG": "🇪🇬 Египет", "GB": "🇬🇧 Великобритания", "TR": "🇹🇷 Турция",
    "CO": "🇨🇴 Колумбия", "ZA": "🇿🇦 ЮАР", "KE": "🇰🇪 Кения",
    "PK": "🇵🇰 Пакистан", "BD": "🇧🇩 Бангладеш", "CN": "🇨🇳 Китай",
    "UA": "🇺🇦 Украина", "BY": "🇧🇾 Беларусь", "UZ": "🇺🇿 Узбекистан"
}

SPAM_MAP = {
    "nomatter": "Не важно 🤷‍♂️",
    "no": "Нет спамблока ✅",
    "yes": "Есть спамблок 🚫"
}

USER_FILTERS = {}
SEARCH_CACHE = {}

# FSM
class TopUpState(StatesGroup):
    waiting_for_amount = State()

class AdminState(StatesGroup):
    waiting_for_rate = State()
    waiting_for_markup = State()

def get_user_filters(user_id: int):
    if user_id not in USER_FILTERS:
        USER_FILTERS[user_id] = {
            "countries": [],
            "origins": [],
            "spam": "nomatter",
            "ignore_price": True
        }
    return USER_FILTERS[user_id]


async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS purchases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                item_id TEXT,
                title TEXT,
                phone TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                balance REAL DEFAULT 0.0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS invoices (
                invoice_id INTEGER PRIMARY KEY,
                user_id INTEGER,
                amount REAL,
                status TEXT DEFAULT 'pending'
            )
        """)
        # База Данных
        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                usdt_rate REAL,
                markup REAL
            )
        """)
        await db.execute("INSERT OR IGNORE INTO settings (id, usdt_rate, markup) VALUES (1, 500.0, 50.0)")
        await db.commit()

# Адмика
async def get_settings():
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT usdt_rate, markup FROM settings WHERE id = 1") as cursor:
            row = await cursor.fetchone()
            return row if row else (500.0, 50.0)

async def update_settings(rate=None, markup=None):
    current_rate, current_markup = await get_settings()
    new_rate = rate if rate is not None else current_rate
    new_markup = markup if markup is not None else current_markup
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE settings SET usdt_rate = ?, markup = ? WHERE id = 1", (new_rate, new_markup))
        await db.commit()

#баланс
async def get_balance(user_id: int) -> float:
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return row[0]
            else:
                await db.execute("INSERT INTO users (user_id, balance) VALUES (?, 0.0)", (user_id,))
                await db.commit()
                return 0.0

async def add_balance(user_id: int, amount: float):
    current = await get_balance(user_id)
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE users SET balance = ? WHERE user_id = ?", (current + amount, user_id))
        await db.commit()

async def deduct_balance(user_id: int, amount: float) -> bool:
    current = await get_balance(user_id)
    if current >= amount:
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("UPDATE users SET balance = ? WHERE user_id = ?", (current - amount, user_id))
            await db.commit()
        return True
    return False

# === Хелповики парсеры ===
def format_origin(val: str) -> str:
    return ORIGIN_MAP.get(str(val).lower(), str(val))

def format_country(val: str) -> str:
    code = str(val).upper()
    return COUNTRY_MAP.get(code, code)

def extract_phone_number(item: dict) -> str:
    for key in ["phone", "telegram_phone", "number", "account_phone", "phone_number"]:
        if item.get(key): return str(item[key])
    login = str(item.get("login", ""))
    if 5 < len(login) < 20 and sum(c.isdigit() for c in login) >= 7: return login
    title = str(item.get("title", ""))
    match = re.search(r'\+?\d{10,15}', title)
    if match: return match.group(0)
    return "Не найден (Лолз спрятал номер)"

# Пойск С ФильТрами
async def search_lzt_items(user_id: int):
    filters = get_user_filters(user_id)
    params = []
    
    for c in filters["countries"]:
        params.append(("country[]", c))
    for o in filters["origins"]:
        params.append(("origin[]", o))
    if filters["spam"] != "nomatter":
        params.append(("spam", filters["spam"]))
    if filters["spam"] == "no":
        params.append(("allow_geo_spamblock", "1"))

    logger.info(f"--- [Поиск LZT | Пользователь: {user_id}] ---")
    logger.info(f"Отправляемые параметры в API: {params}")

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(f"{PROD_API_BASE}/telegram", headers=LZT_HEADERS, params=params) as response:
                if response.status == 429:
                    logger.warning(f"Rate Limit (429) от Лолза для пользователя {user_id}")
                    return None
                data = await response.json()
                
                logger.info(f"Статус ответа: {response.status}")
                logger.info(f"Полученный JSON: {data}")
                
                parsed = []
                for item in data.get("items", []):
                    parsed.append({
                        "id": item.get("item_id"),
                        "price": item.get("price"),
                        "description": item.get("title", f"TG Account #{item.get('item_id')}"),
                        "country": format_country(item.get("telegram_country")),
                        "origin": format_origin(item.get("origin")),
                        "premium": item.get("telegram_premium", 0),
                        "spamblock": item.get("telegram_spam_block", -1)
                    })
                
                if not filters["ignore_price"]:
                    parsed = sorted(parsed, key=lambda x: x["price"])
                    
                SEARCH_CACHE[user_id] = parsed
                return parsed
        except Exception as e:
            logger.error(f"Search API Error: {e}")
            return []



# АДМИKa


@dp.message(Command("admin"))
async def admin_panel(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await state.clear()
    rate, markup = await get_settings()
    
    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 Курс USDT", callback_data="admin_rate")
    builder.button(text="📈 Наценка (₸)", callback_data="admin_markup")
    builder.button(text="🔙 В главное меню", callback_data="main_menu")
    builder.adjust(2, 1)
    
    await message.answer(
        f"👨‍💻 <b>Админ Панель</b>\n\n"
        f"Текущий курс: <b>1 USDT = {rate} ₸</b>\n"
        f"Наценка на аккаунты: <b>+{markup} ₸</b>",
        parse_mode="HTML", reply_markup=builder.as_markup()
    )

# Обработчик кнопки "Админ панель" из главного меню
@dp.callback_query(F.data == "admin_panel_open")
async def admin_panel_open_callback(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID: 
        return
    await state.clear()
    rate, markup = await get_settings()
    
    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 Курс USDT", callback_data="admin_rate")
    builder.button(text="📈 Наценка (₸)", callback_data="admin_markup")
    builder.button(text="🔙 В главное меню", callback_data="main_menu")
    builder.adjust(2, 1)
    
    await callback.message.edit_text(
        f"👨‍💻 <b>Админ Панель</b>\n\n"
        f"Текущий курс: <b>1 USDT = {rate} ₸</b>\n"
        f"Наценка на аккаунты: <b>+{markup} ₸</b>",
        parse_mode="HTML", reply_markup=builder.as_markup()
    )

@dp.callback_query(F.data == "admin_rate")
async def admin_set_rate(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID: return
    await state.set_state(AdminState.waiting_for_rate)
    await callback.message.edit_text("Введите новый курс (сколько тенге в 1 USDT):\n<i>Например: 495.5</i>", parse_mode="HTML")

@dp.message(AdminState.waiting_for_rate)
async def process_new_rate(message: Message, state: FSMContext):
    try:
        new_rate = float(message.text.replace(",", "."))
        await update_settings(rate=new_rate)
        await message.answer(f"✅ Курс обновлен: 1 USDT = {new_rate} ₸")
        await admin_panel(message, state)
    except ValueError:
        await message.answer("❌ Введите число!")

@dp.callback_query(F.data == "admin_markup")
async def admin_set_markup(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID: return
    await state.set_state(AdminState.waiting_for_markup)
    await callback.message.edit_text("Введите новую наценку в тенге:\n<i>Например: 50</i>", parse_mode="HTML")

@dp.message(AdminState.waiting_for_markup)
async def process_new_markup(message: Message, state: FSMContext):
    try:
        new_markup = float(message.text.replace(",", "."))
        await update_settings(markup=new_markup)
        await message.answer(f"✅ Наценка обновлена: +{new_markup} ₸")
        await admin_panel(message, state)
    except ValueError:
        await message.answer("❌ Введите число!")

# Start

@dp.message(Command("start"))
async def open_shop(message: Message, state: FSMContext):
    await state.clear()
    await send_main_menu(message, message.from_user.id)

@dp.callback_query(F.data == "main_menu")
async def back_to_main(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await send_main_menu(callback.message, callback.from_user.id, is_edit=True)

async def send_main_menu(message: Message, user_id: int, is_edit=False):
    builder = InlineKeyboardBuilder()
    builder.button(text="Мой баланс", callback_data="my_balance")
    builder.button(text="🛒 Купить аккаунт ТГ", callback_data="buy_settings")
    builder.button(text="Мои покупки", callback_data="my_purchases_0")
    builder.button(text="☁️ Поддержка", callback_data="support_menu")
    
    # Добавляем кнопку админ панели только для админа
    if user_id == ADMIN_ID:
        builder.button(text="👨‍💻 Админ Панель", callback_data="admin_panel_open")
        builder.adjust(1, 1, 2, 1)
    else:
        builder.adjust(1, 1, 2)
    
    text = "🛒 <b>NeoStore</b>\nДобро пожаловать! Выберите нужный раздел:"
    if is_edit:
        await message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())
    else:
        await message.answer(text, parse_mode="HTML", reply_markup=builder.as_markup())



@dp.callback_query(F.data == "support_menu")
async def support_menu(callback: CallbackQuery):
    builder = InlineKeyboardBuilder()
    builder.button(text="Написать в поддержку", url=f"https://t.me/{SUPPORT_USERNAME.replace('@', '')}")
    builder.button(text="🔙 Назад", callback_data="main_menu")
    builder.adjust(1)
    await callback.message.edit_text(
        f" <b>Поддержка</b>\n\nЕсли у вас возникли проблемы с аккаунтом или пополнением баланса, пишите нам: {SUPPORT_USERNAME}",
        parse_mode="HTML", reply_markup=builder.as_markup()
    )



@dp.callback_query(F.data == "my_balance")
async def show_balance(callback: CallbackQuery):
    balance = await get_balance(callback.from_user.id)
    rate, _ = await get_settings()
    
    builder = InlineKeyboardBuilder()
    builder.button(text="💵 Пополнить (USDT)", callback_data="topup_start")
    builder.button(text="🔙 Назад", callback_data="main_menu")
    builder.adjust(1)
    await callback.message.edit_text(
        f" <b>Ваш баланс:</b> {balance:.2f} ₸\n\n🔄 <i>Текущий курс пополнения: 1 USDT = {rate} ₸</i>",
        parse_mode="HTML", reply_markup=builder.as_markup()
    )

@dp.callback_query(F.data == "topup_start")
async def topup_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(TopUpState.waiting_for_amount)
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Отмена", callback_data="my_balance")
    await callback.message.edit_text(
        "Введите сумму для пополнения в долларах (USDT):", 
        reply_markup=builder.as_markup()
    )

@dp.message(TopUpState.waiting_for_amount)
async def process_topup_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(",", "."))
        if amount < 0.1:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите корректную сумму (минимум 0.1):")
        return

    await state.clear()
    msg = await message.answer("⏳ Создаю счет в CryptoBot...")

    async with aiohttp.ClientSession() as session:
        payload = {"asset": "USDT", "amount": str(amount)}
        async with session.post(f"{CRYPTO_API_BASE}/createInvoice", headers=CRYPTO_HEADERS, json=payload) as resp:
            result = await resp.json()
            if result.get("ok"):
                invoice_data = result["result"]
                invoice_id = invoice_data["invoice_id"]
                pay_url = invoice_data["pay_url"]

                async with aiosqlite.connect(DB_NAME) as db:
                    await db.execute("INSERT INTO invoices (invoice_id, user_id, amount) VALUES (?, ?, ?)",
                                     (invoice_id, message.from_user.id, amount))
                    await db.commit()

                builder = InlineKeyboardBuilder()
                builder.button(text="Оплатить счет 💸", url=pay_url)
                builder.button(text="🔄 Проверить оплату", callback_data=f"checkpay_{invoice_id}")
                builder.button(text="🔙 Назад", callback_data="my_balance")
                builder.adjust(1)

                await msg.edit_text(
                    f"🧾 <b>Счет на пополнение</b>\nСумма: <b>{amount} USDT</b>\n\nОплатите счет по кнопке ниже и нажмите «Проверить оплату».",
                    parse_mode="HTML", reply_markup=builder.as_markup()
                )
            else:
                await msg.edit_text("❌ Ошибка при создании счета. Проверьте токены.")

@dp.callback_query(F.data.startswith("checkpay_"))
async def check_payment(callback: CallbackQuery):
    invoice_id = int(callback.data.split("_")[1])
    
    async with aiohttp.ClientSession() as session:
        params = {"invoice_ids": invoice_id}
        async with session.get(f"{CRYPTO_API_BASE}/getInvoices", headers=CRYPTO_HEADERS, params=params) as resp:
            result = await resp.json()
            if result.get("ok") and result["result"]["items"]:
                invoice = result["result"]["items"][0]
                if invoice["status"] == "paid":
                    async with aiosqlite.connect(DB_NAME) as db:
                        async with db.execute("SELECT status, amount FROM invoices WHERE invoice_id = ?", (invoice_id,)) as cursor:
                            row = await cursor.fetchone()
                            if row and row[0] == "pending":
                                amount_usdt = row[1]
                                await db.execute("UPDATE invoices SET status = 'completed' WHERE invoice_id = ?", (invoice_id,))
                                await db.commit()
                                
                                rate, _ = await get_settings()
                                amount_kzt = amount_usdt * rate
                                
                                await add_balance(callback.from_user.id, amount_kzt)
                                await callback.answer(f"✅ Успешно! Начислено {amount_kzt:.2f} ₸", show_alert=True)
                                await show_balance(callback)
                                return
                    await callback.answer("Этот счет уже был зачислен.", show_alert=True)
                else:
                    await callback.answer("⏳ Счет еще не оплачен. Попробуйте чуть позже.", show_alert=True)
            else:
                await callback.answer("❌ Счет не найден.", show_alert=True)


# ГАЛОЧКИ)


@dp.callback_query(F.data == "buy_settings")
async def buy_settings_menu(callback: CallbackQuery):
    f = get_user_filters(callback.from_user.id)
    c_count = len(f["countries"])
    o_count = len(f["origins"])
    spam_txt = SPAM_MAP[f["spam"]]
    price_txt = "Любая цена 💸" if f["ignore_price"] else "Сначала дешевые 📉"

    builder = InlineKeyboardBuilder()
    builder.button(text=f"🌍 Страны (Выбрано: {c_count})", callback_data="set_countries")
    builder.button(text=f"🛡 Происхождение (Выбрано: {o_count})", callback_data="set_origins")
    builder.button(text=f"🚫 Спамблок: {spam_txt}", callback_data="toggle_spam")
    builder.button(text=f"💰 Цена: {price_txt}", callback_data="toggle_price")
    builder.button(text="🔎 Искать аккаунты", callback_data="execute_search_0")
    builder.button(text="🔙 Назад", callback_data="main_menu")
    builder.adjust(1, 1, 1, 1, 1, 1)

    await callback.message.edit_text(
        "⚙️ <b>Настройка поиска</b>\nОтметьте нужные фильтры перед поиском.",
        parse_mode="HTML", reply_markup=builder.as_markup()
    )

@dp.callback_query(F.data == "toggle_spam")
async def toggle_spam(callback: CallbackQuery):
    f = get_user_filters(callback.from_user.id)
    states = ["nomatter", "no", "yes"]
    f["spam"] = states[(states.index(f["spam"]) + 1) % len(states)]
    await buy_settings_menu(callback)

@dp.callback_query(F.data == "toggle_price")
async def toggle_price(callback: CallbackQuery):
    f = get_user_filters(callback.from_user.id)
    f["ignore_price"] = not f["ignore_price"]
    await buy_settings_menu(callback)

# --- ГАЛОЧКИ СТРАН ---
@dp.callback_query(F.data == "set_countries")
async def menu_set_countries(callback: CallbackQuery):
    f = get_user_filters(callback.from_user.id)
    builder = InlineKeyboardBuilder()
    
    for code, name in COUNTRY_MAP.items():
        mark = "✅ " if code in f["countries"] else ""
        builder.button(text=f"{mark}{name}", callback_data=f"tc_{code}")
        
    builder.button(text="🔙 Назад к настройкам", callback_data="buy_settings")
    builder.adjust(2)
    await callback.message.edit_text("🌍 <b>Выберите страны:</b>", parse_mode="HTML", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("tc_"))
async def toggle_country(callback: CallbackQuery):
    code = callback.data.split("_")[1]
    f = get_user_filters(callback.from_user.id)
    if code in f["countries"]: f["countries"].remove(code)
    else: f["countries"].append(code)
    await menu_set_countries(callback)


@dp.callback_query(F.data == "set_origins")
async def menu_set_origins(callback: CallbackQuery):
    f = get_user_filters(callback.from_user.id)
    builder = InlineKeyboardBuilder()
    
    for code, name in ORIGIN_MAP.items():
        mark = "✅ " if code in f["origins"] else ""
        builder.button(text=f"{mark}{name}", callback_data=f"to_{code}")
        
    builder.button(text="🔙 Назад к настройкам", callback_data="buy_settings")
    builder.adjust(2)
    await callback.message.edit_text("🛡 <b>Выберите происхождение:</b>", parse_mode="HTML", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("to_"))
async def toggle_origin(callback: CallbackQuery):
    code = callback.data.split("_")[1]
    f = get_user_filters(callback.from_user.id)
    if code in f["origins"]: f["origins"].remove(code)
    else: f["origins"].append(code)
    await menu_set_origins(callback)


# ВЫВОД РЕЗУЛЬТАТОВ ПОИСКА


@dp.callback_query(F.data.startswith("execute_search_"))
async def execute_search(callback: CallbackQuery):
    page = int(callback.data.split("_")[2])
    user_id = callback.from_user.id
    
    if page == 0 or user_id not in SEARCH_CACHE:
        await callback.message.edit_text("⏳ <b>Ищем подходящие аккаунты...</b>", parse_mode="HTML")
        items = await search_lzt_items(user_id)
        if items is None:
            await callback.message.edit_text(
                "❌ Лолз ограничил запросы (Rate Limit). Подождите пару минут.",
                reply_markup=InlineKeyboardBuilder().button(text="🔙 Назад", callback_data="buy_settings").as_markup()
            )
            return
    else:
        items = SEARCH_CACHE[user_id]

    if not items:
        await callback.message.edit_text(
            "🤷‍♂️ По вашим фильтрам ничего не найдено.",
            reply_markup=InlineKeyboardBuilder().button(text="🔙 Изменить фильтры", callback_data="buy_settings").as_markup()
        )
        return

    ITEMS_PER_PAGE = 8
    max_page = math.ceil(len(items) / ITEMS_PER_PAGE) - 1
    page = max(0, min(page, max_page))
    
    page_items = items[page * ITEMS_PER_PAGE : (page + 1) * ITEMS_PER_PAGE]

    rate, markup = await get_settings()

    builder = InlineKeyboardBuilder()
    for item in page_items:
        final_price_kzt = item['price'] + markup
        builder.row(InlineKeyboardButton(text=f"{item['description']} ({final_price_kzt:.2f} ₸)", callback_data=f"item_details_{item['id']}"))
    
    nav_buttons = []
    if page > 0: nav_buttons.append(InlineKeyboardButton(text="⬅️", callback_data=f"execute_search_{page - 1}"))
    if page < max_page: nav_buttons.append(InlineKeyboardButton(text="➡️", callback_data=f"execute_search_{page + 1}"))
    if nav_buttons: builder.row(*nav_buttons)
        
    builder.row(InlineKeyboardButton(text="⚙️ Фильтры", callback_data="buy_settings"))
    builder.row(InlineKeyboardButton(text="🔙 В главное меню", callback_data="main_menu"))
    
    await callback.message.edit_text(
        f"🔎 <b>Найдено аккаунтов:</b> {len(items)}\nСтраница {page + 1} из {max_page + 1}",
        parse_mode="HTML", reply_markup=builder.as_markup()
    )


# ДЕТАЛИ И ПОКУПКА


@dp.callback_query(F.data.startswith("item_details_"))
async def show_item_details(callback: CallbackQuery):
    item_id = callback.data.split("_")[2]
    user_id = callback.from_user.id
    items = SEARCH_CACHE.get(user_id, [])
    item = next((i for i in items if str(i["id"]) == str(item_id)), None)
    
    if not item:
        await callback.answer("Товар устарел или скрыт!", show_alert=True)
        return

    spam_val = item.get('spamblock', -1)
    if spam_val == 1: spam_text = "Есть 🚫"
    elif spam_val == 0: spam_text = "Нет ✅"
    else: spam_text = "Не проверено ❓"
    
    rate, markup = await get_settings()
    final_price_kzt = item['price'] + markup
    balance = await get_balance(user_id)

    text = (
        f"🔎 <b>Информация об аккаунте</b>\n\n"
        f"🏷 <b>Название:</b> {item['description']}\n"
        f"🌍 <b>Страна:</b> {item['country']}\n"
        f"🛡 <b>Происхождение:</b> {item['origin']}\n"
        f"🚫 <b>Спамблок:</b> {spam_text}\n\n"
        f"💵 <b>Цена продавца (без наценки):</b> {item['price']} ₸\n"
        f"💳 <b>К оплате с баланса:</b> {final_price_kzt:.2f} ₸\n"
        f"💰 <b>Твой баланс:</b> {balance:.2f} ₸\n\n"
    )

    builder = InlineKeyboardBuilder()
    if balance >= final_price_kzt:
        builder.button(text="✅ Купить", callback_data=f"execute_buy_{item_id}_{final_price_kzt}")
    else:
        builder.button(text="⚠️ Пополнить баланс", callback_data="my_balance")
        
    builder.button(text="🔙 Назад к списку", callback_data="execute_search_0")
    builder.adjust(1)
    
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("execute_buy_"))
async def execute_buy(callback: CallbackQuery):
    parts = callback.data.split("_")
    item_id = parts[2]
    final_price_kzt = float(parts[3])
    user_id = callback.from_user.id
    
    
    if not await deduct_balance(user_id, final_price_kzt):
        await callback.answer("❌ Недостаточно средств!", show_alert=True)
        return

    await callback.message.edit_text("⏳ <b>Стучимся в API Лолза... Оплачиваем...</b>", parse_mode="HTML")

    async with aiohttp.ClientSession() as session:
        try:
            items = SEARCH_CACHE.get(user_id, [])
            item = next((i for i in items if str(i["id"]) == str(item_id)), None)
            lzt_price = item["price"] if item else 0 
            
            payload = {"price": lzt_price, "buy_without_validation": 1}
            async with session.post(f"{API_BASE}/{item_id}/fast-buy", headers=LZT_HEADERS, data=payload) as response:
                result = await response.json()
                
                if "errors" in result:
                    
                    await add_balance(user_id, final_price_kzt)
                    err_msg = result['errors'][0] if isinstance(result['errors'], list) else result['errors']
                    await callback.message.edit_text(
                        f"❌ <b>Отказ от маркета:</b> {err_msg}\n<i>Баланс {final_price_kzt:.2f} ₸ возвращен.</i>", 
                        parse_mode="HTML", 
                        reply_markup=InlineKeyboardBuilder().button(text="🔙 Назад", callback_data="execute_search_0").as_markup()
                    )
                    return
                
                bought_item = result.get("item", {})
                real_phone = extract_phone_number(bought_item)
                item_title = item["description"] if item else "Telegram Account"
                
                async with aiosqlite.connect(DB_NAME) as db:
                    await db.execute(
                        "INSERT INTO purchases (user_id, item_id, title, phone) VALUES (?, ?, ?, ?)",
                        (user_id, str(item_id), item_title, real_phone)
                    )
                    await db.commit()
                
                builder = InlineKeyboardBuilder()
                builder.button(text="🔄 Получить код", callback_data=f"getcode_{item_id}")
                builder.row(InlineKeyboardButton(text="🗃 Мои покупки", callback_data="my_purchases_0"))
                builder.row(InlineKeyboardButton(text="🔙 В главное меню", callback_data="main_menu"))
                
                await callback.message.edit_text(
                    f"✅ <b>Успешно куплено! (ID: {item_id})</b>\n\n"
                    f"📱 <b>Номер для входа:</b> <code>{real_phone}</code>\n\n"
                    f"Вводи этот номер в Telegram. Как только отправишь запрос на код, жми кнопку ниже.",
                    parse_mode="HTML", reply_markup=builder.as_markup()
                )
        except Exception as e:
            await add_balance(user_id, final_price_kzt)
            logger.error(f"Execution error: {e}")
            await callback.message.edit_text("❌ Ошибка сети при оплате. Средства возвращены на внутренний баланс.")



@dp.callback_query(F.data.startswith("my_purchases_"))
async def my_purchases_list(callback: CallbackQuery):
    page = int(callback.data.split("_")[2])
    user_id = callback.from_user.id
    
    purchases = []
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT item_id, title, phone FROM purchases WHERE user_id = ?", (user_id,)) as cursor:
            rows = await cursor.fetchall()
            for row in rows:
                purchases.append({"id": row["item_id"], "title": row["title"], "phone": row["phone"]})
    
    if not purchases:
        builder = InlineKeyboardBuilder()
        builder.button(text="🔙 В меню", callback_data="main_menu")
        await callback.message.edit_text("🗃 У вас пока нет купленных аккаунтов.", reply_markup=builder.as_markup())
        return

    ITEMS_PER_PAGE = 10
    max_page = math.ceil(len(purchases) / ITEMS_PER_PAGE) - 1
    page = max(0, min(page, max_page))
    page_items = purchases[page * ITEMS_PER_PAGE : (page + 1) * ITEMS_PER_PAGE]

    builder = InlineKeyboardBuilder()
    for p in page_items:
        short_title = p['title'][:18] + "..." if len(p['title']) > 18 else p['title']
        builder.row(InlineKeyboardButton(text=f"🆔 {p['id']} | {short_title}", callback_data=f"view_purchase_{p['id']}"))

    nav_buttons = []
    if page > 0: nav_buttons.append(InlineKeyboardButton(text="⬅️", callback_data=f"my_purchases_{page - 1}"))
    if page < max_page: nav_buttons.append(InlineKeyboardButton(text="➡️", callback_data=f"my_purchases_{page + 1}"))
    if nav_buttons: builder.row(*nav_buttons)
        
    builder.row(InlineKeyboardButton(text="🔙 В главное меню", callback_data="main_menu"))
    await callback.message.edit_text(f"🗃 <b>Мои купленные аккаунты</b>\nСтраница {page + 1} из {max_page + 1}", parse_mode="HTML", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("view_purchase_"))
async def view_purchase(callback: CallbackQuery):
    item_id = callback.data.split("_")[2]
    user_id = callback.from_user.id
    
    purchase = None
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT item_id, title, phone FROM purchases WHERE user_id = ? AND item_id = ?", (user_id, str(item_id))) as cursor:
            row = await cursor.fetchone()
            if row:
                purchase = {"id": row["item_id"], "title": row["title"], "phone": row["phone"]}
    
    if not purchase:
        await callback.answer("Данные не найдены!", show_alert=True)
        return
        
    text = (
        f"🗃 <b>Карточка товара</b>\n\n"
        f"🆔 <b>ID Товара:</b> <code>{purchase['id']}</code>\n"
        f"🏷 <b>Имя товара:</b> {purchase['title']}\n"
        f"📱 <b>Номер телефона:</b> <code>{purchase['phone']}</code>\n\n"
        f"Запрашивайте код ниже."
    )
    
    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 Запросить код Telegram", callback_data=f"getcode_{item_id}")
    builder.button(text="🔙 К списку покупок", callback_data="my_purchases_0")
    builder.adjust(1)
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("getcode_"))
async def request_code_from_lzt(callback: CallbackQuery):
    item_id = callback.data.split("_")[1]
    await callback.answer("Тянем код...", show_alert=False)

    api_url = f"{PROD_API_BASE}/{item_id}/telegram-login-code" 

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(api_url, headers=LZT_HEADERS) as response:
                result = await response.json()
                
                if "codes" in result and isinstance(result["codes"], list) and len(result["codes"]) > 0:
                    code = result["codes"][0].get("code")
                    if code:
                        await callback.message.reply(f"🔐 <b>Код авторизации:</b> <code>{code}</code>", parse_mode="HTML")
                        return

                if "errors" in result:
                    err_msg = result['errors'][0] if isinstance(result['errors'], list) else result['errors']
                    await callback.message.reply(f"⏳ Ждем код (Ответ: <b>{err_msg}</b>). Отправь код в клиенте и попробуй снова.", parse_mode="HTML")
                else:
                    await callback.message.reply("⏳ Маркет пока не обнаружил новых кодов. Убедись, что отправил код в клиенте, подожди 5 секунд и нажми еще раз.", parse_mode="HTML")
                    
        except Exception as e:
            logger.error(f"Code fetch error: {e}")
            await callback.message.reply("❌ Ошибка соединения с API маркета.")


class CheckSubscriptionMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        user = data.get("event_from_user")
        if not user:
            return await handler(event, data)

        bot: Bot = data.get("bot")

        #  Проверка
        try:
            member = await bot.get_chat_member(chat_id=REQUIRED_CHANNEL, user_id=user.id)
            is_subbed = member.status in ["member", "administrator", "creator", "restricted"]
        except Exception:
            
            is_subbed = False

        if not is_subbed:
            builder = InlineKeyboardBuilder()
            builder.button(text="📢 Подписаться", url=CHANNEL_URL)
            builder.button(text="✅ Подтвердить", callback_data="check_sub_callback")
            builder.adjust(1)
            
            text = "❗️ <b>Для использования бота необходимо подписаться на наш канал!</b>"
            
            if isinstance(event, Message):
                await event.answer(text, parse_mode="HTML", reply_markup=builder.as_markup())
            elif isinstance(event, CallbackQuery):
                if event.data == "check_sub_callback":
                    await event.answer("❌ Вы еще не подписались на канал!", show_alert=True)
                else:
                    await event.message.answer(text, parse_mode="HTML", reply_markup=builder.as_markup())
                    await event.answer()
            
            return 
        
        
        if isinstance(event, CallbackQuery) and event.data == "check_sub_callback":
            await event.message.delete()
            await send_main_menu(event.message, user.id, is_edit=False)
            return
            
        return await handler(event, data)



# ЗАПУСК

async def main():
    await init_db()
    
    # Middlewar
    dp.message.middleware(CheckSubscriptionMiddleware())
    dp.callback_query.middleware(CheckSubscriptionMiddleware())
    
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
