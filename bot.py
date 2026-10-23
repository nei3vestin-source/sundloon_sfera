import asyncio
import json
import logging
import sys
from datetime import datetime

import aiohttp
import discord
import redis.asyncio as redis
import yaml

# ===== Логирование =====
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("ProfiStaffChat")


# ===== Загрузка конфига =====
def load_config():
    try:
        with open("config.yml", "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        log.error("Файл config.yml не найден!")
        sys.exit(1)
    except yaml.YAMLError as e:
        log.error(f"Ошибка в config.yml: {e}")
        sys.exit(1)


CONFIG = load_config()

# ===== Каналы Redis =====
CHANNEL_MC_TO_DS = "staffchat:mc_to_ds"
CHANNEL_DS_TO_MC = "staffchat:ds_to_mc"
CHANNEL_EVENTS = "staffchat:events"

# ===== Discord клиент =====
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

client = discord.Client(intents=intents)

# ===== Глобальные переменные =====
redis_client: redis.Redis = None
http_session: aiohttp.ClientSession = None


# ======================================================
#                   УТИЛИТЫ
# ======================================================

def sanitize_discord(text: str) -> str:
    """Защита от @everyone, @here и обрезка длины"""
    text = text.replace("@everyone", "@ everyone")
    text = text.replace("@here", "@ here")
    if len(text) > 2000:
        text = text[:1997] + "..."
    return text


def get_avatar_url(uuid: str) -> str:
    """Получить URL головы скина игрока"""
    return f"https://mc-heads.net/avatar/{uuid}/128"


# ======================================================
#               ОТПРАВКА В DISCORD
# ======================================================

async def send_via_webhook(player: str, uuid: str, message: str):
    """Отправить сообщение через вебхук (с аватаркой игрока)"""
    webhook_url = CONFIG["discord"].get("webhook_url", "").strip()

    if not webhook_url:
        return False

    try:
        payload = {
            "username": player,
            "avatar_url": get_avatar_url(uuid),
            "content": sanitize_discord(message),
            "allowed_mentions": {"parse": []},
        }

        async with http_session.post(webhook_url, json=payload) as resp:
            if resp.status not in (200, 204):
                log.warning(f"Webhook вернул код {resp.status}")
                return False
        return True

    except Exception as e:
        log.error(f"Ошибка отправки webhook: {e}")
        return False


async def send_plain_message(player: str, message: str):
    """Запасной вариант - обычное сообщение от бота"""
    channel = client.get_channel(CONFIG["discord"]["channel_id"])
    if not channel:
        log.warning("Канал Discord не найден!")
        return

    text = sanitize_discord(f"**{player}**: {message}")
    try:
        await channel.send(text, allowed_mentions=discord.AllowedMentions.none())
    except Exception as e:
        log.error(f"Ошибка отправки в Discord: {e}")


async def send_mc_message_to_discord(player: str, uuid: str, message: str):
    """Отправить сообщение из Minecraft в Discord"""
    # Пробуем через вебхук, если не вышло - обычным сообщением
    success = await send_via_webhook(player, uuid, message)
    if not success:
        await send_plain_message(player, message)


# ======================================================
#               EMBED-УВЕДОМЛЕНИЯ
# ======================================================

async def send_embed(embed: discord.Embed):
    """Отправить embed в канал стафф-чата"""
    channel = client.get_channel(CONFIG["discord"]["channel_id"])
    if not channel:
        return
    try:
        await channel.send(embed=embed)
    except Exception as e:
        log.error(f"Ошибка отправки embed: {e}")


async def handle_event(data: dict):
    """Обработка событий (вход/выход/старт/стоп)"""
    event_type = data.get("type")
    server_name = CONFIG["settings"]["server_name"]

    if event_type == "staff_join":
        if not CONFIG["settings"].get("staff_join_leave_notify", True):
            return

        player = data["player"]
        uuid = data["uuid"]

        embed = discord.Embed(
            color=0x43B581,
            timestamp=datetime.utcnow(),
        )
        embed.set_author(
            name=f"{player} присоединился к серверу",
            icon_url=get_avatar_url(uuid),
        )
        embed.set_footer(text=server_name)
        await send_embed(embed)

    elif event_type == "staff_leave":
        if not CONFIG["settings"].get("staff_join_leave_notify", True):
            return

        player = data["player"]
        uuid = data["uuid"]

        embed = discord.Embed(
            color=0xF04747,
            timestamp=datetime.utcnow(),
        )
        embed.set_author(
            name=f"{player} покинул сервер",
            icon_url=get_avatar_url(uuid),
        )
        embed.set_footer(text=server_name)
        await send_embed(embed)

    elif event_type == "server_start":
        if not CONFIG["settings"].get("server_status_notify", True):
            return

        embed = discord.Embed(
            title="🟢 Сервер запущен",
            description=f"Сервер **{server_name}** успешно запущен и готов к работе!",
            color=0x43B581,
            timestamp=datetime.utcnow(),
        )
        embed.set_footer(text=server_name)
        await send_embed(embed)

    elif event_type == "server_stop":
        if not CONFIG["settings"].get("server_status_notify", True):
            return

        embed = discord.Embed(
            title="🔴 Сервер остановлен",
            description=f"Сервер **{server_name}** был остановлен.",
            color=0xF04747,
            timestamp=datetime.utcnow(),
        )
        embed.set_footer(text=server_name)
        await send_embed(embed)


# ======================================================
#               REDIS PUB/SUB
# ======================================================

async def redis_listener():
    """Слушаем Redis-каналы от Minecraft"""
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(CHANNEL_MC_TO_DS, CHANNEL_EVENTS)

    log.info(f"Подписка на Redis-каналы: {CHANNEL_MC_TO_DS}, {CHANNEL_EVENTS}")

    async for message in pubsub.listen():
        if message["type"] != "message":
            continue

        channel = message["channel"].decode("utf-8")
        try:
            data = json.loads(message["data"].decode("utf-8"))
        except json.JSONDecodeError:
            log.warning(f"Невалидный JSON от Minecraft: {message['data']}")
            continue

        try:
            if channel == CHANNEL_MC_TO_DS:
                await send_mc_message_to_discord(
                    data["player"],
                    data["uuid"],
                    data["message"],
                )
            elif channel == CHANNEL_EVENTS:
                await handle_event(data)
        except Exception as e:
            log.error(f"Ошибка обработки сообщения из Redis: {e}")


async def publish_to_minecraft(username: str, message: str):
    """Отправить сообщение в Minecraft через Redis"""
    payload = {
        "player": username,
        "message": message,
    }
    await redis_client.publish(CHANNEL_DS_TO_MC, json.dumps(payload, ensure_ascii=False))


# ======================================================
#               ОБРАБОТЧИКИ DISCORD
# ======================================================

@client.event
async def on_ready():
    activity_name = CONFIG["discord"].get("activity", "Minecraft")
    await client.change_presence(
        activity=discord.Activity(type=discord.ActivityType.watching, name=activity_name)
    )
    log.info(f"Бот залогинен как {client.user} (ID: {client.user.id})")
    log.info("Готов к работе!")


@client.event
async def on_message(message: discord.Message):
    # Игнорируем ботов и вебхуки
    if message.author.bot or message.webhook_id is not None:
        return

    # Только нужный канал
    if message.channel.id != CONFIG["discord"]["channel_id"]:
        return

    # Готовим контент
    content = message.clean_content.strip()
    if not content:
        if message.attachments:
            content = "[Вложение]"
        else:
            return

    if len(content) > 500:
        content = content[:497] + "..."

    # Имя автора (ник на сервере если есть)
    author_name = message.author.display_name

    # Публикуем в Redis
    await publish_to_minecraft(author_name, content)


# ======================================================
#                   ТОЧКА ВХОДА
# ======================================================

async def main():
    global redis_client, http_session

    # Подключение к Redis
    try:
        redis_client = redis.Redis(
            host=CONFIG["redis"]["host"],
            port=CONFIG["redis"]["port"],
            password=CONFIG["redis"].get("password") or None,
            db=CONFIG["redis"].get("db", 0),
        )
        await redis_client.ping()
        log.info(f"Подключение к Redis успешно: {CONFIG['redis']['host']}:{CONFIG['redis']['port']}")
    except Exception as e:
        log.error(f"Не удалось подключиться к Redis: {e}")
        sys.exit(1)

    # HTTP-сессия для вебхуков
    http_session = aiohttp.ClientSession()

    # Запускаем Redis-листенер в фоне
    asyncio.create_task(redis_listener())

    # Запускаем Discord-бота
    token = CONFIG["discord"]["token"]
    if not token or token == "ВСТАВЬ_НОВЫЙ_ТОКЕН_СЮДА":
        log.error("Токен Discord не указан в config.yml!")
        sys.exit(1)

    try:
        await client.start(token)
    finally:
        await http_session.close()
        await redis_client.aclose()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Бот остановлен.")
