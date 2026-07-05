import logging
import sqlite3
import random
import string
import asyncio
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, LabeledPrice
from aiogram.filters import Command

API_TOKEN = '8663984903:AAGKuNOjEEArgkKQtsIRBGW8dAtVipx_HGg'
ADMIN_IDS = [8251761249, 7799646371, 8734624959]

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
dp = Dispatcher()
dp['captcha_waiting'] = {}
dp['waiting_for_promo'] = {}
dp['last_video_for_user'] = {}

conn = sqlite3.connect('users.db', check_same_thread=False)
cursor = conn.cursor()

# --- ТАБЛИЦЫ ---
cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        coins INTEGER DEFAULT 0,
        referrer_id INTEGER,
        total_earned INTEGER DEFAULT 0,
        total_videos INTEGER DEFAULT 0,
        last_bonus TEXT,
        pending_captcha TEXT,
        pending_referrer INTEGER,
        premium_until TEXT
    )
''')
cursor.execute('''
    CREATE TABLE IF NOT EXISTS referrals (
        code TEXT PRIMARY KEY,
        user_id INTEGER,
        uses INTEGER DEFAULT 0
    )
''')
cursor.execute('''
    CREATE TABLE IF NOT EXISTS videos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        url TEXT UNIQUE,
        price INTEGER DEFAULT 2,
        is_active INTEGER DEFAULT 1
    )
''')
cursor.execute('''
    CREATE TABLE IF NOT EXISTS promocodes (
        code TEXT PRIMARY KEY,
        reward_coins INTEGER DEFAULT 0,
        reward_premium_days INTEGER DEFAULT 0,
        reward_stars INTEGER DEFAULT 0,
        max_uses INTEGER DEFAULT 1,
        used_count INTEGER DEFAULT 0,
        created_by INTEGER
    )
''')
cursor.execute('''
    CREATE TABLE IF NOT EXISTS promo_uses (
        user_id INTEGER,
        code TEXT,
        used_at TEXT,
        PRIMARY KEY (user_id, code)
    )
''')
cursor.execute('''
    CREATE TABLE IF NOT EXISTS user_tasks (
        user_id INTEGER PRIMARY KEY,
        submitted_count INTEGER DEFAULT 0,
        approved_count INTEGER DEFAULT 0,
        task_completed INTEGER DEFAULT 0,
        last_task_start TEXT
    )
''')
cursor.execute('''
    CREATE TABLE IF NOT EXISTS pending_screenshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        file_id TEXT,
        message_id INTEGER,
        timestamp TEXT
    )
''')
conn.commit()

# --- ВИДЕО (1-100) ---
def add_videos_if_empty():
    cursor.execute('SELECT COUNT(*) FROM videos')
    if cursor.fetchone()[0] == 0:
        video_urls = [f"https://t.me/avakadotomrcsiko/{i}" for i in range(1, 101)]
        for url in video_urls:
            cursor.execute('INSERT OR IGNORE INTO videos (url, price) VALUES (?, ?)', (url, 2))
        conn.commit()
        print(f"[VIDEO] Добавлено {len(video_urls)} видео")
    else:
        print("[VIDEO] Видео уже есть")

add_videos_if_empty()

# --- КЛАВИАТУРЫ ---
def get_main_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎬 Купить видео (2🪙)", callback_data="buy_video")],
        [InlineKeyboardButton(text="👥 Пригласить друга", callback_data="invite"),
         InlineKeyboardButton(text="⭐ Купить коины", callback_data="buy_coins")],
        [InlineKeyboardButton(text="🎁 Бонус (+6🪙/12ч)", callback_data="daily_bonus"),
         InlineKeyboardButton(text="💰 Баланс", callback_data="balance")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="stats"),
         InlineKeyboardButton(text="👑 Премиум", callback_data="premium")],
        [InlineKeyboardButton(text="🎫 Промокод", callback_data="promo_code"),
         InlineKeyboardButton(text="💰 Заработать", callback_data="earn")]
    ])

def get_premium_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💎 Купить премиум за 300⭐", callback_data="buy_premium")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")]
    ])

def get_buy_coins_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ 30 коинов (15⭐)", callback_data="buy_coins_30")],
        [InlineKeyboardButton(text="⭐ 60 коинов (30⭐)", callback_data="buy_coins_60")],
        [InlineKeyboardButton(text="⭐ 100 коинов (50⭐)", callback_data="buy_coins_100")],
        [InlineKeyboardButton(text="⭐ 500 коинов (250⭐)", callback_data="buy_coins_500")],
        [InlineKeyboardButton(text="⭐ 1000 коинов (500⭐)", callback_data="buy_coins_1000")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")]
    ])

# --- ФУНКЦИИ ДЛЯ ПРОМОКОДОВ ---
def create_promo_code(code, reward_coins=0, reward_premium_days=0, reward_stars=0, max_uses=1, admin_id=0):
    try:
        cursor.execute('''
            INSERT INTO promocodes (code, reward_coins, reward_premium_days, reward_stars, max_uses, used_count, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (code, reward_coins, reward_premium_days, reward_stars, max_uses, 0, admin_id))
        conn.commit()
        return True, "✅ Промокод создан!"
    except sqlite3.IntegrityError:
        return False, "❌ Промокод с таким названием уже существует."

def activate_promo_code(user_id, code):
    cursor.execute('SELECT reward_coins, reward_premium_days, reward_stars, max_uses, used_count FROM promocodes WHERE code = ?', (code,))
    promo = cursor.fetchone()
    if not promo:
        return False, "❌ Промокод не найден"
    
    reward_coins, reward_premium_days, reward_stars, max_uses, used_count = promo
    if used_count >= max_uses:
        return False, "❌ Промокод уже использован максимальное количество раз"
    
    cursor.execute('SELECT 1 FROM promo_uses WHERE user_id = ? AND code = ?', (user_id, code))
    if cursor.fetchone():
        return False, "❌ Ты уже использовал этот промокод"
    
    msg_parts = []
    user_msg = ""
    if reward_coins > 0:
        cursor.execute('UPDATE users SET coins = coins + ? WHERE user_id = ?', (reward_coins, user_id))
        msg_parts.append(f"💰 {reward_coins} коинов")
    if reward_premium_days > 0:
        set_premium(user_id, reward_premium_days)
        msg_parts.append(f"👑 {reward_premium_days} дней премиума")
        user_msg += f"\n👑 Вам выдан премиум на {reward_premium_days} дней!"
    if reward_stars > 0:
        cursor.execute('UPDATE users SET coins = coins + ? WHERE user_id = ?', (reward_stars * 2, user_id))
        msg_parts.append(f"⭐ {reward_stars} звёзд")
    
    cursor.execute('INSERT INTO promo_uses (user_id, code, used_at) VALUES (?, ?, ?)',
                   (user_id, code, datetime.now().isoformat()))
    cursor.execute('UPDATE promocodes SET used_count = used_count + 1 WHERE code = ?', (code,))
    conn.commit()
    
    if msg_parts:
        msg = "✅ *Промокод активирован!*\n\nТы получил:\n" + "\n".join(msg_parts) + user_msg
    else:
        msg = "✅ Промокод активирован, но награда не найдена."
    return True, msg

# --- ФУНКЦИИ ДЛЯ ПРЕМИУМ (АДМИН) ---
def give_premium_to_user(target_id, days):
    set_premium(target_id, days)
    try:
        bot.send_message(target_id, f"👑 *Вам выдан премиум на {days} дней!*\n\nДействует до: {(datetime.now() + timedelta(days=days)).strftime('%d.%m.%Y')}", parse_mode='Markdown')
    except:
        pass
    return True

def remove_premium_from_user(target_id):
    cursor.execute('UPDATE users SET premium_until = NULL WHERE user_id = ?', (target_id,))
    conn.commit()
    try:
        bot.send_message(target_id, "❌ *Ваш премиум был снят администратором.*", parse_mode='Markdown')
    except:
        pass
    return True

# --- ФУНКЦИИ (ОСНОВНЫЕ) ---
def is_premium(user_id):
    cursor.execute('SELECT premium_until FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    if row and row[0]:
        return datetime.fromisoformat(row[0]) > datetime.now()
    return False

def set_premium(user_id, days=30):
    until = (datetime.now() + timedelta(days=days)).isoformat()
    cursor.execute('UPDATE users SET premium_until = ? WHERE user_id = ?', (until, user_id))
    conn.commit()

def update_coins(user_id, amount):
    cursor.execute('UPDATE users SET coins = coins + ? WHERE user_id = ?', (amount, user_id))
    conn.commit()

def spend_coins(user_id, amount):
    cursor.execute('UPDATE users SET coins = coins - ? WHERE user_id = ?', (amount, user_id))
    conn.commit()

def add_video_watched(user_id):
    cursor.execute('UPDATE users SET total_videos = total_videos + 1 WHERE user_id = ?', (user_id,))
    conn.commit()

def get_random_video_except_last(user_id):
    cursor.execute('SELECT url, price FROM videos WHERE is_active = 1')
    all_videos = cursor.fetchall()
    if not all_videos:
        return None
    last_url = dp['last_video_for_user'].get(user_id)
    candidates = [v for v in all_videos if v[0] != last_url]
    if not candidates:
        candidates = all_videos
    selected = random.choice(candidates)
    dp['last_video_for_user'][user_id] = selected[0]
    return selected

def get_referral_code(user_id):
    cursor.execute('SELECT code FROM referrals WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    if result:
        return result[0]
    while True:
        code = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
        cursor.execute('SELECT code FROM referrals WHERE code = ?', (code,))
        if not cursor.fetchone():
            cursor.execute('INSERT INTO referrals (code, user_id) VALUES (?, ?)', (code, user_id))
            conn.commit()
            return code

def get_user(user_id):
    cursor.execute('SELECT coins, total_earned, total_videos, referrer_id, last_bonus, premium_until FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    if row:
        return {
            'coins': row[0],
            'total_earned': row[1],
            'total_videos': row[2],
            'referrer_id': row[3],
            'last_bonus': row[4],
            'premium_until': row[5]
        }
    return None

def can_claim_bonus(user_id):
    cursor.execute('SELECT last_bonus FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    if not row or not row[0]:
        return True
    last = datetime.fromisoformat(row[0])
    return datetime.now() - last >= timedelta(hours=12)

def claim_bonus(user_id):
    now = datetime.now().isoformat()
    cursor.execute('UPDATE users SET coins = coins + 6, last_bonus = ? WHERE user_id = ?', (now, user_id))
    conn.commit()

def get_next_bonus_time(user_id):
    cursor.execute('SELECT last_bonus FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    if not row or not row[0]:
        return None
    last = datetime.fromisoformat(row[0])
    return last + timedelta(hours=12)

def generate_captcha():
    a = random.randint(1, 10)
    b = random.randint(1, 10)
    return f"{a}+{b}", a + b

def register_user(user_id, referrer_code=None):
    cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    if cursor.fetchone():
        return None
    captcha, answer = generate_captcha()
    referrer_id = None
    if referrer_code:
        cursor.execute('SELECT user_id FROM referrals WHERE code = ?', (referrer_code,))
        ref = cursor.fetchone()
        if ref:
            referrer_id = ref[0]
    cursor.execute('''
        INSERT INTO users (user_id, coins, referrer_id, pending_captcha, pending_referrer)
        VALUES (?, ?, ?, ?, ?)
    ''', (user_id, 0, referrer_id, captcha, referrer_id))
    conn.commit()
    return {'captcha': captcha, 'answer': answer, 'referrer_id': referrer_id}

def process_captcha(user_id, user_answer):
    cursor.execute('SELECT pending_captcha, pending_referrer FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    if not row or not row[0]:
        return None
    captcha_str = row[0]
    referrer_id = row[1]
    expected = eval(captcha_str)
    if int(user_answer) == expected:
        cursor.execute('UPDATE users SET coins = 10, pending_captcha = NULL WHERE user_id = ?', (user_id,))
        if referrer_id and referrer_id != 0:
            cursor.execute('UPDATE users SET coins = coins + 8, total_earned = total_earned + 8 WHERE user_id = ?', (referrer_id,))
            cursor.execute('UPDATE referrals SET uses = uses + 1 WHERE user_id = ?', (referrer_id,))
        conn.commit()
        return True
    return False

# --- ЗАДАНИЯ ---
def start_task(user_id):
    cursor.execute('SELECT task_completed FROM user_tasks WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    if row and row[0] == 1:
        cursor.execute('UPDATE user_tasks SET submitted_count = 0, approved_count = 0, task_completed = 0, last_task_start = ? WHERE user_id = ?', (datetime.now().isoformat(), user_id))
    elif row:
        submitted, approved = cursor.execute('SELECT submitted_count, approved_count FROM user_tasks WHERE user_id = ?', (user_id,)).fetchone()
        if submitted > 0:
            return False, f"У тебя уже есть активное задание. Отправлено: {submitted}/10, одобрено: {approved}/10"
        else:
            cursor.execute('UPDATE user_tasks SET submitted_count = 0, approved_count = 0, task_completed = 0, last_task_start = ? WHERE user_id = ?', (datetime.now().isoformat(), user_id))
    else:
        cursor.execute('INSERT INTO user_tasks (user_id, submitted_count, approved_count, task_completed, last_task_start) VALUES (?, 0, 0, 0, ?)', (user_id, datetime.now().isoformat()))
    conn.commit()
    return True, "Задание начато! Отправляй скриншоты по одному. Нужно 10 одобренных."

def add_screenshot(user_id, file_id, message_id):
    cursor.execute('UPDATE user_tasks SET submitted_count = submitted_count + 1 WHERE user_id = ?', (user_id,))
    cursor.execute('INSERT INTO pending_screenshots (user_id, file_id, message_id, timestamp) VALUES (?, ?, ?, ?)',
                   (user_id, file_id, message_id, datetime.now().isoformat()))
    conn.commit()
    cursor.execute('SELECT submitted_count FROM user_tasks WHERE user_id = ?', (user_id,))
    return cursor.fetchone()[0]

def approve_screenshot(screenshot_id):
    cursor.execute('SELECT user_id FROM pending_screenshots WHERE id = ?', (screenshot_id,))
    row = cursor.fetchone()
    if not row:
        return None
    user_id = row[0]
    cursor.execute('UPDATE user_tasks SET approved_count = approved_count + 1 WHERE user_id = ?', (user_id,))
    cursor.execute('DELETE FROM pending_screenshots WHERE id = ?', (screenshot_id,))
    conn.commit()
    cursor.execute('SELECT submitted_count, approved_count FROM user_tasks WHERE user_id = ?', (user_id,))
    submitted, approved = cursor.fetchone()
    if approved >= 10:
        cursor.execute('UPDATE user_tasks SET task_completed = 1 WHERE user_id = ?', (user_id,))
        update_coins(user_id, 30)
        conn.commit()
        return user_id, True, submitted, approved
    return user_id, False, submitted, approved

def reject_screenshot(screenshot_id):
    cursor.execute('SELECT user_id FROM pending_screenshots WHERE id = ?', (screenshot_id,))
    row = cursor.fetchone()
    if row:
        user_id = row[0]
        cursor.execute('UPDATE user_tasks SET submitted_count = submitted_count - 1 WHERE user_id = ?', (user_id,))
        cursor.execute('DELETE FROM pending_screenshots WHERE id = ?', (screenshot_id,))
        conn.commit()
        cursor.execute('SELECT submitted_count, approved_count FROM user_tasks WHERE user_id = ?', (user_id,))
        submitted, approved = cursor.fetchone()
        return user_id, submitted, approved
    return None

def get_task_status(user_id):
    cursor.execute('SELECT submitted_count, approved_count, task_completed FROM user_tasks WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    if row:
        return row[0], row[1], row[2]
    return 0, 0, 0

# --- ОБРАБОТЧИКИ ---
@dp.message(Command('start'))
async def start(message: types.Message):
    args = message.text.split()
    referrer_code = args[1] if len(args) > 1 else None
    user_id = message.from_user.id
    user = get_user(user_id)
    if user:
        await message.answer("✨ *Ты уже с нами!*", reply_markup=get_main_keyboard(), parse_mode='Markdown')
        return
    result = register_user(user_id, referrer_code)
    if result and 'captcha' in result:
        await message.answer(
            f"🔐 *Добро пожаловать!*\nРеши пример:\n\n{result['captcha']} = ?\n\nОтправь число.",
            parse_mode='Markdown'
        )
        dp['captcha_waiting'][user_id] = result['answer']

# --- КОМАНДА ДЛЯ АДМИНА (СОЗДАНИЕ ПРОМОКОДА) ---
@dp.message(Command('add_promo'))
async def add_promo_command(message: types.Message):
    user_id = message.from_user.id
    if user_id not in ADMIN_IDS:
        await message.answer("❌ У вас нет прав на создание промокодов.")
        return
    
    args = message.text.split()
    if len(args) < 2:
        await message.answer(
            "📝 *Формат команды:*\n"
            "`/add_promo код [coins=0] [premium_days=0] [stars=0] [max_uses=1]`\n\n"
            "Примеры:\n"
            "`/add_promo FREE1000 1000 0 0 100` — 1000 коинов, 100 использований\n"
            "`/add_promo PREMIUM30 0 30 0 50` — 30 дней премиума, 50 использований",
            parse_mode='Markdown'
        )
        return
    
    try:
        code = args[1].strip().upper()
        coins = int(args[2]) if len(args) > 2 else 0
        premium_days = int(args[3]) if len(args) > 3 else 0
        stars = int(args[4]) if len(args) > 4 else 0
        max_uses = int(args[5]) if len(args) > 5 else 1
    except ValueError:
        await message.answer("❌ Все аргументы должны быть числами (кроме кода).")
        return
    
    cursor.execute('SELECT code FROM promocodes WHERE code = ?', (code,))
    if cursor.fetchone():
        await message.answer(f"❌ Промокод `{code}` уже существует.", parse_mode='Markdown')
        return
    
    cursor.execute('''
        INSERT INTO promocodes (code, reward_coins, reward_premium_days, reward_stars, max_uses, used_count, created_by)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (code, coins, premium_days, stars, max_uses, 0, user_id))
    conn.commit()
    
    await message.answer(
        f"✅ *Промокод создан!*\n\n"
        f"📌 Код: `{code}`\n"
        f"💰 Коины: {coins}\n"
        f"👑 Премиум: {premium_days} дней\n"
        f"⭐ Звёзды: {stars}\n"
        f"🔢 Макс. использований: {max_uses}\n"
        f"👤 Создал: `{user_id}`",
        parse_mode='Markdown'
    )

# --- КОМАНДА ДЛЯ АДМИНА (ВЫДАТЬ ПРЕМИУМ) ---
@dp.message(Command('give_premium'))
async def give_premium_command(message: types.Message):
    user_id = message.from_user.id
    if user_id not in ADMIN_IDS:
        await message.answer("❌ У вас нет прав.")
        return
    
    args = message.text.split()
    if len(args) < 3:
        await message.answer(
            "📝 *Формат команды:*\n"
            "`/give_premium user_id days`\n\n"
            "Пример:\n"
            "`/give_premium 123456789 30` — выдаст 30 дней премиума пользователю с ID 123456789",
            parse_mode='Markdown'
        )
        return
    
    try:
        target_id = int(args[1])
        days = int(args[2])
    except ValueError:
        await message.answer("❌ ID и количество дней должны быть числами.")
        return
    
    target_user = get_user(target_id)
    if not target_user:
        await message.answer(f"❌ Пользователь с ID `{target_id}` не найден в базе.", parse_mode='Markdown')
        return
    
    give_premium_to_user(target_id, days)
    await message.answer(
        f"✅ *Премиум выдан!*\n"
        f"Пользователь: `{target_id}`\n"
        f"Дней: {days}\n"
        f"Действует до: {(datetime.now() + timedelta(days=days)).strftime('%d.%m.%Y')}",
        parse_mode='Markdown'
    )

# --- КОМАНДА ДЛЯ АДМИНА (ЗАБРАТЬ ПРЕМИУМ) ---
@dp.message(Command('remove_premium'))
async def remove_premium_command(message: types.Message):
    user_id = message.from_user.id
    if user_id not in ADMIN_IDS:
        await message.answer("❌ У вас нет прав.")
        return
    
    args = message.text.split()
    if len(args) < 2:
        await message.answer(
            "📝 *Формат команды:*\n"
            "`/remove_premium user_id`\n\n"
            "Пример:\n"
            "`/remove_premium 123456789` — снимает премиум с пользователя",
            parse_mode='Markdown'
        )
        return
    
    try:
        target_id = int(args[1])
    except ValueError:
        await message.answer("❌ ID должен быть числом.")
        return
    
    target_user = get_user(target_id)
    if not target_user:
        await message.answer(f"❌ Пользователь с ID `{target_id}` не найден в базе.", parse_mode='Markdown')
        return
    
    if not target_user['premium_until']:
        await message.answer(f"❌ У пользователя `{target_id}` нет активного премиума.", parse_mode='Markdown')
        return
    
    remove_premium_from_user(target_id)
    await message.answer(
        f"✅ *Премиум снят!*\n"
        f"Пользователь: `{target_id}`\n"
        f"Премиум был активен до: {datetime.fromisoformat(target_user['premium_until']).strftime('%d.%m.%Y')}",
        parse_mode='Markdown'
    )

@dp.message()
async def captcha_or_promo_or_screenshot_handler(message: types.Message):
    user_id = message.from_user.id
    if dp['waiting_for_promo'].get(user_id):
        code = message.text.strip().upper()
        del dp['waiting_for_promo'][user_id]
        success, msg = activate_promo_code(user_id, code)
        await message.answer(msg, parse_mode='Markdown', reply_markup=get_main_keyboard())
        return
    if dp['captcha_waiting'].get(user_id):
        try:
            answer = int(message.text.strip())
            expected = dp['captcha_waiting'][user_id]
            if answer == expected:
                del dp['captcha_waiting'][user_id]
                if process_captcha(user_id, answer):
                    await message.answer(
                        "✅ *Регистрация завершена!*\n\n🎁 Ты получил 10 коинов.\n👥 Твой друг получил 8 коинов.\n\n👇 Меню:",
                        reply_markup=get_main_keyboard(), parse_mode='Markdown'
                    )
                else:
                    await message.answer("❌ Ошибка. Напиши /start заново.")
            else:
                await message.answer("❌ Неправильно. Попробуй ещё раз.")
        except ValueError:
            await message.answer("❌ Отправь число.")
        return
    if message.photo or message.document:
        submitted, approved, completed = get_task_status(user_id)
        if completed == 1:
            await message.answer("У тебя уже выполнено задание. Нажми «💰 Заработать» снова, чтобы начать новое.")
            return
        if submitted >= 10:
            await message.answer(f"Ты уже отправил {submitted} скриншотов. Ожидай проверки админом.")
            return
        if message.photo:
            file_id = message.photo[-1].file_id
        else:
            file_id = message.document.file_id
        new_submitted = add_screenshot(user_id, file_id, message.message_id)
        cursor.execute('SELECT id FROM pending_screenshots WHERE user_id = ? ORDER BY timestamp DESC LIMIT 1', (user_id,))
        scr_id = cursor.fetchone()[0]
        caption = f"📸 Новый скриншот от пользователя {user_id}\nПрогресс: отправлено {new_submitted}/10, одобрено {approved}/10"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Одобрить", callback_data=f"approve_{scr_id}"),
             InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{scr_id}")]
        ])
        if message.photo:
            await bot.send_photo(ADMIN_IDS[0], photo=file_id, caption=caption, reply_markup=keyboard)
        else:
            await bot.send_document(ADMIN_IDS[0], document=file_id, caption=caption, reply_markup=keyboard)
        await message.answer(f"✅ Скриншот {new_submitted}/10 отправлен на проверку. Ожидай одобрения админом.")
        return

# --- ОСТАЛЬНЫЕ ОБРАБОТЧИКИ (КНОПКИ) ---
@dp.callback_query(lambda c: c.data == "earn")
async def earn_callback(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    user = get_user(user_id)
    if not user:
        await callback.message.edit_text("Ошибка. Напиши /start")
        await callback.answer()
        return
    submitted, approved, completed = get_task_status(user_id)
    if completed == 1:
        await callback.message.edit_text(
            "📋 *Задание уже выполнено!*\n\nТы уже получил 30 коинов. Нажми кнопку ниже, чтобы начать новое задание.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔄 Начать новое задание", callback_data="start_new_task")]]),
            parse_mode='Markdown'
        )
        await callback.answer()
        return
    if submitted > 0:
        await callback.message.edit_text(
            f"📋 *Твой прогресс:*\nОтправлено скриншотов: {submitted}/10\nОдобрено админом: {approved}/10\n\nПродолжай отправлять скриншоты.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")]]),
            parse_mode='Markdown'
        )
        await callback.answer()
        return
    success, msg = start_task(user_id)
    if not success:
        await callback.message.edit_text(msg, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")]]), parse_mode='Markdown')
        await callback.answer()
        return
    instruction = (
        "💰 *Как заработать 30 коинов?*\n\n"
        "1. Зайди в TikTok\n"
        "2. В поиске напиши: *Детское Питание*\n"
        "3. Под любым видео оставь комментарий:\n"
        "   `@pizdafdsfsd3_bot РИЛ ДАЛИ 😂`\n"
        "4. Поставь лайк своему комментарию\n"
        "5. Сделай скриншот (видно комментарий, лайк и что это TikTok)\n\n"
        "📌 *Нужно 10 таких скриншотов!*\n\n"
        "Отправляй скриншоты по одному в этот чат.\nПосле проверки админом ты получишь 30 коинов."
    )
    await callback.message.edit_text(instruction, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")]]), parse_mode='Markdown')
    await callback.answer()

@dp.callback_query(lambda c: c.data == "start_new_task")
async def start_new_task_callback(callback: types.CallbackQuery):
    start_task(callback.from_user.id)
    await earn_callback(callback)

@dp.callback_query(lambda c: c.data.startswith("approve_"))
async def approve_screenshot_callback(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("У вас нет прав.", show_alert=True)
        return
    screenshot_id = int(callback.data.split('_')[1])
    result = approve_screenshot(screenshot_id)
    if not result:
        await callback.message.edit_text("❌ Скриншот уже обработан или не найден.")
        await callback.answer()
        return
    user_id, completed, submitted, approved = result
    await callback.message.edit_text(f"✅ Скриншот одобрен. Прогресс пользователя {user_id}: отправлено {submitted}/10, одобрено {approved}/10")
    if completed:
        await bot.send_message(user_id, "🎉 *Поздравляем!*\n\nТы выполнил задание и получил 30 коинов! Можешь начать новое задание, нажав «💰 Заработать».", parse_mode='Markdown', reply_markup=get_main_keyboard())
    else:
        await bot.send_message(user_id, f"✅ Один скриншот одобрен. Прогресс: отправлено {submitted}/10, одобрено {approved}/10. Продолжай отправлять скриншоты.", reply_markup=get_main_keyboard())
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("reject_"))
async def reject_screenshot_callback(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("У вас нет прав.", show_alert=True)
        return
    screenshot_id = int(callback.data.split('_')[1])
    result = reject_screenshot(screenshot_id)
    if not result:
        await callback.message.edit_text("❌ Скриншот не найден.")
        await callback.answer()
        return
    user_id, submitted, approved = result
    await callback.message.edit_text(f"❌ Скриншот отклонён. Пользователь {user_id} может отправить новый. Прогресс: отправлено {submitted}/10, одобрено {approved}/10")
    await bot.send_message(user_id, f"❌ Твой скриншот не прошёл проверку. Отправь новый, соответствующий инструкции. Прогресс: отправлено {submitted}/10, одобрено {approved}/10.", reply_markup=get_main_keyboard())
    await callback.answer()

@dp.callback_query(lambda c: c.data == "buy_video")
async def buy_video(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    user = get_user(user_id)
    if not user:
        await callback.message.edit_text("Ошибка. Напиши /start")
        await callback.answer()
        return
    if not is_premium(user_id) and user['coins'] < 2:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👥 Пригласить друга", callback_data="invite")],
            [InlineKeyboardButton(text="⭐ Купить коины", callback_data="buy_coins")],
            [InlineKeyboardButton(text="👑 Купить премиум", callback_data="premium")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")]
        ])
        await callback.message.edit_text(
            f"❌ Не хватает коинов! Баланс: {user['coins']} 🪙\n1 видео = 2 🪙\nПригласи друга или купи коины.",
            reply_markup=keyboard, parse_mode='Markdown'
        )
        await callback.answer()
        return
    video = get_random_video_except_last(user_id)
    if not video:
        await callback.message.edit_text("❌ Видео пока нет. Попробуй позже.")
        await callback.answer()
        return
    video_url, price = video
    if not is_premium(user_id):
        spend_coins(user_id, price)
        add_video_watched(user_id)
    user = get_user(user_id)
    new_balance = user['coins']
    total_watched = user['total_videos']
    try:
        await bot.send_video(
            chat_id=user_id,
            video=video_url,
            caption=f"📊 *Просмотрено:* {total_watched} видео\n"
                    f"💸 Списано: {price if not is_premium(user_id) else 0} 🪙\n"
                    f"💰 Осталось: {new_balance} 🪙",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🎬 Ещё видео", callback_data="buy_video")],
                [InlineKeyboardButton(text="💰 Баланс", callback_data="balance")],
                [InlineKeyboardButton(text="◀️ Главное меню", callback_data="back_to_menu")]
            ])
        )
    except Exception:
        if not is_premium(user_id):
            update_coins(user_id, price)
            cursor.execute('UPDATE users SET total_videos = total_videos - 1 WHERE user_id = ?', (user_id,))
            conn.commit()
        await callback.message.edit_text(
            "❌ Не удалось загрузить видео. Коины возвращены. Попробуй позже.",
            reply_markup=get_main_keyboard(), parse_mode='Markdown'
        )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "invite")
async def invite(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    code = get_referral_code(user_id)
    bot_username = (await bot.get_me()).username
    invite_link = f"https://t.me/{bot_username}?start={code}"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Поделиться", url=f"https://t.me/share/url?url={invite_link}&text=Привет! Переходи по ссылке и получи 10 коинов! 🎁")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")]
    ])
    await callback.message.edit_text(
        f"👥 *Твоя реферальная ссылка:*\n`{invite_link}`\n\nПригласи друга → +8 🪙 (после капчи)\nДруг получит +10 🪙",
        reply_markup=keyboard, parse_mode='Markdown'
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "buy_coins")
async def buy_coins_menu(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "⭐ *Покупка коинов*\n1 коин = 0.5 Stars\n30-1000 коинов\nВыбери:",
        reply_markup=get_buy_coins_keyboard(), parse_mode='Markdown'
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("buy_coins_"))
async def buy_coins(callback: types.CallbackQuery):
    amount = int(callback.data.split('_')[2])
    stars = amount // 2
    await bot.send_invoice(
        chat_id=callback.from_user.id,
        title=f"{amount} коинов",
        description=f"{amount} коинов для видео",
        payload=f"coins_{amount}",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label=f"{amount} коинов", amount=stars)],
        start_parameter="buy_coins"
    )
    await callback.answer()

@dp.pre_checkout_query()
async def pre_checkout(pre_checkout_query: types.PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@dp.message(lambda m: m.successful_payment)
async def successful_payment(message: types.Message):
    user_id = message.from_user.id
    payload = message.successful_payment.invoice_payload
    if payload.startswith("premium"):
        set_premium(user_id, 30)
        update_coins(user_id, 50)
        await message.answer("👑 Премиум активирован на 30 дней! +50 коинов.", reply_markup=get_main_keyboard(), parse_mode='Markdown')
    elif payload.startswith("coins"):
        coins = int(payload.split('_')[1])
        update_coins(user_id, coins)
        user = get_user(user_id)
        await message.answer(f"✅ Куплено {coins} коинов. Баланс: {user['coins']} 🪙", reply_markup=get_main_keyboard(), parse_mode='Markdown')

@dp.callback_query(lambda c: c.data == "premium")
async def premium_menu(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if is_premium(user_id):
        until = datetime.fromisoformat(get_user(user_id)['premium_until']).strftime('%d.%m.%Y')
        await callback.message.edit_text(f"👑 Премиум активен до {until}", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")]]), parse_mode='Markdown')
    else:
        await callback.message.edit_text("👑 Премиум 300⭐ → безлимит +50🪙 в подарок", reply_markup=get_premium_keyboard(), parse_mode='Markdown')
    await callback.answer()

@dp.callback_query(lambda c: c.data == "buy_premium")
async def buy_premium(callback: types.CallbackQuery):
    await bot.send_invoice(
        chat_id=callback.from_user.id,
        title="Премиум 30 дней",
        description="Безлимит +50 коинов",
        payload="premium_30days",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label="Премиум", amount=300)],
        start_parameter="premium"
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "balance")
async def balance(callback: types.CallbackQuery):
    user = get_user(callback.from_user.id)
    if not user:
        await callback.message.edit_text("Ошибка. /start")
        await callback.answer()
        return
    premium_text = "активен" if is_premium(callback.from_user.id) else "нет"
    await callback.message.edit_text(
        f"💰 *Баланс:* {user['coins']} 🪙\n"
        f"🎬 *Просмотрено:* {user['total_videos']}\n"
        f"👥 *Заработано:* {user['total_earned']} 🪙\n"
        f"👑 *Премиум:* {premium_text}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")]]),
        parse_mode='Markdown'
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "stats")
async def stats(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    user = get_user(user_id)
    cursor.execute('SELECT COUNT(*) FROM users WHERE referrer_id = ?', (user_id,))
    invited = cursor.fetchone()[0]
    await callback.message.edit_text(
        f"📊 *Статистика*\n"
        f"👥 Приглашено: {invited}\n"
        f"💰 Заработано: {user['total_earned']} 🪙\n"
        f"🎬 Просмотрено: {user['total_videos']}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")]]),
        parse_mode='Markdown'
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "daily_bonus")
async def daily_bonus(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if can_claim_bonus(user_id):
        claim_bonus(user_id)
        user = get_user(user_id)
        await callback.message.edit_text(f"🎁 *Бонус получен!*\n\n+6 🪙\n💰 Баланс: {user['coins']} 🪙", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")]]), parse_mode='Markdown')
    else:
        next_time = get_next_bonus_time(user_id)
        if next_time:
            remaining = next_time - datetime.now()
            hours = remaining.seconds // 3600
            minutes = (remaining.seconds % 3600) // 60
            await callback.message.edit_text(f"⏰ Следующий бонус через {hours} ч {minutes} мин.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")]]), parse_mode='Markdown')
    await callback.answer()

@dp.callback_query(lambda c: c.data == "promo_code")
async def promo_code_prompt(callback: types.CallbackQuery):
    await callback.message.edit_text("🎫 *Введите промокод:*", parse_mode='Markdown')
    dp['waiting_for_promo'][callback.from_user.id] = True
    await callback.answer()

@dp.callback_query(lambda c: c.data == "back_to_menu")
async def back_to_menu(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "✨ *Главное меню*\n"
        "🎬 1 видео = 2 🪙\n"
        "🎁 Бонус каждые 12ч → +6🪙\n"
        "👥 Пригласи друга → +8🪙\n"
        "⭐ Купить коины\n"
        "👑 Премиум 300⭐",
        reply_markup=get_main_keyboard(), parse_mode='Markdown'
    )
    await callback.answer()

async def main():
    await dp.start_polling(bot, tasks_concurrency_limit=100)

if __name__ == '__main__':
    asyncio.run(main())
