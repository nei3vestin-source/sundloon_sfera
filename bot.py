#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import json
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# ============= НАСТРОЙКИ =============
BOT_TOKEN = "8678682443:AAGgxH71y9xtAIwHa_ECOrt-kvyqd6xDOTg"
# ID администраторов
ADMIN_IDS = [
    7785643239,     # Ваш ID (@Poalaqss)
    8409401563,     # ID @killeryourbrain1
    7623873942      # ID @Clawtr1ks
]

TICKETS_FOLDER = "tickets"
LOGS_FOLDER = "logs"

# Создаем папки
os.makedirs(TICKETS_FOLDER, exist_ok=True)
os.makedirs(LOGS_FOLDER, exist_ok=True)

# Настройка логирования
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(LOGS_FOLDER, f"bot_{datetime.now().strftime('%Y%m%d')}.log"), encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ============= ФУНКЦИИ РАБОТЫ С ТИКЕТАМИ =============
def save_ticket(user_id, username, message):
    """Сохраняет тикет"""
    try:
        ticket_id = f"{user_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        ticket_data = {
            "id": ticket_id,
            "user_id": user_id,
            "username": username,
            "message": message,
            "time": datetime.now().isoformat(),
            "status": "open"
        }
        
        filepath = os.path.join(TICKETS_FOLDER, f"{ticket_id}.json")
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(ticket_data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"✅ Тикет создан: {ticket_id}")
        return ticket_id
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения: {e}")
        return None

def get_ticket(ticket_id):
    """Получает тикет по ID"""
    try:
        filepath = os.path.join(TICKETS_FOLDER, f"{ticket_id}.json")
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        return None
    except Exception as e:
        logger.error(f"❌ Ошибка чтения: {e}")
        return None

def close_ticket_db(ticket_id):
    """Закрывает тикет"""
    try:
        filepath = os.path.join(TICKETS_FOLDER, f"{ticket_id}.json")
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f:
                ticket = json.load(f)
            
            ticket["status"] = "closed"
            ticket["closed_time"] = datetime.now().isoformat()
            
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(ticket, f, ensure_ascii=False, indent=2)
            logger.info(f"✅ Тикет закрыт: {ticket_id}")
            return True
        return False
    except Exception as e:
        logger.error(f"❌ Ошибка закрытия: {e}")
        return False

def get_all_open_tickets():
    """Получает все открытые тикеты"""
    tickets = []
    try:
        logger.info(f"Поиск тикетов в папке: {TICKETS_FOLDER}")
        
        if not os.path.exists(TICKETS_FOLDER):
            logger.error(f"Папка {TICKETS_FOLDER} не существует")
            return []
        
        files = os.listdir(TICKETS_FOLDER)
        logger.info(f"Найдено файлов: {len(files)}")
        
        for filename in files:
            if filename.endswith('.json'):
                filepath = os.path.join(TICKETS_FOLDER, filename)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        ticket = json.load(f)
                        logger.debug(f"Читаем файл: {filename}, статус: {ticket.get('status')}")
                        if ticket.get("status") == "open":
                            tickets.append(ticket)
                except Exception as e:
                    logger.error(f"Ошибка чтения файла {filename}: {e}")
        
        logger.info(f"Найдено открытых тикетов: {len(tickets)}")
        return sorted(tickets, key=lambda x: x.get("time", ""), reverse=True)
    except Exception as e:
        logger.error(f"❌ Ошибка получения тикетов: {e}")
        return []

def get_user_tickets(user_id):
    """Получает тикеты пользователя"""
    tickets = []
    try:
        for filename in os.listdir(TICKETS_FOLDER):
            if filename.endswith('.json'):
                filepath = os.path.join(TICKETS_FOLDER, filename)
                with open(filepath, 'r', encoding='utf-8') as f:
                    ticket = json.load(f)
                    if ticket.get("user_id") == user_id:
                        tickets.append(ticket)
        return sorted(tickets, key=lambda x: x.get("time", ""), reverse=True)
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        return []

# ============= КОМАНДЫ ДЛЯ ИГРОКОВ =============
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start"""
    keyboard = [
        [InlineKeyboardButton("📝 Создать тикет", callback_data="new")],
        [InlineKeyboardButton("📋 Мои тикеты", callback_data="my")],
        [InlineKeyboardButton("ℹ️ Информация", callback_data="info")]
    ]
    await update.message.reply_text(
        "🎮 **Поддержка Minecraft сервера**\n\n"
        "Выберите действие:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /help"""
    await update.message.reply_text(
        "📖 **Команды для игроков:**\n\n"
        "/start - Главное меню\n"
        "/help - Эта справка\n"
        "/status - Статус сервера\n"
        "/cancel - Отменить создание тикета\n\n"
        "**Как создать тикет:**\n"
        "1. Нажмите /start\n"
        "2. Нажмите 'Создать тикет'\n"
        "3. Напишите вашу проблему",
        parse_mode="Markdown"
    )

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /status"""
    await update.message.reply_text(
        "🟢 **Статус сервера**\n\n"
        "**IP:** 65.108.39.115:25905\n"
        "**Версия:** 1.21.4\n"
        "**Онлайн:** 0/50\n"
        "**Статус:** ✅ Работает",
        parse_mode="Markdown"
    )

async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /cancel"""
    if context.user_data.get("waiting"):
        context.user_data.pop("waiting")
        await update.message.reply_text("✅ Создание тикета отменено")
    else:
        await update.message.reply_text("❌ Нет активных действий")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка сообщений от пользователей"""
    user = update.effective_user
    
    if context.user_data.get("waiting"):
        text = update.message.text.strip()
        
        if len(text) < 3:
            await update.message.reply_text("❌ Сообщение слишком короткое. Напишите подробнее (минимум 3 символа).")
            return
        
        ticket_id = save_ticket(user.id, user.username or user.first_name, text)
        
        if ticket_id:
            context.user_data.pop("waiting")
            short_id = ticket_id[-12:]
            await update.message.reply_text(
                f"✅ **Тикет создан!**\n\n"
                f"**ID:** `{short_id}`\n"
                f"Администраторы уведомлены.\n"
                f"Ответ придет сюда.",
                parse_mode="Markdown"
            )
            await notify_admins(context.bot, user, text, ticket_id)
        else:
            await update.message.reply_text("❌ Ошибка при создании тикета. Попробуйте позже.")
    else:
        keyboard = [[InlineKeyboardButton("📝 Создать тикет", callback_data="new")]]
        await update.message.reply_text(
            "Чтобы создать обращение, нажмите кнопку:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка кнопок"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "new":
        await query.edit_message_text(
            "📝 **Создание тикета**\n\nНапишите ваше сообщение:",
            parse_mode="Markdown"
        )
        context.user_data["waiting"] = True
        
    elif query.data == "my":
        tickets = get_user_tickets(query.from_user.id)
        if not tickets:
            await query.edit_message_text("📭 У вас нет созданных тикетов")
            return
        
        msg = "📋 **Ваши тикеты:**\n\n"
        for t in tickets[:5]:
            status = "🟢 Открыт" if t.get("status") == "open" else "🔴 Закрыт"
            date = datetime.fromisoformat(t.get("time")).strftime("%d.%m %H:%M")
            msg += f"**#{t['id'][-12:]}** | {date}\n"
            msg += f"{status}\n"
            msg += f"📝 {t['message'][:50]}...\n\n"
        await query.edit_message_text(msg, parse_mode="Markdown")
        
    elif query.data == "info":
        await query.edit_message_text(
            "ℹ️ **Информация о сервере**\n\n"
            "**IP:** 65.108.39.115:25905\n"
            "**Версия:** 1.21.4\n"
            "**Владелец:** @Poalaqss\n"
            "**Админы:** @killeryourbrain1, @Clawtr1ks\n\n"
            "**Сайт:** http://hm485389.webhm.pro/\n"
            "**Discord:** https://discord.gg/vHEJpV2g",
            parse_mode="Markdown"
        )

async def notify_admins(bot, user, message, ticket_id):
    """Уведомление администраторов"""
    short_id = ticket_id[-12:]
    
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"🆕 **Новый тикет!**\n\n"
                f"**ID:** `{short_id}`\n"
                f"**Игрок:** @{user.username or user.first_name}\n"
                f"**Сообщение:**\n{message}\n\n"
                f"**Ответить:** `/msg {short_id} ваш ответ`\n"
                f"**Закрыть:** `/close {short_id}`\n"
                f"**Список:** `/tickets`",
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Не удалось отправить админу {admin_id}: {e}")

# ============= КОМАНДЫ ДЛЯ АДМИНОВ =============
async def admin_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ответ на тикет: /msg ID_тикета текст ответа"""
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("⛔ У вас нет прав для этой команды.")
        return
    
    text = update.message.text
    parts = text.split(" ", 2)
    
    if len(parts) < 3:
        await update.message.reply_text(
            "❌ **Как ответить на тикет:**\n\n"
            "`/msg ID_тикета ваш ответ`\n\n"
            "**Пример:**\n"
            "`/msg 60320_140032 Привет, проблема решена!`\n\n"
            "ID тикета можно скопировать из уведомления или из списка /tickets",
            parse_mode="Markdown"
        )
        return
    
    ticket_short = parts[1]
    answer_text = parts[2]
    
    # Ищем полный ID тикета
    ticket_id = None
    try:
        for filename in os.listdir(TICKETS_FOLDER):
            if filename.endswith('.json') and ticket_short in filename:
                ticket_id = filename.replace('.json', '')
                break
    except Exception as e:
        logger.error(f"Ошибка поиска файлов: {e}")
        await update.message.reply_text("❌ Ошибка при поиске тикета")
        return
    
    if not ticket_id:
        await update.message.reply_text(f"❌ Тикет с ID `{ticket_short}` не найден", parse_mode="Markdown")
        return
    
    ticket = get_ticket(ticket_id)
    if not ticket:
        await update.message.reply_text("❌ Тикет не найден")
        return
    
    if ticket.get("status") != "open":
        await update.message.reply_text("❌ Этот тикет уже закрыт")
        return
    
    admin_name = update.effective_user.username or update.effective_user.first_name
    
    try:
        await context.bot.send_message(
            ticket["user_id"],
            f"📢 **Ответ от администратора @{admin_name}**\n\n{answer_text}"
        )
        await update.message.reply_text(
            f"✅ **Ответ отправлен!**\n\n"
            f"👤 Игрок: @{ticket['username']}\n"
            f"📝 Тикет: `{ticket_short}`\n"
            f"💬 Ответ: {answer_text[:100]}",
            parse_mode="Markdown"
        )
        logger.info(f"Админ {admin_name} ответил в тикет {ticket_short}")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка отправки: {e}")

async def admin_close(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Закрыть тикет: /close ID"""
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("⛔ У вас нет прав для этой команды.")
        return
    
    parts = update.message.text.split()
    if len(parts) < 2:
        await update.message.reply_text(
            "❌ **Как закрыть тикет:**\n\n"
            "`/close ID_тикета`\n\n"
            "**Пример:**\n"
            "`/close 60320_140032`",
            parse_mode="Markdown"
        )
        return
    
    ticket_short = parts[1]
    
    ticket_id = None
    try:
        for filename in os.listdir(TICKETS_FOLDER):
            if filename.endswith('.json') and ticket_short in filename:
                ticket_id = filename.replace('.json', '')
                break
    except Exception as e:
        logger.error(f"Ошибка поиска: {e}")
        await update.message.reply_text("❌ Ошибка при поиске тикета")
        return
    
    if not ticket_id:
        await update.message.reply_text(f"❌ Тикет с ID `{ticket_short}` не найден", parse_mode="Markdown")
        return
    
    ticket = get_ticket(ticket_id)
    if not ticket:
        await update.message.reply_text("❌ Тикет не найден")
        return
    
    if close_ticket_db(ticket_id):
        await update.message.reply_text(f"✅ Тикет `{ticket_short}` закрыт!", parse_mode="Markdown")
        
        try:
            await context.bot.send_message(
                ticket["user_id"],
                f"🔒 **Ваш тикет #{ticket_short} закрыт администратором**\n\n"
                f"Спасибо за обращение!"
            )
        except:
            pass
        logger.info(f"Админ закрыл тикет {ticket_short}")
    else:
        await update.message.reply_text("❌ Ошибка закрытия тикета")

async def admin_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Список открытых тикетов: /tickets"""
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("⛔ У вас нет прав для этой команды.")
        return
    
    try:
        tickets = get_all_open_tickets()
        
        if not tickets:
            await update.message.reply_text("📭 Нет открытых тикетов")
            return
        
        msg = "📋 **Открытые тикеты:**\n\n"
        for t in tickets[:10]:
            try:
                date = datetime.fromisoformat(t.get("time")).strftime("%d.%m %H:%M")
                short_id = t['id'][-12:]
                msg += f"**#{short_id}** | {date}\n"
                msg += f"👤 @{t['username']}\n"
                msg += f"📝 {t['message'][:50]}...\n"
                msg += f"💬 `/msg {short_id} ответ`\n"
                msg += f"🔒 `/close {short_id}`\n\n"
            except Exception as e:
                logger.error(f"Ошибка форматирования тикета: {e}")
                continue
        
        await update.message.reply_text(msg, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Ошибка в admin_list: {e}")
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")

async def admin_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Помощь администратора: /adminhelp"""
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("⛔ У вас нет прав для этой команды.")
        return
    
    await update.message.reply_text(
        "👑 **Команды администратора**\n\n"
        "**📝 Ответить на тикет:**\n"
        "`/msg ID_тикета ваш ответ`\n"
        "Пример: `/msg 60320_140032 Привет!`\n\n"
        "**🔒 Закрыть тикет:**\n"
        "`/close ID_тикета`\n"
        "Пример: `/close 60320_140032`\n\n"
        "**📋 Список тикетов:**\n"
        "`/tickets`\n\n"
        "**❓ Эта справка:**\n"
        "`/adminhelp`\n\n"
        "**💡 Подсказка:**\n"
        "ID тикета - это последние 12 символов полного ID\n"
        "Пример: `60320_140032`",
        parse_mode="Markdown"
    )

# ============= ОБРАБОТКА ОШИБОК =============
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик ошибок"""
    logger.error(f"Ошибка: {context.error}")
    if update and update.effective_chat:
        try:
            await update.effective_chat.send_message("⚠️ Произошла ошибка. Попробуйте позже.")
        except:
            pass

# ============= ЗАПУСК БОТА =============
def main():
    print("\n" + "="*60)
    print("🚀 SUNDLOON SFERA - Бот поддержки Minecraft")
    print("="*60)
    print(f"👑 Администраторы:")
    print(f"   - @Poalaqss (ID: 7785643239)")
    print(f"   - @killeryourbrain1 (ID: 8409401563)")
    print(f"   - @Clawtr1ks (ID: 7623873942)")
    print("\n💡 Команды для админов:")
    print("   /msg ID текст - Ответить на тикет")
    print("   /close ID - Закрыть тикет")
    print("   /tickets - Список тикетов")
    print("   /adminhelp - Помощь")
    print("="*60 + "\n")
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Команды для игроков
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("cancel", cancel_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(button_callback))
    
    # Команды для админов
    app.add_handler(CommandHandler("tickets", admin_list))
    app.add_handler(CommandHandler("close", admin_close))
    app.add_handler(CommandHandler("msg", admin_msg))
    app.add_handler(CommandHandler("adminhelp", admin_help))
    
    # Обработка ошибок
    app.add_error_handler(error_handler)
    
    print("✅ Бот успешно запущен и готов к работе!\n")
    
    app.run_polling()

if __name__ == "__main__":
    main()