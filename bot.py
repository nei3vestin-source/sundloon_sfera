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
MANAGER_ID = 8251761249

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
        premium_until TEXT,
        video_history TEXT DEFAULT '',
        start_date TEXT
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

# --- БЕЗОПАСНОЕ ДОБАВЛЕНИЕ КОЛОНКИ start_date (если отсутствует) ---
cursor.execute("PRAGMA table_info(users)")
columns = [col[1] for col in cursor.fetchall()]
if 'start_date' not in columns:
    cursor.execute('ALTER TABLE users ADD COLUMN start_date TEXT')
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

# =================================================================
# КЛАВИАТУРЫ
# =================================================================

def get_main_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎬 Купить видео (2🪙)", callback_data="buy_video")],
        [InlineKeyboardButton(text="👥 Пригласить друга", callback_data="invite"),
         InlineKeyboardButton(text="💎 Купить коины/премиум", callback_data="buy_contact")],
        [InlineKeyboardButton(text="🎁 Бонус (+6🪙/12ч)", callback_data="daily_bonus"),
         InlineKeyboardButton(text="💰 Баланс", callback_data="balance")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="stats"),
         InlineKeyboardButton(text="👑 Премиум", callback_data="premium")],
        [InlineKeyboardButton(text="🎫 Промокод", callback_data="promo_code"),
         InlineKeyboardButton(text="💰 Заработать", callback_data="earn")],
        [InlineKeyboardButton(text="🏆 Топ", callback_data="leaderboard")]
    ])

def get_back_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")]
    ])

def get_video_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎬 Ещё видео", callback_data="buy_video")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")]
    ])

def get_insufficient_coins_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💎 Купить коины", callback_data="buy_contact")],
        [InlineKeyboardButton(text="👥 Пригласить друга (+8🪙)", callback_data="invite")],
        [InlineKeyboardButton(text="🎁 Забрать бонус (+6🪙)", callback_data="daily_bonus")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")]
    ])

def is_admin(user_id):
    return user_id in ADMIN_IDS

def is_manager(user_id):
    return user_id == MANAGER_ID

# =================================================================
# ЗАЩИТА ОТ ПОВТОРОВ
# =================================================================

def get_random_video_except_last(user_id):
    cursor.execute('SELECT url, price FROM videos WHERE is_active = 1')
    all_videos = cursor.fetchall()
    if not all_videos:
        return None
    
    cursor.execute('SELECT video_history FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    history = row[0] if row and row[0] else ""
    history_list = history.split(',') if history else []
    
    if len(history_list) < 5:
        selected = random.choice(all_videos)
        update_video_history(user_id, selected[0])
        return selected
    
    exclude_urls = history_list[-5:]
    candidates = [v for v in all_videos if v[0] not in exclude_urls]
    if not candidates:
        candidates = all_videos
    
    selected = random.choice(candidates)
    update_video_history(user_id, selected[0])
    return selected

def update_video_history(user_id, video_url):
    cursor.execute('SELECT video_history FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    history = row[0] if row and row[0] else ""
    history_list = history.split(',') if history else []
    history_list.append(video_url)
    if len(history_list) > 20:
        history_list = history_list[-20:]
    new_history = ','.join(history_list)
    cursor.execute('UPDATE users SET video_history = ? WHERE user_id = ?', (new_history, user_id))
    conn.commit()

# =================================================================
# ФУНКЦИИ
# =================================================================

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
        INSERT INTO users (user_id, coins, referrer_id, pending_captcha, pending_referrer, start_date)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (user_id, 0, referrer_id, captcha, referrer_id, datetime.now().isoformat()))
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

def create_promo_code(code, coins, premium_days, stars, max_uses, admin_id):
    """Создает промокод с проверкой валидности"""
    if coins <= 0 and premium_days <= 0 and stars <= 0:
        return False, "❌ Промокод должен давать хотя бы одну награду (коины, премиум или звёзды)"
    if coins < 0 or premium_days < 0 or stars < 0 or max_uses < 1:
        return False, "❌ Значения не могут быть отрицательными, а max_uses >= 1"
    try:
        cursor.execute('''
            INSERT INTO promocodes (code, reward_coins, reward_premium_days, reward_stars, max_uses, used_count, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (code.upper(), coins, premium_days, stars, max_uses, 0, admin_id))
        conn.commit()
        rewards = []
        if coins > 0:
            rewards.append(f"{coins} 🪙")
        if premium_days > 0:
            rewards.append(f"{premium_days} дней 👑")
        if stars > 0:
            rewards.append(f"{stars} ⭐")
        return True, f"✅ Промокод создан!\n📝 Код: `{code.upper()}`\n🎁 Награды: {', '.join(rewards)}\n🔄 Использований: {max_uses}"
    except sqlite3.IntegrityError:
        return False, "❌ Промокод с таким названием уже существует."

def activate_promo_code(user_id, code):
    """Активирует промокод с обновлением статистики"""
    cursor.execute('SELECT reward_coins, reward_premium_days, reward_stars, max_uses, used_count FROM promocodes WHERE code = ?', (code.upper(),))
    promo = cursor.fetchone()
    if not promo:
        return False, "❌ Промокод не найден"
    reward_coins, reward_premium_days, reward_stars, max_uses, used_count = promo
    if used_count >= max_uses:
        return False, "❌ Промокод уже использован максимальное количество раз"
    cursor.execute('SELECT 1 FROM promo_uses WHERE user_id = ? AND code = ?', (user_id, code.upper()))
    if cursor.fetchone():
        return False, "❌ Ты уже использовал этот промокод"
    msg_parts = []
    total_earned = 0
    if reward_coins > 0:
        cursor.execute('UPDATE users SET coins = coins + ?, total_earned = total_earned + ? WHERE user_id = ?', (reward_coins, reward_coins, user_id))
        msg_parts.append(f"💰 +{reward_coins} коинов")
        total_earned += reward_coins
    if reward_premium_days > 0:
        set_premium(user_id, reward_premium_days)
        msg_parts.append(f"👑 +{reward_premium_days} дней премиума")
    if reward_stars > 0:
        star_coins = reward_stars * 2
        cursor.execute('UPDATE users SET coins = coins + ?, total_earned = total_earned + ? WHERE user_id = ?', (star_coins, star_coins, user_id))
        msg_parts.append(f"⭐ +{reward_stars} звёзд ({star_coins} коинов)")
        total_earned += star_coins
    cursor.execute('INSERT INTO promo_uses (user_id, code, used_at) VALUES (?, ?, ?)', (user_id, code.upper(), datetime.now().isoformat()))
    cursor.execute('UPDATE promocodes SET used_count = used_count + 1 WHERE code = ?', (code.upper(),))
    conn.commit()
    return True, f"✅ *Промокод активирован!*\n\n" + "\n".join(msg_parts)

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

# =================================================================
# ФУНКЦИИ ДЛЯ СТАТИСТИКИ
# =================================================================

def log_user_start(user_id):
    """Логирует дату первого запуска бота пользователем"""
    cursor.execute('SELECT start_date FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    if row and row[0] is None:
        cursor.execute('UPDATE users SET start_date = ? WHERE user_id = ?', (datetime.now().isoformat(), user_id))
        conn.commit()
        return True
    return False

def get_user_stats():
    """Возвращает общую статистику по пользователям"""
    cursor.execute('SELECT COUNT(*) FROM users')
    total_users = cursor.fetchone()[0]
    cursor.execute('SELECT COUNT(*) FROM users WHERE start_date IS NOT NULL')
    started_users = cursor.fetchone()[0]
    cursor.execute('SELECT COUNT(*) FROM users WHERE premium_until IS NOT NULL AND premium_until > ?', (datetime.now().isoformat(),))
    premium_users = cursor.fetchone()[0]
    cursor.execute('SELECT SUM(coins) FROM users')
    total_coins = cursor.fetchone()[0] or 0
    cursor.execute('SELECT SUM(total_earned) FROM users')
    total_earned = cursor.fetchone()[0] or 0
    return {
        'total_users': total_users,
        'started_users': started_users,
        'premium_users': premium_users,
        'total_coins': total_coins,
        'total_earned': total_earned
    }

# =================================================================
# ОБРАБОТЧИКИ
# =================================================================

@dp.message(Command('start'))
async def start(message: types.Message):
    args = message.text.split()
    referrer_code = args[1] if len(args) > 1 else None
    user_id = message.from_user.id
    log_user_start(user_id)
    user = get_user(user_id)
    if user:
        await message.answer(
            "✨ *Добро пожаловать обратно!* ✨\n\n"
            "🎬 1 видео = 2 🪙\n"
            "🎁 Бонус каждые 12ч → +6🪙\n"
            "👥 Пригласи друга → +8🪙\n"
            "💎 Покупка коинов/премиума — в ЛС @GendaleTray\n"
            "👑 Премиум 300⭐ → безлимит\n\n"
            "👇 *Выбери действие:*",
            reply_markup=get_main_keyboard(),
            parse_mode='Markdown'
        )
        return
    result = register_user(user_id, referrer_code)
    if result and 'captcha' in result:
        await message.answer(
            f"🔐 *Добро пожаловать!*\nРеши пример:\n\n{result['captcha']} = ?\n\nОтправь число.",
            parse_mode='Markdown'
        )
        dp['captcha_waiting'][user_id] = result['answer']

# --- КНОПКА "КУПИТЬ" (СВЯЗЬ С МЕНЕДЖЕРОМ) ---
@dp.callback_query(lambda c: c.data == "buy_contact")
async def buy_contact(callback: types.CallbackQuery):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📩 Написать менеджеру", url="https://t.me/GendaleTray")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")]
    ])
    await callback.message.edit_text(
        "💎 *Покупка коинов и премиума*\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "💰 *Цены:*\n"
        "• 30 коинов — 15 ⭐\n"
        "• 60 коинов — 30 ⭐\n"
        "• 100 коинов — 50 ⭐\n"
        "• 500 коинов — 250 ⭐\n"
        "• 1000 коинов — 500 ⭐\n"
        "• Премиум (30 дней) — 300 ⭐\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "📩 Для покупки напиши @GendaleTray\n"
        "Укажи: что хочешь купить и свой ID (можно скопировать из бота).\n\n"
        "⚠️ *Оплата только через Telegram Stars!*",
        reply_markup=keyboard,
        parse_mode='Markdown'
    )
    await callback.answer()

# --- ОБРАБОТЧИК ТЕКСТОВЫХ СООБЩЕНИЙ ---
@dp.message()
async def handle_all_messages(message: types.Message):
    user_id = message.from_user.id
    text = message.text.strip() if message.text else ""
    
    # ПРОМОКОД
    if dp['waiting_for_promo'].get(user_id):
        del dp['waiting_for_promo'][user_id]
        success, msg = activate_promo_code(user_id, text)
        await message.answer(msg, reply_markup=get_main_keyboard(), parse_mode='Markdown')
        return
    
    # КАПЧА
    if dp['captcha_waiting'].get(user_id):
        try:
            answer = int(text)
            expected = dp['captcha_waiting'][user_id]
            if answer == expected:
                del dp['captcha_waiting'][user_id]
                if process_captcha(user_id, answer):
                    await message.answer(
                        "✅ *Регистрация завершена!*\n━━━━━━━━━━━━━━━━\n"
                        "🎁 Ты получил 10 коинов.\n"
                        "👥 Твой друг получил 8 коинов.\n━━━━━━━━━━━━━━━━",
                        reply_markup=get_main_keyboard(),
                        parse_mode='Markdown'
                    )
                else:
                    await message.answer("❌ Ошибка. Напиши /start заново.")
            else:
                await message.answer("❌ Неправильно. Попробуй ещё раз.")
        except ValueError:
            await message.answer("❌ Отправь число.")
        return
    
    # СКРИНШОТЫ (ОТПРАВЛЯЮТСЯ МЕНЕДЖЕРУ)
    if message.photo or message.document:
        submitted, approved, completed = get_task_status(user_id)
        if completed == 1:
            await message.answer("✅ Задание уже выполнено!", reply_markup=get_main_keyboard())
            return
        if submitted >= 10:
            await message.answer(f"📋 Ты уже отправил {submitted} скриншотов. Ожидай проверки.", reply_markup=get_main_keyboard())
            return
        
        file_id = message.photo[-1].file_id if message.photo else message.document.file_id
        new_submitted = add_screenshot(user_id, file_id, message.message_id)
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Одобрить", callback_data=f"approve_{user_id}"),
             InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{user_id}")]
        ])
        
        caption = f"📸 *Новый скриншот*\n━━━━━━━━━━━━━━━━\n👤 Пользователь: {user_id}\n📊 Прогресс: {new_submitted}/10\n━━━━━━━━━━━━━━━━"
        await bot.send_photo(MANAGER_ID, photo=file_id, caption=caption, reply_markup=keyboard)
        
        await message.answer(f"✅ Скриншот {new_submitted}/10 отправлен менеджеру на проверку.", reply_markup=get_main_keyboard())
        return
    
    await message.answer("❌ Неизвестная команда. Используй /start", reply_markup=get_main_keyboard())

# =================================================================
# ВСЕ CALLBACK'И
# =================================================================

@dp.callback_query(lambda c: c.data == "back_to_menu")
async def back_to_menu(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "✨ *Главное меню* ✨\n━━━━━━━━━━━━━━━━\n"
        "🎬 1 видео = 2 🪙\n"
        "🎁 Бонус каждые 12ч → +6🪙\n"
        "👥 Пригласи друга → +8🪙\n"
        "💎 Покупка — в ЛС @GendaleTray\n"
        "👑 Премиум 300⭐\n━━━━━━━━━━━━━━━━\n"
        "👇 *Выбери действие:*",
        reply_markup=get_main_keyboard(),
        parse_mode='Markdown'
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "buy_video")
async def buy_video(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    user = get_user(user_id)
    if not user:
        await callback.message.edit_text("❌ Ошибка. Напиши /start", reply_markup=get_back_keyboard())
        await callback.answer()
        return
    
    if not is_premium(user_id) and user['coins'] < 2:
        await callback.message.edit_text(
            f"❌ *Недостаточно коинов!*\n\n"
            f"┏━━━━━━━━━━━━━━━━━━━━━━┓\n"
            f"┃  🪙 Твой баланс: {user['coins']}  ┃\n"
            f"┃  🎬 Цена: 2 🪙          ┃\n"
            f"┗━━━━━━━━━━━━━━━━━━━━━━┛\n\n"
            f"💡 *Как пополнить баланс?*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👥 Пригласи друга → +8 🪙\n"
            f"💎 Купи коины у @GendaleTray\n"
            f"🎁 Забери бонус → +6 🪙\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👇 *Выбери способ пополнения:*",
            reply_markup=get_insufficient_coins_keyboard(),
            parse_mode='Markdown'
        )
        await callback.answer()
        return
    
    video_data = get_random_video_except_last(user_id)
    if not video_data:
        await callback.message.edit_text("❌ Видео пока нет. Попробуй позже.", reply_markup=get_back_keyboard())
        await callback.answer()
        return
    
    video_url, price = video_data
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
            caption=f"🎬 *Твоё видео!* 🎬\n━━━━━━━━━━━━━━━━\n"
                    f"📊 *Просмотрено:* {total_watched} видео\n"
                    f"💸 *Списано:* {price if not is_premium(user_id) else 0} 🪙\n"
                    f"💰 *Осталось:* {new_balance} 🪙\n━━━━━━━━━━━━━━━━",
            parse_mode='Markdown',
            reply_markup=get_video_keyboard()
        )
    except Exception:
        if not is_premium(user_id):
            update_coins(user_id, price)
            cursor.execute('UPDATE users SET total_videos = total_videos - 1 WHERE user_id = ?', (user_id,))
            conn.commit()
        await callback.message.edit_text(
            "❌ *Не удалось загрузить видео.*\nКоины возвращены.",
            reply_markup=get_main_keyboard(),
            parse_mode='Markdown'
        )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "balance")
async def balance(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    user = get_user(user_id)
    if not user:
        await callback.message.edit_text("❌ Ошибка. Напиши /start", reply_markup=get_back_keyboard())
        await callback.answer()
        return
    
    premium_text = "✅ активен" if is_premium(user_id) else "❌ нет"
    await callback.message.edit_text(
        f"💰 *Твой баланс* 💰\n━━━━━━━━━━━━━━━━\n"
        f"🪙 *Коинов:* {user['coins']}\n"
        f"🎬 *Просмотрено:* {user['total_videos']}\n"
        f"👥 *Заработано:* {user['total_earned']} 🪙\n"
        f"👑 *Премиум:* {premium_text}\n━━━━━━━━━━━━━━━━",
        reply_markup=get_back_keyboard(),
        parse_mode='Markdown'
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "daily_bonus")
async def daily_bonus(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    user = get_user(user_id)
    if not user:
        await callback.message.edit_text("❌ Ошибка. Напиши /start", reply_markup=get_back_keyboard())
        await callback.answer()
        return
    
    if can_claim_bonus(user_id):
        claim_bonus(user_id)
        user = get_user(user_id)
        await callback.message.edit_text(
            f"🎁 *Бонус получен!* 🎁\n━━━━━━━━━━━━━━━━\n"
            f"+6 🪙\n"
            f"💰 *Баланс:* {user['coins']} 🪙\n━━━━━━━━━━━━━━━━\n"
            f"⏰ Следующий бонус через 12 часов.",
            reply_markup=get_back_keyboard(),
            parse_mode='Markdown'
        )
    else:
        next_time = get_next_bonus_time(user_id)
        if next_time:
            remaining = next_time - datetime.now()
            hours = remaining.seconds // 3600
            minutes = (remaining.seconds % 3600) // 60
            await callback.message.edit_text(
                f"⏰ *Бонус пока недоступен*\n━━━━━━━━━━━━━━━━\n"
                f"Следующий бонус через {hours} ч {minutes} мин.",
                reply_markup=get_back_keyboard(),
                parse_mode='Markdown'
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
        f"👥 *Твоя реферальная ссылка* 👥\n━━━━━━━━━━━━━━━━\n"
        f"🔗 `{invite_link}`\n━━━━━━━━━━━━━━━━\n"
        f"👥 *Пригласи друга → +8 🪙*\n"
        f"🎁 *Друг получит +10 🪙*\n━━━━━━━━━━━━━━━━",
        reply_markup=keyboard,
        parse_mode='Markdown'
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "premium")
async def premium_menu(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if is_premium(user_id):
        until = datetime.fromisoformat(get_user(user_id)['premium_until']).strftime('%d.%m.%Y')
        await callback.message.edit_text(
            f"👑 *Премиум активен* 👑\n━━━━━━━━━━━━━━━━\n"
            f"📅 До: {until}\n"
            f"🎬 Безлимитный просмотр\n━━━━━━━━━━━━━━━━",
            reply_markup=get_back_keyboard(),
            parse_mode='Markdown'
        )
    else:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💎 Купить премиум", callback_data="buy_contact")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")]
        ])
        await callback.message.edit_text(
            "👑 *Премиум подписка* 👑\n━━━━━━━━━━━━━━━━\n"
            "💎 *Цена:* 300 ⭐\n"
            "🌟 *Преимущества:*\n"
            "• Безлимитный просмотр\n"
            "• +50 🪙 в подарок\n━━━━━━━━━━━━━━━━\n"
            "📩 Для покупки напиши @GendaleTray",
            reply_markup=keyboard,
            parse_mode='Markdown'
        )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "stats")
async def stats(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    user = get_user(user_id)
    if not user:
        await callback.message.edit_text("❌ Ошибка. Напиши /start", reply_markup=get_back_keyboard())
        await callback.answer()
        return
    
    cursor.execute('SELECT COUNT(*) FROM users WHERE referrer_id = ?', (user_id,))
    invited = cursor.fetchone()[0]
    await callback.message.edit_text(
        f"📊 *Статистика* 📊\n━━━━━━━━━━━━━━━━\n"
        f"👥 *Приглашено:* {invited}\n"
        f"💰 *Заработано:* {user['total_earned']} 🪙\n"
        f"🎬 *Просмотрено:* {user['total_videos']}\n━━━━━━━━━━━━━━━━",
        reply_markup=get_back_keyboard(),
        parse_mode='Markdown'
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "promo_code")
async def promo_code_prompt(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "🎫 *Введите промокод* 🎫\n━━━━━━━━━━━━━━━━\n"
        "Отправь код текстовым сообщением.\n"
        "Промокод не чувствителен к регистру.",
        reply_markup=get_back_keyboard(),
        parse_mode='Markdown'
    )
    dp['waiting_for_promo'][callback.from_user.id] = True
    await callback.answer()

@dp.callback_query(lambda c: c.data == "earn")
async def earn_callback(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    user = get_user(user_id)
    if not user:
        await callback.message.edit_text("❌ Ошибка. Напиши /start", reply_markup=get_back_keyboard())
        await callback.answer()
        return
    
    submitted, approved, completed = get_task_status(user_id)
    if completed == 1:
        await callback.message.edit_text(
            "📋 *Задание выполнено!* 📋\n━━━━━━━━━━━━━━━━\n"
            "✅ Ты уже получил 30 коинов.\n"
            "🔄 Начни новое задание кнопкой ниже.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Начать новое", callback_data="start_new_task")],
                [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")]
            ]),
            parse_mode='Markdown'
        )
        await callback.answer()
        return
    if submitted > 0:
        await callback.message.edit_text(
            f"📋 *Твой прогресс* 📋\n━━━━━━━━━━━━━━━━\n"
            f"📤 Отправлено: {submitted}/10\n"
            f"✅ Одобрено: {approved}/10\n━━━━━━━━━━━━━━━━\n"
            "📸 Продолжай отправлять скриншоты.",
            reply_markup=get_back_keyboard(),
            parse_mode='Markdown'
        )
        await callback.answer()
        return
    
    success, msg = start_task(user_id)
    if not success:
        await callback.message.edit_text(msg, reply_markup=get_back_keyboard(), parse_mode='Markdown')
        await callback.answer()
        return
    
    instruction = (
        "💰 *Как заработать 30 коинов?* 💰\n━━━━━━━━━━━━━━━━\n"
        "1️⃣ Зайди в TikTok\n"
        "2️⃣ В поиске напиши: *Детское Питание*\n"
        "3️⃣ Под видео оставь комментарий:\n"
        "   `@GendaleTray РИЛ ДАЛИ 😂`\n"
        "4️⃣ Поставь лайк\n"
        "5️⃣ Сделай скриншот\n━━━━━━━━━━━━━━━━\n"
        "📌 *Нужно 10 скриншотов!*\n"
        "📸 Отправляй скриншоты @GendaleTray\n━━━━━━━━━━━━━━━━"
    )
    await callback.message.edit_text(instruction, reply_markup=get_back_keyboard(), parse_mode='Markdown')
    await callback.answer()

@dp.callback_query(lambda c: c.data == "leaderboard")
async def leaderboard(callback: types.CallbackQuery):
    cursor.execute('SELECT user_id, coins, total_videos FROM users ORDER BY coins DESC LIMIT 10')
    users = cursor.fetchall()
    if not users:
        await callback.message.edit_text(
            "🏆 *Топ пользователей* 🏆\n━━━━━━━━━━━━━━━━\n"
            "📊 Пока нет пользователей.",
            reply_markup=get_back_keyboard(),
            parse_mode='Markdown'
        )
        await callback.answer()
        return
    
    text = "🏆 *Топ пользователей* 🏆\n━━━━━━━━━━━━━━━━\n"
    medals = ['🥇', '🥈', '🥉']
    for i, user in enumerate(users):
        medal = medals[i] if i < 3 else f"{i+1}."
        text += f"{medal} `{user[0]}` — {user[1]} 🪙 ({user[2]} видео)\n"
    text += "━━━━━━━━━━━━━━━━"
    
    await callback.message.edit_text(text, reply_markup=get_back_keyboard(), parse_mode='Markdown')
    await callback.answer()

# --- ОДОБРЕНИЕ/ОТКЛОНЕНИЕ СКРИНШОТОВ (МЕНЕДЖЕР) ---
@dp.callback_query(lambda c: c.data.startswith("approve_"))
async def approve_screenshot(callback: types.CallbackQuery):
    if not is_manager(callback.from_user.id):
        await callback.answer("❌ У вас нет прав.", show_alert=True)
        return
    
    target_user = int(callback.data.split('_')[1])
    
    cursor.execute('SELECT id FROM pending_screenshots WHERE user_id = ? ORDER BY timestamp DESC LIMIT 1', (target_user,))
    row = cursor.fetchone()
    if not row:
        await callback.message.edit_text("❌ Нет скриншотов на проверку.")
        await callback.answer()
        return
    
    screenshot_id = row[0]
    result = approve_screenshot(screenshot_id)
    if not result:
        await callback.message.edit_text("❌ Ошибка при одобрении.")
        await callback.answer()
        return
    
    user_id, completed, submitted, approved = result
    await callback.message.edit_text(f"✅ Скриншот одобрен! Прогресс: {approved}/10")
    
    if completed:
        await bot.send_message(target_user, "🎉 *Поздравляем!*\n━━━━━━━━━━━━━━━━\n✅ Ты выполнил задание!\n💰 +30 коинов начислено!\n━━━━━━━━━━━━━━━━", reply_markup=get_main_keyboard(), parse_mode='Markdown')
    else:
        await bot.send_message(target_user, f"✅ Один скриншот одобрен.\n📊 Прогресс: {approved}/10", reply_markup=get_main_keyboard())
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("reject_"))
async def reject_screenshot(callback: types.CallbackQuery):
    if not is_manager(callback.from_user.id):
        await callback.answer("❌ У вас нет прав.", show_alert=True)
        return
    
    target_user = int(callback.data.split('_')[1])
    
    cursor.execute('SELECT id FROM pending_screenshots WHERE user_id = ? ORDER BY timestamp DESC LIMIT 1', (target_user,))
    row = cursor.fetchone()
    if not row:
        await callback.message.edit_text("❌ Нет скриншотов на проверку.")
        await callback.answer()
        return
    
    screenshot_id = row[0]
    result = reject_screenshot(screenshot_id)
    if not result:
        await callback.message.edit_text("❌ Ошибка при отклонении.")
        await callback.answer()
        return
    
    user_id, submitted, approved = result
    await callback.message.edit_text(f"❌ Скриншот отклонён. Прогресс: {approved}/10")
    await bot.send_message(target_user, f"❌ *Скриншот отклонён.*\n📊 Прогресс: {approved}/10\n📸 Отправь новый скриншот.", reply_markup=get_main_keyboard())
    await callback.answer()

# --- АДМИН-КОМАНДЫ ---

@dp.message(Command('add_promo'))
async def add_promo_command(message: types.Message):
    user_id = message.from_user.id
    if not is_admin(user_id):
        await message.answer("❌ У вас нет прав.")
        return
    
    args = message.text.split()
    if len(args) < 2:
        await message.answer(
            "📝 *Формат:* `/add_promo код [coins] [premium_days] [stars] [max_uses]`\n"
            "Пример: `/add_promo FREE1000 1000 0 0 50`",
            parse_mode='Markdown'
        )
        return
    
    try:
        code = args[1].upper()
        coins = int(args[2]) if len(args) > 2 else 0
        premium_days = int(args[3]) if len(args) > 3 else 0
        stars = int(args[4]) if len(args) > 4 else 0
        max_uses = int(args[5]) if len(args) > 5 else 1
    except ValueError:
        await message.answer("❌ Все аргументы должны быть числами (кроме кода).")
        return
    
    success, msg = create_promo_code(code, coins, premium_days, stars, max_uses, user_id)
    await message.answer(msg, parse_mode='Markdown')

@dp.message(Command('give_coins'))
async def give_coins_command(message: types.Message):
    user_id = message.from_user.id
    if not is_admin(user_id):
        await message.answer("❌ У вас нет прав.")
        return
    
    args = message.text.split()
    if len(args) < 3:
        await message.answer("📝 `/give_coins user_id amount`\nПример: `/give_coins 123456789 100`", parse_mode='Markdown')
        return
    
    try:
        target_id = int(args[1])
        amount = int(args[2])
    except ValueError:
        await message.answer("❌ ID и сумма должны быть числами.")
        return
    
    if amount <= 0:
        await message.answer("❌ Сумма должна быть положительной.")
        return
    
    target_user = get_user(target_id)
    if not target_user:
        await message.answer(f"❌ Пользователь {target_id} не найден.")
        return
    
    cursor.execute('UPDATE users SET coins = coins + ?, total_earned = total_earned + ? WHERE user_id = ?', (amount, amount, target_id))
    conn.commit()
    
    new_balance = target_user['coins'] + amount
    await message.answer(f"✅ Выдано {amount} 🪙 пользователю {target_id}.\n📊 Новый баланс: {new_balance} 🪙")
    
    try:
        await bot.send_message(
            target_id,
            f"💰 *Вам начислено {amount} 🪙!*\n📊 Баланс: {new_balance} 🪙",
            reply_markup=get_main_keyboard(),
            parse_mode='Markdown'
        )
    except:
        pass

@dp.message(Command('give_premium'))
async def give_premium_command(message: types.Message):
    user_id = message.from_user.id
    if not is_admin(user_id):
        await message.answer("❌ У вас нет прав.")
        return
    
    args = message.text.split()
    if len(args) < 3:
        await message.answer("📝 `/give_premium user_id days`\nПример: `/give_premium 123456789 30`", parse_mode='Markdown')
        return
    
    try:
        target_id = int(args[1])
        days = int(args[2])
    except ValueError:
        await message.answer("❌ ID и дни должны быть числами.")
        return
    
    if days <= 0:
        await message.answer("❌ Количество дней должно быть положительным.")
        return
    
    target_user = get_user(target_id)
    if not target_user:
        await message.answer(f"❌ Пользователь {target_id} не найден.")
        return
    
    set_premium(target_id, days)
    until = (datetime.now() + timedelta(days=days)).strftime('%d.%m.%Y')
    await message.answer(f"✅ Премиум выдан {target_id} на {days} дней.\n📅 До: {until}")
    
    try:
        await bot.send_message(
            target_id,
            f"👑 *Вам выдан премиум на {days} дней!*\n📅 Действует до: {until}\n🎬 Безлимитный просмотр видео!",
            reply_markup=get_main_keyboard(),
            parse_mode='Markdown'
        )
    except:
        pass

@dp.message(Command('remove_premium'))
async def remove_premium_command(message: types.Message):
    user_id = message.from_user.id
    if not is_admin(user_id):
        await message.answer("❌ У вас нет прав.")
        return
    
    args = message.text.split()
    if len(args) < 2:
        await message.answer("📝 /remove_premium user_id", parse_mode='Markdown')
        return
    
    try:
        target_id = int(args[1])
    except ValueError:
        await message.answer("❌ ID должен быть числом.")
        return
    
    target_user = get_user(target_id)
    if not target_user:
        await message.answer(f"❌ Пользователь {target_id} не найден.")
        return
    
    cursor.execute('UPDATE users SET premium_until = NULL WHERE user_id = ?', (target_id,))
    conn.commit()
    await message.answer(f"✅ Премиум снят с {target_id}.")
    try:
        await bot.send_message(target_id, f"❌ Ваш премиум был снят.", reply_markup=get_main_keyboard())
    except:
        pass

@dp.message(Command('stats_users'))
async def stats_users_command(message: types.Message):
    user_id = message.from_user.id
    if not is_admin(user_id):
        await message.answer("❌ У вас нет прав.")
        return
    
    stats = get_user_stats()
    text = (
        f"📊 *Статистика бота* 📊\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 *Всего пользователей:* {stats['total_users']}\n"
        f"🆕 *Запустили бота:* {stats['started_users']}\n"
        f"👑 *Премиум:* {stats['premium_users']}\n"
        f"💰 *Всего коинов:* {stats['total_coins']}\n"
        f"💎 *Заработано всего:* {stats['total_earned']}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━"
    )
    await message.answer(text, parse_mode='Markdown')

@dp.message(Command('list_promocodes'))
async def list_promocodes_command(message: types.Message):
    user_id = message.from_user.id
    if not is_admin(user_id):
        await message.answer("❌ У вас нет прав.")
        return
    
    cursor.execute('''
        SELECT code, reward_coins, reward_premium_days, reward_stars, max_uses, used_count, created_by 
        FROM promocodes 
        ORDER BY created_by DESC
    ''')
    promocodes = cursor.fetchall()
    
    if not promocodes:
        await message.answer("📝 Нет созданных промокодов.", parse_mode='Markdown')
        return
    
    text = "📋 *Список промокодов* 📋\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for promo in promocodes:
        code, coins, days, stars, max_uses, used_count, created_by = promo
        rewards = []
        if coins > 0:
            rewards.append(f"{coins}🪙")
        if days > 0:
            rewards.append(f"{days}д👑")
        if stars > 0:
            rewards.append(f"{stars}⭐")
        text += (
            f"🔹 `{code}`\n"
            f"   🎁 {', '.join(rewards)}\n"
            f"   📊 {used_count}/{max_uses}\n"
            f"   👤 {created_by}\n\n"
        )
    await message.answer(text, parse_mode='Markdown')

# --- НОВЫЕ КОМАНДЫ ДЛЯ МАССОВОЙ ВЫДАЧИ КОИНОВ ---

@dp.message(Command('give_all_coins'))
async def give_all_coins(message: types.Message):
    """Выдать коины ВСЕМ пользователям (админ)"""
    user_id = message.from_user.id
    if not is_admin(user_id):
        await message.answer("❌ У вас нет прав.")
        return
    
    args = message.text.split()
    if len(args) < 2:
        await message.answer("📝 `/give_all_coins <количество>`\nПример: `/give_all_coins 10`", parse_mode='Markdown')
        return
    
    try:
        amount = int(args[1])
    except ValueError:
        await message.answer("❌ Количество должно быть числом.")
        return
    
    if amount <= 0:
        await message.answer("❌ Количество должно быть положительным.")
        return
    
    cursor.execute('SELECT user_id FROM users')
    all_users = cursor.fetchall()
    if not all_users:
        await message.answer("❌ В базе нет пользователей.")
        return
    
    count = 0
    for (uid,) in all_users:
        cursor.execute('UPDATE users SET coins = coins + ?, total_earned = total_earned + ? WHERE user_id = ?', 
                      (amount, amount, uid))
        count += 1
        try:
            await bot.send_message(uid, f"💰 Админ выдал всем +{amount} 🪙!", reply_markup=get_main_keyboard())
        except:
            pass
    
    conn.commit()
    await message.answer(f"✅ Выдано {amount} 🪙 {count} пользователям.")

@dp.message(Command('give_active_coins'))
async def give_active_coins(message: types.Message):
    """Выдать коины только АКТИВНЫМ пользователям (у кого есть start_date)"""
    user_id = message.from_user.id
    if not is_admin(user_id):
        await message.answer("❌ У вас нет прав.")
        return
    
    args = message.text.split()
    if len(args) < 2:
        await message.answer("📝 `/give_active_coins <количество>`\nПример: `/give_active_coins 10`", parse_mode='Markdown')
        return
    
    try:
        amount = int(args[1])
    except ValueError:
        await message.answer("❌ Количество должно быть числом.")
        return
    
    if amount <= 0:
        await message.answer("❌ Количество должно быть положительным.")
        return
    
    cursor.execute('SELECT user_id FROM users WHERE start_date IS NOT NULL')
    active_users = cursor.fetchall()
    if not active_users:
        await message.answer("❌ Активных пользователей нет.")
        return
    
    count = 0
    for (uid,) in active_users:
        cursor.execute('UPDATE users SET coins = coins + ?, total_earned = total_earned + ? WHERE user_id = ?', 
                      (amount, amount, uid))
        count += 1
        try:
            await bot.send_message(uid, f"💰 Админ выдал активным +{amount} 🪙!", reply_markup=get_main_keyboard())
        except:
            pass
    
    conn.commit()
    await message.answer(f"✅ Выдано {amount} 🪙 {count} активным пользователям.")

# =================================================================
# ЗАПУСК
# =================================================================

async def main():
    await dp.start_polling(bot, tasks_concurrency_limit=100)

if __name__ == '__main__':
    asyncio.run(main())
